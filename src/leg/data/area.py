"""The study area: a country plus a region inside it (bbox or polygon)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pycountry
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Area:
    name: str            # human label, e.g. "negev"
    iso3: str            # country, e.g. "ISR"
    geometry: BaseGeometry  # WGS84 (lon, lat)

    def __post_init__(self):
        country = pycountry.countries.get(alpha_3=self.iso3.upper())
        if country is None:
            raise ValueError(f"Unknown ISO3 country code: {self.iso3!r}")
        object.__setattr__(self, "iso3", country.alpha_3)
        if self.geometry.is_empty or not self.geometry.is_valid:
            raise ValueError("Area geometry is empty or invalid")
        minx, miny, maxx, maxy = self.geometry.bounds
        if not (-180 <= minx < maxx <= 180 and -90 <= miny < maxy <= 90):
            raise ValueError(f"Bounds out of range (expected lon/lat): {self.geometry.bounds}")

    # --- constructors -------------------------------------------------------
    @classmethod
    def from_bbox(cls, name: str, iso3: str, west: float, south: float, east: float, north: float) -> "Area":
        if west >= east or south >= north:
            raise ValueError("bbox must be west < east and south < north")
        return cls(name, iso3, box(west, south, east, north))

    @classmethod
    def from_geojson(cls, name: str, iso3: str, geojson: dict | str | Path) -> "Area":
        """Accepts a Geometry, Feature or single-feature FeatureCollection (what a map UI emits)."""
        if isinstance(geojson, (str, Path)):
            geojson = json.loads(Path(geojson).read_text())
        if geojson.get("type") == "FeatureCollection":
            feats = geojson["features"]
            if len(feats) != 1:
                raise ValueError("FeatureCollection must contain exactly one feature")
            geojson = feats[0]
        if geojson.get("type") == "Feature":
            geojson = geojson["geometry"]
        return cls(name, iso3, shape(geojson))

    # --- helpers ------------------------------------------------------------
    @property
    def iso2(self) -> str:
        return pycountry.countries.get(alpha_3=self.iso3).alpha_2

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(west, south, east, north)"""
        return self.geometry.bounds

    @property
    def area_id(self) -> str:
        """Stable folder name: slug + short hash of the geometry, so two areas never collide."""
        slug = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-") or "area"
        digest = hashlib.sha1(self.geometry.wkb).hexdigest()[:8]
        return f"{self.iso3.lower()}_{slug}_{digest}"

    def to_geojson(self) -> dict:
        return {"type": "Feature", "properties": {"name": self.name, "iso3": self.iso3},
                "geometry": mapping(self.geometry)}
