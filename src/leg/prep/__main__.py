"""CLI:  python -m leg.prep --area-id ETH_wollo_ab12cd34 [--years 2026] [--max-minutes 120]

Reads the snapshots the fetcher stored in data/raw/<area_id>/ (the newest of each, or --snapshot
SOURCE=ID) and writes data/processed/<area_id>/<run_id>/ in the paper's format.
The area id is the one `python -m leg.data fetch` prints ("Snapped to ... -> area <id>").
"""
from __future__ import annotations

import argparse
import json
import sys

from leg.prep import STAGES, PrepParams
from leg.prep.run import prepare


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m leg.prep")
    p.add_argument("--area-id", required=True, help="folder name under data/raw")
    p.add_argument("--root", default="data/raw")
    p.add_argument("--out", default="data/processed")
    p.add_argument("--years", help="comma list of WorldPop years (first = planning year); default: newest snapshot")
    p.add_argument("--min-population", type=float, default=10.0)
    p.add_argument("--window", type=int, default=10, help="pairs at most this many cells apart")
    p.add_argument("--max-minutes", type=float, default=120.0, help="walking time a facility covers")
    p.add_argument("--keep-minutes", type=float, help="pairs written to pairwise_costs.csv (default = max)")
    p.add_argument("--snapshot", action="append", default=[], metavar="SOURCE=ID",
                   help="pin an input snapshot, e.g. --snapshot worldpop=2026-11-12T074642Z")
    a = p.parse_args(argv)

    params = PrepParams(min_population=a.min_population, window=a.window, max_minutes=a.max_minutes,
                        keep_minutes=a.keep_minutes or a.max_minutes)
    years = [int(y) for y in a.years.split(",")] if a.years else None
    last = {"stage": None, "pct": -10}

    def progress(stage, done, total):
        pct = int(100 * done / total) if total else 0
        if stage != last["stage"] or pct >= last["pct"] + 10:
            print(f"  [{STAGES.index(stage) + 1}/{len(STAGES)}] {stage:13s} {pct:3d}%", flush=True)
            last.update(stage=stage, pct=pct)

    try:
        out = prepare(a.area_id, a.root, a.out, dict(s.split("=", 1) for s in a.snapshot), params, years, progress)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1
    meta = json.loads((out / "meta.json").read_text())
    t, u = meta["totals"], meta["unassigned"]
    print(f"Wrote {out}")
    print(f"  {t['cells']} cells, {t['pairs']:,} pairs within {params.keep_minutes:g} min, "
          f"{t['districts']} districts, {t['existing_facilities']} existing facilities")
    pct = 100 * t["covered_population"] / t["population"] if t["population"] else 0
    print(f"  population {t['population']:,}; within {params.max_minutes:g} min of a facility: "
          f"{t['covered_population']:,} ({pct:.1f}%)")
    if u["cells"]:
        print(f"  WARNING: {u['cells']} cells ({u['population']:,} people) are in no district")
    if meta["dropped_facilities"]:
        print(f"  note: {meta['dropped_facilities']} facilities are more than {params.max_snap_km:g} km "
              f"from any populated cell and were left out")
    print(f"  time: {meta['seconds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
