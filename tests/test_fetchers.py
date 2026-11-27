"""Fetcher tests with mocked HTTP (no network)."""
import json

import pytest
import requests
import rasterio
import responses

from leg.data import Area, SnapshotCache
from leg.data.fetchers import (BoundariesFetcher, GtfsFetcher, OsmFacilitiesFetcher,
                               OsmRoadsFetcher, WorldPopFetcher)
from leg.data.fetchers.gtfs import CATALOG_URL, select_feeds
from leg.data.fetchers.osm import OVERPASS_URL


# ---------- WorldPop ----------
def test_worldpop_url_format():
    url = WorldPopFetcher(year=2026).url("isr")
    assert url.endswith("/R2025A/2026/ISR/v1/100m/constrained/isr_pop_2026_CN_100m_R2025A_v1.tif")


@responses.activate
def test_worldpop_clips_to_area(tmp_path, area, country_tif):
    f = WorldPopFetcher()
    responses.get(f.url("ISR"), body=country_tif.read_bytes())
    snap = SnapshotCache(tmp_path).get(f, area)
    with rasterio.open(snap.path / "population.tif") as r:
        assert (r.width, r.height) == (1, 1)  # the 1x1 degree area = exactly one cell
    assert snap.manifest["summary"]["total_population"] == 10.0

    # second area reuses the country download (no second HTTP call)
    other = Area.from_bbox("other", "ISR", 33.0, 31.0, 35.0, 32.0)  # 2 cells, one is nodata
    snap2 = SnapshotCache(tmp_path).get(f, other)
    assert len(responses.calls) == 1
    assert snap2.manifest["summary"]["total_population"] == 10.0  # nodata cell excluded


@responses.activate
def test_worldpop_area_outside_raster_fails(tmp_path, country_tif):
    f = WorldPopFetcher()
    responses.get(f.url("ISR"), body=country_tif.read_bytes())
    far = Area.from_bbox("far", "ISR", 10, 10, 11, 11)
    with pytest.raises(ValueError, match="does not overlap"):
        SnapshotCache(tmp_path).get(f, far)


def test_worldpop_rejects_bad_year():
    with pytest.raises(ValueError):
        WorldPopFetcher(year=2040)


# ---------- Boundaries ----------
def _square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


@responses.activate
def test_boundaries_keeps_intersecting_units(tmp_path, area):
    gj_url = "https://example.org/ISR_ADM2_simplified.geojson"
    responses.get("https://www.geoboundaries.org/api/current/gbOpen/ISR/ADM2/",
                  json={"simplifiedGeometryGeoJSON": gj_url, "gjDownloadURL": "unused"})
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"shapeName": "Inside", "shapeID": "A"},
         "geometry": _square(34.2, 30.2, 34.8, 30.8)},
        {"type": "Feature", "properties": {"shapeName": "Half", "shapeID": "B"},
         "geometry": _square(34.5, 30.0, 35.5, 31.0)},
        {"type": "Feature", "properties": {"shapeName": "Outside", "shapeID": "C"},
         "geometry": _square(36, 30, 37, 31)},
    ]}
    responses.get(gj_url, json=fc)
    snap = SnapshotCache(tmp_path).get(BoundariesFetcher(levels=("ADM2",)), area)
    out = json.loads((snap.path / "adm2.geojson").read_text())
    by_name = {f["properties"]["name"]: f["properties"] for f in out["features"]}
    assert set(by_name) == {"Inside", "Half"}
    assert by_name["Inside"]["share_inside_area"] == 1.0
    assert by_name["Half"]["share_inside_area"] == 0.5
    assert json.loads((snap.path / "districts.geojson").read_text()) == out
    full = json.loads((snap.path / "districts_full.geojson").read_text())["features"]
    half = next(f for f in full if f["properties"]["name"] == "Half")
    assert half["geometry"] == _square(34.5, 30.0, 35.5, 31.0) and half["properties"]["fully_inside"] is False
    assert snap.manifest["summary"]["districts"] == 2


