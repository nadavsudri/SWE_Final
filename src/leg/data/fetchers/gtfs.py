"""Public-transport schedules (GTFS) found through the Mobility Database catalog.

The catalog is a CSV of every known feed with its country and bounding box. We keep active,
no-auth GTFS feeds in the area's country whose bbox overlaps the area, and download them.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from shapely.geometry import box

from leg.data import http
from leg.data.area import Area
from leg.data.fetchers.base import Fetcher

CATALOG_URL = "https://files.mobilitydatabase.org/feeds_v2.csv"


def _float(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def select_feeds(catalog_csv: str, area: Area) -> list[dict]:
    feeds = []
    for row in csv.DictReader(io.StringIO(catalog_csv)):
        if row.get("data_type") != "gtfs" or row.get("location.country_code") != area.iso2:
            continue
        if row.get("status") in ("deprecated", "inactive") or row.get("redirect.id"):
            continue
        if row.get("urls.authentication_type") not in ("", "0", None):
            continue  # needs an API key
        url = row.get("urls.latest") or row.get("urls.direct_download")
        if not url:
            continue
        bb = [_float(row.get(f"location.bounding_box.{k}")) for k in
              ("minimum_longitude", "minimum_latitude", "maximum_longitude", "maximum_latitude")]
        if None not in bb and not box(*bb).intersects(area.geometry):
            continue  # feed with a known bbox outside the area (unknown bbox: keep, to be safe)
        feeds.append({"id": row.get("id"), "provider": row.get("provider"),
                      "name": row.get("name"), "url": url})
    return feeds


class GtfsFetcher(Fetcher):
    source = "gtfs"
    ttl_days = 14  # schedules change often

    def __init__(self, max_feeds: int = 10, catalog_url: str = CATALOG_URL):
        self.max_feeds = max_feeds
        self.catalog_url = catalog_url

    def params(self) -> dict:
        return {"max_feeds": self.max_feeds}

    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        catalog = http.download(self.catalog_url, downloads_dir / "mobility_feeds_v2.csv")
        feeds = select_feeds(catalog.read_text(encoding="utf-8"), area)
        skipped = feeds[self.max_feeds:]
        feeds = feeds[: self.max_feeds]
        for f in feeds:
            dest = out_dir / f"gtfs_{f['id']}.zip"
            http.download(f["url"], dest, cache_dir=downloads_dir)
            f["file"] = dest.name
        (out_dir / "feeds.json").write_text(json.dumps(feeds, indent=2, ensure_ascii=False))
        return {"urls": [self.catalog_url] + [f["url"] for f in feeds], "params": self.params(),
                "summary": {"feeds": len(feeds), "skipped_over_limit": len(skipped)}}
