"""Snap a drawn area to whole districts.

The paper plans over whole administrative districts: every candidate cell belongs to exactly one
district, and expert advice refers to districts by name. A free polygon cuts districts in half,
so by default the drawn area is replaced by the union of the districts it mostly covers.

Rule (majority): a district is included when at least `min_share` (default 50%) of its area lies
inside the drawn polygon. The user can then add or remove single districts by unit_id.

Free-polygon mode keeps the drawing as is; districts carry `fully_inside`, and expert advice is
then applied only to districts that the polygon covers completely.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import unary_union

from leg.data.area import Area
from leg.data.cache import Snapshot, SnapshotCache

DEFAULT_MIN_SHARE = 0.5
AREA_RECORD = "area.json"


@dataclass
class DistrictChoice:
    unit_id: str
    name: str | None
    share_inside_area: float      # part of the district inside the drawn polygon
    included: bool
    reason: str                   # "majority" | "minority" | "added by user" | "removed by user"


@dataclass
class SnapResult:
    area: Area                    # the snapped area (union of included districts)
    drawn: Area                   # what the user drew
    min_share: float
    districts: list[DistrictChoice] = field(default_factory=list)

    @property
    def included(self) -> list[str]:
        return [d.unit_id for d in self.districts if d.included]

    def record(self) -> dict:
        return {"mode": "snap", "rule": f"district included when >= {self.min_share:.0%} of it is inside the drawing",
                "min_share": self.min_share, "drawn_area": self.drawn.to_geojson(),
                "drawn_area_id": self.drawn.area_id,
                "districts": [asdict(d) for d in self.districts],
                "created_at": datetime.now(timezone.utc).isoformat()}


def touched_districts(boundaries: Snapshot) -> list[dict]:
    """Every district the drawing touches, with its whole shape and share_inside_area (GeoJSON
    features). Lets a UI show the choices, including when no district reaches the threshold."""
    path = boundaries.path / "districts_full.geojson"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: this boundaries snapshot predates snapping; "
                                f"fetch boundaries again")
    return json.loads(path.read_text())["features"]


def snap_area(drawn: Area, boundaries: Snapshot, min_share: float = DEFAULT_MIN_SHARE,
              include: list[str] | tuple = (), exclude: list[str] | tuple = ()) -> SnapResult:
    """Union of the districts that are at least `min_share` inside `drawn`, plus `include`,
    minus `exclude` (both lists of unit_id). `boundaries` must be a snapshot fetched for `drawn`."""
    if not 0 < min_share <= 1:
        raise ValueError("min_share must be in (0, 1]")
    feats = touched_districts(boundaries)
    known = {f["properties"]["unit_id"] for f in feats}
    unknown = (set(include) | set(exclude)) - known
    if unknown:
        raise ValueError(f"unknown district ids: {sorted(unknown)}")
    both = set(include) & set(exclude)
    if both:
        raise ValueError(f"districts both added and removed: {sorted(both)}")

    choices, shapes = [], []
    for f in feats:
        p = f["properties"]
        share = float(p["share_inside_area"])
        uid = p["unit_id"]
        if uid in exclude:
            inc, why = False, "removed by user"
        elif uid in include:
            inc, why = True, "added by user"
        elif share >= min_share:
            inc, why = True, "majority"
        else:
            inc, why = False, "minority"
        choices.append(DistrictChoice(uid, p.get("name"), share, inc, why))
        if inc:
            geom = shape(f["geometry"])
            shapes.append(geom if geom.is_valid else geom.buffer(0))
    if not shapes:
        raise ValueError(f"no district is at least {min_share:.0%} inside the drawn area; "
                         f"draw a larger area or add districts by hand")
    choices.sort(key=lambda d: (not d.included, -d.share_inside_area))
    area = Area(drawn.name, drawn.iso3, unary_union(shapes))
    return SnapResult(area, drawn, min_share, choices)


def save_record(root: Path | str, result: SnapResult, extra: dict | None = None) -> Path:
    """Write <root>/<snapped area_id>/area.json: the drawing, the rule and every district's choice,
    so a snapped area can be explained and reproduced."""
    p = Path(root) / result.area.area_id / AREA_RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**result.record(), **(extra or {})}, indent=2, ensure_ascii=False))
    return p


def free_record(root: Path | str, drawn: Area, extra: dict | None = None) -> Path:
    """area.json for free-polygon mode, so every area folder says how it was made."""
    p = Path(root) / drawn.area_id / AREA_RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mode": "free", "drawn_area": drawn.to_geojson(),
                             "note": "expert advice applies only to districts fully inside the area",
                             "created_at": datetime.now(timezone.utc).isoformat(), **(extra or {})},
                            indent=2, ensure_ascii=False))
    return p


def resolve_area(drawn: Area, mode: str = "snap", cache: SnapshotCache | None = None,
                 boundaries_options: dict | None = None, min_share: float = DEFAULT_MIN_SHARE,
                 include=(), exclude=(), refresh: bool = False,
                 extra: dict | None = None) -> tuple[Area, SnapResult | None]:
    """The area every other fetcher should use.
    snap: fetch districts for the drawing, snap to whole districts, write area.json.
    free: the drawing itself (area.json says so).
    extra: more facts for area.json, e.g. {"level_choice": LevelChoice.to_json()}."""
    from leg.data.fetchers import BoundariesFetcher  # local: avoids an import cycle
    cache = cache or SnapshotCache()
    if mode == "free":
        free_record(cache.root, drawn, extra)
        return drawn, None
    if mode != "snap":
        raise ValueError("mode must be 'snap' or 'free'")
    bsnap = cache.get(BoundariesFetcher(**(boundaries_options or {})), drawn, refresh=refresh)
    result = snap_area(drawn, bsnap, min_share, include, exclude)
    save_record(cache.root, result, extra)
    return result.area, result
