"""
routes/__init__.py
------------------
Central blueprint registration hub for Mercury backend.
"""
from flask import Flask, jsonify, request
from flask_login import current_user

from routes.auth import auth_bp
from routes.upload import upload_bp
from routes.sessions import sessions_bp
from routes.cleaning import cleaning_bp
from routes.chat import chat_bp
from routes.visualization import visualization_bp
from routes.reports import reports_bp
from routes.jobs import jobs_bp


def register_blueprints(app: Flask):
    """Registers all route blueprints onto the Flask application instance."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(cleaning_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(visualization_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(jobs_bp)

    @app.before_request
    def require_api_auth():
        exempt_paths = [
            '/',
            '/favicon.ico',
            '/api/auth/login',
            '/api/auth/register',
            '/api/auth/logout',
            '/api/auth/me',
            '/api/health'
        ]
        if request.path in exempt_paths or request.path.startswith('/static'):
            return None

        if request.path.startswith('/api/'):
            if not current_user.is_authenticated:
                return jsonify({
                    "status": "unauthorized",
                    "error": "Authentication required. Please log in."
                }), 401

    @app.errorhandler(500)
    def handle_internal_error(e):
        return jsonify({
            "status": "error",
            "error": "An internal server error occurred."
        }), 500

    @app.errorhandler(404)
    def handle_not_found_error(e):
        if request.path.startswith('/api/'):
            return jsonify({
                "status": "error",
                "error": "Endpoint not found."
            }), 404
        return e
