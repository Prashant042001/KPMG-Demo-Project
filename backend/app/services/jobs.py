"""In-memory job registry. Uploaded data and generated outputs live only in process memory and expire after a TTL."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.errors import JobNotFoundError, JobNotReadyError
from app.output.writer import OutputFile

log = logging.getLogger(__name__)

QUEUED, RUNNING, COMPLETED, FAILED = "queued", "running", "completed", "failed"


@dataclass
class Job:
    id: str
    created_at: float = field(default_factory=time.time)
    status: str = QUEUED
    stage: str = "queued"
    progress: int = 0
    finished_at: float | None = None
    error: str | None = None
    validation: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    preview: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)  # served page by page, not in public()
    gis: Any = None  # GisData for the GIS view, built with the master database
    outputs: dict[str, OutputFile] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.created_at)),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.finished_at)) if self.finished_at else None,
            "error": self.error,
            "validation": self.validation,
            "metrics": self.metrics,
            "summary": self.summary,
            "preview": self.preview,
            "downloads": sorted(self.outputs),
            "record_count": len(self.records),
        }


class JobStore:
    def __init__(self, ttl_seconds: int, max_jobs: int, workers: int):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_jobs
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nca-job")

    def _purge(self) -> None:
        now = time.time()
        expired = [j for j, job in self._jobs.items() if job.finished_at and now - job.finished_at > self._ttl]
        for j in expired:
            del self._jobs[j]
        # Bound memory: drop the oldest finished jobs beyond the limit.
        finished = sorted((j for j in self._jobs.values() if j.finished_at), key=lambda j: j.finished_at)
        while len(self._jobs) > self._max and finished:
            del self._jobs[finished.pop(0).id]
        if expired:
            log.info("Purged %d expired job(s)", len(expired))

    def create(self) -> Job:
        with self._lock:
            self._purge()
            job = Job(id=secrets.token_hex(16))
            self._jobs[job.id] = job
            return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            self._purge()
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError("Job not found or expired.")
        return job

    def output(self, job_id: str, name: str) -> OutputFile:
        job = self.get(job_id)
        if job.status != COMPLETED:
            raise JobNotReadyError("Outputs are available only after processing completes successfully.")
        out = job.outputs.get(name)
        if out is None:
            raise JobNotFoundError("Requested output is not available for this job.")
        return out

    def submit(self, job: Job, fn: Callable[[Job], None]) -> None:
        def run() -> None:
            job.status, job.stage = RUNNING, "starting"
            try:
                fn(job)
                job.status, job.stage, job.progress = COMPLETED, "completed", 100
            except Exception as exc:  # noqa: BLE001 - report a safe message, log the type only
                job.status, job.stage = FAILED, "failed"
                job.error = getattr(exc, "message", None) or "Processing failed due to an internal error."
                # Exception text can echo cell values, so only the type is logged; the traceback is DEBUG-only.
                log.error("Job %s failed: %s", job.id[:8], type(exc).__name__)
                log.debug("Job %s traceback", job.id[:8], exc_info=True)
            finally:
                job.finished_at = time.time()

        self._pool.submit(run)
