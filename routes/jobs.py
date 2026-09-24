"""
routes/jobs.py
--------------
Blueprint for polling individual background job status.
All job lookups are owner-only; cross-user requests return stealth 404.
"""
from flask import Blueprint, jsonify
from flask_login import current_user

from repositories import job_repository
from utils.session_manager import load_session

jobs_bp = Blueprint('jobs', __name__)


@jobs_bp.route('/api/jobs/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """
    Returns the current status of a background job.
    Owner-only: returns 404 if the job belongs to a different user.
    """
    job = job_repository.get_job(job_id)
    if not job:
        return jsonify({"status": "error", "error": "Job not found."}), 404

    # Ownership check: verify job's session belongs to the current user
    session_id = job.get("session_id")
    session_data = load_session(session_id) if session_id else None

    if session_data:
        session_owner = session_data.get("owner_id")
        current_uid = current_user.id if current_user.is_authenticated else None
        if session_owner and current_uid and session_owner != current_uid:
            # Stealth 404 to avoid leaking existence of other users' jobs
            return jsonify({"status": "error", "error": "Job not found."}), 404

    # Normalize status fields for frontend compatibility
    status = job.get("status", "queued")
    if status == "succeeded":
        status = "done"

    return jsonify({
        "job_id": job.get("id"),
        "session_id": session_id,
        "job_type": job.get("job_type"),
        "status": status,
        "progress": job.get("progress", 0),
        "progress_msg": job.get("progress_msg", ""),
        "error": job.get("error"),
        "result": job.get("result_payload"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }), 200
