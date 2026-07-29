import threading

# Thread-safe background job tracking: {session_id: {"status": ..., "result": ..., "error": ..., "progress": ..., "progress_msg": ...}}
_bg_jobs_lock = threading.Lock()
_background_jobs = {}  # session_id -> job state dict

def _set_job_state(session_id, status, result=None, error=None, progress=0, progress_msg=""):
    with _bg_jobs_lock:
        _background_jobs[session_id] = {
            "status": status,
            "result": result,
            "error": error,
            "progress": progress,
            "progress_msg": progress_msg
        }

def _update_job_progress(session_id, progress, progress_msg):
    with _bg_jobs_lock:
        if session_id in _background_jobs:
            _background_jobs[session_id]["progress"] = progress
            _background_jobs[session_id]["progress_msg"] = progress_msg

def _get_job_state(session_id):
    with _bg_jobs_lock:
        return _background_jobs.get(session_id, {"status": "idle", "result": None, "error": None, "progress": 0, "progress_msg": ""})
