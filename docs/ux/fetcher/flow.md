# Flow: Data fetcher UI

Intent `/journey` · 24 Nov 2026 · Phase 1 (UX only, no code)
Diagram: [flow.html](flow.html) · Screen: [screens.md](screens.md) + [wireframes-fetcher.html](wireframes-fetcher.html) ·
States: [states.md](states.md) · Accessibility: [accessibility.md](accessibility.md)

Scope: only the data-fetching step (`leg.data`). Preprocessing, the algorithm, and anything
after the fetch are out of scope and not designed here.

## Problem

Today, fetching data for an area takes the CLI, a hand-typed bbox, and reading `manifest.json`
files to learn what was reused, what downloaded, and what failed. The UI makes every input of
`fetch_all` settable, shows **before** running what the cache will do, and shows **after** running
exactly what came back, per source.

**Success:** a user who has never seen the CLI can draw an area, understand which country profile
applies and why, predict the fetch ("2 reuse the cache, 3 will download"), run it, and open the
district and facility layers, with no terminal.

## Users

| Who | Situation | What changes |
|---|---|---|
| Team member, first visit | New country or region, cold cache | Draws, reads the plan, waits through a slow fetch |
| Team member, returning | Same area, wants fresh data or an exact snapshot | Opens a saved area, toggles Refresh or pins a snapshot |
| Course staff | Watching a demo on a laptop or projector | Needs plain words for cache states and failures |

Laptop browser, 1280–1440 px, mouse + keyboard, English, single local user, no login.

## The screen (one screen, three zones)

```
┌ Header: app name · cache folder (read-only) · LLM key status ─────────────────────┐
│ Inputs panel        │ Map (main)                              │ Fetch panel        │
│  [New | Saved (n)]  │  draw tools · layers + legend · zoom    │  plan line         │
│  1 Area             │                                         │  Refresh toggle    │
│  2 Country profile  │                                         │  Fetch button      │
│  3 Sources (5 rows) │                                         │  progress / results│
└─────────────────────┴─────────────────────────────────────────┴────────────────────┘
```

Reading order follows the work: **inputs (left) → the area (map) → what will happen and what
happened (right)**. The Fetch panel is always visible, so the plan line updates while the user
edits inputs, and the button's disabled reason is never off-screen.

## Flow A: first visit

1. **Arrive.** Empty map of the world. Inputs panel: Area name, Country (searchable, name + ISO3).
   Map hint: "Draw a rectangle or polygon, or drop a GeoJSON file." Fetch panel: "Add a name, a
   country and an area to see the plan." Fetch disabled with that reason.
2. **Name + country.** Choosing a country zooms the map to it. The country's ADM0 outline is
   fetched once in the background (cached through `http.download` in `<root>/_downloads`).
3. **Draw** (rectangle or polygon), or upload / drop GeoJSON. Exactly one area: drawing a new
   shape replaces the old one after a one-line confirmation in the map ("Replace the current
   area?"). Vertices are editable; Delete clears.
4. **Readout updates live:** bbox (W, S, E, N), km², area_id. Validation runs on the server
   (`POST /api/area/validate`):
   - warnings (fetch still allowed): larger than 20,000 km²; partly or fully outside the selected
     country;
   - blocks (fetch disabled): larger than 100,000 km²; invalid geometry; bad GeoJSON.
   Thresholds come from `/api/config`, not UI code.
5. **Country profile card** fills in (`POST /api/profile`): default or LLM, district provider +
   level, facility tags, rationale. No key: "Default profile: no LLM key" and the *Ask the LLM
   again* button is disabled with the reason.
6. **Sources:** five rows, all checked. Each shows its cache state for *this* area and *these*
   options: "reuse 2026-11-12T101414Z (12 days old, fresh for 353 more)" or "will download (no
   snapshot)" / "(params changed)" / "(older than 30 days)". The profile pre-fills the boundaries
   and facilities options; editing them marks the row "edited" with *Reset to profile*.
7. **Plan line** in the Fetch panel: "2 sources reuse the cache, 3 will download." Pressing
   **Fetch** starts a background job (`POST /api/fetch`).
8. **Progress:** per source, queued → running (elapsed) → reused / done / failed. A note says
   there is no cancel ("A download can't be stopped safely once it starts"). Inputs lock while
   the job runs; the map stays usable.
9. **Results:** one card per source, in the Fetch panel: snapshot id, fetched_at, summary
   (population, districts, facilities, ways, feeds), folder, files with sizes, *View manifest*.
   The district and facility layers are switched on and the map fits the area.

## Flow B: returning user

1. **Saved (n)** tab lists every area in the cache root that has a manifest: name, ISO3, area_id
   (two areas can share a name), km², newest snapshot age, sources present.
2. Choosing one restores name, country and polygon, and switches to the inputs view. The sources
   rows show what would be reused now. Example from the real cache: the older "negev"
   (`…d25e423c`) reuses population, roads and transit, but boundaries and facilities show
   "will download (params changed)" because those fetchers' params changed since.
3. Two ways to change what the fetch does:
   - **Refresh** toggle in the Fetch panel: every included source downloads. Plan: "Refresh is on:
     5 will download."
   - **Pin** on a source row: choose an existing snapshot id from that source's list. The row
     then says "pinned 2026-11-12T074645Z" and the plan counts it as "1 pinned". A pin wins over
     Refresh for that source, and the plan says so.
4. Fetch → progress → results as in A.

## Flow C: a failed source

1. During the job one row turns **failed**: alert glyph, the word "Failed", and the error message
   in plain text (e.g. "Overpass timed out after 3 tries"). Other sources continue.
2. When the job ends, the summary reads "3 done, 2 failed". Each failed row has **Retry**
   (`POST /api/fetch/{job}/retry/{source}`), which re-runs that source only, with the same area,
   options, profile and pin.
3. Retry turns the row back to running; success replaces the error with the result card. A
   repeated failure keeps the error and shows "Failed again (2 tries)".
4. Results and map layers for sources that succeeded are available while others failed.

## Following a slow fetch

| Elapsed | User sees |
|---|---|
| 0 s | Reused sources resolve instantly ("reused from cache"); others "queued" / "running" |
| 0–10 s | Elapsed time per running source |
| 10 s+ | Line under the list: "Large downloads can take over a minute (transit: one zip is 138 MB)." |
| any | Inputs locked, map and finished result cards usable; leaving or reloading the page keeps the job (it lives on the server; the page reattaches by job id) |
| end | One polite announcement: "Fetch finished: 3 done, 2 failed." |

## Decisions in this flow
- Validation, cache predictions and the plan come from the API; the UI never re-implements cache
  or TTL rules.
- Per-source jobs: the backend calls `fetch_all(..., sources=[one])` once per source with the same
  resolved profile, so each row has its own status without changing `src/leg/data`.
- Pins and Refresh are visible in the plan line before running. Nothing surprising happens on Fetch.

## Not decided here
- Visual design (Phase 2, Impeccable).
- What happens after a fetch (out of scope).

## Questions for you
- **Q1** Order of the per-source jobs: one after another (gentler on Overpass, slower), or all
  at once? Proposed: one after another, cached sources first, so the fast answers arrive first.
- **Q2** When the selected country's ADM0 outline can't be downloaded (offline, first time), the
  outside-the-country check can't run. Proposed: warning "Couldn't check the country border
  (outline not cached, no network)", fetch still allowed.
