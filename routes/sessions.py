"""
routes/sessions.py
------------------
Blueprint for listing, retrieving, deleting sessions, cell editing,
and checking background processing status.
"""
import os
import json
import logging
from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user

from utils.auth import get_owned_session_or_404
from utils.cleanup import delete_session_files
from utils.session_manager import invalidate_session_cache
from repositories import job_repository
from utils.job_tracker import submit_background_job
from services.dataset_service import update_cell_value
from services.data_service import run_background_process

sessions_bp = Blueprint('sessions', __name__)


@sessions_bp.route('/api/sessions', methods=['GET'])
def list_sessions():
    caller_id = current_user.id if current_user.is_authenticated else None
    is_admin = getattr(current_user, 'is_admin', False)

    try:
        from repositories.session_repository import get_session_repository
        repo = get_session_repository()
        sessions = repo.list_by_owner(owner_id=caller_id, is_admin=is_admin)
        if sessions:
            return jsonify(sessions), 200
    except Exception:
        pass

    sessions = []
    session_folder = current_app.config['SESSION_FOLDER']
    for name in os.listdir(session_folder):
        if name.endswith('.json'):
            path = os.path.join(session_folder, name)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    owner_id = data.get("owner_id")
                    if is_admin or owner_id == caller_id:
                        sessions.append({
                            "session_id": data.get("session_id"),
                            "name": data.get("name"),
                            "original_filename": data.get("original_filename"),
                            "goal": data.get("goal"),
                            "created_at": data.get("created_at")
                        })
            except Exception:
                pass
    sessions.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return jsonify(sessions), 200


@sessions_bp.route('/api/sessions/<session_id>', methods=['GET'])
def get_session_detail(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    # Ensure preview reflects the cleaned dataset if already processed
    cleaned_file = session_data.get("cleaned_filename")
    if cleaned_file:
        out_path = os.path.join(current_app.config['OUTPUT_FOLDER'], cleaned_file)
        if os.path.exists(out_path):
            try:
                import pandas as pd
                from services.dataset_service import get_safe_preview
                from utils.helpers import read_csv_robust
                if out_path.endswith('.csv'):
                    df_clean = read_csv_robust(out_path)
                else:
                    df_clean = pd.read_excel(out_path)
                session_data["preview"] = get_safe_preview(df_clean, 15)
                session_data["row_count"] = len(df_clean)
                session_data["col_count"] = len(df_clean.columns)
            except Exception as e:
                logging.warning("Could not refresh preview from cleaned file %s: %s", cleaned_file, e)

        # Backfill raw_preview if empty or fewer than 15 rows
        raw_prev = session_data.get("raw_preview")
        if (not raw_prev or len(raw_prev) < 15) and session_data.get("file_id"):
            raw_path = os.path.join(current_app.config['UPLOAD_FOLDER'], session_data["file_id"])
            if os.path.exists(raw_path):
                try:
                    import pandas as pd
                    from services.dataset_service import get_safe_preview
                    from utils.helpers import read_csv_robust
                    if raw_path.endswith('.csv'):
                        df_raw = read_csv_robust(raw_path)
                    else:
                        df_raw = pd.read_excel(raw_path)
                    session_data["raw_preview"] = get_safe_preview(df_raw, 15)
                    if not session_data.get("cleaned_filename"):
                        session_data["preview"] = session_data["raw_preview"]
                except Exception as e:
                    logging.warning("Could not backfill raw_preview: %s", e)

    return jsonify(session_data), 200


@sessions_bp.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    summary = delete_session_files(current_app._get_current_object(), session_data, session_id)
    invalidate_session_cache(session_id)
    if summary["errors"]:
        logging.warning("delete_session %s errors: %s", session_id, summary["errors"])
    logging.info("delete_session %s: removed %d file(s)", session_id, len(summary["removed"]))
    return jsonify({"success": True, "removed": len(summary["removed"])}), 200


@sessions_bp.route('/api/me/data', methods=['DELETE'])
def delete_my_data():
    if not current_user.is_authenticated:
        return jsonify({"status": "unauthorized", "error": "Authentication required."}), 401

    owner_id = current_user.id
    session_folder = current_app.config.get('SESSION_FOLDER', '')
    deleted_sessions = 0
    total_removed = 0
    errors = []

    try:
        for name in os.listdir(session_folder):
            if not name.endswith('.json'):
                continue
            path = os.path.join(session_folder, name)
            session_id = name[:-5]
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if data.get('owner_id') != owner_id:
                    continue
                summary = delete_session_files(current_app._get_current_object(), data, session_id)
                invalidate_session_cache(session_id)
                deleted_sessions += 1
                total_removed += len(summary["removed"])
                if summary["errors"]:
                    errors.extend(summary["errors"])
            except Exception as exc:
                errors.append(f"{session_id}: {exc}")
    except OSError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500

    logging.info("delete_my_data: user %s deleted %d session(s), %d file(s).", owner_id, deleted_sessions, total_removed)
    return jsonify({
        "success": True,
        "sessions_deleted": deleted_sessions,
        "files_removed": total_removed,
        "errors": errors
    }), 200


@sessions_bp.route('/api/sessions/<session_id>/update_cell', methods=['POST'])
def update_individual_cell(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    data = request.json or {}
    row_idx = data.get("row_index")
    col_name = data.get("column_name")
    new_val = data.get("new_value")

    if row_idx is None or not col_name:
        return jsonify({"error": "Missing row_index or column_name"}), 400

    result, err = update_cell_value(session_data, row_idx, col_name, new_val)
    if err:
        err_msg, status_code = err
        return jsonify({"error": err_msg}), status_code

    uid = current_user.id if current_user.is_authenticated else None
    submit_background_job(
        session_id, "process", run_background_process,
        current_app._get_current_object(), session_id, None,
        user_id=uid,
        timeout_seconds=300,
    )

    return jsonify(result), 200


@sessions_bp.route('/api/sessions/<session_id>/status', methods=['GET'])
def get_processing_status(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    # Read latest job from DB (multi-worker safe)
    job = job_repository.get_latest_job_for_session(session_id) or {}
    job_status = job.get("status", "idle")

    # Fallback: if no job row yet, read from session record directly
    if job_status in ["idle", None, ""] and session_data:
        status = session_data.get("status", "unknown")
        progress = session_data.get("progress", 0)
        res = session_data.get("bg_result") or session_data.get("result", {})

        if status in ["done", "analyze_done"] or session_data.get("cleaned_filename"):
            if session_data.get("cleaned_filename") and not (res or {}).get("download_url"):
                res = res or {}
                res["download_url"] = f"/api/download/{session_data['cleaned_filename']}"
            return jsonify({
                "status": "done",
                "result": res,
                "progress": 100,
                "progress_msg": "Done!"
            }), 200
        elif status == "error":
            return jsonify({
                "status": "error",
                "error": session_data.get("error", "Unknown error"),
                "progress": progress
            }), 200
        elif status:
            return jsonify({
                "status": status,
                "progress": progress,
                "result": res
            }), 200

    # Normalize succeeded -> done for frontend compatibility
    if job_status == "succeeded":
        job_status = "done"
    elif job_status == "failed":
        job_status = "error"

    return jsonify({
        "status": job_status,
        "progress": job.get("progress", 0),
        "progress_msg": job.get("progress_msg", ""),
        "error": job.get("error"),
        "result": job.get("result_payload"),
        "job_id": job.get("id"),
    }), 200
