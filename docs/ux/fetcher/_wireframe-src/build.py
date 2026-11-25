"""Build docs/ux/fetcher/wireframes-fetcher.html.

usage: python build.py <intent wireframe references dir> <out.html>
Embeds the Intent kit CSS, viewer CSS and viewer JS verbatim, then layout.css and the frames.
Numbers are from the cached fixture (ISR, bbox 34.5,30.5,35.45,31.6) unless a note says otherwise.
"""
import sys
from pathlib import Path

REF, OUT = Path(sys.argv[1]), Path(sys.argv[2])
HERE = Path(__file__).parent
TOTAL = 10
frames, notes = [], []


# ---------------------------------------------------------------- pieces
def header(key=False):
    llm = ('<span class="badge badge-muted"><span class="glyph gl-check glyph-sm"></span>LLM key set</span>' if key else
           '<span class="badge badge-muted"><span class="glyph gl-info glyph-sm"></span>No LLM key: defaults will be used</span>')
    return f'''<header class="shell-bar">
    <span class="t-heading">LEG data fetcher</span>
    <span class="grow"></span>
    <span class="t-caption muted">Cache folder</span><span class="t-small mono">data/raw</span>
    {llm}
    <button class="btn-icon" aria-label="Help"><span class="glyph gl-info"></span></button>
  </header>'''


def tabs(active="new", saved=2):
    a, b = ("tab-item active", "tab-item") if active == "new" else ("tab-item", "tab-item active")
    return f'''<div class="tabs" role="tablist"><button class="{a}" role="tab">New area</button>
      <button class="{b}" role="tab">Saved areas ({saved})</button></div>'''


def area_sec(name="Negev", country="Israel (ISR)", readout=True, extra="", collapsed=False):
    if collapsed:
        return f'''<div class="sec"><button class="sec-head btn-ghost" aria-expanded="false" style="width:100%">
      <span class="glyph gl-chevron glyph-sm"></span><span class="t-heading grow" style="text-align:left">1 Area</span>
      <span class="t-caption muted">{name} · ISR · 11,094 km²</span></button></div>'''
    ro = '''<div class="kv t-small"><span class="muted">Bounding box</span><span class="mono">34.50, 30.50, 35.45, 31.60</span>
        <span class="muted">Area</span><span class="t-body-strong">11,094 km²</span>
        <span class="muted">area_id</span><span class="mono">isr_negev_e1bcadbc</span></div>''' if readout else ''
    nm = f' value="{name}"' if name else ' placeholder="e.g. negev"'
    ct = country or "Choose a country"
    return f'''<div class="sec" style="border-top:0;padding-top:0">
      <h4 class="sec-head t-heading">1 Area</h4>
      <div class="grid-2">
        <label class="field"><span class="field-label">Name</span><input class="input"{nm}></label>
        <label class="field"><span class="field-label">Country</span><button class="select" aria-haspopup="listbox">{ct}</button></label>
      </div>
      <div class="row" style="margin-top: var(--sp-3);"><button class="btn btn-secondary btn-sm"><span class="glyph gl-plus glyph-sm"></span>Upload GeoJSON</button>
        <span class="t-caption muted">or drop a file on the map</span></div>
      <div style="margin-top: var(--sp-3);">{ro}</div>{extra}</div>'''


def profile_sec(key=False, llm=False, collapsed=False):
    if collapsed:
        return '''<div class="sec"><button class="sec-head btn-ghost" aria-expanded="false" style="width:100%">
      <span class="glyph gl-chevron glyph-sm"></span><span class="t-heading grow" style="text-align:left">2 Country profile</span>
      <span class="badge badge-muted">Default</span></button></div>'''
    if llm:
        badge, body = '<span class="badge badge-accent">Chosen by the LLM</span>', '''
      <div class="kv t-small"><span class="muted">Districts</span><span>OpenStreetMap · admin level 8</span>
        <span class="muted">Facilities</span><span>amenity=hospital · emergency=yes</span></div>
      <p class="t-small muted" style="margin:0">Rationale (LLM): “Health services are planned by municipality here …”</p>'''
    else:
        badge, body = '<span class="badge badge-muted">Default · no LLM key</span>', '''
      <div class="kv t-small"><span class="muted">Districts</span><span>geoBoundaries · ADM1 → ADM2</span>
        <span class="muted">Facilities</span><span>amenity=hospital, clinic, doctors · healthcare=*</span></div>'''
    btn = ('<button class="btn btn-secondary btn-sm">Ask the LLM again</button>' if key else
           '<button class="btn btn-secondary btn-sm" disabled aria-describedby="nokey">Ask the LLM again</button><span class="t-caption muted" id="nokey">Needs an API key in .env</span>')
    return f'''<div class="sec"><div class="sec-head"><h4 class="t-heading grow" style="margin:0">2 Country profile</h4>{badge}</div>
      <div class="stack">{body}
      <p class="t-caption muted" style="margin:0">Pre-fills the districts and facilities options below.</p>
      <div class="row">{btn}</div></div></div>'''


