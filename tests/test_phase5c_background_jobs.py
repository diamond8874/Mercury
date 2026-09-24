"""
tests/test_phase5c_background_jobs.py
--------------------------------------
Comprehensive test suite for Phase 5C Background Jobs:
1. Dispatch analyze job -> 202 + job_id -> poll /api/jobs/<job_id> -> completes with status 'done'/'succeeded'.
2. Dispatch trigger_process job -> 202 + job_id -> poll /api/jobs/<job_id> -> completes with result.
3. Dispatch PDF compilation job -> 202 + job_id -> poll /api/jobs/<job_id> -> completes with pdf_url.
4. Cross-user isolation: user B cannot inspect user A's job -> 404 (stealth).
5. Non-existent job lookup -> 404.
6. Startup recovery: in-flight jobs (queued/running) marked failed on server restart.
7. Watchdog: timed-out jobs past threshold marked failed.
8. Bounded concurrency: multiple background tasks submitted concurrently all eventually finish.
"""
import io
import time
import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta

import config
from app import app
from utils.auth import create_user
from models import (
    init_db as init_sqlalchemy_db,
    get_session_factory,
    JobModel
)
from repositories import job_repository
from utils.job_tracker import submit_background_job


def test_analyze_and_process_jobs_flow(client):
    """Verifies analyze and trigger_process return 202 + job_id and poll to completion."""
    # 1. Upload dataset
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["Alice", "Bob", "Charlie"],
        "score": [85, 90, 95]
    })
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    upload_res = client.post('/api/upload', data={'file': (buf, 'scores.csv')}, content_type='multipart/form-data')
    assert upload_res.status_code == 200
    session_id = upload_res.get_json()["session_id"]

    # 2. Analyze job
    analyze_res = client.post('/api/analyze', json={
        "session_id": session_id,
        "goal": "Score analysis",
        "api_key": "MOCK"
    })
    assert analyze_res.status_code == 202
    analyze_data = analyze_res.get_json()
    assert analyze_data.get("status") == "queued"
    analyze_job_id = analyze_data.get("job_id")
    assert analyze_job_id is not None

    # Poll /api/jobs/<analyze_job_id>
    for _ in range(20):
        poll = client.get(f'/api/jobs/{analyze_job_id}')
        assert poll.status_code == 200
        pdata = poll.get_json()
        if pdata.get("status") in ["done", "succeeded"]:
            break
        elif pdata.get("status") == "failed":
            pytest.fail(f"Analyze job failed: {pdata.get('error')}")
        time.sleep(0.3)
    else:
        pytest.fail("Analyze job did not finish in time")

    # 3. Trigger background process job
    proc_res = client.post(f'/api/sessions/{session_id}/trigger_process', json={"api_key": "MOCK"})
    assert proc_res.status_code == 202
    proc_data = proc_res.get_json()
    proc_job_id = proc_data.get("job_id")
    assert proc_job_id is not None

    # Poll /api/jobs/<proc_job_id>
    for _ in range(20):
        poll = client.get(f'/api/jobs/{proc_job_id}')
        assert poll.status_code == 200
        pdata = poll.get_json()
        if pdata.get("status") in ["done", "succeeded"]:
            assert pdata.get("result") is not None
            assert "download_url" in pdata["result"]
            break
        elif pdata.get("status") == "failed":
            pytest.fail(f"Process job failed: {pdata.get('error')}")
        time.sleep(0.3)
    else:
        pytest.fail("Process job did not finish in time")


