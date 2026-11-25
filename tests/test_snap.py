"""Snapping a drawn area to whole districts (majority rule)."""
import json

import pytest
from shapely.geometry import box, mapping

from leg.data import Area, Snapshot, SnapshotCache
from leg.data.fetchers.boundaries import clip_features
from leg.data.snap import resolve_area, snap_area


def _boundaries(tmp_path, drawn):
    """Three districts against a drawing of lon 34.0-35.0:
    A = fully inside, B = exactly 50% inside (the threshold counts), C = 10% inside."""
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": n, "unit_id": n}, "geometry": mapping(g)}
        for n, g in [("A", box(34.1, 30.1, 34.5, 30.9)), ("B", box(34.6, 30.1, 35.4, 30.9)),
                     ("C", box(33.1, 30.1, 34.1, 30.9))]]}
    p = tmp_path / "b" / "s1"
    p.mkdir(parents=True)
    (p / "districts_full.geojson").write_text(json.dumps(clip_features(fc, drawn, "ADM2", keep_whole=True)))
    return Snapshot(p, {"source": "boundaries"})


@pytest.fixture
def drawn():
    return Area.from_bbox("t", "ISR", 34.0, 30.0, 35.0, 31.0)


def test_majority_rule(tmp_path, drawn):
    r = snap_area(drawn, _boundaries(tmp_path, drawn))
    by = {d.unit_id: d for d in r.districts}
    assert r.included == ["A", "B"]
    assert (by["A"].share_inside_area, by["B"].share_inside_area, by["C"].share_inside_area) == (1.0, 0.5, 0.1)
    assert by["C"].reason == "minority" and not by["C"].included
    assert r.area.geometry.equals(box(34.1, 30.1, 34.5, 30.9).union(box(34.6, 30.1, 35.4, 30.9)))
    assert r.area.area_id != drawn.area_id      # the snapped area gets its own cache folder


def test_user_overrides(tmp_path, drawn):
    r = snap_area(drawn, _boundaries(tmp_path, drawn), include=["C"], exclude=["B"])
    assert r.included == ["A", "C"]
    assert {d.unit_id: d.reason for d in r.districts} == {"A": "majority", "C": "added by user",
                                                          "B": "removed by user"}


@pytest.mark.parametrize("kw,msg", [({"include": ["Z"]}, "unknown"), ({"include": ["A"], "exclude": ["A"]}, "both"),
                                    ({"min_share": 0}, "min_share"), ({"exclude": ["A", "B"]}, "no district")])
def test_bad_input(tmp_path, drawn, kw, msg):
    with pytest.raises(ValueError, match=msg):
        snap_area(drawn, _boundaries(tmp_path, drawn), **kw)


def test_old_snapshot_without_full_shapes(tmp_path, drawn):
    p = tmp_path / "old"
    p.mkdir()
    with pytest.raises(FileNotFoundError, match="fetch boundaries again"):
        snap_area(drawn, Snapshot(p, {}))


def test_fully_inside_flag(drawn):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"unit_id": "in"}, "geometry": mapping(box(34.2, 30.2, 34.4, 30.4))},
        {"type": "Feature", "properties": {"unit_id": "cut"}, "geometry": mapping(box(34.9, 30.2, 35.1, 30.4))}]}
    flags = {f["properties"]["unit_id"]: f["properties"]["fully_inside"] for f in clip_features(fc, drawn, "ADM2")["features"]}
    assert flags == {"in": True, "cut": False}


def test_resolve_area_writes_record(tmp_path, drawn, monkeypatch):
    from leg.data import cache as cache_mod
    snap = _boundaries(tmp_path, drawn)
    monkeypatch.setattr(cache_mod.SnapshotCache, "get", lambda self, f, a, **kw: snap)
    cache = SnapshotCache(tmp_path / "raw")
    area, r = resolve_area(drawn, "snap", cache)
    rec = json.loads((tmp_path / "raw" / area.area_id / "area.json").read_text())
    assert rec["mode"] == "snap" and rec["min_share"] == 0.5 and rec["drawn_area_id"] == drawn.area_id
    assert [d["unit_id"] for d in rec["districts"] if d["included"]] == ["A", "B"]
    area2, r2 = resolve_area(drawn, "free", cache)
    assert area2 is drawn and r2 is None
    assert json.loads((tmp_path / "raw" / drawn.area_id / "area.json").read_text())["mode"] == "free"
