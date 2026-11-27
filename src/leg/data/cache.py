"""Snapshot cache.

Layout:  <root>/<area_id>/<source>/<snapshot_id>/   (files + manifest.json)
         <root>/_downloads/                         (shared big downloads, keyed by URL)

- Each fetch creates a NEW snapshot folder; nothing is overwritten.
- `get()` reuses the newest snapshot if it is younger than the fetcher's TTL and was made
  with the same params; otherwise it fetches a new one.
- Experiments pin an exact snapshot id, so results never change underneath them.
"""
from __future__ import annotations

import hashlib
import json
import threading
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leg.data.area import Area
from leg.data.fetchers.base import Fetcher

_ID_LOCK = threading.Lock()
MANIFEST = "manifest.json"


@dataclass
class Snapshot:
    path: Path
    manifest: dict

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def fetched_at(self) -> datetime:
        return datetime.fromisoformat(self.manifest["fetched_at"])


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class SnapshotCache:
    def __init__(self, root: Path | str = "data/raw"):
        self.root = Path(root)

    @property
    def downloads_dir(self) -> Path:
        return self.root / "_downloads"

    def source_dir(self, area: Area, source: str) -> Path:
        return self.root / area.area_id / source

    def list(self, area: Area, source: str) -> list[Snapshot]:
        """All complete snapshots, oldest first. Folders without a manifest, and temp folders
        (".<id>.tmp", possibly mid-write by another thread), are ignored."""
        d = self.source_dir(area, source)
        if not d.exists():
            return []
        snaps = [Snapshot(p, json.loads((p / MANIFEST).read_text()))
                 for p in d.iterdir() if not p.name.startswith(".") and (p / MANIFEST).exists()]
        return sorted(snaps, key=lambda s: (s.fetched_at, s.path.name))

    def pinned(self, area: Area, source: str, snapshot_id: str) -> Snapshot:
        p = self.source_dir(area, source) / snapshot_id
        if not (p / MANIFEST).exists():
            raise FileNotFoundError(f"No snapshot {snapshot_id!r} for {source} in {area.area_id}")
        return Snapshot(p, json.loads((p / MANIFEST).read_text()))

    def get(self, fetcher: Fetcher, area: Area, refresh: bool = False,
            snapshot_id: str | None = None, now: datetime | None = None) -> Snapshot:
        if snapshot_id:
            return self.pinned(area, fetcher.source, snapshot_id)
        now = now or datetime.now(timezone.utc)
        if not refresh:
            fresh = [s for s in self.list(area, fetcher.source)
                     if s.manifest.get("params") == fetcher.params()
                     and now - s.fetched_at < timedelta(days=fetcher.ttl_days)]
            if fresh:
                return fresh[-1]
        return self._fetch_new(fetcher, area, now)

    def _fetch_new(self, fetcher: Fetcher, area: Area, now: datetime) -> Snapshot:
        base = self.source_dir(area, fetcher.source)
        base.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y-%m-%dT%H%M%SZ")
        # Ids are timestamps to the second; fetches in the same second (parallel level probes) get
        # -2, -3, ... Picking the id and the final rename happen under one lock, so two threads never
        # pick the same id; the download itself runs outside it.
        with _ID_LOCK:
            for i in range(1, 1000):
                snap_id = stamp if i == 1 else f"{stamp}-{i}"
                final, tmp = base / snap_id, base / f".{snap_id}.tmp"
                if not final.exists() and not tmp.exists():
                    tmp.mkdir()
                    break
            else:
                raise RuntimeError(f"no free snapshot id for {stamp} in {base}")
        try:
            meta = fetcher.fetch(area, tmp, self.downloads_dir)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        manifest = {
            "source": fetcher.source,
            "area": area.to_geojson(),
            "area_id": area.area_id,
            "fetched_at": now.isoformat(),
            "params": fetcher.params(),
            **meta,
            "files": {p.name: {"bytes": p.stat().st_size, "sha256": _sha256(p)}
                      for p in sorted(tmp.iterdir()) if p.is_file()},
        }
        (tmp / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        with _ID_LOCK:
            tmp.rename(final)  # atomic: a snapshot is either complete or absent
        return Snapshot(final, manifest)
