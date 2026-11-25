---
name: LEG data fetcher
description: A dense, ruled consignment form for fetching and inspecting map data, where every source is a numbered manifest line stamped with its status.
colors:
  harbour-navy: "#1d2b4a"
  harbour-navy-hover: "#2a3d66"
  harbour-navy-pressed: "#14203a"
  carbon-blue: "#2f4bb8"
  carbon-wash: "#e6eaf7"
  carbon-wash-pressed: "#d3daf1"
  customs-green: "#2e7d4f"
  hold-red: "#b3261e"
  hold-wash: "#fbeceb"
  manifest-amber: "#8a5300"
  manifest-amber-wash: "#fbf2e1"
  manifest-amber-rule: "#d9b77a"
  form-stock: "#f3f4f1"
  sheet: "#fbfbf9"
  field-white: "#ffffff"
  ink-secondary: "#4a5671"
  ink-tertiary: "#6b7489"
  hairline: "#cdd2da"
  disabled-slate: "#a9b0bf"
  shell-caption: "#c3cad8"
  shell-rule: "#8f9ab3"
  map-sea: "#d9e0e6"
  map-land: "#f7f7f4"
  map-border: "#a3acba"
typography:
  headline:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.45
    letterSpacing: "0.04em"
  title:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 650
    lineHeight: 1.45
  body:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "\"tnum\" 1"
  body-sm:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  section-head:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    letterSpacing: "0.12em"
  label:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.08em"
  stamp:
    fontFamily: "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 750
    lineHeight: "16px"
    letterSpacing: "0.1em"
  mono:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
rounded:
  none: "0px"
  cluster: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "20px"
  s6: "24px"
components:
  button-primary:
    backgroundColor: "{colors.harbour-navy}"
    textColor: "{colors.field-white}"
    typography: "{typography.title}"
    rounded: "{rounded.none}"
    height: "46px"
    width: "100%"
  button-primary-hover:
    backgroundColor: "{colors.harbour-navy-hover}"
  button-primary-active:
    backgroundColor: "{colors.harbour-navy-pressed}"
  button-primary-disabled:
    backgroundColor: "{colors.disabled-slate}"
  button-secondary:
    backgroundColor: "{colors.field-white}"
    textColor: "{colors.harbour-navy}"
    rounded: "{rounded.none}"
    padding: "0 12px"
    height: "34px"
  button-secondary-hover:
    backgroundColor: "{colors.carbon-wash}"
  button-secondary-active:
    backgroundColor: "{colors.carbon-wash-pressed}"
  button-small:
    height: "28px"
    padding: "0 8px"
  input:
    backgroundColor: "{colors.field-white}"
    textColor: "{colors.carbon-blue}"
    rounded: "{rounded.none}"
    padding: "0 8px"
    height: "34px"
  form-box-field-focus:
    backgroundColor: "{colors.carbon-wash}"
  stamp:
    textColor: "{colors.harbour-navy}"
    typography: "{typography.stamp}"
    rounded: "{rounded.none}"
    padding: "1px 6px"
  stamp-cleared:
    textColor: "{colors.customs-green}"
  stamp-failed:
    textColor: "{colors.hold-red}"
  stamp-pinned:
    textColor: "{colors.carbon-blue}"
  stamp-warning:
    textColor: "{colors.manifest-amber}"
  chip:
    backgroundColor: "{colors.form-stock}"
    textColor: "{colors.carbon-blue}"
    rounded: "{rounded.none}"
    padding: "2px 4px 2px 8px"
  shell:
    backgroundColor: "{colors.harbour-navy}"
    textColor: "{colors.form-stock}"
    height: "56px"
    padding: "0 24px"
  docket:
    backgroundColor: "{colors.field-white}"
    rounded: "{rounded.none}"
  segmented-selected:
    backgroundColor: "{colors.harbour-navy}"
    textColor: "{colors.field-white}"
---

# Design System: LEG data fetcher

## Overview

**Creative North Star: "The Bill of Lading"**

Every fetch is a consignment. The screen reads as one filled-in shipping form: cool form-stock paper under a harbour-navy shell, hairline-ruled boxes with small uppercase captions, values written in carbon blue as if typed through a carbon sheet, and a manifest whose numbered lines each receive a boxed, double-ruled status stamp. The world is printed-form clerical, never nostalgic: no paper texture, no rotated or smudged ink, no rounded cards.

Density is high and deliberate. Modules are separated by 1px rules rather than padding, columns never move, and status changes happen in place (a stamp swaps its word and color; it does not relocate). The map in the centre is the only open field and stays unobstructed apart from its edge-docked tool stacks.

**Key Characteristics:**
- Square everything: zero radius on every control, box and popup (map cluster badges are the single round exception).
- Ruled structure: 1px hairlines between items, 1px navy around form boxes and dockets, 2px navy under section heads, double 2px navy around the totals line.
- Two inks for meaning: navy for the form itself, carbon blue for anything the user or system filled in.
- Status as a stamp: an uppercase boxed word with an outer second rule, coloured by outcome.
- Archivo for all UI, with tabular numerals on by default; monospace only for ids, hashes, paths and file names.

