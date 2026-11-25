"""OpenStreetMap via the Overpass API: existing health facilities and the road/path network."""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, mapping

from leg.data import http
from leg.data.area import Area
from leg.data.fetchers.base import Fetcher

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def overpass(query: str, url: str = OVERPASS_URL) -> dict:
    return http.post(url, data={"data": query}, timeout=300).json()


def _bbox(area: Area) -> str:
    w, s, e, n = area.bbox
    return f"{s},{w},{n},{e}"  # Overpass order: south,west,north,east


def _write(fc: dict, path: Path) -> None:
    path.write_text(json.dumps(fc, ensure_ascii=False))


DEFAULT_FACILITY_TAGS = (("amenity", "hospital"), ("amenity", "clinic"), ("amenity", "doctors"),
                         ("healthcare", "*"))


class OsmFacilitiesFetcher(Fetcher):
    """Existing health facilities matching any of `tags` ((key, value), value "*" = any).
    Points; ways/relations are reduced to their center."""
    source = "osm_facilities"
    ttl_days = 30

    def __init__(self, tags: tuple[tuple[str, str], ...] = DEFAULT_FACILITY_TAGS,
                 overpass_url: str = OVERPASS_URL):
        self.tags = tuple(tuple(t) for t in tags)
        if not self.tags:
            raise ValueError("need at least one facility tag")
        self.overpass_url = overpass_url

    def params(self) -> dict:
        return {"tags": [list(t) for t in self.tags]}

    def query(self, area: Area) -> str:
        bb = _bbox(area)
        lines = [f' nwr["{k}"]({bb});' if v == "*" else f' nwr["{k}"="{v}"]({bb});' for k, v in self.tags]
        return '[out:json][timeout:180];\n(\n' + "\n".join(lines) + '\n);\nout center tags;'

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        data = overpass(self.query(area), self.overpass_url)
        feats, seen = [], set()
        for el in data.get("elements", []):
            lon, lat = (el["lon"], el["lat"]) if "lon" in el else (el.get("center", {}).get("lon"),
                                                                    el.get("center", {}).get("lat"))
            key = (el["type"], el["id"])
            if lon is None or key in seen or not area.geometry.covers(Point(lon, lat)):
                continue
            seen.add(key)
            tags = el.get("tags", {})
            feats.append({"type": "Feature",
                          "properties": {"osm_id": f"{el['type']}/{el['id']}",
                                         "name": tags.get("name:en") or tags.get("name"),
                                         "amenity": tags.get("amenity"),
                                         "healthcare": tags.get("healthcare"),
                                         "emergency": tags.get("emergency")},
                          "geometry": {"type": "Point", "coordinates": [lon, lat]}})
        _write({"type": "FeatureCollection", "features": feats}, out_dir / "facilities.geojson")
        return {"urls": [self.overpass_url], "params": self.params(),
                "query": self.query(area), "summary": {"facilities": len(feats)}}


class OsmRoadsFetcher(Fetcher):
    """Road and footpath network (ways with highway=*), as LineStrings."""
    source = "osm_roads"
    ttl_days = 60

    DEFAULT_TYPES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                     "residential", "service", "track", "path", "footway",
                     "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
                     "living_street", "road", "pedestrian", "bridleway", "cycleway", "steps")

    def __init__(self, highway_types: tuple[str, ...] = DEFAULT_TYPES, overpass_url: str = OVERPASS_URL):
        self.highway_types = tuple(highway_types)
        self.overpass_url = overpass_url

    def params(self) -> dict:
        return {"highway_types": list(self.highway_types)}

    def query(self, area: Area) -> str:
        regex = "|".join(self.highway_types)
        return (f'[out:json][timeout:300];\n'
                f'way["highway"~"^({regex})$"]({_bbox(area)});\nout geom tags;')

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        data = overpass(self.query(area), self.overpass_url)
        feats = []
        for el in data.get("elements", []):
            pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
            if len(pts) < 2:
                continue
            line = LineString(pts)
            if not line.intersects(area.geometry):
                continue
            tags = el.get("tags", {})
            feats.append({"type": "Feature",
                          "properties": {"osm_id": f"way/{el['id']}", "highway": tags.get("highway"),
                                         "maxspeed": tags.get("maxspeed"), "oneway": tags.get("oneway")},
                          "geometry": mapping(line)})
        _write({"type": "FeatureCollection", "features": feats}, out_dir / "roads.geojson")
        return {"urls": [self.overpass_url], "params": self.params(),
                "query": self.query(area), "summary": {"ways": len(feats)}}
