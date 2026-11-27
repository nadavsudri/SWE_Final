"""A facility-location instance: who lives where, which candidate covers whom, which district is which.

Built from the paper's file format (population.csv + pairwise_costs.csv, written by leg.prep or by
the paper's own preprocessing), or directly from lists (tests, toy examples).

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
    def from_paper_files(cls, population_csv: Path | str, pairwise_csv: Path | str,
                         existing_csv: Path | str | None = None, year: int | None = None,
                         max_minutes: float = 120.0) -> "Instance":
        """Load the paper's format (population_*.csv + pairwise_costs_*.csv), ours or theirs.

        As in the paper's code: rows without ADM1 are skipped; districts are (ADM1, ADM2, ADM3);
        every populated cell is a candidate; a cell covers itself and every cell within
        `max_minutes` (pairs count both ways). `year` defaults to the earliest year in the file.
        Existing facilities (our existing.csv) make their cells and neighbours already covered."""
        with open(population_csv, newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["ADM1"].strip() and r["ADM1"] != "nan"]
        if not rows:
            raise ValueError(f"{population_csv} has no usable rows")
        year = year if year is not None else min(int(float(r["year"])) for r in rows)
        rows = [r for r in rows if int(float(r["year"])) == year]
        index: dict[int, int] = {}
        pop, dist, keys = [], [], {}
        for r in rows:
            c = int(float(r["cell"]))
            if c in index:
                continue
            index[c] = len(pop)
            pop.append(float(r["population"]))
            key = (r["ADM1"], r["ADM2"], r["ADM3"])
            dist.append(keys.setdefault(key, len(keys)))
        n = len(pop)
        src, dst = list(range(n)), list(range(n))  # every cell covers itself
        with open(pairwise_csv, newline="") as f:
            for r in csv.DictReader(f):
                d = r["distance"]
                if not d or d == "nan" or float(d) > max_minutes:
                    continue
                i, j = index.get(int(float(r["cell_i"]))), index.get(int(float(r["cell_j"])))
                if i is None or j is None:
                    continue
                src += [i, j]
                dst += [j, i]
        A = sparse.csr_matrix((np.ones(len(src)), (src, dst)), shape=(n, n))
        A.data[:] = 1.0  # duplicate pairs collapse to 1
        pop_a = np.asarray(pop)
        done = np.zeros(n, bool)
        if existing_csv is not None and Path(existing_csv).exists():
            with open(existing_csv, newline="") as f:
                ex = [index[int(float(r["cell"]))] for r in csv.DictReader(f) if int(float(r["cell"])) in index]
            if ex:
                done = np.asarray(A[sorted(set(ex))].sum(axis=0)).ravel() > 0
        names = {v: k[2] for k, v in keys.items()}
        inst = cls(np.where(done, 0.0, pop_a), pop_a, np.asarray(dist), np.arange(n), A, names)
        inst.meta = {"year": year, "max_minutes": max_minutes, "districts": {v: list(k) for k, v in keys.items()},
                     "cell_ids": list(index)}
        return inst

    @classmethod
    def load(cls, prep_dir: Path | str, year: int | None = None, max_minutes: float = 120.0) -> "Instance":
        """A preprocessing output folder (population.csv, pairwise_costs.csv, existing.csv, meta.json)."""
        d = Path(prep_dir)
        inst = cls.from_paper_files(d / "population.csv", d / "pairwise_costs.csv", d / "existing.csv",
                                    year, max_minutes)
        if (d / "meta.json").exists():
            inst.meta = json.loads((d / "meta.json").read_text()) | inst.meta
        inst.meta["prep_dir"] = str(d)
        return inst
