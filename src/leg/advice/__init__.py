"""Expert advice: a text file read at the start of a run, and one scoring function per advice.

As in the paper, an LLM reads the free-text advice and writes the code that measures how well a
plan follows each one. To keep experiments sound, this happens once per advice file:

  1. prepare(): the LLM writes score(plan) for each advice (or marks it not measurable with the
     data we have), every function passes the sandbox and runs on sample plans in a separate
     process: it must return a number in [0, 1], the same number twice, and (warning only) not the
     same number for every sample plan.
  2. The functions and a readable review are saved under data/advice/<file>_<hash>/.
  3. A person reads the review and approves it (approve()); only approved functions are used.
  4. alignment(): every run with that advice file uses exactly these functions.

Advice file: UTF-8 text, one advice per line (blank lines and lines starting with # are skipped,
leading "1." or "-" is removed), or a JSON list of strings. Any language.
"""
from __future__ import annotations

import hashlib
import json
import math
import multiprocessing as mp
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from leg.advice.plan import FIELDS, PlanBuilder
from leg.advice.sandbox import UnsafeCode, check_code, run_score

SCORING = "scoring.json"
REVIEW = "review.md"
CHECK_TIMEOUT_S = 10

LLM = Callable[[str], tuple[dict, dict]]  # prompt -> (json reply, usage)


