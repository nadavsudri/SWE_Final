# Screen: Data fetcher

Intent `/wireframe` · 24 Nov 2026 · full-page wireframes (mid-fi, grayscale)
Artifact: [wireframes-fetcher.html](wireframes-fetcher.html) (open in a browser; Grid / Slides, light / dark).
Source: `_wireframe-src/build.py` + `layout.css` (rebuild with the Intent wireframe kit).

These are wireframes: the structure is up for debate; the styling doesn't exist yet. Values come
from the cached fixture (ISR, bbox 34.5,30.5,35.45,31.6) unless a frame note says otherwise.

## Frames

| # | Frame | Shows |
|---|---|---|
| 1 | First visit | Empty inputs, empty cache, map hint, disabled Fetch with its reason |
| 2 | Ready to fetch | Area readout, default profile (no key), 5 source rows with reuse/download, plan line |
| 3 | Source options | Expanded options, inline validation, edited-vs-profile, pin selector |
| 4 | Upload rejected | GeoJSON with 3 features: named file, reason, fix |
| 5 | Area problems | Too large (block) + outside the country (warning) |
| 6 | Saved areas | Two cached areas with the same name, told apart by area_id |
| 7 | Fetching | Cache hits resolved instantly, one slow source, queued source, "No cancel" |
| 8 | Partial failure | Two failed sources with their errors and Retry (the real offline outcome) |
| 9 | Results | Result cards, district outlines + labels, clustered facilities, popup, layer list |
| 10 | Manifest viewer | Read-only manifest.json drawer |

## Layout: three zones

Pattern: **sidebar + content + sidebar**, ratio 4 : 7 : 4 (at 1440 px: ≈ 384 · 672 · 384).

| Zone | Job | Contents |
|---|---|---|
| Header | Where am I, what is the environment | App name · cache folder (read-only) · LLM key status (boolean only) · help |
| Inputs panel (left) | Everything `fetch_all` takes | Tabs New area / Saved areas (n) · 1 Area · 2 Country profile · 3 Sources |
| Map (centre) | The area, and what came back | Draw tools (rectangle, polygon, edit vertices, delete) · drop target · layers + legend · zoom / fit |
| Fetch panel (right) | What will happen, what happened | Plan line · Refresh switch · Fetch button + disabled reason · progress · result cards |

Why three zones: inputs, area and outcome are needed at the same time. The plan line must update
while options change; progress and results must sit next to the map layers they produce. A
bottom results drawer was rejected: it fights the map for height on a laptop.

Why sections, not a wizard: returning users jump straight to Sources (Refresh, a pin). Sections
collapse to a one-line summary ("1 Area · Negev · ISR · 11,094 km²") once complete.

## Components → API

| # | Component | Reads / writes |
|---|---|---|
| 1 | Header | `GET /api/config` (cache root, llm_key_present, thresholds) |
| 2 | Name + country | `GET /api/countries` (name, iso3); country search by name or code |
| 3 | Map drawing + upload + readout | `POST /api/area/validate` → area_id, bbox, km², warnings, errors |
| 4 | Saved areas | `GET /api/areas` |
| 5 | Country profile card | `POST /api/profile {area, refresh}` |
| 6 | Sources panel | `GET /api/sources` (defaults, TTL) + `POST /api/snapshots {area, options}` (list + reuse/download) |
| 7 | Fetch controls | plan line from `/api/snapshots`; `POST /api/fetch` |
| 8 | Progress | `GET /api/fetch/{job_id}` (poll); `POST /api/fetch/{job_id}/retry/{source}` |
| 9 | Results | from the job result: snapshot id, manifest (summary, files) |
| 10 | Map layers | `GET /api/snapshot/{area_id}/{source}/{id}/districts.geojson`, `facilities.geojson`; `manifest.json` for the viewer |

## Per-component structure

**Area.** Name and Country side by side (both required). Upload button with "or drop a file on
the map". Readout: bbox (W, S, E, N), km², area_id. Warnings and blocks as callouts under the
readout; a block disables Fetch, a warning doesn't.

**Country profile card.** Badge: "Default · no LLM key", "Default · LLM call failed", or "Chosen
by the LLM". Districts (provider + levels) and facility tags as key/value text, rationale quoted
when from the LLM. "Ask the LLM again" (refresh=True); without a key it is disabled with "Needs an
API key in .env" next to it.

**Source row.** Include checkbox · name + one-line summary of options and cache state · badge
(reuse / download / pinned / fix options) · expand. Expanded options per source:

| Source | Options | Validation |
|---|---|---|
| Population (worldpop) | year, resolution | year 2015–2030; resolution 100m / 1km |
| Districts (boundaries) | provider, levels | geoBoundaries: ADM1–ADM5; OSM: numbers 2–11; at least one level; last = districts |
| Health facilities (osm_facilities) | tags (key = value chips + adder) | key ∈ amenity / healthcare / emergency; value lowercase word or `*`; at least one tag |
| Roads (osm_roads) | highway types (checkbox list, default all 16) | at least one |
| Transit (gtfs) | max feeds | integer ≥ 1 |

Every source also has **Pin a snapshot** (that source's snapshots, newest first, with age) and,
for profile-fed sources, **Reset to profile** when edited.

**Fetch panel.** Plan line, then the Refresh switch with a one-line explanation, then the full-width
Fetch button with its disabled reason beneath. After a run, the same panel shows Progress (one
row per source) and then Results (one card per source).

**Result card.** Status badge (reused / done) · summary in words (e.g. "2 districts (ADM2) · 1
ADM1 unit") · snapshot id · fetched_at · folder · files with sizes · View manifest · Copy path.

**Map.** Area: dashed outline. Districts: solid outline + name label. Facilities: diamonds,
clustered into numbered circles when zoomed out; popup with name, amenity, healthcare, emergency,
osm_id. Layer list top-right doubles as the legend. No population raster, no roads.

## Considered and rejected
- **Results replacing the inputs panel** after Fetch. Rejected: Retry and re-fetch need the
  inputs, and returning users edit and re-run.
- **Global progress bar.** Rejected: it hides which source is slow or failed.
- **Modal for source options.** Rejected: users compare options with the cache state in the row.
- **Manifest inline in the card.** Rejected: too long; a drawer keeps the card scannable.

## Handoffs
- `/articulate`: all messages are honest placeholders; error texts quote the backend's own
  exceptions where they are plain enough.
- `/fortify`: [states.md](states.md). `/include`: [accessibility.md](accessibility.md).
- Phase 2 (Impeccable): visual design starts from this structure.

## Added after approval (25 Nov 2026)
- **Country and name from the area.** Drawing or uploading fills the country with the one covering most of the area (bundled Natural Earth outlines, sampled offline) and lists the others with their share ("Also: Palestine 10%, Jordan 10%"), each one click to switch. A country or name the user picks is never overwritten. The default name is the country's slug, unless the same shape is already cached for that country: then the cached area's name is used, because the name is part of the cache folder and a new name would miss the cache. Screenshot 13.
- **Street map, dimmed.** A switch in the Layers panel adds OpenFreeMap's Positron street map (online only) inside the same map, under a dimming sheet, with all data drawn on top. Toggling never moves the camera, so the area stays on the same ground. Sub-option **Only inside the area** covers everything outside the area with the opaque sheet. Offline, the switch turns itself off and says the street map needs a network connection. The choice is remembered per browser. Screenshots 14, 15.
