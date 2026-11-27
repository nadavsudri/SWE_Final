"""Preprocessing: fetched snapshots -> the files the algorithm reads, in the paper's format.

The paper's code (Choo et al. 2026, github.com/yohayt/OHCE, reused by LEG) reads two files per
region; we write the same two, with the same columns, so one loader runs on both:

  population.csv       cell, lat, lon, ADM1, ADM2, ADM3, population, year
                       one row per populated cell (>= 10 people) per year
  pairwise_costs.csv   cell_i, cell_j, lat_i, lon_i, lat_j, lon_j,
                       ADM1_i, ADM2_i, ADM3_i, ADM1_j, ADM2_j, ADM3_j, distance
                       walking minutes between cells at most `window` cells apart (|dr|+|dc|),
                       i < j, computed from i over the friction map (least-cost path)

plus our own files:

  existing.csv         cell, lat, lon, source, name, type, snapped_km   (real facilities, the paper
                       used 5 random cells per district because its data is not public)
  districts.csv        ADM3, ADM2, ADM1, unit_id, population, covered_population, coverage_pct,
                       cells, existing_facilities, share_inside_area, fully_inside
  meta.json            inputs, settings, grid, totals, timings

Grid: the pixels of the Malaria Atlas friction map (30 arc-seconds, ~0.93 km), as in the paper.
`cell` = global row * 43200 + global column on that grid, so ids are stable across areas.
ADM3 = the planning district (the level chosen for the area), ADM2/ADM1 = the two coarser levels.

One difference from the paper's code, on purpose: the paper's code feeds 1/friction to the path
search; we use friction itself (minutes per metre) times metres, which gives walking minutes, the
quantity the paper describes (a facility covers cells within a two-hour walk).
"""
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import rasterio
import shapely
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import shape
from skimage.graph import MCP_Geometric

from leg.data import Snapshot

M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0
GRID_ORIGIN = (-180.0, 85.0)  # MAP friction rasters span lon -180..180, lat -60..85

POPULATION_COLS = ["cell", "lat", "lon", "ADM1", "ADM2", "ADM3", "population", "year"]
PAIR_COLS = ["cell_i", "cell_j", "lat_i", "lon_i", "lat_j", "lon_j",
             "ADM1_i", "ADM2_i", "ADM3_i", "ADM1_j", "ADM2_j", "ADM3_j", "distance"]

Progress = Callable[[str, int, int], None]  # (stage, done, total)
STAGES = ["population", "districts", "travel_times", "facilities", "write"]


@dataclass(frozen=True)
class PrepParams:
    min_population: float = 10.0   # paper: cells with fewer people are dropped
    window: int = 10               # paper: pairs at most 10 cells apart (Manhattan)
    pad: int = 5                   # extra cells around the window so paths can bend
    max_minutes: float = 120.0     # paper: a facility covers cells within a two-hour walk
    keep_minutes: float = 120.0    # pairs written to pairwise_costs.csv (>= max_minutes)
    max_snap_km: float = 5.0       # existing facility -> nearest populated cell, at most this far

    def __post_init__(self):
        if self.min_population < 0 or self.window < 1 or self.pad < 0:
            raise ValueError("min_population >= 0, window >= 1, pad >= 0")
        if self.max_minutes <= 0 or self.keep_minutes < self.max_minutes:
            raise ValueError("max_minutes must be > 0 and keep_minutes >= max_minutes")
        if self.max_snap_km < 0:
            raise ValueError("max_snap_km must be >= 0")


@dataclass
class Grid:
    """The friction raster: cost per pixel (minutes per metre, inf = impassable) and its geometry."""
    cost: np.ndarray
    left: float
    top: float
    res: float

    @property
    def shape(self):
        return self.cost.shape

    def centers(self, rows, cols):
        return self.left + (cols + 0.5) * self.res, self.top - (rows + 0.5) * self.res

    def rowcol(self, lon, lat):
        return (np.floor((self.top - np.asarray(lat)) / self.res).astype(int),
                np.floor((np.asarray(lon) - self.left) / self.res).astype(int))

    def cell_ids(self, rows, cols):
        width = round(360 / self.res)
        r0 = round((GRID_ORIGIN[1] - self.top) / self.res)
        c0 = round((self.left - GRID_ORIGIN[0]) / self.res)
        return (r0 + np.asarray(rows)).astype(np.int64) * width + (c0 + np.asarray(cols))


