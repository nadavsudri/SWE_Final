"""Advice upload and scoring jobs, for the UI step after preprocessing.

POST /api/advice                    {filename, text, area_id, run_id, budget?} -> {job_id}
GET  /api/advice/jobs/{job_id}      status, stage, elapsed; the result when done
GET  /api/advice                    saved advice sets, newest first
GET  /api/advice/{key}              one set: per advice its interpretation, checks, sample scores, code
POST /api/advice/{key}/approve      optional: record that a person read it and agrees
POST /api/advice/{key}/recheck      run the checks again on the saved code (no LLM call)

Functions that pass the checks are used at once (approved_by "auto"); an advice that fails is
not scored (used: false) and the planner still reads it.

The browser reads the .txt/.json file and sends its text: no multipart upload needed.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path

from leg import advice as adv

MAX_BYTES = 64_000
MAX_ADVICE = 50
LABELS = {"reading": "Reading the advice", "sample_plans": "Building sample plans for this area",
          "writing_functions": "The model is writing a scoring function for each advice",
          "checking": "Checking the functions", "saving": "Saving"}
KEY = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def safe_name(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(filename).stem).strip("-")[:60] or "advice"
    suffix = ".json" if filename.lower().endswith(".json") else ".txt"
    return stem + suffix


class AdviceJob:
    def __init__(self, path: Path, prep_dir: Path, budget: int):
        self.id = uuid.uuid4().hex[:12]
        self.path, self.prep_dir, self.budget = path, prep_dir, budget
        self.status, self.stage, self.done, self.total = "queued", None, 0, 1
        self.error: str | None = None
        self.key: str | None = None
        self.started = self.ended = None
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def progress(self, stage: str, done: int, total: int) -> None:
        with self.lock:
            self.stage, self.done, self.total = stage, done, max(total, 1)

    def view(self, root: Path) -> dict:
        with self.lock:
            v = {"job_id": self.id, "status": self.status, "running": self.running, "stage": self.stage,
                 "stage_label": LABELS.get(self.stage, ""),
                 "stage_index": adv.STAGES.index(self.stage) + 1 if self.stage else 0, "stages": len(adv.STAGES),
                 "stage_done": self.done, "stage_total": self.total,
                 "elapsed_s": round((self.ended or time.time()) - self.started, 1) if self.started else 0.0,
                 "error": self.error, "key": self.key, "result": None}
        if self.status == "done" and self.key:
            v["result"] = set_view(root / self.key)
        return v


def set_view(d: Path) -> dict:
    rec = adv.load_dir(d)
    u = rec.get("llm_usage", {})
    return {"key": d.name, "file": Path(rec["advice_file"]).name, "created_at": rec["created_at"],
            "approved_at": rec["approved_at"], "approved_by": rec.get("approved_by"),
            "prep_run": rec["prep_run"], "sample_plans": rec["sample_plans"],
            "model": u.get("model"), "tokens": {"input": u.get("input_tokens"), "output": u.get("output_tokens")},
            "items": [{"advice": it["advice"], "measurable": it["measurable"], "used": adv.used(it),
                       "interpretation": it["interpretation"],
                       "passed": it["check"]["passed"] if it["check"] else None,
                       "errors": it["check"]["errors"] if it["check"] else [],
                       "warnings": it["check"]["warnings"] if it["check"] else [],
                       "sample_scores": it["check"]["sample_scores"] if it["check"] else {},
                       "code": it["code"]} for it in rec["items"]],
            "review_md": (d / adv.REVIEW).read_text(encoding="utf-8") if (d / adv.REVIEW).exists() else ""}


class AdviceManager:
    def __init__(self, root: Path, processed: Path, llm_factory=None):
        self.root, self.processed = Path(root), Path(processed)
        self.llm_factory = llm_factory or adv.claude_llm
        self.jobs: dict[str, AdviceJob] = {}

    def busy(self) -> AdviceJob | None:
        return next((j for j in self.jobs.values() if j.running), None)

    def create(self, filename: str, text: str, area_id: str, run_id: str, budget: int) -> AdviceJob:
        """Validate and save the upload; raises ValueError / FileNotFoundError / RuntimeError."""
        if not filename.lower().endswith((".txt", ".json")):
            raise ValueError("The advice file must be a .txt (one advice per line) or a .json list of strings.")
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise ValueError(f"The advice file is larger than {MAX_BYTES // 1000} KB.")
        if not (KEY.match(area_id) and KEY.match(run_id)):
            raise FileNotFoundError("Unknown preprocessing run.")
        prep = self.processed / area_id / run_id
        if not (prep / "population.csv").exists():
            raise FileNotFoundError("Unknown preprocessing run: preprocess the area first.")
        if not 1 <= budget <= 1000:
            raise ValueError("Budget must be between 1 and 1000.")
        # one folder per content, keeping the original file name (it names the saved set)
        import hashlib
        folder = self.root / "uploads" / hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_name(filename)
        path.write_text(text, encoding="utf-8")
        items = adv.read_advice(path)             # ValueError: empty, duplicate, bad JSON
        if len(items) > MAX_ADVICE:
            raise ValueError(f"At most {MAX_ADVICE} advice per file (this one has {len(items)}).")
        self.llm_factory()                          # RuntimeError now if there is no API key
        return AdviceJob(path, prep, budget)

    def start(self, job: AdviceJob) -> AdviceJob:
        self.jobs[job.id] = job
        job.thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        job.thread.start()
        return job

    def _run(self, job: AdviceJob) -> None:
        with job.lock:
            job.status, job.started = "running", time.time()
        try:
            d = adv.prepare(job.path, job.prep_dir, job.budget, self.llm_factory(), self.root,
                            progress=job.progress)
            with job.lock:
                job.key, job.status = d.name, "done"
        except Exception as e:  # noqa: BLE001 - shown to the user
            with job.lock:
                job.status, job.error = "failed", f"{type(e).__name__}: {e}"
        finally:
            with job.lock:
                job.ended = time.time()

    def set_dir(self, key: str) -> Path:
        d = self.root / key
        if not KEY.match(key) or key == "uploads" or not (d / adv.SCORING).exists():
            raise FileNotFoundError("Unknown advice set.")
        return d
