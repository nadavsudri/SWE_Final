"""Preprocessing in the paper's format, on a 10 x 10 friction grid with known walking times."""
import csv
import json
import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from leg.algo import Instance, coverage
from leg.data import Snapshot
from leg.prep import (M_PER_DEG_LAT, M_PER_DEG_LON, PAIR_COLS, POPULATION_COLS, STAGES, PrepParams,
                      build)
from leg.prep.run import prepare

RES = 1 / 120               # MAP grid: 30 arc-seconds
FINE = RES / 10             # "WorldPop" pixels: 10 x 10 per cell
LEFT, TOP = 34.0, 31.0
AREA = box(LEFT, TOP - 10 * RES, LEFT + 10 * RES, TOP)
FRICTION = 0.012            # minutes per metre = 5 km/h


def _snap(path, source, params=None, fetched="2026-01-01T00:00:00+00:00"):
    path.mkdir(parents=True, exist_ok=True)
    m = {"source": source, "fetched_at": fetched, "params": params or {}}
    (path / "manifest.json").write_text(json.dumps(m))
    return Snapshot(path, m)


def _tif(path, data, res, nodata=-99999.0):
    with rasterio.open(path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1], count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(LEFT, TOP, res, res),
                       nodata=nodata) as dst:
        dst.write(data.astype("float32")[None])


def _fc(feats):
    return json.dumps({"type": "FeatureCollection", "features": feats})


def _poly(name, uid, geom, **props):
    return {"type": "Feature", "properties": {"name": name, "unit_id": uid, **props}, "geometry": mapping(geom)}


def make_inputs(base, impassable=None, year=2026):
    wp = _snap(base / "worldpop" / f"wp{year}", "worldpop", {"year": year})
    pop = np.full((100, 100), 0.2)          # 20 people per cell
    pop[0:10, 0:10] = 0.05                  # NW cell: 5 people -> dropped (< 10)
    _tif(wp.path / "population.tif", pop, FINE)

    fr = _snap(base / "friction" / "f1", "friction", {"mode": "walking"})
    f = np.full((10, 10), FRICTION)
    if impassable:
        f[impassable] = -9999.0             # nodata = impassable
    _tif(fr.path / "friction.tif", f, RES, nodata=-9999.0)

    bd = _snap(base / "boundaries" / "b1", "boundaries", {"provider": "geoboundaries", "levels": ["ADM3"]})
    west, east = box(LEFT, TOP - 10 * RES, LEFT + 5 * RES, TOP), box(LEFT + 5 * RES, TOP - 10 * RES, LEFT + 10 * RES, TOP)
    feats = [_poly("West", "w", west, share_inside_area=1.0), _poly("East", "e", east, share_inside_area=1.0)]
    (bd.path / "districts.geojson").write_text(_fc(feats))
    (bd.path / "districts_full.geojson").write_text(_fc(feats))

    zone = _snap(base / "boundaries" / "z1", "boundaries", {"provider": "geoboundaries", "levels": ["ADM2"]})
    (zone.path / "districts_full.geojson").write_text(_fc([_poly("Zone", "z", AREA.buffer(0.1))]))
    (zone.path / "districts.geojson").write_text(_fc([_poly("Zone", "z", AREA.buffer(0.1))]))
    region = _snap(base / "boundaries" / "r1", "boundaries", {"provider": "geoboundaries", "levels": ["ADM1"]})
    (region.path / "districts_full.geojson").write_text(_fc([_poly("Region", "r", AREA.buffer(0.2))]))
    (region.path / "districts.geojson").write_text(_fc([_poly("Region", "r", AREA.buffer(0.2))]))

    fc = _snap(base / "osm_facilities" / "o1", "osm_facilities")
    sw = [LEFT + 0.5 * RES, TOP - 9.5 * RES]  # center of the SW cell (row 9, col 0)
    far = [LEFT + 2, TOP - 2]                 # far outside: dropped
    (fc.path / "facilities.geojson").write_text(_fc([
        {"type": "Feature", "properties": {"name": "SW clinic", "amenity": "clinic"},
         "geometry": {"type": "Point", "coordinates": sw}},
        {"type": "Feature", "properties": {"name": "Far"}, "geometry": {"type": "Point", "coordinates": far}}]))
    return wp, bd, fc, fr, [region, zone]


def read_csv(p):
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def minutes_east(lat):
    return FRICTION * RES * M_PER_DEG_LON * math.cos(math.radians(lat))


