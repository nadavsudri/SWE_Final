import "./styles.css";
import { api, ApiError, type AreaIn, type AreaMode, type Level, type LevelJob, type SnapResp, type Config, type Country, type Geo, type Job, type JobRow, type PlanRow, type Profile, type SavedArea, type SourceSpec, type Validation } from "./api";
import { hydrateIcons, icon } from "./icons";
import { AreaMap, type Tool } from "./map";

// ── state ────────────────────────────────────────────────────────────
const S = {
  config: null as Config | null,
  countries: [] as Country[],
  specs: [] as SourceSpec[],
  saved: [] as SavedArea[],
  name: "",
  iso3: "",
  geom: null as Geo | null,
  validation: null as Validation | null,
  validating: false,
  profile: null as Profile | null,
  profileFor: "",
  profileLoading: false,
  profileError: "",
  plan: null as Record<string, PlanRow> | null,
  planError: "",
  included: new Set<string>(),
  overrides: {} as Record<string, Record<string, unknown>>,
  pinned: {} as Record<string, string>,
  open: new Set<string>(),
  refresh: false,
  job: null as Job | null,
  jobError: "",
  starting: false,
  uploadError: null as { file: string; message: string } | null,
  layers: { districts: 0, facilities: 0, hasDistricts: false, hasFacilities: false },
  drawer: null as null | { title: string; path: string; json: string; from: HTMLElement | null },
  replaced: null as Geo | null,
  facilities: [] as GeoJSON.Feature<GeoJSON.Point>[],
  facListOpen: false,
  countryAuto: true,   // country was filled in from the area, not chosen
  nameAuto: true,      // name was filled in, not typed
  shares: [] as { iso3: string; name: string; share: number }[],
  street: false,
  streetClip: false,
  streetBusy: false,
  streetError: "",
  mode: "snap" as "snap" | "free",
  minShare: 0.5,
  include: new Set<string>(),
  exclude: new Set<string>(),
  snap: null as SnapResp | null,
  snapping: false,
  snapError: "",
  levels: null as LevelJob | null,       // the rule's count per level (choose_level), with progress
  levelOverride: null as Level | null,    // the user's level, replacing the rule's choice
};
const levelName = (l: Level) => `${l.provider === "osm" ? "OSM admin level" : "geoBoundaries"} ${l.level}`;
// the level the area will use: the user's override, else the rule's choice
const usedLevel = (): Level | null => S.levelOverride ?? (S.levels?.choice ? { provider: S.levels.choice.provider, level: S.levels.choice.level } : null);
const areaMode = (): AreaMode => ({ mode: S.mode, min_share: S.minShare, include: [...S.include], exclude: [...S.exclude] });
const pct = (x: number) => `${Math.round(x * 100)}%`;
const NE_TO_ISO: Record<string, string> = { PSX: "PSE", SDS: "SSD", SAH: "ESH" }; // Natural Earth codes that differ from ISO 3166
const PROFILE_FED = new Set(["boundaries", "osm_facilities"]);
const STORE = "leg-fetcher";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmtInt = (n: number) => Math.round(n).toLocaleString("en-US");
const announce = (msg: string) => { const a = $("announcer"); a.textContent = ""; setTimeout(() => (a.textContent = msg), 30); };
const label = (src: string) => S.specs.find((s) => s.source === src)?.label ?? src;
const two = (i: number) => String(i + 1).padStart(2, "0");
const ageText = (d: number) => (d < 1 ? "today" : `${Math.round(d)}\u00a0day${Math.round(d) === 1 ? "" : "s"}\u00a0old`);
// escaped sub-line text with snapshot ids set in mono and kept on one line
const sub = (s: string) => esc(s).replace(/(\d{4}-\d\d-\d\dT\d{6}Z)/g, '<span class="mono nowrap">$1</span>');
const running = () => !!S.job?.running || S.starting;

function areaIn(): AreaIn | null {
  if (!S.geom) return null;
  return { name: S.name.trim(), iso3: S.iso3, geojson: S.geom };
}

function persist(): void {
  try {
    sessionStorage.setItem(STORE, JSON.stringify({ name: S.name, iso3: S.iso3, geom: S.geom, overrides: S.overrides, pinned: S.pinned,
      mode: S.mode, minShare: S.minShare, include: [...S.include], exclude: [...S.exclude], levelOverride: S.levelOverride,
      included: [...S.included], refresh: S.refresh, jobId: S.job?.job_id ?? null }));
  } catch { /* storage unavailable: nothing to restore later */ }
}

// ── map ──────────────────────────────────────────────────────────────
const map = new AreaMap($("map"));
map.onAnnounce = announce;
map.legendBottom = () => { const l = $("map-layers"); return l.hidden ? 0 : l.offsetTop + l.offsetHeight; };
map.onArea = (g) => { S.geom = g; S.uploadError = null; S.replaced = null; clearChoices(); autoFill(); onAreaChanged(); };
map.onDistrictClick = (uid) => toggleDistrict(uid);
map.onStreetError = (msg) => { S.streetError = msg; renderLayersPanel(); };

// ── country + name from the area (editable; only fills what the user hasn't chosen) ──
const slug = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
function autoFill(): void {
  if (!S.geom || map.failed) { S.shares = []; renderDetect(); return; }
  S.shares = map.countryShares(S.geom)
    .map((c) => ({ ...c, iso3: NE_TO_ISO[c.iso3] ?? c.iso3 }))
    .filter((c) => S.countries.some((x) => x.iso3 === c.iso3) && c.share >= 0.01);
  const top = S.shares[0];
  if (top && (S.countryAuto || !S.iso3)) { pickCountry(top.iso3, false); S.countryAuto = true; }
  if (S.nameAuto && S.iso3) {
    const c = S.countries.find((x) => x.iso3 === S.iso3);
    S.name = slug(c?.name ?? S.iso3); $<HTMLInputElement>("area-name").value = S.name;
  }
  renderDetect();
}
function renderDetect(): void {
  const el = $("country-detect");
  const top = S.shares[0];
  el.hidden = !top;
  if (!top) return;
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const others = S.shares.filter((c) => c.iso3 !== S.iso3).slice(0, 3);
  const cur = S.shares.find((c) => c.iso3 === S.iso3);
  const lead = S.countryAuto && cur
    ? `<span>Country from the area: <b>${esc(countryText(S.iso3))}</b> ${pct(cur.share)}</span>`
    : cur ? `<span>${pct(cur.share)} of the area is in ${esc(countryText(S.iso3))}.</span>`
      : `<span>None of the area is in ${esc(countryText(S.iso3) || "the chosen country")}.</span>`;
  el.innerHTML = lead + (others.length ? `<span>${cur ? "Also" : "It is in"}: ${others.map((c) =>
    `<button class="link" type="button" data-use-country="${c.iso3}">${esc(c.name)} ${pct(c.share)}</button>`).join(", ")}</span>` : "");
}
$("country-detect").addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest<HTMLElement>("[data-use-country]");
  if (!b) return;
  S.countryAuto = false; pickCountry(b.dataset.useCountry!, false);
  if (S.nameAuto) { S.name = slug(S.countries.find((x) => x.iso3 === S.iso3)?.name ?? S.iso3); $<HTMLInputElement>("area-name").value = S.name; onAreaChanged(); }
  renderDetect(); announce(`Country set to ${countryText(S.iso3)}.`);
});
map.onToolChange = () => { renderTools(); renderHint(); };
map.onReplaced = (prev) => { S.replaced = prev; renderReadout(); announce("The new shape replaced the previous area. Undo is available under 1 · Area."); };
$("map").addEventListener("focus", renderHint);
$("map").addEventListener("blur", () => ($("crosshair").hidden = true));

// ── area validation → profile → plan ─────────────────────────────────
let vTimer = 0, vSeq = 0;
function onAreaChanged(): void {
  dropFinishedJob();
  persist();
  renderReadout();
  renderHint();
  renderLayersPanel();
  clearTimeout(vTimer);
  vTimer = window.setTimeout(validate, 250);
}

async function validate(): Promise<void> {
  const a = areaIn();
  const seq = ++vSeq;
  if (!a) { S.validation = null; S.plan = null; renderAll(); return; }
  S.validating = true; renderReadout();
  try {
    const v = await api.validate(a);
    if (seq !== vSeq) return;
    S.validation = v;
  } catch (e) {
    if (seq !== vSeq) return;
    S.validation = { ok: false, warnings: [], errors: [{ code: "server", message: (e as Error).message }] };
  }
  S.validating = false;
  // an auto-filled name follows a cached area with the same shape, so its snapshots are reused
  const same = S.validation?.same_shape ?? [];
  if (S.nameAuto && same.length && S.validation?.area_id && !same.includes(S.validation.area_id)) {
    // the folder is <iso3>_<name slug>_<shape hash>: its middle part is the name that reuses it
    const cachedName = same[0].slice(S.iso3.length + 1, same[0].lastIndexOf("_"));
    if (cachedName) { S.name = cachedName; $<HTMLInputElement>("area-name").value = cachedName; announce(`This shape is already cached as “${cachedName}”; using that name.`); return validate(); }
  }
  renderAll();
  if (S.validation?.ok) {
    const key = `${S.iso3}|${S.validation.area_id}`;
    if (S.profileFor !== key) await loadProfile(false);
    await refreshTarget();
  }
}

async function loadProfile(refresh: boolean): Promise<void> {
  const a = areaIn();
  if (!a) return;
  S.profileLoading = true; S.profileError = ""; renderProfile();
  try {
    S.profile = await api.profile(a, refresh);
    S.profileFor = `${S.iso3}|${S.validation?.area_id}`;
    if (refresh) announce(S.profile.source === "llm" ? "The LLM chose a new profile." : "The LLM call failed; defaults are used.");
  } catch (e) {
    S.profileError = (e as Error).message;
  }
  S.profileLoading = false;
  renderProfile();
  renderSources();
}

let pTimer = 0, pSeq = 0;
function schedulePlan(): void { persist(); clearTimeout(pTimer); pTimer = window.setTimeout(refreshTarget, 250); }

// ── area modes: the area every source will use (snapped to whole districts, or the drawing) ──
async function refreshTarget(): Promise<void> {
  if (!(await loadLevels())) { S.snap = null; S.plan = null; map.setSnap(null, null); renderAll(); return; }
  await loadSnap();
  await loadPlan();
}

// ── district level: the rule counts usable districts per level (probing each once, then cached) ──
let lSeq = 0;
async function loadLevels(): Promise<boolean> {
  const a = areaIn();
  if (!a || !S.validation?.ok) { S.levels = null; return false; }
  const seq = ++lSeq;
  try {
    let j = await api.levels(a, areaMode());
    S.levels = j; renderLevelsProgress();
    while (j.status === "running") {
      await new Promise((r) => setTimeout(r, 400));
      if (seq !== lSeq) return false;
      j = await api.levelJob(j.job_id);
      S.levels = j; renderLevelsProgress();
    }
  } catch (e) {
    if (seq !== lSeq) return false;
    S.levels = { job_id: "", status: "failed", probing: null, probed: [], choice: null, error: (e as Error).message, area_id: "", mode: S.mode, min_share: S.minShare };
  }
  if (seq !== lSeq) return false;
  if (S.levels?.status === "done" && S.levelOverride && !S.levels.choice?.counts.some((c) => c.available && c.provider === S.levelOverride!.provider && c.level === S.levelOverride!.level)) {
    S.levelOverride = null; // the saved level doesn't exist for this drawing
  }
  if (S.levels?.status === "done") announce(`District level: ${levelName(usedLevel()!)}${S.levelOverride ? " (your choice)" : " (chosen by the rule)"}.`);
  else if (S.levels?.status === "failed") announce("Couldn't count districts per level. See the Districts source.");
  renderSources(); renderManifest();
  return S.levels?.status === "done";
}

