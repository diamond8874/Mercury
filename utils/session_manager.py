"""
utils/session_manager.py
------------------------
Session Manager facade connecting to the persistent SessionRepository
while maintaining backwards-compatible function signatures, in-memory caching,
and debug JSON export capability.
"""
import os
import json
import logging
import datetime
import threading
import uuid
from flask import current_app
import pandas as pd
import numpy as np

import config
from models import init_db as init_models_db
from repositories.session_repository import get_session_repository

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
    """Sanitizes session_id and validates it strictly as a UUID string."""
    if not session_id or not isinstance(session_id, str):
        return None
    clean_id = os.path.basename(session_id).strip()
    try:
        val = uuid.UUID(clean_id)
        return str(val)
    except (ValueError, TypeError, AttributeError):
        return None

def invalidate_session_cache(session_id):
    """Removes a session from the in-memory cache."""
    clean_id = sanitize_session_id(session_id)
    if clean_id:
        with CACHE_LOCK:
            SESSION_CACHE.pop(clean_id, None)

def export_session_to_json(session_data: dict) -> str:
    """Exports a session dictionary to a JSON file on disk for debugging and inspections."""
    if not session_data or 'session_id' not in session_data:
        return ""
    clean_id = sanitize_session_id(session_data['session_id'])
    if not clean_id:
        return ""
    folder = get_session_folder()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{clean_id}.json")
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, cls=CustomJSONEncoder, indent=2, ensure_ascii=False)
        return path
    except Exception as e:
        logging.warning("Error writing debug session JSON (%s): %s", clean_id, str(e))
        return ""

def load_session(session_id):
    """Loads session from the relational SessionRepository with in-memory caching and fallback."""
    clean_id = sanitize_session_id(session_id)
    if not clean_id:
        logging.warning("Invalid or unsafe session_id rejected: %s", session_id)
        return None

    # Check fast in-memory cache first
    with CACHE_LOCK:
        if clean_id in SESSION_CACHE:
            return json.loads(json.dumps(SESSION_CACHE[clean_id]))

    # Query persistent database repository
    repo = get_session_repository()
    try:
        data = repo.get_by_id(clean_id)
        if data:
            with CACHE_LOCK:
                SESSION_CACHE[clean_id] = data
            return data
    except Exception as db_err:
        logging.warning("Repository load failed (%s), falling back to filesystem: %s", clean_id, str(db_err))

    # Filesystem fallback if DB lookup fails
    path = os.path.join(get_session_folder(), f"{clean_id}.json")
    if os.path.exists(path):
        with SESSION_LOCK:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    with CACHE_LOCK:
                        SESSION_CACHE[clean_id] = data
                    # Sync into database
                    try:
                        repo.save(data)
                    except Exception:
                        pass
                    return data
            except Exception as e:
                logging.error("Error loading fallback session JSON (%s): %s", clean_id, str(e))
    return None

def save_session(session_data):
    """Persists session to SessionRepository, in-memory cache, and updates debug JSON export."""
    if not session_data or 'session_id' not in session_data:
        return

    session_id = session_data['session_id']
    clean_id = sanitize_session_id(session_id)
    if not clean_id:
        logging.warning("Invalid or unsafe session_id in save_session: %s", session_id)
        return

    with CACHE_LOCK:
        SESSION_CACHE[clean_id] = session_data

    # Save to persistent database repository
    repo = get_session_repository()
    try:
        repo.save(session_data)
    except Exception as db_err:
        logging.error("Repository save failed (%s): %s", clean_id, str(db_err))

    # Keep a JSON export for debugging and compatibility
    export_session_to_json(session_data)
