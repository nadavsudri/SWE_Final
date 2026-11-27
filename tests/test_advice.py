"""Advice file -> LLM-written scoring functions -> checks -> approval -> alignment."""
import json

import pytest

from leg import advice as adv
from leg.advice.plan import PlanBuilder
from leg.advice.sandbox import UnsafeCode, check_code, compile_score, run_score
from leg.prep import PrepParams, build
from test_prep import AREA, make_inputs

GOOD = "def score(plan):\n    ds = plan['districts']\n    return sum(1 for d in ds if d['new_facilities'] >= 1) / len(ds)\n"
LOW_COVERAGE_FIRST = ("def score(plan):\n    low = [d for d in plan['districts'] if d['coverage_before_pct'] < 50]\n"
                      "    if not low:\n        return 1.0\n"
                      "    return sum(d['new_facilities'] for d in low) / max(plan['budget'], 1)\n")


@pytest.fixture
def run(tmp_path):
    wp, bd, fc, fr, parents = make_inputs(tmp_path / "raw")
    return build(wp, bd, [fc], fr, AREA, tmp_path / "out", "ETH_t", PrepParams(max_minutes=30), parents=parents)


def fake_llm(codes, measurable=None):
    def llm(prompt):
        assert "def score(plan)" in prompt and "Example plan" in prompt
        items = [{"advice": f"a{i}", "measurable": True if measurable is None else measurable[i],
                  "interpretation": f"reading {i}", "code": c} for i, c in enumerate(codes)]
        return {"items": items}, {"model": "fake", "input_tokens": 100, "output_tokens": 50}
    return llm


# ---------------------------------------------------------------- the advice file
def test_read_advice_text_and_json(tmp_path):
    t = tmp_path / "a.txt"
    t.write_text("# expert notes\n1. Every district gets one\n\n- עדיפות למחוזות עם כיסוי נמוך\n", encoding="utf-8")
    assert adv.read_advice(t) == ["Every district gets one", "עדיפות למחוזות עם כיסוי נמוך"]
    j = tmp_path / "a.json"
    j.write_text(json.dumps(["x", "y"]))
    assert adv.read_advice(j) == ["x", "y"]
    (tmp_path / "e.txt").write_text("# nothing\n")
    with pytest.raises(ValueError, match="no advice"):
        adv.read_advice(tmp_path / "e.txt")
    (tmp_path / "d.txt").write_text("x\nx\n")
    with pytest.raises(ValueError, match="twice"):
        adv.read_advice(tmp_path / "d.txt")


def test_store_dir_changes_with_the_text(tmp_path):
    assert adv.store_dir("my advice.txt", ["a"]) != adv.store_dir("my advice.txt", ["a", "b"])
    assert adv.store_dir("my advice.txt", ["a"]).name.startswith("my-advice_")


# ---------------------------------------------------------------- sandbox
@pytest.mark.parametrize("code", [
    "import os\ndef score(plan):\n    return 1.0",
    "def score(plan):\n    return open('x').read()",
    "def score(plan):\n    return ().__class__",
    "def score(plan):\n    return __import__('os')",
    "def score(plan):\n    while True:\n        pass",
    "def score(plan):\n    return eval('1')",
    "def other(plan):\n    return 1.0",
    "class A:\n    pass\ndef score(plan):\n    return 1.0",
])
def test_sandbox_rejects(code):
    with pytest.raises((UnsafeCode, NameError)):
        check_code(code)
        compile_score(code)({"districts": []})


def test_sandbox_runs_plain_python_and_math():
    code = "def score(plan):\n    return math.sqrt(sum(d['x'] for d in plan['districts'])) / 10\n"
    assert run_score(code, {"districts": [{"x": 4}, {"x": 5}]}) == pytest.approx(0.3)
    with pytest.raises(ValueError, match="range larger"):
        run_score("def score(plan):\n    return len(range(10**9))\n", {})
    with pytest.raises(ValueError, match="not a number"):
        run_score("def score(plan):\n    return 'high'\n", {})


# ---------------------------------------------------------------- plan record
def test_plan_builder(run):
    pb = PlanBuilder.from_run(run, max_minutes=30)
    empty = pb.plan([], 2)
    names = {d["name"] for d in empty["districts"]}
    assert names == {"West", "East"} and set(empty["districts"][0]) == set(adv.FIELDS)
    west = next(d for d in empty["districts"] if d["name"] == "West")
    assert west["existing_facilities"] == 1 and 0 < west["covered_before"] < west["population"]
    assert west["covered_after"] == west["covered_before"] and west["new_facilities"] == 0
    east_id = pb.key_to_id["East"]
    cell = int(next(i for i in range(pb.inst.n_cells) if pb.inst.district[i] == east_id))
    p = pb.plan([cell], 1)
    east = next(d for d in p["districts"] if d["name"] == "East")
    assert east["new_facilities"] == 1 and east["covered_after"] > east["covered_before"]
    with pytest.raises(KeyError):
        pb.allocation_ids({"Nowhere": 1})


