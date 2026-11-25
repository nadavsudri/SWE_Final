"""District level for the UI: leg.data.levels.choose_level run as a background job, so the UI can
show which level is being probed. Each level is fetched once per drawing and cached afterwards."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import leg.data.levels as levels_mod
from leg.data import Area, SnapshotCache
from leg.data.fetchers import BoundariesFetcher


def options_for(provider: str, level: str) -> dict:
    """Boundaries fetcher kwargs for one level, the same shape as LevelChoice.boundaries_options()."""
    return {"provider": provider, "levels": (level,)}


def _state(e: Exception) -> str:
    if "intersect" in str(e):
        return "no unit"
    return "missing" if levels_mod._missing_level(e) else "failed"


class LevelJob:
    def __init__(self, key: tuple, drawn: Area, mode: str, min_share: float):
        self.id = uuid.uuid4().hex[:12]
        self.key, self.drawn, self.mode, self.min_share = key, drawn, mode, min_share
        self.status, self.error, self.choice = "running", None, None
        self.probing: dict | None = None
        self.probed: list[dict] = []
        self.lock = threading.Lock()

    def view(self) -> dict:
        with self.lock:
            return {"job_id": self.id, "status": self.status, "probing": self.probing, "probed": list(self.probed),
                    "choice": self.choice.to_json() if self.choice else None, "error": self.error,
                    "area_id": self.drawn.area_id, "mode": self.mode, "min_share": self.min_share}


class LevelManager:
    """One job per (drawing, mode, min_share). A finished job answers again at once; the probes
    behind it are cached snapshots, so even a new job for the same drawing is quick."""

    # Snapshot ids are UTC timestamps to the second, so two levels of one drawing fetched within the
    # same second collide in SnapshotCache. Until leg.data fixes that, new probes are spaced out.
    MIN_GAP_S = 1.05

    def __init__(self, cache: SnapshotCache):
        self.cache = cache
        self.jobs: dict[str, LevelJob] = {}
        self.by_key: dict[tuple, LevelJob] = {}

    @staticmethod
    def key(drawn: Area, mode: str, min_share: float) -> tuple:
        return drawn.area_id, mode, round(float(min_share), 4)

    def start(self, drawn: Area, mode: str, min_share: float) -> LevelJob:
        k = self.key(drawn, mode, min_share)
        job = self.by_key.get(k)
        if job and job.status in ("running", "done"):
            return job
        job = LevelJob(k, drawn, mode, min_share)
        self.jobs[job.id] = self.by_key[k] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def done_choice(self, drawn: Area, mode: str, min_share: float):
        job = self.by_key.get(self.key(drawn, mode, min_share))
        return job.choice if job and job.status == "done" else None

    def _run(self, job: LevelJob) -> None:
        last_new = [0.0]

        def cached(fetcher) -> bool:
            now = datetime.now(timezone.utc)
            return any(s.manifest.get("params") == fetcher.params() and now - s.fetched_at < timedelta(days=fetcher.ttl_days)
                       for s in self.cache.list(job.drawn, fetcher.source))

        def fetch(provider: str, level: str):
            fetcher = BoundariesFetcher(levels=(level,), provider=provider)
            was_cached = cached(fetcher)
            if not was_cached:
                time.sleep(max(0.0, self.MIN_GAP_S - (time.time() - last_new[0])))
            with job.lock:
                job.probing = {"provider": provider, "level": level}
            try:
                snap = self.cache.get(fetcher, job.drawn)
            except Exception as e:
                with job.lock:
                    job.probed.append({"provider": provider, "level": level, "state": _state(e)})
                raise
            with job.lock:
                if not was_cached:
                    last_new[0] = time.time()
                job.probed.append({"provider": provider, "level": level, "state": "cached" if was_cached else "downloaded"})
            return snap

        try:
            choice = levels_mod.choose_level(job.drawn, self.cache, job.mode, job.min_share, fetch=fetch)
        except Exception as e:
            with job.lock:
                job.status, job.probing = "failed", None
                job.error = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
            return
        with job.lock:
            job.status, job.probing, job.choice = "done", None, choice