# ---------- OSM ----------
@responses.activate
def test_osm_facilities_filters_and_dedups(tmp_path, area):
    responses.post(OVERPASS_URL, json={"elements": [
        {"type": "node", "id": 1, "lat": 30.5, "lon": 34.5, "tags": {"amenity": "clinic", "name": "In"}},
        {"type": "node", "id": 1, "lat": 30.5, "lon": 34.5, "tags": {"amenity": "clinic"}},  # dup
        {"type": "way", "id": 2, "center": {"lat": 30.6, "lon": 34.6}, "tags": {"healthcare": "hospital"}},
        {"type": "node", "id": 3, "lat": 35.0, "lon": 36.0, "tags": {"amenity": "doctors"}},  # outside
    ]})
    snap = SnapshotCache(tmp_path).get(OsmFacilitiesFetcher(), area)
    feats = json.loads((snap.path / "facilities.geojson").read_text())["features"]
    assert [f["properties"]["osm_id"] for f in feats] == ["node/1", "way/2"]
    assert "30.0,34.0,31.0,35.0" in snap.manifest["query"]  # south,west,north,east


@responses.activate
def test_osm_roads_builds_lines(tmp_path, area):
    responses.post(OVERPASS_URL, json={"elements": [
        {"type": "way", "id": 10, "tags": {"highway": "primary"},
         "geometry": [{"lat": 30.1, "lon": 34.1}, {"lat": 30.9, "lon": 34.9}]},
        {"type": "way", "id": 11, "tags": {"highway": "path"}, "geometry": [{"lat": 30.1, "lon": 34.1}]},
    ]})
    snap = SnapshotCache(tmp_path).get(OsmRoadsFetcher(), area)
    feats = json.loads((snap.path / "roads.geojson").read_text())["features"]
    assert len(feats) == 1 and feats[0]["geometry"]["type"] == "LineString"


# ---------- GTFS ----------
CATALOG = """id,data_type,location.country_code,status,redirect.id,urls.authentication_type,urls.direct_download,urls.latest,provider,name,location.bounding_box.minimum_longitude,location.bounding_box.minimum_latitude,location.bounding_box.maximum_longitude,location.bounding_box.maximum_latitude
mdb-1,gtfs,IL,active,,0,https://x/il.zip,https://m/il.zip,MOT,Israel,34.2,29.4,35.9,33.3
mdb-2,gtfs,IL,active,,2,https://x/key.zip,,Keyed,,34,30,35,31
mdb-3,gtfs,IL,deprecated,,0,https://x/old.zip,,Old,,34,30,35,31
mdb-4,gtfs,IL,active,,0,https://x/north.zip,,North,,35.5,32.5,35.9,33.2
mdb-5,gtfs_rt,IL,active,,0,https://x/rt,,RT,,34,30,35,31
mdb-6,gtfs,FR,active,,0,https://x/fr.zip,,FR,,2,48,3,49
mdb-7,gtfs,IL,,,,https://x/nobbox.zip,,NoBBox,,,,,
"""


def test_gtfs_feed_selection(area):
    ids = [f["id"] for f in select_feeds(CATALOG, area)]
    assert ids == ["mdb-1", "mdb-7"]


@responses.activate
def test_gtfs_downloads_selected_feeds(tmp_path, area):
    responses.get(CATALOG_URL, body=CATALOG)
    responses.get("https://m/il.zip", body=b"PK-fake-zip")
    responses.get("https://x/nobbox.zip", body=b"PK-fake-zip-2")
    snap = SnapshotCache(tmp_path).get(GtfsFetcher(max_feeds=1), area)
    feeds = json.loads((snap.path / "feeds.json").read_text())
    assert [f["file"] for f in feeds] == ["gtfs_mdb-1.zip"]
    assert snap.manifest["summary"] == {"feeds": 1, "skipped_over_limit": 1}


def _ring(x0, y0, x1, y1):
    return [{"lat": y0, "lon": x0}, {"lat": y0, "lon": x1}, {"lat": y1, "lon": x1},
            {"lat": y1, "lon": x0}, {"lat": y0, "lon": x0}]


