"""Baselines: exact maximum coverage (MCLP) as an integer program, and random placement."""
from __future__ import annotations

import time
from dataclasses import dataclass

import highspy
import numpy as np
from scipy import sparse

from leg.algo.coverage import coverage
from leg.algo.instance import Instance


@dataclass
class IlpResult:
    sites: list[int]
    value: float            # coverage of the best solution found
    optimal: bool           # proven optimal
    upper_bound: float      # proven upper bound on OPT (== value when optimal)
    gap: float              # (upper_bound - value) / upper_bound
    seconds: float
    status: str


def ilp(inst: Instance, b: int, time_limit: float = 60.0, warm_start: list[int] | None = None) -> IlpResult:
    """Maximal Covering Location Problem, solved with HiGHS:

        max  sum_i w_i y_i
        s.t. y_i <= sum_{j covers i} x_j     for every cell i that some candidate covers
             sum_j x_j = b
             x_j in {0,1},  0 <= y_i <= 1

    y can stay continuous: at an optimum each y_i is 1 exactly when cell i is covered.
    Only cells with weight > 0 get a y variable (the rest cannot change the objective).
    warm_start (e.g. the greedy sites) gives the solver a first solution, so on large instances
    that hit the time limit the result is never worse than that start."""
    if not 0 <= b <= inst.n_candidates:
        raise ValueError(f"budget b={b} must be between 0 and {inst.n_candidates}")
    t0 = time.perf_counter()
    A = inst.cover.tocsc()
    reach = np.flatnonzero((np.asarray(A.sum(axis=0)).ravel() > 0) & (inst.weight > 0))
    A = A[:, reach].tocsr()                               # candidates x relevant cells
    nx, ny = A.shape
    M = sparse.vstack([sparse.hstack([-A.T, sparse.identity(ny)]),           # y_i - sum x_j <= 0
                       sparse.hstack([sparse.csr_matrix(np.ones((1, nx))), sparse.csr_matrix((1, ny))])
                       ]).tocsc()
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = nx + ny, ny + 1
    lp.col_cost_ = np.concatenate([np.zeros(nx), -inst.weight[reach]])
    lp.col_lower_, lp.col_upper_ = np.zeros(nx + ny), np.ones(nx + ny)
    lp.row_lower_ = np.concatenate([np.full(ny, -highspy.kHighsInf), [b]])
    lp.row_upper_ = np.concatenate([np.zeros(ny), [b]])
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = M.indptr, M.indices, M.data
    lp.integrality_ = [highspy.HighsVarType.kInteger] * nx + [highspy.HighsVarType.kContinuous] * ny
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(time_limit))
    h.passModel(lp)
    if warm_start:
        x0 = np.zeros(nx)
        x0[[inst.cand_index[int(c)] for c in warm_start]] = 1
        y0 = np.minimum(1, A.T @ x0)
        sol = highspy.HighsSolution()
        sol.col_value = list(np.concatenate([x0, y0]))
        h.setSolution(sol)
    h.run()
    secs = time.perf_counter() - t0
    status = h.modelStatusToString(h.getModelStatus())
    x = np.asarray(h.getSolution().col_value[:nx])
    if x.size != nx or not np.isfinite(x).all():
        raise RuntimeError(f"ILP found no solution within {time_limit}s: {status}")
    sites = [int(inst.candidates[j]) for j in np.argsort(-x, kind="stable")[:b]]
    value = coverage(inst, sites)                     # recomputed, not trusted from the solver
    optimal = h.getModelStatus() == highspy.HighsModelStatus.kOptimal
    bound = -float(h.getInfo().mip_dual_bound)
    if optimal:
        bound = value
    elif not np.isfinite(bound) or bound <= 0:
        bound = float(inst.weight[reach].sum())
    gap = 0.0 if optimal or bound <= 0 else max(0.0, (bound - value) / bound)
    return IlpResult(sites, value, optimal, bound, gap, secs, status)


def random_sites(inst: Instance, b: int, seed: int) -> list[int]:
    """b distinct candidates chosen uniformly at random (seeded, so runs repeat)."""
    if not 0 <= b <= inst.n_candidates:
        raise ValueError(f"budget b={b} must be between 0 and {inst.n_candidates}")
    rng = np.random.default_rng(seed)
    return [int(c) for c in rng.choice(inst.candidates, size=b, replace=False)]