SRC = [
    ("worldpop", "Population", "WorldPop · 2026 · 100m", "will download", "no snapshot for this area", "180 d"),
    ("boundaries", "Districts", "geoBoundaries · ADM1 → ADM2", "reuse", "2026-11-12T101414Z · 12 days old", "365 d"),
    ("osm_facilities", "Health facilities", "4 tags · from profile", "reuse", "2026-11-12T101415Z · 12 days old", "30 d"),
    ("osm_roads", "Roads", "16 highway types", "will download", "no snapshot for this area", "60 d"),
    ("gtfs", "Transit (GTFS)", "max 10 feeds", "will download", "no snapshot for this area", "14 d"),
]


def src_row(key, label, opts, state, detail, ttl, open_html="", override=None):
    if override:
        state, detail = override
    badge = {"reuse": '<span class="badge badge-muted">reuse</span>',
             "will download": '<span class="badge badge-muted">download</span>',
             "pinned": '<span class="badge badge-accent">pinned</span>',
             "invalid": '<span class="badge badge-muted"><span class="glyph gl-alert glyph-sm" style="color: var(--w-error)"></span>fix options</span>'}[state]
    exp = "true" if open_html else "false"
    return f'''<div class="src-row"><div class="src-line">
      <label class="choice"><input type="checkbox" checked aria-label="Include {label}"></label>
      <div class="text-stack"><span class="t-body-strong">{label}</span><span class="t-caption muted">{opts} · {detail}</span></div>
      <div class="row">{badge}<button class="btn-icon" aria-label="{label} options" aria-expanded="{exp}"><span class="glyph gl-chevron glyph-sm"></span></button></div>
    </div>{open_html}</div>'''


def sources_sec(overrides=None, opened=None, head_extra=""):
    overrides, opened = overrides or {}, opened or {}
    rows = "".join(src_row(*s, open_html=opened.get(s[0], ""), override=overrides.get(s[0])) for s in SRC)
    return f'''<div class="sec"><div class="sec-head"><h4 class="t-heading grow" style="margin:0">3 Sources</h4>
      <span class="t-caption muted">5 of 5 included</span>{head_extra}</div>{rows}</div>'''


def fetch_panel(plan, enabled=True, reason="", refresh=False, body=""):
    dis = "" if enabled else ' disabled aria-describedby="fetchwhy"'
    why = f'<p class="t-caption muted" id="fetchwhy" style="margin:0">{reason}</p>' if reason else ""
    sw = "true" if refresh else "false"
    return f'''<h4 class="t-title" style="margin:0">Fetch</h4>
    <p class="t-body" style="margin:0">{plan}</p>
    <div class="row"><button class="switch" role="switch" aria-checked="{sw}" aria-label="Refresh"></button>
      <div class="text-stack"><span class="t-body-strong">Refresh</span><span class="t-caption muted">Ignore the cache and download every included source</span></div></div>
    <button class="btn btn-primary btn-lg btn-block"{dis}>Fetch data</button>{why}{body}'''


def zoom():
    return '''<div class="map-br"><div class="toolgroup">
      <button class="btn-icon" aria-label="Zoom in"><span class="glyph gl-plus"></span></button>
      <button class="btn-icon" aria-label="Zoom out"><span class="icon icon-sm"></span></button>
      <button class="btn-icon" aria-label="Fit area"><span class="icon icon-sm"></span></button></div></div>'''


def draw_tools(active="rect"):
    def b(k, lbl):
        p = "true" if k == active else "false"
        return f'<button class="btn-icon" aria-label="{lbl}" aria-pressed="{p}"><span class="icon icon-sm"></span></button>'
    return f'''<div class="map-tl"><div class="toolgroup">{b("rect","Draw rectangle")}{b("poly","Draw polygon")}{b("edit","Edit vertices")}
      <button class="btn-icon" aria-label="Delete area"><span class="glyph gl-x glyph-sm"></span></button></div></div>'''


