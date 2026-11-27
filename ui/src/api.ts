// Typed calls to the leg.api FastAPI layer. The UI never re-implements cache or validation rules.

export type Geo = GeoJSON.Polygon | GeoJSON.MultiPolygon;
export interface AreaIn { name: string; iso3: string; geojson: unknown }
export interface Msg { code: string; message: string; share_outside?: number }

export interface AreaMode { mode: "snap" | "free"; min_share: number; include: string[]; exclude: string[] }
export interface Level { provider: string; level: string }
export interface LevelCount { provider: string; level: string; available: boolean; touched: number; usable: number; note: string }
export interface LevelChoice { provider: string; level: string; usable: number; in_range: boolean; reason: string; counts: LevelCount[]; rule: Record<string, unknown> }
export interface LevelJob {
  job_id: string; status: "running" | "done" | "failed"; probing: Level | null;
  in_progress?: (Level & { elapsed_s: number })[];   // every level being checked right now
  probed: (Level & { state: "cached" | "downloaded" | "missing" | "no unit" | "failed" | "skipped";
    touched: number; usable: number; note: string; seconds: number | null })[];
  choice: LevelChoice | null; error: string | null; area_id: string; mode: string; min_share: number;
}
export interface SnapDistrict {
  unit_id: string; name: string | null; share_inside_area: number; fully_inside: boolean; included: boolean;
  reason: "majority" | "minority" | "added by user" | "removed by user"; geometry: GeoJSON.Geometry;
}
export interface SnapResp {
  ok: boolean; mode: "snap" | "free"; drawn_area_id: string; drawn_km2: number; area_id: string | null; km2: number | null;
  geojson: GeoJSON.Geometry | null; min_share: number; districts: SnapDistrict[]; boundaries_snapshot?: string;
  error: null | { code: "no_district_qualifies" | "boundaries_failed" | "no_level" | "levels_failed"; message: string };
  level: (Level & { source: "rule" | "override"; in_range: boolean; reason: string }) | null;
  warnings: Msg[]; size_errors: Msg[];
}
export interface Config { cache_root: string; llm_key_present: boolean; warn_km2: number; max_km2: number }
export interface Country { name: string; iso3: string }
export interface SavedArea {
  area_id: string; name: string; iso3: string; geojson: GeoJSON.Feature<Geo>; km2: number | null;
  bbox: number[]; sources: Record<string, string[]>; newest_fetched_at: string;
  mode: "snap" | "free" | null; drawn_geojson?: GeoJSON.Feature<Geo>; min_share?: number; include?: string[]; exclude?: string[];
  level_override?: Level | null; level_choice?: LevelChoice | null;
}
export interface Validation { ok: boolean; area_id?: string; bbox?: number[]; km2?: number; warnings: Msg[]; errors: Msg[]; same_shape?: string[] }
export interface Profile {
  admin_provider: string; admin_levels: string[]; facility_tags: [string, string][]; source: "default" | "llm";
  rationale: string; status: "llm" | "default_no_key" | "default_llm_failed"; note: string;
  fetcher_options: Record<string, Record<string, unknown>>;
}
export interface OptionSpec {
  type: "int" | "enum" | "levels" | "tags" | "multi"; min?: number; max?: number; values?: string[]; keys?: string[]; default: unknown;
}
export interface SourceSpec { source: string; label: string; ttl_days: number; options: Record<string, OptionSpec> }
export interface SnapInfo { id: string; fetched_at: string; age_days: number; params_match: boolean; fresh: boolean }
export interface PlanRow {
  source: string; label: string; ttl_days: number; errors: Record<string, string>;
  decision: "reuse" | "download" | "invalid"; reason?: "no_snapshot" | "params_changed" | "expired";
  snapshot_id?: string; fresh_days_left?: number; snapshots: SnapInfo[];
}
export interface SnapResult {
  snapshot_id: string; path: string; fetched_at: string; summary: Record<string, unknown>;
  params: Record<string, unknown>; urls: string[]; files: Record<string, number>;
}
export interface JobRow {
  source: string; status: "queued" | "running" | "reused" | "done" | "failed"; attempts: number;
  error: string | null; elapsed_s?: number; result: SnapResult | null;
}
export interface JobArea {
  status: "queued" | "running" | "done" | "failed"; error: string | null; area_id: string | null; km2: number | null;
  included: string[] | null; mode: "snap" | "free"; drawn_area_id: string; drawn_km2: number; elapsed_s: number | null;
  level: (Level & { source: "rule" | "override"; in_range: boolean }) | null;
}
export interface Job {
  area?: JobArea;
  job_id: string; area_id: string; running: boolean; refresh: boolean; pinned: Record<string, string>;
  counts: Record<string, number>; sources: JobRow[];
}

