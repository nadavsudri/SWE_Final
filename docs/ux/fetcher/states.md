# States: Data fetcher

Intent `/fortify` · 24 Nov 2026
For each state: **what the user sees · what they can do · how they recover**. IDs are used by the
Phase 2 tests and screenshots. Wireframe frame numbers in brackets.

Fixture facts (ISR, 34.5,30.5,35.45,31.6): `boundaries` and `osm_facilities` cached and reusable;
`worldpop` rebuilds offline from `_downloads`; `osm_roads` and `gtfs` need the network; no profile
cached; ADM0 outline not cached yet.

## Header

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| H-1 | Key present | "LLM key set" (glyph + text) | - | - |
| H-2 | No key | "No LLM key: defaults will be used" | Read help: how to add a key | Restart the server after editing .env |
| H-3 | Server down | Full-screen message: "The fetcher server isn't running. Start it with `<command>`." | Copy command | Page retries every 5 s |
| H-4 | Cache folder missing | Header shows the path + "will be created on first fetch" | - | - |

## Area: name and country

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| N-1 | Empty | Placeholders; Fetch reason lists "name, country" [1] | Type / search | - |
| N-2 | Country search no match | "No country matches 'Isrel'. Try the name or a 3-letter code." | Edit | - |
| N-3 | Countries loading | Select disabled with "Loading countries…" | Wait | API error → "Couldn't load countries" + Retry |
| N-4 | Name with spaces/symbols | Accepted; readout shows the slugged area_id | - | - |
| N-5 | Country changed after drawing | Area re-validated; warnings update; profile re-resolved | - | - |

## Area: map drawing and upload

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| M-1 | Empty | World map + hint card (mouse and keyboard paths) [1] | Pick a tool, drop a file | - |
| M-2 | Drawing | Live outline, vertex handles, live km² | Undo point, finish, cancel | Esc cancels the shape in progress |
| M-3 | Valid area | Readout bbox / km² / area_id [2] | Edit vertices, delete, replace | - |
| M-4 | Validating | Readout values dimmed + "Checking…" (≤ 1 s usually) | Keep editing | Debounced; last edit wins |
| M-5 | Replace existing area | Inline map prompt "Replace the current area?" Replace / Keep | Choose | Keep restores the old shape |
| M-6 | **Invalid GeoJSON** | Drop zone in error: file name + reason + "Choose another file" [4]. Reasons: not JSON; no `type`; FeatureCollection with N ≠ 1 features ("contains 3 features, expected 1"); invalid geometry; coordinates out of lon/lat range | Choose another file | The previous area is kept |
| M-7 | Invalid drawn geometry (self-intersecting) | Error callout "Edges cross. Move a vertex or redraw." Fetch blocked | Edit vertices | - |
| M-8 | **Large area** (> 20,000 km², configurable) | Neutral warning: "Big areas make the road and facility queries slow and can time out." | Fetch anyway | - |
| M-9 | **Too large** (> 100,000 km², configurable) | Error callout + Fetch disabled with reason [5] | Edit / redraw | - |
| M-10 | **Outside the country** (partly / fully) | Neutral warning with the share outside + "Show border" [5] | Fetch anyway | - |
| M-11 | Country check unavailable | Warning "Couldn't check the country border: outline not cached and no network." | Fetch anyway | Rechecked when online |
| M-12 | Upload while a fetch runs | Inputs locked; drop ignored with "Inputs are locked while fetching" | Wait | - |

