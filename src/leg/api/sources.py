"""Per-source options for the UI: what can be set, validation, and what the cache will do."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from leg.data import Area, SnapshotCache
from leg.data.fetchers import REGISTRY, OsmRoadsFetcher
from leg.data.fetchers.osm import DEFAULT_FACILITY_TAGS
from leg.data.profile import ALLOWED_TAG_KEYS, _VALUE_RE

LABELS = {"worldpop": "Population", "boundaries": "Districts", "osm_facilities": "Health facilities",
          "public_facilities": "Public facilities (sub-Saharan Africa)",
          "osm_roads": "Roads", "gtfs": "Transit (GTFS)"}

SCHEMA = {
    "worldpop": {"year": {"type": "int", "min": 2015, "max": 2030, "default": 2026},
                 "resolution": {"type": "enum", "values": ["100m", "1km"], "default": "100m"}},
    "boundaries": {},  # the level is chosen by leg.data.levels (or overridden): /api/area/levels
    "osm_facilities": {"tags": {"type": "tags", "keys": sorted(ALLOWED_TAG_KEYS),
                                "default": [list(t) for t in DEFAULT_FACILITY_TAGS]}},
    "osm_roads": {"highway_types": {"type": "multi", "values": list(OsmRoadsFetcher.DEFAULT_TYPES),
                                    "default": list(OsmRoadsFetcher.DEFAULT_TYPES)}},
    "gtfs": {"max_feeds": {"type": "int", "min": 1, "max": 100, "default": 10}},
    "public_facilities": {},  # no options: a fixed dataset, read from a file downloaded once
}


def describe() -> list[dict]:
    return [{"source": s, "label": LABELS.get(s, s), "ttl_days": REGISTRY[s].ttl_days, "options": SCHEMA.get(s, {})}
            for s in REGISTRY]


def _int(v, lo, hi, what):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number")
    if str(v).strip() != str(n) and not isinstance(v, int):
        raise ValueError(f"{what} must be a whole number")
    if not lo <= n <= hi:
        raise ValueError(f"{what} must be {lo}–{hi}")
    return n


def normalize(source: str, opts: dict | None, base: dict | None = None) -> tuple[dict, dict[str, str]]:
    """UI options -> fetcher kwargs, plus {field: error}. Only keys the user sent are returned,
    so fetch_all still merges them over the profile; `base` (the profile's options) is used to
    check combinations, e.g. a provider changed by the user against levels from the profile."""
    opts, kw, err = opts or {}, {}, {}
    base = base or {}
    try:
        if source == "worldpop":
            if "year" in opts:
                kw["year"] = _int(opts["year"], 2015, 2030, "Year")
            if "resolution" in opts:
                if opts["resolution"] not in ("100m", "1km"):
                    raise ValueError("Resolution must be 100m or 1km")
                kw["resolution"] = opts["resolution"]
        elif source == "boundaries":
            provider = opts.get("provider", base.get("provider", "geoboundaries"))
            if provider not in ("geoboundaries", "osm"):
                err["provider"] = "Provider must be geoBoundaries or OpenStreetMap"
            if "provider" in opts:
                kw["provider"] = provider
            if "levels" in opts or ("provider" in opts and "levels" in base):
                levels = [str(x).strip() for x in opts.get("levels", base.get("levels", [])) if str(x).strip()]
                if not levels:
                    err["levels"] = "Give at least one level"
                elif provider == "geoboundaries" and not all(re.fullmatch(r"ADM[1-5]", lv) for lv in levels):
                    bad = next(lv for lv in levels if not re.fullmatch(r"ADM[1-5]", lv))
                    err["levels"] = f"geoBoundaries levels are ADM1–ADM5; “{bad}” is not one"
                elif provider == "osm" and not all(lv.isdigit() and 2 <= int(lv) <= 11 for lv in levels):
                    bad = next(lv for lv in levels if not (lv.isdigit() and 2 <= int(lv) <= 11))
                    hint = " (“ADM…” is a geoBoundaries level)" if bad.upper().startswith("ADM") else ""
                    err["levels"] = f"OpenStreetMap levels are numbers 2–11; “{bad}” is not one{hint}"
                if "levels" in opts:
                    kw["levels"] = tuple(levels)
        elif source == "osm_facilities":
            if "tags" in opts:
                tags = [tuple(str(p).strip() for p in t) for t in opts["tags"]]
                if not tags:
                    err["tags"] = "Give at least one tag"
                for t in tags:
                    if len(t) != 2:
                        err["tags"] = "Each tag is a key and a value"
                    elif t[0] not in ALLOWED_TAG_KEYS:
                        err["tags"] = f"Key must be amenity, healthcare or emergency; “{t[0]}” is not allowed"
                    elif not _VALUE_RE.match(t[1]):
                        err["tags"] = f"Value “{t[1]}” must be lowercase letters and _ , or * for any value"
                kw["tags"] = tuple(tags)
        elif source == "osm_roads":
            if "highway_types" in opts:
                types = [str(t).strip() for t in opts["highway_types"]]
                if not types:
                    err["highway_types"] = "Choose at least one highway type"
                elif not all(re.fullmatch(r"[a-z_]+", t) for t in types):
                    err["highway_types"] = "Highway types are lowercase words"
                kw["highway_types"] = tuple(types)
        elif source == "public_facilities":
            pass
        elif source == "gtfs":
            if "max_feeds" in opts:
                kw["max_feeds"] = _int(opts["max_feeds"], 1, 100, "Max feeds")
        elif source in REGISTRY and not SCHEMA.get(source):
            pass  # a source without options
        else:
            err["source"] = f"Unknown source {source!r}"
    except ValueError as e:
        field = {"worldpop": "year" if "Year" in str(e) else "resolution", "gtfs": "max_feeds"}.get(source, "options")
        err[field] = str(e)
    if not err:
        try:
            REGISTRY[source](**{**base, **kw})  # the fetcher's own checks, on what will really run
        except (ValueError, TypeError) as e:
            err["options"] = str(e)
    return kw, err


def plan(area: Area, cache: SnapshotCache, profile_opts: dict, user_opts: dict,
         now: datetime | None = None) -> dict:
    """Per source: snapshots (newest first) and whether fetch_all would reuse or download.
    Mirrors SnapshotCache.get(): same params and younger than the TTL means reuse."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for src in REGISTRY:
        kw, err = normalize(src, (user_opts or {}).get(src), profile_opts.get(src))
        entry = {"source": src, "label": LABELS.get(src, src), "ttl_days": REGISTRY[src].ttl_days, "errors": err}
        if err:
            out[src] = entry | {"decision": "invalid", "snapshots": []}
            continue
        fetcher = REGISTRY[src](**{**profile_opts.get(src, {}), **kw})
        params = fetcher.params()
        ttl = timedelta(days=fetcher.ttl_days)
        snaps = []
        for s in reversed(cache.list(area, src)):
            age = now - s.fetched_at
            snaps.append({"id": s.id, "fetched_at": s.manifest["fetched_at"],
                          "age_days": round(age.total_seconds() / 86400, 1),
                          "params_match": s.manifest.get("params") == params, "fresh": age < ttl})
        reuse = next((s for s in snaps if s["params_match"] and s["fresh"]), None)
        if reuse:
            entry |= {"decision": "reuse", "snapshot_id": reuse["id"],
                      "fresh_days_left": round(fetcher.ttl_days - reuse["age_days"], 1)}
        else:
            reason = ("no_snapshot" if not snaps else
                      "expired" if any(s["params_match"] for s in snaps) else "params_changed")
            entry |= {"decision": "download", "reason": reason}
        out[src] = entry | {"params": params, "snapshots": snaps}
    return out