@responses.activate
def test_boundaries_osm_municipalities(tmp_path, area):
    # one municipality split into two outer ways, with a hole; one outside the area
    responses.post(OVERPASS_URL, json={"elements": [
        {"type": "relation", "id": 7, "tags": {"name": "עיר", "name:en": "Town", "admin_level": "8"},
         "members": [
             {"type": "way", "role": "outer", "geometry": [{"lat": 30.2, "lon": 34.2}, {"lat": 30.2, "lon": 34.8},
                                                           {"lat": 30.8, "lon": 34.8}]},
             {"type": "way", "role": "outer", "geometry": [{"lat": 30.8, "lon": 34.8}, {"lat": 30.8, "lon": 34.2},
                                                           {"lat": 30.2, "lon": 34.2}]},
             {"type": "way", "role": "inner", "geometry": _ring(34.4, 30.4, 34.6, 30.6)},
         ]},
        {"type": "relation", "id": 8, "tags": {"name": "Far"},
         "members": [{"type": "way", "role": "outer", "geometry": _ring(36, 30, 37, 31)}]},
    ]})
    f = BoundariesFetcher(provider="osm", levels=("8",))
    snap = SnapshotCache(tmp_path).get(f, area)
    feats = json.loads((snap.path / "districts.geojson").read_text())["features"]
    assert len(feats) == 1
    p = feats[0]["properties"]
    assert (p["name"], p["name_local"], p["unit_id"], p["level"]) == ("Town", "עיר", "relation/7", "8")
    from shapely.geometry import shape
    assert abs(shape(feats[0]["geometry"]).area - (0.36 - 0.04)) < 1e-9  # hole subtracted
    assert (snap.path / "osm_admin8.geojson").exists()


def test_boundaries_rejects_unknown_provider():
    with pytest.raises(ValueError):
        BoundariesFetcher(provider="gadm")


def test_facility_query_from_tags(area):
    q = OsmFacilitiesFetcher(tags=(("amenity", "hospital"), ("emergency", "ambulance_station"),
                                   ("healthcare", "*"))).query(area)
    assert 'nwr["amenity"="hospital"]' in q
    assert 'nwr["emergency"="ambulance_station"]' in q
    assert 'nwr["healthcare"](' in q



@responses.activate
def test_overpass_falls_back_to_mirror_and_rejects_partial(tmp_path, area):
    from leg.data.fetchers.osm import OVERPASS_MIRRORS, overpass
    responses.post(OVERPASS_MIRRORS[0], body=requests.ReadTimeout("slow"))
    responses.post(OVERPASS_MIRRORS[1], json={"elements": [], "remark": "runtime error: Query timed out"})
    responses.post(OVERPASS_MIRRORS[2], json={"elements": [{"type": "node", "id": 1}]})
    assert overpass("q")["elements"] == [{"type": "node", "id": 1}]
    assert [c.request.url for c in responses.calls] == list(OVERPASS_MIRRORS)


@responses.activate
def test_overpass_timeout_everywhere_saves_no_snapshot(tmp_path, area):
    from leg.data.fetchers.osm import OVERPASS_MIRRORS
    for u in OVERPASS_MIRRORS:
        responses.post(u, json={"elements": [], "remark": "runtime error: Query timed out"})
    cache = SnapshotCache(tmp_path)
    with pytest.raises(RuntimeError, match="did not finish"):
        cache.get(OsmFacilitiesFetcher(), area)
    assert cache.list(area, "osm_facilities") == []


# ---------- Malaria Atlas friction ----------
def _friction_tif(tmp_path):
    import numpy as np
    from rasterio.transform import from_origin
    p = tmp_path / "f.tif"
    with rasterio.open(p, "w", driver="GTiff", height=2, width=2, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(34.0, 32.0, 1 / 120, 1 / 120), nodata=-9999) as d:
        d.write(np.array([[[0.012, 0.02], [-9999, 0.015]]], dtype="float32"))
    return p.read_bytes()


@responses.activate
def test_friction_fetch_and_axis_fallback(tmp_path, area):
    from leg.data.fetchers import FrictionFetcher
    from leg.data.fetchers.friction import AXES, WCS_URL
    f = FrictionFetcher()
    responses.get(WCS_URL, body=b"<ows:ExceptionReport>bad axis</ows:ExceptionReport>")  # first axis names
    responses.get(WCS_URL, body=_friction_tif(tmp_path))
    snap = SnapshotCache(tmp_path / "c").get(f, area)
    assert snap.manifest["summary"]["valid_pixels"] == 3
    assert "subset=lat(" in snap.manifest["urls"][0] and AXES[1] == ("lat", "long")
    assert "Walking_Only_Friction" in responses.calls[0].request.url
    w, s, e, n = area.bbox
    assert f"Long({w - 0.1}," in responses.calls[0].request.url  # 0.1 degree margin


@responses.activate
def test_friction_error_saves_no_snapshot(tmp_path, area):
    from leg.data.fetchers import FrictionFetcher
    from leg.data.fetchers.friction import WCS_URL
    responses.get(WCS_URL, body=b"<xml>nope</xml>")
    with pytest.raises(RuntimeError, match="friction download failed"):
        SnapshotCache(tmp_path).get(FrictionFetcher(), area)
    assert not list((tmp_path / area.area_id / "friction").glob("*/manifest.json"))


