# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Set by the team (24 Nov 2026): a thin FastAPI layer in `src/leg/api/` (no business logic; wraps `leg.data`) and a frontend in `ui/` with Vite 5 + TypeScript (no UI framework), MapLibre GL and terra-draw. Basemap: bundled Natural Earth country outlines, so the map works offline. Dependencies stay minimal; new ones need the team's OK. Local only: no login, no deployment.

## Users

The student team, who use the tool to fetch and inspect data for new areas, and course staff watching or clicking through a demo on a laptop or projector. English, single local user. Neither group should need the CLI or the codebase to fetch an area and see what came back.

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

Current UI scope (team decision, 24 Nov 2026): **the data fetcher only**, one screen. UX is in `docs/ux/fetcher/` (flow, screens + wireframes, states, accessibility).
1. **Area**: name, country (searchable), one area drawn (rectangle/polygon, editable) or uploaded as GeoJSON; readout of bbox, km², area_id; warnings for large areas and areas outside the country (geoBoundaries ADM0), blocks for too-large and invalid areas. Thresholds are config constants.
2. **Saved areas**: areas already in the cache, restorable.
3. **Country profile**: default vs LLM, district provider/levels, facility tags, rationale; ask the LLM again (only with a key).
4. **Sources**: include, options with validation, cache state (reuse vs download), pin a snapshot.
5. **Fetch**: plan line, Refresh, per-source background jobs with status, error and Retry; no cancel.
6. **Results**: per-source snapshot cards, manifest viewer, district and facility map layers.

Out of scope until the team says otherwise: preprocessing, the algorithm, expert advice, run configuration, placement results, experiments, ILP, login, deployment. The LLM API key is never sent to the browser, logged or shown; the UI only knows whether one is set.

Nothing may assume a specific country; the cached Negev area (ISR, bbox 34.5,30.5,35.45,31.6) is a test fixture only.

Terminology: *cell* (~`cell_km` population block), *candidate*, *already covered*, *district*, *coverage radius* (default 10 km straight-line, ≈ the paper's 2 h walk), *snapshot*, *run*, *country profile*.

Constraints: without an `ANTHROPIC_API_KEY` the system falls back to default values ("no llm key - using default values"); the UI must show when that happened. Cells in no district (`district_id = -1`) are counted and warned about. The LEG algorithm step itself is not yet in the repo.

## Brand Commitments

Product name in code: "LEG Facility Location". No logo, voice or visual identity exists yet.

## Evidence on Hand

- Real cached data for the Negev (`data/raw/isr_negev_*`), used as the offline test fixture.
- The source paper (AAMAS 2026).
- No user research, testimonials or benchmark results; team names still to be added. Do not invent results or coverage numbers: show only what a real run produced.

## Product Principles

1. **Show the pipeline, not just the answer.** Each stage (fetch → prep → LEG) is visible with its inputs and outputs.
2. **Honest about data.** Snapshot age, missing sources, fallback LLM defaults and failures are shown, never hidden.
3. **Reproducible by default.** Every result names the snapshot ids and parameters that produced it.
4. **Explainable in a demo.** A grader new to the paper can follow what the LLM decided versus what the algorithm computed.
