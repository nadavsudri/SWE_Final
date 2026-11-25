"""Coverage f(S), marginal gains and per-district counts h(S)."""
from __future__ import annotations

from collections import Counter

import numpy as np

from leg.algo.instance import Instance


class CoverageState:
    """Tracks what the chosen sites cover. Gains for all candidates come from one sparse
    matrix-vector product, so each greedy step is exact and fast (no lazy-greedy bookkeeping)."""

    def __init__(self, inst: Instance, start=()):
        self.inst = inst
        self.remaining = inst.weight.copy()   # weight of cells not covered yet
        self.chosen: list[int] = []
        self._mask = np.zeros(inst.n_candidates, bool)
        for c in start:
            self.add(c)

    def gains(self) -> np.ndarray:
        """Marginal gain of every candidate (chosen ones get -inf)."""
        g = self.inst.cover @ self.remaining
        g[self._mask] = -np.inf
        return g

    def add(self, cell: int) -> float:
        i = self.inst.cand_index.get(int(cell))
        if i is None:
            raise ValueError(f"cell {cell} is not a candidate")
        if self._mask[i]:
            raise ValueError(f"cell {cell} already chosen")
        row = self.inst.cover.getrow(i).indices
        gain = float(self.remaining[row].sum())
        self.remaining[row] = 0.0
        self._mask[i] = True
        self.chosen.append(int(cell))
        return gain

    @property
    def value(self) -> float:
        return float(self.inst.weight.sum() - self.remaining.sum())


def coverage(inst: Instance, S) -> float:
    """f(S): population newly covered by the sites in S (overlaps counted once)."""
    covered = np.zeros(inst.n_cells, bool)
    for c in S:
        covered[inst.cover.getrow(inst.cand_index[int(c)]).indices] = True
    return float(inst.weight[covered].sum())


def district_counts(inst: Instance, S) -> dict[int, int]:
    """h(S): number of chosen sites per district (-1 = outside every district)."""
    return dict(Counter(int(inst.district[int(c)]) for c in S))
