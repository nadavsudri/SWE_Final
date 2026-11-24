"""Administrative boundaries ("districts"), clipped to the area.

Providers:
- geoboundaries: levels ADM1..ADM5 (good for most countries)
- osm:           OSM admin_level numbers, e.g. "8" = municipalities in Israel

Writes one file per level plus districts.geojson (= the last, finest level). Every feature has
the same properties: name, unit_id, level, share_inside_area.
"""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, mapping, shape
from shapely.ops import polygonize, unary_union

from leg.data import http
from leg.data.area import Area
from leg.data.fetchers.base import Fetcher
from leg.data.fetchers.osm import OVERPASS_URL, _bbox, overpass

API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{level}/"


class BoundariesFetcher(Fetcher):
    source = "boundaries"
    ttl_days = 365  # borders rarely change

    def __init__(self, levels: tuple[str, ...] = ("ADM1", "ADM2"), simplified: bool = True,
                 provider: str = "geoboundaries", overpass_url: str = OVERPASS_URL):
        if provider not in ("geoboundaries", "osm"):
            raise ValueError("provider must be 'geoboundaries' or 'osm'")
        self.levels = tuple(str(lv) for lv in levels)
        self.simplified = simplified
        self.provider = provider
        self.overpass_url = overpass_url

    def params(self) -> dict:
        p = {"provider": self.provider, "levels": list(self.levels)}
        if self.provider == "geoboundaries":
            p["simplified"] = self.simplified
        return p

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        urls, counts, last = [], {}, None
        for level in self.levels:
            if self.provider == "geoboundaries":
                fc, used = self._geoboundaries(area, level, downloads_dir)
                fname = f"{level.lower()}.geojson"
            else:
                fc, used = self._osm(area, level)
                fname = f"osm_admin{level}.geojson"
            fc = clip_features(fc, area, level)
            (out_dir / fname).write_text(json.dumps(fc, ensure_ascii=False))
            urls += used
            counts[level] = len(fc["features"])
            last = fc
        if not counts[self.levels[-1]]:
            raise ValueError(f"No {self.provider} level-{self.levels[-1]} units intersect the area")
        (out_dir / "districts.geojson").write_text(json.dumps(last, ensure_ascii=False))
        return {"urls": urls, "params": self.params(),
                "summary": {"units": counts, "districts": counts[self.levels[-1]]}}

    def _geoboundaries(self, area: Area, level: str, downloads_dir: Path) -> tuple[dict, list[str]]:
        meta_url = API.format(iso3=area.iso3, level=level)
        meta = http.get_json(meta_url)
        gj_url = meta["simplifiedGeometryGeoJSON" if self.simplified else "gjDownloadURL"]
        raw = http.download(gj_url, downloads_dir / f"{area.iso3}_{level}_{Path(gj_url).name}",
                            cache_dir=downloads_dir)
        fc = json.loads(raw.read_text())
        for f in fc["features"]:
            p = f["properties"]
            p["name"], p["unit_id"] = p.get("shapeName"), p.get("shapeID")
        return fc, [meta_url, gj_url]

    def _osm(self, area: Area, level: str) -> tuple[dict, list[str]]:
        q = (f'[out:json][timeout:300];\n'
             f'relation["boundary"="administrative"]["admin_level"="{level}"]({_bbox(area)});\n'
             f'out geom tags;')
        data = overpass(q, self.overpass_url)
        feats = []
        for el in data.get("elements", []):
            geom = relation_to_polygon(el)
            if geom is None:
                continue
            tags = el.get("tags", {})
            feats.append({"type": "Feature",
                          "properties": {"name": tags.get("name:en") or tags.get("name"),
                                         "name_local": tags.get("name"),
                                         "unit_id": f"relation/{el['id']}"},
                          "geometry": mapping(geom)})
        return {"type": "FeatureCollection", "features": feats}, [self.overpass_url]


def relation_to_polygon(rel: dict):
    """Assemble an OSM multipolygon relation (outer/inner way members with geometry) into shapely."""
    outer, inner = [], []
    for m in rel.get("members", []):
        pts = [(p["lon"], p["lat"]) for p in m.get("geometry", []) if p]
        if m.get("type") != "way" or len(pts) < 2:
            continue
        (inner if m.get("role") == "inner" else outer).append(LineString(pts))
    polys = list(polygonize(unary_union(outer))) if outer else []
    if not polys:
        return None
    geom = unary_union(polys)
    holes = list(polygonize(unary_union(inner))) if inner else []
    if holes:
        geom = geom.difference(unary_union(holes))
    return geom if not geom.is_empty else None


def clip_features(fc: dict, area: Area, level: str) -> dict:
    """Keep units that intersect the area; geometry cut to the area, original share kept."""
    out = []
    for f in fc["features"]:
        geom = shape(f["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        if not geom.intersects(area.geometry):
            continue
        clipped = geom.intersection(area.geometry)
        if clipped.area == 0:  # touches only along an edge
            continue
        src = f["properties"]
        props = {"name": src.get("name"), "unit_id": src.get("unit_id"), "level": level,
                 "share_inside_area": round(clipped.area / geom.area, 4) if geom.area else 0.0}
        if "name_local" in src:
            props["name_local"] = src["name_local"]
        out.append({"type": "Feature", "properties": props, "geometry": mapping(clipped)})
    return {"type": "FeatureCollection", "features": out}
