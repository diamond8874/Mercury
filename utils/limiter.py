import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

def _rate_limit_key():
    """
    Key function for Flask-Limiter: prefer authenticated user ID over IP.
    Ensures per-user rate limit accounting.
    """
    from flask_login import current_user
    try:
        if current_user and current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return f"ip:{get_remote_address()}"

limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)
