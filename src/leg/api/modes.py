"""Area modes for the UI: snap the drawing to whole districts, or keep it as a free polygon.
Wraps leg.data.snap; previews never write area.json (only the fetch job's resolve_area does)."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
from shapely.geometry import mapping

import leg.data.snap as snap
from leg.data import Area, SnapshotCache
from leg.data.fetchers import REGISTRY
from leg.data.profile import _area_km2


class AreaModeIn(BaseModel):
    mode: str = "snap"                 # "snap" | "free"
    min_share: float = snap.DEFAULT_MIN_SHARE
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class ModeError(ValueError):
    """Bad mode input (unknown district id, min_share out of range...): a 400, not a state."""


def check_mode(m: AreaModeIn) -> None:
    if m.mode not in ("snap", "free"):
        raise ModeError("mode must be 'snap' or 'free'")
    if not 0 < m.min_share <= 1:
        raise ModeError("min_share must be more than 0 and at most 1")


def _km2(geom) -> float:
    return round(_area_km2(Area("x", "ISR", geom)), 1)


def preview(drawn: Area, m: AreaModeIn, cache: SnapshotCache, bopts: dict, refresh: bool = False) -> dict:
    """What the area will be, without writing area.json. Snap mode fetches the drawing's districts
    (cached after the first time). Nothing reaching min_share is a state (ok: False), not an error."""
    check_mode(m)
    out = {"mode": m.mode, "drawn_area_id": drawn.area_id, "drawn_km2": _km2(drawn.geometry),
           "min_share": m.min_share, "districts": [], "error": None}
    if m.mode == "free":
        return out | {"ok": True, "area_id": drawn.area_id, "km2": out["drawn_km2"],
                      "geojson": mapping(drawn.geometry), "area": drawn}
    try:
        bsnap = cache.get(REGISTRY["boundaries"](**bopts), drawn, refresh=refresh)
        feats = snap.touched_districts(bsnap)
    except Exception as e:  # network, provider, old snapshot: say so, the UI offers retry
        return out | {"ok": False, "area_id": None, "km2": None, "geojson": None, "area": None,
                      "error": {"code": "boundaries_failed", "message": f"{type(e).__name__}: {e}"}}
    out["boundaries_snapshot"] = bsnap.id
    try:
        result = snap.snap_area(drawn, bsnap, m.min_share, m.include, m.exclude)
    except ValueError as e:
        if not str(e).startswith("no district"):
            raise ModeError(str(e))
        choices = {}  # what snap_area would have said, for the list and the map
        for f in feats:
            p = f["properties"]
            uid, share = p["unit_id"], float(p["share_inside_area"])
            inc = uid in m.include and uid not in m.exclude
            why = "removed by user" if uid in m.exclude else "added by user" if inc else "minority"
            choices[uid] = (inc, why)
        out["error"] = {"code": "no_district_qualifies", "message": str(e)}
        area = None
    else:
        choices = {d.unit_id: (d.included, d.reason) for d in result.districts}
        area = result.area
    rows = []
    for f in feats:
        p = f["properties"]
        inc, why = choices[p["unit_id"]]
        rows.append({"unit_id": p["unit_id"], "name": p.get("name"), "share_inside_area": float(p["share_inside_area"]),
                     "fully_inside": bool(p.get("fully_inside")), "included": inc, "reason": why,
                     "geometry": f["geometry"]})
    rows.sort(key=lambda r: (not r["included"], -r["share_inside_area"]))
    return out | {"ok": area is not None, "districts": rows, "area": area,
                  "area_id": area.area_id if area else None, "km2": _km2(area.geometry) if area else None,
                  "geojson": mapping(area.geometry) if area else None}


def read_record(folder: Path) -> dict | None:
    p = folder / snap.AREA_RECORD
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def restore_fields(rec: dict) -> dict:
    """What a saved area needs to be reopened as it was made: drawing, mode, rule, user choices."""
    out = {"mode": rec.get("mode"), "drawn_geojson": rec.get("drawn_area"), "drawn_area_id": rec.get("drawn_area_id"),
           "min_share": rec.get("min_share", snap.DEFAULT_MIN_SHARE), "include": [], "exclude": [],
           "level_override": rec.get("level_override"), "level_choice": rec.get("level_choice")}
    for d in rec.get("districts", []):
        if d.get("reason") == "added by user":
            out["include"].append(d["unit_id"])
        elif d.get("reason") == "removed by user":
            out["exclude"].append(d["unit_id"])
    if out["drawn_geojson"] and out["mode"] == "free":
        out["drawn_area_id"] = None
    return out

