# LEG Facility Location — course project

Implementation of the LEG framework (Trabelsi et al., *Health Facility Location in Ethiopia:
Leveraging LLMs to Integrate Expert Knowledge into Algorithmic Planning*, AAMAS 2026) on new data.

**Team:** _add names_

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```
Python ≥ 3.10.

## Data fetching (`src/leg/data`)

Input is a **country** (ISO3) plus an **area** inside it: a bounding box, or a GeoJSON polygon
(what the future map UI will send).

| Source | What | From | Output file | TTL |
|---|---|---|---|---|
| `worldpop` | people per ~100 m cell | WorldPop Global2 (R2025A, constrained) | `population.tif` | 180 d |
| `boundaries` | districts (level per country profile) | geoBoundaries API or OSM | `districts.geojson` (+ one file per level) | 365 d |
| `osm_facilities` | existing hospitals/clinics/doctors | OpenStreetMap (Overpass) | `facilities.geojson` | 30 d |
| `osm_roads` | road & path network | OpenStreetMap (Overpass) | `roads.geojson` | 60 d |
| `gtfs` | bus/train schedules | Mobility Database catalog | `gtfs_<id>.zip`, `feeds.json` | 14 d |
| `friction` | walking minutes per metre (~1 km) | Malaria Atlas Project WCS (2020 walking-only surface) | `friction.tif` | 365 d |

Roads are queried in 0.5° tiles; a tile that times out is split in four (twice at most), so large areas don't time out as one query.

```bash
# fetch everything for an area
python -m leg.data fetch --name negev --iso3 ISR --bbox 34.25,30.5,35.45,31.6

# polygon instead of bbox, only some sources, another year
python -m leg.data fetch --name galilee --iso3 ISR --geojson galilee.geojson --sources worldpop,boundaries --year 2025

