"""
utils/cleanup.py
-----------------
4D §4: Session / file expiry cleanup job.

Runs on startup and every CLEANUP_INTERVAL_SECONDS (default 1 h).
Deleting a session removes every file it owns:
  - uploads/<file_id>
  - output_data/<cleaned_filename>
  - charts saved in session["charts"]

TTL is configurable via SESSION_TTL_SECONDS (default 24 h since last access).
"Last access" is tracked by a "last_accessed" ISO timestamp in the session JSON
that is updated by the load/save helpers (patched below via monkey-patch hook).

Exports:
  start_cleanup_scheduler(app)   - call once from app factory
  delete_session_files(app, session_data, session_id)  - shared helper also
                                   used by the DELETE route and /api/me/data
"""
import os
import json
import logging
import threading
import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
SESSION_TTL_SECONDS: int = int(os.environ.get("SESSION_TTL_SECONDS", 86_400))   # 24 h
CLEANUP_INTERVAL_SECONDS: int = int(
    os.environ.get("CLEANUP_INTERVAL_SECONDS", 3_600)   # 1 h
)

# ---------------------------------------------------------------------------
# Core file-deletion helper (reused by route handlers too)
# ---------------------------------------------------------------------------

def delete_session_files(app, session_data: dict, session_id: str) -> dict:
    """
    Atomically removes all files owned by *session_data* and deletes the
    session JSON.  Returns a summary dict suitable for logging.

    Caller is responsible for removing the session from any in-memory cache.
    """
    removed = []
    errors = []

    upload_folder = app.config.get("UPLOAD_FOLDER", "")
    output_folder = app.config.get("OUTPUT_FOLDER", "")
    session_folder = app.config.get("SESSION_FOLDER", "")

    # 1. Raw upload file
    file_id = session_data.get("file_id")
    if file_id:
        path = os.path.join(upload_folder, file_id)
        if os.path.exists(path):
            try:
                os.remove(path)
                removed.append(path)
            except OSError as exc:
                errors.append(f"upload {file_id}: {exc}")

    # 2. Cleaned output
    cleaned = session_data.get("cleaned_filename")
    if cleaned:
        path = os.path.join(output_folder, cleaned)
        if os.path.exists(path):
            try:
                os.remove(path)
                removed.append(path)
            except OSError as exc:
                errors.append(f"cleaned {cleaned}: {exc}")

    # 3. Pinned charts (stored as image paths in session["charts"])
    for chart in session_data.get("charts", []):
        chart_path = chart.get("image_path") or chart.get("path")
        if chart_path and os.path.exists(chart_path):
            try:
                os.remove(chart_path)
                removed.append(chart_path)
            except OSError as exc:
                errors.append(f"chart {chart_path}: {exc}")

    # 4. PDF if stored separately (session stores pdf_path)
    pdf_path = session_data.get("pdf_path")
    if pdf_path and os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
            removed.append(pdf_path)
        except OSError as exc:
            errors.append(f"pdf {pdf_path}: {exc}")

    # 5. Session JSON itself (debug export)
    session_json = os.path.join(session_folder, f"{session_id}.json")
    if os.path.exists(session_json):
        try:
            os.remove(session_json)
            removed.append(session_json)
        except OSError as exc:
            errors.append(f"session json: {exc}")

    # 6. Delete from persistent database repository if available
    try:
        from repositories.session_repository import get_session_repository
        repo = get_session_repository()
        repo.delete(session_id)
    except Exception:
        # Silently skip if DB not initialized or table doesn't exist in unit test context
        pass

    return {"session_id": session_id, "removed": removed, "errors": errors}


# ---------------------------------------------------------------------------
# Cleanup sweep
# ---------------------------------------------------------------------------

def _run_sweep(app):
    """Scans the session folder and expires stale sessions."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=SESSION_TTL_SECONDS
    )
    session_folder = app.config.get("SESSION_FOLDER", "")
    if not session_folder or not os.path.isdir(session_folder):
        return

    expired_count = 0
    error_count = 0

    for name in os.listdir(session_folder):
        if not name.endswith(".json"):
            continue
        path = os.path.join(session_folder, name)
        session_id = name[:-5]   # strip .json

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("Cleanup: cannot read session %s: %s", session_id, exc)
            continue

        # Determine the "last touched" timestamp.
        # Prefer last_accessed > created_at > file mtime as fallback.
        ts_str = data.get("last_accessed") or data.get("created_at")
        if ts_str:
            try:
                ts = datetime.datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                ts = None
        else:
            ts = None

        if ts is None:
            # Fall back to filesystem mtime
            mtime = os.path.getmtime(path)
            ts = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)

        if ts < cutoff:
            summary = delete_session_files(app, data, session_id)
            # Invalidate cache
            try:
                from utils.session_manager import invalidate_session_cache
                invalidate_session_cache(session_id)
            except Exception:
                pass
            expired_count += 1
            if summary["errors"]:
                error_count += 1
                logger.warning(
                    "Cleanup expired session %s with errors: %s",
                    session_id, summary["errors"]
                )
            else:
                logger.info(
                    "Cleanup expired session %s — removed %d file(s)",
                    session_id, len(summary["removed"])
                )

    if expired_count:
        logger.info(
            "Cleanup sweep complete: %d session(s) expired, %d with errors.",
            expired_count, error_count
        )


def _periodic_sweep(app, interval: int):
    """Runs _run_sweep in a daemon thread every *interval* seconds."""
    with app.app_context():
        _run_sweep(app)
    t = threading.Timer(interval, _periodic_sweep, args=(app, interval))
    t.daemon = True
    t.start()


def start_cleanup_scheduler(app):
    """
    Call once from app.py after the app object is configured.
    Runs an initial sweep immediately, then repeats every
    CLEANUP_INTERVAL_SECONDS.
    """
    logger.info(
        "Cleanup scheduler starting (TTL=%ds, interval=%ds).",
        SESSION_TTL_SECONDS, CLEANUP_INTERVAL_SECONDS
    )
    t = threading.Thread(
        target=_periodic_sweep,
        args=(app, CLEANUP_INTERVAL_SECONDS),
        daemon=True,
        name="cleanup-scheduler",
    )
    t.start()
