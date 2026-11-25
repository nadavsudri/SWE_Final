"""Public health facilities in sub-Saharan Africa (Maina et al. 2019, KEMRI-Wellcome / WHO GMP).

98,745 geocoded public facilities from national master facility lists in 50 countries. OSM is
very sparse there (one facility for ~2 million people in a test area in Ethiopia), so this is the
main facility source for those countries.

The dataset is an Excel file without a stable direct-download URL, so it is downloaded once by
hand and placed at  <cache root>/_manual/ssa_public_health_facilities.xlsx  (.csv also works).
- Country outside sub-Saharan Africa: empty result with a note (not an error).
- Country inside it and the file missing: an error that says where to get it and where to put it.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pycountry
from shapely.geometry import Point

from leg.data.area import Area
from leg.data.fetchers.base import Fetcher

FILE_STEM = "ssa_public_health_facilities"
SOURCE_URL = "https://www.who.int/publications/m/item/who-cds-gmp-2019-01"
CITATION = ("Maina J. et al. (2019) A spatial database of health facilities managed by the public "
            "health sector in sub Saharan Africa. Scientific Data 6:134. doi:10.1038/s41597-019-0142-2")

# UN M49 sub-Saharan Africa
SSA_ISO3 = set("""AGO BDI BEN BFA BWA CAF CIV CMR COD COG COM CPV DJI ERI ETH GAB GHA GIN GMB GNB GNQ
KEN LBR LSO MDG MLI MOZ MRT MUS MWI MYT NAM NER NGA REU RWA SDN SEN SHN SLE SOM SSD STP SWZ SYC TCD
TGO TZA UGA ZAF ZMB ZWE""".split())

# header keyword -> our field (matched case-insensitively, first hit wins)
COLUMNS = {
    "country": ("country",),
    "admin1": ("admin1", "admin 1", "region"),
    "name": ("facility name", "facility_name", "name"),
    "type": ("facility type", "facility_type", "type"),
    "ownership": ("ownership", "owner"),
    "lat": ("lat",),
    "lon": ("long", "lon"),
}


def manual_path(downloads_dir: Path) -> Path | None:
    base = downloads_dir.parent / "_manual"
    for ext in (".xlsx", ".csv"):
        p = base / f"{FILE_STEM}{ext}"
        if p.exists():
            return p
    return None


def _rows(path: Path):
    if path.suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            yield from csv.reader(f)
        return
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    for row in wb.worksheets[0].iter_rows(values_only=True):
        yield ["" if v is None else v for v in row]


def _map_header(header: list) -> dict[str, int]:
    h = [str(x).strip().lower() for x in header]
    out = {}
    for field, keys in COLUMNS.items():
        for k in keys:
            hit = next((i for i, col in enumerate(h) if col == k or col.startswith(k)), None)
            if hit is not None and hit not in out.values():
                out[field] = hit
                break
    missing = {"country", "lat", "lon"} - out.keys()
    if missing:
        raise ValueError(f"Facility file is missing columns {sorted(missing)}; header was {header}")
    return out


_iso_cache: dict[str, str | None] = {}
# names pycountry doesn't resolve on its own
ALIASES = {"democratic republic of the congo": "COD", "dr congo": "COD", "drc": "COD",
           "congo-brazzaville": "COG", "republic of congo": "COG", "republic of the congo": "COG",
           "swaziland": "SWZ", "cape verde": "CPV", "ivory coast": "CIV", "the gambia": "GMB",
           "tanzania": "TZA", "sao tome and principe": "STP", "south sudan": "SSD",
           "guinea bissau": "GNB", "guinea-bissau": "GNB", "eswatini": "SWZ"}


def country_iso3(name: str) -> str | None:
    """Country name as written in the dataset -> ISO3 (None if unknown)."""
    if name.strip().lower() in ALIASES:
        return ALIASES[name.strip().lower()]
    if name not in _iso_cache:
        try:
            _iso_cache[name] = pycountry.countries.lookup(name).alpha_3
        except LookupError:
            try:
                _iso_cache[name] = pycountry.countries.search_fuzzy(name)[0].alpha_3
            except LookupError:
                _iso_cache[name] = None
    return _iso_cache[name]


def read_facilities(path: Path, area: Area) -> tuple[list[dict], dict]:
    rows = _rows(path)
    col = _map_header(next(rows))
    feats, stats = [], {"rows_for_country": 0, "bad_coordinates": 0, "unknown_countries": set()}
    for i, r in enumerate(rows, start=2):
        if len(r) <= max(col.values()):
            continue
        iso = country_iso3(str(r[col["country"]]).strip())
        if iso is None:
            stats["unknown_countries"].add(str(r[col["country"]]))
            continue
        if iso != area.iso3:
            continue
        stats["rows_for_country"] += 1
        try:
            lat, lon = float(r[col["lat"]]), float(r[col["lon"]])
        except (TypeError, ValueError):
            stats["bad_coordinates"] += 1
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            stats["bad_coordinates"] += 1
            continue
        if not area.geometry.covers(Point(lon, lat)):
            continue
        get = lambda f: (str(r[col[f]]).strip() or None) if f in col else None
        feats.append({"type": "Feature",
                      "properties": {"id": f"ssa/{i}", "name": get("name"), "facility_type": get("type"),
                                     "ownership": get("ownership"), "admin1": get("admin1"),
                                     "source": "ssa_public_facilities"},
                      "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    stats["unknown_countries"] = sorted(stats["unknown_countries"])[:20]
    return feats, stats


class PublicFacilitiesFetcher(Fetcher):
    source = "public_facilities"
    ttl_days = 365  # static dataset

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        out = out_dir / "facilities.geojson"
        if area.iso3 not in SSA_ISO3:
            out.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
            return {"urls": [], "params": self.params(),
                    "summary": {"facilities": 0, "note": f"dataset covers sub-Saharan Africa only, not {area.iso3}"}}
        path = manual_path(downloads_dir)
        if path is None:
            raise FileNotFoundError(
                f"Public facility file not found. Download it once from {SOURCE_URL} and save it as "
                f"{downloads_dir.parent / '_manual' / (FILE_STEM + '.xlsx')}")
        feats, stats = read_facilities(path, area)
        if stats["rows_for_country"] == 0:
            raise ValueError(f"The facility file has no rows for {area.iso3}; check its country names "
                             f"(unmatched: {stats['unknown_countries']})")
        out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))
        return {"urls": [SOURCE_URL], "params": self.params(), "citation": CITATION,
                "input_file": path.name,
                "summary": {"facilities": len(feats), "in_country": stats["rows_for_country"],
                            "bad_coordinates": stats["bad_coordinates"]}}