def shape(vertices=False, bad=False):
    cls = "area-shape bad" if bad else "area-shape"
    v = ""
    if vertices:
        for t, l in [("2", "2"), ("2", "5"), ("6", "2"), ("6", "5")]:
            v += f'<span class="vertex" style="top: calc(var(--sp-23) * {t} - var(--sp-2)); left: calc(var(--sp-23) * {l} - var(--sp-2));"></span>'
    return f'<div class="{cls}"></div>{v}'


def app(left, map_html, right, key=False):
    return f'''<div class="wf app">{header(key)}
  <div class="app-body">
    <section class="panel left" aria-label="Inputs">{left}</section>
    <div class="media map" role="region" aria-label="Map">{map_html}</div>
    <section class="panel right" aria-label="Fetch">{right}</section>
  </div></div>'''


def frame(fid, name, n, inner, items):
    frames.append(f'''<article class="frame" id="{fid}" style="width: 1440px">
  <h3 class="frame-plate"><span>{name}</span><span class="frame-pos">{n}/{TOTAL}</span></h3>
  <div style="position: relative;">{inner}</div></article>''')
    notes.append((fid, name, items))


def callout(title, text, kind="", action=""):
    k = f" {kind}" if kind else ""
    g = "gl-info" if kind == "accent" else "gl-alert"
    act = f'<div class="row" style="margin-top: var(--sp-2);">{action}</div>' if action else ""
    return f'''<div class="callout{k}"><span class="glyph {g}"></span><div class="callout-body">
      <p class="callout-title">{title}</p><p class="callout-text">{text}</p>{act}</div></div>'''


# ---------------------------------------------------------------- 1 first visit (empty)
left = tabs("new", 0) + area_sec(name="", country="", readout=False) + '''
  <div class="sec"><h4 class="sec-head t-heading">2 Country profile</h4><p class="t-small muted" style="margin:0">Appears when a country and an area are set.</p></div>
  <div class="sec"><h4 class="sec-head t-heading">3 Sources</h4><p class="t-small muted" style="margin:0">Population, districts, health facilities, roads, transit. Options and cache state appear once the area is set.</p></div>'''
mp = draw_tools("rect") + '''<div class="map-c"><div class="map-card stack" style="text-align:center">
    <p class="t-body-strong" style="margin:0">Draw a rectangle or polygon</p>
    <p class="t-small muted" style="margin:0">or drop a GeoJSON file here. Keyboard: Tab to the tools, then Enter to place points.</p></div></div>''' + zoom()
right = fetch_panel("Add a name, a country and an area to see what will be fetched.", False,
                    "Missing: name, country, area.")
frame("f-empty", "First visit: nothing set, empty cache", 1, app(left, mp, right), [
    "Inputs left, map centre, fetch right: the order of the work. The Fetch panel is always there, so the reason the button is disabled is always visible.",
    "Profile and Sources say what they will contain instead of rendering empty forms.",
    "The map hint names the keyboard path as well as the mouse one (include).",
    "Saved areas (0): the tab is still shown so returning users learn where saved areas live."])

# ---------------------------------------------------------------- 2 ready to fetch
left = tabs("new") + area_sec() + profile_sec() + sources_sec()
mp = draw_tools("edit") + shape(vertices=True) + zoom()
right = fetch_panel("2 sources reuse the cache, 3 will download.") + '''
  <ul class="t-small muted" style="margin:0;padding-left: var(--sp-5)">
    <li>Reuse: districts, health facilities</li><li>Download: population, roads, transit (one transit zip is 138 MB)</li></ul>'''
frame("f-ready", "Area set, ready to fetch (cached fixture)", 2, app(left, mp, right), [
    "Readout = exactly what the backend will use: bbox, km², area_id (the cache folder name).",
    "The profile card says which profile applies and why; without a key the LLM button is disabled with its reason next to it, not in a tooltip.",
    "Each source row predicts reuse vs download from /api/snapshots (same params and younger than TTL). The UI never re-implements TTL rules.",
    "The plan line turns the five predictions into one sentence before anything runs. Real fixture: districts and facilities reuse; population rebuilds from the shared download."])

