import json

import pytest

from leg.data import DEFAULT_PROFILE, Area, SnapshotCache, fetch_all
from leg.data.profile import resolve_profile, validate

ISRAEL_REPLY = {"admin_provider": "osm", "admin_levels": ["8"],
                "facility_tags": [["amenity", "hospital"], ["emergency", "ambulance_station"]],
                "rationale": "Municipalities; hospitals and EMS only."}


def test_no_key_prints_notice_and_uses_defaults(tmp_path, area, capsys):
    p = resolve_profile(area, tmp_path)
    assert p == DEFAULT_PROFILE
    assert "no llm key - using default values" in capsys.readouterr().out
    assert not (tmp_path / "_profiles").exists()  # defaults are not cached: a later key gets asked


def test_llm_profile_is_validated_and_cached(tmp_path, area):
    calls = []
    ask = lambda prompt, key: calls.append(prompt) or ISRAEL_REPLY
    p = resolve_profile(area, tmp_path, api_key="k", ask=ask)
    assert (p.source, p.admin_provider, p.admin_levels) == ("llm", "osm", ("8",))
    assert "Israel" in calls[0] and "km2" in calls[0]
    again = resolve_profile(area, tmp_path, api_key="k", ask=ask)
    assert again == p and len(calls) == 1  # second call served from cache
    assert json.loads((tmp_path / "_profiles" / "ISR.json").read_text())["admin_levels"] == ["8"]


@pytest.mark.parametrize("bad", [
    {**ISRAEL_REPLY, "admin_provider": "gadm"},
    {**ISRAEL_REPLY, "admin_levels": ["ADM2"]},                  # geoBoundaries level with osm
    {**ISRAEL_REPLY, "admin_provider": "geoboundaries"},         # osm level with geoBoundaries
    {**ISRAEL_REPLY, "facility_tags": [["shop", "pharmacy"]]},   # key not allowed
    {**ISRAEL_REPLY, "facility_tags": [["amenity", 'x"];out;']]},  # injection into Overpass
    {**ISRAEL_REPLY, "facility_tags": []},
])
def test_invalid_llm_choices_rejected(bad):
    with pytest.raises(ValueError):
        validate(bad)


def test_bad_llm_reply_falls_back_to_defaults(tmp_path, area, capsys):
    p = resolve_profile(area, tmp_path, api_key="k", ask=lambda *_: {"nonsense": 1})
    assert p == DEFAULT_PROFILE
    assert "using default values" in capsys.readouterr().out


def test_profile_feeds_fetcher_options(tmp_path, area, monkeypatch):
    seen = {}

    def fake_get(self, fetcher, area, **kw):
        seen[fetcher.source] = fetcher.params()
        raise RuntimeError("stop")
    monkeypatch.setattr(SnapshotCache, "get", fake_get)
    p = validate(ISRAEL_REPLY)
    fetch_all(area, ["boundaries", "osm_facilities"], SnapshotCache(tmp_path), profile=p,
              options={"boundaries": {"levels": ("6", "8")}})
    assert seen["boundaries"] == {"provider": "osm", "levels": ["6", "8"], "geometry_version": 2}  # user option wins
    assert seen["osm_facilities"]["tags"] == [["amenity", "hospital"], ["emergency", "ambulance_station"]]


def test_prompt_has_no_country_specific_rules(tmp_path, area):
    """The LLM must infer the choices; the prompt names no example countries or answers."""
    prompt = []
    resolve_profile(Area.from_bbox("x", "KEN", 36, -2, 37, -1), tmp_path, api_key="k",
                    ask=lambda p, k: prompt.append(p) or ISRAEL_REPLY)
    text = prompt[0]
    assert "Kenya" in text
    for leaked in ("Israel", "Africa", "admin_level 8", "municipalit"):
        assert leaked not in text
    assert "km2" in text  # area size given
