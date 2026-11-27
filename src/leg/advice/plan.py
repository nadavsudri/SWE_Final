"""The plan record that advice scoring functions read.

A plan is what one round of the planner produced, described per district:

    {"budget": 10,
     "districts": [
        {"name": "Habru", "adm2": "North Wollo", "adm1": "Amhara",
         "population": 210000,            # people living in the district's populated cells
         "covered_before": 40000,         # within a two-hour walk of an existing facility
         "coverage_before_pct": 19.0,
         "covered_after": 95000,          # ... of an existing or a new facility
         "coverage_after_pct": 45.2,
         "existing_facilities": 3, "new_facilities": 2,
         "cells": 812,                    # populated ~1 km cells
         "fully_inside": True},           # the whole district is inside the planning area
        ...]}

The same record is used in the advice-file checks (sample plans) and in the LLM loop.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from leg.algo import Instance

FIELDS = ["name", "adm2", "adm1", "population", "covered_before", "coverage_before_pct", "covered_after",
          "coverage_after_pct", "existing_facilities", "new_facilities", "cells", "fully_inside"]


def district_keys(rows: list[dict]) -> list[str]:
    """A unique name per district: ADM3, or "ADM3 (ADM2)" when two districts share a name."""
    names = [r["ADM3"] for r in rows]
    return [r["ADM3"] if names.count(r["ADM3"]) == 1 else f"{r['ADM3']} ({r['ADM2'] or r['ADM1']})" for r in rows]


class PlanBuilder:
    """Turns chosen sites into a plan record, for one preprocessing run."""

    def __init__(self, inst: Instance, districts_csv: Path | str):
        self.inst = inst
        with open(districts_csv, newline="") as f:
            self.rows = list(csv.DictReader(f))
        self.keys = district_keys(self.rows)
        ids = {tuple(v): int(k) for k, v in inst.meta.get("districts", {}).items()}
        # district key -> instance district id (None: the district has no populated cell)
        self.key_to_id = {k: ids.get((r["ADM1"], r["ADM2"], r["ADM3"])) for k, r in zip(self.keys, self.rows)}
        self.id_to_key = {v: k for k, v in self.key_to_id.items() if v is not None}
        self.before = inst.weight == 0                     # covered by an existing facility
        self.cover_rows = [inst.cover.getrow(i).indices for i in range(inst.n_candidates)]

    @classmethod
    def from_run(cls, prep_dir: Path | str, max_minutes: float = 120.0) -> "PlanBuilder":
        return cls(Instance.load(prep_dir, max_minutes=max_minutes), Path(prep_dir) / "districts.csv")

    def allocation_ids(self, allocation: dict[str, int]) -> dict[int, int]:
        """{district key: n} -> {instance district id: n}; unknown keys raise."""
        unknown = [k for k in allocation if k not in self.key_to_id]
        if unknown:
            raise KeyError(f"unknown districts: {unknown}")
        return {self.key_to_id[k]: n for k, n in allocation.items() if self.key_to_id[k] is not None and n > 0}

    def plan(self, sites, budget: int) -> dict:
        inst = self.inst
        after = self.before.copy()
        for c in sites:
            after[self.cover_rows[inst.cand_index[int(c)]]] = True
        new = np.zeros(max(inst.district.max(initial=-1) + 1, 1), int)
        for c in sites:
            new[inst.district[int(c)]] += 1
        out = []
        for key, r in zip(self.keys, self.rows):
            d = self.key_to_id[key]
            if d is None:
                pop = cb = ca = cells = 0
            else:
                m = inst.district == d
                pop, cells = float(inst.population[m].sum()), int(m.sum())
                cb, ca = float(inst.population[m & self.before].sum()), float(inst.population[m & after].sum())
            out.append({"name": key, "adm2": r["ADM2"], "adm1": r["ADM1"], "population": round(pop),
                        "covered_before": round(cb), "coverage_before_pct": round(100 * cb / pop, 1) if pop else 0.0,
                        "covered_after": round(ca), "coverage_after_pct": round(100 * ca / pop, 1) if pop else 0.0,
                        "existing_facilities": int(r.get("existing_facilities") or 0),
                        "new_facilities": int(new[d]) if d is not None and d < len(new) else 0,
                        "cells": cells, "fully_inside": str(r.get("fully_inside", "1")) in ("1", "True", "true")})
        return {"budget": int(budget), "districts": out}
