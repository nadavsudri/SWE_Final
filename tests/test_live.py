"""Hits the real APIs on a small area near Be'er Sheva. Run explicitly:  pytest -m live"""
import pytest

from leg.data import Area, SnapshotCache, fetch_all

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    area = Area.from_bbox("beer-sheva-test", "ISR", 34.70, 31.20, 34.90, 31.30)
    return fetch_all(area, cache=SnapshotCache(tmp_path_factory.mktemp("live")))


@pytest.mark.parametrize("source", ["worldpop", "boundaries", "osm_facilities", "osm_roads", "gtfs", "friction"])
def test_source_fetches(results, source):
    r = results[source]
    assert not isinstance(r, Exception), f"{source}: {r!r}"
    assert r.manifest["files"], f"{source}: no files written"


def test_level_rule_live(tmp_path_factory):
    """Checks how geoBoundaries answers for levels a country doesn't have (should be skipped, not crash)."""
    from leg.data.levels import choose_level
    area = Area.from_bbox("wollo-test", "ETH", 38.6, 9.7, 40.6, 11.7)
    c = choose_level(area, SnapshotCache(tmp_path_factory.mktemp("lv")))
    print(c.provider, c.level, c.usable, [(x.level, x.available, x.usable) for x in c.counts])
    assert c.level == "ADM3" and c.in_range


def test_friction_values_live(results):
    """Walking friction is minutes per metre: ~0.012 (5 km/h) on flat ground, more off-road."""
    s = results["friction"].manifest["summary"]
    print(s)
    assert s["valid_pixels"] > 100 and 0.005 < s["median_min_per_m"] < 0.1


def test_prepare_live(tmp_path_factory):
    """Fetch + preprocess a small Ethiopian area end to end (snap to woredas)."""
    import json
    from leg.data.levels import choose_level
    from leg.data.snap import resolve_area
    from leg.prep import PrepParams
    from leg.prep.run import prepare
    root = tmp_path_factory.mktemp("prep")
    cache = SnapshotCache(root)
    drawn = Area.from_bbox("bahir-dar-test", "ETH", 37.2, 11.4, 37.6, 11.8)
    c = choose_level(drawn, cache)
    area, _ = resolve_area(drawn, "snap", cache, c.boundaries_options(), extra={"level_choice": c.to_json()})
    r = fetch_all(area, ["worldpop", "boundaries", "friction", "osm_facilities"], cache,
                  options={"boundaries": c.boundaries_options()})
    assert not [k for k, v in r.items() if isinstance(v, Exception)], r
    out = prepare(area.area_id, root, root / "processed", params=PrepParams())
    meta = json.loads((out / "meta.json").read_text())
    print(meta["totals"], meta["seconds"])
    assert meta["totals"]["cells"] > 100 and meta["totals"]["pairs"] > 1000
