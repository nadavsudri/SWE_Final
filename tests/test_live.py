"""Hits the real APIs on a small area near Be'er Sheva. Run explicitly:  pytest -m live"""
import pytest

from leg.data import Area, SnapshotCache, fetch_all

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    area = Area.from_bbox("beer-sheva-test", "ISR", 34.70, 31.20, 34.90, 31.30)
    return fetch_all(area, cache=SnapshotCache(tmp_path_factory.mktemp("live")))


@pytest.mark.parametrize("source", ["worldpop", "boundaries", "osm_facilities", "osm_roads", "gtfs"])
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
