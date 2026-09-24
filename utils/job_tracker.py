"""
utils/job_tracker.py
--------------------
Job tracking facade. Fully delegates to DB-persisted `JobRepository` with a bounded
ThreadPoolExecutor for asynchronous job execution.
"""
import uuid
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, Callable

from repositories import job_repository

# Bounded worker pool (max 2 concurrent heavy background jobs)
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="MercuryJobWorker")


def submit_background_job(
    session_id: str,
    job_type: str,
    fn: Callable[..., Any],
    *args,
    user_id: Optional[str] = None,
    timeout_seconds: int = 300,
    **kwargs
) -> str:
    """
    Submits a callable to the bounded ThreadPoolExecutor and records the job in SQLite DB.
    Returns the generated job_id.
    """
    job_id = str(uuid.uuid4())
    job_repository.create_job(
        job_id=job_id,
        session_id=session_id,
        user_id=user_id,
        job_type=job_type,
        status="queued",
        progress=5,
        progress_msg="Queued in worker pool...",
        timeout_seconds=timeout_seconds
    )

    def _worker_wrapper():
        job_repository.update_job_progress(job_id, 10, "Processing started...", status="running")
        try:
            # Pass job_id to kwargs if the function accepts it or uses helper wrappers
            kwargs_with_job = dict(kwargs)
            kwargs_with_job["job_id"] = job_id
            try:
                result = fn(*args, **kwargs_with_job)
            except TypeError:
                # If function signature doesn't take job_id
                result = fn(*args, **kwargs)

            job_repository.complete_job(
                job_id=job_id,
                status="succeeded",
                result_payload=result if isinstance(result, dict) and result else None,
                progress=100,
                progress_msg="Done!"
            )
        except Exception as ex:
            logging.error(f"[JobTracker] Job {job_id} ({job_type}) failed with exception: {ex}", exc_info=True)
            job_repository.complete_job(
                job_id=job_id,
                status="failed",
                error=str(ex),
                progress_msg="Failed"
            )

    JOB_EXECUTOR.submit(_worker_wrapper)
    return job_id


def _set_job_state(session_id: str, status: str, result: Any = None, error: Optional[str] = None, progress: int = 0, progress_msg: str = "", job_id: Optional[str] = None):
    """Backwards-compatible bridge for legacy calls. Updates DB state."""
    if job_id:
        if status in ["succeeded", "done", "analyze_done"]:
            job_repository.complete_job(job_id, "succeeded", result_payload=result if isinstance(result, dict) else {}, progress=progress or 100, progress_msg=progress_msg or "Done")
        elif status in ["failed", "error"]:
            job_repository.complete_job(job_id, "failed", error=error, progress=progress, progress_msg=progress_msg or "Error")
        else:
            job_repository.update_job_progress(job_id, progress, progress_msg, status=status)
        return

    # Fallback to latest session job if job_id not provided
    latest = job_repository.get_latest_job_for_session(session_id)
    if latest:
        jid = latest["id"]
        if status in ["succeeded", "done", "analyze_done"]:
            job_repository.complete_job(jid, "succeeded", result_payload=result if isinstance(result, dict) else {}, progress=progress or 100, progress_msg=progress_msg or "Done")
        elif status in ["failed", "error"]:
            job_repository.complete_job(jid, "failed", error=error, progress=progress, progress_msg=progress_msg or "Error")
        else:
            job_repository.update_job_progress(jid, progress, progress_msg, status=status)


def _update_job_progress(session_id: str, progress: int, progress_msg: str, job_id: Optional[str] = None):
    """Backwards-compatible progress updater."""
    if job_id:
        job_repository.update_job_progress(job_id, progress, progress_msg)
        return

    latest = job_repository.get_latest_job_for_session(session_id)
    if latest:
        job_repository.update_job_progress(latest["id"], progress, progress_msg)


def _get_job_state(session_id: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves current job state from DB."""
    if job_id:
        job = job_repository.get_job(job_id)
        if job:
            return job
    latest = job_repository.get_latest_job_for_session(session_id)
    if latest:
        return latest
    return {"status": "idle", "result": None, "error": None, "progress": 0, "progress_msg": ""}
