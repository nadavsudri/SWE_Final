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

Turns the cached snapshots into what the algorithm reads. Fetches anything missing first.
```bash
python -m leg.prep --name negev --iso3 ISR --bbox 34.5,30.5,35.45,31.6 --cell-km 1 --radius-km 10
# pin inputs for experiments:  --snapshot worldpop=2026-11-12T074642Z
```
Output in `data/processed/<area_id>/<run_id>/`:

| File | Content |
|---|---|
| `cells.csv` | `cell_id, lon, lat, population, district_id, is_candidate, already_covered` |
| `coverage.json` | `{candidate_cell_id: [cell_ids within radius]}` |
| `districts.csv` | per district: population, covered population, coverage %, cells, candidates, existing facilities |
| `meta.json` | input snapshot ids, parameters, totals, cells in no district |

- Cells: the 100 m WorldPop grid summed into ~`cell_km` blocks; only cells whose center is in the area.
- Coverage v1: straight-line distance ≤ `radius_km` (default 10 km ≈ the paper's 2 h walk).
- `already_covered`: an existing facility is within `radius_km`.
- Candidates: populated cells (`--candidates all` for every cell).
- `district_id = -1`: the cell is in no district; counted and printed as a warning.

## Tests
```bash
pytest            # offline, mocked HTTP
pytest -m live    # real APIs, small area near Be'er Sheva
```