def test_paper_format(tmp_path):
    wp, bd, fc, fr, parents = make_inputs(tmp_path / "raw")
    seen = []
    out = build(wp, bd, [fc], fr, AREA, tmp_path / "out", "ETH_test_1", PrepParams(max_minutes=30),
                parents=parents, iso3="ETH", progress=lambda s, d, t: seen.append(s))
    pop, pairs = read_csv(out / "population.csv"), read_csv(out / "pairwise_costs.csv")
    assert list(pop[0]) == POPULATION_COLS and list(pairs[0]) == PAIR_COLS

    # 99 cells: the NW cell (5 people) is dropped; 20 people each; one year
    assert len(pop) == 99 and {r["year"] for r in pop} == {"2026"}
    assert all(abs(float(r["population"]) - 20) < 1e-6 for r in pop)
    assert {(r["ADM1"], r["ADM2"], r["ADM3"]) for r in pop} == {("Region", "Zone", "West"), ("Region", "Zone", "East")}

    # global cell ids: row * 43200 + col on the 30" grid from lon -180, lat 85
    r0, c0 = round((85 - TOP) / RES), round((LEFT + 180) / RES)
    ids = {int(r["cell"]) for r in pop}
    assert (r0 + 9) * 43200 + c0 in ids and r0 * 43200 + c0 not in ids

    # pairs: i < j, at most 10 cells apart, and walking minutes match the friction
    cells = {int(r["cell"]): ((int(r["cell"]) // 43200) - r0, (int(r["cell"]) % 43200) - c0) for r in pop}
    expected = {(a, b) for a in cells for b in cells
                if a < b and sum(abs(x - y) for x, y in zip(cells[a], cells[b])) <= 10}
    got = {(int(r["cell_i"]), int(r["cell_j"])) for r in pairs}
    assert got == expected
    d = {(int(r["cell_i"]), int(r["cell_j"])): float(r["distance"]) for r in pairs}
    a = (r0 + 5) * 43200 + c0 + 3
    lat = TOP - 5.5 * RES
    assert d[(a, a + 1)] == pytest.approx(minutes_east(lat), rel=1e-3)                  # one cell east
    assert d[(a, a + 43200)] == pytest.approx(FRICTION * RES * M_PER_DEG_LAT, rel=1e-3)  # one cell south
    assert d[(a, a + 3)] == pytest.approx(3 * minutes_east(lat), rel=1e-3)

    # existing: the SW clinic sits in its own cell; the far one is dropped
    ex = read_csv(out / "existing.csv")
    assert [(int(r["cell"]), r["name"], r["type"]) for r in ex] == [((r0 + 9) * 43200 + c0, "SW clinic", "clinic")]
    meta = json.loads((out / "meta.json").read_text())
    assert meta["dropped_facilities"] == 1 and meta["planning_year"] == 2026

    # districts: West holds the clinic; covered = cells within 30 min of it
    dist = {r["ADM3"]: r for r in read_csv(out / "districts.csv")}
    assert dist["West"]["existing_facilities"] == "1" and dist["East"]["existing_facilities"] == "0"
    assert int(dist["West"]["population"]) == 49 * 20
    assert int(dist["West"]["cells"]) == 49 and int(dist["East"]["cells"]) == 50
    assert 0 < int(dist["West"]["covered_population"]) < int(dist["West"]["population"])
    assert seen[0] == "population" and set(seen) == set(STAGES)


def test_impassable_cell_has_no_pairs(tmp_path):
    wp, bd, fc, fr, parents = make_inputs(tmp_path / "raw", impassable=(5, 5))
    out = build(wp, bd, [fc], fr, AREA, tmp_path / "out", "ETH_t", parents=parents)
    pairs = read_csv(out / "pairwise_costs.csv")
    r0, c0 = round((85 - TOP) / RES), round((LEFT + 180) / RES)
    blocked = (r0 + 5) * 43200 + c0 + 5
    assert not [r for r in pairs if blocked in (int(r["cell_i"]), int(r["cell_j"]))]
    assert blocked in {int(r["cell"]) for r in read_csv(out / "population.csv")}  # still a cell


def test_no_parents_uses_country_code(tmp_path):
    wp, bd, fc, fr, _ = make_inputs(tmp_path / "raw")
    out = build(wp, bd, [fc], fr, AREA, tmp_path / "out", "ETH_t", iso3="ETH")
    assert {(r["ADM1"], r["ADM2"]) for r in read_csv(out / "population.csv")} == {("ETH", "")}


def test_multi_year(tmp_path):
    raw = tmp_path / "raw"
    wp, bd, fc, fr, parents = make_inputs(raw)
    wp27, *_ = make_inputs(raw, year=2027)
    out = build([wp27, wp], bd, [fc], fr, AREA, tmp_path / "out", "ETH_t", parents=parents)
    pop = read_csv(out / "population.csv")
    assert [r["year"] for r in pop[:1]] == ["2026"] and len(pop) == 2 * 99
    assert json.loads((out / "meta.json").read_text())["years"] == [2026, 2027]


def test_no_populated_cells(tmp_path):
    wp, bd, fc, fr, _ = make_inputs(tmp_path / "raw")
    with pytest.raises(ValueError, match="No cells"):
        build(wp, bd, [fc], fr, AREA, tmp_path / "out", "ETH_t", PrepParams(min_population=1000))


def test_params_checked():
    with pytest.raises(ValueError):
        PrepParams(max_minutes=120, keep_minutes=60)


# ---------------------------------------------------------------- the algorithm reads it
def test_instance_loads_prep_output(tmp_path):
    wp, bd, fc, fr, parents = make_inputs(tmp_path / "raw")
    out = build(wp, bd, [fc], fr, AREA, tmp_path / "out", "ETH_t", PrepParams(max_minutes=30), parents=parents)
    inst = Instance.load(out, max_minutes=30)
    assert inst.n_cells == inst.n_candidates == 99 and len(inst.districts()) == 2
    assert sorted(inst.district_names.values()) == ["East", "West"]
    covered = inst.population.sum() - inst.weight.sum()
    meta = json.loads((out / "meta.json").read_text())
    assert covered == pytest.approx(meta["totals"]["covered_population"], abs=1)
    # a site covers itself plus the cells within 30 minutes (2 east/west, 2 north/south, ...)
    assert coverage(inst, [50]) > 20


def test_instance_reads_paper_files(tmp_path):
    """The paper's own files: NaN ADM1 rows are skipped, pairs over 120 min ignored, two years."""
    pop = tmp_path / "population_1.csv"
    pop.write_text("cell,lat,lon,ADM1,ADM2,ADM3,population,year\n"
                   "1,9.0,40.0,Afar,Z1,W1,100.0,2026\n2,9.0,40.01,Afar,Z1,W1,50.0,2026\n"
                   "3,9.0,40.02,Afar,Z1,W2,30.0,2026\n4,9.0,40.03,,,,999.0,2026\n"
                   "1,9.0,40.0,Afar,Z1,W1,110.0,2027\n")
    pairs = tmp_path / "pairwise_costs_1.csv"
    pairs.write_text(",".join(PAIR_COLS) + "\n"
                     "1,2,9,40,9,40.01,Afar,Z1,W1,Afar,Z1,W1,60.5\n"
                     "2,3,9,40.01,9,40.02,Afar,Z1,W1,Afar,Z1,W2,200.0\n"
                     "1,3,9,40,9,40.02,Afar,Z1,W1,Afar,Z1,W2,\n")
    inst = Instance.from_paper_files(pop, pairs)
    assert inst.n_cells == 3 and inst.meta["year"] == 2026
    assert coverage(inst, [0]) == 150 and coverage(inst, [1]) == 150 and coverage(inst, [2]) == 30
    assert inst.district_names == {0: "W1", 1: "W2"}
    assert Instance.from_paper_files(pop, pairs, year=2027).population.tolist() == [110.0]


# ---------------------------------------------------------------- prepare(area_id)
def _raw_area(tmp_path, mode="free"):
    root = tmp_path / "raw"
    drawn = {"type": "Feature", "properties": {"name": "t", "iso3": "ETH"}, "geometry": mapping(AREA)}
    from leg.data import Area
    drawn_id = Area.from_geojson("t", "ETH", drawn).area_id
    area_id = drawn_id if mode == "free" else "ETH_snapped_1"
    base = root / area_id
    wp, bd, fc, fr, parents = make_inputs(base)
    # the level rule's probes live under the drawing's folder
    for s in parents:
        dst = root / drawn_id / "boundaries" / s.path.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        s.path.rename(dst)
    rec = {"mode": mode, "drawn_area": drawn, "drawn_area_id": drawn_id,
           "level_choice": {"provider": "geoboundaries", "level": "ADM3"}}
    (base / "area.json").write_text(json.dumps(rec))
    return root, area_id


@pytest.mark.parametrize("mode", ["free", "snap"])
def test_prepare_from_area_folder(tmp_path, mode):
    root, area_id = _raw_area(tmp_path, mode)
    out = prepare(area_id, root, tmp_path / "out", fetch_parents=False)
    pop = read_csv(out / "population.csv")
    assert len(pop) == 99 and pop[0]["ADM1"] == "Region" and pop[0]["ADM2"] == "Zone"
    assert json.loads((out / "meta.json").read_text())["inputs"]["friction"] == "f1"


def test_prepare_reports_missing_friction(tmp_path):
    root, area_id = _raw_area(tmp_path)
    import shutil
    shutil.rmtree(root / area_id / "friction")
    with pytest.raises(FileNotFoundError, match="friction"):
        prepare(area_id, root, tmp_path / "out", fetch_parents=False)


def test_cli(tmp_path, capsys):
    from leg.prep.__main__ import main
    root, area_id = _raw_area(tmp_path)
    assert main(["--area-id", area_id, "--root", str(root), "--out", str(tmp_path / "out")]) == 0
    text = capsys.readouterr().out
    assert "99 cells" in text and "[3/5] travel_times" in text
    assert main(["--area-id", "nope", "--root", str(root)]) == 1