## Colors

A restrained clerical palette: one navy, one carbon blue, and three outcome colours that appear almost only inside stamps and notes.

### Primary
- **Harbour Navy** (harbour-navy): the form itself. Header shell, section rules, form-box borders, the primary Fetch button, selected segments and pressed tool buttons, the area outline and facility diamonds on the map. Hover lightens to harbour-navy-hover, press darkens to harbour-navy-pressed.

### Secondary
- **Carbon Blue** (carbon-blue): filled-in values. Input text, readout and key-value values, line numbers (01-05, section numbers 1-3), chip text, links, the running duration bar, the drawn-area fill on the map, the focus ring, and the "pinned" / "chosen by the LLM" stamps. Carbon Wash (carbon-wash) is its tint for hover rows, focused form boxes and secondary-button hover.

### Tertiary (outcome colours)
- **Customs Green** (customs-green): cleared. Stamps for reuse, reused, downloaded.
- **Hold Red** (hold-red): failed or blocked. Failed stamps, field errors, blocking notes (with hold-wash fill), invalid-input borders, the keyboard-draw crosshair.
- **Manifest Amber** (manifest-amber): warnings. Warning notes on manifest-amber-wash with a manifest-amber-rule border, and the "LLM call failed" stamp.

### Neutral
- **Form Stock** (form-stock): page ground and chip fill. Cool, never cream.
- **Sheet** (sheet): side panes. **Field White** (field-white): inputs, buttons, dockets, note boxes, map overlays.
- **Ink Secondary** (ink-secondary): captions, hints, sub-lines (6.6:1 on ground). **Ink Tertiary** (ink-tertiary): placeholders, excluded rows, disabled text; only at 13px or larger.
- **Hairline** (hairline): 1px dividers between rows, quiet button borders, chip borders.
- **Map Sea / Map Land / Map Border**: the offline Natural Earth basemap, kept pale so navy and carbon overlays dominate.

### Named Rules
**The Carbon Copy Rule.** Carbon blue means "this was filled in". Labels, headings and chrome are navy or ink-secondary; a value the user typed or the system resolved is carbon. Never use carbon for decoration.

**The Stamp-Only Outcome Rule.** Green, red and amber carry outcome and nothing else. They appear in stamps, notes, field errors and the crosshair, never as fills for buttons, headers or panels.

## Typography

**Body Font:** Archivo (self-hosted variable woff2, 100-900), falling back to system-ui
**Label/Mono Font:** ui-monospace stack, for ids, hashes, paths, file names and the manifest.json viewer

**Character:** A plain, slightly wide grotesk that reads like the typeset parts of a printed form; monospace is the typewritten entry, used only where the content is machine-exact.

### Hierarchy
- **Headline** (700, 16px, uppercase, 0.04em): the app name in the shell only.
- **Title** (650, 14px): line names, docket titles (700), saved-area names, note titles.
- **Body** (400, 14px, 1.45): default text, with tabular numerals on.
- **Body small** (400, 13px; 12.5px for sub-lines and docket key-values): hints, readouts, sub-lines.
- **Section head** (700, 11px, uppercase, 0.12em): numbered section heads ("1 AREA"), MANIFEST, RESULTS, LAYERS; always sits on a 2px navy rule.
- **Label** (600, 11px, uppercase, 0.08em): field captions above values inside form boxes.
- **Stamp** (750, 11px, uppercase, 0.1em, 16px line): status words.
- **Mono** (400, 12px; 11.5px in raw lines): ids, bbox, snapshot ids, paths.

### Named Rules
**The Caption-Above Rule.** A field is a small uppercase caption above a carbon value, inside a ruled box. Do not place labels beside inputs or inside them as placeholders-only.

**The Mono-Is-Data Rule.** Monospace is reserved for strings a machine must match exactly. Prose, numbers with units and names stay in Archivo.

## Layout

A fixed three-column desk on laptop and projector widths: form pane 384px, map flexible, manifest pane 400px, under a 56px shell; the page itself does not scroll above 1100px, each pane scrolls on its own. Panes are separated from the map by 1px navy rules and padded 20px.

Spacing runs on a 4px base (s1-s6: 4, 8, 12, 16, 20, 24). Rows inside lists use 8px vertical padding and a hairline below; sections stack with 20px between them. Numbered rows use a fixed narrow number column (22-26px) so numbers and stamps align vertically down the manifest.

Below 1100px the columns stack: map first at 60vh, then form, then manifest, each separated by a navy top rule; the shell wraps.

**The Fixed-Columns Rule.** Nothing reflows when status changes. Stamps change word and colour in place; columns and rows keep their positions so a running fetch is readable at a glance.

## Elevation & Depth

