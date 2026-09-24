import os
import sqlite3
import logging
import uuid
import datetime
import re
import time
from functools import wraps
from typing import Optional, Tuple, Dict, Any

from flask import current_app, jsonify, request
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash

import config
from utils.session_manager import load_session, save_session, sanitize_session_id, get_session_folder

# In-memory login attempt tracker for brute-force protection
# Key: (ip, username_lower) -> list of failure timestamps
LOGIN_ATTEMPTS: Dict[Tuple[str, str], list] = {}
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_FAILED_ATTEMPTS = 5

class User(UserMixin):
    def __init__(self, id: str, username: str, is_admin: bool = False):
        self.id = id
        self.username = username
        self.is_admin = is_admin

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "is_admin": self.is_admin
        }

def get_db_path(custom_path: Optional[str] = None) -> str:
    if custom_path:
        return custom_path
    try:
        if current_app:
            return current_app.config.get('DATABASE_PATH', config.DATABASE_PATH)
    except RuntimeError:
        pass
    return config.DATABASE_PATH

def init_db(db_path: Optional[str] = None):
    """Initializes the SQLite database and ensures the users table exists."""
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0
            )
        """)
        conn.commit()

def get_user_by_id(user_id: str, db_path: Optional[str] = None) -> Optional[User]:
    """Loads a user by unique ID for Flask-Login user_loader."""
    path = get_db_path(db_path)
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return User(id=row[0], username=row[1], is_admin=bool(row[2]))
    except Exception as e:
        logging.error(f"Error loading user by id {user_id}: {str(e)}")
    return None

def get_user_by_username(username: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Loads raw user record by username."""
    path = get_db_path(db_path)
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, password_hash, is_admin FROM users WHERE LOWER(username) = ?",
                (username.strip().lower(),)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "username": row[1],
                    "password_hash": row[2],
                    "is_admin": bool(row[3])
                }
    except Exception as e:
        logging.error(f"Error loading user by username {username}: {str(e)}")
    return None

def count_users(db_path: Optional[str] = None) -> int:
    """Returns the total number of registered users."""
    path = get_db_path(db_path)
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            row = cursor.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0

def create_user(username: str, password: str, db_path: Optional[str] = None) -> Tuple[Optional[User], Optional[str]]:
    """
    Registers a new user with validation, password hashing, and auto-admin for first user.
    Auto-migrates unowned sessions to the first registered admin user.
    """
    clean_username = (username or "").strip()
    if not clean_username or len(clean_username) < 3 or len(clean_username) > 30:
        return None, "Username must be between 3 and 30 characters."
    if not re.match(r'^[a-zA-Z0-9_.-]+$', clean_username):
        return None, "Username may only contain letters, numbers, underscores, dots, or hyphens."

    if not password or len(password) < 8:
        return None, "Password must be at least 8 characters long."

    init_db(db_path)
    existing = get_user_by_username(clean_username, db_path)
    if existing:
        return None, "Username is already taken."

    user_id = str(uuid.uuid4())
    pw_hash = generate_password_hash(password)
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # First user is granted administrator status
    is_admin = 1 if count_users(db_path) == 0 else 0

    path = get_db_path(db_path)
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (id, username, password_hash, created_at, is_admin) VALUES (?, ?, ?, ?, ?)",
                (user_id, clean_username, pw_hash, created_at, is_admin)
            )
            conn.commit()

        new_user = User(id=user_id, username=clean_username, is_admin=bool(is_admin))
        
        # If this is the admin user, migrate existing unowned sessions
        if is_admin:
            try:
                migrate_unowned_sessions(user_id)
            except Exception as mig_err:
                logging.warning(f"Session migration warning: {mig_err}")

        return new_user, None
    except Exception as e:
        logging.error(f"Error creating user {clean_username}: {str(e)}")
        return None, f"Registration failed: {str(e)}"