function renderLevelsProgress(): void { renderSources(); renderManifest(); renderSnap(); }

function setLevel(l: Level | null): void {
  const rule = S.levels?.choice;
  S.levelOverride = l && rule && (l.provider !== rule.provider || l.level !== rule.level) ? l : null;
  clearChoices(); // other level, other district ids
  dropFinishedJob();
  announce(S.levelOverride ? `Using ${levelName(S.levelOverride)} (your choice).` : "Using the rule's level.");
  schedulePlan();
}

function levelPanel(): string {
  const L = S.levels;
  if (!L) return `<p class="hint">Appears when the area is set.</p>`;
  const rowsFor = (counts: { provider: string; level: string; available: boolean; touched: number; usable: number; note?: string }[], live: boolean) => {
    const used = usedLevel();
    const rule = L.choice;
    return `<table class="lvl-table"><caption class="sr-only">Usable districts per level</caption>
      <thead><tr><th scope="col"><span class="sr-only">Use</span></th><th scope="col">Level</th><th scope="col" class="num">Touched</th><th scope="col" class="num" title="${S.mode === "snap" ? `at least ${pct(S.minShare)} inside the drawing` : "every district the drawing touches"}">Usable</th><th scope="col">Available</th></tr></thead>
      <tbody>${counts.map((c) => {
        const id = `${c.provider}|${c.level}`;
        const isRule = !!rule && rule.provider === c.provider && rule.level === c.level;
        const isUsed = !!used && used.provider === c.provider && used.level === c.level;
        const tag = isUsed && S.levelOverride ? `<span class="stamp carbon">your choice</span>` : isRule ? `<span class="stamp ok">rule's choice</span>` : "";
        return `<tr class="${isUsed ? "chosen" : ""}${isRule ? " rule" : ""}"><td><input type="radio" name="lvl" value="${esc(id)}" aria-label="Use ${esc(levelName(c))}" ${isUsed ? "checked" : ""} ${!c.available || live || running() ? "disabled" : ""}/></td>
          <td><b>${esc(c.provider === "osm" ? `OSM ${c.level}` : c.level)}</b> ${tag}</td><td class="num">${c.available ? c.touched : "-"}</td><td class="num">${c.available ? c.usable : "-"}</td>
          <td>${c.available ? (c.note ? esc(c.note) : "yes") : `<span class="muted-cell">no</span>`}</td></tr>`;
      }).join("")}</tbody></table>`;
  };
  if (L.status === "running") {
    const probed = L.probed.map((p) => ({ provider: p.provider, level: p.level, available: p.state !== "missing", touched: 0, usable: 0, note: p.state }));
    return `<p class="lvl-progress" role="status"><span class="spinner-inline" aria-hidden="true"></span>Counting districts per level${L.probing ? `… probing ${esc(levelName(L.probing))}` : "…"} (${L.probed.length} done). Each level is downloaded once, then cached.</p>
      ${probed.length ? rowsFor(probed, true) : ""}`;
  }
  if (L.status === "failed") {
    return `<div class="note block" role="alert"><span class="ic">${icon("alert")}</span><b>Couldn't choose a district level</b><p>${esc(plainError(L.error ?? ""))}</p>
      <details class="line-raw"><summary>Error details</summary><code>${esc(L.error ?? "")}</code></details>
      <div class="note-actions"><button class="btn btn-sm" type="button" id="lvl-retry"><span class="ic">${icon("retry")}</span>Retry</button></div></div>`;
  }
  const c = L.choice!;
  return `<p class="lvl-reason">${S.levelOverride ? `Using <b>${esc(levelName(S.levelOverride))}</b> (your choice). The rule picked ${esc(levelName(c))}: ${esc(c.reason)}.`
      : `The rule picked <b>${esc(levelName(c))}</b>: ${esc(c.reason)}.`}</p>
    ${c.in_range ? "" : `<div class="note warn"><span class="ic">${icon("alert")}</span><b>No level has 10-100 usable districts; using the closest.</b><p>Pick another level below if a different one fits better.</p></div>`}
    ${rowsFor(c.counts, false)}
    <p class="hint">Usable: ${S.mode === "snap" ? `districts at least ${pct(S.minShare)} inside the drawing` : "every district the drawing touches"}. Pick a row to use that level instead.</p>
    ${S.levelOverride ? `<button class="btn btn-sm" type="button" id="lvl-reset">Use the rule's choice</button>` : ""}`;
}

let sSeq = 0;
async function loadSnap(): Promise<void> {
  const a = areaIn();
  if (S.mode !== "snap" || !a || !S.validation?.ok) {
    S.snap = null; S.snapError = ""; map.setSnap(null, null); renderSnap(); return;
  }
  const seq = ++sSeq;
  S.snapping = true; S.snapError = ""; renderSnap(); renderManifest();
  try {
    const r = await api.snap(a, S.overrides, areaMode(), S.levelOverride);
    if (seq !== sSeq) return;
    S.snap = r;
    map.setSnap(r.districts, r.geojson);
    if (r.ok) announce(`Snapped to ${r.districts.filter((d) => d.included).length} whole districts, ${fmtInt(r.km2 ?? 0)} square kilometres.`);
    else if (r.error) announce(r.error.code === "no_district_qualifies" ? "No district reaches the threshold. Fixes are listed under the area." : "Couldn't get the districts for the drawing.");
  } catch (e) {
    if (seq !== sSeq) return;
    S.snap = null; S.snapError = (e as Error).message; map.setSnap(null, null);
  }
  S.snapping = false;
  renderSnap(); renderReadout(); renderManifest(); renderLayersPanel();
}

function clearChoices(): void { S.include.clear(); S.exclude.clear(); }

// a finished fetch belongs to the area it was made for: once the area changes, show the new plan
function dropFinishedJob(): void {
  if (S.job && !S.job.running) { S.job = null; S.jobError = ""; renderDockets(); }
}

function toggleDistrict(uid: string): void {
  if (running() || S.mode !== "snap") return;
  const d = S.snap?.districts.find((x) => x.unit_id === uid);
  if (!d) return;
  if (d.included) { if (S.include.has(uid)) S.include.delete(uid); else S.exclude.add(uid); }
  else { if (S.exclude.has(uid)) S.exclude.delete(uid); else S.include.add(uid); }
  announce(`${d.name ?? uid} ${d.included ? "removed" : "added"}. Re-snapping.`);
  dropFinishedJob();
  schedulePlan();
}

const REASON: Record<string, string> = { majority: "majority inside", minority: "minority inside", "added by user": "added by you", "removed by user": "removed by you" };

function renderSnap(): void {
  const p = $("snap-panel");
  p.hidden = S.mode !== "snap" || !S.validation?.ok;
  if (p.hidden) return;
  const u = usedLevel();
  const rule = `<p class="snap-rule">${u ? `Districts: <b>${esc(levelName(u))}</b> (${S.levelOverride ? "your choice" : "chosen by the rule"}). ` : ""}A district is included when at least <b>${pct(S.minShare)}</b> of it is inside the drawing (change it under Advanced). Click a district on the map, or tick it here, to add or remove it.</p>`;
  if (S.levels?.status === "running") {
    p.innerHTML = `<h3 class="snap-head" id="snap-head">Districts in the drawing<span>choosing the level…</span></h3>${rule}<p class="lvl-progress" style="padding:8px 12px"><span class="spinner-inline" aria-hidden="true"></span>Counting districts per level${S.levels.probing ? `: ${esc(levelName(S.levels.probing))}` : ""}…</p>`;
    return;
  }
  if (S.levels?.status === "failed") {
    p.innerHTML = `<h3 class="snap-head" id="snap-head">Districts in the drawing</h3><div class="note block" role="alert"><span class="ic">${icon("alert")}</span><b>No district level to snap to</b><p>${esc(S.levels.error ?? "")}</p><div class="note-actions"><button class="btn btn-sm btn-quiet" type="button" data-set-mode="free">Use the free polygon instead</button></div></div>`;
    return;
  }
  if (S.snapping && !S.snap) {
    p.innerHTML = `<h3 class="snap-head" id="snap-head">Districts in the drawing<span>checking…</span></h3>${rule}<div style="padding:8px 12px"><div class="skeleton" style="width:80%"></div><div class="skeleton" style="width:60%"></div></div>`;
    return;
  }
  if (S.snapError) {
    p.innerHTML = `<h3 class="snap-head" id="snap-head">Districts in the drawing</h3><div class="note block" role="alert"><span class="ic">${icon("alert")}</span><b>Can't snap with these choices</b><p>${esc(S.snapError)}</p><div class="note-actions"><button class="btn btn-sm" type="button" id="snap-reset">Clear my additions and removals</button></div></div>`;
    return;
  }
  const r = S.snap;
  if (!r) { p.innerHTML = ""; return; }
  if (r.error?.code === "boundaries_failed") {
    p.innerHTML = `<h3 class="snap-head" id="snap-head">Districts in the drawing</h3><div class="note block" role="alert"><span class="ic">${icon("alert")}</span><b>Couldn't get the districts for the drawing</b>
      <p>Snapping needs the districts first. ${esc(plainError(r.error.message))}</p><details class="line-raw"><summary>Error details</summary><code>${esc(r.error.message)}</code></details>
      <div class="note-actions"><button class="btn btn-sm" type="button" id="snap-retry"><span class="ic">${icon("retry")}</span>Retry</button><button class="btn btn-sm btn-quiet" type="button" data-set-mode="free">Use the free polygon instead</button></div></div>`;
    return;
  }
  const inc = r.districts.filter((d) => d.included).length;
  let none = "";
  if (r.error?.code === "no_district_qualifies") {
    const best = r.districts.slice().sort((a, b) => b.share_inside_area - a.share_inside_area).slice(0, 3)
      .map((d) => `${esc(d.name ?? d.unit_id)} ${pct(d.share_inside_area)}`).join(", ");
    none = `<div class="note block" role="alert"><span class="ic">${icon("alert")}</span><b>No district is at least ${pct(S.minShare)} inside the drawing</b>
      <p>The whole-district area would be empty, so there is nothing to fetch yet. Closest: ${best || "none"}.</p>
      <div class="snap-fixes"><button class="btn btn-sm" type="button" id="fix-add">Add districts: click them on the map or tick them below</button>
      <button class="btn btn-sm" type="button" id="fix-level">Pick another district level (Districts source)</button>
      <button class="btn btn-sm" type="button" id="fix-draw">Draw a larger area</button></div></div>`;
  }
  p.innerHTML = `<h3 class="snap-head" id="snap-head">Districts in the drawing<span>${inc} of ${r.districts.length} included${S.snapping ? " · updating…" : ""}</span></h3>${rule}${none}
    <ul class="snap-list">${r.districts.map((d) => `<li><label><input type="checkbox" class="check" data-district="${esc(d.unit_id)}" ${d.included ? "checked" : ""} ${running() ? "disabled" : ""}/>
      <span><span>${esc(d.name ?? d.unit_id)}</span><span class="why">${REASON[d.reason] ?? d.reason}${d.fully_inside ? " · fully inside" : ""}</span></span>
      <span class="share">${pct(d.share_inside_area)}</span></label></li>`).join("")}</ul>`;
}
$("snap-panel").addEventListener("change", (e) => {
  const t = e.target as HTMLInputElement;
  if (t.dataset.district) toggleDistrict(t.dataset.district);
});
$("snap-panel").addEventListener("click", (e) => {
  const t = e.target as HTMLElement;
  if (t.closest("#snap-retry")) { loadSnap().then(loadPlan); return; }
  if (t.closest("#snap-reset")) { clearChoices(); schedulePlan(); return; }
  const m = t.closest<HTMLElement>("[data-set-mode]");
  if (m) { setMode(m.dataset.setMode as "snap" | "free"); return; }
  if (t.closest("#fix-add")) { (document.querySelector("#snap-panel [data-district]:not(:checked)") as HTMLElement | null)?.focus(); return; }
  if (t.closest("#fix-level")) {
    S.open.add("boundaries"); $("sources-body").closest(".sec")?.querySelector<HTMLButtonElement>(".sec-toggle[aria-expanded=false]")?.click();
    renderSources();
    const lv = document.querySelector<HTMLInputElement>("#lvl-panel input[name=lvl]:not(:checked):not(:disabled)") ?? document.querySelector<HTMLElement>("#lvl-panel") as HTMLInputElement | null;
    lv?.scrollIntoView({ block: "center" }); lv?.focus();
    announce("District levels table: pick another level.");
    return;
  }
  if (t.closest("#fix-draw")) { map.setTool("rect"); $("map").focus(); announce("Rectangle tool. Draw a larger area."); }
});

