"""CLI:  python -m leg.data fetch --name negev --iso3 ISR --bbox 34.25,30.5,35.45,31.6
       python -m leg.data fetch --name galilee --iso3 ISR --geojson area.geojson --sources worldpop,boundaries
       python -m leg.data list --name negev --iso3 ISR --bbox 34.25,30.5,35.45,31.6
"""
from __future__ import annotations

import argparse
import sys

from leg.data import Area, SnapshotCache, fetch_all, resolve_profile
from leg.data.levels import choose_level
from leg.data.snap import resolve_area
from leg.data.fetchers import REGISTRY


def _area(a: argparse.Namespace) -> Area:
    if bool(a.bbox) == bool(a.geojson):
        sys.exit("give exactly one of --bbox or --geojson")
    if a.bbox:
        w, s, e, n = (float(x) for x in a.bbox.split(","))
        return Area.from_bbox(a.name, a.iso3, w, s, e, n)
    return Area.from_geojson(a.name, a.iso3, a.geojson)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m leg.data")
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("fetch", "list"):
        s = sub.add_parser(cmd)
        s.add_argument("--name", required=True, help="label for the area, e.g. negev")
        s.add_argument("--iso3", required=True, help="country code, e.g. ISR")
        s.add_argument("--bbox", help="west,south,east,north in degrees")
        s.add_argument("--geojson", help="polygon file (Geometry / Feature / 1-feature collection)")
        s.add_argument("--root", default="data/raw", help="cache folder")
        s.add_argument("--sources", default=",".join(REGISTRY), help="comma list of sources")
    f = sub.choices["fetch"]
    f.add_argument("--refresh", action="store_true", help="ignore TTL, always fetch new snapshots")
    f.add_argument("--year", type=int, default=2026, help="WorldPop year")
    f.add_argument("--refresh-profile", action="store_true",
                   help="ask the LLM again for this country's profile instead of the cached one")
    f.add_argument("--mode", choices=["snap", "free"], default="snap",
                   help="snap: use the whole districts the drawing mostly covers (default); "
                        "free: use the drawing as is (advice then applies only to fully covered districts)")
    f.add_argument("--min-share", type=float, default=0.5,
                   help="snap: include a district when at least this share of it is inside (default 0.5)")
    f.add_argument("--level", help="district level instead of the automatic rule: ADM1-ADM5 "
                                   "(geoBoundaries) or an OSM admin_level number, e.g. 8")
    f.add_argument("--include", default="", help="snap: comma list of district unit_ids to add")
    f.add_argument("--exclude", default="", help="snap: comma list of district unit_ids to remove")
    a = p.parse_args(argv)

    area, cache = _area(a), SnapshotCache(a.root)
    sources = [s.strip() for s in a.sources.split(",") if s.strip()]
    print(f"Area {area.area_id}  bbox={tuple(round(v, 4) for v in area.bbox)}")

    if a.cmd == "list":
        for src in sources:
            snaps = cache.list(area, src)
            print(f"  {src:15s} " + (", ".join(s.id for s in snaps) if snaps else "(none)"))
        return 0

    profile = resolve_profile(area, cache.root, refresh=a.refresh_profile)
    print(f"Profile ({profile.source}): facilities = {', '.join(f'{k}={v}' for k, v in profile.facility_tags)}")
    if profile.rationale:
        print(f"  why: {profile.rationale}")

    ids = lambda t: [x.strip() for x in t.split(",") if x.strip()]
    if a.level:
        provider = "geoboundaries" if a.level.upper().startswith("ADM") else "osm"
        bopts, extra = {"provider": provider, "levels": (a.level.upper() if provider == "geoboundaries"
                                                         else a.level,)}, {"level_choice": "set by user"}
        print(f"District level: {provider} {a.level} (set by user)")
    else:
        choice = choose_level(area, cache, a.mode, a.min_share, refresh=a.refresh)
        bopts, extra = choice.boundaries_options(), {"level_choice": choice.to_json()}
        print(f"District level: {choice.provider} {choice.level}, {choice.usable} usable districts "
              f"({choice.reason})")
        for c in choice.counts:
            print(f"  {c.provider:13s} {c.level:5s} " + (f"{c.usable:4d} usable of {c.touched:4d} touched"
                                                         if c.available else "not available"))
        if not choice.in_range:
            print("  WARNING: no level is in the 10-100 range; check the choice or set --level")
    area, snap = resolve_area(area, a.mode, cache, bopts, a.min_share, ids(a.include), ids(a.exclude),
                              a.refresh, extra)
    if snap:
        print(f"Snapped to {len(snap.included)} whole districts -> area {area.area_id}")
        for d in snap.districts:
            print(f"  {'+' if d.included else '-'} {str(d.name):30s} {d.share_inside_area:7.1%} inside  "
                  f"({d.reason})  {d.unit_id}")
    else:
        print("WARNING: free polygon. Expert advice will be taken into account only for districts "
              "the polygon covers completely.")

    results = fetch_all(area, sources, cache, refresh=a.refresh, profile=profile,
                        options={"worldpop": {"year": a.year}, "boundaries": bopts})
    failed = 0
    for src, r in results.items():
        if isinstance(r, Exception):
            failed += 1
            print(f"  FAIL {src:15s} {type(r).__name__}: {r}")
        else:
            print(f"  ok   {src:15s} {r.id}  {r.manifest.get('summary', {})}  -> {r.path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
