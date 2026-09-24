"""
routes/upload.py
----------------
Blueprint for dataset upload operations and file validation.
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user

from utils.helpers import allowed_file
from utils.limiter import limiter
from utils.quota import count_user_sessions, user_storage_bytes
from services.dataset_service import save_uploaded_file

upload_bp = Blueprint('upload', __name__)


@upload_bp.route('/api/upload', methods=['POST'])
@limiter.limit("10 per hour")
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not (file and allowed_file(file.filename)):
        return jsonify({"error": "Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV."}), 400

    # Quota checks
    if current_user.is_authenticated:
        max_sessions = current_app.config.get('MAX_SESSIONS_PER_USER', 20)
        if count_user_sessions(current_user.id) >= max_sessions:
            return jsonify({
                "error": f"Session quota reached ({max_sessions} active sessions). "
                         "Please delete old sessions before uploading a new file."
            }), 429

        max_storage = current_app.config.get('MAX_STORAGE_BYTES_PER_USER', 500 * 1024 * 1024)
        used_bytes = user_storage_bytes(current_user.id)
        if used_bytes + (request.content_length or 0) > max_storage:
            return jsonify({
                "error": f"Storage quota exceeded ({max_storage // (1024*1024)} MB). "
                         "Please delete old sessions to free space."
            }), 429

    user_id = current_user.id if current_user.is_authenticated else None
    result, err = save_uploaded_file(file, user_id=user_id)
    if err:
        err_msg, status_code = err
        return jsonify({"status": "error", "error": err_msg}), status_code

    return jsonify(result), 200
