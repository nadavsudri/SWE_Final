"""CLI:  python -m leg.data fetch --name negev --iso3 ISR --bbox 34.25,30.5,35.45,31.6
       python -m leg.data fetch --name galilee --iso3 ISR --geojson area.geojson --sources worldpop,boundaries
       python -m leg.data list --name negev --iso3 ISR --bbox 34.25,30.5,35.45,31.6
"""
from __future__ import annotations

import argparse
import sys

from leg.data import Area, SnapshotCache, fetch_all, resolve_profile
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
    print(f"Profile ({profile.source}): districts = {profile.admin_provider} level {profile.admin_levels[-1]}, "
          f"facilities = {', '.join(f'{k}={v}' for k, v in profile.facility_tags)}")
    if profile.rationale:
        print(f"  why: {profile.rationale}")

    results = fetch_all(area, sources, cache, refresh=a.refresh, profile=profile,
                        options={"worldpop": {"year": a.year}})
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
