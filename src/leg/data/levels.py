"""Choose the administrative level used as "districts" by a fixed rule (no LLM).

The paper's districts are a country's local planning units (Ethiopia: woredas, ADM3) and a
region contains many of them. The right level depends on the country and on how big the drawn
area is, so the rule looks at the area itself:

1. For each geoBoundaries level ADM1..ADM5 that exists for the country, count the *usable*
   districts: in snap mode those at least `min_share` inside the drawing (what the snap would
   keep); in free mode every district the drawing touches.
2. Pick the finest level whose count is within [min_count, max_count] (default 10..100).
3. If no geoBoundaries level is in range and the finest one has too few districts, try OSM
   admin levels (e.g. Israeli municipalities are only in OSM) the same way.
4. If still nothing is in range, take the level closest to the range and say so (warning).

Every count is reported, so the UI can show the table and let the user override the choice.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import requests

from leg.data.area import Area
from leg.data.cache import Snapshot, SnapshotCache
from leg.data.snap import DEFAULT_MIN_SHARE, touched_districts

GEOBOUNDARIES_LEVELS = ("ADM1", "ADM2", "ADM3", "ADM4", "ADM5")
OSM_LEVELS = ("5", "6", "7", "8", "9", "10")
MIN_COUNT, MAX_COUNT = 10, 100


@dataclass
class LevelCount:
    provider: str          # "geoboundaries" | "osm"
    level: str             # "ADM3" | "8"
    available: bool
    touched: int = 0       # districts the drawing touches
    usable: int = 0        # districts the rule counts (snap: >= min_share inside; free: touched)
    note: str = ""


@dataclass
class LevelChoice:
    provider: str
    level: str
    usable: int
    in_range: bool
    reason: str
    counts: list[LevelCount] = field(default_factory=list)
    rule: dict = field(default_factory=dict)

    def boundaries_options(self) -> dict:
        return {"provider": self.provider, "levels": (self.level,)}

    def to_json(self) -> dict:
        return asdict(self)


def _missing_level(e: Exception) -> bool:
    """True when the source simply has no such level (vs. a network or server failure)."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return e.response.status_code in (404, 410)
    return isinstance(e, KeyError)  # metadata without a download link


def _count(feats: list[dict], mode: str, min_share: float) -> int:
    if mode == "free":
        return len(feats)
    return sum(1 for f in feats if float(f["properties"]["share_inside_area"]) >= min_share)


def _distance(n: int, lo: int, hi: int) -> float:
    """How far a count is from the range, on a log scale (2 vs 10 is as far as 500 vs 100)."""
    if n <= 0:
        return math.inf
    return 0.0 if lo <= n <= hi else abs(math.log(n / (lo if n < lo else hi)))


def choose_level(drawn: Area, cache: SnapshotCache | None = None, mode: str = "snap",
                 min_share: float = DEFAULT_MIN_SHARE, min_count: int = MIN_COUNT,
                 max_count: int = MAX_COUNT, refresh: bool = False, fetch=None) -> LevelChoice:
    """fetch(provider, level) -> boundaries Snapshot for `drawn`; defaults to the cached fetcher.
    Raises on network/server failures; a level the source doesn't have is skipped."""
    if mode not in ("snap", "free"):
        raise ValueError("mode must be 'snap' or 'free'")
    if not 0 < min_count <= max_count:
        raise ValueError("need 0 < min_count <= max_count")
    cache = cache or SnapshotCache()
    if fetch is None:
        from leg.data.fetchers import BoundariesFetcher

        def fetch(provider: str, level: str) -> Snapshot:
            return cache.get(BoundariesFetcher(levels=(level,), provider=provider), drawn, refresh=refresh)

    counts: list[LevelCount] = []

    def probe(provider: str, levels) -> None:
        for lv in levels:
            try:
                feats = touched_districts(fetch(provider, lv))
            except ValueError as e:
                if "intersect" in str(e):  # the level exists but has no unit in this area
                    counts.append(LevelCount(provider, lv, True, 0, 0, note="no unit in the area"))
                    continue
                raise
            except Exception as e:  # noqa: BLE001 - classified below
                if _missing_level(e):
                    counts.append(LevelCount(provider, lv, False, note=str(e)[:200]))
                    continue
                raise
            counts.append(LevelCount(provider, lv, True, len(feats), _count(feats, mode, min_share)))

    def best() -> LevelCount | None:
        ok = [c for c in counts if c.available and min_count <= c.usable <= max_count]
        return ok[-1] if ok else None  # levels are probed coarse to fine: last = finest

    probe("geoboundaries", GEOBOUNDARIES_LEVELS)
    pick = best()
    finest_gb = next((c for c in reversed(counts) if c.available), None)
    if pick is None and (finest_gb is None or finest_gb.usable < min_count):
        probe("osm", OSM_LEVELS)
        pick = best()

    rule = {"mode": mode, "min_share": min_share, "min_count": min_count, "max_count": max_count}
    if pick is not None:
        return LevelChoice(pick.provider, pick.level, pick.usable, True,
                           f"finest level with {min_count}-{max_count} usable districts", counts, rule)
    avail = [c for c in counts if c.available and c.usable > 0]
    if not avail:
        raise ValueError("no administrative level has any usable district for this area; "
                         "draw a larger area or use free-polygon mode")
    near = min(avail, key=lambda c: (_distance(c.usable, min_count, max_count), -counts.index(c)))
    return LevelChoice(near.provider, near.level, near.usable, False,
                       f"no level has {min_count}-{max_count} usable districts; closest is "
                       f"{near.provider} {near.level} with {near.usable}", counts, rule)