# ---------------------------------------------------------------- 3 source options + validation
wp = '''<div class="src-opts stack">
  <div class="grid-2"><label class="field"><span class="field-label">Year</span><input class="input error" value="2040" aria-invalid="true" aria-describedby="yr-e">
    <span class="field-error" id="yr-e"><span class="glyph gl-alert glyph-sm"></span>Year must be 2015–2030</span></label>
  <label class="field"><span class="field-label">Resolution</span><button class="select">100m</button></label></div></div>'''
bd = '''<div class="src-opts stack">
  <p class="t-caption muted" style="margin:0">Edited · differs from the profile. <button class="link">Reset to profile</button></p>
  <fieldset style="border:0;padding:0;margin:0"><legend class="field-label">Provider</legend><div class="row">
    <button class="chip" aria-pressed="false">geoBoundaries</button><button class="chip active" aria-pressed="true">OpenStreetMap</button></div></fieldset>
  <label class="field"><span class="field-label">Levels, coarse to fine (last = districts)</span><input class="input error" value="4, ADM2" aria-invalid="true" aria-describedby="lv-e">
    <span class="field-error" id="lv-e"><span class="glyph gl-alert glyph-sm"></span>OpenStreetMap levels are numbers 2–11; “ADM2” is a geoBoundaries level</span></label></div>'''
fc = '''<div class="src-opts stack">
  <p class="field-label" style="margin:0">Tags (any match counts)</p>
  <div class="chips"><button class="chip">amenity = hospital <span class="glyph gl-x glyph-sm"></span></button><button class="chip">amenity = clinic <span class="glyph gl-x glyph-sm"></span></button>
    <button class="chip">amenity = doctors <span class="glyph gl-x glyph-sm"></span></button><button class="chip">healthcare = * <span class="glyph gl-x glyph-sm"></span></button></div>
  <div class="grid-3"><label class="field"><span class="field-label">Key</span><input class="input error" value="shop" aria-invalid="true" aria-describedby="tg-e"></label>
    <label class="field"><span class="field-label">Value</span><input class="input" value="chemist"></label>
    <div class="field"><span class="field-label">&nbsp;</span><button class="btn btn-secondary">Add tag</button></div></div>
  <span class="field-error" id="tg-e"><span class="glyph gl-alert glyph-sm"></span>Key must be amenity, healthcare or emergency</span>
  <label class="field"><span class="field-label">Pin a snapshot (instead of fetching)</span><button class="select">Don't pin: use the plan</button>
    <span class="field-hint">1 snapshot: 2026-11-12T101415Z (12 days old)</span></label></div>'''
left = tabs("new") + area_sec(collapsed=True) + profile_sec(collapsed=True) + sources_sec(
    overrides={"worldpop": ("invalid", "year out of range"), "boundaries": ("invalid", "edited · level format"),
               "osm_facilities": ("invalid", "tag key not allowed")},
    opened={"worldpop": wp, "boundaries": bd, "osm_facilities": fc})
right = fetch_panel("Fix 3 source options to see the plan.", False, "3 options need fixing: population year, district levels, a facility tag key.")
frame("f-options", "Sources: options open, with validation errors and the pin", 3, app(left, draw_tools("edit") + shape() + zoom(), right), [
    "Options sit under their own row (progressive disclosure); Area and Profile collapse to a one-line summary to make room.",
    "Validation is inline, names the rule, and uses the field's own terms (“ADM2 is a geoBoundaries level”). Errors read from glyph + text, not red alone.",
    "Edited profile options say so and offer Reset to profile: the user sees that their edit overrides the profile (fetch_all merges it that way).",
    "Pin lives in the row's options, listing that source's snapshots with their age. Facility tags are removable chips plus a key/value adder."])

# ---------------------------------------------------------------- 4 upload rejected
extra = '''<div class="drop error" style="margin-top: var(--sp-3);">
    <span class="glyph gl-alert" style="color: var(--w-error)"></span>
    <p class="t-body-strong" style="margin:0">galilee_districts.geojson wasn't used</p>
    <p class="t-small" style="margin:0">It contains 3 features, expected 1. Merge them into one polygon, or export just the area you want.</p>
    <button class="btn btn-secondary btn-sm">Choose another file</button></div>'''
left = tabs("new") + area_sec(name="galilee", readout=False, extra=extra) + '''
  <div class="sec"><h4 class="sec-head t-heading">2 Country profile</h4><p class="t-small muted" style="margin:0">Appears when the area is set.</p></div>'''
