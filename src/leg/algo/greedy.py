"""Greedy (Nemhauser et al. 1978) and GuidedGreedy (Algorithm 2 of the LEG paper).

Ties are broken by the lowest cell id, so every run is deterministic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from leg.algo.coverage import CoverageState
from leg.algo.instance import Instance


@dataclass
class Result:
    sites: list[int]                      # chosen candidate cell ids, in pick order
    value: float                          # f(S)
    picks: list[dict] = field(default_factory=list)  # per pick: cell, gain, rule


def _argmax(gains: np.ndarray, inst: Instance, allowed: np.ndarray | None = None) -> int | None:
    g = gains if allowed is None else np.where(allowed, gains, -np.inf)
    if not np.isfinite(g).any():
        return None
    best = g.max()
    ties = np.flatnonzero(g == best)
    return int(ties[np.argmin(inst.candidates[ties])])  # index into candidates


def _check_budget(inst: Instance, b: int, start) -> None:
    if b < 0:
        raise ValueError("budget b must be >= 0")
    if b > inst.n_candidates - len(start):
        raise ValueError(f"budget b={b} exceeds the {inst.n_candidates - len(start)} free candidate cells")


def greedy(inst: Instance, b: int, start=()) -> Result:
    """Plain greedy: b times, take the candidate with the largest marginal gain."""
    _check_budget(inst, b, start)
    st = CoverageState(inst, start)
    picks = []
    for _ in range(b):
        i = _argmax(st.gains(), inst)
        cell = int(inst.candidates[i])
        picks.append({"cell": cell, "gain": st.add(cell), "rule": "greedy"})
    return Result(st.chosen[len(start):], st.value, picks)


def protected_picks(alpha: float, b: int) -> int:
    """Number of picks checked against the global best (first ceil(alpha*b) picks).

    The paper's pseudocode writes the check as |S| <= ceil(alpha*b), which would protect one
    pick more. We protect exactly ceil(alpha*b), which is what the guarantee
    f(S) >= (1 - e^(-alpha*beta)) * OPT needs."""
    return math.ceil(alpha * b - 1e-12)


def guided_greedy(inst: Instance, b: int, allocation: dict[int, int], alpha: float, beta: float,
                  start=()) -> Result:
    """GuidedGreedy (Algorithm 2).

    allocation: {district id: number of facilities} proposed by the planner (the LLM).
    The first ceil(alpha*b) picks are protected: the best cell inside a district that still has
    budget is taken only if its gain is >= beta * (best gain anywhere); otherwise the global best
    is taken and the allocation is not charged. Later picks always follow the allocation.
    If no district has budget left (or has no free candidates), the global best is taken
    ("fallback"). Guarantee: f(S) >= (1 - e^(-alpha*beta)) * OPT.
    """
    if not (0 <= alpha <= 1 and 0 <= beta <= 1):
        raise ValueError("alpha and beta must be in [0, 1]")
    known = set(inst.districts())
    bad = {k: v for k, v in allocation.items() if int(k) not in known or int(v) < 0}
    if bad:
        raise ValueError(f"allocation has unknown districts or negative counts: {bad}")
    _check_budget(inst, b, start)

    left = {int(k): int(v) for k, v in allocation.items()}
    protected = protected_picks(alpha, b)
    st = CoverageState(inst, start)
    picks = []
    for k in range(b):
        gains = st.gains()
        i_any = _argmax(gains, inst)
        in_budget = np.array([left.get(int(d), 0) > 0 for d in inst.cand_district])
        i_d = _argmax(gains, inst, in_budget)
        if i_d is None:
            i, rule = i_any, "fallback"
        elif k >= protected:
            i, rule = i_d, "allocation"
        elif gains[i_d] >= beta * gains[i_any]:
            i, rule = i_d, "allocation_checked"
        else:
            i, rule = i_any, "override"
        cell = int(inst.candidates[i])
        if rule.startswith("allocation"):
            left[int(inst.cand_district[i])] -= 1
        picks.append({"cell": cell, "gain": st.add(cell), "rule": rule,
                      "best_anywhere": float(gains[i_any])})
    return Result(st.chosen[len(start):], st.value, picks)
