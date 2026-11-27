"""CLI for the advice file and its scoring functions.

  python -m leg.advice prepare advice.txt --prep data/processed/<area>/<run> [--budget 10] [--model ...]
      the LLM writes one scoring function per advice; checks run; a review is saved
  python -m leg.advice recheck advice.txt     run the checks again on the saved code (no LLM call)
  python -m leg.advice show advice.txt        print the review (interpretation, checks, code)
  python -m leg.advice approve advice.txt     approve after reading; only approved functions are used
"""
from __future__ import annotations

import argparse
import sys

from leg import advice as adv


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m leg.advice")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prepare", help="write and check the scoring functions")
    pr.add_argument("advice_file")
    pr.add_argument("--prep", required=True, help="a preprocessing run folder (for real sample plans)")
    pr.add_argument("--budget", type=int, default=10, help="budget of the sample plans")
    pr.add_argument("--model", help="Claude model (default: LEG_LLM_MODEL or claude-sonnet-5-5)")
    pr.add_argument("--root", default="data/advice")
    for name in ("show", "approve", "recheck"):
        s = sub.add_parser(name)
        s.add_argument("advice_file")
        s.add_argument("--root", default="data/advice")
    a = p.parse_args(argv)

    try:
        if a.cmd == "prepare":
            items = adv.read_advice(a.advice_file)
            print(f"{len(items)} advice read from {a.advice_file}; asking the LLM for scoring functions...")
            d = adv.prepare(a.advice_file, a.prep, a.budget, adv.claude_llm(a.model), a.root)
            rec = adv.load(a.advice_file, a.root, require_approved=False)
            u = rec["llm_usage"]
            print(f"Saved in {d}  ({u.get('model')}: {u.get('input_tokens')} in / {u.get('output_tokens')} out tokens)")
            _summary(rec)
            print(f"\nRead {d / adv.REVIEW}, then: python -m leg.advice approve {a.advice_file}")
        elif a.cmd == "recheck":
            rec = adv.recheck(a.advice_file, a.root)
            print(f"Checked again ({len(rec['items'])} advice):")
            _summary(rec)
        elif a.cmd == "show":
            rec = adv.load(a.advice_file, a.root, require_approved=False)
            print(adv.review_text(rec))
        else:
            rec = adv.approve(a.advice_file, a.root)
            print(f"Approved at {rec['approved_at']}. Runs with {a.advice_file} will use these functions.")
    except (FileNotFoundError, ValueError, PermissionError, RuntimeError) as e:
        print(f"ERROR: {e}")
        return 1
    return 0


def _summary(rec: dict) -> None:
    for i, it in enumerate(rec["items"], 1):
        if not it["measurable"]:
            state = "not measurable (read by the planner, not scored)"
        elif it["check"]["passed"]:
            state = "checks passed" + (f"; warning: {it['check']['warnings'][0]}" if it["check"]["warnings"] else "")
        else:
            state = "CHECKS FAILED: " + "; ".join(it["check"]["errors"])
        print(f"  {i}. {it['advice'][:70]}  ->  {state}")


if __name__ == "__main__":
    sys.exit(main())