function setMode(m: "snap" | "free"): void {
  if (running() || m === S.mode) return;
  S.mode = m;
  dropFinishedJob();
  renderMode();
  announce(m === "free" ? "Free polygon. Expert advice will be taken into account only for districts the polygon covers completely."
    : "Whole districts. The area becomes the districts the drawing mostly covers.");
  schedulePlan();
}

function renderMode(): void {
  document.querySelectorAll<HTMLButtonElement>(".mode-pick [data-mode]").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.mode === S.mode)); b.disabled = running();
  });
  const free = S.mode === "free";
  $("mode-hint").innerHTML = free
    ? `<b style="color:var(--warn)">Expert advice will be taken into account only for districts the polygon covers completely.</b>`
    : "The area becomes the whole districts the drawing mostly covers, so every cell belongs to one district.";
  $("free-banner").hidden = !free;
  $("map-region").classList.toggle("free", free);
  $<HTMLInputElement>("min-share").disabled = free || running();
}
document.querySelector(".mode-pick")!.addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest<HTMLElement>("[data-mode]");
  if (b) setMode(b.dataset.mode as "snap" | "free");
});
document.querySelector(".mode-pick .seg")!.addEventListener("keydown", (e) => {
  const k = (e as KeyboardEvent).key;
  if (k !== "ArrowLeft" && k !== "ArrowRight") return;
  setMode(S.mode === "snap" ? "free" : "snap");
  (document.querySelector(`.mode-pick [data-mode="${S.mode}"]`) as HTMLElement).focus();
});
$<HTMLInputElement>("min-share").addEventListener("change", (e) => {
  const t = e.target as HTMLInputElement;
  const v = Number(t.value.replace(",", "."));
  const ok = t.value.trim() !== "" && v > 0 && v <= 1;
  t.setAttribute("aria-invalid", String(!ok));
  document.getElementById("min-share-err")?.remove();
  if (!ok) { t.insertAdjacentHTML("afterend", `<p class="field-error" id="min-share-err"><span class="ic">${icon("alert")}</span>Use a number more than 0 and at most 1, e.g. 0.5</p>`); return; }
  S.minShare = v; dropFinishedJob(); schedulePlan();
});

async function loadPlan(): Promise<void> {
  const a = areaIn();
  if (!a || !S.validation?.ok) return;
  if (S.mode === "snap" && !S.snap?.ok) { S.plan = null; renderSources(); renderManifest(); return; }
  const seq = ++pSeq;
  try {
    const plan = await api.plan(a, S.overrides, areaMode(), S.levelOverride);
    if (seq !== pSeq) return;
    S.plan = plan; S.planError = "";
    for (const [src, id] of Object.entries(S.pinned)) if (!plan[src]?.snapshots.some((s) => s.id === id)) delete S.pinned[src];
  } catch (e) {
    if (seq !== pSeq) return;
    S.plan = null; S.planError = (e as Error).message;
  }
  renderSources(); renderManifest();
}

// ── header ───────────────────────────────────────────────────────────
function renderHeader(): void {
  const c = S.config;
  $("cache-root").textContent = c?.cache_root ?? "unknown";
  const k = $("key-status");
  k.innerHTML = c?.llm_key_present ? `<span class="ic">${icon("key")}</span>LLM key set`
    : `<span class="ic">${icon("nokey")}</span>No LLM key: defaults will be used`;
}

// ── area section ─────────────────────────────────────────────────────
function renderReadout(): void {
  const v = S.validation;
  const ro = $("readout");
  ro.hidden = !(v?.ok || (v && v.area_id));
  if (v?.bbox) {
    const sn = S.mode === "snap" ? S.snap : null;
    const snapped = sn?.ok ? `${fmtInt(sn.km2 ?? 0)} km² · ${sn.districts.filter((d) => d.included).length} whole districts`
      : S.mode === "snap" ? (S.snapping ? "snapping…" : sn?.error?.code === "no_district_qualifies" ? "empty: no district qualifies (see below)"
        : sn?.error ? "couldn't snap (see below)" : "not snapped yet") : "same as drawn (free polygon)";
    ro.innerHTML = `<div><dt>Bounding box</dt><dd class="mono">${v.bbox.map((x) => x.toFixed(2)).join(", ")}</dd></div>
      <div><dt>Drawn</dt><dd>${fmtInt(v.km2 ?? 0)} km²</dd></div>
      <div><dt>${S.mode === "snap" ? "Snapped" : "Fetched"}</dt><dd>${snapped}</dd></div>
      <div><dt>area_id</dt><dd class="mono">${esc(sn?.ok ? sn.area_id : v.area_id ?? "")}</dd></div>
      ${sn?.ok ? `<div><dt>Drawing</dt><dd class="mono">${esc(sn.drawn_area_id)}</dd></div>` : ""}`;
  }
  ro.style.opacity = S.validating ? "0.55" : "";
  const msgs: string[] = [];
  if (S.validating) msgs.push(`<p class="hint" role="status">Checking the area…</p>`);
  for (const e of (S.mode === "snap" && S.snap?.ok ? S.snap.size_errors : [])) {
    msgs.push(`<div class="note block" role="alert"><span class="ic">${icon("alert")}</span><b>The snapped area is too large</b><p>${esc(e.message)} Remove districts or draw a smaller area.</p></div>`);
  }
  for (const e of v?.errors ?? []) {
    msgs.push(`<div class="note block" role="alert"><span class="ic">${icon("alert")}</span><b>${e.code === "too_large" ? "Too large to fetch" : "Can't use this area"}</b><p>${esc(e.message)}</p></div>`);
  }
  for (const w of v?.warnings ?? []) {
    const t = { large: "Large area", outside_country: "Partly outside the country", border_unknown: "Border not checked" }[w.code] ?? "Note";
    msgs.push(`<div class="note warn"><span class="ic">${icon("alert")}</span><b>${t}</b><p>${esc(w.message)}</p></div>`);
  }
  if (S.replaced) msgs.unshift(`<div class="note info"><span class="ic">${icon("info")}</span><b>Area replaced</b><p>There is only ever one area: the new shape replaced the previous one.</p><div class="note-actions"><button class="btn btn-sm" type="button" id="undo-replace">Undo</button><button class="btn btn-sm btn-quiet" type="button" id="keep-replace">Keep the new one</button></div></div>`);
  $("area-msgs").innerHTML = msgs.join("");
  const ue = $("upload-error");
  ue.hidden = !S.uploadError;
  if (S.uploadError) ue.innerHTML = `<b>${esc(S.uploadError.file)} wasn't used</b>${esc(S.uploadError.message)} The previous area is kept.`;
  const km = S.mode === "snap" && S.snap?.ok ? S.snap.km2 ?? 0 : v?.km2 ?? 0;
  $("area-sum").textContent = v?.ok ? `${S.name || "unnamed"} · ${S.iso3} · ${S.mode === "snap" ? "whole districts" : "free"} · ${fmtInt(km)} km²` : "";
}

// country combobox
const cInput = $<HTMLInputElement>("country-input");
const cList = $<HTMLUListElement>("country-list");
let cActive = -1, cMatches: Country[] = [];
function countryText(iso3: string): string {
  const c = S.countries.find((x) => x.iso3 === iso3);
  return c ? `${c.name} (${c.iso3})` : "";
}
function openCountries(): void {
  const q = cInput.value.trim().toLowerCase().replace(/\s*\([a-z]{3}\)$/, "");
  cMatches = S.countries.filter((c) => !q || c.name.toLowerCase().includes(q) || c.iso3.toLowerCase() === q).slice(0, 60);
  if (q.length === 3) cMatches.sort((a, b) => Number(b.iso3.toLowerCase() === q) - Number(a.iso3.toLowerCase() === q));
  cActive = cMatches.length ? 0 : -1;
  cList.innerHTML = cMatches.length
    ? cMatches.map((c, i) => `<li role="option" id="co-${c.iso3}" aria-selected="${i === cActive}" data-iso3="${c.iso3}"><span>${esc(c.name)}</span><span class="mono">${c.iso3}</span></li>`).join("")
    : `<li class="combo-empty" role="option" aria-disabled="true">No country matches “${esc(cInput.value)}”. Try the name or a 3-letter code.</li>`;
  cList.hidden = false;
  cInput.setAttribute("aria-expanded", "true");
  cInput.setAttribute("aria-activedescendant", cMatches[cActive] ? `co-${cMatches[cActive].iso3}` : "");
}
function closeCountries(): void { cList.hidden = true; cInput.setAttribute("aria-expanded", "false"); }
function pickCountry(iso3: string, fit = true): void {
  const changed = iso3 !== S.iso3;
  S.iso3 = iso3;
  cInput.value = countryText(iso3);
  closeCountries();
  map.setCountry(iso3, fit && !S.geom);
  if (changed) { S.profileFor = ""; onAreaChanged(); }
}
cInput.addEventListener("input", openCountries);
cInput.addEventListener("focus", () => { cInput.select(); });
cInput.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (cList.hidden) openCountries();
    if (!cMatches.length) return;
    cActive = (cActive + (e.key === "ArrowDown" ? 1 : cMatches.length - 1)) % cMatches.length;
    cList.querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", String(i === cActive)));
    cInput.setAttribute("aria-activedescendant", `co-${cMatches[cActive].iso3}`);
    cList.children[cActive]?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter" && !cList.hidden && cMatches[cActive]) {
    e.preventDefault(); S.countryAuto = false; pickCountry(cMatches[cActive].iso3); renderDetect();
  } else if (e.key === "Escape") {
    closeCountries(); cInput.value = countryText(S.iso3);
  }
});
cInput.addEventListener("blur", () => setTimeout(() => {
  if (!cList.hidden) closeCountries();
  if (cInput.value !== countryText(S.iso3)) {
    const q = cInput.value.trim().toLowerCase();
    const m = S.countries.find((c) => c.iso3.toLowerCase() === q || c.name.toLowerCase() === q);
    if (m) pickCountry(m.iso3); else cInput.value = countryText(S.iso3);
  }
}, 120));
cList.addEventListener("mousedown", (e) => {
  const li = (e.target as HTMLElement).closest<HTMLElement>("li[data-iso3]");
  if (li) { e.preventDefault(); S.countryAuto = false; pickCountry(li.dataset.iso3!); renderDetect(); }
});