# list cached snapshots
python -m leg.data list --name negev --iso3 ISR --bbox 34.25,30.5,35.45,31.6
```

From Python:
```python
from leg.data import Area, fetch_all
area = Area.from_bbox("negev", "ISR", 34.25, 30.5, 35.45, 31.6)
results = fetch_all(area)                         # {source: Snapshot | Exception}
results = fetch_all(area, pinned={"worldpop": "2026-11-11T163000Z"})  # exact snapshot
```

### Country profile (LLM)
Before fetching, an LLM decides per country:
- which admin units are the **districts** (e.g. Israel → OSM municipalities, `admin_level=8`;
  sub-Saharan Africa → geoBoundaries districts), and
- which OSM tags count as an **existing facility** (Israel → hospitals + emergency only;
  Africa → all healthcare).

Put your key in `.env` (`ANTHROPIC_API_KEY=...`). Without a key it prints
`no llm key - using default values` and uses geoBoundaries ADM1/ADM2 + all healthcare tags.
The answer is validated (allowed keys/levels only) and cached in `data/raw/_profiles/<ISO3>.json`,
so each country is asked once; `--refresh-profile` asks again. `boundaries` always writes
`districts.geojson` (the finest level) with the same properties for every provider.

### Cache layout
```
data/raw/<area_id>/<source>/<snapshot_id>/   files + manifest.json
data/raw/_downloads/                         shared country-wide downloads (keyed by URL)
```
- A snapshot is reused while younger than the source's TTL **and** made with the same params;
  otherwise a new one is fetched. Old snapshots are never overwritten.
- `--refresh` forces new snapshots.
- **Experiments must pin snapshot ids**, so results don't change when data is refreshed.
- `manifest.json` records the area, URLs, params, fetch time and a sha256 for every file.
- A failed fetch leaves no snapshot behind; failures are reported per source, never hidden.

## Preprocessing (`src/leg/prep`)

Turns an area's cached snapshots into the **paper's own file format** (the code of Choo et al. 2026,
github.com/yohayt/OHCE, which LEG reuses), so the algorithms run unchanged on our data and on theirs.
Needs `worldpop`, `boundaries` and `friction` (Malaria Atlas walking friction) for the area.
```bash
python -m leg.data fetch --name wollo --iso3 ETH --bbox 38.6,9.7,40.6,11.7   # prints "-> area <id>"
python -m leg.prep --area-id <id>                    # options: --years 2026,2027  --max-minutes 120
# pin inputs for experiments:  --snapshot worldpop=2026-11-12T074642Z
```
Output in `data/processed/<area_id>/<run_id>/`:

| File | Same as the paper? | Content |
|---|---|---|
| `population.csv` | yes | `cell, lat, lon, ADM1, ADM2, ADM3, population, year`: populated cells (≥ 10 people) |
| `pairwise_costs.csv` | yes | `cell_i, cell_j, lat/lon, ADM1-3 of both, distance`: walking minutes, cells ≤ 10 apart, i < j |
| `existing.csv` | ours | `cell, lat, lon, source, name, type, snapped_km`: real facilities in their (nearest populated) cell |
| `districts.csv` | ours | per district: population, population within 120 min of a facility, cells, facilities, fully_inside |
| `meta.json` | ours | input snapshot ids, settings, grid, totals, time per stage |

- Grid: the friction map's ~0.93 km pixels, as in the paper. `cell` = global row × 43200 + column, so ids are stable.
- `ADM3` = the planning district (the level the rule chose); `ADM2`/`ADM1` = the two coarser levels (country code when unknown).
- Walking minutes: least-cost path over friction (minutes per metre) × metres. The paper's code passes
  1/friction to the path search; we follow the paper's text (a two-hour walk) instead.
- `pairwise_costs.csv` keeps pairs up to `--keep-minutes` (default = the 120-minute cutoff) to keep the file small.

The algorithms load either format: `Instance.load(<run folder>)`, or the paper's files with
`python -m leg.algo --population population_1.csv --pairwise pairwise_costs_1.csv --b 10`.

## Area mode: whole districts (default) or free polygon

The paper plans over whole administrative districts (every cell in exactly one district; advice
names districts). So by default the drawn area is **snapped**: it becomes the union of the
districts with at least 50% of their area inside the drawing (`--min-share`). Districts can be
added or removed by `unit_id` (`--include`, `--exclude`). `data/raw/<area_id>/area.json` records
the drawing, the rule and each district's choice.

**District level (rule, no LLM).** For each geoBoundaries level ADM1-ADM5 the fetcher counts the
districts the area would use (snap: >= 50% inside; free: all touched) and picks the finest level
with 10-100 of them; the five levels are downloaded in parallel. If geoBoundaries is too coarse
(e.g. Israel), OSM admin levels 5-8 are tried the same way, one query at a time, stopping once a level
has more than 100 districts (finer levels only split them further). If nothing is in range, the closest level is used with a warning. `--level ADM3` (or an
OSM number) overrides the rule. The counts and the choice are saved in `area.json`. This follows the
paper's data: its districts are Ethiopian woredas (ADM3), several dozen per region. The LLM profile
now only decides which facilities count as existing.

`--mode free` keeps the drawing as is. Districts get `fully_inside`, and expert advice is then taken
into account only for districts the polygon covers completely.

```bash
python -m leg.data fetch --name wollo --iso3 ETH --bbox 38.6,9.7,40.6,11.7              # snap (default)
python -m leg.data fetch --name wollo --iso3 ETH --bbox 38.6,9.7,40.6,11.7 --mode free
```

## Public health facilities in sub-Saharan Africa (`public_facilities` source)

OpenStreetMap has very few health facilities in much of Africa (one facility for ~2 million
people in a test area in Ethiopia). For sub-Saharan countries the `public_facilities` source reads
the geocoded inventory of 98,745 public facilities by Maina et al. (2019), *Scientific Data* 6:134.
The file has no stable download URL, so download it once from
<https://www.who.int/publications/m/item/who-cds-gmp-2019-01> and save it as
`data/raw/_manual/ssa_public_health_facilities.xlsx` (`.csv` also works).
Outside sub-Saharan Africa the source returns no facilities and says why; inside it, a missing file
is an error that says where to put it. Preprocessing merges these facilities with the OSM ones.

## Expert advice (`src/leg/advice`)

The advice is a file given at the start of a run: one advice per line, free text, any language
(`#` lines are comments), or a JSON list of strings. As in the paper, an LLM reads it and writes one
scoring function per advice, `score(plan) -> 0..1`, **once per advice file**; fully automatic:
```bash
python -m leg.advice prepare advice.txt --prep data/processed/<area>/<run>   # needs ANTHROPIC_API_KEY in .env
python -m leg.advice show advice.txt        # how each advice is measured: interpretation, checks, examples, code
python -m leg.advice recheck advice.txt     # run the checks again on the saved code (no LLM call)
python -m leg.advice approve advice.txt     # optional: record that a person read it and agrees
```
- Each function gets a plan record per district: population, coverage before/after (people within a
  two-hour walk), existing and new facilities, cells, `fully_inside` (see `advice/plan.py`).
