"""CLI:  python -m leg.prep --name negev --iso3 ISR --bbox 34.5,30.5,35.45,31.6 [--cell-km 1] [--radius-km 10]

Uses the cached snapshots (fetches whatever is missing), then writes data/processed/<area_id>/<run_id>/.
"""
from __future__ import annotations

import argparse
import json
import sys

from leg.data import Area, SnapshotCache, fetch_all
from leg.prep import PrepParams, build

NEEDED = ["worldpop", "boundaries", "osm_facilities", "public_facilities"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m leg.prep")
    p.add_argument("--name", required=True)
    p.add_argument("--iso3", required=True)
    p.add_argument("--bbox", help="west,south,east,north")
    p.add_argument("--geojson", help="polygon file instead of --bbox")
    p.add_argument("--root", default="data/raw")
    p.add_argument("--out", default="data/processed")
    p.add_argument("--cell-km", type=float, default=1.0)
    p.add_argument("--radius-km", type=float, default=10.0)
    p.add_argument("--candidates", choices=["populated", "all"], default="populated")
    p.add_argument("--snapshot", action="append", default=[], metavar="SOURCE=ID",
                   help="pin an input snapshot, e.g. --snapshot worldpop=2026-11-12T074642Z")
    a = p.parse_args(argv)

    if bool(a.bbox) == bool(a.geojson):
        sys.exit("give exactly one of --bbox or --geojson")
    area = (Area.from_bbox(a.name, a.iso3, *(float(x) for x in a.bbox.split(",")))
            if a.bbox else Area.from_geojson(a.name, a.iso3, a.geojson))
    pinned = dict(s.split("=", 1) for s in a.snapshot)

    snaps = fetch_all(area, NEEDED, SnapshotCache(a.root), pinned=pinned)
    failed = {k: v for k, v in snaps.items() if isinstance(v, Exception)}
    if failed:
        for k, v in failed.items():
            print(f"FAIL {k}: {type(v).__name__}: {v}")
        return 1

    params = PrepParams(a.cell_km, a.radius_km, a.candidates)
    out = build(snaps["worldpop"], snaps["boundaries"], [snaps["osm_facilities"], snaps["public_facilities"]],
                area.geometry, a.out, area.area_id, params)
    meta = json.loads((out / "meta.json").read_text())
    t, u = meta["totals"], meta["unassigned"]
    print(f"Wrote {out}")
    print(f"  cells {t['cells']} (~{meta['real_cell_km']} km), candidates {t['candidates']}, "
          f"districts {t['districts']}, existing facilities {t['existing_facilities']}")
    pct = 100 * t["already_covered_population"] / t["population"] if t["population"] else 0
    print(f"  population {t['population']:,}, already covered {t['already_covered_population']:,} ({pct:.1f}%)")
    if u["cells"]:
        print(f"  WARNING: {u['cells']} cells ({u['population']:,} people) are in no district")
    return 0


if __name__ == "__main__":
    sys.exit(main())
