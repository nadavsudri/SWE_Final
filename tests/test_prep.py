import csv
import json
import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from leg.data import Snapshot
from leg.prep import KM_PER_DEG, PrepParams, aggregate, build

RES = 0.01  # degrees per pixel; 10x10 pixels over lon 34.00-34.10, lat 30.90-31.00
AREA = box(34.0, 30.9, 34.1, 31.0)


def _snap(path, source):
    path.mkdir(parents=True, exist_ok=True)
    return Snapshot(path, {"source": source, "fetched_at": "2026-01-01T00:00:00+00:00"})


@pytest.fixture
def snaps(tmp_path):
    wp = _snap(tmp_path / "wp" / "s1", "worldpop")
    data = np.ones((1, 10, 10), dtype="float32")
    data[0, 0, 0] = -99999.0  # nodata in the NW corner
    with rasterio.open(wp.path / "population.tif", "w", driver="GTiff", height=10, width=10, count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(34.0, 31.0, RES, RES),
                       nodata=-99999.0) as dst:
        dst.write(data)

    bd = _snap(tmp_path / "bd" / "s1", "boundaries")  # only the WEST half is a district
    (bd.path / "districts.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "West", "unit_id": "w", "share_inside_area": 1.0},
         "geometry": mapping(box(34.0, 30.9, 34.05, 31.0))}]}))

    fc = _snap(tmp_path / "fc" / "s1", "osm_facilities")  # one facility in the SW corner pixel
    (fc.path / "facilities.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [34.005, 30.905]}}]}))
    return wp, bd, fc


def _read(out):
    cells = list(csv.DictReader(open(out / "cells.csv")))
    districts = list(csv.DictReader(open(out / "districts.csv")))
    return cells, districts, json.loads((out / "coverage.json").read_text()), json.loads((out / "meta.json").read_text())


def test_aggregate_sums_blocks_and_drops_nodata():
    band = np.array([[1, 2, 5], [3, -9, 5]], dtype=float)
    assert aggregate(band, 2, -9).tolist() == [[6.0, 10.0]]  # padded third column


def test_build_outputs(tmp_path, snaps):
    out = build(*snaps, AREA, tmp_path / "out", "isr_test", PrepParams(cell_km=1.0, radius_km=1.5))
    cells, districts, coverage, meta = _read(out)

    assert len(cells) == 100 and meta["totals"]["population"] == 99
    # east half belongs to no district -> reported, not silently dropped
    assert meta["unassigned"] == {"cells": 50, "population": 50}
    assert {c["district_id"] for c in cells} == {"0", "-1"}

    # candidates = populated cells; every candidate covers at least itself
    assert len(coverage) == 99 == meta["totals"]["candidates"]
    assert all(int(k) in v for k, v in coverage.items())
    assert "0" not in coverage  # the nodata cell is not a candidate

    # already covered: only cells within 1.5 km of the SW-corner facility
    covered = {int(c["cell_id"]) for c in cells if c["already_covered"] == "1"}
    sw = 90  # row 9, col 0
    assert sw in covered and 0 not in covered and 99 not in covered
    km_x = RES * KM_PER_DEG * math.cos(math.radians(30.95))
    for c in cells:
        d = math.hypot((float(c["lon"]) - 34.005) / RES * km_x, (float(c["lat"]) - 30.905) * KM_PER_DEG)
        assert (int(c["cell_id"]) in covered) == (d <= 1.5)

    west = districts[0]
    assert west["name"] == "West" and int(west["population"]) == 49 and west["existing_facilities"] == "1"
    assert float(west["coverage_pct"]) == pytest.approx(100 * int(west["covered_population"]) / 49, abs=0.1)
    assert meta["inputs"] == {"worldpop": "s1", "boundaries": "s1", "osm_facilities": "s1"}


def test_coarser_cells_aggregate_population(tmp_path, snaps):
    out = build(*snaps, AREA, tmp_path / "out", "isr_test", PrepParams(cell_km=2.0, radius_km=1.0))
    cells, _, _, meta = _read(out)
    assert len(cells) == 25 and meta["totals"]["population"] == 99
    assert meta["real_cell_km"] == pytest.approx(2 * RES * KM_PER_DEG * math.cos(math.radians(30.95)), abs=0.01)


def test_all_cells_as_candidates(tmp_path, snaps):
    out = build(*snaps, AREA, tmp_path / "out", "isr_test", PrepParams(candidates="all"))
    assert len(_read(out)[2]) == 100


@pytest.mark.parametrize("kw", [{"cell_km": 0}, {"radius_km": -1}, {"candidates": "some"}])
def test_bad_params(kw):
    with pytest.raises(ValueError):
        PrepParams(**kw)


def test_area_outside_raster(tmp_path, snaps):
    with pytest.raises(ValueError, match="No grid cells"):
        build(*snaps, box(40, 40, 41, 41), tmp_path / "out", "x", PrepParams())
