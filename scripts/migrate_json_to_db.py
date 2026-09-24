"""
scripts/migrate_json_to_db.py
-----------------------------
One-off, idempotent migration script to import legacy JSON session files
and unstructured dataset files into the relational database and storage layout.

Usage:
    python scripts/migrate_json_to_db.py --dry-run
    python scripts/migrate_json_to_db.py --source-dir sessions --db-path users.db
"""
import os
import sys
import json
import shutil
import argparse
import logging
from typing import Dict, Any

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from models import init_db as init_models_db, get_session_factory
from repositories.session_repository import SessionRepository, get_session_repository
from repositories.storage_backend import get_storage_backend

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def migrate_sessions(source_dir: str, db_path: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Scans source_dir for .json session files, imports them into SQLite via SessionRepository,
    and copies raw datasets/cleaned outputs into the structured data/ folder.
    """
    logger.info("Starting session migration (dry_run=%s)", dry_run)
    logger.info("Source directory: %s", os.path.abspath(source_dir))
    logger.info("Target database:  %s", os.path.abspath(db_path))

    if not os.path.exists(source_dir):
        logger.warning("Source directory %s does not exist. Nothing to migrate.", source_dir)
        return {"total_found": 0, "migrated": 0, "skipped": 0, "errors": 0}

    if not dry_run:
        init_models_db(db_path)

    factory = get_session_factory(db_path)
    repo = SessionRepository(session_factory=factory)
    storage = get_storage_backend()

    total_found = 0
    migrated = 0
    skipped = 0
    errors = 0

    json_files = [f for f in os.listdir(source_dir) if f.endswith('.json')]
    total_found = len(json_files)

    for fname in json_files:
        session_id = fname[:-5]
        file_path = os.path.join(source_dir, fname)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            sess_id = data.get('session_id') or session_id
            owner_id = data.get('owner_id')

            # Check if session already exists in target DB
            existing = repo.get_by_id(sess_id)
            if existing is not None:
                logger.info("Session %s already exists in database. Skipping DB insert.", sess_id)
                skipped += 1
            else:
                if dry_run:
                    logger.info("[DRY-RUN] Would migrate session %s (name: %s, owner: %s)", sess_id, data.get('name'), owner_id)
                else:
                    repo.save(data)
                    logger.info("Successfully imported session %s into database.", sess_id)
                migrated += 1

            # Migrate associated files to data/<user_id>/<session_id>/
            raw_file_id = data.get('file_id')
            if raw_file_id:
                src_upload = os.path.join(config.UPLOAD_FOLDER, raw_file_id)
                if os.path.exists(src_upload):
                    if dry_run:
                        logger.info("[DRY-RUN] Would copy upload %s to storage for session %s", raw_file_id, sess_id)
                    else:
                        with open(src_upload, 'rb') as uf:
                            storage.save(owner_id, sess_id, raw_file_id, uf.read())

            cleaned_fn = data.get('cleaned_filename')
            if cleaned_fn:
                src_cleaned = os.path.join(config.OUTPUT_FOLDER, cleaned_fn)
                if os.path.exists(src_cleaned):
                    if dry_run:
                        logger.info("[DRY-RUN] Would copy cleaned file %s to storage for session %s", cleaned_fn, sess_id)
                    else:
                        with open(src_cleaned, 'rb') as cf:
                            storage.save(owner_id, sess_id, cleaned_fn, cf.read())

        except Exception as e:
            logger.error("Error migrating file %s: %s", fname, str(e))
            errors += 1

    summary = {
        "total_found": total_found,
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run
    }
    logger.info("Migration complete: %s", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy Mercury JSON sessions to persistent SQLite DB.")
    parser.add_argument("--source-dir", default=config.SESSION_FOLDER, help="Directory containing .json session files")
    parser.add_argument("--db-path", default=config.DATABASE_PATH, help="Path to SQLite database file")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and simulate without writing to DB or files")

    args = parser.parse_args()
    migrate_sessions(source_dir=args.source_dir, db_path=args.db_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