## Saved areas

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| S-1 | Empty cache | Tab "Saved areas (0)": "Areas you fetch are saved in data/raw and listed here." | Go to New area | - |
| S-2 | List | Name · ISO3 · area_id · km² · sources present · newest age [6] | Filter, open, hover to outline | - |
| S-3 | Same name twice | Both rows; area_id disambiguates | - | - |
| S-4 | Folder without a readable manifest | Not listed (definition: has a manifest); count of skipped folders in a caption | - | - |
| S-5 | Opening an area while another is unsaved | Opens directly (nothing is lost: inputs aren't documents) | - | Back to New area keeps the last drawn shape |

## Country profile card

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| P-1 | Waiting for area | "Appears when a country and an area are set." [1] | - | - |
| P-2 | Loading | Skeleton lines (LLM call can take seconds) | - | - |
| P-3 | **No key** | Badge "Default · no LLM key", districts + tags; Ask again disabled with reason [2] | Edit options in Sources | Add key → restart → H-1 |
| P-4 | LLM (cached) | Badge "Chosen by the LLM", rationale quoted | Ask again | - |
| P-5 | Asking again | Button spinner "Asking…"; Sources keep the old pre-fill until the answer arrives | Wait | - |
| P-6 | LLM failed | Badge "Default · LLM call failed" + the reason (as printed by `resolve_profile`) | Ask again | - |
| P-7 | Profile changed after user edits | Edited options stay edited; a note "Profile changed: Reset to profile to use it" on those rows | Reset or keep | - |

## Sources panel

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| R-1 | Loading cache state | Row badges "checking…" | - | - |
| R-2 | **Cache hit** (same params, younger than TTL) | Badge "reuse" + snapshot id + age [2] | Pin, Refresh | - |
| R-3 | No snapshot | Badge "download" + "no snapshot for this area" | - | - |
| R-4 | Params changed | Badge "download" + "(params changed)" | Reset to profile / pin the old one | - |
| R-5 | Expired | Badge "download" + "(older than 30 days)" | Pin it anyway | - |
| R-6 | Pinned | Badge "pinned" + id; plan counts it | Unpin | - |
| R-7 | Excluded | Row dimmed, "not fetched"; plan omits it | Re-include | - |
| R-8 | **Invalid options** | Badge "fix options", inline field errors [3] | Fix | Fetch disabled with count |
| R-9 | All excluded | Fetch disabled: "Include at least one source." | Include one | - |

## Fetch controls

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| F-1 | Not ready | Disabled button + exact missing items [1] | - | - |
| F-2 | Ready | Plan: "2 sources reuse the cache, 3 will download." [2] | Fetch | - |
| F-3 | Refresh on | Plan: "Refresh is on: 5 will download." | Fetch | - |
| F-4 | Refresh + pins | Plan: "Refresh is on: 4 will download, 1 pinned." | Fetch | - |
| F-5 | All cached | Plan: "All 5 sources reuse the cache: instant." | Fetch | - |
| F-6 | Double click | Second click ignored (button disabled at the first) | - | - |

## Fetch progress

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| G-1 | Started | Rows: reused sources "reused" at once; others "queued" [7] | Watch; use the map | - |
| G-2 | **Slow fetch** | Elapsed time per running row; after 10 s, the 138 MB note [7] | Leave the page | Reload reattaches to the job |
| G-3 | No cancel | Callout "No cancel: a download can't be stopped safely once it starts." [7] | - | - |
| G-4 | **Partial failure** | Failed rows: glyph + "failed" + error message + Retry; summary "3 done, 2 failed" [8] | Retry one / Retry all failed | Successful results stay usable |
| G-5 | Retry running | That row back to running; others unchanged | - | - |
| G-6 | Retry failed again | "Failed again (2 tries)" + latest error | Retry | - |
| G-7 | Offline | Network sources fail with "could not be reached"; cache hits and offline-capable sources succeed [8] | Retry later | - |
| G-8 | Rate-limited (HTTP 429) | "The OpenStreetMap server is busy (rate limit). Wait a minute, then retry." | Retry | - |
| G-9 | Server restarted mid-job | "This fetch was interrupted. Snapshots that finished are saved." | Fetch again (finished ones are now cache hits) | - |
| G-10 | All failed | Summary "0 done, 5 failed" + Retry all | Retry all | - |

## Results and map layers

| ID | State | Sees | Can do | Recovery |
|---|---|---|---|---|
| Q-1 | Done | One card per source; districts + facilities layers on; map fits area [9] | View manifest, copy path, toggle layers | - |
| Q-2 | Empty result | Facilities card "0 facilities found with these tags"; layer toggle disabled with "nothing to show" | Edit tags, fetch again | - |
| Q-3 | Many facilities | Clusters with counts; split on zoom | Zoom, click a cluster | - |
| Q-4 | Districts failed | Districts layer toggle disabled: "Districts failed: retry to see this layer" | Retry | - |
| Q-5 | Manifest viewer | Read-only drawer [10] | Copy, Esc | - |
| Q-6 | Layer file too large to draw | "Too large to draw (N MB)"; card still shows the summary | - | - |

## Priorities
- **P0:** M-6, M-9, R-8, F-1 (block bad input); G-4 + Retry; H-2/P-3 (no key); R-2 (cache hit shown).
- **P1:** G-2 slow fetch + reattach; M-10/M-11 country check; R-4/R-5 why it downloads; G-7 offline.
- **P2:** G-8, G-9, P-7, Q-2, Q-6.
- **P3:** S-4, N-2, M-5.
