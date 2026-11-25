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


def test_network_errors_are_not_hidden(tmp_path, drawn):
    f = fake(tmp_path, {("geoboundaries", "ADM1"): requests.ConnectionError("offline")})
    with pytest.raises(requests.ConnectionError):
        choose_level(drawn, fetch=f)


def test_llm_profile_no_longer_needs_admin_fields():
    p = validate({"facility_tags": [["amenity", "hospital"]], "rationale": "x"})
    assert p.source == "llm" and p.facility_tags == (("amenity", "hospital"),)