def read_friction(path: Path) -> Grid:
    with rasterio.open(path) as src:
        a = src.read(1).astype("float64")
        nodata, t = src.nodata, src.transform
    bad = ~np.isfinite(a) | (a <= 0)
    if nodata is not None:
        bad |= a == nodata
    a[bad] = np.inf
    return Grid(a, t.c, t.f, abs(t.a))


def population_on_grid(tif: Path, grid: Grid) -> np.ndarray:
    """Sum the ~100 m WorldPop pixels into the friction pixels that contain their centers."""
    with rasterio.open(tif) as src:
        band, nodata, t = src.read(1).astype("float64"), src.nodata, src.transform
    ok = np.isfinite(band) & (band > 0)
    if nodata is not None:
        ok &= band != nodata
    rr, cc = np.nonzero(ok)
    lon = t.c + (cc + 0.5) * t.a
    lat = t.f + (rr + 0.5) * t.e
    gr, gc = grid.rowcol(lon, lat)
    h, w = grid.shape
    inb = (gr >= 0) & (gr < h) & (gc >= 0) & (gc < w)
    out = np.zeros(grid.shape)
    np.add.at(out, (gr[inb], gc[inb]), band[rr[inb], cc[inb]])
    return out


def _year(s: Snapshot) -> int:
    return int(s.manifest.get("params", {}).get("year", 0))


def _features(s: Snapshot, name="districts.geojson") -> list[dict]:
    return json.loads((s.path / name).read_text())["features"]


def district_labels(districts: list[dict], parents: list[list[dict]], iso3: str) -> list[tuple[str, str, str]]:
    """(ADM1, ADM2, ADM3) per district. `parents` = coarser levels' features, coarsest first."""
    trees = [(STRtree([shape(f["geometry"]) for f in fs]), fs) for fs in parents]
    out = []
    for f in districts:
        pt = shape(f["geometry"]).representative_point()
        names = []
        for tree, fs in trees:
            hit = tree.query(pt, predicate="intersects")
            names.append(fs[int(hit[0])]["properties"].get("name") or "" if len(hit) else "")
        names = names[-2:]
        adm1 = names[0] if names else iso3
        adm2 = names[1] if len(names) > 1 else ""
        out.append((adm1 or iso3, adm2, f["properties"].get("name") or f["properties"].get("unit_id") or "?"))
    seen: dict[tuple, int] = {}
    for i, lab in enumerate(out):  # same name and parents twice: add the unit id to both
        if lab in seen:
            for k in (seen[lab], i):
                a1, a2, a3 = out[k]
                out[k] = (a1, a2, f"{a3} ({districts[k]['properties'].get('unit_id')})")
        seen[lab] = i
    return out


