"""Algorithm tests. The toy instance is small enough to check every answer by hand."""
import math

import numpy as np
import pytest

from leg.algo import (Instance, check, coverage, district_counts, greedy, guided_greedy, ilp,
                      protected_picks, random_sites)

A, B = 0, 1


@pytest.fixture
def toy():
    """4 candidates, each covering only its own cell.
    District A: cell 0 (4 people), cell 1 (6).  District B: cell 2 (10), cell 3 (2)."""
    return Instance.from_lists([4, 6, 10, 2], [A, A, B, B], {0: [0], 1: [1], 2: [2], 3: [3]},
                               district_names={A: "A", B: "B"})


# ---------------------------------------------------------------- hand-checked example
def test_greedy_by_hand(toy):
    r = greedy(toy, 2)
    assert r.sites == [2, 1] and r.value == 16
    assert district_counts(toy, r.sites) == {B: 1, A: 1}


def test_llm_in_full_control(toy):  # alpha = 0: follow the allocation
    r = guided_greedy(toy, 2, {A: 2}, alpha=0, beta=1)
    assert r.sites == [1, 0] and r.value == 10
    assert [p["rule"] for p in r.picks] == ["allocation", "allocation"]


def test_alpha1_beta1_is_plain_greedy(toy):
    assert guided_greedy(toy, 2, {A: 2}, alpha=1, beta=1).sites == greedy(toy, 2).sites


def test_beta_half_by_hand(toy):
    # pick 1: best anywhere 10 (cell 2), best in A 6 >= 0.5*10 -> take cell 1
    # pick 2: best anywhere 10, best in A 4 < 5 -> override, take cell 2
    r = guided_greedy(toy, 2, {A: 2}, alpha=1, beta=0.5)
    assert r.sites == [1, 2] and r.value == 16
    assert [p["rule"] for p in r.picks] == ["allocation_checked", "override"]


def test_only_first_ceil_alpha_b_picks_are_checked(toy):
    assert protected_picks(0.5, 2) == 1 and protected_picks(0.25, 3) == 1 and protected_picks(1, 3) == 3
    r = guided_greedy(toy, 2, {A: 2}, alpha=0.5, beta=0.5)   # second pick unchecked
    assert r.sites == [1, 0]
    assert [p["rule"] for p in r.picks] == ["allocation_checked", "allocation"]


# ---------------------------------------------------------------- coverage semantics
def test_overlap_counted_once_and_already_covered_is_zero():
    inst = Instance.from_lists([5, 5, 5], [0, 0, 0], {0: [0, 1], 1: [1, 2]}, already_covered=[0, 0, 1])
    assert coverage(inst, [0]) == 10
    assert coverage(inst, [1]) == 5            # cell 2 already covered
    assert coverage(inst, [0, 1]) == 10        # cell 1 counted once
    assert greedy(inst, 2).picks[1]["gain"] == 0


# ---------------------------------------------------------------- edge cases
def test_zero_budget(toy):
    assert greedy(toy, 0).sites == [] and guided_greedy(toy, 0, {}, 1, 1).sites == []


def test_budget_above_candidates(toy):
    with pytest.raises(ValueError, match="exceeds"):
        greedy(toy, 5)


def test_allocation_short_of_budget_falls_back(toy):
    r = guided_greedy(toy, 2, {A: 1}, alpha=0, beta=1)
    assert r.sites == [1, 2] and [p["rule"] for p in r.picks] == ["allocation", "fallback"]


def test_district_without_free_candidates_falls_back(toy):
    r = guided_greedy(toy, 3, {A: 3}, alpha=0, beta=1)       # A has only 2 cells
    assert r.sites == [1, 0, 2] and r.picks[-1]["rule"] == "fallback"


@pytest.mark.parametrize("alloc", [{7: 1}, {A: -1}])
def test_bad_allocation_rejected(toy, alloc):
    with pytest.raises(ValueError):
        guided_greedy(toy, 1, alloc, 1, 1)


@pytest.mark.parametrize("a,b", [(-0.1, 1), (1, 1.5)])
def test_bad_alpha_beta(toy, a, b):
    with pytest.raises(ValueError):
        guided_greedy(toy, 1, {A: 1}, a, b)


def test_start_sites_are_kept(toy):
    r = greedy(toy, 1, start=[2])
    assert r.sites == [1] and r.value == 16


# ---------------------------------------------------------------- validation
def test_check_catches_bad_outputs(toy):
    assert check(toy, [2, 1], 2).ok
    rep = check(toy, [2, 2, 9], 2)
    assert not rep.ok and len(rep.errors) == 3   # size, duplicates, non-candidate
    assert not check(toy, [0, 3], 2, alpha=1, beta=1, opt=16).ok  # 6 < 0.632*16


