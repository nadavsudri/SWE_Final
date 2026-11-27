"""Thin HTTP layer over leg.data for the fetcher UI. No business logic: it validates input, calls
leg.data, and reports what came back. Run with `python -m leg.api`."""
from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

import pycountry
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import leg.data as data
from leg.data import SnapshotCache
from leg.data.cache import MANIFEST
from leg.data.fetchers import REGISTRY
from leg.llm import claude
from leg.api import areas as areas_mod
import leg.data.levels as data_levels
from leg.api import levels as levels_api
from leg.api import modes
from leg.api import sources as sources_mod
from leg.api.jobs import Job, JobManager
from leg.api.advice import AdviceManager, set_view
from leg.api.prep import PrepJob, PrepManager
from leg.prep import PrepParams
from leg.api.settings import Settings

SERVED_FILES = {"districts.geojson", "facilities.geojson", MANIFEST}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class AreaIn(BaseModel):
    name: str = ""
    iso3: str = ""
    geojson: dict | str | None = None


class ProfileIn(BaseModel):
    area: AreaIn
    refresh: bool = False


class LevelIn(BaseModel):
    provider: str
    level: str


class LevelsIn(BaseModel):
    area: AreaIn
    area_mode: modes.AreaModeIn = Field(default_factory=modes.AreaModeIn)


class PlanIn(BaseModel):
    area: AreaIn
    options: dict[str, dict] = Field(default_factory=dict)
    area_mode: modes.AreaModeIn = Field(default_factory=lambda: modes.AreaModeIn(mode="free"))
    level_override: LevelIn | None = None


class SnapIn(BaseModel):
    area: AreaIn
    options: dict[str, dict] = Field(default_factory=dict)
    area_mode: modes.AreaModeIn = Field(default_factory=modes.AreaModeIn)
    level_override: LevelIn | None = None
    refresh: bool = False


class AdviceIn(BaseModel):
    filename: str
    text: str
    area_id: str
    run_id: str
    budget: int = 10


class PrepIn(BaseModel):
    area_id: str
    pinned: dict[str, str] = Field(default_factory=dict)
    years: list[int] | None = None
    max_minutes: float = 120.0
    min_population: float = 10.0


class FetchIn(BaseModel):
    area: AreaIn
    area_mode: modes.AreaModeIn = Field(default_factory=lambda: modes.AreaModeIn(mode="free"))
    level_override: LevelIn | None = None
    sources: list[str] = Field(default_factory=lambda: list(REGISTRY))
    refresh: bool = False
    pinned: dict[str, str] = Field(default_factory=dict)
    options: dict[str, dict] = Field(default_factory=dict)


