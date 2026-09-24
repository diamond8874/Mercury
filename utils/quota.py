import os
import json
import logging
from flask import current_app

def count_user_sessions(owner_id: str) -> int:
    """Count sessions owned by owner_id in repository or session folder."""
    try:
        from repositories.session_repository import get_session_repository
        repo = get_session_repository()
        count = repo.count_by_owner(owner_id)
        if count > 0:
            return count
    except Exception:
        pass

    session_folder = current_app.config.get('SESSION_FOLDER', '')
    count = 0
    try:
        for name in os.listdir(session_folder):
            if not name.endswith('.json'):
                continue
            path = os.path.join(session_folder, name)
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if data.get('owner_id') == owner_id:
                    count += 1
            except Exception:
                pass
    except OSError:
        pass
    return count

def user_storage_bytes(owner_id: str) -> int:
    """
    Sum the on-disk size of every file owned by owner_id:
    raw uploads + cleaned outputs.
    """
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    output_folder = current_app.config.get('OUTPUT_FOLDER', '')
    session_folder = current_app.config.get('SESSION_FOLDER', '')
    total = 0
    try:
        for name in os.listdir(session_folder):
            if not name.endswith('.json'):
                continue
            path = os.path.join(session_folder, name)
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if data.get('owner_id') != owner_id:
                    continue
                file_id = data.get('file_id')
                if file_id:
                    p = os.path.join(upload_folder, file_id)
                    if os.path.exists(p):
                        total += os.path.getsize(p)
                cleaned = data.get('cleaned_filename')
                if cleaned:
                    p = os.path.join(output_folder, cleaned)
                    if os.path.exists(p):
                        total += os.path.getsize(p)
            except Exception:
                pass
    except OSError:
        pass
    return total
