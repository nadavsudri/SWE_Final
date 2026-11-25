"""Fetcher tests with mocked HTTP (no network)."""
import json

import pytest
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