$("area-msgs").addEventListener("click", async (e) => {
  const t = e.target as HTMLElement;
  if (t.closest("#undo-replace") && S.replaced) {
    const prev = S.replaced; S.replaced = null;
    await map.setArea(prev, false); S.geom = prev; map.setTool("edit"); announce("Previous area restored."); onAreaChanged();
  } else if (t.closest("#keep-replace")) { S.replaced = null; renderReadout(); }
});
$<HTMLInputElement>("area-name").addEventListener("input", (e) => { S.name = (e.target as HTMLInputElement).value; S.nameAuto = !S.name.trim(); onAreaChanged(); });

// upload + drop
async function useFile(file: File): Promise<void> {
  if (running()) { announce("Inputs are locked while fetching."); return; }
  const text = await file.text();
  let geom: Geo | null = null;
  try {
    const v = await api.validate({ name: S.name || "upload", iso3: S.iso3 || "ISR", geojson: text });
    // only unreadable files are rejected; a readable area that is too large loads and shows its block
    const errs = v.errors.filter((e) => e.code === "invalid" && !/^Name is required|^Choose a country/.test(e.message));
    if (errs.length) { S.uploadError = { file: file.name, message: errs.map((e) => e.message).join(" ") }; renderReadout(); announce(`${file.name} wasn't used. ${errs[0].message}`); return; }
    let g = JSON.parse(text);
    if (g.type === "FeatureCollection") g = g.features[0];
    if (g.type === "Feature") g = g.geometry;
    geom = g as Geo;
  } catch (e) {
    S.uploadError = { file: file.name, message: (e as Error).message }; renderReadout(); return;
  }
  S.uploadError = null;
  S.geom = geom;
  clearChoices();
  renderLayersPanel(); // the legend is part of the fit's padding, so it must be laid out first
  await map.setArea(geom, true);
  autoFill();
  if (S.nameAuto && !S.iso3) { S.name = slug(file.name.replace(/\.(geo)?json$/i, "")); $<HTMLInputElement>("area-name").value = S.name; }
  map.setTool("edit");
  announce(`Area from ${file.name} loaded.`);
  onAreaChanged();
}
$("upload-btn").addEventListener("click", () => $<HTMLInputElement>("upload-input").click());
$<HTMLInputElement>("upload-input").addEventListener("change", (e) => {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) useFile(f);
  (e.target as HTMLInputElement).value = "";
});
const region = $("map-region");
let dragDepth = 0;
region.addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { dragDepth++; $("drop-overlay").hidden = false; } });
region.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("drop-overlay").hidden = true; } });
region.addEventListener("dragover", (e) => e.preventDefault());
region.addEventListener("drop", (e) => {
  e.preventDefault(); dragDepth = 0; $("drop-overlay").hidden = true;
  const f = e.dataTransfer?.files?.[0];
  if (f) useFile(f);
});

// ── draw tools, hint ─────────────────────────────────────────────────
let currentTool: Tool = null;
function renderTools(): void {
  const tools: [Tool, string, string][] = [["rect", "rect", "Draw rectangle"], ["poly", "poly", "Draw polygon"], ["edit", "edit", "Edit vertices"]];
  const t = (map as unknown as { tool: Tool }).tool;
  currentTool = t;
  const lock = running();
  $("draw-tools").innerHTML = tools.map(([id, ic, lbl]) =>
    `<button class="icon-btn" type="button" data-tool="${id}" aria-pressed="${t === id}" aria-label="${lbl}" title="${lbl}" ${lock || (id === "edit" && !S.geom) ? "disabled" : ""}><span class="ic">${icon(ic)}</span></button>`).join("")
    + `<div class="sep"></div><button class="icon-btn" type="button" data-tool="delete" aria-label="Delete area" title="Delete area" ${lock || !S.geom ? "disabled" : ""}><span class="ic">${icon("trash")}</span></button>`;
}
$("draw-tools").addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest<HTMLButtonElement>("button[data-tool]");
  if (!b) return;
  const t = b.dataset.tool!;
  if (t === "delete") { map.clearArea(); announce("Area deleted."); return; }
  map.setTool(currentTool === t ? null : (t as Tool));
  if (t !== "edit") $("map").focus();
  announce(t === "rect" ? "Rectangle tool. Drag on the map, or press Enter twice to set two corners at the crosshair."
    : t === "poly" ? "Polygon tool. Click to add points, or press Enter at the crosshair; F finishes." : "Edit tool. Drag a vertex, or press ] to pick one and Alt+arrows to move it.");
});
$("draw-tools").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
  const bs = [...$("draw-tools").querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
  const i = bs.indexOf(document.activeElement as HTMLButtonElement);
  bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length]?.focus();
  e.preventDefault();
});
$("map-zoom").innerHTML = `<button class="icon-btn" type="button" data-z="in" aria-label="Zoom in"><span class="ic">${icon("plus")}</span></button><button class="icon-btn" type="button" data-z="out" aria-label="Zoom out"><span class="ic">${icon("minus")}</span></button><button class="icon-btn" type="button" data-z="fit" aria-label="Fit the area"><span class="ic">${icon("fit")}</span></button>`;
$("map-zoom").addEventListener("click", (e) => {
  const z = (e.target as HTMLElement).closest<HTMLElement>("[data-z]")?.dataset.z;
  if (z === "in") map.zoomBy(1); else if (z === "out") map.zoomBy(-1); else if (z === "fit") map.fitArea();
});

function renderHint(): void {
  const t = currentTool;
  const focused = document.activeElement === $("map");
  $("crosshair").hidden = !(focused && (t === "rect" || t === "poly"));
  const h = $("map-hint");
  h.hidden = !!S.geom || t !== null;
  h.innerHTML = `<b>Draw a rectangle or polygon</b><span class="hint">Pick a tool top-left, or drop a GeoJSON file here. Keyboard: Tab to the tools, then use Enter on the map to place points.</span>`;
  const v = S.validation;
  $("map-summary").textContent = S.geom && v?.km2 ? `Area ${S.name || "unnamed"}, ${fmtInt(v.km2)} square kilometres.` : "";
}

// ── profile ──────────────────────────────────────────────────────────
function renderProfile(): void {
  const body = $("profile-body");
  const p = S.profile;
  if (!S.validation?.ok) { body.innerHTML = `<p class="hint">Appears when a country and an area are set.</p>`; $("profile-sum").textContent = ""; return; }
  if (S.profileLoading && !p) { body.innerHTML = `<div class="skeleton" style="width:70%"></div><div class="skeleton" style="width:90%"></div><div class="skeleton" style="width:55%"></div>`; return; }
  if (S.profileError && !p) { body.innerHTML = `<div class="note block"><span class="ic">${icon("alert")}</span><b>Couldn't load the profile</b><p>${esc(S.profileError)}</p></div>`; return; }
  if (!p) return;
  const badge = p.status === "llm" ? `<span class="stamp carbon">Chosen by the LLM</span>`
    : p.status === "default_no_key" ? `<span class="stamp">Default · no LLM key</span>` : `<span class="stamp warn">Default · LLM call failed</span>`;
  const key = !!S.config?.llm_key_present;
  const tags = p.facility_tags.map(([k, v]) => `${k}=${v}`).join(", ");
  body.innerHTML = `<div class="profile-top">${badge}</div>
    <dl class="kv"><dt>Facilities</dt><dd>${esc(tags)}</dd></dl>
    ${p.source === "llm" && p.rationale ? `<p class="quote">“${esc(p.rationale)}”</p>` : ""}
    ${p.status === "default_llm_failed" && p.note ? `<p class="hint" style="margin-top:6px">${esc(p.note)}</p>` : ""}
    <p class="hint" style="margin-top:6px">The LLM only decides which facilities count. The district level is chosen by a rule (see 3 · Sources, Districts). Pre-fills the facilities options below.</p>
    <div class="row-actions"><button class="btn btn-sm" id="ask-llm" type="button" ${key && !S.profileLoading && !running() ? "" : "disabled"} ${key ? "" : 'aria-describedby="nokey"'}>
      <span class="ic">${icon("retry")}</span>${S.profileLoading ? "Asking…" : "Ask the LLM again"}</button>
      ${key ? "" : `<span class="hint" id="nokey">Needs ANTHROPIC_API_KEY in .env (restart after adding it)</span>`}</div>
    ${S.profileError ? `<p class="field-error"><span class="ic">${icon("alert")}</span>${esc(S.profileError)}</p>` : ""}`;
  $("profile-sum").textContent = p.source === "llm" ? "LLM" : "Default";
  document.getElementById("ask-llm")?.addEventListener("click", async () => { await loadProfile(true); await refreshTarget(); });
}

// ── sources ──────────────────────────────────────────────────────────
function effective(src: string, field: string): unknown {
  const o = S.overrides[src];
  if (o && field in o) return o[field];
  const fromProfile = S.profile?.fetcher_options?.[src]?.[field];
  if (fromProfile !== undefined) return fromProfile;
  return S.specs.find((s) => s.source === src)?.options[field]?.default;
}
function setOpt(src: string, field: string, value: unknown): void {
  if (src === "boundaries") clearChoices(); // another level or provider: other district ids
  (S.overrides[src] ??= {})[field] = value;
  schedulePlan();
}

function rowState(src: string): { word: string; cls: string; sub: string } {
  const p = S.plan?.[src];
  if (!S.included.has(src)) return { word: "Excluded", cls: "muted", sub: "not fetched" };
  if (p && Object.keys(p.errors).length) return { word: "Fix options", cls: "bad", sub: Object.values(p.errors)[0] };
  if (S.pinned[src]) return { word: "Pinned", cls: "carbon", sub: `pinned ${S.pinned[src]}` };
  if (src === "boundaries" && S.levels?.status === "running") return { word: "", cls: "muted", sub: `counting districts per level${S.levels.probing ? ` (${S.levels.probing.level})` : ""}…` };
  if (src === "boundaries" && S.levels?.status === "failed") return { word: "Failed", cls: "bad", sub: "couldn't choose a district level" };
  if (!p) return { word: "", cls: "muted", sub: !S.validation?.ok ? "set the area first"
    : S.mode === "snap" && S.snap && !S.snap.ok ? "waits for a usable area (see 1 · Area)" : "checking the cache…" };
  if (S.refresh) return { word: "Download", cls: "", sub: "Refresh is on" };
  if (src === "boundaries" && usedLevel()) {
    const u = usedLevel()!, cnt = S.levels?.choice?.counts.find((c) => c.provider === u.provider && c.level === u.level);
    const lvl = `${levelName(u)}${cnt ? ` · ${cnt.usable} usable` : ""} · ${S.levelOverride ? "your choice" : "chosen by the rule"}`;
    if (p.decision === "reuse") return { word: "Reuse", cls: "ok", sub: `${lvl} · ${p.snapshot_id}` };
    return { word: "Download", cls: "", sub: lvl };
  }
  if (p.decision === "reuse") {
    const s = p.snapshots.find((x) => x.id === p.snapshot_id);
    return { word: "Reuse", cls: "ok", sub: `${p.snapshot_id} · ${s ? ageText(s.age_days) : ""}` };
  }
  const why = { no_snapshot: "no snapshot for this area", params_changed: "options changed since the last snapshot", expired: `older than ${p.ttl_days} days` }[p.reason ?? "no_snapshot"];
  return { word: "Download", cls: "", sub: why };
}

function optionsHtml(src: string): string {
  if (src === "boundaries") return `<div class="lvl" id="lvl-panel">${levelPanel()}</div>${optionsFields(src)}`;
  return optionsFields(src);
}

