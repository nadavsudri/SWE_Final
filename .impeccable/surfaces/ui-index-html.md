---
version: 1
slug: "ui-index-html"
primary_target: "ui/index.html"
related_targets: []
---

# Surface: data fetcher (ui/index.html)

Mode: Operate. Audience: the student team and course staff, laptop or projector, English. Job: set every input of `leg.data.fetch_all`, predict what the cache will do, run it, inspect what came back. Structure, states and accessibility are fixed by docs/ux/fetcher/ (approved wireframes). Constraints: no country assumed; works offline on the cached fixture; the LLM key never reaches the browser.

## Direction contract

THESIS: Every fetch is a consignment. The five sources are numbered lines on one manifest, each stamped in plain words: REUSE / DOWNLOAD / PINNED before the run, REUSED / DOWNLOADED / FAILED after it. Refuses the category default of grey panels, rounded cards and a blue button.

OWN-WORLD: Cool form-stock ground (#F3F4F1 family, never cream) under a harbour-navy shell (#1D2B4A) that carries the header, rules and primary button. Values that the user or the system filled in are carbon blue (#2F4BB8); labels are small uppercase field captions above them. Hairline-ruled boxes instead of cards; 2px navy rules under section heads. Status is a boxed uppercase word with a double rule (stamp), coloured customs green (reuse/reused/downloaded), hold red (failed), navy (download), carbon (pinned/running), amber (warnings). System grotesk for UI, monospace only for ids, hashes and paths. No paper texture, no rotated ink.

STORY: The user fills the form on the left, sees the area on the map, reads the manifest's totals line ("5 lines · 2 cleared from cache · 3 to ship"), presses Fetch, watches each line get stamped in place, opens a line's docket (result card + manifest.json) and its layers on the map.

FIRST VIEWPORT: 56px navy header (app name, cache folder, LLM key status). Three columns 384 / flexible / 400: left form (1 Area, 2 Country profile, 3 Sources as numbered ruled lines with stamps); centre map with nothing over the drawn area but its dashed outline and the tool/zoom stacks at the edges; right manifest: numbered lines 01-05, totals line between double rules, full-width navy FETCH DATA button, the no-cancel note.

FORM: Bill of Lading, position 5 of my ordered list. seed:fe7397f79d92cc24. Raises: labanotation (running lines carry a duration bar to scale), split-flap (columns never move; stamps change in place), high-density (hairline modules, no card padding), vertical feed (map centre unobstructed). Signature move: the in-place stamp on each manifest line.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