- Checks: the code passes an allow-list sandbox (plain Python + `math`, no imports, files, network or
  while loops), then runs in a separate process with a 10 s limit on five real sample plans of the
  area: a number in 0-1, the same number twice, and (warning) not the same number for every plan.
- Functions that pass are used at once. An advice that fails a check, or needs data the plan
  doesn't have (roads, terrain...), is not scored; the planner still reads it. Alignment of a plan =
  mean over the scored advice.
- In the UI (after preprocessing): upload the .txt, follow the progress, see how each advice will be
  measured, rephrase if needed. API: `POST /api/advice`, `GET /api/advice/jobs/{id}`,
  `GET /api/advice[/{key}]`, `POST /api/advice/{key}/approve|recheck` (`src/leg/api/advice.py`).
- Saved in `data/advice/<file>_<hash>/` (`scoring.json` + `review.md`); editing the file = new functions.

## Placement algorithms (`src/leg/algo`)

| | What | From |
|---|---|---|
| `coverage` | f(S): people newly covered by the sites (already covered cells count 0) | paper, Eq. 1 |
| `greedy` | take the cell with the largest marginal gain, b times | Nemhauser et al. 1978 |
| `guided_greedy` | GuidedGreedy with a district allocation, alpha and beta; f(S) >= (1 - e^(-alpha*beta)) OPT | paper, Algorithm 2 |
| `ilp` | exact maximum coverage (MCLP) with HiGHS, time limit, greedy warm start | baseline |
| `random_sites` | seeded random placement | baseline |
| `check` | b sites, all candidates, no duplicates, coverage guarantee when OPT is known | validation |

```bash
python -m leg.algo data/processed/<area_id>/<run_id> --b 20
python -m leg.algo <prep_dir> --b 20 --allocation "1:4,2:6,4:8,5:2" --alpha 0.5 --beta 0.8 --out result.json
```
Notes:
- GuidedGreedy protects exactly the first ceil(alpha*b) picks (the paper's pseudocode allows one
  more); `protected_picks()` documents this.
- Ties go to the lowest cell id, so runs are deterministic.
- When the ILP hits its time limit it reports the best solution found (never worse than greedy,
  thanks to the warm start) and an upper bound. At 1 km cells an area of ~12,000 km2 is too big
  to solve in 2 minutes; at 2 km cells it is solved to optimality in ~5 s.

## Fetcher UI (`ui/` + `src/leg/api`)

One screen to set every input of `fetch_all`, see what the cache will do, run it and inspect the result.

```bash
./start.sh            # builds the UI if needed, then serves UI + API on http://127.0.0.1:8000
```

Needs Python ≥ 3.10 and Node ≥ 18. The first run installs `.[ui]` and `ui/node_modules`.
For UI development run `python -m leg.api` and `npm --prefix ui run dev` (Vite proxies `/api`).

- `src/leg/api/` is a thin FastAPI layer over `leg.data` (no changes to `leg.data`/`leg.prep`).
  Each source is fetched with its own `fetch_all(..., sources=[one])` call in a background job, so
  every source reports its own status and can be retried alone. Cached and pinned sources run first.
- Size limits are constants in `src/leg/api/settings.py` (warn 20,000 km², block 100,000 km²;
  env `LEG_WARN_KM2` / `LEG_MAX_KM2`). The country check uses the geoBoundaries ADM0 outline,
  downloaded once into `data/raw/_downloads`.
- The LLM key is never sent to the browser: the API only reports whether one is set.
- The basemap is bundled (Natural Earth countries, `ui/public/countries.geojson`), so the map works
  offline. The font (Archivo) is self-hosted in `ui/public/fonts`.
- UX docs, wireframes and screenshots of every state: `docs/ux/fetcher/`.

## Tests
```bash
pytest            # offline, mocked HTTP (includes tests/test_api.py)
pytest -m live    # real APIs, small area near Be'er Sheva
```