def check_login_rate_limit(ip: str, username: str) -> Tuple[bool, int]:
    """Checks if an IP + account has exceeded the max login failure rate limit."""
    now = time.time()
    key = (ip, username.strip().lower())
    attempts = LOGIN_ATTEMPTS.get(key, [])
    # Filter attempts within the window
    recent = [t for t in attempts if now - t < RATE_LIMIT_WINDOW_SECONDS]
    LOGIN_ATTEMPTS[key] = recent
    if len(recent) >= MAX_FAILED_ATTEMPTS:
        wait_seconds = int(RATE_LIMIT_WINDOW_SECONDS - (now - recent[0]))
        return False, max(1, wait_seconds)
    return True, 0

def record_login_failure(ip: str, username: str):
    """Records a failed login attempt for rate limiting."""
    now = time.time()
    key = (ip, username.strip().lower())
    if key not in LOGIN_ATTEMPTS:
        LOGIN_ATTEMPTS[key] = []
    LOGIN_ATTEMPTS[key].append(now)

def clear_login_failures(ip: str, username: str):
    """Clears failed attempts on successful login."""
    key = (ip, username.strip().lower())
    LOGIN_ATTEMPTS.pop(key, None)

def authenticate_user(username: str, password: str, ip: str = "127.0.0.1", db_path: Optional[str] = None) -> Tuple[Optional[User], Optional[str], int]:
    """Authenticates credentials with brute-force rate-limiting."""
    clean_username = (username or "").strip()
    if not clean_username or not password:
        return None, "Username and password are required.", 400

    allowed, wait_secs = check_login_rate_limit(ip, clean_username)
    if not allowed:
        return None, f"Too many failed login attempts. Please wait {wait_secs} seconds.", 429

    user_dict = get_user_by_username(clean_username, db_path)
    if not user_dict or not check_password_hash(user_dict["password_hash"], password):
        record_login_failure(ip, clean_username)
        return None, "Invalid username or password.", 401

    clear_login_failures(ip, clean_username)
    user = User(id=user_dict["id"], username=user_dict["username"], is_admin=user_dict["is_admin"])
    return user, None, 200

def migrate_unowned_sessions(admin_user_id: str) -> int:
    """Assigns all existing sessions without an owner_id to the admin user."""
    folder = get_session_folder()
    if not os.path.exists(folder):
        return 0
    
    count = 0
    for filename in os.listdir(folder):
        if filename.endswith('.json'):
            session_id = filename[:-5]
            clean_id = sanitize_session_id(session_id)
            if not clean_id:
                continue
            data = load_session(clean_id)
            if data and not data.get("owner_id"):
                data["owner_id"] = admin_user_id
                save_session(data)
                count += 1
    if count > 0:
        logging.info(f"Migrated {count} unowned sessions to admin user {admin_user_id}.")
    return count

def get_owned_session_or_404(session_id: str, user_id: Optional[str] = None) -> Tuple[Optional[dict], Optional[Tuple[Any, int]]]:
    """
    Loads a session and verifies ownership.
    Returns (session_data, None) on success.
    Returns (None, (json_response, status_code)) on error.
    Returns 404 (stealth) if caller is not the owner, masking existence of the session.
    """
    clean_id = sanitize_session_id(session_id)
    if not clean_id:
        return None, (jsonify({"status": "error", "error": "Invalid session ID format"}), 400)

    session_data = load_session(clean_id)
    if not session_data:
        return None, (jsonify({"status": "error", "error": "Session not found"}), 404)

    # Determine caller user_id
    caller_id = user_id
    is_admin = False
    if caller_id is None and current_user and current_user.is_authenticated:
        caller_id = current_user.id
        is_admin = getattr(current_user, 'is_admin', False)

    owner_id = session_data.get("owner_id")

    # If session has an owner, caller must be owner or admin
    if owner_id:
        if caller_id != owner_id and not is_admin:
            # Stealth 404: do not reveal that this session belongs to another user
            return None, (jsonify({"status": "error", "error": "Session not found"}), 404)
    else:
        # If session has no owner yet, bind to current authenticated caller
        if caller_id:
            session_data["owner_id"] = caller_id
            save_session(session_data)

    return session_data, None

def login_required_api(f):
    """Decorator ensuring that API endpoints require an authenticated session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({
                "status": "unauthorized",
                "error": "Authentication required. Please log in."
            }), 401
        return f(*args, **kwargs)
    return decorated_function