# ------------------------------------------------------------------ the advice file
def read_advice(path: Path | str) -> list[str]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        items = json.loads(text)
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            raise ValueError(f"{p}: a JSON advice file must be a list of strings")
    else:
        items = [re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", ln).strip() for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    items = [x.strip() for x in items if x.strip()]
    if not items:
        raise ValueError(f"{p}: no advice found")
    if len(set(items)) != len(items):
        raise ValueError(f"{p}: the same advice appears twice")
    return items


def advice_hash(items: list[str]) -> str:
    return hashlib.sha256("\n".join(items).encode()).hexdigest()


def store_dir(advice_file: Path | str, items: list[str], root: Path | str = "data/advice") -> Path:
    """One folder per advice text: editing the file means new functions and a new approval."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(advice_file).stem).strip("-") or "advice"
    return Path(root) / f"{stem}_{advice_hash(items)[:8]}"


# ------------------------------------------------------------------ asking the LLM
PROMPT = """You help plan where to build new health facilities. A planner splits a budget of new
facilities between districts; an algorithm then places them in the best locations inside each
district. Experts gave advice, in free text. For EACH advice, write a Python function that
measures how well a plan follows it.

The function receives one plan:
{schema}

Example plan (real numbers from the area being planned):
{example}

Rules for the code:
- Define exactly `def score(plan):` returning a float from 0.0 (ignores the advice) to 1.0 (fully follows it).
- Plain Python only. `math` is available without import. No imports, no while loops, no classes,
  no names or attributes starting with "_", no file or network access, no randomness.
- Partial credit where it makes sense (e.g. the share of districts that meet a condition).
- Use only the fields above. If the advice needs information the plan does not have (e.g. roads,
  terrain, distances between towns), set "measurable": false and "code": null; the planner will
  still read the advice, it just cannot be scored.
- Interpret the advice as a planner would; when it is vague, choose a reasonable reading and say
  which in "interpretation".

Advice (in order):
{advice}

Reply with one JSON object only:
{{"items": [{{"advice": "<copied exactly>", "measurable": true, "interpretation": "<one or two sentences>",
"code": "def score(plan):\\n    ..."}}, ...]}}
The list must have one item per advice, in the same order."""

SCHEMA = """{"budget": int,                      # number of new facilities in the plan
 "districts": [                          # one entry per district in the area
   {"name": str, "adm2": str, "adm1": str,   # district name and the two levels above it
    "population": int,                   # people living in the district
    "covered_before": int,               # people within a two-hour walk of an existing facility
    "coverage_before_pct": float,        # covered_before / population * 100
    "covered_after": int,                # ... of an existing or a NEW facility (after this plan)
    "coverage_after_pct": float,
    "existing_facilities": int,          # facilities there today
    "new_facilities": int,               # new facilities this plan puts in the district
    "cells": int,                        # populated ~1 km grid cells (a measure of settled area)
    "fully_inside": bool},               # whole district inside the planning area
   ...]}"""


def build_prompt(items: list[str], example: dict) -> str:
    ex = dict(example, districts=example["districts"][:6])
    if len(example["districts"]) > 6:
        ex["districts"] = ex["districts"] + [f"... {len(example['districts']) - 6} more districts"]
    return PROMPT.format(schema=SCHEMA, example=json.dumps(ex, ensure_ascii=False, indent=1),
                         advice="\n".join(f"{i + 1}. {a}" for i, a in enumerate(items)))


def claude_llm(model: str | None = None, max_tokens: int = 8000) -> LLM:
    from leg.llm.claude import complete, load_api_key
    key = load_api_key()
    if not key:
        raise RuntimeError("Writing the scoring functions needs the Claude API key: set ANTHROPIC_API_KEY in .env")
    return lambda prompt: complete(prompt, key, model, max_tokens)


# ------------------------------------------------------------------ sample plans for the checks
def sample_allocations(names: list[str], pops: list[float], uncovered: list[float],
                       coverage: list[float], b: int) -> dict[str, dict[str, int]]:
    def prop(weights):
        tot = sum(weights) or 1.0
        raw = [b * w / tot for w in weights]
        n = [int(math.floor(x)) for x in raw]
        for i in sorted(range(len(raw)), key=lambda i: raw[i] - n[i], reverse=True)[: b - sum(n)]:
            n[i] += 1
        return {k: v for k, v in zip(names, n) if v}

    order = sorted(range(len(names)), key=lambda i: -pops[i])
    spread = {}
    for j in range(b):
        k = names[order[j % len(order)]]
        spread[k] = spread.get(k, 0) + 1
    return {"by uncovered population": prop(uncovered),
            "all in the most populated district": {names[order[0]]: b},
            "all in the least covered district": {names[min(range(len(names)), key=lambda i: coverage[i])]: b},
            "spread one by one, most populated first": spread,
            "by population": prop(pops)}


def sample_plans(builder: PlanBuilder, b: int) -> dict[str, dict]:
    """Real plans for this area: each sample allocation placed by GuidedGreedy (alpha=0, follow it)."""
    from leg.algo.greedy import guided_greedy
    base = builder.plan([], b)["districts"]
    usable = [d for d in base if builder.key_to_id[d["name"]] is not None and d["cells"] > 0]
    allocs = sample_allocations([d["name"] for d in usable], [d["population"] for d in usable],
                                [d["population"] - d["covered_before"] for d in usable],
                                [d["coverage_before_pct"] for d in usable], b)
    out = {}
    for label, alloc in allocs.items():
        r = guided_greedy(builder.inst, b, builder.allocation_ids(alloc), 0.0, 1.0)
        out[label] = builder.plan(r.sites, b)
    return out


# ------------------------------------------------------------------ checks (separate process)
def _check_worker(code: str, plans: list[dict], q) -> None:
    try:
        first = [run_score(code, p) for p in plans]
        again = [run_score(code, p) for p in plans]
        q.put(("ok", first, again))
    except Exception as e:  # noqa: BLE001 - reported to the user
        q.put(("error", f"{type(e).__name__}: {e}", None))


def check_function(code: str, plans: dict[str, dict], timeout: float = CHECK_TIMEOUT_S) -> dict:
    """Run score() on every sample plan in a separate process with a time limit."""
    res = {"passed": False, "errors": [], "warnings": [], "sample_scores": {}}
    try:
        check_code(code)
    except UnsafeCode as e:
        res["errors"].append(f"unsafe or invalid code: {e}")
        return res
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_check_worker, args=(code, list(plans.values()), q), daemon=True)
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        res["errors"].append(f"did not finish within {timeout:g} s")
        return res
    status, first, again = q.get() if not q.empty() else ("error", "no result", None)
    if status != "ok":
        res["errors"].append(first)
        return res
    res["sample_scores"] = {k: round(v, 4) for k, v in zip(plans, first)}
    if any(not 0.0 <= v <= 1.0 for v in first):
        res["errors"].append("returns values outside 0-1")
    if first != again:
        res["errors"].append("gives different results for the same plan")
    if len(set(round(v, 6) for v in first)) == 1:
        res["warnings"].append(f"gives the same score ({first[0]:.3f}) to every sample plan")
    res["passed"] = not res["errors"]
    return res


# ------------------------------------------------------------------ prepare / review / approve
STAGES = ["reading", "sample_plans", "writing_functions", "checking", "saving"]


def prepare(advice_file: Path | str, prep_dir: Path | str, budget: int = 10, llm: LLM | None = None,
            root: Path | str = "data/advice", max_minutes: float = 120.0, progress=None) -> Path:
    """Write, check and save the scoring functions for an advice file. Not approved yet.
    progress(stage, done, total) is called as it goes (stages: STAGES)."""
    report = progress or (lambda *a: None)
    report("reading", 0, 1)
    items = read_advice(advice_file)
    llm = llm or claude_llm()   # fail early (no API key) before the slower steps
    report("sample_plans", 0, 1)
    builder = PlanBuilder.from_run(prep_dir, max_minutes)
    plans = sample_plans(builder, budget)
    example = plans["by uncovered population"]
    report("writing_functions", 0, 1)
    reply, usage = llm(build_prompt(items, example))
    got = reply.get("items") if isinstance(reply, dict) else None
    if not isinstance(got, list) or len(got) != len(items):
        raise ValueError(f"the LLM returned {len(got) if isinstance(got, list) else 'no'} items for {len(items)} advice")
    out = []
    for i, (text, it) in enumerate(zip(items, got)):
        report("checking", i, len(items))
        measurable = bool(it.get("measurable")) and bool(it.get("code"))
        entry = {"advice": text, "measurable": measurable, "interpretation": str(it.get("interpretation", "")),
                 "code": it.get("code") if measurable else None}
        entry["check"] = check_function(entry["code"], plans) if measurable else None
        out.append(entry)
    d = store_dir(advice_file, items, root)
    d.mkdir(parents=True, exist_ok=True)
    record = {"advice_file": str(advice_file), "advice_sha256": advice_hash(items),
              "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "prep_run": str(prep_dir), "budget_for_samples": budget, "llm_usage": usage,
              "approved_at": None, "sample_plans": list(plans), "items": out}
    report("saving", 0, 1)
    save_dir(d, record)
    report("saving", 1, 1)
    return d


def save_dir(d: Path, rec: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / SCORING).write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / REVIEW).write_text(review_text(rec), encoding="utf-8")


def load_dir(d: Path | str) -> dict:
    p = Path(d) / SCORING
    if not p.exists():
        raise FileNotFoundError(f"No scoring functions in {d}")
    return json.loads(p.read_text(encoding="utf-8"))


def approve_dir(d: Path | str) -> dict:
    rec = load_dir(d)
    failed = [i + 1 for i, it in enumerate(rec["items"]) if it["measurable"] and not it["check"]["passed"]]
    if failed:
        raise ValueError(f"advice {failed} failed the checks: fix the code in {SCORING} or prepare again")
    rec["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_dir(Path(d), rec)
    return rec


def recheck_dir(d: Path | str, max_minutes: float = 120.0) -> dict:
    """Run the checks again on the saved code (no LLM call). Clears an earlier approval."""
    rec = load_dir(d)
    builder = PlanBuilder.from_run(rec["prep_run"], max_minutes)
    plans = sample_plans(builder, rec["budget_for_samples"])
    for it in rec["items"]:
        it["check"] = check_function(it["code"], plans) if it["measurable"] else None
    rec["sample_plans"], rec["approved_at"] = list(plans), None
    save_dir(Path(d), rec)
    return rec


def list_sets(root: Path | str = "data/advice") -> list[dict]:
    """Every saved advice set, newest first."""
    out = []
    for p in Path(root).glob(f"*/{SCORING}"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        out.append({"key": p.parent.name, "file": Path(rec["advice_file"]).name, "created_at": rec["created_at"],
                    "approved_at": rec["approved_at"], "advice": len(rec["items"]),
                    "measurable": sum(1 for it in rec["items"] if it["measurable"]),
                    "failed": sum(1 for it in rec["items"] if it["measurable"] and not it["check"]["passed"])})
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


def recheck(advice_file: Path | str, root: Path | str = "data/advice", max_minutes: float = 120.0) -> dict:
    """Run the checks again on the saved code (no LLM call), e.g. after a sandbox change.
    Clears an earlier approval: the person approves the result of the new checks."""
    return recheck_dir(store_dir(advice_file, read_advice(advice_file), root), max_minutes)


def review_text(rec: dict) -> str:
    lines = [f"# Advice scoring review: {Path(rec['advice_file']).name}", "",
             f"Written by {rec['llm_usage'].get('model', '?')} on {rec['created_at']}. "
             f"Sample plans use budget {rec['budget_for_samples']} on {rec['prep_run']}.",
             f"Status: {'APPROVED ' + rec['approved_at'] if rec['approved_at'] else 'NOT APPROVED'}", ""]
    for i, it in enumerate(rec["items"], 1):
        lines += [f"## {i}. {it['advice']}", "", f"Interpretation: {it['interpretation'] or '-'}", ""]
        if not it["measurable"]:
            lines += ["Not measurable with the plan data: the planner reads it, it is not scored.", ""]
            continue
        c = it["check"]
        lines += ["Checks: " + ("passed" if c["passed"] else "FAILED: " + "; ".join(c["errors"]))]
        lines += [f"Warning: {w}" for w in c["warnings"]]
        lines += ["", "| Sample plan | Score |", "|---|---|"]
        lines += [f"| {k} | {v:.3f} |" for k, v in c["sample_scores"].items()]
        lines += ["", "```python", it["code"].rstrip(), "```", ""]
    return "\n".join(lines)


def load(advice_file: Path | str, root: Path | str = "data/advice", require_approved: bool = True) -> dict:
    items = read_advice(advice_file)
    p = store_dir(advice_file, items, root) / SCORING
    if not p.exists():
        raise FileNotFoundError(f"No scoring functions for {advice_file}: run `python -m leg.advice prepare` first")
    rec = json.loads(p.read_text(encoding="utf-8"))
    if require_approved and not rec.get("approved_at"):
        raise PermissionError(f"The scoring functions for {advice_file} are not approved yet: read {p.parent / REVIEW}, "
                              f"then run `python -m leg.advice approve {advice_file}`")
    return rec


def approve(advice_file: Path | str, root: Path | str = "data/advice") -> dict:
    load(advice_file, root, require_approved=False)  # clear error if it was never prepared
    return approve_dir(store_dir(advice_file, read_advice(advice_file), root))


# ------------------------------------------------------------------ scoring a plan
def alignment(rec: dict, plan: dict) -> dict:
    """Per-advice scores and their mean over the measurable advice (None if none is measurable)."""
    scores = []
    for it in rec["items"]:
        if not it["measurable"]:
            scores.append(None)
            continue
        v = run_score(it["code"], plan)
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"advice {it['advice']!r} scored {v}, outside 0-1")
        scores.append(round(v, 4))
    vals = [s for s in scores if s is not None]
    return {"scores": scores, "alignment": round(sum(vals) / len(vals), 4) if vals else None}


__all__ = ["FIELDS", "PlanBuilder", "read_advice", "prepare", "recheck", "approve", "load", "load_dir", "approve_dir", "recheck_dir", "list_sets", "STAGES", "alignment", "check_function"]