mp = draw_tools("rect") + '''<div class="map-c"><div class="map-card stack" style="text-align:center">
    <p class="t-body-strong" style="margin:0">Drop a GeoJSON file to use it as the area</p>
    <p class="t-small muted" style="margin:0">A Geometry, a Feature, or a FeatureCollection with exactly one feature</p></div></div>''' + zoom()
right = fetch_panel("Add an area to see what will be fetched.", False, "Missing: area.")
frame("f-upload", "Area: GeoJSON upload rejected", 4, app(left, mp, right), [
    "The rejected file is named, the reason uses the server's words (Area.from_geojson rules), and the fix is one sentence.",
    "The previous area (if any) is kept; a bad file never wipes a good shape.",
    "Other messages in the same slot: “Not valid JSON”, “Not GeoJSON (no type)”, “Geometry is invalid (edges cross)”, “Coordinates out of range: expected lon/lat”."])

# ---------------------------------------------------------------- 5 outside country + too large
extra = '<div class="stack" style="margin-top: var(--sp-3);">' + callout(
    "Too large to fetch", "142,300 km² is over the 100,000 km² limit. Draw a smaller area.", "error",
    '<button class="btn btn-secondary btn-sm">Edit shape</button>') + callout(
    "Mostly outside Israel", "About 85% of the area is outside the country border (geoBoundaries ADM0). Sources only have data inside the country. You can still fetch.",
    action='<button class="btn btn-ghost btn-sm">Show border</button>') + '</div>'
left = tabs("new") + area_sec(name="sinai test", readout=False, extra=extra).replace(
    '<div style="margin-top: var(--sp-3);"></div>',
    '<div class="kv t-small" style="margin-top: var(--sp-3);"><span class="muted">Bounding box</span><span class="mono">32.80, 28.60, 35.90, 31.80</span><span class="muted">Area</span><span class="t-body-strong">142,300 km²</span><span class="muted">area_id</span><span class="mono">isr_sinai-test_7c41f0aa</span></div>')
right = fetch_panel("Fix the area to see the plan.", False, "Blocked: area over 100,000 km².")
frame("f-area-bad", "Area: outside the country (warning) and too large (block)", 5, app(left, draw_tools("edit") + shape(bad=True) + zoom(), right), [
    "Blocks and warnings look different: a block has the error border and disables Fetch with the reason; a warning is neutral and leaves Fetch on.",
    "Outside-the-country is a warning, as specified: it states the share outside and offers to show the ADM0 border on the map.",
    "Limits (20,000 warn / 100,000 block km²) come from /api/config. The 20,000 warning uses the same neutral callout.",
    "Numbers in this frame are illustrative (no such area is cached)."])

# ---------------------------------------------------------------- 6 saved areas
saved = '''<div class="search"><span class="glyph gl-search glyph-sm"></span><input class="input" placeholder="Filter by name, country or id" aria-label="Filter saved areas"></div>
  <div class="list">
    <button class="list-row"><span class="icon icon-md"></span><div class="grow text-stack">
      <span class="t-body-strong">negev · ISR</span><span class="t-caption muted">isr_negev_e1bcadbc · 11,094 km² · 2 of 5 sources · newest 12 days old</span></div>
      <span class="glyph gl-chevron glyph-sm"></span></button>
    <button class="list-row"><span class="icon icon-md"></span><div class="grow text-stack">
      <span class="t-body-strong">negev · ISR</span><span class="t-caption muted">isr_negev_d25e423c · 14,010 km² · 5 of 5 sources · newest 12 days old</span></div>
      <span class="glyph gl-chevron glyph-sm"></span></button>
  </div>
  <p class="t-caption muted" style="margin:0">Areas are folders in data/raw with at least one manifest. Opening one restores its name, country and shape.</p>'''
left = tabs("saved") + saved
mp = '''<div class="area-shape" style="opacity: 0.5"></div><div class="area-shape" style="left: calc(var(--sp-23) * 2 - var(--sp-12)); width: calc(var(--sp-23) * 3 + var(--sp-12))"></div>''' + zoom()
right = fetch_panel("Open a saved area or draw a new one.", False, "Missing: area.")
frame("f-saved", "Returning user: saved areas", 6, app(left, mp, right), [
    "Two cached areas share the name “negev”: the area_id and size tell them apart, and hovering a row outlines its shape on the map.",
    "Rows say how complete each area is (sources present) and how old its newest snapshot is: the facts that decide whether to re-fetch.",
    "After opening the older one, its rows predict: population, roads, transit reuse; districts and facilities download because those fetchers' params changed since (real cache state)."])

