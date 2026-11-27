"""Run preprocessing for an area the fetcher already prepared (data/raw/<area_id>/ with area.json).

Used by the CLI (python -m leg.prep) and the UI's preprocessing job.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from shapely import union_all
from shapely.geometry import shape

from leg.data import Area, Snapshot, SnapshotCache
from leg.data.cache import MANIFEST
from leg.data.snap import AREA_RECORD
from leg.prep import PrepParams, Progress, build

REQUIRED = ["worldpop", "boundaries", "friction"]
OPTIONAL = ["osm_facilities", "public_facilities"]


def snapshots(root: Path, area_id: str, source: str) -> list[Snapshot]:
    d = Path(root) / area_id / source
    snaps = [Snapshot(p, json.loads((p / MANIFEST).read_text()))
             for p in (d.iterdir() if d.exists() else []) if not p.name.startswith(".") and (p / MANIFEST).exists()]
    return sorted(snaps, key=lambda s: s.fetched_at)


def pick(root: Path, area_id: str, source: str, pinned: dict) -> Snapshot | None:
    snaps = snapshots(root, area_id, source)
    if source in pinned:
        hit = [s for s in snaps if s.id == pinned[source]]
        if not hit:
            raise FileNotFoundError(f"No {source} snapshot {pinned[source]!r} in {area_id}")
        return hit[0]
    return snaps[-1] if snaps else None


def chosen_level(record: dict) -> tuple[str, str] | None:
    """(provider, level) the fetch used, from area.json: the user's override, else the rule's choice."""
    for key in ("level_override", "level_choice"):
        v = record.get(key)
        if isinstance(v, dict) and v.get("level"):
            return v.get("provider", "geoboundaries"), str(v["level"])
    return None


def pick_boundaries(root: Path, area_id: str, record: dict, pinned: dict) -> Snapshot | None:
    """The planning-level snapshot. In free mode the folder also holds the level rule's probes of
    other levels, so match the recorded level instead of taking the newest."""
    if "boundaries" in pinned:
        return pick(root, area_id, "boundaries", pinned)
    lvl = chosen_level(record)
    snaps = snapshots(root, area_id, "boundaries")
    if lvl:
        match = [s for s in snaps if (s.manifest.get("params", {}).get("provider", "geoboundaries"),
                                      (s.manifest.get("params", {}).get("levels") or [""])[-1]) == lvl]
        if match:
            return match[-1]
    return snaps[-1] if snaps else None


def area_geometry(root: Path, area_id: str, record: dict, boundaries: Snapshot):
    """free: the drawing; snap: the whole districts kept (the boundaries snapshot of the snapped area)."""
    if record.get("mode") == "free":
        return shape(record["drawn_area"]["geometry"])
    feats = json.loads((boundaries.path / "districts.geojson").read_text())["features"]
    return union_all([shape(f["geometry"]) for f in feats])


def parent_snapshots(root: Path, record: dict, boundaries: Snapshot, fetch: bool = True,
                     warn=print) -> list[Snapshot]:
    """Boundaries of the two levels above the planning level (coarsest first), for ADM1/ADM2.
    Reuses the probes the level rule cached for the drawing; fetches a missing one if allowed.
    Only for geoBoundaries ADMk levels; OSM levels get the country code as ADM1."""
    p = boundaries.manifest.get("params", {})
    level = (p.get("levels") or [""])[-1]
    if p.get("provider", "geoboundaries") != "geoboundaries" or not re.fullmatch(r"ADM[2-5]", level):
        return []
    k = int(level[3])
    drawn_feat = record["drawn_area"]
    drawn = Area.from_geojson(drawn_feat["properties"].get("name", "area"),
                              drawn_feat["properties"]["iso3"], drawn_feat)
    out = []
    for lv in [f"ADM{j}" for j in range(max(1, k - 2), k)]:
        found = [s for s in snapshots(root, drawn.area_id, "boundaries")
                 if s.manifest.get("params", {}).get("levels") == [lv]
                 and s.manifest.get("params", {}).get("provider", "geoboundaries") == "geoboundaries"]
        if found:
            out.append(found[-1])
        elif fetch:
            from leg.data.fetchers import BoundariesFetcher
            try:
                out.append(SnapshotCache(root).get(BoundariesFetcher(levels=(lv,)), drawn))
            except Exception as e:  # parents only label rows; never block preprocessing on them
                warn(f"WARNING: could not get {lv} for the ADM1/ADM2 columns: {type(e).__name__}: {e}")
    return out


def prepare(area_id: str, root: Path | str = "data/raw", out: Path | str = "data/processed",
            pinned: dict | None = None, params: PrepParams = PrepParams(), years: list[int] | None = None,
            progress: Progress | None = None, fetch_parents: bool = True, warn=print) -> Path:
    root, pinned = Path(root), pinned or {}
    rec_path = root / area_id / AREA_RECORD
    if not rec_path.exists():
        raise FileNotFoundError(f"{rec_path} not found: fetch the area first (python -m leg.data fetch ...)")
    record = json.loads(rec_path.read_text())

    snaps = {s: pick(root, area_id, s, pinned) for s in REQUIRED + OPTIONAL}
    snaps["boundaries"] = pick_boundaries(root, area_id, record, pinned)
    missing = [s for s in REQUIRED if snaps[s] is None]
    if missing:
        raise FileNotFoundError(f"Missing data for {area_id}: {', '.join(missing)}. Fetch "
                                f"{'it' if len(missing) == 1 else 'them'} first "
                                f"(python -m leg.data fetch ... --sources {','.join(missing)})")
    worldpop = snaps["worldpop"]
    if years:
        by_year = {}
        for s in snapshots(root, area_id, "worldpop"):
            by_year[int(s.manifest.get("params", {}).get("year", 0))] = s  # newest per year wins
        lacking = [y for y in years if y not in by_year]
        if lacking:
            raise FileNotFoundError(f"No WorldPop snapshot for {lacking}; fetch with --year")
        worldpop = [by_year[y] for y in years]

    facilities = [snaps[s] for s in OPTIONAL if snaps[s] is not None]
    geom = area_geometry(root, area_id, record, snaps["boundaries"])
    parents = parent_snapshots(root, record, snaps["boundaries"], fetch_parents, warn)
    iso3 = record["drawn_area"]["properties"].get("iso3") or area_id.split("_")[0]
    return build(worldpop, snaps["boundaries"], facilities, snaps["friction"], geom, out, area_id,
                 params, parents, iso3, progress)
