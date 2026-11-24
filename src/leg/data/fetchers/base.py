"""Fetcher interface. One subclass per data source."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from leg.data.area import Area


class Fetcher(ABC):
    source: str          # folder name under the area, e.g. "worldpop"
    ttl_days: int        # how long a snapshot stays fresh before auto-refresh

    @abstractmethod
    def fetch(self, area: Area, out_dir: Path, downloads_dir: Path) -> dict:
        """Write this source's files for `area` into `out_dir` (already created, empty).

        `downloads_dir` is a shared cache for large country-wide files.
        Returns metadata for the manifest: at least {"urls": [...], "params": {...}}.
        Must raise on failure; never leave a half-written snapshot that looks valid.
        """

    def params(self) -> dict:
        """Settings that change the output (year, admin levels...). Part of the cache key."""
        return {}