# ---------------------------------------------------------------- 7 fetching (slow)
def prog(glyph, label, sub, right_html):
    g = {"ok": '<span class="glyph gl-check"></span>', "run": '<span class="spinner" aria-hidden="true"></span>',
         "q": '<span class="icon icon-sm"></span>', "fail": '<span class="glyph gl-alert" style="color: var(--w-error)"></span>'}[glyph]
    return f'<div class="prog-row">{g}<div class="text-stack"><span class="t-body-strong">{label}</span><span class="t-caption muted">{sub}</span></div>{right_html}</div>'

rows = (prog("ok", "Districts", "Reused from cache · 2026-11-12T101414Z", '<span class="t-caption">reused</span>')
        + prog("ok", "Health facilities", "Reused from cache · 2026-11-12T101415Z", '<span class="t-caption">reused</span>')
        + prog("ok", "Population", "Done · 2026-11-24T160502Z", '<span class="t-caption">4 s</span>')
        + prog("run", "Roads", "Running · Overpass query", '<span class="t-caption">38 s</span>')
        + prog("q", "Transit (GTFS)", "Queued", '<span class="t-caption muted">-</span>'))
body = f'''<div class="divider"></div>
  <div class="row"><span class="t-heading grow">Progress</span><span class="t-caption muted">3 of 5 · 46 s</span></div>
  <div aria-live="polite">{rows}</div>
  <p class="t-small muted" style="margin:0">Large downloads can take over a minute (transit: one zip is 138 MB).</p>
  {callout("No cancel", "A download can't be stopped safely once it starts. You can leave this page: the fetch keeps running and this panel reconnects.")}'''
right = fetch_panel("2 sources reuse the cache, 3 will download.", False, "Fetching… inputs are locked until it finishes.", body=body)
left = tabs("new") + area_sec(collapsed=True) + profile_sec(collapsed=True) + sources_sec(head_extra='<span class="badge badge-muted">locked</span>')
frame("f-running", "Fetching: slow source, cache hits resolve instantly", 7, app(left, draw_tools("edit") + shape() + zoom(), right), [
    "One row per source (one fetch_all call each): cache hits show “reused” immediately, so the user sees progress from the first second.",
    "Elapsed time per running source, plus a line that sets expectations after 10 s.",
    "No cancel, said plainly with what the user can do instead (leave; the job lives on the server).",
    "Inputs lock during the job so the plan can't drift from what is running; the map stays usable."])

# ---------------------------------------------------------------- 8 partial failure
rows = (prog("ok", "Districts", "Reused · 2 districts", '<span class="t-caption">reused</span>')
        + prog("ok", "Health facilities", "Reused · 200 facilities", '<span class="t-caption">reused</span>')
        + prog("ok", "Population", "Done · 749,331 people", '<span class="t-caption">4 s</span>')
        + prog("fail", "Roads: failed", "ConnectionError: overpass-api.de could not be reached (3 tries). Other sources are not affected.", '<button class="btn btn-secondary btn-sm">Retry</button>')
        + prog("fail", "Transit (GTFS): failed again (2 tries)", "ConnectionError: files.mobilitydatabase.org could not be reached.", '<button class="btn btn-secondary btn-sm">Retry</button>'))
body = f'''<div class="divider"></div>
  <div class="row"><span class="t-heading grow">Finished: 3 done, 2 failed</span><span class="t-caption muted">51 s</span></div>
  <div aria-live="polite">{rows}</div>
  <button class="btn btn-ghost btn-sm">Retry 2 failed</button>'''
right = fetch_panel("2 sources reuse the cache, 3 will download.", True, body=body)
left = tabs("new") + area_sec(collapsed=True) + profile_sec(collapsed=True) + sources_sec()
mp = draw_tools("edit") + shape() + '''<div class="map-tr"><div class="map-card stack">
    <p class="t-body-strong" style="margin:0">Layers</p>
    <label class="choice"><input type="checkbox" checked> Area (dashed)</label>
    <label class="choice"><input type="checkbox" checked> Districts (outline + name)</label>
    <label class="choice"><input type="checkbox" checked> Facilities (◆, numbered clusters)</label></div></div>''' + zoom()
