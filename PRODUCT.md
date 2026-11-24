# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated: a web front-end (Vite + React + TypeScript, MapLibre GL for the map) over a small FastAPI service that wraps the existing Python package (`leg.data`, `leg.prep`, and the LEG algorithm). Reason: the pipeline is already Python, so the API stays a thin layer, and a real map library is needed for drawing areas and showing cells, districts and sites. Deploy target: undecided (local demo is enough for now).

## Users

Course graders, instructors and classmates evaluating a 3rd-year software-engineering final project. They watch or click through a demo: they don't know the codebase, may not know the LEG paper in detail, and need to see the whole pipeline work on new data (Israel / Negev) in a few minutes.

## Product Purpose

An implementation of the LEG framework (Trabelsi et al., *Health Facility Location in Ethiopia: Leveraging LLMs to Integrate Expert Knowledge into Algorithmic Planning*, AAMAS 2026) applied to new data. Given a country and an area, it fetches population, district, facility, road and transit data, preprocesses it into candidate cells and coverage sets, and runs an LLM-guided greedy to choose new health-facility locations. Success for the UI: a grader can pick an area, run the pipeline, and understand what was chosen and how much coverage improved, without reading code.

## Positioning

Not a generic GIS viewer: the point is the LEG mechanism, where an LLM supplies expert knowledge (country profile: which admin units are districts, which OSM tags count as existing facilities; and guidance to the greedy), and the algorithm does the coverage maximisation. The UI should make that split visible.

## Operating Context

- Inputs: country (ISO3) plus an area as a bbox or GeoJSON polygon drawn on the map.
- Data sources: WorldPop (population raster), geoBoundaries / OSM (districts), OSM Overpass (facilities, roads), Mobility Database (GTFS).
- Cached snapshots under `data/raw/<area_id>/<source>/<snapshot_id>/` with `manifest.json`; experiments pin snapshot ids for reproducibility.
- Preprocessing output in `data/processed/<area_id>/<run_id>/`: `cells.csv`, `coverage.json`, `districts.csv`, `meta.json`.
- Fetches and LLM calls can be slow and can fail per source; failures are reported per source, never hidden.

## Capabilities and Constraints

First version of the UI:
1. **Select an area**: pick a country, draw a polygon or bbox, trigger fetch + prep.
2. **Run LEG and see sites**: run the LLM-guided greedy and show chosen facility locations on the map.
3. **Coverage stats**: per-district population, covered population and coverage %, before vs. after.
4. **Inspect data and snapshots**: cached snapshots per source, their age/TTL, and pinnable snapshot ids.

Terminology: *cell* (~`cell_km` population block), *candidate*, *already covered*, *district*, *coverage radius* (default 10 km straight-line, ≈ the paper's 2 h walk), *snapshot*, *run*, *country profile*.

Constraints: without an `ANTHROPIC_API_KEY` the system falls back to default values ("no llm key - using default values"); the UI must show when that happened. Cells in no district (`district_id = -1`) are counted and warned about. The LEG algorithm step itself is not yet in the repo.

## Brand Commitments

Product name in code: "LEG Facility Location". No logo, voice or visual identity exists yet.

## Evidence on Hand

- Real cached data for the Negev (`data/raw/isr_negev_*`).
- The source paper (AAMAS 2026).
- No user research, testimonials or benchmark results; team names still to be added. Do not invent results or coverage numbers: show only what a real run produced.

## Product Principles

1. **Show the pipeline, not just the answer.** Each stage (fetch → prep → LEG) is visible with its inputs and outputs.
2. **Honest about data.** Snapshot age, missing sources, fallback LLM defaults and failures are shown, never hidden.
3. **Reproducible by default.** Every result names the snapshot ids and parameters that produced it.
4. **Explainable in a demo.** A grader new to the paper can follow what the LLM decided versus what the algorithm computed.
