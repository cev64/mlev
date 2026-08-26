"""Background job runner for the web UI.

The pipeline steps are minutes long, so the browser cannot wait on them
synchronously. Each job runs on a worker thread and appends to a log the UI
polls. One job at a time per sport+kind, because two backfills writing the same
parquet file would corrupt it.
"""

from __future__ import annotations

import io
import logging
import threading
import time
import traceback
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MAX_LOG_LINES = 600


@dataclass
class Job:
    id: str
    kind: str
    sport: str
    label: str
    status: str = "running"          # running | done | failed
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    lines: deque = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    result: Any = None
    error: str | None = None

    def log(self, message: str) -> None:
        for line in str(message).rstrip().splitlines():
            self.lines.append(line)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "sport": self.sport,
            "label": self.label,
            "status": self.status,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
            "lines": list(self.lines),
            "result": self.result,
            "error": self.error,
        }


class _JobLogHandler(logging.Handler):
    """Pipes the pipeline's own logging into the job log the browser polls."""

    def __init__(self, job: Job) -> None:
        super().__init__(level=logging.INFO)
        self.job = job
        self.setFormatter(logging.Formatter("%(message)s"))

    # Flask's request logger writes a line per poll, and the browser polls once
    # a second. Left in, it buries the pipeline's own output completely.
    NOISY = ("werkzeug", "urllib3", "matplotlib", "PIL", "asyncio")

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.split(".")[0] in self.NOISY:
            return
        try:
            self.job.log(self.format(record))
        except Exception:
            pass


class JobRunner:
    """Tracks jobs and refuses to run two conflicting ones at once."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def active(self, sport: str, kind: str) -> Job | None:
        with self._lock:
            for job in self._jobs.values():
                if job.status == "running" and job.sport == sport and job.kind == kind:
                    return job
        return None

    def any_active(self, sport: str) -> Job | None:
        with self._lock:
            for job in self._jobs.values():
                if job.status == "running" and job.sport == sport:
                    return job
        return None

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, limit: int = 12) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)
        return [
            {k: v for k, v in job.snapshot().items() if k != "lines"} for job in jobs[:limit]
        ]

    def submit(
        self, *, kind: str, sport: str, label: str, target: Callable[[Job], Any]
    ) -> Job:
        """Start `target` on a worker thread. Raises if a conflicting job runs."""
        existing = self.any_active(sport)
        if existing is not None:
            raise RuntimeError(
                f"'{existing.label}' is already running for {sport.upper()}. "
                "Wait for it to finish — two jobs writing the same files would "
                "corrupt them."
            )

        job = Job(id=uuid.uuid4().hex[:12], kind=kind, sport=sport, label=label)
        with self._lock:
            self._jobs[job.id] = job

        def run() -> None:
            handler = _JobLogHandler(job)
            root = logging.getLogger()
            previous_level = root.level
            root.addHandler(handler)
            root.setLevel(logging.INFO)
            buffer = io.StringIO()
            try:
                job.log(f"starting: {label}")
                job.result = target(job)
                job.status = "done"
                job.log("finished")
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.log(job.error)
                for line in traceback.format_exc().splitlines()[-12:]:
                    job.log(line)
            finally:
                job.finished_at = time.time()
                root.removeHandler(handler)
                root.setLevel(previous_level)
                buffer.close()

        threading.Thread(target=run, name=f"job-{job.id}", daemon=True).start()
        return job


RUNNER = JobRunner()
