import os
import logging
from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
import config
from utils.fonts import download_lora_fonts
from utils.logging_filter import APIKeyRedactionFilter

# Configure logging with sensitive credential redaction filter
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
_redaction_filter = APIKeyRedactionFilter()
logging.getLogger().addFilter(_redaction_filter)
for _h in logging.getLogger().handlers:
    _h.addFilter(_redaction_filter)

INSECURE_SECRET_KEYS = {
    'placeholder',
    'your_secret_key_here',
    'changeme',
    'secret',
    'dev_key',
    '',
}

def validate_secret_key(key: str, is_debug: bool = False, is_testing: bool = False) -> str:
    """
    Validates SECRET_KEY for security.
    Refuses to start in production mode (non-debug) if SECRET_KEY is missing or insecure.
    """
    cleaned_key = (key or "").strip()
    if not cleaned_key or cleaned_key.lower() in INSECURE_SECRET_KEYS:
        if not is_debug and not is_testing:
            raise RuntimeError(
                "FATAL: SECRET_KEY must be set to a secure, non-placeholder value in production mode (DEBUG=false)."
            )
        logging.warning("Insecure or missing SECRET_KEY used in development/testing mode.")
        return "dev-insecure-secret-key-change-in-production"
    return cleaned_key

from flask_login import LoginManager, current_user
import datetime
from utils.auth import init_db, get_user_by_id
from utils.cleanup import start_cleanup_scheduler
from utils.limiter import limiter

# Initialize Flask app
app = Flask(__name__, static_folder='static', static_url_path='')

# Apply configuration settings
is_debug = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 't')
is_testing = os.environ.get('TESTING', 'false').lower() in ('true', '1', 't')
raw_secret = os.environ.get('SECRET_KEY')

app.config['SECRET_KEY'] = validate_secret_key(raw_secret, is_debug=is_debug, is_testing=is_testing)
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = config.OUTPUT_FOLDER
app.config['SESSION_FOLDER'] = config.SESSION_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['DATABASE_PATH'] = config.DATABASE_PATH
app.config['REMEMBER_COOKIE_DURATION'] = datetime.timedelta(days=14)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Pass quota constants into Flask config so routes can read them
app.config['MAX_SESSIONS_PER_USER'] = config.MAX_SESSIONS_PER_USER
app.config['MAX_STORAGE_BYTES_PER_USER'] = config.MAX_STORAGE_BYTES_PER_USER

# ---------------------------------------------------------------------------
# Flask-Limiter (4D §2)
# ---------------------------------------------------------------------------
limiter.init_app(app)
app.extensions["limiter"] = limiter

# Initialize Authentication & Database
init_db(config.DATABASE_PATH)
from models import init_db as init_sqlalchemy_db
init_sqlalchemy_db(config.DATABASE_PATH)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.session_protection = "strong"

@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(user_id)

@login_manager.unauthorized_handler
def handle_unauthorized():
    return jsonify({
        "status": "unauthorized",
        "error": "Authentication required. Please log in."
    }), 401

# Register Blueprints
from routes import register_blueprints
register_blueprints(app)

# 4A.4 Security Headers on all responses
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-src 'self' data:;"
    )
    return response

# 4A.5 Max Content Length 413 Error Handler
@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    max_mb = (app.config.get('MAX_CONTENT_LENGTH') or config.MAX_CONTENT_LENGTH) // (1024 * 1024)
    return jsonify({
        "status": "error",
        "error": f"File size exceeds maximum allowed upload limit ({max_mb}MB)."
    }), 413

# 4D §2: Rate-limit 429 handler
@app.errorhandler(429)
def handle_rate_limit(e):
    return jsonify({
        "status": "error",
        "error": "Too many requests. Please wait a moment and try again.",
        "retry_after": str(e.description)
    }), 429

# Initialize fonts
download_lora_fonts()

# 4D §4: Start background cleanup scheduler
start_cleanup_scheduler(app)

# 5C: Startup recovery - fail jobs that were left running/queued before server restart
def _startup_job_recovery():
    try:
        from repositories import job_repository
        count = job_repository.fail_stuck_and_interrupted_jobs(reason="Interrupted by server restart")
        if count:
            logging.info("[Startup] Marked %d interrupted job(s) as failed.", count)
    except Exception as _e:
        logging.warning("[Startup] Job recovery failed (DB may not be ready): %s", _e)


# 5C: Watchdog - periodically fail timed-out jobs
def _start_job_watchdog(flask_app):
    import threading

    def _watchdog():
        while True:
            import time
            time.sleep(60)  # check every 60 seconds
            try:
                with flask_app.app_context():
                    from repositories import job_repository
                    job_repository.check_and_fail_timed_out_jobs()
            except Exception as _we:
                logging.warning("[JobWatchdog] Error: %s", _we)

    t = threading.Thread(target=_watchdog, daemon=True, name="JobWatchdog")
    t.start()


_startup_job_recovery()
_start_job_watchdog(app)

if __name__ == '__main__':
    logging.info("Starting Flask application...")
    host = os.environ.get('HOST', '127.0.0.1')
    debug = is_debug
    port = int(os.environ.get('PORT', 5000))
    app.run(host=host, port=port, debug=debug)
