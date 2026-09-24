"""
repositories/job_repository.py
------------------------------
Thread-safe, transaction-managed data access layer for background jobs.
Persists all background job lifecycles to the SQLAlchemy database.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import config
from models import get_session_factory, JobModel


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_factory(db_path: Optional[str] = None):
    """Returns a session factory for the given db_path (defaults to config.DATABASE_PATH)."""
    return get_session_factory(db_path or config.DATABASE_PATH)


def create_job(
    job_id: str,
    session_id: str,
    user_id: Optional[str] = None,
    job_type: str = "analyze",
    status: str = "queued",
    progress: int = 0,
    progress_msg: str = "",
    timeout_seconds: int = 300,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Creates and persists a new background job row."""
    SessionFactory = _get_factory(db_path)
    session = SessionFactory()
    try:
        now = _now_iso()
        job = JobModel(
            id=job_id,
            session_id=session_id,
            user_id=user_id,
            job_type=job_type,
            status=status,
            progress=progress,
            progress_msg=progress_msg,
            timeout_seconds=timeout_seconds,
            created_at=now,
            updated_at=now
        )
        session.add(job)
        session.commit()
        return job.to_dict()
    except Exception as e:
        session.rollback()
        logging.error(f"[JobRepository] Failed to create job {job_id}: {e}")
        raise
    finally:
        session.close()


def update_job_progress(
    job_id: str,
    progress: int,
    progress_msg: str,
    status: Optional[str] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Updates progress percentage, progress message, and optional status of an existing job."""
    SessionFactory = _get_factory(db_path)
    session = SessionFactory()
    try:
        job = session.query(JobModel).filter_by(id=job_id).first()
        if not job:
            return None
        job.progress = progress
        job.progress_msg = progress_msg
        if status:
            job.status = status
        job.updated_at = _now_iso()
        session.commit()
        return job.to_dict()
    except Exception as e:
        session.rollback()
        logging.error(f"[JobRepository] Failed to update progress for job {job_id}: {e}")
        return None
    finally:
        session.close()


def complete_job(
    job_id: str,
    status: str,  # "succeeded" or "failed"
    result_payload: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    progress: int = 100,
    progress_msg: str = "Done",
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Marks a job as succeeded or failed, storing result or error message."""
    SessionFactory = _get_factory(db_path)
    session = SessionFactory()
    try:
        job = session.query(JobModel).filter_by(id=job_id).first()
        if not job:
            return None
        job.status = status
        if result_payload is not None:
            job.result_payload = result_payload
        if error is not None:
            job.error = error
        job.progress = progress
        job.progress_msg = progress_msg
        job.updated_at = _now_iso()
        session.commit()
        return job.to_dict()
    except Exception as e:
        session.rollback()
        logging.error(f"[JobRepository] Failed to complete job {job_id}: {e}")
        return None
    finally:
        session.close()


def get_job(job_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches a single job dictionary by job_id."""
    SessionFactory = _get_factory(db_path)
    session = SessionFactory()
    try:
        job = session.query(JobModel).filter_by(id=job_id).first()
        if not job:
            return None
        return job.to_dict()
    finally:
        session.close()


def get_latest_job_for_session(session_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches the latest job for a given session by created_at descending."""
    SessionFactory = _get_factory(db_path)
    session = SessionFactory()
    try:
        job = session.query(JobModel).filter_by(session_id=session_id).order_by(JobModel.created_at.desc()).first()
        if not job:
            return None
        return job.to_dict()
    finally:
        session.close()


def fail_stuck_and_interrupted_jobs(db_path: Optional[str] = None, reason: str = "Interrupted by server restart") -> int:
    """
    Sweeps the database at startup to fail any in-flight jobs left in 'queued' or 'running' status.
    Returns the count of failed jobs.
    """
    SessionFactory = _get_factory(db_path)
    session = SessionFactory()
    try:
        stuck_jobs = session.query(JobModel).filter(JobModel.status.in_(["queued", "running"])).all()
        count = len(stuck_jobs)
        now = _now_iso()
        for job in stuck_jobs:
            job.status = "failed"
            job.error = reason
            job.updated_at = now
        session.commit()
        if count > 0:
            logging.info(f"[JobRepository] Marked {count} unfinished job(s) as failed ({reason}).")
        return count
    except Exception as e:
        session.rollback()
        logging.error(f"[JobRepository] Error failing stuck jobs: {e}")
        return 0
    finally:
        session.close()


def check_and_fail_timed_out_jobs(db_path: Optional[str] = None) -> int:
    """
    Watchdog function checking running/queued jobs whose updated_at/created_at exceeds timeout_seconds.
    """
    SessionFactory = _get_factory(db_path)
    session = SessionFactory()
    try:
        active_jobs = session.query(JobModel).filter(JobModel.status.in_(["queued", "running"])).all()
        count = 0
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        for job in active_jobs:
            # Parse created_at or updated_at
            t_str = job.updated_at or job.created_at
            try:
                job_dt = datetime.fromisoformat(t_str)
                # Ensure timezone awareness
                if job_dt.tzinfo is None:
                    job_dt = job_dt.replace(tzinfo=timezone.utc)
                elapsed = (now_dt - job_dt).total_seconds()
                if elapsed > (job.timeout_seconds or 300):
                    job.status = "failed"
                    job.error = f"Job timed out after exceeding limit ({job.timeout_seconds}s)"
                    job.updated_at = now_iso
                    count += 1
            except Exception as parse_err:
                logging.warning(f"[JobRepository] Could not parse timestamp for job {job.id}: {parse_err}")

        if count > 0:
            session.commit()
            logging.info(f"[JobRepository Watchdog] Timed out {count} hung job(s).")
        return count
    except Exception as e:
        session.rollback()
        logging.error(f"[JobRepository Watchdog] Error checking timeouts: {e}")
        return 0
    finally:
        session.close()
