"""Background fetch jobs: one fetch_all call per source, so each source reports its own status."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

import leg.data as data
import leg.data.levels as data_levels
import leg.data.snap as snap
from leg.data import Area, SnapshotCache
from leg.data.profile import _area_km2


def _snapshot_view(snap) -> dict:
    m = snap.manifest
    return {"snapshot_id": snap.id, "path": str(snap.path), "fetched_at": m.get("fetched_at"),
            "summary": m.get("summary", {}), "params": m.get("params", {}), "urls": m.get("urls", []),
            "files": {k: v.get("bytes") for k, v in m.get("files", {}).items()}}


class Job:
    def __init__(self, area: Area, sources: list[str], refresh: bool, pinned: dict, options: dict,
                 mode: dict | None = None, level_override: dict | None = None, check=None):
        self.id = uuid.uuid4().hex[:12]
        # `area` is the drawing; the area step replaces it with what resolve_area returns
        self.drawn, self.area, self.refresh, self.pinned, self.options = area, area, refresh, pinned, options
        self.mode = mode or {"mode": "free", "min_share": snap.DEFAULT_MIN_SHARE, "include": [], "exclude": []}
        self.level_override = level_override  # {"provider", "level"} replacing the rule's choice
        self.check = check  # area -> list of blocking size errors, applied to the resolved area
        self.area_step = {"status": "queued", "error": None, "area_id": None, "km2": None, "included": None,
                          "level": None, "started": None, "ended": None}
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.profile = None
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.sources = {s: {"source": s, "status": "queued", "attempts": 0, "error": None,
                            "started": None, "ended": None, "result": None} for s in sources}

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def view(self) -> dict:
        now = time.time()
        with self.lock:
            rows = []
            for r in self.sources.values():
                row = {k: v for k, v in r.items() if k not in ("started", "ended")}
                if r["started"]:
                    row["elapsed_s"] = round((r["ended"] or now) - r["started"], 1)
                rows.append(row)
        counts = {k: sum(r["status"] == k for r in rows) for k in ("queued", "running", "reused", "done", "failed")}
        a = self.area_step
        area = {k: v for k, v in a.items() if k not in ("started", "ended")} | {
            "mode": self.mode["mode"], "drawn_area_id": self.drawn.area_id,
            "drawn_km2": round(_area_km2(self.drawn), 1),
            "elapsed_s": round((a["ended"] or now) - a["started"], 1) if a["started"] else None}
        return {"job_id": self.id, "area_id": self.area.area_id, "created_at": self.created_at, "area": area,
                "running": self.running, "refresh": self.refresh, "pinned": self.pinned,
                "profile_source": getattr(self.profile, "source", None), "counts": counts, "sources": rows}


class JobManager:
    def __init__(self, cache: SnapshotCache):
        self.cache = cache
        self.jobs: dict[str, Job] = {}

    def busy(self) -> Job | None:
        return next((j for j in self.jobs.values() if j.running), None)

    def start(self, job: Job, order: list[str]) -> Job:
        self.jobs[job.id] = job
        job.thread = threading.Thread(target=self._run, args=(job, order), daemon=True)
        job.thread.start()
        return job

    def retry(self, job: Job, source: str) -> None:
        with job.lock:
            job.sources[source].update(status="queued", error=None, result=None)
        job.thread = threading.Thread(target=self._run, args=(job, [source]), daemon=True)
        job.thread.start()

    def retry_area(self, job: Job) -> None:
        """The area step failed, so nothing was fetched: run the whole job again."""
        with job.lock:
            job.area_step.update(status="queued", error=None)
            for r in job.sources.values():
                r.update(status="queued", error=None, result=None)
        job.thread = threading.Thread(target=self._run, args=(job, list(job.sources)), daemon=True)
        job.thread.start()

    def _resolve(self, job: Job) -> bool:
        """resolve_area first (snap writes area.json); every source then uses the area it returns."""
        a = job.area_step
        if a["status"] == "done":
            return True
        with job.lock:
            a.update(status="running", started=time.time(), ended=None, error=None)
        m = job.mode
        try:
            # the district level first (rule, or the user's override); resolve_area and the Districts
            # source then use that same level, and area.json records both
            choice = data_levels.choose_level(job.drawn, self.cache, m["mode"], m["min_share"])
            lvl = job.level_override or {"provider": choice.provider, "level": choice.level}
            bopts = {"provider": lvl["provider"], "levels": (lvl["level"],)}
            job.options["boundaries"] = {**job.options.get("boundaries", {}), **bopts}
            extra = {"level_choice": choice.to_json(), "level_override": job.level_override}
            area, result = snap.resolve_area(job.drawn, m["mode"], self.cache, bopts, m["min_share"],
                                             m["include"], m["exclude"], refresh=job.refresh, extra=extra)
            problems = job.check(area) if job.check else []
            if problems:
                raise ValueError(" ".join(problems))
        except Exception as e:
            with job.lock:
                a.update(status="failed", ended=time.time(), error=f"{type(e).__name__}: {e}")
                for r in job.sources.values():
                    r.update(status="failed", error="Not fetched: the area step failed.")
            return False
        with job.lock:
            job.area = area
            a.update(status="done", ended=time.time(), area_id=area.area_id, km2=round(_area_km2(area), 1),
                     included=result.included if result else None,
                     level={**lvl, "source": "override" if job.level_override else "rule", "in_range": choice.in_range})
        return True

    def _run(self, job: Job, order: list[str]) -> None:
        if not self._resolve(job):
            return
        if job.profile is None:
            try:
                job.profile = data.resolve_profile(job.area, self.cache.root)
            except Exception:
                job.profile = data.DEFAULT_PROFILE
        for src in order:
            row = job.sources[src]
            with job.lock:
                row.update(status="running", started=time.time(), ended=None, error=None)
                row["attempts"] += 1
            pin = job.pinned.get(src)
            try:
                res = data.fetch_all(job.area, sources=[src], cache=self.cache, refresh=job.refresh,
                                     pinned={src: pin} if pin else None, options=job.options,
                                     profile=job.profile)[src]
            except Exception as e:  # fetch_all reports per source; this guards the unexpected
                res = e
            with job.lock:
                row["ended"] = time.time()
                if isinstance(res, Exception):
                    row.update(status="failed", error=f"{type(res).__name__}: {res}")
                else:
                    reused = bool(pin) or res.fetched_at.timestamp() < row["started"] - 1
                    row.update(status="reused" if reused else "done", result=_snapshot_view(res))
