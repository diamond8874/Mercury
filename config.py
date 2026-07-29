"""
Application configuration.

Every value can be overridden with an environment variable so the same image
runs unchanged in development and production. See `.env.example` and
DEPLOYMENT.md.
"""

import os
import secrets
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Runtime mode
# ---------------------------------------------------------------------------
# ENVIRONMENT drives the safe defaults: 'production' turns off the debugger and
# turns on strict cookie/security headers.
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development').strip().lower()
IS_PRODUCTION = ENVIRONMENT == 'production'

# Flask needs a stable secret in production; a random one per boot would
# invalidate anything signed across a restart or across workers.
SECRET_KEY = os.environ.get('SECRET_KEY') or (
    None if IS_PRODUCTION else secrets.token_hex(32)
)

# Optional shared-secret gate for /api/*. Unset (the default) means no auth,
# which is only appropriate on localhost or behind an authenticating proxy.
API_TOKEN = os.environ.get('MERCURY_API_TOKEN') or None

# Trust X-Forwarded-* from this many reverse proxies (0 = none).
TRUSTED_PROXY_COUNT = _env_int('TRUSTED_PROXY_COUNT', 1 if IS_PRODUCTION else 0)

# Comma-separated allowlist for cross-origin API calls. Empty = same-origin only.
CORS_ORIGINS = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
# DATA_DIR lets a container mount one volume for all mutable state.
DATA_DIR = os.environ.get('DATA_DIR') or os.getcwd()

UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(DATA_DIR, 'uploads')
OUTPUT_FOLDER = os.environ.get('OUTPUT_FOLDER') or os.path.join(DATA_DIR, 'output_data')
SESSION_FOLDER = os.environ.get('SESSION_FOLDER') or os.path.join(DATA_DIR, 'sessions')

# File Upload Restrictions
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}
MAX_UPLOAD_MB = _env_int('MAX_UPLOAD_MB', 16)
MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------
# Uploaded datasets, cleaned files, chart PNGs and PDFs accumulate forever
# otherwise. Sessions older than this are swept at startup and after each
# upload. Set RETENTION_DAYS=0 to keep everything.
RETENTION_DAYS = _env_int('RETENTION_DAYS', 0 if not IS_PRODUCTION else 7)
MAX_SESSIONS = _env_int('MAX_SESSIONS', 0)  # 0 = unlimited

# ---------------------------------------------------------------------------
# LLM configuration (provider-agnostic)
# ---------------------------------------------------------------------------
# Mercury does not depend on any single vendor. Set the generic variables below
# and any OpenAI-compatible or Anthropic endpoint will work. The provider is
# auto-detected from the key prefix when LLM_PROVIDER is not set, and legacy
# per-vendor variables (OPENAI_API_KEY, NVIDIA_API_KEY, ANTHROPIC_API_KEY,
# GEMINI_API_KEY, GROQ_API_KEY, ...) are still honoured as fallbacks.
#
#   LLM_API_KEY   - the key itself; "MOCK" forces the offline rule engine
#   LLM_PROVIDER  - optional override, e.g. openai | anthropic | nvidia | groq
#   LLM_MODEL     - optional model id override
#   LLM_BASE_URL  - optional endpoint override (required for custom servers)
#
# These are read at call time by services/llm_provider.py; they are surfaced
# here so the values are visible in one place.
LLM_API_KEY = os.environ.get('LLM_API_KEY')
LLM_PROVIDER = os.environ.get('LLM_PROVIDER')
LLM_MODEL = os.environ.get('LLM_MODEL')
LLM_BASE_URL = os.environ.get('LLM_BASE_URL')

# Analysis / visualisation tuning
MAX_CHARTS = _env_int('MAX_CHARTS', 6)
PROFILE_WAIT_TIMEOUT = _env_int('PROFILE_WAIT_TIMEOUT', 180)

# Logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# Ensure necessary directories exist
for _folder in (UPLOAD_FOLDER, OUTPUT_FOLDER, SESSION_FOLDER):
    os.makedirs(_folder, exist_ok=True)


def validate():
    """
    Fail fast on misconfiguration. Returns a list of fatal problems; the caller
    decides whether to abort. Called from app.py at import time.
    """
    problems = []
    if IS_PRODUCTION:
        if not SECRET_KEY:
            problems.append("SECRET_KEY must be set when ENVIRONMENT=production.")
        if _env_flag('FLASK_DEBUG'):
            problems.append("FLASK_DEBUG must be off when ENVIRONMENT=production "
                            "(the Werkzeug debugger allows remote code execution).")
    return problems
