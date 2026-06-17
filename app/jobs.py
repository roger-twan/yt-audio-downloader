from datetime import datetime, timezone
from threading import Lock
from typing import Any


jobs: dict[str, dict[str, Any]] = {}
jobs_lock = Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_id: str, **values: Any) -> None:
    now = utc_now()
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            **values,
        }


def update_job(job_id: str, **changes: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.update(changes)
        job["updated_at"] = utc_now()


def read_job(job_id: str) -> dict[str, Any] | None:
    with jobs_lock:
        job = jobs.get(job_id)
        return dict(job) if job else None


def list_jobs() -> list[dict[str, Any]]:
    with jobs_lock:
        return sorted(
            (dict(job) for job in jobs.values()),
            key=lambda job: job["created_at"],
            reverse=True,
        )
