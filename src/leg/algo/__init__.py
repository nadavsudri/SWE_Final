"""Placement algorithms: greedy, GuidedGreedy (LEG Algorithm 2), exact ILP and random baselines,
plus output validation. The LLM loop (Algorithm 1) builds on these."""
from leg.algo.baselines import IlpResult, ilp, random_sites
from leg.algo.coverage import CoverageState, coverage, district_counts
from leg.algo.greedy import Result, greedy, guided_greedy, protected_picks
from leg.algo.instance import Instance
from leg.algo.validate import Report, check

__all__ = ["Instance", "CoverageState", "coverage", "district_counts", "greedy", "guided_greedy",
           "protected_picks", "Result", "ilp", "IlpResult", "random_sites", "check", "Report"]