function optionsFields(src: string): string {
  const spec = S.specs.find((s) => s.source === src)!;
  const err = S.plan?.[src]?.errors ?? {};
  const fe = (f: string) => (err[f] ? `<p class="field-error" id="err-${src}-${f}"><span class="ic">${icon("alert")}</span>${esc(err[f])}</p>` : "");
  const inv = (f: string) => (err[f] ? `aria-invalid="true" aria-describedby="err-${src}-${f}"` : "");
  const parts: string[] = [];
  if (PROFILE_FED.has(src) && S.overrides[src] && Object.keys(S.overrides[src]).length) {
    parts.push(`<p class="edited"><span>Edited: differs from the profile.</span><button class="link" type="button" data-reset="${src}">Reset to profile</button></p>`);
  }
  const fields: string[] = [];
  for (const [f, o] of Object.entries(spec.options)) {
    const id = `opt-${src}-${f}`;
    const v = effective(src, f);
    const capName = { year: "Year", resolution: "Resolution", provider: "Provider", levels: "Levels, coarse to fine (last = districts)", tags: "Tags (any match counts)", highway_types: "Highway types", max_feeds: "Max feeds" }[f] ?? f;
    if (o.type === "int") {
      fields.push(`<label class="field"><span class="cap">${capName}</span><input class="input" id="${id}" inputmode="numeric" data-src="${src}" data-f="${f}" data-kind="int" value="${esc(v)}" ${inv(f)} /><span class="hint">${o.min}–${o.max}</span>${fe(f)}</label>`);
    } else if (o.type === "enum") {
      const names: Record<string, string> = { geoboundaries: "geoBoundaries", osm: "OpenStreetMap" };
      fields.push(`<fieldset class="field" style="border:0;padding:0;margin:0"><legend class="cap">${capName}</legend><div class="seg">${o.values!.map((x) =>
        `<button type="button" aria-pressed="${v === x}" data-src="${src}" data-f="${f}" data-enum="${x}">${names[x] ?? x}</button>`).join("")}</div>${fe(f)}</fieldset>`);
    } else if (o.type === "levels") {
      const val = Array.isArray(v) ? (v as string[]).join(", ") : String(v ?? "");
      fields.push(`<label class="field" style="grid-column: 1 / -1"><span class="cap">${capName}</span><input class="input" id="${id}" data-src="${src}" data-f="${f}" data-kind="list" value="${esc(val)}" ${inv(f)} />
        <span class="hint">${effective(src, "provider") === "osm" ? "OpenStreetMap admin_level numbers 2–11, e.g. 4, 8" : "ADM1–ADM5, e.g. ADM1, ADM2"}</span>${fe(f)}</label>`);
    } else if (o.type === "tags") {
      const tags = (v as [string, string][]) ?? [];
      fields.push(`<div class="field" style="grid-column: 1 / -1"><span class="cap">${capName}</span><div class="chips">${tags.map(([k, x], i) =>
        `<span class="chip">${esc(k)} = ${esc(x)}<button type="button" data-src="${src}" data-tag-rm="${i}" aria-label="Remove ${esc(k)} = ${esc(x)}"><span class="ic">${icon("x")}</span></button></span>`).join("")}</div>
        <div class="tag-add" style="margin-top:8px"><label class="field"><span class="cap">Key</span><select class="select" id="tagk-${src}">${o.keys!.map((k) => `<option>${k}</option>`).join("")}</select></label>
        <label class="field"><span class="cap">Value</span><input class="input" id="tagv-${src}" placeholder="e.g. hospital, or *" /></label>
        <button class="btn" type="button" data-tag-add="${src}"><span class="ic">${icon("plus")}</span>Add</button></div>${fe(f)}</div>`);
    } else if (o.type === "multi") {
      const sel = new Set((v as string[]) ?? []);
      fields.push(`<fieldset class="field" style="grid-column: 1 / -1;border:0;padding:0;margin:0"><legend class="cap">${capName} · ${sel.size} of ${o.values!.length}</legend><div class="checks">${o.values!.map((x) =>
        `<label><input type="checkbox" class="check" data-src="${src}" data-multi="${f}" value="${x}" ${sel.has(x) ? "checked" : ""}/>${x.replace(/_/g, " ")}</label>`).join("")}</div>${fe(f)}</fieldset>`);
    }
  }
  parts.push(`<div class="opts-grid">${fields.join("")}</div>`);
  const snaps = S.plan?.[src]?.snapshots ?? [];
  parts.push(`<label class="field"><span class="cap">Pin a snapshot (use it instead of fetching)</span>
    <select class="select" data-pin="${src}" ${snaps.length ? "" : "disabled"}><option value="">Don't pin: follow the plan</option>${snaps.map((s) =>
      `<option value="${s.id}" ${S.pinned[src] === s.id ? "selected" : ""}>${s.id} · ${ageText(s.age_days)}${s.params_match ? "" : " · other options"}</option>`).join("")}</select>
    <span class="hint">${snaps.length ? `${snaps.length} snapshot${snaps.length > 1 ? "s" : ""} in the cache · fresh for ${S.plan?.[src]?.ttl_days} days` : "No snapshots of this source for this area yet"}</span></label>`);
  if (err.options) parts.push(fe("options"));
  return parts.join("");
}

function renderSources(): void {
  const body = $("sources-body");
  if (!S.specs.length) { body.innerHTML = `<p class="hint">Loading sources…</p>`; return; }
  const lock = running();
  body.innerHTML = S.specs.map((s, i) => {
    const st = rowState(s.source);
    const open = S.open.has(s.source);
    return `<div class="src ${S.included.has(s.source) ? "" : "excluded"}">
      <div class="src-line"><span class="src-no">${two(i)}</span>
        <input type="checkbox" class="check" data-include="${s.source}" ${S.included.has(s.source) ? "checked" : ""} aria-label="Include ${esc(s.label)}" ${lock ? "disabled" : ""}/>
        <span><span class="src-name">${esc(s.label)}</span><span class="src-sub">${sub(st.sub)}</span></span>
        ${st.word ? `<span class="stamp ${st.cls}">${st.word}</span>` : "<span></span>"}
        <button class="icon-btn" type="button" data-toggle="${s.source}" aria-expanded="${open}" aria-controls="opts-${s.source}" aria-label="${esc(s.label)} options" ${lock ? "disabled" : ""}><span class="ic" style="transform:rotate(${open ? 180 : 0}deg)">${icon("chevron")}</span></button></div>
      <div class="src-opts" id="opts-${s.source}" ${open && !lock ? "" : "hidden"}>${open ? optionsHtml(s.source) : ""}</div></div>`;
  }).join("") + (lock ? `<p class="hint" style="margin-top:8px">Inputs are locked while fetching.</p>` : "");
  const n = S.included.size;
  $("sources-sum").textContent = `${n} of ${S.specs.length} included`;
}

const srcBody = $("sources-body");
srcBody.addEventListener("click", (e) => {
  const t = e.target as HTMLElement;
  if (t.closest("#lvl-reset")) { setLevel(null); return; }
  if (t.closest("#lvl-retry")) { schedulePlan(); return; }
  const tog = t.closest<HTMLElement>("[data-toggle]");
  if (tog) { const s = tog.dataset.toggle!; S.open.has(s) ? S.open.delete(s) : S.open.add(s); renderSources(); (document.querySelector(`[data-toggle="${s}"]`) as HTMLElement)?.focus(); return; }
  const en = t.closest<HTMLElement>("[data-enum]");
  if (en) { setOpt(en.dataset.src!, en.dataset.f!, en.dataset.enum); renderSources(); return; }
  const rm = t.closest<HTMLElement>("[data-tag-rm]");
  if (rm) {
    const src = rm.dataset.src!;
    const tags = [...((effective(src, "tags") as [string, string][]) ?? [])];
    tags.splice(Number(rm.dataset.tagRm), 1);
    setOpt(src, "tags", tags); renderSources(); return;
  }
  const add = t.closest<HTMLElement>("[data-tag-add]");
  if (add) {
    const src = add.dataset.tagAdd!;
    const k = (document.getElementById(`tagk-${src}`) as HTMLSelectElement).value;
    const v = (document.getElementById(`tagv-${src}`) as HTMLInputElement).value.trim();
    if (!v) { (document.getElementById(`tagv-${src}`) as HTMLInputElement).focus(); return; }
    setOpt(src, "tags", [...((effective(src, "tags") as [string, string][]) ?? []), [k, v]]); renderSources();
    (document.getElementById(`tagv-${src}`) as HTMLInputElement)?.focus();
    return;
  }
  const reset = t.closest<HTMLElement>("[data-reset]");
  if (reset) { delete S.overrides[reset.dataset.reset!]; schedulePlan(); renderSources(); announce("Options reset to the profile."); }
});
srcBody.addEventListener("change", (e) => {
  const t = e.target as HTMLInputElement;
  if (t.name === "lvl") { const [provider, level] = t.value.split("|"); setLevel({ provider, level }); return; }
  if (t.dataset.include) { t.checked ? S.included.add(t.dataset.include) : S.included.delete(t.dataset.include); persist(); renderSources(); renderManifest(); return; }
  if (t.dataset.multi) {
    const src = t.dataset.src!;
    const sel = [...srcBody.querySelectorAll<HTMLInputElement>(`input[data-multi][data-src="${src}"]:checked`)].map((x) => x.value);
    setOpt(src, t.dataset.multi, sel); return;
  }
  const pin = (e.target as HTMLElement).closest<HTMLSelectElement>("select[data-pin]");
  if (pin) { pin.value ? (S.pinned[pin.dataset.pin!] = pin.value) : delete S.pinned[pin.dataset.pin!]; persist(); renderSources(); renderManifest(); }
});
srcBody.addEventListener("input", (e) => {
  const t = e.target as HTMLInputElement;
  if (!t.dataset.f || !t.dataset.kind) return;
  const v = t.dataset.kind === "list" ? t.value.split(",").map((x) => x.trim()).filter(Boolean) : t.value.trim();
  setOpt(t.dataset.src!, t.dataset.f, v);
});
// re-render source rows after the plan returns, without stealing focus from a field being typed in
const _renderSources = renderSources;
function renderSourcesKeepFocus(): void {
  const a = document.activeElement as HTMLElement | null;
  const id = a?.id, pos = (a as HTMLInputElement | null)?.selectionStart ?? null;
  _renderSources();
  if (id) { const n = document.getElementById(id) as HTMLInputElement | null; if (n) { n.focus(); if (pos !== null && "setSelectionRange" in n) try { n.setSelectionRange(pos, pos); } catch { /* not a text field */ } } }
}

// ── manifest: plan, progress, totals, fetch ──────────────────────────
function planSentence(): string {
  const inc = S.specs.filter((s) => S.included.has(s.source)).map((s) => s.source);
  if (!inc.length) return "No sources included.";
  if (!S.plan) return !S.validation?.ok ? "Set a name, a country and an area to see the plan."
    : S.mode === "snap" && S.snap && !S.snap.ok ? "No plan yet: the whole-district area is empty." : "Checking the cache…";
  const pinned = inc.filter((s) => S.pinned[s]).length;
  const rest = inc.filter((s) => !S.pinned[s]);
  if (S.refresh) return `Refresh is on: ${rest.length} will download${pinned ? `, ${pinned} pinned` : ""}.`;
  const reuse = rest.filter((s) => S.plan![s]?.decision === "reuse").length;
  const dl = rest.length - reuse;
  if (!dl && !pinned) return `All ${reuse} sources reuse the cache: instant.`;
  const bits = [reuse ? `${reuse} reuse the cache` : "", dl ? `${dl} will download` : "", pinned ? `${pinned} pinned` : ""].filter(Boolean);
  return `${inc.length} line${inc.length > 1 ? "s" : ""} · ${bits.join(" · ")}`;
}

