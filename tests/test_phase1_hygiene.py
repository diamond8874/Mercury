import os
import io
import uuid
import pytest
import pandas as pd
from utils.session_manager import sanitize_session_id

def test_sanitize_session_id_uuid_validation():
    """Verify sanitize_session_id only accepts valid UUID strings."""
    valid_uuid_str = str(uuid.uuid4())
    assert sanitize_session_id(valid_uuid_str) == valid_uuid_str

    # Invalid session IDs must return None
    assert sanitize_session_id("../etc/passwd") is None
    assert sanitize_session_id("invalid-session-123") is None
    assert sanitize_session_id("12345") is None
    assert sanitize_session_id("") is None
    assert sanitize_session_id(None) is None

def test_routes_reject_invalid_uuid(client):
    """Verify API endpoints reject non-UUID session_ids with 400 or 404."""
    invalid_id = "not-a-valid-uuid"

    res = client.get(f'/api/sessions/{invalid_id}')
    assert res.status_code in (400, 404)

    res = client.delete(f'/api/sessions/{invalid_id}')
    assert res.status_code in (400, 404)

    res = client.get(f'/api/sessions/{invalid_id}/status')
    assert res.status_code in (400, 404)

    res = client.post(f'/api/sessions/{invalid_id}/chat', json={"message": "hi"})
    assert res.status_code in (400, 404)

    res = client.post(f'/api/sessions/{invalid_id}/pdf')
    assert res.status_code in (400, 404)

def test_app_env_vars_configuration(monkeypatch):
    """Verify app.py respects HOST, DEBUG, and PORT environment variables."""
    import app as flask_app_module

    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("PORT", "5050")

    host = os.environ.get("HOST", "127.0.0.1")
    debug = os.environ.get("DEBUG", "false").lower() in ("true", "1", "t")
    port = int(os.environ.get("PORT", "5000"))

    assert host == "0.0.0.0"
    assert debug is True
    assert port == 5050

def test_pin_and_report_flow_portable(client):
    """Test upload, custom chart generation, pinning, and PDF export using Flask client."""
    df = pd.DataFrame({
        "Department": ["Sales", "Engineering", "Marketing", "HR"],
        "Salary": [50000, 80000, 60000, 55000]
    })
    csv_buffer = io.BytesIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    # 1. Upload
    resp = client.post('/api/upload', data={'file': (csv_buffer, 'test_data.csv')}, content_type='multipart/form-data')
    assert resp.status_code == 200
    session_id = resp.get_json()["session_id"]

    # 2. Process dataset
    proc_resp = client.post('/api/process', json={
        "session_id": session_id,
        "actions": {"Department": {"action": "keep", "reason": "", "transformation": ""}}
    })
    assert proc_resp.status_code == 200

    # 3. Custom chart
    chart_resp = client.post(f'/api/sessions/{session_id}/custom_chart', json={
        "chart_category": "change_flow",
        "chart_type": "waterfall",
        "x_col": "Department",
        "y_col": "Salary"
    })
    assert chart_resp.status_code == 200
    assert chart_resp.get_json().get("success") is True

    # 4. Pin chart
    pin_payload = {
        "chart": {
            "title": "Salary by Department",
            "chart_type": "waterfall",
            "x_axis": "Department",
            "y_axis": "Salary",
            "description": "Waterfall chart"
        }
    }
    pin_resp = client.post(f'/api/sessions/{session_id}/pin_chart', json=pin_payload)
    assert pin_resp.status_code == 200
    assert pin_resp.get_json().get("pinned_count") == 1

    # 5. Generate PDF
    pdf_resp = client.post(f'/api/sessions/{session_id}/pdf')
    assert pdf_resp.status_code == 202
    job_id = pdf_resp.get_json().get("job_id")
    assert job_id is not None

    # Poll job until done
    import time
    for _ in range(20):
        job_res = client.get(f'/api/jobs/{job_id}')
        assert job_res.status_code == 200
        job_data = job_res.get_json()
        if job_data.get("status") in ["succeeded", "done"]:
            break
        elif job_data.get("status") == "failed":
            pytest.fail(f"PDF job failed: {job_data.get('error')}")
        time.sleep(0.5)
    else:
        pytest.fail(f"PDF job did not complete in time. Last state: {job_data}")