def travel_minutes(grid: Grid, rows: np.ndarray, cols: np.ndarray, window: int, pad: int,
                   keep: float, progress: Progress | None = None):
    """Walking minutes from each listed cell to every listed cell j > i within `window` (Manhattan).
    Returns arrays (i, j, minutes) of the pairs with minutes <= keep."""
    h, w = grid.shape
    index = np.full(grid.shape, -1, dtype=np.int64)
    index[rows, cols] = np.arange(len(rows))
    ii, jj, dd = [], [], []
    R = window + pad
    step = max(1, len(rows) // 200)
    for i, (r, c) in enumerate(zip(rows, cols)):
        if progress and i % step == 0:
            progress("travel_times", i, len(rows))
        if not np.isfinite(grid.cost[r, c]):
            continue
        r0, r1, c0, c1 = max(r - R, 0), min(r + R + 1, h), max(c - R, 0), min(c + R + 1, w)
        _, lat = grid.centers(r, c)
        dy = grid.res * M_PER_DEG_LAT
        dx = grid.res * M_PER_DEG_LON * math.cos(math.radians(lat))
        costs, _ = MCP_Geometric(grid.cost[r0:r1, c0:c1], sampling=(dy, dx)).find_costs([(r - r0, c - c0)])
        sub = index[r0:r1, c0:c1]
        lr, lc = np.nonzero(sub > i)
        near = np.abs(lr + r0 - r) + np.abs(lc + c0 - c) <= window
        lr, lc = lr[near], lc[near]
        d = costs[lr, lc]
        keep_m = np.isfinite(d) & (d <= keep)
        ii.append(np.full(keep_m.sum(), i))
        jj.append(sub[lr[keep_m], lc[keep_m]])
        dd.append(d[keep_m])
    if progress:
        progress("travel_times", len(rows), len(rows))
    cat = lambda xs, t: np.concatenate(xs).astype(t) if xs else np.zeros(0, t)
    return cat(ii, np.int64), cat(jj, np.int64), cat(dd, float)


def _xy_km(lon, lat, lat0):
    return np.column_stack([np.asarray(lon) * M_PER_DEG_LON / 1000 * math.cos(math.radians(lat0)),
                            np.asarray(lat) * M_PER_DEG_LAT / 1000])


def build(worldpop: Snapshot | list[Snapshot], boundaries: Snapshot, facilities: Snapshot | list[Snapshot],
          friction: Snapshot, area_geom, out_root: Path | str, area_id: str,
          params: PrepParams = PrepParams(), parents: list[Snapshot] | None = None,
          iso3: str | None = None, progress: Progress | None = None) -> Path:
    """Write population.csv, pairwise_costs.csv, existing.csv, districts.csv and meta.json.
    `worldpop` may be several snapshots (one per year); the first year is the planning year.
    `parents` = boundaries snapshots of the coarser levels, coarsest first (fills ADM1/ADM2)."""
    iso3 = iso3 or area_id.split("_")[0]
    timings: dict[str, float] = {}
    clock = time.perf_counter()

    def stage(name):
        nonlocal clock
        now = time.perf_counter()
        timings[name] = round(now - clock, 2)
        clock = now

    def report(s, done=0, total=1):
        if progress:
            progress(s, done, total)

    # ---- population on the friction grid, per year
    report("population")
    grid = read_friction(friction.path / "friction.tif")
    years = sorted(worldpop if isinstance(worldpop, list) else [worldpop], key=_year)
    h, w = grid.shape
    rr, cc = np.indices(grid.shape)
    lon_all, lat_all = grid.centers(rr.ravel(), cc.ravel())
    inside = shapely.intersects_xy(area_geom, lon_all, lat_all).reshape(grid.shape)
    pops = {}
    for s in years:
        p = population_on_grid(s.path / "population.tif", grid)
        p[~inside] = 0
        pops[_year(s)] = p
    year_list = list(pops)
    plan_year = year_list[0]
    populated = {y: p >= params.min_population for y, p in pops.items()}
    in_all = np.logical_and.reduce(list(populated.values()))
    rows, cols = np.nonzero(in_all)
    if len(rows) == 0:
        raise ValueError(f"No cells with at least {params.min_population:g} people inside the area")
    lon, lat = grid.centers(rows, cols)
    cell_id = grid.cell_ids(rows, cols)
    stage("population")

    # ---- districts: cell center -> containing district; labels with parent names
    report("districts")
    feats = _features(boundaries)
    tree = STRtree([shape(f["geometry"]) for f in feats])
    labels = district_labels(feats, [_features(s) for s in (parents or [])], iso3)
    dist = np.full(len(rows), -1, dtype=int)
    pi, di = tree.query(shapely.points(lon, lat), predicate="intersects")
    first = np.unique(pi, return_index=True)[1]
    dist[pi[first]] = di[first]
    adm = [labels[d] if d >= 0 else ("", "", "") for d in dist]
    stage("districts")

    # ---- walking minutes between nearby cells
    pi, pj, pd = travel_minutes(grid, rows, cols, params.window, params.pad, params.keep_minutes, progress)
    stage("travel_times")

    # ---- existing facilities -> nearest populated cell
    report("facilities")
    lat0 = float(np.mean(lat))
    kd = cKDTree(_xy_km(lon, lat, lat0))
    fac_snaps = facilities if isinstance(facilities, list) else [facilities]
    existing, dropped = [], 0
    for snap in fac_snaps:
        src = snap.manifest.get("source", snap.path.parent.name)
        for f in _features(snap, "facilities.geojson"):
            flon, flat = f["geometry"]["coordinates"][:2]
            km, k = kd.query(_xy_km([flon], [flat], lat0)[0])
            if km > params.max_snap_km:
                dropped += 1
                continue
            pr = f["properties"]
            existing.append({"idx": int(k), "source": src, "name": pr.get("name") or "",
                             "type": pr.get("facility_type") or pr.get("amenity") or pr.get("healthcare")
                             or pr.get("emergency") or "", "snapped_km": round(float(km), 2)})
    has_fac = np.zeros(len(rows), bool)
    has_fac[[e["idx"] for e in existing]] = True
    covered = has_fac.copy()
    close = pd <= params.max_minutes
    covered[pj[close & has_fac[pi]]] = True
    covered[pi[close & has_fac[pj]]] = True
    stage("facilities")

    # ---- write
    report("write")
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = Path(out_root) / area_id / run_id
    out.mkdir(parents=True)
    r6 = lambda x: round(float(x), 6)
    with open(out / "population.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(POPULATION_COLS)
        for y in year_list:
            for k in range(len(rows)):
                wr.writerow([int(cell_id[k]), r6(lat[k]), r6(lon[k]), *adm[k],
                             round(float(pops[y][rows[k], cols[k]]), 3), y])
    with open(out / "pairwise_costs.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(PAIR_COLS)
        for a, b, d in zip(pi, pj, pd):
            wr.writerow([int(cell_id[a]), int(cell_id[b]), r6(lat[a]), r6(lon[a]), r6(lat[b]), r6(lon[b]),
                         *adm[a], *adm[b], round(float(d), 3)])
    with open(out / "existing.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["cell", "lat", "lon", "source", "name", "type", "snapped_km"])
        for e in existing:
            k = e["idx"]
            wr.writerow([int(cell_id[k]), r6(lat[k]), r6(lon[k]), e["source"], e["name"], e["type"], e["snapped_km"]])

    pop = pops[plan_year][rows, cols]
    drows = []
    for j, f in enumerate(feats):
        m = dist == j
        dp, dc = float(pop[m].sum()), float(pop[m & covered].sum())
        p = f["properties"]
        drows.append({"ADM3": labels[j][2], "ADM2": labels[j][1], "ADM1": labels[j][0],
                      "unit_id": p.get("unit_id"), "population": round(dp), "covered_population": round(dc),
                      "coverage_pct": round(100 * dc / dp, 1) if dp else "", "cells": int(m.sum()),
                      "existing_facilities": int(has_fac[m].sum()),
                      "share_inside_area": p.get("share_inside_area"),
                      # expert advice applies only to districts fully inside the area (free-polygon mode)
                      "fully_inside": int(bool(p.get("fully_inside", p.get("share_inside_area") == 1)))})
    with open(out / "districts.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(drows[0]) if drows else ["ADM3"])
        wr.writeheader()
        wr.writerows(drows)

    un = dist == -1
    stage("write")
    meta = {
        "area_id": area_id, "created_at": run_id, "params": asdict(params),
        "years": year_list, "planning_year": plan_year, "iso3": iso3,
        "grid": {"source": "Malaria Atlas friction surface", "res_deg": grid.res,
                 "cell_id": "global_row * 43200 + global_col (origin lon -180, lat 85)",
                 "distance_unit": "walking minutes"},
        "inputs": {s.manifest.get("source", "?"): s.id for s in (boundaries, friction, *fac_snaps)}
                  | {f"worldpop_{_year(s)}": s.id for s in years}
                  | {f"parent_{i}": s.id for i, s in enumerate(parents or [])},
        "totals": {"cells": int(len(rows)), "pairs": int(len(pi)), "districts": len(feats),
                   "population": round(float(pop.sum())),
                   "covered_population": round(float(pop[covered].sum())),
                   "existing_facilities": len(existing)},
        "unassigned": {"cells": int(un.sum()), "population": round(float(pop[un].sum()))},
        "dropped_facilities": dropped,
        "seconds": timings,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    report("write", 1, 1)
    return out
