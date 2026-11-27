# Advice scoring review: advice_eth.txt

Written by claude-sonnet-5-5 on 2026-11-27T17:35:23+00:00. Sample plans use budget 10 on data/processed/eth_negev_6dfcdf57/2026-11-25T132613Z.
Status: in use (used automatically, 2026-11-27T17:36:05+00:00).

## 1. Prioritise districts where fewer than 10% of people live within two hours of a facility.

Interpretation: Score is the share of new facilities placed in districts whose coverage before the plan is under 10%. If the plan has no new facilities, or no district is under 10%, the advice has nothing to act on and the score is 1.0.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 0.900 |
| all in the most populated district | 1.000 |
| all in the least covered district | 1.000 |
| spread one by one, most populated first | 0.900 |
| by population | 0.900 |

```python
def score(plan):
    ds = plan.get('districts', [])
    total = 0
    low = 0
    anylow = False
    for d in ds:
        pop = d.get('population', 0)
        if pop > 0:
            pct = d['covered_before'] / pop * 100.0
        else:
            pct = d.get('coverage_before_pct', 0.0)
        n = d.get('new_facilities', 0)
        total += n
        if pct < 10.0:
            anylow = True
            low += n
    if total <= 0 or not anylow:
        return 1.0
    return float(max(0.0, min(1.0, low / total)))
```

## 2. Do not put more than three new facilities in one district.

Interpretation: Each district may have at most 3 new facilities. Score is 1 minus the share of new facilities that exceed that cap (the excess over 3 in each district).

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 1.000 |
| all in the most populated district | 0.300 |
| all in the least covered district | 0.300 |
| spread one by one, most populated first | 1.000 |
| by population | 1.000 |

```python
def score(plan):
    total = 0
    excess = 0
    for d in plan.get('districts', []):
        n = d.get('new_facilities', 0)
        total += n
        if n > 3:
            excess += n - 3
    if total <= 0:
        return 1.0
    return float(max(0.0, min(1.0, 1.0 - excess / total)))
```

## 3. Spread facilities across as many districts as possible.

Interpretation: Score is the number of districts that receive at least one new facility, divided by the most that could be reached, which is the smaller of the budget and the number of districts.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 0.900 |
| all in the most populated district | 0.100 |
| all in the least covered district | 0.100 |
| spread one by one, most populated first | 1.000 |
| by population | 0.900 |

```python
def score(plan):
    ds = plan.get('districts', [])
    if not ds:
        return 0.0
    used = 0
    total = 0
    for d in ds:
        n = d.get('new_facilities', 0)
        total += n
        if n > 0:
            used += 1
    budget = plan.get('budget', total)
    if budget is None or budget <= 0:
        budget = total
    best = min(budget, len(ds))
    if best <= 0:
        return 1.0
    return float(max(0.0, min(1.0, used / best)))
```

## 4. Prefer sites close to main roads.

Interpretation: Needs road locations and exact site positions. The plan only has district-level figures, so this cannot be scored.

Not measurable with the plan data: the planner reads it, it is not scored.
