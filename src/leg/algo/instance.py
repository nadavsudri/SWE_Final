"""A facility-location instance: who lives where, which candidate covers whom, which district is which.

Built from the preprocessing output folder (cells.csv, coverage.json, districts.csv, meta.json)
or directly from arrays (tests, toy examples).

Objective (as in the paper, Eq. 1): f(S) = population in cells covered by at least one site in S.
Cells already covered by an existing facility count 0, so f measures the *improvement* in
coverage, which is what new facilities can change.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import sparse


@dataclass
class Instance:
    weight: np.ndarray            # per cell: population not yet covered (0 if already covered)
    population: np.ndarray        # per cell: total population
    district: np.ndarray          # per cell: district id, -1 = none
    candidates: np.ndarray        # cell ids where a facility may be placed
    cover: sparse.csr_matrix      # rows = candidates (same order), cols = cells, 1 = covers
    district_names: dict[int, str] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        self.candidates = np.asarray(self.candidates, dtype=int)
        self.cand_index = {int(c): i for i, c in enumerate(self.candidates)}
        self.cand_district = self.district[self.candidates]

    @property
    def n_cells(self) -> int:
        return len(self.weight)

    @property
    def n_candidates(self) -> int:
        return len(self.candidates)

    def districts(self) -> list[int]:
        return sorted(int(d) for d in np.unique(self.district) if d >= 0)

    @classmethod
    def from_lists(cls, population, district, cover: dict[int, list[int]], already_covered=None,
                   district_names=None) -> "Instance":
        """Small instances by hand: cover = {candidate cell: [cells it covers]}."""
        pop = np.asarray(population, dtype=float)
        dist = np.asarray(district, dtype=int)
        done = np.zeros(len(pop), bool) if already_covered is None else np.asarray(already_covered, bool)
        cands = sorted(cover)
        rows, cols = [], []
        for i, c in enumerate(cands):
            rows += [i] * len(cover[c])
            cols += list(cover[c])
        A = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(cands), len(pop)))
        return cls(np.where(done, 0.0, pop), pop, dist, np.array(cands), A, district_names or {})

    @classmethod
    def load(cls, prep_dir: Path | str) -> "Instance":
        d = Path(prep_dir)
        with open(d / "cells.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        n = len(rows)
        pop = np.zeros(n)
        dist = np.full(n, -1, dtype=int)
        done = np.zeros(n, bool)
        for r in rows:
            i = int(r["cell_id"])
            pop[i] = float(r["population"])
            dist[i] = int(r["district_id"])
            done[i] = r["already_covered"] == "1"
        cov = {int(k): v for k, v in json.loads((d / "coverage.json").read_text()).items()}
        names = {}
        if (d / "districts.csv").exists():
            with open(d / "districts.csv", newline="") as f:
                names = {int(r["district_id"]): r["name"] for r in csv.DictReader(f)}
        inst = cls.from_lists(pop, dist, cov, done, names)
        inst.meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        inst.meta["prep_dir"] = str(d)
        return inst