Flat by default. Depth is drawn with rules, not shadows: surfaces sit on the ground separated by 1px and 2px lines and by the sheet / white / stock tonal steps. Shadows exist only on things that genuinely float above the map or a field.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 8px 20px rgb(29 43 74 / 0.16)`): the country combobox list; 0.18 alpha on map popups.
- **Drawer** (`box-shadow: -10px 0 24px rgb(29 43 74 / 0.12)`): the manifest.json drawer sliding over the map.

**The Ruled-Not-Raised Rule.** Panels, dockets, notes and buttons never carry a shadow. If it is part of the form, it is ruled; only transient overlays float.

## Shapes

Square corners everywhere (0px), including inputs, selects, buttons, chips, dockets, popups and the map attribution. Form language is the ruled box: 1px borders, shared edges between adjacent fields (a two-field form box divides with a single 1px navy line, not a gap). The toggle switch is a square track with a square thumb. Map cluster counts are the one round shape (pill radius, 2px navy border), so they read as map marks rather than UI. Facility points are navy diamonds with a white keyline; the area outline is a dashed navy line over a white halo.

## Components

### Buttons
- **Shape:** square (0px), 1px border.
- **Primary (Fetch data):** full-width harbour-navy block, 46px tall, white uppercase 14px/600 at 0.1em. Hover and press step the navy lighter and darker; disabled turns disabled-slate at full opacity with the reason printed beneath.
- **Secondary:** white, 34px, 1px navy border, 13px/600, icon left at 16px. Hover carbon-wash, press carbon-wash-pressed, disabled 45% opacity.
- **Quiet:** secondary with a hairline border, for less important actions (Upload GeoJSON, Ask the LLM again, Copy).
- **Small:** 28px, 12.5px, used for Retry and docket actions.
- **Icon button:** 34px square, white, no border until pressed; pressed is navy with white glyph (map tools).
- **Link:** carbon, underlined at 3px offset, no box.

### Stamps (signature)
The status mark on every source line and docket: uppercase 11px/750 word in a 1.5px border with a second 1px outline offset 1.5px (the double rule), coloured by outcome: navy (download), customs green (reuse, reused, downloaded), hold red (failed), carbon (pinned, running, chosen by LLM), amber (warnings), ink-tertiary with no outer rule for muted/excluded. When a stamp's status changes it lands once: scale 1.35 to 1 with fade over 260ms on the expo-out curve.

### Form boxes and inputs
- **Ruled form box:** a 1px navy box holding caption-over-value fields; focus tints the whole cell carbon-wash instead of drawing an outline.
- **Standalone input:** 34px, white, hairline border, carbon 600 value text, ink-tertiary placeholder. Hover darkens border to ink-secondary; focus is a 2px carbon outline inset; invalid is a hold-red double border with an icon-led error line below.
- **Segmented control:** 1px navy box, divided by navy rules, selected segment filled navy.
- **Chips:** form-stock fill, hairline border, carbon 600 text, 24px remove target turning red on hover.

### Manifest lines
Numbered rows (01-05) in carbon 700, name in 650, sub-line in 12.5px ink-secondary, stamp right-aligned; hairline between rows. A running line carries a 4px duration bar (carbon on hairline). The totals sentence sits between two 2px navy rules.

### Dockets (result cards)
White ruled boxes (1px navy), a head strip with number, title and stamp divided by a navy rule, a carbon summary line, key-values in ink, a file list under a hairline, then small secondary actions.

### Notes
Bordered boxes with a 16px glyph and a bold title: info (hairline, carbon glyph), warn (amber wash and rule), block (red wash and red border). Upload rejection uses a dashed red box.

### Navigation
- **Shell:** 56px harbour-navy bar with the uppercase app name left and cache path plus LLM-key status (a 1px slate-ruled box) right.
- **Tabs:** text tabs on a hairline, 500 ink-secondary at rest, selected 650 navy with a 2px navy underline.

### Map overlays
Tool and zoom stacks are white columns with a 1px navy border docked to the map edges; the layers legend is a white ruled box top-right with a section-head title. Popups are square with a navy border and the float shadow.

## Do's and Don'ts

### Do:
- **Do** write every user- or system-filled value in carbon blue, and every label as an 11px uppercase caption above it.
- **Do** separate items with 1px hairlines and close sections with a 2px navy rule; use ruled boxes instead of padded cards.
- **Do** show status as a stamp that changes in place, and let it land with the 260ms stamp motion (disabled under reduced motion).
- **Do** keep icons from the one authored set: 20px grid, 1.6 stroke, square caps, rendered at 14-18px.
- **Do** keep the focus ring a 2px carbon outline at 2px offset on every interactive element.

### Don't:
- **Don't** round corners on any control, panel or popup (0px); only map cluster badges are round.
- **Don't** put shadows on panels, dockets, buttons or notes; shadows belong to the combobox list, popups and the drawer only.
- **Don't** use green, red or amber outside stamps, notes, errors and the crosshair.
- **Don't** add paper texture, rotated or distressed stamps, or a cream ground; the stock stays cool (form-stock).
- **Don't** use monospace for prose, labels or numbers with units.
- **Don't** set ink-tertiary text below 13px.
