# Advice scoring review: example.txt

Written by claude-sonnet-5-5 on 2026-11-27T17:53:06+00:00. Sample plans use budget 10 on data/processed/yem_egypt_ba184309/2026-11-27T174158Z.
Status: in use (used automatically, 2026-11-27T17:53:06+00:00).

## 1. Every district should receive at least one new facility.

Interpretation: Score is the share of districts that get at least one new facility. It is normalised by the most that is possible, min(budget, number of districts), so a plan that spreads the budget over as many different districts as it can gets 1.0.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 0.500 |
| all in the most populated district | 0.100 |
| all in the least covered district | 0.100 |
| spread one by one, most populated first | 1.000 |
| by population | 0.900 |

```python
def score(plan):
    ds = plan["districts"]
    n = len(ds)
    if n == 0:
        return 0.0
    feasible = min(plan["budget"], n)
    if feasible <= 0:
        return 0.0
    got = sum(1 for d in ds if d["new_facilities"] >= 1)
    return float(min(1.0, got / feasible))
```

## 2. Give priority to districts where less than 30% of the people are within reach of a facility.

Interpretation: Low-coverage districts are those with coverage_before_pct below 30. Score is the number of them that receive at least one new facility, divided by the most that could be served (min(budget, number of such districts)). If no district is that poorly covered, the advice is trivially followed and the score is 1.

Checks: passed
Warning: gives the same score (1.000) to every sample plan

| Sample plan | Score |
|---|---|
| by uncovered population | 1.000 |
| all in the most populated district | 1.000 |
| all in the least covered district | 1.000 |
| spread one by one, most populated first | 1.000 |
| by population | 1.000 |

```python
def score(plan):
    ds = plan["districts"]
    low = [d for d in ds if d["coverage_before_pct"] < 30]
    if len(low) == 0:
        return 1.0
    feasible = min(plan["budget"], len(low))
    if feasible <= 0:
        return 0.0
    served = sum(1 for d in low if d["new_facilities"] >= 1)
    return float(min(1.0, served / feasible))
```

## 3. No single district should receive more than a third of the new facilities.

Interpretation: Take the largest share of the new facilities that any one district receives. The score is 1 if that share is at most 1/3. Above 1/3 it falls linearly to 0 when one district gets everything.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 0.900 |
| all in the most populated district | 0.000 |
| all in the least covered district | 0.000 |
| spread one by one, most populated first | 1.000 |
| by population | 1.000 |

```python
def score(plan):
    ds = plan["districts"]
    total = sum(d["new_facilities"] for d in ds)
    if total <= 0:
        return 1.0
    mx = max(d["new_facilities"] for d in ds)
    share = mx / total
    if share <= 1.0 / 3.0 + 1e-9:
        return 1.0
    return float(max(0.0, 1.0 - (share - 1.0 / 3.0) / (2.0 / 3.0)))
```

## 4. Districts that have no existing facility should be served before others.

Interpretation: Districts with existing_facilities == 0 should get new facilities first. Score is the number of them that receive at least one new facility, divided by the most that could be served (min(budget, number of such districts)). If every district already has a facility, the score is 1.

Checks: passed
Warning: gives the same score (1.000) to every sample plan

| Sample plan | Score |
|---|---|
| by uncovered population | 1.000 |
| all in the most populated district | 1.000 |
| all in the least covered district | 1.000 |
| spread one by one, most populated first | 1.000 |
| by population | 1.000 |

```python
def score(plan):
    ds = plan["districts"]
    zero = [d for d in ds if d["existing_facilities"] == 0]
    if len(zero) == 0:
        return 1.0
    feasible = min(plan["budget"], len(zero))
    if feasible <= 0:
        return 0.0
    served = sum(1 for d in zero if d["new_facilities"] >= 1)
    return float(min(1.0, served / feasible))
```

## 5. More populated districts should get more facilities than small ones.

Interpretation: Look at all pairs of districts with different populations. A pair scores 1 if the larger district gets more new facilities, 0.5 if they get the same, and 0 if the larger gets fewer. The score is the average over pairs. A plan with no new facilities scores 0.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 0.396 |
| all in the most populated district | 0.545 |
| all in the least covered district | 0.476 |
| spread one by one, most populated first | 0.760 |
| by population | 0.771 |

```python
def score(plan):
    ds = plan["districts"]
    n = len(ds)
    total = sum(d["new_facilities"] for d in ds)
    if total <= 0:
        return 0.0
    if n < 2:
        return 1.0
    acc = 0.0
    cnt = 0
    for i in range(n):
        for j in range(i + 1, n):
            pi = ds[i]["population"]
            pj = ds[j]["population"]
            if pi == pj:
                continue
            ni = ds[i]["new_facilities"]
            nj = ds[j]["new_facilities"]
            if pi > pj:
                big, small = ni, nj
            else:
                big, small = nj, ni
            cnt += 1
            if big > small:
                acc += 1.0
            elif big == small:
                acc += 0.5
    if cnt == 0:
        return 1.0
    return float(acc / cnt)
```

## 6. Prefer locations close to the main roads.

Interpretation: The plan has no road data and no facility locations inside districts, so closeness to main roads cannot be scored.

Not measurable with the plan data: the planner reads it, it is not scored.
