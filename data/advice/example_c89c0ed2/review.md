# Advice scoring review: example.txt

Written by claude-sonnet-5-5 on 2026-11-27T17:07:49+00:00. Sample plans use budget 10 on data/processed/eth_negev_6dfcdf57/2026-11-25T132613Z.
Status: in use (used automatically, 2026-11-27T17:30:50+00:00).

## 1. Every district should receive at least one new facility.

Interpretation: Score is the number of districts with at least one new facility, divided by the most that could be reached (the smaller of the budget and the number of districts), capped at 1. A budget smaller than the number of districts is therefore not penalised for the districts it cannot reach.

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
    ds = plan['districts']
    n = len(ds)
    if n == 0:
        return 0.0
    k = min(plan['budget'], n)
    if k <= 0:
        return 0.0
    got = 0
    for d in ds:
        if d['new_facilities'] >= 1:
            got += 1
    return float(min(1.0, got / k))
```

## 2. Give priority to districts where less than 30% of the people are within reach of a facility.

Interpretation: Priority means the districts with coverage_before_pct below 30 get a new facility first. Score is the number of such districts that receive at least one new facility, divided by the most that could be served (the smaller of the facilities placed and the number of such districts). If there are no such districts, the score is 1.

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
    ds = plan['districts']
    low = []
    for d in ds:
        if d['coverage_before_pct'] < 30:
            low.append(d)
    if len(low) == 0:
        return 1.0
    total = 0
    for d in ds:
        total += d['new_facilities']
    if total <= 0:
        return 0.0
    served = 0
    for d in low:
        if d['new_facilities'] >= 1:
            served += 1
    k = min(total, len(low))
    return float(min(1.0, served / k))
```

## 3. No single district should receive more than a third of the new facilities.

Interpretation: The cap per district is a third of the facilities placed, but never less than 1, since a small plan cannot split a single facility. Score is the share of facilities that sit within the cap, so a district that exceeds it loses only the excess.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 1.000 |
| all in the most populated district | 0.333 |
| all in the least covered district | 0.333 |
| spread one by one, most populated first | 1.000 |
| by population | 1.000 |

```python
def score(plan):
    ds = plan['districts']
    total = 0
    for d in ds:
        total += d['new_facilities']
    if total <= 0:
        return 0.0
    cap = max(1.0, total / 3.0)
    ok = 0.0
    for d in ds:
        ok += min(d['new_facilities'], cap)
    return float(max(0.0, min(1.0, ok / total)))
```

## 4. Districts that have no existing facility should be served before others.

Interpretation: Districts with existing_facilities == 0 should get a new facility before districts that already have one. Score is the number of such districts that receive at least one new facility, divided by the most that could be served (the smaller of the facilities placed and the number of such districts). If every district already has a facility, the score is 1.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 0.889 |
| all in the most populated district | 0.111 |
| all in the least covered district | 0.111 |
| spread one by one, most populated first | 1.000 |
| by population | 0.889 |

```python
def score(plan):
    ds = plan['districts']
    zero = []
    for d in ds:
        if d['existing_facilities'] == 0:
            zero.append(d)
    if len(zero) == 0:
        return 1.0
    total = 0
    for d in ds:
        total += d['new_facilities']
    if total <= 0:
        return 0.0
    served = 0
    for d in zero:
        if d['new_facilities'] >= 1:
            served += 1
    k = min(total, len(zero))
    return float(min(1.0, served / k))
```

## 5. More populated districts should get more facilities than small ones.

Interpretation: Score is the share of district pairs with different populations in which the more populous district gets more new facilities. A tie counts as half, and pairs with equal population are ignored.

Checks: passed

| Sample plan | Score |
|---|---|
| by uncovered population | 0.689 |
| all in the most populated district | 0.600 |
| all in the least covered district | 0.444 |
| spread one by one, most populated first | 0.500 |
| by population | 0.689 |

```python
def score(plan):
    ds = plan['districts']
    total = 0
    for d in ds:
        total += d['new_facilities']
    if total <= 0:
        return 0.0
    n = len(ds)
    pairs = 0
    pts = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            a = ds[i]
            b = ds[j]
            if a['population'] == b['population']:
                continue
            if a['population'] > b['population']:
                big = a
                small = b
            else:
                big = b
                small = a
            pairs += 1
            if big['new_facilities'] > small['new_facilities']:
                pts += 1.0
            elif big['new_facilities'] == small['new_facilities']:
                pts += 0.5
    if pairs == 0:
        return 1.0
    return float(pts / pairs)
```

## 6. Prefer locations close to the main roads.

Interpretation: The plan has no road data and no facility coordinates, only district-level figures, so closeness to main roads cannot be scored.

Not measurable with the plan data: the planner reads it, it is not scored.
