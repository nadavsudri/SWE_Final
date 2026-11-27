"""Malaria Atlas Project walking-only friction surface (minutes to cross one metre, ~1 km pixels).

The paper's code computes walking time between cells on this map, and its pixel grid becomes the
cell grid. Served by MAP's GeoServer (WCS 2.0.1), cut to the area's bounding box plus a margin so
walking paths can leave the area slightly.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from leg.data import http
from leg.data.area import Area
from leg.data.fetchers.base import Fetcher

WCS_URL = "https://data.malariaatlas.org/geoserver/Accessibility/wcs"
COVERAGES = {
    "walking": "Accessibility__202001_Global_Walking_Only_Friction_Surface",
    "motorized": "Accessibility__202001_Global_Motorized_Friction_Surface",
}
# GeoServer names the EPSG:4326 axes Lat/Long; older setups use lat/long.
AXES = [("Lat", "Long"), ("lat", "long")]


class FrictionFetcher(Fetcher):
    source = "friction"
    ttl_days = 365  # MAP releases a new surface every few years

    def __init__(self, mode: str = "walking", margin_deg: float = 0.1):
        if mode not in COVERAGES:
            raise ValueError(f"mode must be one of {sorted(COVERAGES)}")
        if not 0 <= margin_deg <= 1:
            raise ValueError("margin_deg must be between 0 and 1")
        self.mode, self.margin_deg = mode, margin_deg

    def params(self) -> dict:
        return {"mode": self.mode, "margin_deg": self.margin_deg}

    def url(self, bbox: tuple[float, float, float, float], axes=AXES[0]) -> str:
        w, s, e, n = bbox
        lat, lon = axes
        return (f"{WCS_URL}?service=WCS&version=2.0.1&request=GetCoverage"
                f"&coverageId={COVERAGES[self.mode]}"
                f"&subset={lat}({s},{n})&subset={lon}({w},{e})&format=image/tiff")

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        m = self.margin_deg
        w, s, e, n = area.bbox
        bbox = (max(w - m, -180), max(s - m, -60), min(e + m, 180), min(n + m, 85))
        out = out_dir / "friction.tif"
        errors = []
        for axes in AXES:
            url = self.url(bbox, axes)
            try:
                http.download(url, out)
                stats = _check(out)
                return {"urls": [url], "params": self.params(), "summary": stats}
            except Exception as ex:  # an XML error page or a bad axis name
                errors.append(f"{axes}: {ex}")
                out.unlink(missing_ok=True)
        raise RuntimeError("Malaria Atlas friction download failed: " + " | ".join(errors))


def _check(path: Path) -> dict:
    """Make sure the download is a raster (GeoServer answers errors as XML with status 200)."""
    head = path.read_bytes()[:200]
    if head.lstrip().startswith(b"<"):
        raise ValueError(head.decode("utf-8", "replace").strip()[:200])
    with rasterio.open(path) as src:
        band = src.read(1).astype("float64")
        nodata = src.nodata
        res = abs(src.transform.a)
    ok = np.isfinite(band) & (band > 0)
    if nodata is not None:
        ok &= band != nodata
    if not ok.any():
        raise ValueError("friction raster has no valid pixels for this area")
    return {"pixels": int(band.size), "valid_pixels": int(ok.sum()), "res_deg": res,
            "median_min_per_m": round(float(np.median(band[ok])), 5)}
