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
        self.in_progress: dict[tuple, float] = {}   # (provider, level) -> start time
        self.fetch_state: dict[tuple, str] = {}     # (provider, level) -> cached | downloaded
        self.probed: list[dict] = []
        self.seconds: dict[tuple, float] = {}
        self.lock = threading.Lock()

    def view(self) -> dict:
        now = time.time()
        with self.lock:
            running = [{"provider": p, "level": lv, "elapsed_s": round(now - t, 1)}
                       for (p, lv), t in sorted(self.in_progress.items(), key=lambda kv: kv[1])]
            # `probing` (the first level still running) is kept for the current UI; `in_progress` lists all
            return {"job_id": self.id, "status": self.status, "probing": running[0] if running else None,
                    "in_progress": running, "probed": list(self.probed),
                    "choice": self.choice.to_json() if self.choice else None, "error": self.error,
                    "area_id": self.drawn.area_id, "mode": self.mode, "min_share": self.min_share}


class LevelManager:
    """One job per (drawing, mode, min_share). A finished job answers again at once; the probes
    behind it are cached snapshots, so even a new job for the same drawing is quick."""

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
        def cached(fetcher) -> bool:
            now = datetime.now(timezone.utc)
            return any(s.manifest.get("params") == fetcher.params() and now - s.fetched_at < timedelta(days=fetcher.ttl_days)
                       for s in self.cache.list(job.drawn, fetcher.source))

        def fetch(provider: str, level: str):  # called from several threads (geoBoundaries levels in parallel)
            fetcher = BoundariesFetcher(levels=(level,), provider=provider)
            was_cached = cached(fetcher)
            key = (provider, level)
            with job.lock:
                job.in_progress[key] = time.time()
            try:
                snap = self.cache.get(fetcher, job.drawn)
            except Exception as e:
                with job.lock:
                    job.fetch_state[key] = _state(e)
                raise
            finally:
                with job.lock:
                    job.seconds[key] = round(time.time() - job.in_progress.pop(key), 1)
            with job.lock:
                job.fetch_state[key] = "cached" if was_cached else "downloaded"
            return snap

        def progress(c) -> None:  # called in level order, coarse to fine, as each result is known
            key = (c.provider, c.level)
            if c.skipped:
                state = "skipped"
            elif c.failed:
                state = "failed"
            elif not c.available:
                state = "missing"
            elif c.note == "no unit in the area":
                state = "no unit"
            else:
                state = job.fetch_state.get(key, "downloaded")
            with job.lock:
                job.probed.append({"provider": c.provider, "level": c.level, "state": state,
                                   "touched": c.touched, "usable": c.usable, "note": c.note,
                                   "seconds": job.seconds.get(key)})

        try:
            choice = levels_mod.choose_level(job.drawn, self.cache, job.mode, job.min_share, fetch=fetch,
                                             progress=progress)
        except Exception as e:
            with job.lock:
                job.status, job.in_progress = "failed", {}
                job.error = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
            return
        with job.lock:
            job.status, job.in_progress, job.choice = "done", {}, choice