export interface PrepOutput {
  run_id: string; path: string; planning_year: number | null; seconds?: number; params?: Record<string, unknown>;
  totals: { cells: number; pairs: number; districts: number; population: number; covered_population: number; existing_facilities: number };
  unassigned: { cells: number; population: number }; dropped_facilities: number; files: Record<string, number>;
}
export interface PrepJob {
  job_id: string; area_id: string; status: "queued" | "running" | "done" | "failed"; running: boolean;
  stage: string | null; stage_label: string; stage_index: number; stages: number; percent: number;
  elapsed_s: number; eta_s: number | null; error: string | null; warnings: string[]; output: PrepOutput | null;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(ApiError.text(detail));
  }
  static text(detail: unknown): string {
    const d = (detail as { detail?: { errors?: unknown } })?.detail ?? detail;
    const errs = (d as { errors?: unknown })?.errors ?? d;
    if (Array.isArray(errs)) return errs.join(" ");
    if (errs && typeof errs === "object") return Object.values(errs as Record<string, unknown>).map((v) => (typeof v === "object" ? Object.values(v as object).join(" ") : String(v))).join(" ");
    return String(errs ?? "Request failed");
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method, headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, { errors: ["The fetcher server isn't reachable. Start it with ./start.sh"] });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

export const api = {
  config: () => call<Config>("GET", "/api/config"),
  countries: () => call<Country[]>("GET", "/api/countries"),
  areas: () => call<SavedArea[]>("GET", "/api/areas"),
  sources: () => call<SourceSpec[]>("GET", "/api/sources"),
  validate: (a: AreaIn) => call<Validation>("POST", "/api/area/validate", a),
  profile: (area: AreaIn, refresh = false) => call<Profile>("POST", "/api/profile", { area, refresh }),
  plan: (area: AreaIn, options: Record<string, unknown>, area_mode: AreaMode, level_override: Level | null) =>
    call<Record<string, PlanRow>>("POST", "/api/snapshots", { area, options, area_mode, level_override }),
  snap: (area: AreaIn, options: Record<string, unknown>, area_mode: AreaMode, level_override: Level | null) =>
    call<SnapResp>("POST", "/api/area/snap", { area, options, area_mode, level_override }),
  prep: (body: { area_id: string; pinned?: Record<string, string>; max_minutes?: number; years?: number[] }) =>
    call<{ job_id: string }>("POST", "/api/prep", body),
  prepJob: (id: string) => call<PrepJob>("GET", `/api/prep/${id}`),
  prepRuns: (areaId: string) => call<{ area_id: string; runs: PrepOutput[] }>("GET", `/api/prep/area/${encodeURIComponent(areaId)}`),
  levels: (area: AreaIn, area_mode: AreaMode) => call<LevelJob>("POST", "/api/area/levels", { area, area_mode }),
  levelJob: (id: string) => call<LevelJob>("GET", `/api/area/levels/${id}`),
  fetch: (body: { area: AreaIn; area_mode: AreaMode; level_override: Level | null; sources: string[]; refresh: boolean; pinned: Record<string, string>; options: Record<string, unknown> }) =>
    call<{ job_id: string; order: string[] }>("POST", "/api/fetch", body),
  job: (id: string) => call<Job>("GET", `/api/fetch/${id}`),
  retry: (id: string, source: string) => call<Job>("POST", `/api/fetch/${id}/retry/${source}`),
  file: (areaId: string, source: string, snap: string, file: string) =>
    call<unknown>("GET", `/api/snapshot/${encodeURIComponent(areaId)}/${source}/${encodeURIComponent(snap)}/${file}`),
};