def test_friction_rejects_bad_mode():
    from leg.data.fetchers import FrictionFetcher
    with pytest.raises(ValueError):
        FrictionFetcher(mode="flying")


def test_roads_tiles_and_dedup(tmp_path):
    from leg.data.fetchers.osm import tiles
    assert len(tiles((34.0, 30.0, 35.2, 31.0), 0.5)) == 3 * 2
    big = Area.from_bbox("big", "ISR", 34.0, 30.0, 35.0, 31.0)
    way = {"type": "way", "id": 7, "tags": {"highway": "track"},
           "geometry": [{"lat": 30.4, "lon": 34.4}, {"lat": 30.6, "lon": 34.6}]}  # crosses all 4 tiles
    with responses.RequestsMock() as rs:
        rs.post(OVERPASS_URL, json={"elements": [way]})
        snap = SnapshotCache(tmp_path).get(OsmRoadsFetcher(tile_deg=0.5), big)
        assert len(rs.calls) == 4
    s = snap.manifest["summary"]
    assert s["ways"] == 1 and s["tiles"] == 4 and s["splits"] == 0


def test_roads_splits_a_tile_that_times_out(tmp_path):
    small = Area.from_bbox("s", "ISR", 34.0, 30.0, 34.4, 30.4)  # one tile
    way = {"type": "way", "id": 1, "tags": {"highway": "path"},
           "geometry": [{"lat": 30.1, "lon": 34.1}, {"lat": 30.2, "lon": 34.2}]}
    with responses.RequestsMock() as rs:
        rs.post(OVERPASS_URL, body=requests.Timeout("slow"))      # whole tile: too big
        rs.post(OVERPASS_URL, json={"elements": [way]})            # each quarter answers
        snap = SnapshotCache(tmp_path).get(OsmRoadsFetcher(), small)
        assert len(rs.calls) == 1 + 4   # no mirror tried for the timeout; split at once
    s = snap.manifest["summary"]
    assert s["splits"] == 1 and s["queries"] == 4 and s["ways"] == 1


def test_roads_gives_up_after_max_splits(tmp_path):
    small = Area.from_bbox("s", "ISR", 34.0, 30.0, 34.4, 30.4)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rs:
        rs.post(OVERPASS_URL, json={"remark": "runtime error: Query timed out in \"query\" at line 2"})
        with pytest.raises(RuntimeError, match="after 1 splits"):
            SnapshotCache(tmp_path).get(OsmRoadsFetcher(max_splits=1), small)
        assert len(rs.calls) == 2   # the whole tile, then the first quarter: it stops there
    assert not list((tmp_path / small.area_id / "osm_roads").glob("*/manifest.json"))


def test_osm_boundaries_timeout_does_not_retry_on_mirrors(tmp_path, area):
    """A timed-out border query is too heavy: one server, then fail (no 3 x 180 s wait)."""
    from leg.data.fetchers import BoundariesFetcher
    from leg.data.fetchers.osm import OVERPASS_MIRRORS, QueryTooBig
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rs:
        for u in OVERPASS_MIRRORS:
            rs.post(u, body=requests.Timeout("slow"))
        with pytest.raises(QueryTooBig):
            SnapshotCache(tmp_path).get(BoundariesFetcher(provider="osm", levels=("6",)), area)
        assert len(rs.calls) == 1


def test_osm_boundaries_busy_server_tries_mirror(tmp_path, area):
    from leg.data.fetchers import BoundariesFetcher
    from leg.data.fetchers.osm import OVERPASS_MIRRORS
    w, s, e, n = area.bbox
    rel = {"type": "relation", "id": 5, "tags": {"name": "R", "admin_level": "6", "boundary": "administrative"},
           "members": [{"type": "way", "role": "outer", "geometry": [
               {"lat": s, "lon": w}, {"lat": s, "lon": e}, {"lat": n, "lon": e}, {"lat": n, "lon": w}, {"lat": s, "lon": w}]}]}
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rs:
        rs.post(OVERPASS_MIRRORS[0], status=429)
        rs.post(OVERPASS_MIRRORS[1], json={"elements": [rel]})
        snap = SnapshotCache(tmp_path).get(BoundariesFetcher(provider="osm", levels=("6",)), area)
        assert len(rs.calls) == 2
    assert snap.manifest["summary"]["districts"] == 1
