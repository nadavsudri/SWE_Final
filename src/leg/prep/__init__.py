"""Preprocessing: fetched snapshots -> the files the algorithm reads.

Output (data/processed/<area_id>/<run_id>/):
  cells.csv      cell_id, lon, lat, population, district_id, is_candidate, already_covered
  coverage.json  {candidate_cell_id: [cell_ids within reach]}
  districts.csv  per district: population, already covered population and %, cells, candidates,
                 existing facilities
  meta.json      input snapshot ids, parameters, totals, unassigned cells

Coverage rule (v1): straight-line distance <= radius_km. A cell is `already_covered` if an
existing facility lies within radius_km of its center.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from scipy.spatial import cKDTree
import shapely
from shapely import STRtree
from shapely.geometry import shape

from leg.data import Snapshot

KM_PER_DEG = 111.32


@dataclass(frozen=True)
class PrepParams:
    cell_km: float = 1.0          # target cell size
    radius_km: float = 10.0       # coverage radius (~2h walk, as in the paper)
    candidates: str = "populated"  # "populated" (population > 0) | "all"

    def __post_init__(self):
        if self.cell_km <= 0 or self.radius_km <= 0:
            raise ValueError("cell_km and radius_km must be > 0")
        if self.candidates not in ("populated", "all"):
            raise ValueError("candidates must be 'populated' or 'all'")


# ---------------------------------------------------------------- grid
def aggregate(band: np.ndarray, factor: int, nodata) -> np.ndarray:
    """Sum blocks of factor x factor pixels; nodata / negative / NaN count as 0."""
    a = band.astype("float64")
    bad = ~np.isfinite(a) | (a < 0)
    if nodata is not None:
        bad |= a == nodata
    a[bad] = 0.0
    h, w = a.shape
    H, W = math.ceil(h / factor), math.ceil(w / factor)
    padded = np.zeros((H * factor, W * factor))
    padded[:h, :w] = a
    return padded.reshape(H, factor, W, factor).sum(axis=(1, 3))


def build_grid(population_tif: Path, area_geom, cell_km: float):
    """Return (lon, lat, pop) arrays of grid cells whose center is inside the area,
    plus the real cell size in km."""
    with rasterio.open(population_tif) as src:
        band, nodata, t = src.read(1), src.nodata, src.transform
    res_deg = abs(t.a)
    lat_mid = t.f + t.e * band.shape[0] / 2
    res_km = res_deg * KM_PER_DEG * math.cos(math.radians(lat_mid))  # E-W size of a pixel
    factor = max(1, round(cell_km / res_km))
    grid = aggregate(band, factor, nodata)
    cw, ch = t.a * factor, t.e * factor  # cell size in degrees (ch negative)
    rows, cols = np.indices(grid.shape)
    lon = t.c + (cols + 0.5) * cw
    lat = t.f + (rows + 0.5) * ch
    inside = shapely.intersects_xy(area_geom, lon.ravel(), lat.ravel())
    real_km = factor * res_km
    return lon.ravel()[inside], lat.ravel()[inside], grid.ravel()[inside], real_km


def _assign(tree: STRtree, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Index of the polygon containing each point (first match), -1 if none."""
    out = np.full(len(lon), -1, dtype=int)
    pts_idx, poly_idx = tree.query(shapely.points(lon, lat), predicate="intersects")
    first = np.unique(pts_idx, return_index=True)[1]
    out[pts_idx[first]] = poly_idx[first]
    return out


def _xy_km(lon: np.ndarray, lat: np.ndarray, lat0: float) -> np.ndarray:
    """Local equirectangular projection to km (fine for areas of a few hundred km)."""
    return np.column_stack([lon * KM_PER_DEG * math.cos(math.radians(lat0)), lat * KM_PER_DEG])


# ---------------------------------------------------------------- main step
def build(worldpop: Snapshot, boundaries: Snapshot, facilities: Snapshot, area_geom,
          out_root: Path | str, area_id: str, params: PrepParams = PrepParams()) -> Path:
    lon, lat, pop, real_km = build_grid(worldpop.path / "population.tif", area_geom, params.cell_km)
    n = len(pop)
    if n == 0:
        raise ValueError("No grid cells inside the area")

    # districts: cell center -> containing district
    feats = json.loads((boundaries.path / "districts.geojson").read_text())["features"]
    geoms = [shape(f["geometry"]) for f in feats]
    tree = STRtree(geoms)
    district = _assign(tree, lon, lat)

    # coverage
    lat0 = float(np.mean(lat))
    xy = _xy_km(lon, lat, lat0)
    tree_cells = cKDTree(xy)
    fac = [f["geometry"]["coordinates"] for f in
           json.loads((facilities.path / "facilities.geojson").read_text())["features"]]
    covered = np.zeros(n, dtype=bool)
    fac_district = np.full(len(fac), -1, dtype=int)
    if fac:
        fxy = _xy_km(np.array([c[0] for c in fac]), np.array([c[1] for c in fac]), lat0)
        for hits in tree_cells.query_ball_point(fxy, params.radius_km):
            covered[hits] = True
        fac_district = _assign(tree, np.array([c[0] for c in fac]), np.array([c[1] for c in fac]))

    is_cand = pop > 0 if params.candidates == "populated" else np.ones(n, dtype=bool)
    cand_idx = np.flatnonzero(is_cand)
    reach = tree_cells.query_ball_point(xy[cand_idx], params.radius_km)
    coverage = {int(c): sorted(int(v) for v in r) for c, r in zip(cand_idx, reach)}

    # write
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = Path(out_root) / area_id / run_id
    out.mkdir(parents=True)
    with open(out / "cells.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell_id", "lon", "lat", "population", "district_id", "is_candidate", "already_covered"])
        for i in range(n):
            w.writerow([i, round(lon[i], 6), round(lat[i], 6), round(float(pop[i]), 2),
                        int(district[i]), int(is_cand[i]), int(covered[i])])
    (out / "coverage.json").write_text(json.dumps(coverage, separators=(",", ":")))

    rows = []
    for j, f in enumerate(feats):
        m = district == j
        dp, dc = float(pop[m].sum()), float(pop[m & covered].sum())
        rows.append({"district_id": j, "unit_id": f["properties"].get("unit_id"),
                     "name": f["properties"].get("name"),
                     "population": round(dp), "covered_population": round(dc),
                     "coverage_pct": round(100 * dc / dp, 1) if dp else None,
                     "cells": int(m.sum()), "candidates": int((m & is_cand).sum()),
                     "existing_facilities": int((fac_district == j).sum()),
                     "share_inside_area": f["properties"].get("share_inside_area")})
    with open(out / "districts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["district_id"])
        w.writeheader()
        w.writerows(rows)

    un = district == -1
    meta = {
        "area_id": area_id, "created_at": run_id, "params": asdict(params),
        "real_cell_km": round(real_km, 3),
        "inputs": {s.manifest["source"]: s.id for s in (worldpop, boundaries, facilities)},
        "totals": {"cells": n, "candidates": int(is_cand.sum()), "districts": len(feats),
                   "population": round(float(pop.sum())),
                   "already_covered_population": round(float(pop[covered].sum())),
                   "existing_facilities": len(fac)},
        "unassigned": {"cells": int(un.sum()), "population": round(float(pop[un].sum()))},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return out