function fetchBlockers(): string[] {
  const why: string[] = [];
  if (running()) return ["Fetching… inputs are locked until it finishes."];
  if (!S.name.trim()) why.push("name");
  if (!S.iso3) why.push("country");
  if (!S.geom) why.push("area");
  if (why.length) return [`Missing: ${why.join(", ")}.`];
  if (S.validation && !S.validation.ok) return ["Fix the area first (see 1 · Area)."];
  if (S.levels?.status === "running") return ["Counting districts per level…"];
  if (S.levels?.status === "failed") return ["No district level could be chosen (see the Districts source)."];
  if (S.mode === "snap") {
    if (S.snapping && !S.snap) return ["Snapping to whole districts…"];
    if (S.snapError) return ["The district choices can't be used (see 1 · Area)."];
    if (S.snap?.error?.code === "no_district_qualifies") return [`No district is at least ${pct(S.minShare)} inside the drawing: add districts, use a finer level, or draw a larger area.`];
    if (S.snap?.error) return ["Couldn't get the districts for the drawing (see 1 · Area)."];
    if (S.snap?.size_errors.length) return ["The snapped area is too large (see 1 · Area)."];
  }
  if (!S.included.size) return ["Include at least one source."];
  const bad = S.specs.filter((s) => S.included.has(s.source) && Object.keys(S.plan?.[s.source]?.errors ?? {}).length);
  if (bad.length) return [`${bad.length} source option${bad.length > 1 ? "s need" : " needs"} fixing: ${bad.map((s) => s.label.toLowerCase()).join(", ")}.`];
  if (!S.plan) return ["Checking the cache…"];
  return [];
}

// the backend's exception, said plainly first; the raw text stays below for whoever debugs it
function plainError(raw: string): string {
  if (/429|Too Many Requests|rate/i.test(raw)) return "The server is busy (rate limit). Wait a minute, then retry.";
  if (/timed? ?out|Timeout/i.test(raw)) return "The server took too long to answer. Retry, or try a smaller area.";
  if (/ConnectionError|ProxyError|Max retries|could not be reached|NameResolution|RemoteDisconnected|Connection (aborted|refused)/i.test(raw))
    return "Couldn't reach the data server: no network, or the connection was refused. Other sources are not affected.";
  if (/^HTTPError|status code|\b5\d\d\b/.test(raw)) return "The data server returned an error. Retry later.";
  return "This source failed. Other sources are not affected.";
}

function lineFor(row: JobRow | null, src: string, i: number): string {
  const name = esc(label(src));
  if (!row) {
    const st = rowState(src);
    const word = st.word || "Pending";
    return `<li class="line ${S.included.has(src) ? "" : "excluded"}"><span class="line-no">${two(i)}</span><span><span class="line-name">${name}</span><span class="line-sub">${sub(st.sub)}</span></span>
      <span class="line-right"><span class="stamp ${st.word ? st.cls : "muted"}">${word}</span></span></li>`;
  }
  const el = row.elapsed_s ?? 0;
  const map: Record<JobRow["status"], [string, string, string]> = {
    queued: ["Queued", "muted", "waiting for its turn"],
    running: ["Running", "carbon", `running · ${Math.round(el)}\u00a0s`],
    reused: ["Reused", "ok", `from cache · ${row.result?.snapshot_id ?? ""}`],
    done: ["Downloaded", "ok", `${row.result?.snapshot_id ?? ""} · ${Math.round(el)}\u00a0s`],
    failed: [row.attempts > 1 ? `Failed ×${row.attempts}` : "Failed", "bad", row.attempts > 1 ? `failed again (${row.attempts} tries)` : ""],
  };
  const [word, cls, subText] = map[row.status];
  const longest = Math.max(1, ...(S.job?.sources ?? []).map((r) => r.elapsed_s ?? 0));
  const bar = row.status === "running" || row.status === "done" ? `<span class="dur" aria-hidden="true"><i style="width:${Math.max(4, (el / longest) * 100)}%"></i></span>` : "";
  const glyph = row.status === "running" ? icon("clock") : row.status === "failed" ? icon("alert") : row.status === "queued" ? icon("queued") : icon("check");
  const retry = row.status === "failed" && !S.job?.running ? `<button class="btn btn-sm" type="button" data-retry="${src}"><span class="ic">${icon("retry")}</span>Retry</button>` : "";
  return `<li class="line"><span class="line-no">${two(i)}</span><span><span class="line-name">${name}</span>${subText ? `<span class="line-sub">${sub(subText)}</span>` : ""}
    ${row.error ? `<span class="line-err">${esc(plainError(row.error))}</span><details class="line-raw"><summary>Error details</summary><code>${esc(row.error)}</code></details>` : ""}${bar}</span>
    <span class="line-right"><span class="stamp ${cls}" data-stamp="${src}:${row.status}:${row.attempts}"><span class="ic">${glyph}</span>${word}</span>${retry}</span></li>`;
}

function areaLine(): string {
  const a = S.job?.area;
  let word: string, cls: string, text: string, err = "", retryBtn = "", glyph = "";
  const snapMode = (a?.mode ?? S.mode) === "snap";
  if (a) {
    const n = a.included?.length ?? 0;
    const lv = a.level ? ` ${a.level.provider === "osm" ? `OSM ${a.level.level}` : a.level.level}` : "";
    const done = snapMode ? `snapped to ${n}${lv} district${n === 1 ? "" : "s"} · ${a.area_id} · ${fmtInt(a.km2 ?? 0)}\u00a0km²` : `the drawing as is · ${a.area_id}`;
    [word, cls, text, glyph] = {
      queued: ["Queued", "muted", "first: resolve the area", icon("queued")],
      running: ["Running", "carbon", snapMode ? "snapping to whole districts…" : "recording the free polygon…", icon("clock")],
      done: [snapMode ? "Snapped" : "Free", "ok", done, icon("check")],
      failed: ["Failed", "bad", "", icon("alert")],
    }[a.status] as [string, string, string, string];
    if (a.status === "failed" && a.error) {
      err = `<span class="line-err">${esc(plainError(a.error))} Nothing else was fetched.</span><details class="line-raw"><summary>Error details</summary><code>${esc(a.error)}</code></details>`;
      if (!S.job?.running) retryBtn = `<button class="btn btn-sm" type="button" data-retry="area"><span class="ic">${icon("retry")}</span>Retry</button>`;
    }
  } else if (!snapMode) {
    [word, cls, text] = ["Free", "carbon", S.validation?.ok ? `the drawing as is · ${fmtInt(S.validation.km2 ?? 0)}\u00a0km²` : "set the area first"];
  } else if (S.snap?.ok) {
    const n = S.snap.districts.filter((d) => d.included).length;
    [word, cls, text] = ["Snap", "ok", `${n} whole district${n === 1 ? "" : "s"} · ${fmtInt(S.snap.km2 ?? 0)}\u00a0km² (drawn ${fmtInt(S.snap.drawn_km2)}\u00a0km²)`];
  } else if (S.snap?.error) {
    [word, cls, text] = S.snap.error.code === "no_district_qualifies" ? ["No district", "bad", `none is ${pct(S.minShare)} inside the drawing`] : ["Failed", "bad", "couldn't get the districts"];
  } else {
    [word, cls, text] = ["Pending", "muted", S.snapping ? "snapping to whole districts…" : "set the area first"];
  }
  return `<li class="line"><span class="line-no">00</span><span><span class="line-name">Area</span>${text ? `<span class="line-sub">${sub(text)}</span>` : ""}${err}</span>
    <span class="line-right"><span class="stamp ${cls}" data-stamp="area:${a?.status ?? word}">${glyph ? `<span class="ic">${glyph}</span>` : ""}${word}</span>${retryBtn}</span></li>`;
}

let lastStamps = new Set<string>();
function renderManifest(): void {
  const job = S.job;
  const rows = new Map(job?.sources.map((r) => [r.source, r]) ?? []);
  $("lines").innerHTML = areaLine() + S.specs.map((s, i) => lineFor(job ? rows.get(s.source) ?? null : null, s.source, i)).join("");
  // the signature move: a stamp lands once when its status changes
  const now = new Set<string>();
  $("lines").querySelectorAll<HTMLElement>("[data-stamp]").forEach((st) => {
    now.add(st.dataset.stamp!);
    if (lastStamps.size && !lastStamps.has(st.dataset.stamp!)) st.classList.add("fresh");
  });
  lastStamps = now;
  let totals = planSentence();
  if (job) {
    const c = job.counts;
    const n = job.sources.length;
    totals = job.running ? `Fetching: ${c.reused + c.done + c.failed} of ${n} finished` : `Finished: ${c.reused + c.done} of ${n} ready${c.failed ? ` · ${c.failed} failed` : ""}`;
  }
  $("totals").textContent = totals;
  const why = fetchBlockers();
  const btn = $<HTMLButtonElement>("fetch-btn");
  btn.disabled = why.length > 0;
  btn.textContent = job && !job.running ? "Fetch again" : "Fetch data";
  $("fetch-why").textContent = why[0] ?? "";
  $("fetch-why").hidden = !why.length;
  const sw = $("refresh");
  sw.setAttribute("aria-checked", String(S.refresh));
  (sw as HTMLButtonElement).disabled = running();
  const notes: string[] = [];
  if (S.jobError) notes.push(`<div class="note block job-note" role="alert"><span class="ic">${icon("alert")}</span><b>Fetch problem</b><p>${esc(S.jobError)}</p></div>`);
  if (job?.running) {
    const slow = job.sources.some((r) => r.status === "running" && (r.elapsed_s ?? 0) > 10);
    if (slow) notes.push(`<p class="hint">Large downloads can take over a minute (a transit zip can be 138 MB).</p>`);
    notes.push(`<div class="note info job-note"><span class="ic">${icon("info")}</span><b>No cancel</b><p>A download can't be stopped safely once it starts. You can leave this page: the fetch keeps running and this panel reconnects.</p></div>`);
  }
  if (job && !job.running && job.counts.failed > 1) notes.push(`<button class="btn btn-sm" type="button" id="retry-all"><span class="ic">${icon("retry")}</span>Retry ${job.counts.failed} failed</button>`);
  $("job-notes").innerHTML = notes.join("");
  $("no-cancel").hidden = !!job?.running;
}

$("refresh").addEventListener("click", () => { S.refresh = !S.refresh; persist(); renderSources(); renderManifest(); });
$("lines").addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest<HTMLElement>("[data-retry]");
  if (b) retry([b.dataset.retry!]);
});
$("job-notes").addEventListener("click", (e) => {
  if ((e.target as HTMLElement).closest("#retry-all")) retry(S.job!.sources.filter((r) => r.status === "failed").map((r) => r.source));
});

async function startFetch(): Promise<void> {
  const a = areaIn();
  if (!a || fetchBlockers().length) return;
  S.starting = true; S.jobError = ""; renderAll();
  const sources = S.specs.map((s) => s.source).filter((s) => S.included.has(s));
  const options = Object.fromEntries(Object.entries(S.overrides).filter(([s]) => sources.includes(s)));
  const pinned = Object.fromEntries(Object.entries(S.pinned).filter(([s]) => sources.includes(s)));
  try {
    const r = await api.fetch({ area: a, area_mode: areaMode(), level_override: S.levelOverride, sources, refresh: S.refresh, pinned, options });
    lastStamps = new Set();
    S.job = { job_id: r.job_id, area_id: (S.mode === "snap" ? S.snap?.area_id : S.validation?.area_id) ?? "", running: true, refresh: S.refresh, pinned, counts: { queued: sources.length, running: 0, reused: 0, done: 0, failed: 0 },
      sources: sources.map((s) => ({ source: s, status: "queued", attempts: 0, error: null, result: null })) };
    persist();
    announce(`Fetch started: ${sources.length} sources.`);
    poll();
  } catch (e) {
    S.jobError = (e as ApiError).message;
  }
  S.starting = false;
  renderAll();
}
$("fetch-btn").addEventListener("click", startFetch);