# ---------------------------------------------------------------- prepare / checks / approve
def test_prepare_checks_and_saves(run, tmp_path):
    f = tmp_path / "advice.txt"
    f.write_text("a0\na1\na2\na3\na4\n")
    codes = [GOOD, None, "import os\ndef score(plan):\n    return 1.0",
             "def score(plan):\n    return 2.0\n", "def score(plan):\n    return 0.5\n"]
    d = adv.prepare(f, run, budget=2, llm=fake_llm(codes, [True, False, True, True, True]), root=tmp_path / "adv")
    rec = json.loads((d / adv.SCORING).read_text())
    it = rec["items"]
    assert it[0]["check"]["passed"] and len(it[0]["check"]["sample_scores"]) == 5
    assert not it[1]["measurable"] and it[1]["code"] is None and it[1]["check"] is None
    assert "unsafe" in it[2]["check"]["errors"][0]
    assert "outside 0-1" in it[3]["check"]["errors"][0]
    assert it[4]["check"]["passed"] and "same score" in it[4]["check"]["warnings"][0]
    assert rec["approved_at"] is None and rec["llm_usage"]["model"] == "fake"
    review = (d / adv.REVIEW).read_text()
    assert "NOT APPROVED" in review and "Not measurable" in review and "def score" in review
    with pytest.raises(PermissionError, match="not approved"):
        adv.load(f, tmp_path / "adv")
    with pytest.raises(ValueError, match=r"advice \[3, 4\] failed"):
        adv.approve(f, tmp_path / "adv")


def test_approve_then_alignment(run, tmp_path):
    f = tmp_path / "advice.txt"
    f.write_text("one new facility per district\nlow coverage first\nnear the main road\n")
    adv.prepare(f, run, budget=2, llm=fake_llm([GOOD, LOW_COVERAGE_FIRST, None], [True, True, False]),
                root=tmp_path / "adv")
    adv.approve(f, tmp_path / "adv")
    rec = adv.load(f, tmp_path / "adv")
    assert rec["approved_at"]
    pb = PlanBuilder.from_run(run, max_minutes=30)
    cells = {}
    for i in range(pb.inst.n_cells):
        cells.setdefault(pb.id_to_key[int(pb.inst.district[i])], i)
    both = pb.plan([cells["West"], cells["East"]], 2)
    r = adv.alignment(rec, both)
    assert r["scores"][0] == 1.0 and r["scores"][2] is None
    assert r["alignment"] == pytest.approx((1.0 + r["scores"][1]) / 2)
    # editing the advice file means new functions and a new approval
    f.write_text("one new facility per district\n")
    with pytest.raises(FileNotFoundError):
        adv.load(f, tmp_path / "adv")


def test_llm_must_answer_every_advice(run, tmp_path):
    f = tmp_path / "advice.txt"
    f.write_text("a\nb\n")
    with pytest.raises(ValueError, match="1 items for 2 advice"):
        adv.prepare(f, run, llm=fake_llm([GOOD]), root=tmp_path / "adv")


def test_slow_function_is_stopped():
    slow = "def score(plan):\n    t = 0\n    for i in range(100000):\n        for j in range(100000):\n            t += 1\n    return 1.0\n"
    r = adv.check_function(slow, {"p": {"districts": []}}, timeout=1)
    assert not r["passed"] and "did not finish" in r["errors"][0]


def test_cli(run, tmp_path, monkeypatch, capsys):
    from leg.advice.__main__ import main
    f = tmp_path / "advice.txt"
    f.write_text("one new facility per district\n")
    monkeypatch.setattr(adv, "claude_llm", lambda model=None: fake_llm([GOOD]))
    root = str(tmp_path / "adv")
    assert main(["prepare", str(f), "--prep", str(run), "--budget", "2", "--root", root]) == 0
    assert "checks passed" in capsys.readouterr().out
    assert main(["show", str(f), "--root", root]) == 0 and "NOT APPROVED" in capsys.readouterr().out
    assert main(["approve", str(f), "--root", root]) == 0 and "Approved" in capsys.readouterr().out
    monkeypatch.setattr(adv, "claude_llm", lambda model=None: (_ for _ in ()).throw(RuntimeError("needs the Claude API key")))
    assert main(["prepare", str(f), "--prep", str(run), "--root", root]) == 1


def test_list_methods_allowed_and_plan_is_copied():
    code = ("def score(plan):\n    xs = []\n    for d in plan['districts']:\n        xs.append(d['n'])\n"
            "    plan['districts'].pop()\n    xs.sort()\n"
            "    return xs[0] / 10\n")
    plan = {"districts": [{"n": 3}, {"n": 1}]}
    assert run_score(code, plan) == pytest.approx(0.1)
    assert len(plan["districts"]) == 2          # the caller's plan is untouched
    with pytest.raises(UnsafeCode):
        check_code("def score(plan):\n    return '{0.__class__}'.format(plan)\n")


def test_recheck_without_llm(run, tmp_path):
    from leg.advice.__main__ import main
    f = tmp_path / "advice.txt"
    f.write_text("a\n")
    bad = "def score(plan):\n    return 2.0\n"
    adv.prepare(f, run, budget=2, llm=fake_llm([bad]), root=tmp_path / "adv")
    d = adv.store_dir(f, ["a"], tmp_path / "adv")
    rec = json.loads((d / adv.SCORING).read_text())
    rec["items"][0]["code"] = GOOD                     # e.g. a person fixed the code by hand
    (d / adv.SCORING).write_text(json.dumps(rec))
    assert main(["recheck", str(f), "--root", str(tmp_path / "adv")]) == 0
    assert adv.load(f, tmp_path / "adv", require_approved=False)["items"][0]["check"]["passed"]
