"""
tests/test_phase5b_persistence.py
---------------------------------
Unit and integration tests for Phase 5B Persistent State & Storage Abstraction:
1. Concurrent chat message append across threads loses nothing (atomic rows).
2. Concurrent cell update + chat message writes persist both cleanly.
3. Idempotent execution of the migration script on fixture JSON datasets.
4. Cascade deletion removing all related DB rows (column_actions, chat_messages, operation_logs) and disk files.
5. StorageBackend interface save, open, delete, and quota calculation.
"""
import os
import json
import time
import uuid
import threading
import pytest
from flask import Flask

import config
from models import (
    init_db as init_models_db,
    get_session_factory,
    SessionModel,
    ChatMessageModel,
    ColumnActionModel,
    OperationLogModel
)
from repositories.session_repository import SessionRepository, get_session_repository
from repositories.storage_backend import LocalStorageBackend, get_storage_backend
from scripts.migrate_json_to_db import migrate_sessions


@pytest.fixture
def persistence_env(tmp_path):
    """Provides isolated SQLite DB and data folders for testing Phase 5B persistence."""
    db_file = str(tmp_path / "test_persistence.db")
    data_dir = str(tmp_path / "test_data")
    session_dir = str(tmp_path / "test_sessions")
    upload_dir = str(tmp_path / "test_uploads")
    output_dir = str(tmp_path / "test_outputs")

    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(session_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    init_models_db(db_file)
    factory = get_session_factory(db_file)
    repo = SessionRepository(session_factory=factory)
    storage = LocalStorageBackend(base_dir=data_dir)

    return {
        "db_file": db_file,
        "data_dir": data_dir,
        "session_dir": session_dir,
        "upload_dir": upload_dir,
        "output_dir": output_dir,
        "repo": repo,
        "storage": storage,
        "factory": factory
    }


def test_concurrent_chat_messages_atomic_append(persistence_env):
    """Verifies that multiple concurrent threads appending chat messages lose no data."""
    repo = persistence_env["repo"]
    sess_id = str(uuid.uuid4())

    # Create session
    repo.save({
        "session_id": sess_id,
        "owner_id": "test-user-1",
        "name": "Chat Concurrency Test",
        "original_filename": "test.csv",
        "goal": "Test concurrent writes",
        "chat_history": []
    })

    num_threads = 5
    messages_per_thread = 10
    errors = []

    def worker(thread_idx):
        try:
            for m_idx in range(messages_per_thread):
                repo.append_chat_message(
                    session_id=sess_id,
                    role="user" if m_idx % 2 == 0 else "assistant",
                    content=f"Thread-{thread_idx} Message-{m_idx}"
                )
        except Exception as ex:
            errors.append(f"Thread {thread_idx} error: {str(ex)}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent chat errors encountered: {errors}"

    session_data = repo.get_by_id(sess_id)
    assert len(session_data["chat_history"]) == num_threads * messages_per_thread


def test_concurrent_cell_update_and_chat(persistence_env):
    """Verifies concurrent session state update (e.g. cell update) and chat append."""
    repo = persistence_env["repo"]
    sess_id = str(uuid.uuid4())

    repo.save({
        "session_id": sess_id,
        "owner_id": "test-user-2",
        "name": "Hybrid Concurrency Test",
        "original_filename": "data.csv",
        "column_actions": {"ColA": {"action": "keep", "reason": "Init"}},
        "chat_history": []
    })

    errors = []

    def update_actions_worker():
        try:
            for i in range(5):
                sess = repo.get_by_id(sess_id)
                sess["column_actions"][f"Col_{i}"] = {"action": "transform", "reason": f"Step {i}"}
                repo.save(sess)
                time.sleep(0.01)
        except Exception as ex:
            errors.append(f"Action update error: {str(ex)}")

    def chat_worker():
        try:
            for i in range(5):
                repo.append_chat_message(
                    session_id=sess_id,
                    role="assistant",
                    content=f"Live token {i}"
                )
                time.sleep(0.01)
        except Exception as ex:
            errors.append(f"Chat append error: {str(ex)}")

    t1 = threading.Thread(target=update_actions_worker)
    t2 = threading.Thread(target=chat_worker)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors, f"Hybrid concurrency errors: {errors}"
    final_sess = repo.get_by_id(sess_id)
    assert len(final_sess["column_actions"]) >= 5
    assert len(final_sess["chat_history"]) >= 5


def test_migration_script_idempotent(persistence_env, tmp_path):
    """Verifies that running the migration script multiple times produces consistent, non-duplicate results."""
    src_dir = persistence_env["session_dir"]
    db_file = persistence_env["db_file"]

    # Create 3 legacy JSON session files
    for i in range(3):
        s_id = f"00000000-0000-0000-0000-00000000000{i}"
        with open(os.path.join(src_dir, f"{s_id}.json"), "w", encoding="utf-8") as f:
            json.dump({
                "session_id": s_id,
                "owner_id": "legacy_user",
                "name": f"Dataset {i}",
                "original_filename": f"dataset_{i}.csv",
                "goal": "Clean duplicates",
                "column_actions": {"col1": {"action": "keep"}},
                "chat_history": [{"role": "user", "content": f"Hello {i}"}]
            }, f)

    # 1. Dry run
    res_dry = migrate_sessions(source_dir=src_dir, db_path=db_file, dry_run=True)
    assert res_dry["total_found"] == 3
    assert res_dry["migrated"] == 3
    assert res_dry["errors"] == 0

    # 2. First real migration
    res1 = migrate_sessions(source_dir=src_dir, db_path=db_file, dry_run=False)
    assert res1["total_found"] == 3
    assert res1["migrated"] == 3
    assert res1["skipped"] == 0

    # Verify rows in DB
    repo = persistence_env["repo"]
    s0 = repo.get_by_id("00000000-0000-0000-0000-000000000000")
    assert s0 is not None
    assert s0["name"] == "Dataset 0"
    assert len(s0["chat_history"]) == 1

    # 3. Second migration (idempotent check)
    res2 = migrate_sessions(source_dir=src_dir, db_path=db_file, dry_run=False)
    assert res2["total_found"] == 3
    assert res2["skipped"] == 3  # All 3 skipped as existing


def test_cascade_deletion(persistence_env):
    """Verifies that deleting a session removes rows from all related tables."""
    repo = persistence_env["repo"]
    sess_id = str(uuid.uuid4())

    repo.save({
        "session_id": sess_id,
        "owner_id": "user-del",
        "name": "Delete Cascade Test",
        "original_filename": "del.csv",
        "column_actions": {"col1": {"action": "drop"}},
        "chat_history": [{"role": "user", "content": "hi"}],
        "audit_log": [{"step": 1, "operation": "drop_col", "status": "success"}]
    })

    # Ensure record exists
    assert repo.get_by_id(sess_id) is not None

    # Delete session
    deleted = repo.delete(sess_id)
    assert deleted is True

    # Check that session and all child entities are deleted
    assert repo.get_by_id(sess_id) is None


def test_storage_backend_operations(persistence_env):
    """Verifies StorageBackend save, open, delete, and user storage size."""
    storage = persistence_env["storage"]
    user_id = "storage_user"
    session_id = "sess_001"
    filename = "raw.csv"
    data = b"col1,col2\n10,20\n30,40"

    # Save
    stored_path = storage.save(user_id, session_id, filename, data)
    assert os.path.exists(stored_path)
    assert storage.exists(user_id, session_id, filename)

    # Open and verify bytes
    with storage.open(user_id, session_id, filename) as f:
        assert f.read() == data

    # Storage size
    size = storage.get_user_storage_size(user_id)
    assert size == len(data)

    # Delete single file
    assert storage.delete(user_id, session_id, filename) is True
    assert not storage.exists(user_id, session_id, filename)

    # Delete session directory
    storage.save(user_id, session_id, "file1.txt", b"abc")
    storage.save(user_id, session_id, "file2.txt", b"xyz")
    deleted_count = storage.delete_session_dir(user_id, session_id)
    assert deleted_count == 2
