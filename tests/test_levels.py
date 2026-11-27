"""Rule-based choice of the district level."""
import json

import pytest
import requests
from shapely.geometry import box, mapping

from leg.data import Area, Snapshot
from leg.data.levels import choose_level
from leg.data.profile import validate


@pytest.fixture
def drawn():
    return Area.from_bbox("t", "ETH", 38.0, 10.0, 40.0, 12.0)


def fake(tmp_path, layout):
    """layout: {(provider, level): list of shares | 'missing' | 'empty' | Exception}"""
    def fetch(provider, level):
        spec = layout.get((provider, level), "missing")
        if spec == "missing":
            r = requests.Response()
            r.status_code = 404
            raise requests.HTTPError(response=r)
        if spec == "empty":
            raise ValueError(f"No {provider} level-{level} units intersect the area")
        if isinstance(spec, Exception):
            raise spec
        p = tmp_path / provider / level
        p.mkdir(parents=True, exist_ok=True)
        feats = [{"type": "Feature", "properties": {"unit_id": f"{level}-{i}", "share_inside_area": s},
                  "geometry": mapping(box(38, 10, 38.1, 10.1))} for i, s in enumerate(spec)]
        (p / "districts_full.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
        return Snapshot(p, {})
    return fetch


def shares(whole, partial=0):
    return [1.0] * whole + [0.2] * partial


def test_picks_finest_level_in_range(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM1"): shares(0, 2), ("geoboundaries", "ADM2"): shares(2, 5),
                        ("geoboundaries", "ADM3"): shares(18, 9), ("geoboundaries", "ADM4"): shares(150)})
    c = choose_level(drawn, fetch=f)
    assert (c.provider, c.level, c.usable, c.in_range) == ("geoboundaries", "ADM3", 18, True)
    by = {x.level: x for x in c.counts}
    assert (by["ADM2"].usable, by["ADM2"].touched) == (2, 7)
    assert not by["ADM5"].available
    assert c.boundaries_options() == {"provider": "geoboundaries", "levels": ("ADM3",)}
    assert not any(x.provider == "osm" for x in c.counts)  # no OSM queries when not needed


def test_too_many_at_finest_keeps_coarser(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM2"): shares(12), ("geoboundaries", "ADM3"): shares(300)})
    assert choose_level(drawn, fetch=f).level == "ADM2"


def test_osm_fallback_when_geoboundaries_too_coarse(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM1"): shares(1), ("geoboundaries", "ADM2"): shares(2),
                        ("osm", "6"): "empty", ("osm", "8"): shares(25, 4)})
    c = choose_level(drawn, fetch=f)
    assert (c.provider, c.level, c.usable) == ("osm", "8", 25)
    assert next(x for x in c.counts if x.level == "6").note == "no unit in the area"


def test_nothing_in_range_takes_closest_with_warning(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM1"): shares(1), ("geoboundaries", "ADM2"): shares(6)})
    c = choose_level(drawn, fetch=f)
    assert (c.level, c.in_range) == ("ADM2", False) and "closest" in c.reason


def test_free_mode_counts_touched(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM2"): shares(3, 9)})
    assert choose_level(drawn, mode="free", fetch=f).usable == 12
    with pytest.raises(ValueError):
        choose_level(drawn, mode="snap", min_count=10, fetch=fake(tmp_path, {}))  # nothing at all


def test_failed_level_does_not_block_the_others(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM1"): shares(1), ("geoboundaries", "ADM2"): shares(2),
                        ("osm", "6"): requests.ReadTimeout("slow"), ("osm", "8"): shares(30)})
    c = choose_level(drawn, fetch=f)
    assert (c.provider, c.level) == ("osm", "8")
    bad = next(x for x in c.counts if x.level == "6")
    assert bad.failed and "ReadTimeout" in bad.note


def test_failed_finer_level_is_reported(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM2"): shares(12),
                        ("geoboundaries", "ADM3"): requests.ConnectionError("offline")})
    c = choose_level(drawn, fetch=f)
    assert c.level == "ADM2" and "could not check geoboundaries ADM3" in c.reason


def test_only_failures_raise_with_a_clear_message(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM1"): shares(1),
                        **{("osm", lv): requests.ReadTimeout("slow") for lv in ("5", "6", "7", "8", "9", "10")}})
    with pytest.raises(RuntimeError, match=r"osm 5 could not be checked.*use the free polygon"):
        choose_level(drawn, fetch=f)


def test_llm_profile_no_longer_needs_admin_fields():
    p = validate({"facility_tags": [["amenity", "hospital"]], "rationale": "x"})
    assert p.source == "llm" and p.facility_tags == (("amenity", "hospital"),)


def test_geoboundaries_levels_are_fetched_in_parallel(tmp_path, drawn):
    import time
    base = fake(tmp_path, {("geoboundaries", f"ADM{i}"): shares(5 * i) for i in range(1, 6)})

    def slow(provider, level):
        time.sleep(0.3)
        return base(provider, level)
    seen = []
    t = time.time()
    c = choose_level(drawn, fetch=slow, progress=seen.append)
    assert time.time() - t < 0.9                     # 5 levels x 0.3 s, at once
    assert c.level == "ADM5" and c.usable == 25
    assert [x.level for x in seen] == ["ADM1", "ADM2", "ADM3", "ADM4", "ADM5"]   # reported in level order


def test_osm_stops_after_a_level_with_too_many(tmp_path, drawn):
    calls = []
    base = fake(tmp_path, {("geoboundaries", "ADM1"): shares(2), ("osm", "5"): shares(3), ("osm", "6"): shares(400)})

    def f(provider, level):
        calls.append((provider, level))
        return base(provider, level)
    c = choose_level(drawn, fetch=f)
    assert ("osm", "7") not in calls and ("osm", "8") not in calls
    by = {(x.provider, x.level): x for x in c.counts}
    assert by[("osm", "7")].skipped and by[("osm", "8")].skipped and "not checked" in by[("osm", "8")].note
    assert not any(x.level in ("9", "10") for x in c.counts)       # OSM checks levels 5-8 only
    assert (c.provider, c.level) == ("osm", "5") and not c.in_range  # 3 is closer to 10-100 than 400


def test_snapshots_in_the_same_second_do_not_collide(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from leg.data import SnapshotCache
    from leg.data.fetchers.base import Fetcher

    class F(Fetcher):
        source, ttl_days = "x", 1

        def __init__(self, n):
            self.n = n

        def params(self):
            return {"n": self.n}

        def fetch(self, area, out_dir, downloads_dir):
            (out_dir / "v.txt").write_text(str(self.n))
            return {}
    area = Area.from_bbox("a", "ETH", 38, 10, 39, 11)
    cache = SnapshotCache(tmp_path)
    now = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    with ThreadPoolExecutor(8) as pool:
        snaps = list(pool.map(lambda n: cache.get(F(n), area, now=now), range(8)))
    assert len({s.id for s in snaps}) == 8
    assert sorted(int((s.path / "v.txt").read_text()) for s in snaps) == list(range(8))
