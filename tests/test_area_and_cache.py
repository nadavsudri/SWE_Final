from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from leg.data import Area, SnapshotCache, fetch_all
from leg.data.fetchers.base import Fetcher


# ---------- Area ----------
def test_area_id_is_stable_and_distinct():
    a = Area.from_bbox("Negev", "isr", 34, 30, 35, 31)
    b = Area.from_bbox("Negev", "ISR", 34, 30, 35, 31)
    c = Area.from_bbox("Negev", "ISR", 34, 30, 35, 31.5)
    assert a.iso3 == "ISR" and a.iso2 == "IL"
    assert a.area_id == b.area_id != c.area_id
    assert a.area_id.startswith("isr_negev_")


def test_area_from_geojson_feature_collection():
    poly = {"type": "Polygon", "coordinates": [[[34, 30], [35, 30], [35, 31], [34, 30]]]}
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": poly}]}
    assert Area.from_geojson("t", "ISR", fc).geometry.equals(Area.from_geojson("t", "ISR", poly).geometry)


@pytest.mark.parametrize("args", [
    ("x", "ZZZ", 34, 30, 35, 31),      # unknown country
    ("x", "ISR", 35, 30, 34, 31),      # west > east
    ("x", "ISR", 34, 30, 200, 31),     # not lon/lat
])
def test_area_rejects_bad_input(args):
    with pytest.raises(ValueError):
        Area.from_bbox(*args)


# ---------- Cache ----------
class CountingFetcher(Fetcher):
    source = "dummy"
    ttl_days = 7

    def __init__(self, fail=False, version=1):
        self.calls, self.fail, self.version = 0, fail, version

    def params(self):
        return {"version": self.version}

    def fetch(self, area, out_dir: Path, downloads_dir: Path):
        self.calls += 1
        (out_dir / "data.txt").write_text(f"call {self.calls}")
        if self.fail:
            raise RuntimeError("boom")
        return {"urls": ["http://example"], "params": self.params()}


T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_cache_reuses_fresh_snapshot_and_refetches_stale(tmp_path, area):
    cache, f = SnapshotCache(tmp_path), CountingFetcher()
    s1 = cache.get(f, area, now=T0)
    s2 = cache.get(f, area, now=T0 + timedelta(days=6))
    s3 = cache.get(f, area, now=T0 + timedelta(days=8))
    assert f.calls == 2 and s1.id == s2.id != s3.id
    assert [s.id for s in cache.list(area, "dummy")] == [s1.id, s3.id]  # old snapshot kept


def test_cache_manifest_has_hashes(tmp_path, area):
    s = SnapshotCache(tmp_path).get(CountingFetcher(), area, now=T0)
    assert s.manifest["files"]["data.txt"]["bytes"] == len("call 1")
    assert len(s.manifest["files"]["data.txt"]["sha256"]) == 64
    assert s.manifest["area_id"] == area.area_id


def test_cache_refresh_and_param_change_force_new_snapshot(tmp_path, area):
    cache, f = SnapshotCache(tmp_path), CountingFetcher()
    cache.get(f, area, now=T0)
    cache.get(f, area, refresh=True, now=T0 + timedelta(seconds=1))
    cache.get(CountingFetcher(version=2), area, now=T0 + timedelta(seconds=2))
    assert len(cache.list(area, "dummy")) == 3


def test_cache_pinned_snapshot_ignores_ttl(tmp_path, area):
    cache, f = SnapshotCache(tmp_path), CountingFetcher()
    s1 = cache.get(f, area, now=T0)
    pinned = cache.get(f, area, snapshot_id=s1.id, now=T0 + timedelta(days=999))
    assert pinned.id == s1.id and f.calls == 1
    with pytest.raises(FileNotFoundError):
        cache.get(f, area, snapshot_id="does-not-exist")


def test_failed_fetch_leaves_no_snapshot(tmp_path, area):
    cache = SnapshotCache(tmp_path)
    with pytest.raises(RuntimeError):
        cache.get(CountingFetcher(fail=True), area, now=T0)
    assert cache.list(area, "dummy") == []
    assert not any(cache.source_dir(area, "dummy").iterdir())


def test_fetch_all_reports_failures_per_source(tmp_path, area):
    res = fetch_all(area, ["not_a_source"], SnapshotCache(tmp_path))
    assert isinstance(res["not_a_source"], KeyError)
