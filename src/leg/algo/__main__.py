"""CLI: run the placement methods on a preprocessing output and compare them.

  python -m leg.algo data/processed/<area_id>/<run_id> --b 10
  python -m leg.algo <prep_dir> --b 10 --allocation "0:4,1:6" --alpha 0.5 --beta 0.8 --out result.json

Methods: greedy, ILP (optimum, with a time limit), random (seeded), and GuidedGreedy when an
allocation {district id: count} is given. Every output is validated; failures are printed.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time

from leg.algo import (Instance, check, coverage, district_counts, greedy, guided_greedy, ilp,
                      random_sites)


def _allocation(text: str) -> dict[int, int]:
    out = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        d, n = part.split(":")
        out[int(d)] = int(n)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m leg.algo")
    p.add_argument("prep_dir")
    p.add_argument("--b", type=int, required=True, help="number of new facilities")
    p.add_argument("--allocation", help='district:count list for GuidedGreedy, e.g. "0:4,1:6"')
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--beta", type=float, default=0.8)
    p.add_argument("--seed", type=int, default=0, help="random baseline seed")
    p.add_argument("--ilp-time", type=float, default=60.0, help="ILP time limit (s); 0 = skip ILP")
    p.add_argument("--out", help="write all results as JSON")
    a = p.parse_args(argv)

    inst = Instance.load(a.prep_dir)
    total_uncovered = float(inst.weight.sum())
    print(f"{inst.n_cells} cells, {inst.n_candidates} candidates, {len(inst.districts())} districts, "
          f"{total_uncovered:,.0f} people not yet covered; b={a.b}")

    runs = {}

    def run(name, fn):
        t0 = time.perf_counter()
        out = fn()
        runs[name] = {"seconds": round(time.perf_counter() - t0, 3), **out}

    opt = None
    run("greedy", lambda: (lambda r: {"sites": r.sites, "value": r.value})(greedy(inst, a.b)))
    if a.ilp_time > 0:
        r = ilp(inst, a.b, a.ilp_time, warm_start=runs["greedy"]["sites"])
        opt = r.value if r.optimal else None
        # greedy is a (1 - 1/e)-approximation, so OPT <= greedy / (1 - 1/e): a second valid bound
        bound = min(r.upper_bound, runs["greedy"]["value"] / (1 - 1 / math.e))
        runs["ilp"] = {"seconds": round(r.seconds, 3), "sites": r.sites, "value": r.value,
                       "optimal": r.optimal, "upper_bound": bound,
                       "gap": 0.0 if r.optimal else (bound - r.value) / bound if bound else 0.0}
    run(f"random(seed={a.seed})", lambda: (lambda s: {"sites": s, "value": coverage(inst, s)})(
        random_sites(inst, a.b, a.seed)))
    if a.allocation:
        alloc = _allocation(a.allocation)
        run(f"guided(a={a.alpha},b={a.beta})", lambda: (lambda r: {
            "sites": r.sites, "value": r.value, "allocation": alloc,
            "rules": [x["rule"] for x in r.picks]})(guided_greedy(inst, a.b, alloc, a.alpha, a.beta)))

    ub = runs["ilp"]["upper_bound"] if "ilp" in runs else None
    failed = 0
    print(f"\n{'method':26s} {'covered':>12s} {'% of uncovered':>15s} {'% of OPT':>9s} {'time s':>8s}  valid")
    for name, r in runs.items():
        guided = name.startswith("guided")
        rep = check(inst, r["sites"], a.b, a.alpha if guided else None, a.beta if guided else None, opt)
        r["valid"], r["errors"] = rep.ok, rep.errors
        r["district_counts"] = {str(k): v for k, v in district_counts(inst, r["sites"]).items()}
        failed += not rep.ok
        pct = 100 * r["value"] / total_uncovered if total_uncovered else 0
        vs = f"{100 * r['value'] / ub:8.1f}%" if ub else "      n/a"
        print(f"{name:26s} {r['value']:12,.0f} {pct:14.1f}% {vs} {r['seconds']:8.2f}  "
              f"{'ok' if rep.ok else 'FAIL: ' + '; '.join(rep.errors)}")
    if "ilp" in runs and not runs["ilp"]["optimal"]:
        print(f"\nILP stopped at the time limit: best found {runs['ilp']['value']:,.0f}, "
              f"upper bound {ub:,.0f} (gap {100 * runs['ilp']['gap']:.1f}%). '% of OPT' uses the bound.")
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"prep_dir": a.prep_dir, "b": a.b, "alpha": a.alpha, "beta": a.beta,
                       "seed": a.seed, "runs": runs}, f, indent=2)
        print(f"\nWrote {a.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
