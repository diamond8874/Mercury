"""
Thread-safe tracking of a session's background pipeline.

One session moves through an explicit state machine, which the browser follows
by polling ``GET /api/sessions/<id>/status``::

    idle -> profiling -> profile_ready -> analyzing -> analyze_done -> processing -> done
                                                                                 \\-> error

``profiling`` starts the moment a file is uploaded - before the user has typed
anything. ``analyzing`` only starts once the goal is submitted, and it waits on
:func:`wait_for_profile` so the two stages never race.

State is held in memory for speed **and** mirrored to ``<session>.job.json`` so
it survives a restart and stays readable if a poll lands on a different worker
process. The disk copy is the reason :func:`wait_for_profile` can fall back to
polling instead of relying solely on an in-process ``threading.Event``.
"""

import os
import json
import logging
import threading
import time

from utils.session_manager import get_session_folder

_bg_jobs_lock = threading.Lock()
_background_jobs = {}     # session_id -> job state dict
_profile_events = {}      # session_id -> threading.Event set when profiling ends

STATUS_IDLE = "idle"
STATUS_PROFILING = "profiling"
STATUS_PROFILE_READY = "profile_ready"
STATUS_ANALYZING = "analyzing"
STATUS_ANALYZE_DONE = "analyze_done"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_ERROR = "error"

# Statuses that mean the profiling stage is over, one way or another.
_PROFILE_SETTLED = (STATUS_PROFILE_READY, STATUS_ANALYZING, STATUS_ANALYZE_DONE,
                    STATUS_PROCESSING, STATUS_DONE, STATUS_ERROR)

_IDLE_STATE = {
    "status": STATUS_IDLE,
    "phase": None,
    "result": None,
    "error": None,
    "progress": 0,
    "progress_msg": "",
}


# ---------------------------------------------------------------------------
# Disk mirror
# ---------------------------------------------------------------------------

def _job_path(session_id):
    return os.path.join(get_session_folder(), f"{session_id}.job.json")


def _write_job_file(session_id, state):
    """Persist job state atomically so a reader never sees a half-written file."""
    try:
        path = _job_path(session_id)
        temp_path = f"{path}.{os.getpid()}.tmp"
        with open(temp_path, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, default=str)
        os.replace(temp_path, path)
    except (OSError, TypeError, ValueError) as exc:
        # The in-memory copy is still authoritative for this process.
        logging.debug(f"Could not persist job state for {session_id}: {exc}")


def _read_job_file(session_id):
    try:
        path = _job_path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        logging.debug(f"Could not read job state for {session_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def _set_job_state(session_id, status, result=None, error=None, progress=0,
                   progress_msg="", phase=None):
    """Replace a session's job state wholesale."""
    state = {
        "status": status,
        "phase": phase,
        "result": result,
        "error": error,
        "progress": progress,
        "progress_msg": progress_msg,
    }
    with _bg_jobs_lock:
        _background_jobs[session_id] = state
    _write_job_file(session_id, state)


def _update_job_progress(session_id, progress, progress_msg):
    """Update only the progress fields of an in-flight job."""
    with _bg_jobs_lock:
        state = _background_jobs.get(session_id)
        if state is None:
            return
        state["progress"] = progress
        state["progress_msg"] = progress_msg
        snapshot = dict(state)
    _write_job_file(session_id, snapshot)


def _get_job_state(session_id):
    """Current state: memory first, then the disk mirror, then idle."""
    with _bg_jobs_lock:
        state = _background_jobs.get(session_id)
        if state is not None:
            return dict(state)

    persisted = _read_job_file(session_id)
    if persisted is not None:
        return persisted
    return dict(_IDLE_STATE)


def reset_job(session_id):
    """Forget a session's job state (used on delete and before a fresh run)."""
    with _bg_jobs_lock:
        _background_jobs.pop(session_id, None)
        _profile_events.pop(session_id, None)
    try:
        path = _job_path(session_id)
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logging.debug(f"Could not remove job file for {session_id}: {exc}")


# ---------------------------------------------------------------------------
# Profile handshake
# ---------------------------------------------------------------------------

def _profile_event(session_id):
    with _bg_jobs_lock:
        event = _profile_events.get(session_id)
        if event is None:
            event = threading.Event()
            _profile_events[session_id] = event
        return event


def clear_profile_ready(session_id):
    """Called when profiling (re)starts."""
    _profile_event(session_id).clear()


def mark_profile_ready(session_id):
    """Called when profiling finishes - successfully or not."""
    _profile_event(session_id).set()


def wait_for_profile(session_id, timeout=180, poll_interval=0.25):
    """
    Block until background profiling finishes. Returns True if ready.

    Waits on the in-process event, but re-checks the persisted state between
    slices. That second path is what makes an early goal submission safe even
    when the profiling thread lives in a different worker process.
    """
    event = _profile_event(session_id)
    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if event.wait(timeout=min(poll_interval, remaining)):
            return True
        if _get_job_state(session_id).get("status") in _PROFILE_SETTLED:
            return True

    return False


def is_profile_ready(session_id):
    return (_profile_event(session_id).is_set()
            or _get_job_state(session_id).get("status") in _PROFILE_SETTLED)
