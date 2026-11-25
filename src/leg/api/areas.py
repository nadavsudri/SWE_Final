"""Area validation for the UI, the country-border check, and the list of areas already cached."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pycountry
import shapely
from shapely.geometry import box, shape
from shapely.validation import explain_validity

from leg.data import Area, http
from leg.data.cache import MANIFEST
from leg.data.profile import _area_km2

ADM0_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM0/"


def parse_area(name: str, iso3: str, geojson) -> tuple[Area | None, list[str]]:
    """Build an Area the way the fetchers will see it, or return readable errors."""
    errors = []
    if not (name or "").strip():
        errors.append("Name is required.")
    if not iso3 or pycountry.countries.get(alpha_3=iso3.upper()) is None:
        errors.append("Choose a country.")
    if geojson in (None, "", {}):
        errors.append("Draw an area or upload a GeoJSON file.")
        return None, errors
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except json.JSONDecodeError as e:
            return None, errors + [f"Not valid JSON ({e.msg}, line {e.lineno})."]
    if not isinstance(geojson, dict) or "type" not in geojson:
        return None, errors + ["Not GeoJSON: the file has no \"type\"."]
    if geojson["type"] == "FeatureCollection":
        n = len(geojson.get("features") or [])
        if n != 1:
            return None, errors + [f"The file contains {n} features, expected 1."]
        geojson = geojson["features"][0]
    if geojson.get("type") == "Feature":
        geojson = geojson.get("geometry") or {}
    try:
        geom = shape(geojson)
    except Exception as e:  # malformed coordinates
        return None, errors + [f"Not a valid geometry ({e})."]
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        return None, errors + [f"The area must be a Polygon or MultiPolygon, not a {geom.geom_type}."]
    if not geom.is_valid:
        return None, errors + [f"The shape is invalid: {explain_validity(geom)}. Move a vertex or redraw."]
    if errors:
        return None, errors
    try:
        # An axis-aligned rectangle becomes the same Area as `--bbox`, so it shares the CLI's cache.
        if geom.equals(box(*geom.bounds)):
            return Area.from_bbox(name.strip(), iso3, *geom.bounds), []
        return Area(name.strip(), iso3, geom), []
    except ValueError as e:
        return None, [str(e)]


class CountryBorders:
    """geoBoundaries ADM0 outlines, downloaded once per country into <root>/_downloads."""

    RETRY_AFTER_S = 120

    def __init__(self, root: Path):
        self.downloads = Path(root) / "_downloads"
        self._geoms: dict[str, object] = {}
        self._failed: dict[str, float] = {}
        self._lock = threading.Lock()

    def _cached_file(self, iso3: str) -> Path | None:
        hits = sorted(self.downloads.glob(f"{iso3}_ADM0_*.geojson")) if self.downloads.exists() else []
        return hits[0] if hits else None

    def get(self, iso3: str):
        """Shapely geometry of the country, or None when it can't be had (offline, first time)."""
        iso3 = iso3.upper()
        with self._lock:
            if iso3 in self._geoms:
                return self._geoms[iso3]
            if time.monotonic() - self._failed.get(iso3, -1e9) < self.RETRY_AFTER_S:
                return None
            path = self._cached_file(iso3)
            if path is None:
                try:
                    meta = http.get_json(ADM0_API.format(iso3=iso3), timeout=15)
                    url = meta["simplifiedGeometryGeoJSON"]
                    path = http.download(url, self.downloads / f"{iso3}_ADM0_{Path(url).name}",
                                         cache_dir=self.downloads)
                except Exception:
                    self._failed[iso3] = time.monotonic()
                    return None
            fc = json.loads(path.read_text())
            geom = shapely.union_all([shape(f["geometry"]) for f in fc["features"]])
            self._geoms[iso3] = geom
            return geom


def check_area(area: Area, borders: CountryBorders, warn_km2: float, max_km2: float) -> dict:
    km2 = _area_km2(area)
    warnings, errors = [], []
    if km2 > max_km2:
        errors.append({"code": "too_large",
                       "message": f"{km2:,.0f} km² is over the {max_km2:,.0f} km² limit. Draw a smaller area."})
    elif km2 > warn_km2:
        warnings.append({"code": "large",
                         "message": f"{km2:,.0f} km² is a big area: the road and facility queries will be slow "
                                    f"and can time out (warning above {warn_km2:,.0f} km²)."})
    country = pycountry.countries.get(alpha_3=area.iso3)
    border = borders.get(area.iso3)
    if border is None:
        warnings.append({"code": "border_unknown",
                         "message": "Couldn't check the country border: the outline isn't cached and the "
                                    "network isn't reachable."})
    else:
        inside = area.geometry.intersection(border).area / area.geometry.area
        if inside < 0.995:
            name = getattr(country, "common_name", country.name)
            warnings.append({"code": "outside_country", "share_outside": round(1 - inside, 3),
                             "message": f"About {100 * (1 - inside):.0f}% of the area is outside {name}. "
                                        "Sources only have data inside the country. You can still fetch."})
    return {"area_id": area.area_id, "bbox": list(area.bbox), "km2": round(km2, 1),
            "iso2": area.iso2, "warnings": warnings, "errors": errors}


def saved_areas(root: Path) -> list[dict]:
    """Every folder in the cache root with at least one manifest, newest snapshot first."""
    root = Path(root)
    out = []
    if not root.exists():
        return out
    from leg.api import modes  # local import: modes imports sources, which imports leg.data
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name[0] not in "._")
    records = {d.name: modes.read_record(d) for d in dirs}
    # a snapped area's drawing gets its own folder (its districts, for snapping): not an area of its own
    drawings = {r.get("drawn_area_id") for r in records.values() if r and r.get("mode") == "snap"}
    for d in dirs:
        rec = records[d.name]
        if d.name in drawings and not rec:
            continue
        manifests = sorted(d.glob(f"*/*/{MANIFEST}"))
        if not manifests and not rec:
            continue
        sources, newest = {}, None
        for m in manifests:
            try:
                data = json.loads(m.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            src = m.parent.parent.name
            sources.setdefault(src, []).append(m.parent.name)
            if newest is None or data.get("fetched_at", "") > newest[0].get("fetched_at", ""):
                newest = (data, m)
        if newest is None and rec is None:
            continue
        if newest is None:  # area.json only (e.g. snapped, sources not fetched yet)
            newest = ({"area": rec["drawn_area"], "fetched_at": rec.get("created_at")}, None)
        feat = newest[0]["area"]
        props = feat.get("properties", {})
        try:
            area = Area.from_geojson(props.get("name", d.name), props.get("iso3", "XXX"), feat)
            km2 = round(_area_km2(area), 1)
        except ValueError:
            km2 = None
        out.append({"area_id": d.name, "name": props.get("name"), "iso3": props.get("iso3"),
                    "geojson": feat, "km2": km2, "bbox": list(shape(feat["geometry"]).bounds),
                    "sources": {s: sorted(v) for s, v in sorted(sources.items())},
                    "newest_fetched_at": newest[0].get("fetched_at"),
                    **(modes.restore_fields(rec) if rec else {"mode": None})})
    out.sort(key=lambda a: a["newest_fetched_at"] or "", reverse=True)
    return out
