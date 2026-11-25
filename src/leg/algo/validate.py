"""Checks every method's output against the hard constraints. Problems are reported, never hidden."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from leg.algo.coverage import coverage
from leg.algo.instance import Instance


@dataclass
class Report:
    ok: bool
    errors: list[str] = field(default_factory=list)
    value: float = 0.0
    guarantee: float | None = None   # (1 - e^(-alpha*beta)) * OPT, when OPT is known


def check(inst: Instance, sites, b: int, alpha: float | None = None, beta: float | None = None,
          opt: float | None = None, start=()) -> Report:
    errors = []
    sites = [int(c) for c in sites]
    if len(sites) != b:
        errors.append(f"expected {b} sites, got {len(sites)}")
    if len(set(sites)) != len(sites):
        errors.append("duplicate sites")
    not_cand = [c for c in sites if c not in inst.cand_index]
    if not_cand:
        errors.append(f"not candidate cells: {not_cand[:10]}")
    clash = set(sites) & {int(c) for c in start}
    if clash:
        errors.append(f"sites already built: {sorted(clash)[:10]}")
    value = coverage(inst, [c for c in sites if c in inst.cand_index])
    bound = None
    if opt is not None and alpha is not None and beta is not None:
        bound = (1 - math.exp(-alpha * beta)) * opt
        if value + 1e-6 < bound:
            errors.append(f"coverage {value:.1f} below the guarantee {bound:.1f}")
    if opt is not None and value > opt + 1e-6:
        errors.append(f"coverage {value:.1f} above the optimum {opt:.1f}: OPT is wrong")
    return Report(not errors, errors, value, bound)
