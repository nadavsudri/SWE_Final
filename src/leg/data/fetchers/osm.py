"""OpenStreetMap via the Overpass API: existing health facilities and the road/path network."""
from __future__ import annotations

import json
import math
from pathlib import Path

import requests
from shapely.geometry import LineString, Point, box, mapping

from leg.data import http
from leg.data.area import Area
from leg.data.fetchers.base import Fetcher

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# Public Overpass servers. The main one is often overloaded; on a timeout, connection error or
# server error the next one is tried. A custom url (tests, own server) is used alone.
OVERPASS_MIRRORS = (OVERPASS_URL, "https://overpass.private.coffee/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter")


class QueryTooBig(RuntimeError):
    """The server ran out of time or memory on the query: a smaller query may work."""


def overpass(query: str, url: str = OVERPASS_URL, timeout: float = 180, split_on_timeout: bool = False) -> dict:
    """With split_on_timeout, a timeout (or a timed-out / out-of-memory answer) raises QueryTooBig
    at once instead of trying the other servers: the query is too big, not the server too busy."""
    urls = OVERPASS_MIRRORS if url == OVERPASS_URL else (url,)
    last: Exception | None = None
    for u in urls:
        try:
            data = http.post(u, data={"data": query}, timeout=timeout, retries=1).json()
        except requests.Timeout as e:
            if split_on_timeout:
                raise QueryTooBig(f"Overpass ({u}) timed out after {timeout:g} s") from e
            last = e
            continue
        except requests.ConnectionError as e:
            last = e
            continue
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (429, 500, 502, 503, 504):
                last = e
                continue
            raise
        remark = str(data.get("remark", ""))
        if "runtime error" in remark or "timed out" in remark:  # partial answer: don't trust it
            msg = f"Overpass ({u}) did not finish the query: {remark[:200]}"
            if split_on_timeout and ("timed out" in remark or "out of memory" in remark):
                raise QueryTooBig(msg)
            last = RuntimeError(msg)
            continue
        return data
    raise last  # every server failed; the caller reports which source


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


def tiles(bbox: tuple[float, float, float, float], size: float) -> list[tuple[float, float, float, float]]:
    """Split (west, south, east, north) into tiles of at most size x size degrees."""
    w, s, e, n = bbox
    nx, ny = max(1, math.ceil((e - w) / size - 1e-9)), max(1, math.ceil((n - s) / size - 1e-9))
    dx, dy = (e - w) / nx, (n - s) / ny
    return [(w + i * dx, s + j * dy, w + (i + 1) * dx, s + (j + 1) * dy) for j in range(ny) for i in range(nx)]


def _quarters(t):
    w, s, e, n = t
    mx, my = (w + e) / 2, (s + n) / 2
    return [(w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)]


class OsmRoadsFetcher(Fetcher):
    """Road and footpath network (ways with highway=*), as LineStrings.

    One query for a large area is too much for the public Overpass servers (hundreds of thousands
    of paths and tracks), so the area is queried in tiles of `tile_deg`; a tile that still times
    out is split in four, up to `max_splits` times. Ways crossing tiles are kept once."""
    source = "osm_roads"
    ttl_days = 60
    QUERY_TIMEOUT = 120   # seconds the server may spend on one tile
    HTTP_TIMEOUT = 150    # the client waits a bit longer than the server

    DEFAULT_TYPES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                     "residential", "service", "track", "path", "footway",
                     "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
                     "living_street", "road", "pedestrian", "bridleway", "cycleway", "steps")

    def __init__(self, highway_types: tuple[str, ...] = DEFAULT_TYPES, overpass_url: str = OVERPASS_URL,
                 tile_deg: float = 0.5, max_splits: int = 2):
        self.highway_types = tuple(highway_types)
        if not self.highway_types:
            raise ValueError("need at least one highway type")
        if not 0.05 <= tile_deg <= 5:
            raise ValueError("tile_deg must be between 0.05 and 5")
        self.overpass_url, self.tile_deg, self.max_splits = overpass_url, tile_deg, max_splits

    def params(self) -> dict:
        # tiling doesn't change the result, so it is not part of the cache key
        return {"highway_types": list(self.highway_types)}

    def query(self, area_or_bbox) -> str:
        regex = "|".join(self.highway_types)
        if isinstance(area_or_bbox, Area):
            bb = _bbox(area_or_bbox)
        else:
            w, s, e, n = area_or_bbox
            bb = f"{s},{w},{n},{e}"
        return (f'[out:json][timeout:{self.QUERY_TIMEOUT}];\n'
                f'way["highway"~"^({regex})$"]({bb});\nout geom tags;')

    def _tile(self, t, depth: int, stats: dict) -> list[dict]:
        try:
            data = overpass(self.query(t), self.overpass_url, timeout=self.HTTP_TIMEOUT, split_on_timeout=True)
            stats["queries"] += 1
            return data.get("elements", [])
        except QueryTooBig as e:  # other failures (every server down or busy) are not helped by splitting
            if depth >= self.max_splits:
                raise RuntimeError(f"roads tile {tuple(round(x, 3) for x in t)} failed after "
                                   f"{depth} splits: {type(e).__name__}: {e}") from e
            stats["splits"] += 1
            return [el for q in _quarters(t) for el in self._tile(q, depth + 1, stats)]

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        todo = [t for t in tiles(area.bbox, self.tile_deg) if box(*t).intersects(area.geometry)]
        stats = {"tiles": len(todo), "queries": 0, "splits": 0}
        feats, seen = [], set()
        for t in todo:
            for el in self._tile(t, 0, stats):
                if el.get("id") in seen:
                    continue
                pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
                if len(pts) < 2:
                    continue
                line = LineString(pts)
                if not line.intersects(area.geometry):
                    continue
                seen.add(el.get("id"))
                tags = el.get("tags", {})
                feats.append({"type": "Feature",
                              "properties": {"osm_id": f"way/{el['id']}", "highway": tags.get("highway"),
                                             "maxspeed": tags.get("maxspeed"), "oneway": tags.get("oneway")},
                              "geometry": mapping(line)})
        _write({"type": "FeatureCollection", "features": feats}, out_dir / "roads.geojson")
        return {"urls": [self.overpass_url], "params": self.params(),
                "query": self.query(area), "summary": {"ways": len(feats), **stats}}