# ---------------------------------------------------------------- random instances vs the ILP optimum
def random_instance(seed, n=60, n_cand=25, k=6):
    rng = np.random.default_rng(seed)
    pop = rng.integers(0, 50, n).astype(float)
    dist = rng.integers(0, 4, n)
    cands = rng.choice(n, n_cand, replace=False)
    cover = {int(c): sorted(set(rng.choice(n, k, replace=False)) | {int(c)}) for c in cands}
    return Instance.from_lists(pop, dist, cover, already_covered=rng.random(n) < 0.1)


@pytest.mark.parametrize("seed", range(8))
def test_guarantees_against_optimum(seed):
    inst = random_instance(seed)
    b = 5
    opt = ilp(inst, b, time_limit=30)
    assert opt.optimal and opt.value >= greedy(inst, b).value - 1e-9
    assert greedy(inst, b).value >= (1 - 1 / math.e) * opt.value - 1e-9
    rng = np.random.default_rng(seed)
    for alpha, beta in [(1, 1), (0.6, 0.8), (1, 0.5), (0.4, 1)]:
        alloc = {d: int(x) for d, x in zip(inst.districts(), rng.multinomial(b, [0.25] * 4))}
        r = guided_greedy(inst, b, alloc, alpha, beta)
        rep = check(inst, r.sites, b, alpha, beta, opt=opt.value)
        assert rep.ok, rep.errors


def test_ilp_on_toy(toy):
    r = ilp(toy, 2)
    assert r.optimal and r.value == 16 and sorted(r.sites) == [1, 2] and r.gap == 0


def test_random_is_seeded(toy):
    assert random_sites(toy, 2, seed=3) == random_sites(toy, 2, seed=3)
    assert check(toy, random_sites(toy, 3, seed=1), 3).ok


# ---------------------------------------------------------------- end to end from preprocessing output
def test_load_prep_output_and_cli(tmp_path, capsys):
    import json
    from leg.algo.__main__ import main
    from leg.prep import PAIR_COLS
    d = tmp_path / "prep"
    d.mkdir()
    # cells 10..14: populations 4, 6, 10, 2, 3; districts North (10, 11) and South (12, 13, 14)
    rows = [(10, 4, "North"), (11, 6, "North"), (12, 10, "South"), (13, 2, "South"), (14, 3, "South")]
    (d / "population.csv").write_text("cell,lat,lon,ADM1,ADM2,ADM3,population,year\n" + "".join(
        f"{c},0,0,R,Z,{n},{p},2026\n" for c, p, n in rows))
    pair = lambda i, j, m: f"{i},{j},0,0,0,0,R,Z,x,R,Z,y,{m}\n"
    (d / "pairwise_costs.csv").write_text(",".join(PAIR_COLS) + "\n" + pair(11, 14, 30) + pair(12, 13, 90)
                                          + pair(10, 12, 121))
    (d / "existing.csv").write_text("cell,lat,lon,source,name,type,snapped_km\n13,0,0,osm,x,clinic,0\n")
    (d / "meta.json").write_text("{}")
    inst = Instance.load(d)
    # cell 13 has a facility; it also covers 12 (90 min) -> both already covered
    assert inst.weight.tolist() == [4, 6, 0, 0, 3] and inst.district_names == {0: "North", 1: "South"}
    assert coverage(inst, [1]) == 9            # cell 11 covers itself and 14 (30 min)
    assert coverage(inst, [0]) == 4            # 121 min is past the 2-hour cutoff
    out = tmp_path / "r.json"
    assert main([str(d), "--b", "2", "--allocation", "0:2", "--alpha", "0", "--beta", "1",
                 "--out", str(out)]) == 0
    res = json.loads(out.read_text())["runs"]
    assert res["ilp"]["optimal"] and res["ilp"]["value"] == 13 and res["greedy"]["value"] == 13
    assert res["guided(a=0.0,b=1.0)"]["value"] == 13
    assert "valid" in capsys.readouterr().out
    # the paper's files directly
    assert main(["--population", str(d / "population.csv"), "--pairwise", str(d / "pairwise_costs.csv"),
                 "--b", "1", "--ilp-time", "0"]) == 0


def test_ilp_warm_start_never_worse_than_greedy_under_time_pressure():
    inst = random_instance(42, n=400, n_cand=200, k=25)
    g = greedy(inst, 15)
    r = ilp(inst, 15, time_limit=0.05, warm_start=g.sites)
    assert r.value >= g.value - 1e-9
    assert r.upper_bound >= r.value - 1e-9
