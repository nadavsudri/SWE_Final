"""API tests: fetch_all and resolve_profile are mocked; no network, temp cache root."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

import leg.data as data
from leg.api import Settings, create_app
from leg.api import areas as areas_mod
from leg.data import Area, DEFAULT_PROFILE, Snapshot

import leg.data.levels as data_levels  # noqa: E402
from leg.data.levels import LevelChoice, LevelCount  # noqa: E402

BBOX = (34.5, 30.5, 35.45, 31.6)
FIXED_LEVEL = LevelChoice("geoboundaries", "ADM2", 12, True, "finest level with 10-100 usable districts",
                          [LevelCount("geoboundaries", "ADM1", True, 1, 1), LevelCount("geoboundaries", "ADM2", True, 14, 12),
                           LevelCount("geoboundaries", "ADM3", False, note="404")])
RECT = {"type": "Polygon", "coordinates": [[[34.5, 30.5], [35.45, 30.5], [35.45, 31.6], [34.5, 31.6], [34.5, 30.5]]]}
AREA = {"name": "negev", "iso3": "ISR", "geojson": RECT}


def write_snapshot(root, area, source, snap_id, params, fetched_at, files=None):
    d = root / area.area_id / source / snap_id
    d.mkdir(parents=True)
    for name, content in (files or {}).items():
        (d / name).write_text(content)
    manifest = {"source": source, "area": area.to_geojson(), "area_id": area.area_id,
                "fetched_at": fetched_at.isoformat(), "params": params, "urls": ["http://x"],
                "summary": {"n": 1}, "files": {n: {"bytes": len(c), "sha256": "0"} for n, c in (files or {}).items()}}
    (d / "manifest.json").write_text(json.dumps(manifest))
    return Snapshot(d, manifest)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "raw"


@pytest.fixture
def client(root, monkeypatch, tmp_path):
    monkeypatch.setattr(areas_mod.CountryBorders, "get", lambda self, iso3: box(34, 29, 36, 33))
    monkeypatch.setattr(data, "resolve_profile", lambda area, root, refresh=False, **kw: DEFAULT_PROFILE)
    # the district-level rule probes every level over the network; most tests take a fixed choice
    monkeypatch.setattr(data_levels, "choose_level", lambda drawn, cache=None, mode="snap", min_share=0.5, **kw: FIXED_LEVEL)
    env = tmp_path / "no.env"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(create_app(Settings(root=root, env_file=env)))


def wait_idle(client, job_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get(f"/api/fetch/{job_id}").json()
        if not v["running"]:
            return v
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_config_reports_key_as_boolean_only(client, tmp_path, monkeypatch):
    cfg = client.get("/api/config").json()
    assert cfg["llm_key_present"] is False and cfg["warn_km2"] == 20000 and cfg["max_km2"] == 100000
    monkeypatch.setattr("leg.llm.claude.load_api_key", lambda *a, **k: "sk-secret-value")  # conftest stubs it to None
    body = client.get("/api/config").text
    assert '"llm_key_present":true' in body and "sk-secret" not in body


def test_countries_list(client):
    rows = client.get("/api/countries").json()
    assert {"name": "Israel", "iso3": "ISR"} in rows and len(rows) > 200


def test_validate_rectangle_matches_bbox_area_id(client):
    r = client.post("/api/area/validate", json=AREA).json()
    assert r["ok"] and r["area_id"] == Area.from_bbox("negev", "ISR", *BBOX).area_id
    assert r["bbox"] == list(BBOX) and 11000 < r["km2"] < 11200 and r["warnings"] == []


@pytest.mark.parametrize("geojson, needle", [
    ({"type": "FeatureCollection", "features": [{}, {}, {}]}, "contains 3 features, expected 1"),
    ("{not json", "Not valid JSON"),
    ({"coordinates": []}, "no \"type\""),
    ({"type": "Point", "coordinates": [34.8, 31.0]}, "Polygon or MultiPolygon"),
    ({"type": "Polygon", "coordinates": [[[34, 30], [35, 31], [35, 30], [34, 31], [34, 30]]]}, "shape is invalid"),
])
def test_validate_rejects_bad_geojson(client, geojson, needle):
    r = client.post("/api/area/validate", json={"name": "a", "iso3": "ISR", "geojson": geojson}).json()
    assert not r["ok"] and needle in r["errors"][0]["message"]


def test_validate_reports_cached_areas_with_the_same_shape(client, root):
    cached = Area.from_bbox("negev", "ISR", *BBOX)
    write_snapshot(root, cached, "boundaries", "b1", {}, datetime(2026, 11, 12, tzinfo=timezone.utc))
    r = client.post("/api/area/validate", json={**AREA, "name": "israel"}).json()
    assert r["area_id"] != cached.area_id and r["same_shape"] == [cached.area_id]


def test_validate_requires_name_and_country(client):
    r = client.post("/api/area/validate", json={"name": " ", "iso3": "", "geojson": RECT}).json()
    msgs = " ".join(e["message"] for e in r["errors"])
    assert "Name is required" in msgs and "Choose a country" in msgs


def test_validate_size_warning_and_block(client):
    big = {"type": "Polygon", "coordinates": [[[34, 29], [36, 29], [36, 31.2], [34, 31.2], [34, 29]]]}
    r = client.post("/api/area/validate", json={"name": "b", "iso3": "ISR", "geojson": big}).json()
    assert r["ok"] and [w["code"] for w in r["warnings"]] == ["large"]
    huge = {"type": "Polygon", "coordinates": [[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]]}
    r = client.post("/api/area/validate", json={"name": "h", "iso3": "ISR", "geojson": huge}).json()
    assert not r["ok"] and r["errors"][0]["code"] == "too_large"


def test_validate_outside_country_and_unknown_border(client, monkeypatch):
    monkeypatch.setattr(areas_mod.CountryBorders, "get", lambda self, iso3: box(34.5, 30.5, 35.0, 31.6))
    r = client.post("/api/area/validate", json=AREA).json()
    w = r["warnings"][0]
    assert r["ok"] and w["code"] == "outside_country" and 0.4 < w["share_outside"] < 0.6
    monkeypatch.setattr(areas_mod.CountryBorders, "get", lambda self, iso3: None)
    r = client.post("/api/area/validate", json=AREA).json()
    assert r["ok"] and r["warnings"][0]["code"] == "border_unknown"


def test_saved_areas_lists_folders_with_manifests(client, root):
    area = Area.from_bbox("negev", "ISR", *BBOX)
    write_snapshot(root, area, "boundaries", "2026-11-12T101414Z", {}, datetime(2026, 11, 12, tzinfo=timezone.utc))
    (root / "_downloads").mkdir()
    (root / "empty_area").mkdir()
    rows = client.get("/api/areas").json()
    assert [r["area_id"] for r in rows] == [area.area_id]
    assert rows[0]["name"] == "negev" and rows[0]["iso3"] == "ISR" and rows[0]["sources"] == {"boundaries": ["2026-11-12T101414Z"]}


def test_profile_default_and_refresh_needs_key(client):
    p = client.post("/api/profile", json={"area": AREA}).json()
    assert p["status"] == "default_no_key" and p["fetcher_options"]["boundaries"]["levels"] == ["ADM1", "ADM2"]
    r = client.post("/api/profile", json={"area": AREA, "refresh": True})
    assert r.status_code == 400 and "No LLM key" in r.text


def test_snapshots_plan_reuse_download_and_reasons(client, root):
    area = Area.from_bbox("negev", "ISR", *BBOX)
    now = datetime.now(timezone.utc)
    write_snapshot(root, area, "boundaries", "b1",
                   {"provider": "geoboundaries", "levels": ["ADM2"], "geometry_version": 2, "simplified": True}, now - timedelta(days=12))
    write_snapshot(root, area, "osm_facilities", "f1", {"tags": [["amenity", "hospital"]]}, now - timedelta(days=1))
    write_snapshot(root, area, "gtfs", "g1", {"max_feeds": 10}, now - timedelta(days=20))
    plan = client.post("/api/snapshots", json={"area": AREA, "options": {}}).json()
    assert plan["boundaries"]["decision"] == "reuse" and plan["boundaries"]["snapshot_id"] == "b1"
    assert plan["osm_facilities"]["reason"] == "params_changed"
    assert plan["gtfs"]["reason"] == "expired"
    assert plan["worldpop"]["reason"] == "no_snapshot"


def test_snapshots_validates_options(client):
    opts = {"worldpop": {"year": 2040}, "boundaries": {"provider": "osm", "levels": ["4", "ADM2"]},
            "osm_facilities": {"tags": [["shop", "chemist"]]}, "gtfs": {"max_feeds": 0}}
    plan = client.post("/api/snapshots", json={"area": AREA, "options": opts}).json()
    assert "2015–2030" in plan["worldpop"]["errors"]["year"]
    # the district level comes from the rule (or an override), never from hand-edited provider/levels
    assert plan["boundaries"]["errors"] == {} and plan["boundaries"]["params"]["levels"] == ["ADM2"]
    assert "amenity, healthcare or emergency" in plan["osm_facilities"]["errors"]["tags"]
    assert plan["gtfs"]["decision"] == "invalid"
    assert plan["osm_roads"]["decision"] == "download"
    plan = client.post("/api/snapshots", json={"area": AREA, "options": {"boundaries": {"provider": "osm"}}}).json()
    assert plan["boundaries"]["params"]["provider"] == "geoboundaries"


def test_fetch_runs_one_source_per_call_reports_status_and_retry(client, root, monkeypatch):
    area = Area.from_bbox("negev", "ISR", *BBOX)
    old = write_snapshot(root, area, "boundaries", "b1", {}, datetime(2026, 11, 12, tzinfo=timezone.utc),
                         {"districts.geojson": "{}"})
    calls, fail = [], {"osm_roads": 1}

    def fake_fetch_all(area, sources=None, cache=None, refresh=False, pinned=None, options=None, profile=None):
        (src,) = sources
        calls.append((src, pinned, profile))
        if fail.get(src):
            fail[src] -= 1
            return {src: ConnectionError("overpass-api.de could not be reached")}
        if src == "boundaries":
            return {src: old}
        return {src: write_snapshot(root, area, src, f"new-{src}-{len(calls)}", {}, datetime.now(timezone.utc))}

    monkeypatch.setattr(data, "fetch_all", fake_fetch_all)
    r = client.post("/api/fetch", json={"area": AREA, "sources": ["worldpop", "boundaries", "osm_roads"]})
    assert r.status_code == 200
    job = wait_idle(client, r.json()["job_id"])
    rows = {s["source"]: s for s in job["sources"]}
    assert [c[0] for c in calls][:3] == ["worldpop", "boundaries", "osm_roads"]
    assert all(c[2] is DEFAULT_PROFILE for c in calls)
    assert rows["boundaries"]["status"] == "reused" and rows["boundaries"]["result"]["snapshot_id"] == "b1"
    assert rows["worldpop"]["status"] == "done"
    assert rows["osm_roads"]["status"] == "failed" and "could not be reached" in rows["osm_roads"]["error"]
    assert job["counts"] == {"queued": 0, "running": 0, "reused": 1, "done": 1, "failed": 1}

    assert client.post(f"/api/fetch/{job['job_id']}/retry/worldpop").status_code == 400
    r = client.post(f"/api/fetch/{job['job_id']}/retry/osm_roads")
    assert r.status_code == 200
    job = wait_idle(client, job["job_id"])
    rows = {s["source"]: s for s in job["sources"]}
    assert rows["osm_roads"]["status"] == "done" and rows["osm_roads"]["attempts"] == 2
    assert [c[0] for c in calls].count("worldpop") == 1


def test_fetch_orders_cached_first_and_passes_pin(client, root, monkeypatch):
    area = Area.from_bbox("negev", "ISR", *BBOX)
    write_snapshot(root, area, "osm_facilities", "f-old", {"tags": [["x", "y"]]}, datetime(2026, 1, 1, tzinfo=timezone.utc))
    seen = []

    def fake_fetch_all(area, sources=None, pinned=None, **kw):
        seen.append((sources[0], pinned))
        return {sources[0]: RuntimeError("offline")}

    monkeypatch.setattr(data, "fetch_all", fake_fetch_all)
    r = client.post("/api/fetch", json={"area": AREA, "sources": ["worldpop", "osm_facilities"],
                                        "pinned": {"osm_facilities": "f-old"}})
    assert r.json()["order"] == ["osm_facilities", "worldpop"]
    wait_idle(client, r.json()["job_id"])
    assert seen[0] == ("osm_facilities", {"osm_facilities": "f-old"})


def test_fetch_rejects_bad_input(client):
    assert client.post("/api/fetch", json={"area": {"name": "", "iso3": "ISR", "geojson": RECT}}).status_code == 400
    r = client.post("/api/fetch", json={"area": AREA, "sources": ["worldpop"], "options": {"worldpop": {"year": 1999}}})
    assert r.status_code == 400 and "2015–2030" in r.text
    r = client.post("/api/fetch", json={"area": AREA, "sources": ["boundaries"], "pinned": {"boundaries": "nope"}})
    assert r.status_code == 400 and "No snapshot" in r.text
    assert client.post("/api/fetch", json={"area": AREA, "sources": []}).status_code == 400
    assert client.get("/api/fetch/unknown").status_code == 404


def test_snapshot_file_whitelist_and_traversal(client, root):
    area = Area.from_bbox("negev", "ISR", *BBOX)
    write_snapshot(root, area, "boundaries", "b1", {}, datetime(2026, 11, 12, tzinfo=timezone.utc),
                   {"districts.geojson": '{"type":"FeatureCollection","features":[]}', "adm1.geojson": "{}"})
    base = f"/api/snapshot/{area.area_id}/boundaries/b1"
    assert client.get(f"{base}/districts.geojson").json()["type"] == "FeatureCollection"
    assert client.get(f"{base}/manifest.json").json()["source"] == "boundaries"
    assert client.get(f"{base}/adm1.geojson").status_code == 404
    assert client.get(f"/api/snapshot/{area.area_id}/notasource/b1/manifest.json").status_code == 404
    assert client.get(f"/api/snapshot/..%2F..%2Fetc/boundaries/b1/manifest.json").status_code == 404
    assert client.get(f"/api/snapshot/{area.area_id}/boundaries/..%2F..%2F/manifest.json").status_code == 404


# ── area modes: snap to whole districts / free polygon (boundaries fetch mocked) ──
from shapely.geometry import mapping as _mapping  # noqa: E402

from leg.data.fetchers import BoundariesFetcher  # noqa: E402
from leg.data.fetchers.boundaries import clip_features  # noqa: E402

DRAWN = {"type": "Polygon", "coordinates": [[[34, 30], [35, 30], [35, 31], [34, 31], [34, 30]]]}
SNAP_AREA = {"name": "t", "iso3": "ISR", "geojson": DRAWN}


@pytest.fixture
def districts(monkeypatch):
    """A fully inside, B exactly 50% inside, C 10% inside (the same layout as test_snap)."""
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": n, "unit_id": n}, "geometry": _mapping(g)}
        for n, g in [("A", box(34.1, 30.1, 34.5, 30.9)), ("B", box(34.6, 30.1, 35.4, 30.9)),
                     ("C", box(33.1, 30.1, 34.1, 30.9))]]}
    calls = []

    def fake_fetch(self, area, out_dir, downloads_dir):
        calls.append(area.area_id)
        (out_dir / "districts_full.geojson").write_text(json.dumps(clip_features(fc, area, "ADM2", keep_whole=True)))
        (out_dir / "districts.geojson").write_text(json.dumps(clip_features(fc, area, "ADM2")))
        return {"urls": [], "params": self.params(), "summary": {"districts": 3}}

    monkeypatch.setattr(BoundariesFetcher, "fetch", fake_fetch)
    return calls


def snap(client, **mode):
    return client.post("/api/area/snap", json={"area": SNAP_AREA, "area_mode": {"mode": "snap", **mode}})


def test_snap_success_previews_without_writing_area_json(client, root, districts):
    r = snap(client)
    assert r.status_code == 200
    j = r.json()
    rows = {d["unit_id"]: d for d in j["districts"]}
    assert j["ok"] and j["error"] is None
    assert [d["unit_id"] for d in j["districts"] if d["included"]] == ["A", "B"]
    assert rows["C"]["reason"] == "minority" and rows["C"]["share_inside_area"] == 0.1
    assert rows["A"]["fully_inside"] and rows["A"]["geometry"]["type"] == "Polygon"
    assert j["area_id"] != j["drawn_area_id"] and j["km2"] < j["drawn_km2"]
    assert j["geojson"]["type"] in ("Polygon", "MultiPolygon")
    assert not list(root.glob("*/area.json"))                       # a preview writes nothing
    snap(client)
    assert len(districts) == 1                                      # the drawing's districts are cached


def test_snap_nothing_qualifies_is_a_state_with_the_district_list(client, districts):
    j = snap(client, min_share=0.6, exclude=["A"]).json()
    assert not j["ok"] and j["area_id"] is None and j["geojson"] is None
    assert j["error"]["code"] == "no_district_qualifies" and "60%" in j["error"]["message"]
    assert {d["unit_id"]: (d["included"], d["reason"]) for d in j["districts"]} == {
        "A": (False, "removed by user"), "B": (False, "minority"), "C": (False, "minority")}


def test_snap_include_exclude_and_bad_input(client, districts):
    j = snap(client, include=["C"], exclude=["B"]).json()
    assert [d["unit_id"] for d in j["districts"] if d["included"]] == ["A", "C"]
    assert {d["unit_id"]: d["reason"] for d in j["districts"]}["C"] == "added by user"
    assert snap(client, include=["Z"]).status_code == 400
    assert snap(client, include=["A"], exclude=["A"]).status_code == 400
    assert snap(client, min_share=0).status_code == 400


def test_snap_reports_boundaries_failure(client, monkeypatch):
    def boom(self, area, out_dir, downloads_dir):
        raise ConnectionError("geoboundaries.org could not be reached")
    monkeypatch.setattr(BoundariesFetcher, "fetch", boom)
    j = snap(client).json()
    assert not j["ok"] and j["error"]["code"] == "boundaries_failed" and "could not be reached" in j["error"]["message"]


def test_plan_refers_to_the_snapped_area(client, root, districts):
    snapped = snap(client).json()["area_id"]
    plan = client.post("/api/snapshots", json={"area": SNAP_AREA, "area_mode": {"mode": "snap"}}).json()
    assert plan["boundaries"]["decision"] == "download"             # nothing cached for the snapped area yet
    r = client.post("/api/snapshots", json={"area": SNAP_AREA, "area_mode": {"mode": "snap", "exclude": ["A", "B"]}})
    assert r.status_code == 409 and "no district" in r.text
    assert snapped


def test_fetch_snap_mode_resolves_area_then_fetches_it(client, root, districts, monkeypatch):
    seen = []

    def fake_fetch_all(area, sources=None, **kw):
        seen.append(area.area_id)
        return {sources[0]: RuntimeError("offline")}
    monkeypatch.setattr(data, "fetch_all", fake_fetch_all)
    expected = snap(client, include=["C"]).json()["area_id"]
    r = client.post("/api/fetch", json={"area": SNAP_AREA, "sources": ["worldpop"],
                                        "area_mode": {"mode": "snap", "include": ["C"]}})
    job = wait_idle(client, r.json()["job_id"])
    assert job["area"]["status"] == "done" and job["area"]["area_id"] == expected == job["area_id"]
    assert job["area"]["mode"] == "snap" and set(job["area"]["included"]) == {"A", "B", "C"}
    assert seen == [expected]                                       # sources fetched for the snapped area
    rec = json.loads((root / expected / "area.json").read_text())
    assert rec["mode"] == "snap" and rec["drawn_area_id"] == job["area"]["drawn_area_id"]
    # saved areas: the snapped area with its mode and choices; the drawing's own folder is hidden
    rows = client.get("/api/areas").json()
    assert [a["area_id"] for a in rows] == [expected]
    assert rows[0]["mode"] == "snap" and rows[0]["include"] == ["C"] and rows[0]["min_share"] == 0.5
    assert rows[0]["drawn_geojson"]["geometry"]["type"] == "Polygon"


def test_fetch_free_mode_keeps_the_drawing(client, root, districts, monkeypatch):
    seen = []
    monkeypatch.setattr(data, "fetch_all", lambda area, sources=None, **kw: seen.append(area.area_id) or {sources[0]: RuntimeError("x")})
    r = client.post("/api/fetch", json={"area": SNAP_AREA, "sources": ["worldpop"], "area_mode": {"mode": "free"}})
    job = wait_idle(client, r.json()["job_id"])
    drawn_id = Area.from_bbox("t", "ISR", 34, 30, 35, 31).area_id
    assert job["area"]["mode"] == "free" and job["area_id"] == drawn_id and seen == [drawn_id]
    assert json.loads((root / drawn_id / "area.json").read_text())["mode"] == "free"
    assert districts == []                                          # free mode fetches no districts to resolve
    assert client.get("/api/areas").json()[0]["mode"] == "free"


def test_fetch_area_step_failure_and_retry(client, root, monkeypatch, districts):
    monkeypatch.setattr(data, "fetch_all", lambda area, sources=None, **kw: {sources[0]: RuntimeError("x")})
    import leg.data.snap as snap_mod
    real = snap_mod.resolve_area
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("boundaries unreachable")
        return real(*a, **kw)
    monkeypatch.setattr(snap_mod, "resolve_area", flaky)
    r = client.post("/api/fetch", json={"area": SNAP_AREA, "sources": ["worldpop"], "area_mode": {"mode": "snap"}})
    job = wait_idle(client, r.json()["job_id"])
    assert job["area"]["status"] == "failed" and "unreachable" in job["area"]["error"]
    assert job["sources"][0]["error"] == "Not fetched: the area step failed."
    job = client.post(f"/api/fetch/{job['job_id']}/retry/area").json()
    job = wait_idle(client, job["job_id"])
    assert job["area"]["status"] == "done"


# ── district level: choose_level as a job, override, saved in area.json (fetches mocked) ──
REAL_CHOOSE = data_levels.choose_level


@pytest.fixture
def levelled(monkeypatch):
    """Per level, n small districts fully inside DRAWN: ADM1 2, ADM2 15, ADM3 150; ADM4/ADM5 missing."""
    import requests
    monkeypatch.setattr(data_levels, "choose_level", REAL_CHOOSE)
    per_level = {"ADM1": 2, "ADM2": 15, "ADM3": 150}
    probes = []

    def fake_fetch(self, area, out_dir, downloads_dir):
        lv = self.levels[-1]
        probes.append((self.provider, lv))
        n = per_level.get(lv)
        if n is None:
            raise requests.HTTPError(response=type("R", (), {"status_code": 404})())
        side = int(n ** 0.5) + 1
        feats = [{"type": "Feature", "properties": {"name": f"{lv}-{i}", "unit_id": f"{lv}-{i}"},
                  "geometry": _mapping(box(34.01 + (i % side) * 0.9 / side, 30.01 + (i // side) * 0.9 / side,
                                           34.01 + (i % side + 0.8) * 0.9 / side, 30.01 + (i // side + 0.8) * 0.9 / side))}
                 for i in range(n)]
        fc = {"type": "FeatureCollection", "features": feats}
        (out_dir / "districts_full.geojson").write_text(json.dumps(clip_features(fc, area, lv, keep_whole=True)))
        (out_dir / "districts.geojson").write_text(json.dumps(clip_features(fc, area, lv)))
        return {"urls": [], "params": self.params(), "summary": {"districts": n}}

    monkeypatch.setattr(BoundariesFetcher, "fetch", fake_fetch)
    # snapshot ids are timestamps to the second: give the cache a clock that ticks per call
    import leg.data.cache as cache_mod
    from leg.api import levels as levels_api
    tick = {"n": 0}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            tick["n"] += 1
            return datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=tick["n"])
    monkeypatch.setattr(cache_mod, "datetime", Clock)
    monkeypatch.setattr(levels_api.LevelManager, "MIN_GAP_S", 0.0)
    return probes


def wait_levels(client, job_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get(f"/api/area/levels/{job_id}").json()
        if v["status"] != "running":
            return v
        time.sleep(0.02)
    raise AssertionError("level job did not finish")


def test_levels_job_reports_probes_and_the_rules_choice(client, levelled):
    j = client.post("/api/area/levels", json={"area": SNAP_AREA, "area_mode": {"mode": "snap"}}).json()
    v = wait_levels(client, j["job_id"])
    assert v["status"] == "done" and v["probing"] is None
    c = v["choice"]
    assert (c["provider"], c["level"], c["usable"], c["in_range"]) == ("geoboundaries", "ADM2", 15, True)
    counts = {x["level"]: (x["available"], x["touched"], x["usable"]) for x in c["counts"]}
    assert counts["ADM3"] == (True, 150, 150) and counts["ADM4"][0] is False
    assert [(p["level"], p["state"]) for p in v["probed"]][:3] == [("ADM1", "downloaded"), ("ADM2", "downloaded"), ("ADM3", "downloaded")]
    # the same drawing again answers from the finished job; a new job would hit the cached probes
    again = client.post("/api/area/levels", json={"area": SNAP_AREA, "area_mode": {"mode": "snap"}}).json()
    assert again["job_id"] == j["job_id"] and again["status"] == "done"
    n = len(levelled)
    snap_r = client.post("/api/area/snap", json={"area": SNAP_AREA, "area_mode": {"mode": "snap"}}).json()
    assert snap_r["ok"] and snap_r["level"]["level"] == "ADM2" and snap_r["level"]["source"] == "rule"
    assert len(snap_r["districts"]) == 15 and len(levelled) == n    # snapping reuses the cached ADM2 probe


def test_levels_closest_when_nothing_in_range(client, monkeypatch, levelled):
    monkeypatch.setattr(data_levels, "choose_level", lambda *a, **kw: REAL_CHOOSE(*a, **{**kw, "min_count": 200, "max_count": 300}))
    j = client.post("/api/area/levels", json={"area": SNAP_AREA, "area_mode": {"mode": "snap"}}).json()
    c = wait_levels(client, j["job_id"])["choice"]
    assert c["in_range"] is False and c["level"] == "ADM3" and "closest" in c["reason"]


def test_levels_nothing_usable_is_a_failed_state(client, monkeypatch, levelled):
    def none(*a, **kw):
        raise ValueError("no administrative level has any usable district for this area; draw a larger area")
    monkeypatch.setattr(data_levels, "choose_level", none)
    v = wait_levels(client, client.post("/api/area/levels", json={"area": SNAP_AREA}).json()["job_id"])
    assert v["status"] == "failed" and "no administrative level" in v["error"]
    r = client.post("/api/area/snap", json={"area": SNAP_AREA, "area_mode": {"mode": "snap"}}).json()
    assert not r["ok"] and r["error"]["code"] == "no_level"


def test_level_override_replaces_the_rule_and_is_saved(client, root, monkeypatch, levelled):
    seen = []
    monkeypatch.setattr(data, "fetch_all", lambda area, sources=None, options=None, **kw:
                        seen.append(options.get("boundaries")) or {sources[0]: RuntimeError("x")})
    override = {"provider": "geoboundaries", "level": "ADM3"}
    r = client.post("/api/area/snap", json={"area": SNAP_AREA, "area_mode": {"mode": "snap"}, "level_override": override}).json()
    assert r["level"] == {"provider": "geoboundaries", "level": "ADM3", "source": "override", "in_range": True,
                          "reason": "finest level with 10-100 usable districts"} and len(r["districts"]) == 150
    bad = client.post("/api/area/snap", json={"area": SNAP_AREA, "level_override": {"provider": "geoboundaries", "level": "ADM5"}})
    assert bad.status_code == 400
    job = client.post("/api/fetch", json={"area": SNAP_AREA, "sources": ["boundaries"], "area_mode": {"mode": "snap"},
                                          "level_override": override}).json()
    job = wait_idle(client, job["job_id"])
    assert job["area"]["level"]["level"] == "ADM3" and job["area"]["level"]["source"] == "override"
    assert seen and seen[0]["levels"] == ("ADM3",) and seen[0]["provider"] == "geoboundaries"   # fetch_all gets the same level
    rec = json.loads((root / job["area_id"] / "area.json").read_text())
    assert rec["level_override"] == override and rec["level_choice"]["level"] == "ADM2"
    saved = client.get("/api/areas").json()[0]
    assert saved["level_override"] == override and saved["level_choice"]["level"] == "ADM2"