async function retry(sources: string[]): Promise<void> {
  if (!S.job) return;
  for (const s of sources) {
    try { S.job = await api.retry(S.job.job_id, s); } catch (e) { S.jobError = (e as Error).message; }
    if (S.job?.running) break; // one at a time: the rest stay failed with their Retry
  }
  renderAll();
  poll();
}

let pollTimer = 0;
let announcedDone = new Set<string>();
async function poll(): Promise<void> {
  clearTimeout(pollTimer);
  if (!S.job) return;
  try {
    const j = await api.job(S.job.job_id);
    for (const r of j.sources) {
      const key = `${r.source}:${r.status}:${r.attempts}`;
      if (["reused", "done", "failed"].includes(r.status) && !announcedDone.has(key)) {
        announcedDone.add(key);
        announce(r.status === "failed" ? `${label(r.source)} failed. ${plainError(r.error ?? "")} Retry available.` : `${label(r.source)} ${r.status === "reused" ? "reused from cache" : "downloaded"}.`);
      }
    }
    const wasRunning = S.job.running;
    S.job = j;
    if (wasRunning && !j.running) {
      announce(`Fetch finished: ${j.counts.reused + j.counts.done} ready, ${j.counts.failed} failed.`);
      loadLayers(); refreshSaved(); loadPlan();
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      S.jobError = "This fetch was interrupted (the server restarted). Snapshots that finished are saved: fetch again and they are reused.";
      S.job = null; persist();
    } else S.jobError = (e as Error).message;
  }
  renderAll();
  if (S.job?.running) pollTimer = window.setTimeout(poll, 700);
}

// ── results: dockets ─────────────────────────────────────────────────
function summaryText(src: string, s: Record<string, unknown>): string {
  const n = (k: string) => fmtInt(Number(s[k] ?? 0));
  if (src === "worldpop") return `${n("total_population")} people`;
  if (src === "boundaries") {
    const units = (s.units ?? {}) as Record<string, number>;
    return `${n("districts")} district${s.districts === 1 ? "" : "s"} · ${Object.entries(units).map(([k, v]) => `${v} ${k}`).join(", ")}`;
  }
  if (src === "osm_facilities") return `${n("facilities")} facilities`;
  if (src === "osm_roads") return `${n("ways")} road segments`;
  if (src === "gtfs") return `${n("feeds")} feed${s.feeds === 1 ? "" : "s"}${Number(s.skipped_over_limit) ? ` · ${s.skipped_over_limit} skipped over the limit` : ""}`;
  return JSON.stringify(s);
}
const size = (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e3).toFixed(1)} KB`);
const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";

function renderDockets(): void {
  const rows = (S.job?.sources ?? []).filter((r) => r.result);
  if (!rows.length) { $("dockets").innerHTML = ""; return; }
  $("dockets").innerHTML = `<h2 class="dockets-head">Results<span>${rows.length} snapshot${rows.length > 1 ? "s" : ""}</span></h2>` + rows.map((r) => {
    const res = r.result!;
    const files = Object.entries(res.files).map(([f, b]) => `<span class="mono">${esc(f)}</span><span>${size(b ?? 0)}</span>`).join("");
    const no = two(S.specs.findIndex((s) => s.source === r.source));
    return `<article class="docket"><div class="docket-head"><span class="line-no">${no}</span><h3>${esc(label(r.source))}</h3><span class="stamp ok">${r.status === "reused" ? "Reused" : "Downloaded"}</span></div>
      <p class="docket-sum">${esc(summaryText(r.source, res.summary))}</p>
      <dl class="kv"><dt>Snapshot</dt><dd class="mono">${esc(res.snapshot_id)}</dd><dt>Fetched</dt><dd>${esc(when(res.fetched_at))}</dd><dt>Folder</dt><dd class="mono">${esc(res.path)}</dd></dl>
      <div class="files">${files}</div>
      ${r.source === "osm_facilities" && S.facilities.length ? facilityList() : ""}
      <div class="row-actions"><button class="btn btn-sm" type="button" data-manifest="${r.source}">View manifest</button><button class="btn btn-sm btn-quiet" type="button" data-copy="${esc(res.path)}"><span class="ic">${icon("copy")}</span>Copy path</button></div></article>`;
  }).join("");
}
$("dockets").addEventListener("toggle", (e) => {
  if ((e.target as HTMLElement).classList.contains("fac-list")) S.facListOpen = (e.target as HTMLDetailsElement).open;
}, true);

function facilityList(): string {
  const name = (f: GeoJSON.Feature) => { const n = f.properties?.name; return n && n !== "null" ? String(n) : "Unnamed facility"; };
  const kind = (f: GeoJSON.Feature) => [f.properties?.amenity, f.properties?.healthcare].filter((x) => x && x !== "null").join(" · ");
  const rows = [...S.facilities].sort((a, b) => name(a).localeCompare(name(b)));
  return `<details class="fac-list" ${S.facListOpen ? "open" : ""}><summary><span class="ic">${icon("chevron")}</span>List the ${rows.length} facilities</summary><ul>${rows.map((f) =>
    `<li><button type="button" data-fac="${S.facilities.indexOf(f)}"><span>${esc(name(f))}</span><span class="src-sub">${esc(kind(f))}</span></button></li>`).join("")}</ul></details>`;
}

$("dockets").addEventListener("click", async (e) => {
  const t = e.target as HTMLElement;
  const fac = t.closest<HTMLElement>("[data-fac]");
  if (fac) { const f = S.facilities[Number(fac.dataset.fac)]; if (f) { map.showFacility(f); announce(`Showing ${f.properties?.name ?? "facility"} on the map.`); } return; }
  const m = t.closest<HTMLElement>("[data-manifest]");
  if (m) openManifest(m.dataset.manifest!, m);
  const c = t.closest<HTMLElement>("[data-copy]");
  if (c) { try { await navigator.clipboard.writeText(c.dataset.copy!); announce("Path copied."); } catch { announce("Couldn't copy: select the path text instead."); } }
});

async function openManifest(src: string, from: HTMLElement): Promise<void> {
  const r = S.job?.sources.find((x) => x.source === src)?.result;
  if (!r || !S.job) return;
  try {
    const json = await api.file(S.job.area_id, src, r.snapshot_id, "manifest.json");
    S.drawer = { title: `manifest.json · ${label(src)}`, path: `${r.path}/manifest.json`, json: JSON.stringify(json, null, 2), from };
  } catch (e) {
    S.drawer = { title: `manifest.json · ${label(src)}`, path: r.path, json: (e as Error).message, from };
  }
  const d = $("drawer");
  $("drawer-title").textContent = S.drawer.title;
  $("drawer-path").textContent = S.drawer.path;
  $("drawer-code").textContent = S.drawer.json;
  d.hidden = false;
  $("drawer-close").focus();
}
function closeDrawer(): void {
  $("drawer").hidden = true;
  S.drawer?.from?.focus();
  S.drawer = null;
}
$("drawer-close").addEventListener("click", closeDrawer);
$("drawer").addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
$("drawer-copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(S.drawer?.json ?? ""); announce("Manifest copied."); } catch { announce("Couldn't copy."); }
});

// ── map layers ───────────────────────────────────────────────────────
async function loadLayers(): Promise<void> {
  const job = S.job;
  if (!job) return;
  const get = async (src: string, file: string) => {
    const r = job.sources.find((x) => x.source === src)?.result;
    if (!r || !(file in r.files)) return null;
    try { return (await api.file(job.area_id, src, r.snapshot_id, file)) as GeoJSON.FeatureCollection; } catch { return null; }
  };
  const [d, f1, f2] = await Promise.all([get("boundaries", "districts.geojson"), get("osm_facilities", "facilities.geojson"),
    get("public_facilities", "facilities.geojson")]);
  const f: GeoJSON.FeatureCollection | null = f1 || f2 ? { type: "FeatureCollection", features: [...(f1?.features ?? []), ...(f2?.features ?? [])] } : null;
  S.layers = { districts: d?.features.length ?? 0, facilities: f?.features.length ?? 0, hasDistricts: !!d, hasFacilities: !!f };
  S.facilities = (f?.features ?? []).filter((x) => x.geometry?.type === "Point") as GeoJSON.Feature<GeoJSON.Point>[];
  renderDockets();
  // snap mode already labels each district (with its share): the fetched layer stays unlabelled there
  await map.setDistricts(d, job.area?.mode === "free", job.area?.mode !== "snap");
  await map.setFacilities(f);
  map.fitArea();
  renderLayersPanel();
  $("map-summary").textContent = `Layers loaded: ${S.layers.districts} districts, ${S.layers.facilities} facilities.`;
}

const legend = {
  area: `<svg width="26" height="14" aria-hidden="true"><line x1="1" y1="7" x2="25" y2="7" style="stroke:var(--ink)" stroke-width="2.4" stroke-dasharray="5 3"/></svg>`,
  districts: `<svg width="26" height="14" aria-hidden="true"><rect x="2" y="2" width="22" height="10" style="fill:var(--carbon-soft);stroke:var(--ink)" stroke-width="2"/></svg>`,
  snap: `<svg width="26" height="14" aria-hidden="true"><defs><pattern id="lg-h" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" style="stroke:var(--carbon)" stroke-width="1.4"/></pattern></defs><rect x="2" y="2" width="22" height="10" fill="url(#lg-h)" style="stroke:var(--ink)" stroke-width="2.5"/></svg>`,
  full: `<svg width="26" height="14" aria-hidden="true"><rect x="2" y="2" width="22" height="10" fill="url(#lg-h)" style="stroke:var(--ink)" stroke-width="2"/></svg>`,
  partial: `<svg width="26" height="14" aria-hidden="true"><rect x="2" y="2" width="22" height="10" fill="none" style="stroke:var(--ink)" stroke-width="2" stroke-dasharray="3 2"/></svg>`,
  facilities: `<svg width="26" height="14" aria-hidden="true"><rect x="9" y="3" width="8" height="8" transform="rotate(45 13 7)" style="fill:var(--ink)" stroke="#fff"/></svg>`,
};
const layerOn = { area: true, districts: true, facilities: true, snap: true };
function renderLayersPanel(): void {
  const p = $("map-layers");
  p.hidden = false; // always there: it also holds the base-map switch
  const row = (k: keyof typeof layerOn, text: string, enabled: boolean, why: string) =>
    `<label class="layer"><input type="checkbox" class="check" data-layer="${k}" ${layerOn[k] ? "checked" : ""} ${enabled ? "" : "disabled"}/>${legend[k]}<span>${text}${enabled ? "" : `<span class="src-sub">${why}</span>`}</span></label>`;
  const clipOk = S.street && !!S.geom;
  const base = `<div class="layer-group"><label class="layer-switch"><button class="switch" role="switch" type="button" id="street-toggle" aria-checked="${S.street}" ${S.streetBusy || map.failed ? "disabled" : ""}><span></span></button>
      <span>Street map, dimmed${S.streetBusy ? " · loading…" : ""}</span></label>
    <label class="layer layer-sub"><input type="checkbox" class="check" id="street-clip" ${S.streetClip ? "checked" : ""} ${clipOk ? "" : "disabled"}/><span></span><span>Only inside the area${clipOk ? "" : `<span class="src-sub">${S.street ? "draw an area first" : "turn the street map on"}</span>`}</span></label>
    ${S.streetError ? `<p class="layer-note" role="status">${esc(S.streetError)}</p>` : ""}</div>`;
  const free = S.job?.area?.mode === "free" && S.layers.hasDistricts;
  const freeLegend = free ? `<div class="layer"><span></span>${legend.full}<span>Fully covered: advice applies (hatched, solid edge)</span></div>
    <div class="layer"><span></span>${legend.partial}<span>Partial: advice not applied (dashed edge, no fill)</span></div>` : "";
  p.innerHTML = `<h3>Layers</h3>${row("area", "Drawing (dashed line)", !!S.geom, "draw an area")}
    ${row("districts", `Districts${S.layers.hasDistricts ? ` · ${S.layers.districts}` : ""} (outline, named)`, S.layers.hasDistricts, "fetch districts to see them")}
    ${freeLegend}
    ${row("snap", "Whole districts: included (hatched) · not (dotted) · snapped outline (solid)", S.mode === "snap" && !!S.snap?.districts.length, S.mode === "snap" ? "draw an area to see them" : "only in whole-district mode")}
    ${row("facilities", `Facilities${S.layers.hasFacilities ? ` · ${S.layers.facilities}` : ""} (diamonds; circles = clusters)`, S.layers.hasFacilities, "fetch facilities to see them")}${base}`;
}
async function setStreet(on: boolean): Promise<void> {
  S.streetBusy = true; S.streetError = ""; renderLayersPanel();
  try {
    await map.setStreet(on); // same map, same camera: the view does not move
    S.street = on;
    announce(on ? "Street map on, dimmed under the data." : "Street map off.");
  } catch (e) {
    S.street = false; S.streetError = (e as Error).message;
  }
  S.streetBusy = false;
  try { localStorage.setItem("leg-street", JSON.stringify({ on: S.street, clip: S.streetClip })); } catch { /* per-viewer convenience only */ }
  renderLayersPanel();
  document.getElementById("street-toggle")?.focus();
}
$("map-layers").addEventListener("click", (e) => {
  if ((e.target as HTMLElement).closest("#street-toggle")) setStreet(!S.street);
});
$("map-layers").addEventListener("change", (e) => {
  const t = e.target as HTMLInputElement;
  if (t.id === "street-clip") {
    S.streetClip = t.checked; map.setStreetClip(t.checked);
    try { localStorage.setItem("leg-street", JSON.stringify({ on: S.street, clip: S.streetClip })); } catch { /* ignore */ }
    announce(t.checked ? "Street map shown only inside the area." : "Street map shown everywhere, dimmed.");
    return;
  }
  const k = t.dataset.layer as keyof typeof layerOn;
  if (!k) return;
  layerOn[k] = t.checked;
  map.setVisible(k, t.checked);
});

