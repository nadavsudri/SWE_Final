// The map: bundled country outlines (works offline), one drawn area, and the fetched layers.
import maplibregl, { type GeoJSONSource, type LngLatBoundsLike, type Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  TerraDraw, TerraDrawPolygonMode, TerraDrawRectangleMode, TerraDrawSelectMode, type GeoJSONStoreFeatures,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import type { Geo } from "./api";

export type Tool = "rect" | "poly" | "edit" | null;
type Pos = [number, number];
// map colours come from the page tokens (styles.css :root), read once at start
const token = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
const INK = token("--ink", "#1D2B4A");
const CARBON = token("--carbon", "#2F4BB8");
const BAD = token("--bad", "#B3261E");
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export function bboxOf(geom: GeoJSON.Geometry): [number, number, number, number] {
  let w = 180, s = 90, e = -180, n = -90;
  const walk = (c: unknown): void => {
    if (typeof (c as number[])[0] === "number") {
      const [x, y] = c as number[];
      w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
    } else (c as unknown[]).forEach(walk);
  };
  walk((geom as GeoJSON.Polygon).coordinates);
  return [w, s, e, n];
}

function labelPoint(geom: GeoJSON.Geometry): Pos {
  // centre of the largest ring's bbox: cheap, offline, good enough for a label
  const polys = geom.type === "MultiPolygon" ? geom.coordinates : geom.type === "Polygon" ? [geom.coordinates] : [];
  let best: number[][] = [], size = -1;
  for (const p of polys) {
    const [w, s, e, n] = bboxOf({ type: "Polygon", coordinates: [p[0]] });
    if ((e - w) * (n - s) > size) { size = (e - w) * (n - s); best = p[0]; }
  }
  const [w, s, e, n] = bboxOf({ type: "Polygon", coordinates: [best] });
  return [(w + e) / 2, (s + n) / 2];
}

export class AreaMap {
  map!: MLMap;
  failed = false;
  private draw!: TerraDraw;
  private ready!: Promise<void>;
  private tool: Tool = null;
  private kbPoints: Pos[] = [];
  private kbVertex = 0;
  private geom: Geo | null = null;
  private districtMarkers: maplibregl.Marker[] = [];
  private clusterMarkers = new Map<number, maplibregl.Marker>();
  private countries: GeoJSON.FeatureCollection = EMPTY;
  private visible = { area: true, districts: true, facilities: true, snap: true };
  private street = { on: false, loaded: false, clip: false };
  onStreetError: (msg: string) => void = () => {};
  onArea: (g: Geo | null) => void = () => {};
  onAnnounce: (msg: string) => void = () => {};
  onToolChange: (t: Tool) => void = () => {};
  onReplaced: (previous: Geo) => void = () => {};
  onDistrictClick: (unitId: string) => void = () => {};
  private snapMarkers: maplibregl.Marker[] = [];
  // each label's district extent: a label shows only when its district is drawn big enough to hold it
  private labelBox = new WeakMap<maplibregl.Marker, [number, number, number, number]>();
  /** Pixels the top-right legend covers; fits keep the area clear of it. */
  legendBottom: () => number = () => 150;

  constructor(private el: HTMLElement) {
    try {
      this.map = this.create();
    } catch {
      // no WebGL (disabled, old GPU, some VMs): the rest of the screen still works
      this.failed = true;
      this.ready = Promise.resolve();
      el.innerHTML = `<div class="map-fail" role="note"><b>The map can't start: this browser has WebGL turned off.</b>
        Everything else still works: upload a GeoJSON file for the area, then fetch and read the results on the right.</div>`;
      return;
    }
    this.map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-left");
    const countries = fetch("/countries.geojson").then((r) => r.json()).catch(() => EMPTY);
    this.ready = new Promise((resolve) => this.map.once("load", async () => {
      this.countries = await countries; // one download, shared by the basemap and the country fit
      (this.map.getSource("countries") as GeoJSONSource).setData(this.countries);
      this.setup(); resolve();
    }));
  }

  private create(): MLMap {
    return new maplibregl.Map({
      container: this.el, center: [20, 25], zoom: 1.3, attributionControl: false,
      dragRotate: false, pitchWithRotate: false, keyboard: true, renderWorldCopies: false,
      style: {
        version: 8,
        sources: {
          countries: { type: "geojson", data: EMPTY, attribution: "Natural Earth" },
          area: { type: "geojson", data: EMPTY },
          kb: { type: "geojson", data: EMPTY },
          districts: { type: "geojson", data: EMPTY },
          "snap-d": { type: "geojson", data: EMPTY },
          snapped: { type: "geojson", data: EMPTY },
          "sheet-out": { type: "geojson", data: EMPTY },
          "sheet-in": { type: "geojson", data: EMPTY },
          facilities: { type: "geojson", data: EMPTY, cluster: true, clusterRadius: 42, clusterMaxZoom: 11 },
        },
        layers: [
          { id: "sea", type: "background", paint: { "background-color": token("--sea", "#D9E0E6") } },
          { id: "land", type: "fill", source: "countries", paint: { "fill-color": token("--land", "#F7F7F4") } },
          // the street map's layers are inserted here (below the sheet) when it is switched on
          { id: "sheet-out", type: "fill", source: "sheet-out", layout: { visibility: "none" }, paint: { "fill-color": token("--ground", "#F3F4F1"), "fill-opacity": 0.45 } },
          { id: "sheet-in", type: "fill", source: "sheet-in", layout: { visibility: "none" }, paint: { "fill-color": token("--ground", "#F3F4F1"), "fill-opacity": 0.45 } },
          { id: "borders", type: "line", source: "countries", paint: { "line-color": "#A3ACBA", "line-width": 0.8 } },
          { id: "country", type: "line", source: "countries", filter: ["==", ["get", "iso3"], ""],
            paint: { "line-color": INK, "line-width": 1.6, "line-dasharray": [0.6, 1.6] } },
          { id: "districts-fill", type: "fill", source: "districts", paint: { "fill-color": INK, "fill-opacity": 0.04 } },
          // free mode: districts the polygon covers completely are hatched; partial ones are dashed and unfilled
          { id: "districts-full-fill", type: "fill", source: "districts", layout: { visibility: "none" }, filter: ["==", ["get", "fully_inside"], true], paint: { "fill-pattern": "hatch" } },
          { id: "districts-line", type: "line", source: "districts", paint: { "line-color": INK, "line-width": 2 } },
          { id: "districts-partial-line", type: "line", source: "districts", layout: { visibility: "none" }, filter: ["!=", ["get", "fully_inside"], true],
            paint: { "line-color": INK, "line-width": 2, "line-dasharray": [2, 2] } },
          // snap mode: every district the drawing touches, included (hatched, solid edge) or not (dotted edge)
          { id: "snap-out-fill", type: "fill", source: "snap-d", filter: ["!=", ["get", "included"], true], paint: { "fill-color": INK, "fill-opacity": 0.01 } },
          { id: "snap-in-fill", type: "fill", source: "snap-d", filter: ["==", ["get", "included"], true], paint: { "fill-pattern": "hatch" } },
          { id: "snap-out-line", type: "line", source: "snap-d", filter: ["!=", ["get", "included"], true], paint: { "line-color": token("--ink-2", "#4A5671"), "line-width": 1.2, "line-dasharray": [1, 2] } },
          { id: "snap-in-line", type: "line", source: "snap-d", filter: ["==", ["get", "included"], true], paint: { "line-color": CARBON, "line-width": 1.2 } },
          { id: "snapped-line", type: "line", source: "snapped", paint: { "line-color": INK, "line-width": 3.5 } },
          { id: "area-halo", type: "line", source: "area", paint: { "line-color": "#FFFFFF", "line-width": 5, "line-opacity": 0.9 } },
          { id: "area-line", type: "line", source: "area", paint: { "line-color": INK, "line-width": 2.4, "line-dasharray": [3, 2] } },
          { id: "kb-line", type: "line", source: "kb", paint: { "line-color": BAD, "line-width": 2 } },
          { id: "kb-pts", type: "circle", source: "kb", paint: { "circle-radius": 4, "circle-color": "#FFFFFF", "circle-stroke-color": BAD, "circle-stroke-width": 2 } },
          { id: "fac-pt", type: "symbol", source: "facilities", filter: ["!", ["has", "point_count"]],
            layout: { "icon-image": "diamond", "icon-allow-overlap": true } },
        ],
      },
    });
  }

  private setup(): void {
    const c = document.createElement("canvas");
    c.width = c.height = 20;
    const g = c.getContext("2d")!;
    g.translate(10, 10); g.rotate(Math.PI / 4);
    g.fillStyle = INK; g.strokeStyle = "#FFFFFF"; g.lineWidth = 2;
    g.fillRect(-5.5, -5.5, 11, 11); g.strokeRect(-5.5, -5.5, 11, 11);
    this.map.addImage("diamond", g.getImageData(0, 0, 20, 20), { pixelRatio: 1.4 });
    const h = document.createElement("canvas");
    h.width = h.height = 10;
    const hg = h.getContext("2d")!;
    hg.strokeStyle = CARBON; hg.globalAlpha = 0.55; hg.lineWidth = 1.4;
    hg.beginPath(); hg.moveTo(0, 10); hg.lineTo(10, 0); hg.moveTo(-5, 5); hg.lineTo(5, -5); hg.moveTo(5, 15); hg.lineTo(15, 5); hg.stroke();
    this.map.addImage("hatch", hg.getImageData(0, 0, 10, 10), { pixelRatio: 1 });

    const C = CARBON as `#${string}`;
    const poly = { fillColor: C, fillOpacity: 0.08, outlineColor: C, outlineWidth: 1.5 } as const;
    const vertex = { coordinatePointColor: "#FFFFFF", coordinatePointOutlineColor: C, coordinatePointOutlineWidth: 2, coordinatePointWidth: 5 } as const;
    const editable = { feature: { coordinates: { draggable: true, midpoints: true, deletable: true } } };
    this.draw = new TerraDraw({
      adapter: new TerraDrawMapLibreGLAdapter({ map: this.map }),
      modes: [
        new TerraDrawRectangleMode({ styles: { ...poly } }),
        new TerraDrawPolygonMode({ styles: { ...poly, ...vertex, closingPointColor: C, closingPointWidth: 6 } }),
        new TerraDrawSelectMode({
          flags: { polygon: editable, rectangle: editable },
          styles: { selectedPolygonColor: C, selectedPolygonFillOpacity: 0.1, selectedPolygonOutlineColor: C,
            selectedPolygonOutlineWidth: 2, selectionPointColor: "#FFFFFF", selectionPointOutlineColor: C,
            selectionPointOutlineWidth: 2, selectionPointWidth: 6, midPointColor: C, midPointWidth: 3 },
        }),
      ],
    });
    this.draw.start();
    this.draw.setMode("static");
    this.draw.on("finish", (id, ctx) => {
      const f = this.draw.getSnapshot().find((x) => x.id === id);
      if (!f || f.geometry.type !== "Polygon") return;
      // a new shape replaces the old one; an edit (select mode) only updates it. The store also holds
      // terra-draw's own vertex handles and midpoints while editing: those must never be removed.
      const created = ctx?.mode === "rectangle" || ctx?.mode === "polygon";
      const others = created ? this.areaFeatures().filter((x) => x.id !== f.id).map((x) => x.id!) : [];
      const previous = others.length ? this.geom : null;
      if (others.length) this.draw.removeFeatures(others);
      this.commit(f.geometry as Geo);
      if (previous) this.onReplaced(previous);
      if (this.tool !== "edit") this.setTool("edit");
    });

    // A vertex dragged past the map's edge and released outside it never sees pointerup, so terra-draw
    // would keep dragging it on the next mouse move. End such a drag at the nearest point on the map.
    window.addEventListener("pointerup", (e) => {
      if (this.tool !== "edit" && this.tool !== "rect" && this.tool !== "poly") return;
      const c = this.map.getCanvas(); // terra-draw only listens on the canvas itself
      if (e.target === c) return;
      const r = c.getBoundingClientRect();
      const x = Math.min(r.right - 1, Math.max(r.left + 1, e.clientX)), y = Math.min(r.bottom - 1, Math.max(r.top + 1, e.clientY));
      c.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: x, clientY: y, pointerId: e.pointerId,
        pointerType: e.pointerType, isPrimary: true, button: 0, buttons: 0 }));
    });
    // Editing (select mode): terra-draw reports vertex drags only as "change" events, never "finish".
    // Keep the dashed outline on the shape while it moves, and commit it once the drag has stopped.
    let editTimer = 0;
    this.draw.on("change", (ids, type, ctx) => {
      if (type !== "update" || this.tool !== "edit" || (ctx as { target?: string } | undefined)?.target !== "geometry") return;
      const f = this.areaFeatures().find((x) => ids.includes(x.id!));
      if (!f) return;
      (this.map.getSource("area") as GeoJSONSource).setData({ type: "Feature", properties: {}, geometry: f.geometry });
      clearTimeout(editTimer);
      editTimer = window.setTimeout(() => {
        const now = this.areaFeatures().find((x) => x.id === f.id);
        if (now) this.commit(now.geometry as Geo);
      }, 350);
    });
    this.map.on("click", "fac-pt", (e) => {
      this.popup((e.features?.[0]?.properties ?? {}) as Record<string, unknown>, [e.lngLat.lng, e.lngLat.lat]);
    });
    for (const id of ["snap-in-fill", "snap-out-fill"]) {
      this.map.on("click", id, (e) => {
        if (this.tool === "rect" || this.tool === "poly") return;
        const uid = e.features?.[0]?.properties?.unit_id;
        if (uid != null) this.onDistrictClick(String(uid));
      });
      this.map.on("mouseenter", id, () => { if (this.tool !== "rect" && this.tool !== "poly") this.map.getCanvas().style.cursor = "pointer"; });
      this.map.on("mouseleave", id, () => (this.map.getCanvas().style.cursor = ""));
    }
    this.map.on("mouseenter", "fac-pt", () => (this.map.getCanvas().style.cursor = "pointer"));
    this.map.on("mouseleave", "fac-pt", () => (this.map.getCanvas().style.cursor = ""));
    this.map.on("render", () => this.updateClusters());
    this.map.on("zoomend", () => this.placeLabels());
    this.map.on("moveend", () => this.placeLabels());
    this.map.on("error", (e) => {
      const id = (e as unknown as { sourceId?: string }).sourceId ?? "";
      if (this.street.on && id.startsWith("st-")) this.onStreetError("Street map tiles aren't loading: no network connection?");
    });
    this.el.addEventListener("keydown", (e) => this.onKey(e));
  }

  private popup(p: Record<string, unknown>, at: Pos): void {
    const esc = (s: unknown) => String(s ?? "-").replace(/[&<>"]/g, (ch) => `&#${ch.charCodeAt(0)};`);
    const val = (k: string) => (p[k] === "null" || p[k] == null ? null : p[k]);
    const rows = ["amenity", "healthcare", "emergency", "osm_id"].map((k) => `<dt>${k}</dt><dd>${esc(val(k))}</dd>`).join("");
    new maplibregl.Popup({ offset: 10, maxWidth: "280px" }).setLngLat(at)
      .setHTML(`<h3>${esc(val("name") ?? "Unnamed facility")}</h3><dl class="kv">${rows}</dl>`).addTo(this.map);
  }

  /** Keyboard / list twin of clicking a facility on the map. */
  showFacility(f: GeoJSON.Feature<GeoJSON.Point>): void {
    if (this.failed) return;
    const at = f.geometry.coordinates as Pos;
    this.map.easeTo({ center: at, zoom: Math.max(this.map.getZoom(), 13), duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 400 });
    this.popup((f.properties ?? {}) as Record<string, unknown>, at);
  }

  // ── area ───────────────────────────────────────────
  private commit(g: Geo | null): void {
    this.geom = g;
    if (this.failed) { this.onArea(g); return; }
    (this.map.getSource("area") as GeoJSONSource).setData(g ? { type: "Feature", properties: {}, geometry: g } : EMPTY);
    this.updateSheet();
    this.onArea(g);
  }

  async setArea(g: Geo | null, fit = true): Promise<void> {
    await this.ready;
    if (this.failed) { this.geom = g; return; }
    this.draw.clear();
    if (g) {
      const polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates];
      const feats = polys.map((coords) => ({ type: "Feature", properties: { mode: "polygon" },
        geometry: { type: "Polygon", coordinates: coords.map((ring) => ring.map(([x, y]) => [+x.toFixed(7), +y.toFixed(7)])) } }));
      if (polys.length === 1) this.draw.addFeatures(feats as GeoJSONStoreFeatures[]);
    }
    this.geom = g;
    (this.map.getSource("area") as GeoJSONSource).setData(g ? { type: "Feature", properties: {}, geometry: g } : EMPTY);
    this.updateSheet();
    if (g && fit) this.fit(bboxOf(g));
  }

  get area(): Geo | null { return this.geom; }

  /** The drawn area in terra-draw's store (rectangle or polygon), without its editing handles. */
  private areaFeatures() {
    return this.draw.getSnapshot().filter((x) => x.geometry.type === "Polygon" && ["polygon", "rectangle"].includes(String(x.properties?.mode)));
  }

  clearArea(): void {
    this.draw?.clear();
    this.commit(null);
    this.setTool(null);
  }

  setTool(t: Tool): void {
    this.tool = t;
    this.kbPoints = [];
    this.kbVertex = 0;
    this.drawKb();
    if (!this.draw) return;
    this.draw.setMode(t === "rect" ? "rectangle" : t === "poly" ? "polygon" : t === "edit" ? "select" : "static");
    if (t === "edit") {
      const f = this.areaFeatures()[0];
      if (f) this.draw.selectFeature(f.id!);
    }
    this.onToolChange(t);
  }

  // ── keyboard drawing: crosshair at the map centre ──
  private centre(): Pos {
    const c = this.map.getCenter();
    return [+c.lng.toFixed(5), +c.lat.toFixed(5)];
  }

  private drawKb(): void {
    if (this.failed) return;
    const src = this.map.getSource("kb") as GeoJSONSource | undefined;
    if (!src) return;
    const pts = this.kbPoints;
    const feats: GeoJSON.Feature[] = pts.map((p) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } }));
    if (pts.length > 1) feats.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts } });
    src.setData({ type: "FeatureCollection", features: feats });
  }

  private onKey(e: KeyboardEvent): void {
    if (e.target !== this.el && !this.el.contains(e.target as Node)) return;
    const t = this.tool;
    const fmt = ([x, y]: Pos) => `${Math.abs(y).toFixed(2)}° ${y >= 0 ? "N" : "S"}, ${Math.abs(x).toFixed(2)}° ${x >= 0 ? "E" : "W"}`;
    if ((t === "rect" || t === "poly") && e.key === "Enter") {
      e.preventDefault();
      const p = this.centre();
      if (t === "rect") {
        this.kbPoints.push(p);
        this.onAnnounce(`Corner ${this.kbPoints.length} set at ${fmt(p)}`);
        if (this.kbPoints.length === 2) {
          const [[x1, y1], [x2, y2]] = this.kbPoints;
          const [w, e2, s, n] = [Math.min(x1, x2), Math.max(x1, x2), Math.min(y1, y2), Math.max(y1, y2)];
          this.kbPoints = [];
          this.drawKb();
          if (w === e2 || s === n) { this.onAnnounce("The two corners must differ. Pan the map and try again."); return; }
          const g: Geo = { type: "Polygon", coordinates: [[[w, s], [e2, s], [e2, n], [w, n], [w, s]]] };
          this.setArea(g, false).then(() => { this.commit(g); this.setTool("edit"); });
          return;
        }
      } else {
        this.kbPoints.push(p);
        this.onAnnounce(`Point ${this.kbPoints.length} added at ${fmt(p)}`);
      }
      this.drawKb();
    } else if (t === "poly" && (e.key === "f" || e.key === "F")) {
      e.preventDefault();
      if (this.kbPoints.length < 3) { this.onAnnounce("A polygon needs at least 3 points."); return; }
      const ring = [...this.kbPoints, this.kbPoints[0]];
      const g: Geo = { type: "Polygon", coordinates: [ring] };
      this.kbPoints = [];
      this.drawKb();
      this.setArea(g, false).then(() => { this.commit(g); this.setTool("edit"); });
    } else if ((t === "rect" || t === "poly") && e.key === "Backspace" && this.kbPoints.length) {
      e.preventDefault();
      this.kbPoints.pop();
      this.drawKb();
      this.onAnnounce(`Point removed. ${this.kbPoints.length} left.`);
    } else if ((t === "rect" || t === "poly") && e.key === "Escape") {
      this.kbPoints = [];
      this.drawKb();
      this.onAnnounce("Drawing cancelled.");
    } else if (t === "edit" && this.geom?.type === "Polygon") {
      const ring = this.geom.coordinates[0].slice(0, -1) as Pos[];
      if (e.key === "]" || e.key === "[") {
        e.preventDefault();
        this.kbVertex = (this.kbVertex + (e.key === "]" ? 1 : ring.length - 1)) % ring.length;
        this.kbPoints = [ring[this.kbVertex]];
        this.drawKb();
        this.onAnnounce(`Vertex ${this.kbVertex + 1} of ${ring.length} at ${fmt(ring[this.kbVertex])}. Alt+arrows move it.`);
      } else if (e.altKey && e.key.startsWith("Arrow") && this.kbPoints.length) {
        e.preventDefault();
        const step = e.shiftKey ? 0.1 : 0.01;
        const [x, y] = ring[this.kbVertex];
        const d: Record<string, Pos> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
        ring[this.kbVertex] = [+(x + d[e.key][0]).toFixed(5), +(y + d[e.key][1]).toFixed(5)];
        const g: Geo = { type: "Polygon", coordinates: [[...ring, ring[0]]] };
        this.kbPoints = [ring[this.kbVertex]];
        this.drawKb();
        this.setArea(g, false).then(() => { this.commit(g); this.draw.setMode("select"); });
        this.onAnnounce(`Vertex ${this.kbVertex + 1} moved to ${fmt(ring[this.kbVertex])}`);
      } else if ((e.key === "Delete") && this.kbPoints.length && ring.length > 3) {
        e.preventDefault();
        ring.splice(this.kbVertex, 1);
        const g: Geo = { type: "Polygon", coordinates: [[...ring, ring[0]]] };
        this.kbVertex = 0; this.kbPoints = []; this.drawKb();
        this.setArea(g, false).then(() => { this.commit(g); this.draw.setMode("select"); });
        this.onAnnounce(`Vertex removed. ${ring.length} left.`);
      }
    }
  }

  // ── street map: a dimmed sheet under the data, same map and camera ──
  /** Never moves the camera: the street layers join the same map, so the area sits on the same ground. */
  async setStreet(on: boolean): Promise<void> {
    await this.ready;
    if (this.failed) throw new Error("The map isn't available in this browser.");
    if (on && !this.street.loaded) await this.loadStreet();
    this.street.on = on;
    for (const l of this.map.getStyle().layers) {
      if (l.id.startsWith("st-")) this.map.setLayoutProperty(l.id, "visibility", on ? "visible" : "none");
    }
    this.updateSheet();
  }

  setStreetClip(clip: boolean): void {
    this.street.clip = clip;
    this.updateSheet();
  }

  private async loadStreet(): Promise<void> {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 8000);
    let style: { sources: Record<string, maplibregl.SourceSpecification>; layers: maplibregl.LayerSpecification[]; glyphs?: string; sprite?: string };
    try {
      style = await (await fetch("https://tiles.openfreemap.org/styles/positron", { signal: ctl.signal })).json();
    } catch {
      throw new Error("The street map needs a network connection (tiles.openfreemap.org).");
    } finally { clearTimeout(t); }
    if (style.glyphs) this.map.setGlyphs(style.glyphs);
    if (style.sprite) this.map.setSprite(style.sprite);
    for (const [id, src] of Object.entries(style.sources)) this.map.addSource(`st-${id}`, src);
    for (const layer of style.layers) {
      const l = { ...layer, id: `st-${layer.id}` } as maplibregl.LayerSpecification & { source?: string };
      if ("source" in layer && typeof layer.source === "string") l.source = `st-${layer.source}`;
      this.map.addLayer(l, "sheet-out");
    }
    this.street.loaded = true;
  }

  private updateSheet(): void {
    if (this.failed || !this.map.getSource("sheet-out")) return;
    const show = this.street.on ? "visible" : "none";
    this.map.setLayoutProperty("sheet-out", "visibility", show);
    this.map.setLayoutProperty("sheet-in", "visibility", show);
    const g = this.geom;
    const world: Pos[] = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
    const outers = g ? (g.type === "MultiPolygon" ? g.coordinates.map((p) => p[0]) : [g.coordinates[0]]) : [];
    const clip = this.street.clip && !!g;
    // outside the area: dimmed, or fully covered when clipped to the area
    (this.map.getSource("sheet-out") as GeoJSONSource).setData({ type: "Feature", properties: {},
      geometry: { type: "Polygon", coordinates: [world, ...(g ? outers : [])] as Pos[][] } });
    (this.map.getSource("sheet-in") as GeoJSONSource).setData(g ? { type: "Feature", properties: {}, geometry: g } : EMPTY);
    this.map.setPaintProperty("sheet-out", "fill-opacity", clip ? 1 : 0.45);
  }

  /** Share of the area in each country, from the bundled outlines (sampled on a grid; offline). */
  countryShares(g: Geo): { iso3: string; name: string; share: number }[] {
    const [w, s, e, n] = bboxOf(g);
    const inRing = (x: number, y: number, ring: number[][]) => {
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
      }
      return inside;
    };
    const inPoly = (x: number, y: number, geom: GeoJSON.Geometry) => {
      const polys = geom.type === "MultiPolygon" ? geom.coordinates : geom.type === "Polygon" ? [geom.coordinates] : [];
      return polys.some((p) => inRing(x, y, p[0]) && !p.slice(1).some((h) => inRing(x, y, h)));
    };
    const cands = this.countries.features.filter((f) => {
      const [cw, cs, ce, cn] = bboxOf(f.geometry);
      return cw <= e && ce >= w && cs <= n && cn >= s;
    });
    const counts = new Map<string, number>();
    let land = 0;
    const N = 40;
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
      const x = w + ((i + 0.5) / N) * (e - w), y = s + ((j + 0.5) / N) * (n - s);
      if (!inPoly(x, y, g)) continue;
      const hit = cands.find((f) => inPoly(x, y, f.geometry));
      if (!hit) continue;
      land++;
      const k = String(hit.properties?.iso3);
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    return [...counts.entries()].map(([iso3, c]) => ({ iso3, name: String(this.countries.features.find((f) => f.properties?.iso3 === iso3)?.properties?.name ?? iso3), share: c / land }))
      .sort((a, b) => b.share - a.share);
  }

  // ── country context ─────────────────────────────────
  async setCountry(iso3: string, fit: boolean): Promise<void> {
    await this.ready;
    if (this.failed) return;
    this.map.setFilter("country", ["==", ["get", "iso3"], iso3 || ""]);
    if (!fit || !iso3) return;
    const f = this.countries.features.find((x) => x.properties?.iso3 === iso3);
    if (f) this.fit(bboxOf(f.geometry));
  }

  fit(b: [number, number, number, number]): void {
    if (this.failed) return;
    this.map.fitBounds(b as LngLatBoundsLike, { padding: { top: Math.max(72, this.legendBottom() + 16), right: 72, bottom: 40, left: 72 }, duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 500, maxZoom: 11 });
  }

  zoomBy(d: number): void { if (!this.failed) this.map.zoomTo(this.map.getZoom() + d, { duration: 200 }); }
  fitArea(): void { if (this.geom) this.fit(bboxOf(this.geom)); }

  // ── fetched layers ─────────────────────────────────
  private freeDistricts = false;

  /** free: mark districts the polygon covers completely ("advice applies") apart from partial ones. */
  async setDistricts(fc: GeoJSON.FeatureCollection | null, free = false, labels = true): Promise<void> {
    await this.ready;
    if (this.failed) return;
    this.freeDistricts = free;
    (this.map.getSource("districts") as GeoJSONSource).setData(fc ?? EMPTY);
    this.map.setFilter("districts-line", free ? ["==", ["get", "fully_inside"], true] : null);
    this.districtMarkers.forEach((m) => m.remove());
    this.districtMarkers = (labels ? fc?.features ?? [] : []).filter((f) => f.properties?.name).map((f) => {
      const el = document.createElement("div");
      el.className = "district-label";
      const full = f.properties!.fully_inside === true;
      el.textContent = String(f.properties!.name) + (free ? (full ? " · advice applies" : " · partial: advice not applied") : "");
      if (free && !full) el.classList.add("partial");
      const m = new maplibregl.Marker({ element: el }).setLngLat(labelPoint(f.geometry));
      this.labelBox.set(m, bboxOf(f.geometry));
      return m;
    });
    this.applyVisibility();
  }

  /** Snap preview: touched districts (included or not, with their share) and the snapped outline. */
  async setSnap(districts: { unit_id: string; name: string | null; share_inside_area: number; included: boolean; geometry: GeoJSON.Geometry }[] | null,
                snapped: GeoJSON.Geometry | null): Promise<void> {
    await this.ready;
    if (this.failed) return;
    (this.map.getSource("snap-d") as GeoJSONSource).setData({ type: "FeatureCollection", features: (districts ?? []).map((d) => ({
      type: "Feature", properties: { unit_id: d.unit_id, name: d.name, included: d.included }, geometry: d.geometry })) });
    (this.map.getSource("snapped") as GeoJSONSource).setData(snapped ? { type: "Feature", properties: {}, geometry: snapped } : EMPTY);
    this.snapMarkers.forEach((m) => m.remove());
    this.snapMarkers = (districts ?? []).map((d) => {
      const el = document.createElement("div");
      el.className = `district-label snap ${d.included ? "in" : "out"}`;
      el.textContent = `${d.name ?? d.unit_id} · ${Math.round(d.share_inside_area * 100)}% · ${d.included ? "included" : "not included"}`;
      const m = new maplibregl.Marker({ element: el }).setLngLat(labelPoint(d.geometry));
      this.labelBox.set(m, bboxOf(d.geometry));
      return m;
    });
    this.applyVisibility();
  }

  async setFacilities(fc: GeoJSON.FeatureCollection | null): Promise<void> {
    await this.ready;
    if (this.failed) return;
    (this.map.getSource("facilities") as GeoJSONSource).setData(fc ?? EMPTY);
    this.clusterMarkers.forEach((m) => m.remove());
    this.clusterMarkers.clear();
    this.applyVisibility();
  }

  setVisible(layer: keyof AreaMap["visible"], on: boolean): void {
    this.visible[layer] = on;
    this.applyVisibility();
  }

  /** Labels only where they fit: a district must be drawn at least LABEL_MIN px on screen, so zoomed
   *  out the map stays readable and labels appear as you zoom in (the side list has every name). */
  private static readonly LABEL_MIN: [number, number] = [110, 36];
  private placeLabels(): void {
    if (this.failed) return;
    const [minW, minH] = AreaMap.LABEL_MIN;
    const fits = (m: maplibregl.Marker) => {
      const b = this.labelBox.get(m);
      if (!b) return true;
      const p1 = this.map.project([b[0], b[1]]), p2 = this.map.project([b[2], b[3]]);
      return Math.abs(p2.x - p1.x) >= minW && Math.abs(p2.y - p1.y) >= minH;
    };
    const place = (ms: maplibregl.Marker[], on: boolean) => ms.forEach((m) => (on && fits(m) ? m.addTo(this.map) : m.remove()));
    place(this.snapMarkers, this.visible.snap);
    place(this.districtMarkers, this.visible.districts);
  }

  private applyVisibility(): void {
    if (this.failed) return;
    const v = (on: boolean) => (on ? "visible" : "none");
    for (const id of ["area-halo", "area-line"]) this.map.setLayoutProperty(id, "visibility", v(this.visible.area));
    for (const id of ["districts-fill", "districts-line"]) this.map.setLayoutProperty(id, "visibility", v(this.visible.districts));
    for (const id of ["districts-full-fill", "districts-partial-line"]) this.map.setLayoutProperty(id, "visibility", v(this.visible.districts && this.freeDistricts));
    for (const id of ["snap-in-fill", "snap-out-fill", "snap-in-line", "snap-out-line", "snapped-line"]) this.map.setLayoutProperty(id, "visibility", v(this.visible.snap));
    this.placeLabels();
    this.map.setLayoutProperty("fac-pt", "visibility", v(this.visible.facilities));

    if (!this.visible.facilities) { this.clusterMarkers.forEach((m) => m.remove()); this.clusterMarkers.clear(); }
  }

  private updateClusters(): void {
    if (!this.visible.facilities || !this.map.getSource("facilities") || !this.map.isSourceLoaded("facilities")) return;
    const seen = new Set<number>();
    for (const f of this.map.querySourceFeatures("facilities")) {
      const p = f.properties as { cluster?: boolean; cluster_id?: number; point_count?: number };
      if (!p?.cluster || p.cluster_id == null || seen.has(p.cluster_id)) continue;
      seen.add(p.cluster_id);
      if (this.clusterMarkers.has(p.cluster_id)) continue;
      const el = document.createElement("button");
      el.className = "cluster";
      el.type = "button";
      el.textContent = String(p.point_count);
      el.setAttribute("aria-label", `${p.point_count} facilities. Zoom in`);
      const id = p.cluster_id;
      const at = (f.geometry as GeoJSON.Point).coordinates as Pos;
      el.addEventListener("click", async () => {
        const z = await (this.map.getSource("facilities") as GeoJSONSource).getClusterExpansionZoom(id);
        this.map.easeTo({ center: at, zoom: z });
      });
      this.clusterMarkers.set(id, new maplibregl.Marker({ element: el }).setLngLat(at).addTo(this.map));
    }
    for (const [id, m] of this.clusterMarkers) if (!seen.has(id)) { m.remove(); this.clusterMarkers.delete(id); }
  }
}