frame("f-failed", "Partial failure with Retry (network off: the real offline outcome)", 8, app(left, mp, right), [
    "Failure is per source: the word “failed” + glyph + the error message, never colour alone. Successful sources stay usable.",
    "Retry re-runs that source only, with the same area, options, profile and pin; a second failure says “failed again (2 tries)”.",
    "These two failures are what the cached fixture really does offline: Overpass and the GTFS catalog need the network.",
    "The Fetch button stays enabled after the job: running it again follows the plan line."])

# ---------------------------------------------------------------- 9 results + layers + manifest
def rcard(title, sid, fetched, summary, files, path):
    fl = "".join(f'<span class="muted">{f}</span><span class="num">{s}</span>' for f, s in files)
    return f'''<div class="card result-card"><div class="card-body">
      <div class="row"><span class="t-heading grow">{title}</span><span class="badge badge-muted">{summary[0]}</span></div>
      <p class="t-body-strong" style="margin:0">{summary[1]}</p>
      <div class="kv t-caption"><span class="muted">Snapshot</span><span class="mono">{sid}</span><span class="muted">Fetched</span><span>{fetched}</span>
        <span class="muted">Folder</span><span class="mono">{path}</span>{fl}</div>
      <div class="row"><button class="btn btn-ghost btn-sm">View manifest</button><button class="btn btn-ghost btn-sm">Copy path</button></div></div></div>'''

cards = (rcard("Districts", "2026-11-12T101414Z", "12 Nov 2026, 10:14 UTC", ("reused", "2 districts (ADM2) · 1 ADM1 unit"),
               [("districts.geojson", "13.3 KB"), ("adm1.geojson", "4.1 KB"), ("adm2.geojson", "13.3 KB")], "data/raw/isr_negev_e1bcadbc/boundaries/2026-11-12T101414Z")
         + rcard("Health facilities", "2026-11-12T101415Z", "12 Nov 2026, 10:14 UTC", ("reused", "200 facilities"),
                 [("facilities.geojson", "46.7 KB")], "data/raw/isr_negev_e1bcadbc/osm_facilities/2026-11-12T101415Z"))
body = f'''<div class="divider"></div>
  <div class="row"><span class="t-heading grow">Results</span><span class="t-caption muted">3 done, 2 failed</span></div>
  {cards}<p class="t-caption muted" style="margin:0">+ Population card (749,331 people · population.tif 0.5 MB) below</p>'''
right = fetch_panel("2 sources reuse the cache, 3 will download.", True, body=body)
mp = draw_tools("edit") + shape() + '''
  <div class="district" style="top: calc(var(--sp-23) * 2); left: calc(var(--sp-23) * 2); width: calc(var(--sp-23) * 3); height: calc(var(--sp-23) * 3);"></div>
  <span class="district-label t-small" style="top: calc(var(--sp-23) * 3); left: calc(var(--sp-23) * 3);">Be'er Sheva</span>
  <span class="district-label t-small" style="top: calc(var(--sp-23) * 2 - var(--sp-6)); left: calc(var(--sp-23) * 2);">Ashqelon</span>
  <span class="cluster" style="top: calc(var(--sp-23) * 2 + var(--sp-10)); left: calc(var(--sp-23) * 3 + var(--sp-10));">64</span>
  <span class="cluster" style="top: calc(var(--sp-23) * 4); left: calc(var(--sp-23) * 2 + var(--sp-8));">23</span>
  <span class="fac" style="top: calc(var(--sp-23) * 5); left: calc(var(--sp-23) * 4);"></span>
  <div class="popup map-card stack" style="top: calc(var(--sp-23) * 5 + var(--sp-5)); left: calc(var(--sp-23) * 4 - var(--sp-10));">
    <div class="row"><span class="t-body-strong grow">Al Mizan Hospital</span><button class="btn-icon" aria-label="Close"><span class="glyph gl-x glyph-sm"></span></button></div>
    <div class="kv t-caption"><span class="muted">amenity</span><span>hospital</span><span class="muted">healthcare</span><span>hospital</span><span class="muted">emergency</span><span>-</span><span class="muted">osm_id</span><span class="mono">node/431850794</span></div></div>
  <div class="map-tr"><div class="map-card stack">
    <p class="t-body-strong" style="margin:0">Layers</p>
    <label class="choice"><input type="checkbox" checked> Area (dashed line)</label>
    <label class="choice"><input type="checkbox" checked> Districts (solid outline, labelled)</label>
    <label class="choice"><input type="checkbox" checked> Facilities (◆ diamond; circle = cluster with count)</label></div></div>''' + zoom()
