"""
Flask application factory and entry point.

Development:  python app.py
Production:   see wsgi.py and DEPLOYMENT.md (waitress / gunicorn)

Everything environment-dependent lives in config.py, so the same code runs in
both places without edits.
"""

import os
import sys
import hmac
import logging

from flask import Flask, jsonify, request

import config
from components.routes import api_blueprint
from utils.fonts import download_lora_fonts
from utils.session_manager import purge_old_sessions

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Endpoints reachable without the API token, when one is configured.
PUBLIC_PATHS = ('/api/health', '/api/ready')


def create_app():
    """Build a fully configured Flask app."""
    problems = config.validate()
    if problems:
        for problem in problems:
            logger.critical("Configuration error: %s", problem)
        raise RuntimeError("Refusing to start with an unsafe configuration: "
                           + " ".join(problems))

    app = Flask(__name__, static_folder='static', static_url_path='')

    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
    app.config['OUTPUT_FOLDER'] = config.OUTPUT_FOLDER
    app.config['SESSION_FOLDER'] = config.SESSION_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['JSON_SORT_KEYS'] = False

    if config.IS_PRODUCTION:
        app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            PREFERRED_URL_SCHEME='https',
        )

    # Behind a reverse proxy, honour X-Forwarded-* so redirects and logged
    # client IPs are correct. Disabled by default outside production because
    # trusting these headers when nothing sets them is a spoofing vector.
    if config.TRUSTED_PROXY_COUNT > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=config.TRUSTED_PROXY_COUNT,
            x_proto=config.TRUSTED_PROXY_COUNT,
            x_host=config.TRUSTED_PROXY_COUNT,
            x_prefix=config.TRUSTED_PROXY_COUNT,
        )

    app.register_blueprint(api_blueprint)
    _register_guards(app)
    _register_error_handlers(app)
    _register_ops_routes(app)

    download_lora_fonts()

    removed = purge_old_sessions(
        config.SESSION_FOLDER, config.UPLOAD_FOLDER, config.OUTPUT_FOLDER,
        retention_days=config.RETENTION_DAYS, max_sessions=config.MAX_SESSIONS)
    if removed:
        logger.info("Startup retention sweep removed %s session(s).", removed)

    logger.info("Mercury started in %s mode (auth=%s, retention=%sd)",
                config.ENVIRONMENT, "on" if config.API_TOKEN else "off",
                config.RETENTION_DAYS or "off")
    return app


def _register_guards(app):
    """Optional shared-secret auth, CORS allowlist and security headers."""

    @app.before_request
    def require_api_token():
        if not config.API_TOKEN:
            return None
        if not request.path.startswith('/api/'):
            return None
        if request.path in PUBLIC_PATHS:
            return None
        if request.method == 'OPTIONS':
            return None

        # Header is preferred. The query parameter exists because a plain
        # <a download> link cannot set headers; it is logged by proxies, so
        # deployments that care should front Mercury with a real auth proxy.
        supplied = (request.headers.get('X-API-Key')
                    or request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
                    or request.args.get('token', ''))
        # Constant-time compare: a length/prefix-sensitive check leaks the token.
        if not supplied or not hmac.compare_digest(supplied, config.API_TOKEN):
            return jsonify({"error": "Unauthorized. Supply the X-API-Key header."}), 401
        return None

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        if config.IS_PRODUCTION:
            response.headers.setdefault(
                'Strict-Transport-Security', 'max-age=31536000; includeSubDomains')

        origin = request.headers.get('Origin')
        if origin and origin in config.CORS_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        return response


def _register_error_handlers(app):
    """The API contract is "every failure is JSON"; Flask defaults to HTML."""

    @app.errorhandler(401)
    def handle_unauthorized(error):
        return jsonify({"error": getattr(error, "description", "Unauthorized")}), 401

    @app.errorhandler(404)
    def handle_not_found(error):
        return jsonify({"error": getattr(error, "description", "Resource not found")}), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return jsonify({"error": getattr(error, "description", "Method not allowed")}), 405

    @app.errorhandler(413)
    def handle_upload_too_large(_error):
        return jsonify({
            "error": f"File is too large. The maximum upload size is {config.MAX_UPLOAD_MB}MB."
        }), 413

    @app.errorhandler(500)
    def handle_server_error(_error):
        logger.exception("Unhandled server error")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        from werkzeug.exceptions import HTTPException
        # HTTPExceptions keep their own status code and message.
        if isinstance(error, HTTPException):
            return jsonify({"error": error.description}), error.code
        # In debug/test runs let the traceback surface instead of swallowing it
        # into a generic 500 - otherwise real failures become unreadable.
        if app.debug or app.testing:
            raise error
        logger.exception("Unhandled exception")
        return jsonify({"error": "Internal server error"}), 500


def _register_ops_routes(app):
    """Liveness and readiness probes for containers and load balancers."""

    @app.route('/api/health')
    def health():
        return jsonify({"status": "ok", "environment": config.ENVIRONMENT})

    @app.route('/api/ready')
    def ready():
        from services.llm_provider import resolve_llm_config

        checks = {}
        for name, folder in (('uploads', config.UPLOAD_FOLDER),
                             ('output_data', config.OUTPUT_FOLDER),
                             ('sessions', config.SESSION_FOLDER)):
            checks[name] = os.path.isdir(folder) and os.access(folder, os.W_OK)

        llm = resolve_llm_config()
        payload = {
            "status": "ready" if all(checks.values()) else "degraded",
            "storage": checks,
            # Mercury runs without a key, so this is informational, not fatal.
            "llm": {"provider": llm.provider, "model": llm.model, "has_key": bool(llm.api_key)},
            "auth_required": bool(config.API_TOKEN),
        }
        return jsonify(payload), (200 if all(checks.values()) else 503)


app = create_app()


if __name__ == '__main__':
    # debug=True exposes the Werkzeug console, which is remote code execution
    # for anyone who can reach the port. It is opt-out here and forbidden in
    # production by config.validate().
    debug = os.environ.get('FLASK_DEBUG', '0' if config.IS_PRODUCTION else '1') == '1'
    host = os.environ.get('FLASK_HOST') or ('127.0.0.1' if debug else '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', '5000'))

    if config.IS_PRODUCTION:
        logger.warning("ENVIRONMENT=production but you are on the Flask development "
                       "server. Use wsgi.py with waitress or gunicorn instead.")
    if debug and host != '127.0.0.1':
        logger.warning("Debug mode bound to %s - the Werkzeug debugger allows remote "
                       "code execution. Set FLASK_DEBUG=0 for anything shared.", host)

    logger.info("Serving on http://%s:%s (debug=%s)", host, port, debug)
    try:
        app.run(host=host, port=port, debug=debug)
    except OSError as exc:
        logger.critical("Could not bind %s:%s - %s", host, port, exc)
        sys.exit(1)
