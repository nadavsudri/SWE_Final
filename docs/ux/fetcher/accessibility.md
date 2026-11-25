# Accessibility: Data fetcher

Intent `/include` · 24 Nov 2026 · target WCAG 2.2 AA
Likely real conditions: laptop or projector (washed-out colour), colour-vision deficiency,
keyboard-only use while presenting.

**Rule:** the map is never the only way to set or learn something.

## Keyboard access to drawing

| Task | Keyboard path |
|---|---|
| Choose a tool | Tab to the draw toolbar (one tab stop; arrows move between tools, roving tabindex); Enter/Space activates (`aria-pressed`) |
| Draw a rectangle | With the map focused, a crosshair marks the centre. Arrows pan the map under it; **Enter** sets corner 1, pan, **Enter** sets corner 2 |
| Draw a polygon | **Enter** adds a vertex at the crosshair; **Backspace** removes the last; **Enter** on the first vertex or **F** finishes; **Esc** cancels |
| Edit vertices | In Edit mode, **Tab / Shift+Tab** cycle vertices (each announced with its coordinates); arrows move the focused vertex (Shift = larger step); **Delete** removes it (polygons with > 3 vertices) |
| Delete the area | Delete button in the toolbar; confirmation inline |
| No-map alternative | Upload GeoJSON via the file button (native file picker); drag and drop is never the only way |
| Zoom / pan | + / − and arrows while the map is focused; "Fit area" button |

Announcements (polite): "Corner 1 set at 31.60 N, 34.50 E", "Area 11,094 km², valid", "Vertex 3
moved to …". Shortcuts work only while the map has focus (no global single-key shortcuts, WCAG
2.1.4). A "Keyboard" help popover lists them.

## All other controls
- Native elements only: `button`, `input`, `select`-style listbox for country (combobox pattern:
  type to filter, arrows, Enter), checkbox per source, `role="switch"` for Refresh.
- Each source row's expand button has `aria-expanded` and `aria-controls`; the include checkbox is
  labelled "Include Population" (not just a bare box).
- Options use `fieldset` + `legend` (Provider, Tags); field errors are linked with
  `aria-describedby` and `aria-invalid`, announced on blur.
- Disabled Fetch keeps focusable reason text (`aria-describedby`), so a keyboard user learns why.
- Facility tag chips: each remove button is labelled "Remove amenity = clinic".
- Manifest drawer: `role="dialog"` with a label; focus moves into it, Esc closes, focus returns to
  the View manifest button. It's the only focus trap.
- Tab order: header → Inputs (tabs, Area, Profile, Sources) → map region + toolbar → Fetch panel →
  results. A skip link "Skip to Fetch" is first in the tab order.

## Status never by colour alone

| Status | Glyph | Word | Extra |
|---|---|---|---|
| reused | check | "reused" | snapshot id |
| done | check | "done" | elapsed |
| running | spinner (static "…" under reduced motion) | "running" | elapsed |
| queued | empty circle | "queued" | - |
| failed | alert triangle | "failed" | error message + Retry |
| reuse / download / pinned (plan) | - | the word in a badge | reason in the row text |
| warning vs block (area) | alert | callout title | a block also disables Fetch with the reason |

## Colour-blind-safe map layers

| Layer | Primary encoding | Secondary |
|---|---|---|
| Drawn area | **Dashed** dark line + halo | - |
| Districts | **Solid** outline, labelled with the district name | Selected/hovered: thicker line |
| Facilities | **Diamond** markers | Clusters: **circle with a number**, sized by count |
| Country border (on "Show border") | **Dotted** line | - |

Each layer is identified by line style or shape, so any palette works; colour is reinforcement.
Phase 2 checks: CVD simulation (deuteranopia, protanopia, tritanopia), non-text contrast ≥ 3:1
against the basemap, text labels ≥ 4.5:1 with a halo, a low-saturation basemap.

The layer list doubles as the legend: each toggle shows a small sample of the line/marker style
next to its text.

## Screen reader
- Landmarks: `header`, `main` containing three regions: "Inputs", "Map", "Fetch".
- One `h1` (app name). `h2` for Area, Country profile, Sources, Fetch, Progress, Results.
- Live region (polite, one message per change, never per second): "Districts reused from cache",
  "Roads failed: overpass-api.de could not be reached. Retry available", "Fetch finished: 3 done,
  2 failed." Errors that block Fetch use `role="alert"` once.
- The map has a text summary under its label: "Area Negev, 11,094 km². Layers: 2 districts, 200
  facilities." Districts and facilities are also listed in the result cards.

## Motion
`prefers-reduced-motion`: no fly-to animations (jump), static spinners, no pulsing on the running
row.

## Phase 2 checklist (P0 first)
- **P0:** keyboard drawing + vertex editing; file upload path; labelled controls and linked errors;
  live region for progress; status glyph + word everywhere.
- **P1:** CVD and contrast check on real tiles; focus return after the manifest drawer and after Retry
  (focus stays on the row's Retry → moves to the row's new status).
- **P2:** 200% / 400% zoom reflow (panels stack below 1024 px); keyboard help popover.
