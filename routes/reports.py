"""
routes/reports.py
-----------------
Blueprint for PDF report compilation, PDF download, and dataset file downloads.
PDF generation is now dispatched as a background job, returning 202 + job_id.
"""
import os
import re
import urllib.parse
import logging
from flask import Blueprint, jsonify, current_app, send_from_directory
from flask_login import current_user
from werkzeug.utils import secure_filename

from utils.auth import get_owned_session_or_404
from utils.limiter import limiter
from utils.job_tracker import submit_background_job
from services.report_service import build_pdf_report

reports_bp = Blueprint('reports', __name__)

# ---------------------------------------------------------------------------
# Background worker: PDF compilation (idempotent)
# ---------------------------------------------------------------------------
def _do_pdf(app_config_snapshot, session_data_snapshot, job_id=None):
    """Worker function for PDF report generation."""
    result, err = build_pdf_report(session_data_snapshot, app_config_snapshot)
    if err:
        err_msg, _ = err
        raise Exception(err_msg)
    return result or {}


@reports_bp.route('/api/sessions/<session_id>/pdf', methods=['POST'])
@limiter.limit("10 per hour")
def create_pdf_report(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    if not session_data.get("cleaned_filename"):
        return jsonify({"error": "No cleaned file exists. Please apply cleaning rules and process the dataset first."}), 400

    uid = current_user.id if current_user.is_authenticated else None
    # Snapshot config and session data for thread-safe passing
    config_snapshot = dict(current_app.config)

    job_id = submit_background_job(
        session_id, "pdf", _do_pdf,
        config_snapshot, dict(session_data),
        user_id=uid,
        timeout_seconds=180,
    )

    return jsonify({
        "status": "queued",
        "job_id": job_id,
        "message": "PDF generation started in background."
    }), 202


@reports_bp.route('/api/sessions/<session_id>/download_pdf', methods=['GET'])
def download_pdf_report(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp
    if not session_data.get("pdf_filename"):
        return jsonify({"error": "PDF report not found. Please click generate report first."}), 404

    safe_pdf_name = secure_filename(session_data["pdf_filename"])
    pdf_path = os.path.join(current_app.config['OUTPUT_FOLDER'], safe_pdf_name)
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Report PDF file not found on disk."}), 404

    return send_from_directory(current_app.config['OUTPUT_FOLDER'], safe_pdf_name, as_attachment=True)


@reports_bp.route('/api/download/<filename>', methods=['GET'])
def download_cleaned_file(filename):
    decoded = urllib.parse.unquote(filename)
    double_decoded = urllib.parse.unquote(decoded)
    for check_str in (filename, decoded, double_decoded):
        if '..' in check_str or '/' in check_str or '\\' in check_str:
            return jsonify({"status": "error", "error": "Invalid file path."}), 400

    safe_filename = secure_filename(filename)
    if not safe_filename or safe_filename != filename:
        if any(bad in filename for bad in ['..', '/', '\\', '%2e', '%2f', '%5c']):
            return jsonify({"status": "error", "error": "Invalid file path."}), 400

    uuid_match = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', safe_filename, re.I)
    if not uuid_match:
        return jsonify({"status": "error", "error": "File not found."}), 404

    session_id = uuid_match.group(1)
    _, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    file_path = os.path.join(current_app.config['OUTPUT_FOLDER'], safe_filename)
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "error": "File not found."}), 404

    return send_from_directory(current_app.config['OUTPUT_FOLDER'], safe_filename, as_attachment=True)


@reports_bp.route('/api/sessions/<session_id>/download/<kind>', methods=['GET'])
def download_session_file(session_id, kind):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    if kind == 'cleaned':
        target_file = session_data.get('cleaned_filename')
    elif kind == 'pdf':
        target_file = session_data.get('pdf_filename') or f"{session_id}_report.pdf"
    else:
        return jsonify({"status": "error", "error": f"Invalid download kind '{kind}'."}), 400

    if not target_file:
        return jsonify({"status": "error", "error": "Requested file is not ready yet."}), 404

    safe_filename = secure_filename(target_file)
    if '..' in safe_filename or '/' in safe_filename or '\\' in safe_filename:
        return jsonify({"status": "error", "error": "Invalid file path."}), 400

    return send_from_directory(current_app.config['OUTPUT_FOLDER'], safe_filename, as_attachment=True)
