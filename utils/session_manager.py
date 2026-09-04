import os
import json
import logging
import datetime
import re
import time
import threading
from flask import current_app
import pandas as pd
import numpy as np
import config

SESSION_LOCK = threading.RLock()
SESSION_CACHE = {}
CACHE_LOCK = threading.RLock()

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def get_session_folder():
    try:
        if current_app:
            return current_app.config.get('SESSION_FOLDER', config.SESSION_FOLDER)
    except RuntimeError:
        pass
    return config.SESSION_FOLDER

def sanitize_session_id(session_id):
    """Sanitizes session_id to prevent path traversal vulnerabilities."""
    if not session_id or not isinstance(session_id, str):
        return None
    clean_id = os.path.basename(session_id).strip()
    if not re.match(r'^[a-zA-Z0-9_-]+$', clean_id):
        return None
    return clean_id

def invalidate_session_cache(session_id):
    """Removes a session from the in-memory cache when deleted."""
    clean_id = sanitize_session_id(session_id)
    if clean_id:
        with CACHE_LOCK:
            SESSION_CACHE.pop(clean_id, None)

def load_session(session_id):
    """Thread-safe session loader with sanitization and in-memory caching."""
    clean_id = sanitize_session_id(session_id)
    if not clean_id:
        logging.warning(f"Invalid or unsafe session_id rejected: {session_id}")
        return None

    # Check fast in-memory cache first
    with CACHE_LOCK:
        if clean_id in SESSION_CACHE:
            return json.loads(json.dumps(SESSION_CACHE[clean_id]))

    path = os.path.join(get_session_folder(), f"{clean_id}.json")
    if os.path.exists(path):
        with SESSION_LOCK:
            for attempt in range(5):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        with CACHE_LOCK:
                            SESSION_CACHE[clean_id] = data
                        return data
                except Exception as e:
                    time.sleep(0.05 * (attempt + 1))
                    if attempt == 4:
                        logging.error(f"Error loading session JSON ({clean_id}): {str(e)}")
    return None

def save_session(session_data):
    """Thread-safe session saver with retrying atomic replacement and cache sync."""
    if not session_data or 'session_id' not in session_data:
        return

    session_id = session_data['session_id']
    clean_id = sanitize_session_id(session_id)
    if not clean_id:
        logging.warning(f"Invalid or unsafe session_id in save_session: {session_id}")
        return

    # Update in-memory cache
    with CACHE_LOCK:
        SESSION_CACHE[clean_id] = session_data

    folder = get_session_folder()
    path = os.path.join(folder, f"{clean_id}.json")
    tmp_path = os.path.join(folder, f"{clean_id}.tmp")

    with SESSION_LOCK:
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, cls=CustomJSONEncoder, indent=2, ensure_ascii=False)
            
            # Retry loop for Windows file locking PermissionError
            for attempt in range(5):
                try:
                    os.replace(tmp_path, path)
                    break
                except PermissionError:
                    time.sleep(0.05 * (attempt + 1))
                    if attempt == 4:
                        raise
        except Exception as e:
            logging.error(f"Error saving session JSON ({clean_id}): {str(e)}")

