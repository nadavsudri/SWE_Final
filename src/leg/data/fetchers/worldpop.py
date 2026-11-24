"""WorldPop Global2 constrained population counts (people per ~100m cell), clipped to the area."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask
from shapely.geometry import mapping

from leg.data import http
from leg.data.area import Area
from leg.data.fetchers.base import Fetcher

URL_TEMPLATE = (
    "https://data.worldpop.org/GIS/Population/Global_2015_2030/{release}/{year}/{ISO3}/v1/"
    "{res}/constrained/{iso3}_pop_{year}_CN_{res}_{release}_v1.tif"
)


class WorldPopFetcher(Fetcher):
    source = "worldpop"
    ttl_days = 180  # yearly releases

    def __init__(self, year: int = 2026, release: str = "R2025A", resolution: str = "100m"):
        if not 2015 <= year <= 2030:
            raise ValueError("Global2 covers 2015-2030")
        if resolution not in ("100m", "1km"):
            raise ValueError("resolution must be '100m' or '1km'")
        self.year, self.release, self.resolution = year, release, resolution

    def params(self) -> dict:
        return {"year": self.year, "release": self.release, "resolution": self.resolution}

    def url(self, iso3: str) -> str:
        return URL_TEMPLATE.format(release=self.release, year=self.year, res=self.resolution,
                                   ISO3=iso3.upper(), iso3=iso3.lower())

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        url = self.url(area.iso3)
        country_tif = http.download(url, downloads_dir / Path(url).name, cache_dir=downloads_dir)
        out = out_dir / "population.tif"
        total = clip_raster(country_tif, area, out)
        return {"urls": [url], "params": self.params(),
                "summary": {"total_population": round(total, 1)}}


def clip_raster(src_path: Path, area: Area, out_path: Path) -> float:
    """Clip a raster to the area polygon. Returns the population sum inside it."""
    with rasterio.open(src_path) as src:
        try:
            data, transform = mask(src, [mapping(area.geometry)], crop=True, all_touched=True)
        except ValueError as e:  # rasterio raises this when shapes don't overlap the raster
            raise ValueError(f"Area does not overlap the {area.iso3} WorldPop raster") from e
        profile = src.profile | {"height": data.shape[1], "width": data.shape[2],
                                 "transform": transform, "compress": "deflate"}
        nodata = src.nodata
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data)
    band = data[0].astype("float64")
    valid = band != nodata if nodata is not None else np.ones_like(band, bool)
    valid &= np.isfinite(band) & (band > 0)
    return float(band[valid].sum())