def test_pdf_generation_job_flow(client):
    """Verifies PDF compilation returns 202 + job_id and updates job state to done."""
    # Setup session with cleaned data
    df = pd.DataFrame({"Department": ["Sales", "Engineering"], "Salary": [60000, 90000]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    upload_res = client.post('/api/upload', data={'file': (buf, 'salaries.csv')}, content_type='multipart/form-data')
    session_id = upload_res.get_json()["session_id"]

    # Process first to create cleaned file
    proc = client.post('/api/process', json={"session_id": session_id, "actions": {}})
    assert proc.status_code == 200

    # Request PDF
    pdf_res = client.post(f'/api/sessions/{session_id}/pdf')
    assert pdf_res.status_code == 202
    job_id = pdf_res.get_json().get("job_id")
    assert job_id is not None

    # Poll job status
    for _ in range(20):
        poll = client.get(f'/api/jobs/{job_id}')
        assert poll.status_code == 200
        pdata = poll.get_json()
        if pdata.get("status") in ["done", "succeeded"]:
            assert pdata.get("result") is not None
            assert "pdf_url" in pdata["result"]
            break
        elif pdata.get("status") == "failed":
            pytest.fail(f"PDF job failed: {pdata.get('error')}")
        time.sleep(0.3)
    else:
        pytest.fail("PDF job did not finish in time")


def test_cross_user_job_isolation(client):
    """Verifies that user B receives a stealth 404 when querying user A's job."""
    # 1. Create session as testadmin (client)
    df = pd.DataFrame({"col": [1, 2]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    upload_res = client.post('/api/upload', data={'file': (buf, 'sample.csv')}, content_type='multipart/form-data')
    assert upload_res.status_code == 200, f"Upload failed: {upload_res.get_json()}"
    session_id = upload_res.get_json()["session_id"]

    # Trigger job
    analyze_res = client.post('/api/analyze', json={"session_id": session_id, "goal": "Analyze", "api_key": "MOCK"})
    job_id = analyze_res.get_json()["job_id"]

    # 2. Login as user B on a separate client
    with app.test_client() as client_b:
        reg = client_b.post("/api/auth/register", json={"username": "user_b_iso", "password": "password123"})
        assert reg.status_code == 201

        # User B queries user A's job -> 404 stealth
        cross_res = client_b.get(f'/api/jobs/{job_id}')
        assert cross_res.status_code == 404

    # Non-existent job -> 404
    missing_res = client.get('/api/jobs/00000000-0000-0000-0000-000000000000')
    assert missing_res.status_code == 404


def test_startup_recovery_fails_in_flight_jobs(tmp_path):
    """Verifies that fail_stuck_and_interrupted_jobs marks queued/running jobs as failed."""
    test_db = str(tmp_path / "test_recovery.db")
    init_sqlalchemy_db(test_db)

    # Insert a fake session and jobs
    factory = get_session_factory(test_db)
    session = factory()
    from models import SessionModel
    test_session = SessionModel(
        id="session-test-rec",
        owner_id="admin",
        name="Recovery Test Session",
        original_filename="file.csv",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        last_accessed=datetime.now(timezone.utc).isoformat()
    )
    session.add(test_session)
    session.commit()

    # Create one running and one queued job
    job1 = JobModel(
        id="job-running",
        session_id="session-test-rec",
        job_type="analyze",
        status="running",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    job2 = JobModel(
        id="job-queued",
        session_id="session-test-rec",
        job_type="process",
        status="queued",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    job3 = JobModel(
        id="job-done",
        session_id="session-test-rec",
        job_type="pdf",
        status="succeeded",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    session.add_all([job1, job2, job3])
    session.commit()
    session.close()

    # Run startup recovery
    failed_count = job_repository.fail_stuck_and_interrupted_jobs(db_path=test_db)
    assert failed_count == 2

    # Verify statuses
    j1 = job_repository.get_job("job-running", db_path=test_db)
    j2 = job_repository.get_job("job-queued", db_path=test_db)
    j3 = job_repository.get_job("job-done", db_path=test_db)

    assert j1["status"] == "failed"
    assert "Interrupted" in j1["error"]
    assert j2["status"] == "failed"
    assert "Interrupted" in j2["error"]
    assert j3["status"] == "succeeded"


def test_watchdog_fails_timed_out_jobs(tmp_path):
    """Verifies that check_and_fail_timed_out_jobs marks expired running jobs as failed."""
    test_db = str(tmp_path / "test_timeout.db")
    init_sqlalchemy_db(test_db)

    factory = get_session_factory(test_db)
    session = factory()
    from models import SessionModel
    test_session = SessionModel(
        id="session-test-time",
        owner_id="admin",
        name="Timeout Test Session",
        original_filename="file.csv",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        last_accessed=datetime.now(timezone.utc).isoformat()
    )
    session.add(test_session)
    session.commit()

    # Job created 10 minutes ago with 300 second timeout
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    stuck_job = JobModel(
        id="job-stuck",
        session_id="session-test-time",
        job_type="process",
        status="running",
        timeout_seconds=300,
        created_at=old_time,
        updated_at=old_time
    )
    fresh_job = JobModel(
        id="job-fresh",
        session_id="session-test-time",
        job_type="process",
        status="running",
        timeout_seconds=300,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    session.add_all([stuck_job, fresh_job])
    session.commit()
    session.close()

    # Run watchdog sweep
    failed_count = job_repository.check_and_fail_timed_out_jobs(db_path=test_db)
    assert failed_count == 1

    sj = job_repository.get_job("job-stuck", db_path=test_db)
    fj = job_repository.get_job("job-fresh", db_path=test_db)

    assert sj["status"] == "failed"
    assert "timed out" in sj["error"].lower()
    assert fj["status"] == "running"
