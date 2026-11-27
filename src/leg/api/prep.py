"""Background preprocessing jobs with progress, for the UI's loading bar.

POST /api/prep {area_id}        -> {job_id}
GET  /api/prep/{job_id}         -> status, stage, percent, eta, and the output summary when done
GET  /api/prep/area/{area_id}   -> earlier runs of this area (newest first)

Percent is weighted by how long each stage usually takes: walking times dominate.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from leg.prep import STAGES, PrepParams
from leg.prep.run import prepare

WEIGHTS = {"population": 5, "districts": 3, "travel_times": 82, "facilities": 3, "write": 7}
LABELS = {"population": "Placing people on the grid", "districts": "Assigning cells to districts",
          "travel_times": "Computing walking times", "facilities": "Placing existing facilities",
          "write": "Writing files"}


class PrepJob:
    def __init__(self, area_id: str, pinned: dict, params: PrepParams, years: list[int] | None):
        self.id = uuid.uuid4().hex[:12]
        self.area_id, self.pinned, self.params, self.years = area_id, pinned, params, years
        self.status, self.stage, self.done, self.total = "queued", None, 0, 1
        self.error: str | None = None
        self.out: Path | None = None
        self.warnings: list[str] = []
        self.started = self.ended = self.stage_started = None
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def progress(self, stage: str, done: int, total: int) -> None:
        with self.lock:
            if stage != self.stage:
                self.stage_started = time.time()
            self.stage, self.done, self.total = stage, done, max(total, 1)

    def percent(self) -> float:
        if self.status == "done":
            return 100.0
        if self.stage is None:
            return 0.0
        i = STAGES.index(self.stage)
        before = sum(WEIGHTS[s] for s in STAGES[:i])
        return round(before + WEIGHTS[self.stage] * min(self.done / self.total, 1.0), 1)

    def view(self) -> dict:
        now = time.time()
        with self.lock:
            pct = self.percent()
            elapsed = (self.ended or now) - self.started if self.started else 0.0
            eta = None
            # only during walking times: the earlier stages are too short to extrapolate from
            if self.status == "running" and self.stage == "travel_times" and self.done > 0:
                stage_s = now - self.stage_started
                left = stage_s * (self.total - self.done) / self.done
                eta = round(left + elapsed * (WEIGHTS["facilities"] + WEIGHTS["write"]) / max(pct, 1), 0)
            v = {"job_id": self.id, "area_id": self.area_id, "status": self.status, "running": self.running,
                 "stage": self.stage, "stage_label": LABELS.get(self.stage, ""),
                 "stage_index": STAGES.index(self.stage) + 1 if self.stage else 0, "stages": len(STAGES),
                 "stage_done": self.done, "stage_total": self.total, "percent": pct,
                 "elapsed_s": round(elapsed, 1), "eta_s": eta, "error": self.error, "warnings": self.warnings,
                 "output": None}
        if self.status == "done" and self.out:
            v["output"] = output_view(self.out)
        return v


def output_view(out: Path) -> dict:
    meta = json.loads((out / "meta.json").read_text())
    return {"run_id": out.name, "path": str(out), "totals": meta["totals"], "unassigned": meta["unassigned"],
            "dropped_facilities": meta["dropped_facilities"], "planning_year": meta["planning_year"],
            "params": meta["params"], "seconds": meta["seconds"],
            "files": {p.name: p.stat().st_size for p in sorted(out.iterdir()) if p.is_file()}}


class PrepManager:
    def __init__(self, root: Path, out: Path):
        self.root, self.out = Path(root), Path(out)
        self.jobs: dict[str, PrepJob] = {}

    def busy(self) -> PrepJob | None:
        return next((j for j in self.jobs.values() if j.running), None)

    def start(self, job: PrepJob) -> PrepJob:
        self.jobs[job.id] = job
        job.thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        job.thread.start()
        return job

    def _run(self, job: PrepJob) -> None:
        with job.lock:
            job.status, job.started = "running", time.time()
        try:
            out = prepare(job.area_id, self.root, self.out, job.pinned, job.params, job.years,
                          progress=job.progress, warn=job.warnings.append)
            with job.lock:
                job.out, job.status = out, "done"
        except Exception as e:
            with job.lock:
                job.status, job.error = "failed", f"{type(e).__name__}: {e}"
        finally:
            with job.lock:
                job.ended = time.time()

    def runs(self, area_id: str) -> list[dict]:
        d = self.out / area_id
        outs = [p for p in d.iterdir() if (p / "meta.json").exists()] if d.is_dir() else []
        return [output_view(p) for p in sorted(outs, key=lambda p: p.name, reverse=True)]
