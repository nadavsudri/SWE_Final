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
