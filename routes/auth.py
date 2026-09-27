"""
routes/auth.py
--------------
Blueprint for user authentication: registration, login, logout, and current user info.
Also serves root static/index.html and favicon.
"""
from flask import Blueprint, request, jsonify, send_from_directory
from flask_login import current_user, login_user, logout_user

from utils.auth import create_user, authenticate_user, get_db_path
import sqlite3
import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    user, err = create_user(username, password)
    if err:
        return jsonify({"status": "error", "error": err}), 400
    login_user(user, remember=True)
    return jsonify({"status": "success", "user": user.to_dict()}), 201


@auth_bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    remember = bool(data.get('remember', True))
    ip = request.remote_addr or "127.0.0.1"
    user, err, status_code = authenticate_user(username, password, ip=ip)
    if err:
        return jsonify({"status": "error", "error": err}), status_code
    login_user(user, remember=remember)
    return jsonify({"status": "success", "user": user.to_dict()}), 200


@auth_bp.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    if current_user.is_authenticated:
        logout_user()
    return jsonify({"status": "success", "message": "Logged out successfully"}), 200


@auth_bp.route('/api/auth/me', methods=['GET'])
def auth_me():
    if current_user.is_authenticated:
        return jsonify({
            "authenticated": True,
            "user": current_user.to_dict()
        }), 200
    return jsonify({
        "authenticated": False,
        "user": None
    }), 200


@auth_bp.route('/')
def index():
    return send_from_directory('static', 'index.html')


@auth_bp.route('/dashboard')
def dashboard():
    return send_from_directory('static', 'app.html')


@auth_bp.route('/feedback')
def feedback_page():
    return send_from_directory('static', 'feedback.html')


@auth_bp.route('/api/feedback', methods=['POST'])
def submit_feedback():
    data = request.get_json(silent=True) or {}
    rating = data.get('rating')
    comment = data.get('comment')
    user_id = current_user.id if current_user.is_authenticated else 'anonymous'
    
    if not rating:
        return jsonify({"status": "error", "error": "Rating is required"}), 400
        
    try:
        with sqlite3.connect(get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO feedback (user_id, rating, comment, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, rating, comment, datetime.datetime.utcnow().isoformat())
            )
            conn.commit()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@auth_bp.route('/favicon.ico')
def favicon():
    return '', 204