drawer = '''<div class="drawer" role="dialog" aria-label="Manifest: districts">
    <div class="row"><span class="t-heading grow">manifest.json · Districts</span><button class="btn btn-ghost btn-sm">Copy</button>
      <button class="btn-icon" aria-label="Close manifest"><span class="glyph gl-x"></span></button></div>
    <p class="t-caption muted" style="margin:0">Read-only · data/raw/isr_negev_e1bcadbc/boundaries/2026-11-12T101414Z/manifest.json</p>
    <div class="codebox">{
  "source": "boundaries",
  "area_id": "isr_negev_e1bcadbc",
  "fetched_at": "2026-11-12T10:14:14.613830+00:00",
  "params": { "provider": "geoboundaries",
              "levels": ["ADM1", "ADM2"],
              "simplified": true },
  "urls": [ "https://www.geoboundaries.org/api/…/ADM1/",
            "… 3 more" ],
  "summary": { "units": { "ADM1": 1, "ADM2": 2 },
               "districts": 2 },
  "files": { "districts.geojson": { "bytes": 13313,
             "sha256": "…" }, … }
}</div></div>'''
left9 = tabs("new") + area_sec(collapsed=True) + profile_sec(collapsed=True) + sources_sec()
frame("f-results", "Results: cards, district + facility layers", 9, app(left9, mp, right), [
    "One card per source: summary in words first, then snapshot id, fetched_at, folder and files with sizes. Real fixture values.",
    "Layers: area = dashed line, districts = solid outline + name label, facilities = diamonds that cluster into numbered circles when zoomed out. Shape and line style identify each layer without colour (include).",
    "Facility popup shows the name and the tags the fetcher saved (amenity, healthcare, emergency, osm_id).",
    "The popup shows a real record from the cached facilities.geojson. View manifest: next frame."])
frame("f-manifest", "Manifest viewer (read-only drawer)", 10, app(left9, mp + drawer, right), [
    "Raw manifest.json, read-only, with Copy and the file path. Esc closes; focus returns to the View manifest button that opened it.",
    "The drawer covers the map, not the result cards, so the user can open another card's manifest without closing first.",
    "Long values wrap; the hash and URLs stay selectable for copying."])

# ---------------------------------------------------------------- assemble
rail = "".join(
    f'<div class="note-group" data-for="{fid}"><p class="note-frame">{name}</p>'
    + "".join(f'<p><span class="note-num">{i}</span> {t}</p>' for i, t in enumerate(items, 1)) + "</div>"
    for fid, name, items in notes)
css = "\n".join(p.read_text() for p in (REF / "design-system.css", REF / "viewer.css", HERE / "layout.css"))
js = (REF / "viewer.js").read_text()
OUT.write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>LEG data fetcher: wireframes</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='6' fill='%234338ca'/%3E%3C/svg%3E">
<style>{css}</style></head>
<body data-view="grid">
<header class="board-header">
  <div class="board-id"><h1 class="board-title">LEG data fetcher: wireframes</h1>
  <p class="board-meta">Intent /wireframe · November 2026 · full-page wireframes</p></div>
  <div class="board-controls">
    <nav class="view-toggle" aria-label="View"><button data-setview="grid" aria-pressed="true">Grid</button><button data-setview="slides" aria-pressed="false">Slides</button></nav>
    <button class="theme-toggle" data-toggle-theme><span class="swatch" aria-hidden="true"></span><span class="theme-label">Dark</span></button>
  </div>
</header>
<nav class="slide-nav"><span class="slide-section">Fetcher screen</span><span class="slide-pos">1/{TOTAL}</span>
  <span class="nav-hint slides-hint">← → to page · Esc returns to grid</span>
  <button data-prev aria-label="Previous"></button><button data-next aria-label="Next"></button></nav>
<section class="board-section" data-section="Fetcher screen">
  <h2 class="section-label">Fetcher screen</h2>
  <div class="frame-grid">{"".join(frames)}</div>
  <aside class="note-rail"><p>Wireframes: the structure is up for debate; styling doesn't exist yet. Values come from the cached fixture (ISR, 34.5,30.5,35.45,31.6) unless a note says otherwise.</p>{rail}</aside>
</section>
<script>{js}</script>
</body></html>''')
print("wrote", OUT)