def create_app(settings: Settings | None = None, static_dir: Path | None = None, advice_llm=None) -> FastAPI:
    settings = settings or Settings.from_env()
    cache = SnapshotCache(settings.root)
    borders = areas_mod.CountryBorders(settings.root)
    jobs = JobManager(cache)
    level_jobs = levels_api.LevelManager(cache)
    prep_jobs = PrepManager(settings.root, settings.processed_root)
    advice_jobs = AdviceManager(settings.advice_root, settings.processed_root, advice_llm)
    app = FastAPI(title="LEG data fetcher", docs_url="/api/docs", openapi_url="/api/openapi.json")

    def key_present() -> bool:
        return claude.load_api_key(settings.env_file) is not None  # never returned or logged

    def area_or_400(a: AreaIn):
        area, errors = areas_mod.parse_area(a.name, a.iso3, a.geojson)
        if area is None:
            raise HTTPException(400, {"errors": errors})
        return area

    def profile_view(profile, note: str = "") -> dict:
        status = "llm" if profile.source == "llm" else ("default_llm_failed" if key_present() else "default_no_key")
        return profile.to_json() | {"status": status, "note": note.strip(),
                                    "fetcher_options": {k: {kk: list(vv) if isinstance(vv, tuple) else vv
                                                            for kk, vv in v.items()}
                                                        for k, v in profile.fetcher_options().items()}}

    def resolve(area, refresh=False):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):  # resolve_profile prints its fallback reason
            profile = data.resolve_profile(area, settings.root, refresh=refresh)
        return profile, out.getvalue()

    @app.get("/api/config")
    def config():
        return {"cache_root": str(settings.root), "llm_key_present": key_present(),
                "warn_km2": settings.warn_km2, "max_km2": settings.max_km2}

    @app.get("/api/countries")
    def countries():
        rows = [{"name": getattr(c, "common_name", c.name), "iso3": c.alpha_3} for c in pycountry.countries]
        return sorted(rows, key=lambda r: r["name"])

    @app.get("/api/areas")
    def list_areas():
        return areas_mod.saved_areas(settings.root)

    @app.post("/api/area/validate")
    def validate(a: AreaIn):
        area, errors = areas_mod.parse_area(a.name, a.iso3, a.geojson)
        if area is None:
            return {"ok": False, "errors": [{"code": "invalid", "message": m} for m in errors], "warnings": []}
        res = areas_mod.check_area(area, borders, settings.warn_km2, settings.max_km2)
        # the name is part of the cache folder: report cached areas with this exact shape and country
        digest = area.area_id.rsplit("_", 1)[-1]
        same = sorted(d.name for d in settings.root.iterdir()
                      if d.is_dir() and d.name.startswith(f"{area.iso3.lower()}_") and d.name.endswith(f"_{digest}")) \
            if settings.root.exists() else []
        return res | {"ok": not res["errors"], "same_shape": same}

    @app.post("/api/profile")
    def profile(p: ProfileIn):
        area = area_or_400(p.area)
        if p.refresh and not key_present():
            raise HTTPException(400, {"errors": ["No LLM key: add ANTHROPIC_API_KEY to .env and restart."]})
        prof, note = resolve(area, p.refresh)
        return profile_view(prof, note)

    def level_choice(drawn, m: modes.AreaModeIn, override: LevelIn | None):
        """The rule's level (from a finished level job, else choose_level on the cached probes) and
        the level that will be used: the user's override when given."""
        choice = level_jobs.done_choice(drawn, m.mode, m.min_share) or \
            data_levels.choose_level(drawn, cache, m.mode, m.min_share)
        if override is not None:
            ok = any(c.available and c.provider == override.provider and c.level == override.level for c in choice.counts)
            if not ok:
                raise modes.ModeError(f"level {override.provider} {override.level} isn't available for this area")
            return choice, {"provider": override.provider, "level": override.level}, "override"
        return choice, {"provider": choice.provider, "level": choice.level}, "rule"

    def with_level(options: dict, bopts: dict) -> dict:
        """User options with the chosen level as the Districts source's provider and level."""
        out = {k: dict(v) for k, v in (options or {}).items()}
        out["boundaries"] = {**out.get("boundaries", {}), "provider": bopts["provider"], "levels": list(bopts["levels"])}
        return out

    def preview_or_400(area, m: modes.AreaModeIn, options: dict, override: LevelIn | None = None, refresh=False) -> dict:
        prof, _ = resolve(area)
        try:
            modes.check_mode(m)
            try:
                choice, lvl, source = level_choice(area, m, override)
            except modes.ModeError:
                raise
            except Exception as e:  # nothing usable at any level, or the probes can't be fetched
                code = "no_level" if isinstance(e, ValueError) else "levels_failed"
                msg = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
                return {"ok": False, "mode": m.mode, "drawn_area_id": area.area_id, "drawn_km2": modes._km2(area.geometry),
                        "area_id": None, "km2": None, "geojson": None, "area": None, "min_share": m.min_share,
                        "districts": [], "level": None, "error": {"code": code, "message": msg},
                        "_profile": prof, "_bopts": {}, "_choice": None}
            bopts = levels_api.options_for(lvl["provider"], lvl["level"])
            r = modes.preview(area, m, cache, bopts, refresh)
        except modes.ModeError as e:
            raise HTTPException(400, {"errors": [str(e)]})
        level = {**lvl, "source": source, "in_range": choice.in_range, "reason": choice.reason}
        return r | {"level": level, "_profile": prof, "_bopts": bopts, "_choice": choice}

    @app.post("/api/area/levels")
    def start_levels(p: LevelsIn):
        """Count usable districts per level (choose_level) in the background; poll for progress."""
        drawn = area_or_400(p.area)
        try:
            modes.check_mode(p.area_mode)
        except modes.ModeError as e:
            raise HTTPException(400, {"errors": [str(e)]})
        return level_jobs.start(drawn, p.area_mode.mode, p.area_mode.min_share).view()

    @app.get("/api/area/levels/{job_id}")
    def levels_status(job_id: str):
        job = level_jobs.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, {"errors": ["Unknown level count (the server restarted): start it again."]})
        return job.view()

    def size_errors(area) -> list[str]:
        return [e["message"] for e in areas_mod.check_area(area, borders, settings.warn_km2, settings.max_km2)["errors"]]

    @app.post("/api/area/snap")
    def snap_preview(p: SnapIn):
        """The area the fetch will use: snapped to whole districts (or the drawing, in free mode)."""
        drawn = area_or_400(p.area)
        r = preview_or_400(drawn, p.area_mode, p.options, p.level_override, p.refresh)
        target = r.pop("area")
        r.pop("_profile"); r.pop("_bopts"); r.pop("_choice")
        checks = areas_mod.check_area(target, borders, settings.warn_km2, settings.max_km2) if target else {"warnings": [], "errors": []}
        return r | {"warnings": checks["warnings"], "size_errors": checks["errors"]}

    @app.get("/api/sources")
    def sources():
        return sources_mod.describe()

    @app.post("/api/snapshots")
    def snapshots(p: PlanIn):
        """The plan for the area the fetch will really use (the snapped one in snap mode)."""
        drawn = area_or_400(p.area)
        r = preview_or_400(drawn, p.area_mode, p.options, p.level_override)
        if not r["ok"]:
            raise HTTPException(409, {"errors": [r["error"]["message"]], "code": r["error"]["code"]})
        return sources_mod.plan(r["area"], cache, r["_profile"].fetcher_options(), with_level(p.options, r["_bopts"]))

    @app.post("/api/fetch")
    def fetch(p: FetchIn):
        drawn = area_or_400(p.area)
        # limits, plan and order refer to the area the fetch will use; the job resolves it for real
        pre = preview_or_400(drawn, p.area_mode, p.options, p.level_override)
        if not pre["ok"]:
            raise HTTPException(400, {"errors": [pre["error"]["message"]]})
        area = pre["area"]
        if errs := size_errors(area):
            raise HTTPException(400, {"errors": errs})
        unknown = [s for s in p.sources if s not in REGISTRY]
        if unknown or not p.sources:
            raise HTTPException(400, {"errors": [f"Unknown sources: {unknown}" if unknown else "Include at least one source."]})
        prof = pre["_profile"]
        eff = with_level(p.options, pre["_bopts"])  # the Districts source fetches the chosen level
        options, errs = {}, {}
        for s in p.sources:
            kw, e = sources_mod.normalize(s, eff.get(s), prof.fetcher_options().get(s))
            options[s] = kw
            if e:
                errs[s] = e
        if errs:
            raise HTTPException(400, {"errors": errs})
        for s, sid in p.pinned.items():
            if s not in p.sources:
                continue
            try:
                cache.pinned(area, s, sid)
            except FileNotFoundError as e:
                raise HTTPException(400, {"errors": [str(e)]})
        if (busy := jobs.busy()) is not None:
            raise HTTPException(409, {"errors": ["Another fetch is still running."], "job_id": busy.id})
        plan = sources_mod.plan(area, cache, prof.fetcher_options(), eff)
        # Cached and pinned sources first: the fast answers arrive first, and Overpass gets one query at a time.
        order = sorted(p.sources, key=lambda s: 0 if (s in p.pinned or (not p.refresh and plan[s]["decision"] == "reuse")) else 1)
        job = Job(drawn, p.sources, p.refresh, {s: v for s, v in p.pinned.items() if s in p.sources}, options,
                  mode=p.area_mode.model_dump(), check=size_errors,
                  level_override=p.level_override.model_dump() if p.level_override else None)
        job.profile = prof
        jobs.start(job, order)
        return {"job_id": job.id, "order": order}

    @app.get("/api/fetch/{job_id}")
    def job_status(job_id: str):
        job = jobs.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, {"errors": ["This fetch is unknown: the server was restarted. Finished snapshots are saved."]})
        return job.view()

    @app.post("/api/fetch/{job_id}/retry/{source}")
    def retry(job_id: str, source: str):
        job = jobs.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, {"errors": ["Unknown fetch."]})
        if jobs.busy() is not None:
            raise HTTPException(409, {"errors": ["A fetch is still running; retry when it finishes."]})
        if source == "area":
            if job.area_step["status"] != "failed":
                raise HTTPException(400, {"errors": ["The area step did not fail."]})
            jobs.retry_area(job)
            return job.view()
        if source not in job.sources:
            raise HTTPException(404, {"errors": [f"{source} is not part of this fetch."]})
        if job.sources[source]["status"] != "failed":
            raise HTTPException(400, {"errors": [f"{source} did not fail."]})
        jobs.retry(job, source)
        return job.view()

    @app.post("/api/prep")
    def start_prep(p: PrepIn):
        if not _ID.match(p.area_id) or not (settings.root / p.area_id / "area.json").is_file():
            raise HTTPException(404, {"errors": ["Unknown area: fetch it first."]})
        try:
            params = PrepParams(min_population=p.min_population, max_minutes=p.max_minutes,
                                keep_minutes=p.max_minutes)
        except ValueError as e:
            raise HTTPException(400, {"errors": [str(e)]})
        if jobs.busy() is not None:
            raise HTTPException(409, {"errors": ["A fetch is still running; preprocess when it finishes."]})
        if (busy := prep_jobs.busy()) is not None:
            raise HTTPException(409, {"errors": ["Preprocessing is already running."], "job_id": busy.id})
        job = prep_jobs.start(PrepJob(p.area_id, p.pinned, params, p.years))
        return {"job_id": job.id}

    @app.get("/api/prep/area/{area_id}")
    def prep_runs(area_id: str):
        if not _ID.match(area_id):
            raise HTTPException(404, "Not found")
        return {"area_id": area_id, "runs": prep_jobs.runs(area_id)}

    @app.get("/api/prep/{job_id}")
    def prep_status(job_id: str):
        job = prep_jobs.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, {"errors": ["This run is unknown: the server was restarted. Finished runs are saved."]})
        return job.view()

    @app.post("/api/advice")
    def start_advice(a: AdviceIn):
        if (busy := advice_jobs.busy()) is not None:
            raise HTTPException(409, {"errors": ["Advice is already being scored."], "job_id": busy.id})
        try:
            job = advice_jobs.create(a.filename, a.text, a.area_id, a.run_id, a.budget)
        except FileNotFoundError as e:
            raise HTTPException(404, {"errors": [str(e)]})
        except (ValueError, RuntimeError) as e:
            raise HTTPException(400, {"errors": [str(e)]})
        return {"job_id": advice_jobs.start(job).id}

    @app.get("/api/advice")
    def advice_sets():
        from leg import advice as adv
        return {"sets": adv.list_sets(settings.advice_root)}

    @app.get("/api/advice/jobs/{job_id}")
    def advice_status(job_id: str):
        job = advice_jobs.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, {"errors": ["This job is unknown: the server was restarted. Saved sets are listed at /api/advice."]})
        return job.view(settings.advice_root)

    def _advice_dir(key: str):
        try:
            return advice_jobs.set_dir(key)
        except FileNotFoundError as e:
            raise HTTPException(404, {"errors": [str(e)]})

    @app.get("/api/advice/{key}")
    def advice_set(key: str):
        return set_view(_advice_dir(key))

    @app.post("/api/advice/{key}/approve")
    def advice_approve(key: str):
        from leg import advice as adv
        d = _advice_dir(key)
        adv.approve_dir(d)
        return set_view(d)

    @app.post("/api/advice/{key}/recheck")
    def advice_recheck(key: str):
        from leg import advice as adv
        d = _advice_dir(key)
        if advice_jobs.busy() is not None:
            raise HTTPException(409, {"errors": ["Advice is being scored; try again when it finishes."]})
        adv.recheck_dir(d)
        return set_view(d)

    @app.get("/api/snapshot/{area_id}/{source}/{snapshot_id}/{file}")
    def snapshot_file(area_id: str, source: str, snapshot_id: str, file: str):
        if file not in SERVED_FILES or source not in REGISTRY or not (_ID.match(area_id) and _ID.match(snapshot_id)):
            raise HTTPException(404, "Not found")
        root = settings.root.resolve()
        path = (root / area_id / source / snapshot_id / file).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="application/json")

    if static_dir is not None and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
    return app


__all__ = ["create_app", "Settings"]