// ── saved areas + tabs ───────────────────────────────────────────────
async function refreshSaved(): Promise<void> {
  try { S.saved = await api.areas(); } catch { S.saved = []; }
  renderSaved();
}
function renderSaved(): void {
  $("saved-count").textContent = String(S.saved.length);
  const q = $<HTMLInputElement>("saved-filter").value.trim().toLowerCase();
  const rows = S.saved.filter((a) => !q || `${a.name} ${a.iso3} ${a.area_id}`.toLowerCase().includes(q));
  $("saved-list").innerHTML = rows.length ? rows.map((a) => {
    const n = Object.keys(a.sources).length;
    const age = a.newest_fetched_at ? ageText((Date.now() - Date.parse(a.newest_fetched_at)) / 864e5) : "";
    return `<li><button type="button" data-area="${esc(a.area_id)}"><span class="saved-name">${esc(a.name)} · ${esc(a.iso3)}</span>
      <span class="saved-meta mono">${esc(a.area_id)}</span><span class="saved-meta">${a.mode ? `<span class="stamp ${a.mode === "snap" ? "ok" : "warn"}">${a.mode === "snap" ? "Whole districts" : "Free polygon"}</span> · ` : ""}${a.km2 ? `${fmtInt(a.km2)} km² · ` : ""}${n} of ${S.specs.length} sources · newest ${age}</span></button></li>`;
  }).join("") : `<li class="saved-empty">${S.saved.length ? "No saved area matches the filter." : "Areas you fetch are saved in the cache and listed here."}</li>`;
}
$("saved-filter").addEventListener("input", renderSaved);
$("saved-list").addEventListener("click", async (e) => {
  const b = (e.target as HTMLElement).closest<HTMLElement>("[data-area]");
  const a = S.saved.find((x) => x.area_id === b?.dataset.area);
  if (!a || running()) return;
  S.name = a.name; $<HTMLInputElement>("area-name").value = a.name;
  S.nameAuto = false; S.countryAuto = false;
  S.overrides = {}; S.pinned = {}; S.refresh = false; S.job = null; S.jobError = "";
  S.layers = { districts: 0, facilities: 0, hasDistricts: false, hasFacilities: false };
  map.setDistricts(null); map.setFacilities(null);
  pickCountry(a.iso3, false);
  // reopen as it was made: the drawing (not the snapped outline), the mode, the rule and the user's choices
  S.mode = a.mode === "free" ? "free" : "snap";
  S.minShare = a.min_share ?? 0.5; $<HTMLInputElement>("min-share").value = String(S.minShare);
  S.include = new Set(a.include ?? []); S.exclude = new Set(a.exclude ?? []);
  S.levelOverride = a.level_override ?? null;
  renderMode();
  S.geom = (a.drawn_geojson?.geometry ?? a.geojson.geometry) as Geo;
  renderLayersPanel();
  await map.setArea(S.geom, true);
  S.shares = map.failed ? [] : map.countryShares(S.geom).map((c) => ({ ...c, iso3: NE_TO_ISO[c.iso3] ?? c.iso3 })).filter((c) => c.share >= 0.01);
  renderDetect();
  selectTab("new");
  announce(`Opened ${a.name}, ${a.area_id}.`);
  onAreaChanged();
});

function selectTab(which: "new" | "saved"): void {
  for (const t of ["new", "saved"] as const) {
    const tab = $(`tab-${t}`);
    tab.setAttribute("aria-selected", String(t === which));
    tab.tabIndex = t === which ? 0 : -1;
    $(`panel-${t}`).hidden = t !== which;
  }
}
$("tab-new").addEventListener("click", () => selectTab("new"));
$("tab-saved").addEventListener("click", () => { selectTab("saved"); refreshSaved(); });
document.querySelector(".tabs")!.addEventListener("keydown", (e) => {
  const k = (e as KeyboardEvent).key;
  if (k !== "ArrowLeft" && k !== "ArrowRight") return;
  const next = $("tab-new").getAttribute("aria-selected") === "true" ? "saved" : "new";
  selectTab(next); $(`tab-${next}`).focus(); if (next === "saved") refreshSaved();
});

// section collapse
document.querySelectorAll<HTMLButtonElement>(".sec-toggle").forEach((b) => b.addEventListener("click", () => {
  const open = b.getAttribute("aria-expanded") !== "true";
  b.setAttribute("aria-expanded", String(open));
  $(b.getAttribute("aria-controls")!).hidden = !open;
}));

// lock inputs during a fetch
function renderLock(): void {
  const lock = running();
  document.querySelectorAll<HTMLInputElement | HTMLButtonElement>("#area-body input, #area-body button, #profile-body button").forEach((el) => {
    if (lock) { if (!el.disabled) { el.disabled = true; el.dataset.locked = "1"; } } else if (el.dataset.locked) { el.disabled = false; delete el.dataset.locked; }
  });
  if (lock && currentTool) map.setTool(null);
}

// innerHTML re-renders replace buttons; put keyboard focus back on the same control (or its row)
function keepFocus(render: () => void): void {
  const a = document.activeElement as HTMLElement | null;
  const attrs = ["data-retry", "data-manifest", "data-copy", "data-fac", "id"];
  const key = a && attrs.map((k) => [k, a.getAttribute(k)] as const).find(([, v]) => v);
  render();
  if (!key || document.activeElement !== document.body) return;
  const [k, v] = key;
  const sel = k === "id" ? `#${CSS.escape(v!)}` : `[${k}="${CSS.escape(v!)}"]`;
  const next = document.querySelector<HTMLElement>(sel) ?? (k === "data-retry" ? document.querySelector<HTMLElement>(`[data-stamp^="${v}:"]`)?.closest<HTMLElement>(".line") ?? null : null);
  if (next) { if (!next.matches("button, input, select, a")) next.tabIndex = -1; next.focus(); }
}

function renderAll(): void {
  renderMode();
  renderSnap();
  renderReadout();
  renderProfile();
  renderSourcesKeepFocus();
  keepFocus(renderManifest);
  keepFocus(renderDockets);
  renderTools();
  renderHint();
  renderLayersPanel();
  renderLock();
}

// ── boot ─────────────────────────────────────────────────────────────
async function boot(): Promise<void> {
  hydrateIcons();
  renderTools(); renderHint(); renderSources(); renderManifest(); renderLayersPanel();
  try {
    [S.config, S.countries, S.specs] = await Promise.all([api.config(), api.countries(), api.sources()]);
  } catch (e) {
    document.body.insertAdjacentHTML("afterbegin", `<div class="note block" role="alert" style="margin:0;border-width:0 0 1px"><span class="ic">${icon("alert")}</span><b>The fetcher server isn't running</b><p>${esc((e as Error).message)} The page retries every 5 seconds.</p></div>`);
    setTimeout(() => location.reload(), 5000);
    return;
  }
  S.included = new Set(S.specs.map((s) => s.source));
  renderHeader();
  try {
    const pref = JSON.parse(localStorage.getItem("leg-street") ?? "null");
    if (pref?.clip) { S.streetClip = true; map.setStreetClip(true); }
    if (pref?.on) setStreet(true);
  } catch { /* no stored preference */ }
  refreshSaved();
  let saved: Record<string, unknown> | null = null;
  try { saved = JSON.parse(sessionStorage.getItem(STORE) ?? "null"); } catch { saved = null; }
  if (saved) {
    S.name = String(saved.name ?? ""); $<HTMLInputElement>("area-name").value = S.name;
    S.nameAuto = !S.name; S.countryAuto = !saved.iso3; // restored values count as chosen
    S.overrides = (saved.overrides as typeof S.overrides) ?? {};
    S.pinned = (saved.pinned as typeof S.pinned) ?? {};
    S.refresh = !!saved.refresh;
    if (saved.mode === "free" || saved.mode === "snap") S.mode = saved.mode;
    if (typeof saved.minShare === "number") S.minShare = saved.minShare;
    S.include = new Set((saved.include as string[]) ?? []); S.exclude = new Set((saved.exclude as string[]) ?? []);
    S.levelOverride = (saved.levelOverride as Level | null) ?? null;
    renderMode();
    if (Array.isArray(saved.included)) S.included = new Set(saved.included as string[]);
    if (saved.iso3) pickCountry(String(saved.iso3), false);
    if (saved.geom) { S.geom = saved.geom as Geo; renderLayersPanel(); await map.setArea(S.geom, true); }
    if (saved.jobId) {
      S.job = { job_id: String(saved.jobId), area_id: "", running: true, refresh: S.refresh, pinned: S.pinned, counts: { queued: 0, running: 0, reused: 0, done: 0, failed: 0 }, sources: [] };
      await poll();
      if (S.job && !S.job.running) loadLayers();
    }
  }
  renderAll();
  if (S.geom) validate();
}
boot();
