"""
tests/test_phase4e_comprehensive.py
------------------------------------
Phase 4E Comprehensive Security & Hardening Test Suite:
1. Unauthenticated request to each /api/* route -> 401
2. User B requesting User A's session (each route) -> 404 (stealth)
3. /api/sessions lists only own sessions
4. Download of another user's file -> 404; "../" and encoded variants -> rejected (400/404)
5. session_id not a UUID -> 400
6. base_url validation matrix (127.0.0.1, localhost, 169.254.169.254, 10.0.0.5, private IP DNS -> rejected; valid public https -> accepted)
7. API key never present in logs or session JSON
8. Oversized upload -> 413; too many rows/columns -> clean 400
9. Rate limit exceeded -> 429
10. Cleanup removes expired session + all associated files, keeps fresh ones
11. App refuses to start without SECRET_KEY when DEBUG is false
"""
import io
import os
import re
import json
import logging
import datetime
import pytest
from unittest.mock import patch
import socket

from app import app, validate_secret_key
import config
from utils.auth import init_db, create_user
from utils.url_validator import validate_base_url
from utils.session_manager import save_session, load_session
import utils.cleanup as cleanup_mod


def _make_csv(rows=3, cols=2) -> bytes:
    header = ",".join(f"col{i}" for i in range(cols))
    data = ",".join(str(i) for i in range(cols))
    return ("\n".join([header] + [data] * rows)).encode()


# ---------------------------------------------------------------------------
# 1. Unauthenticated request to each /api/* route -> 401
# ---------------------------------------------------------------------------
def test_unauthenticated_request_to_each_api_route_returns_401(unauthenticated_client):
    test_uuid = "00000000-0000-0000-0000-000000000000"
    
    # Exhaustive list of all protected /api/ routes
    protected_calls = [
        ("GET", "/api/sessions", None),
        ("GET", f"/api/sessions/{test_uuid}", None),
        ("DELETE", f"/api/sessions/{test_uuid}", None),
        ("DELETE", "/api/me/data", None),
        ("POST", "/api/upload", {"file": (io.BytesIO(b"a,b\n1,2"), "test.csv")}),
        ("POST", "/api/analyze", {"session_id": test_uuid, "goal": "test"}),
        ("POST", "/api/process", {"session_id": test_uuid, "actions": {}}),
        ("POST", f"/api/sessions/{test_uuid}/trigger_process", {}),
        ("GET", f"/api/sessions/{test_uuid}/status", None),
        ("POST", f"/api/sessions/{test_uuid}/chat", {"message": "hi"}),
        ("POST", f"/api/sessions/{test_uuid}/chat/stream", {"message": "hi"}),
        ("POST", f"/api/sessions/{test_uuid}/pdf", {}),
        ("GET", f"/api/sessions/{test_uuid}/download_pdf", None),
        ("POST", f"/api/sessions/{test_uuid}/pin_chart", {"chart": {"title": "c"}}),
        ("GET", f"/api/sessions/{test_uuid}/pinned_charts", None),
        ("POST", f"/api/sessions/{test_uuid}/update_cell", {"row_index": 0, "column_name": "a", "new_value": 1}),
        ("GET", f"/api/download/cleaned_{test_uuid}.xlsx", None),
        ("GET", f"/api/sessions/{test_uuid}/download/cleaned", None),
        ("POST", f"/api/sessions/{test_uuid}/viz_chat", {"message": "chart"}),
        ("POST", f"/api/sessions/{test_uuid}/custom_chart", {"chart_category": "trend", "chart_type": "line"}),
        ("POST", f"/api/sessions/{test_uuid}/dry_run", {}),
    ]

    for method, path, payload in protected_calls:
        if method == "GET":
            resp = unauthenticated_client.get(path)
        elif method == "DELETE":
            resp = unauthenticated_client.delete(path)
        elif method == "POST":
            if payload and "file" in payload:
                resp = unauthenticated_client.post(path, data=payload)
            else:
                resp = unauthenticated_client.post(path, json=payload or {})
        assert resp.status_code == 401, f"Expected 401 for {method} {path}, got {resp.status_code}"
        data = resp.get_json()
        assert data.get("status") == "unauthorized" or "Authentication required" in str(data)


# ---------------------------------------------------------------------------
# 2. User B requesting User A's session (each route) -> 404 (stealth)
# ---------------------------------------------------------------------------
def test_user_b_requesting_user_a_session_returns_404_each_route(client, tmp_path):
    # 1. User A (testadmin) creates a session
    up_resp = client.post("/api/upload", data={"file": (io.BytesIO(_make_csv()), "user_a.csv")})
    assert up_resp.status_code == 200
    session_id_a = up_resp.get_json()["session_id"]

    # 2. Create User B and log in on a separate test client
    with app.test_client() as client_b:
        reg = client_b.post("/api/auth/register", json={"username": "user_b_isolation", "password": "password123"})
        assert reg.status_code == 201

        routes_to_test = [
            ("GET", f"/api/sessions/{session_id_a}", None),
            ("DELETE", f"/api/sessions/{session_id_a}", None),
            ("POST", "/api/analyze", {"session_id": session_id_a, "goal": "test"}),
            ("POST", "/api/process", {"session_id": session_id_a, "actions": {}}),
            ("POST", f"/api/sessions/{session_id_a}/trigger_process", {}),
            ("GET", f"/api/sessions/{session_id_a}/status", None),
            ("POST", f"/api/sessions/{session_id_a}/chat", {"message": "hi"}),
            ("POST", f"/api/sessions/{session_id_a}/chat/stream", {"message": "hi"}),
            ("POST", f"/api/sessions/{session_id_a}/pdf", {}),
            ("GET", f"/api/sessions/{session_id_a}/download_pdf", None),
            ("POST", f"/api/sessions/{session_id_a}/pin_chart", {"chart": {"title": "c"}}),
            ("GET", f"/api/sessions/{session_id_a}/pinned_charts", None),
            ("POST", f"/api/sessions/{session_id_a}/update_cell", {"row_index": 0, "column_name": "col0", "new_value": 99}),
            ("GET", f"/api/download/cleaned_{session_id_a}.xlsx", None),
            ("GET", f"/api/sessions/{session_id_a}/download/cleaned", None),
            ("POST", f"/api/sessions/{session_id_a}/viz_chat", {"message": "chart"}),
            ("POST", f"/api/sessions/{session_id_a}/custom_chart", {"chart_category": "trend", "chart_type": "line"}),
            ("POST", f"/api/sessions/{session_id_a}/dry_run", {}),
        ]

        for method, path, payload in routes_to_test:
            if method == "GET":
                resp = client_b.get(path)
            elif method == "DELETE":
                resp = client_b.delete(path)
            elif method == "POST":
                resp = client_b.post(path, json=payload or {})
            assert resp.status_code == 404, f"Stealth 404 violation for {method} {path}: got {resp.status_code}"


# ---------------------------------------------------------------------------
# 3. /api/sessions lists only own sessions
# ---------------------------------------------------------------------------
def test_api_sessions_lists_only_own_sessions(tmp_path):
    with app.test_client() as client_a:
        # Register User A (non-admin)
        reg_a = client_a.post("/api/auth/register", json={"username": "user_alpha", "password": "password123"})
        assert reg_a.status_code == 201
        up_a = client_a.post("/api/upload", data={"file": (io.BytesIO(_make_csv()), "user_alpha.csv")})
        assert up_a.status_code == 200
        id_a = up_a.get_json()["session_id"]

        with app.test_client() as client_b:
            # Register User B (non-admin)
            reg_b = client_b.post("/api/auth/register", json={"username": "user_beta", "password": "password123"})
            assert reg_b.status_code == 201
            up_b = client_b.post("/api/upload", data={"file": (io.BytesIO(_make_csv()), "user_beta.csv")})
            assert up_b.status_code == 200
            id_b = up_b.get_json()["session_id"]

            # User B listing sees ONLY session B
            list_b = client_b.get("/api/sessions").get_json()
            b_ids = [s["session_id"] for s in list_b]
            assert id_b in b_ids
            assert id_a not in b_ids

        # User A listing sees ONLY session A
        list_a = client_a.get("/api/sessions").get_json()
        a_ids = [s["session_id"] for s in list_a]
        assert id_a in a_ids
        assert id_b not in a_ids


# ---------------------------------------------------------------------------
# 4. Download of another user's file -> 404; "../" and encoded variants -> rejected
# ---------------------------------------------------------------------------
def test_download_isolation_and_traversal_variants(client):
    # Create session for User A
    up_a = client.post("/api/upload", data={"file": (io.BytesIO(_make_csv()), "user_a.csv")})
    id_a = up_a.get_json()["session_id"]

    # Place a dummy cleaned file on disk for session A
    cleaned_filename = f"cleaned_{id_a}.xlsx"
    cleaned_path = os.path.join(config.OUTPUT_FOLDER, cleaned_filename)
    with open(cleaned_path, "wb") as f:
        f.write(b"dummy-cleaned-content")

    # User B attempting to download User A's file receives 404
    with app.test_client() as client_b:
        client_b.post("/api/auth/register", json={"username": "user_b_dl", "password": "password123"})
        dl_resp = client_b.get(f"/api/download/{cleaned_filename}")
        assert dl_resp.status_code == 404
        dl_sess_resp = client_b.get(f"/api/sessions/{id_a}/download/cleaned")
        assert dl_sess_resp.status_code == 404

    # Traversal attempts: "../", "..\\", "%2e%2e%2f", "%252e%252e%252f", "foo/bar"
    traversal_patterns = [
        "../config.py",
        "..\\config.py",
        "%2e%2e%2fconfig.py",
        "%252e%252e%252fconfig.py",
        "..%2fconfig.py",
        "foo/bar",
        "arbitrary_file.csv"  # Non-UUID file download
    ]
    for pattern in traversal_patterns:
        resp = client.get(f"/api/download/{pattern}")
        assert resp.status_code in (400, 404), f"Traversal pattern {pattern} was not rejected: {resp.status_code}"


# ---------------------------------------------------------------------------
# 5. session_id not a UUID -> 400
# ---------------------------------------------------------------------------
def test_session_id_not_uuid_returns_400(client):
    invalid_ids = ["not-a-uuid", "12345", "select-from-sessions", "uuid-drop-table", "11111111-2222-3333-4444-55555555555g"]
    for bad_id in invalid_ids:
        # GET session detail
        r_get = client.get(f"/api/sessions/{bad_id}")
        assert r_get.status_code == 400, f"Expected 400 for bad_id '{bad_id}', got {r_get.status_code}"
        assert "Invalid session ID format" in r_get.get_json()["error"]

        # DELETE session
        r_del = client.delete(f"/api/sessions/{bad_id}")
        assert r_del.status_code == 400

        # POST analyze
        r_ana = client.post("/api/analyze", json={"session_id": bad_id, "goal": "test"})
        assert r_ana.status_code == 400

        # POST process
        r_prc = client.post("/api/process", json={"session_id": bad_id, "actions": {}})
        assert r_prc.status_code == 400

        # POST chat
        r_cht = client.post(f"/api/sessions/{bad_id}/chat", json={"message": "hello"})
        assert r_cht.status_code == 400

        # POST pdf
        r_pdf = client.post(f"/api/sessions/{bad_id}/pdf")
        assert r_pdf.status_code == 400


# ---------------------------------------------------------------------------
# 6. base_url validation matrix
# ---------------------------------------------------------------------------
def test_base_url_validation_matrix():
    # Production mode: is_debug=False
    # Loopback / local
    valid, _ = validate_base_url("http://127.0.0.1", is_debug=False)
    assert not valid
    valid, _ = validate_base_url("http://localhost", is_debug=False)
    assert not valid

    # Cloud metadata
    valid, _ = validate_base_url("http://169.254.169.254", is_debug=False)
    assert not valid
    valid, _ = validate_base_url("https://169.254.169.254", is_debug=False)
    assert not valid

    # Private network
    valid, _ = validate_base_url("http://10.0.0.5", is_debug=False)
    assert not valid
    valid, _ = validate_base_url("https://10.0.0.5", is_debug=False)
    assert not valid
    valid, _ = validate_base_url("https://192.168.1.1", is_debug=False)
    assert not valid

    # HTTPS URL resolving to a private IP (DNS rebinding / SSRF)
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 443))
        ]
        valid, err = validate_base_url("https://evil-internal.corporate.local", is_debug=False)
        assert not valid
        assert "private" in err.lower() or "blocked" in err.lower()

    # Valid public HTTPS URL
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("104.18.7.192", 443))
        ]
        valid, err = validate_base_url("https://api.openai.com/v1", is_debug=False)
        assert valid, f"Expected public https to pass, got error: {err}"


# ---------------------------------------------------------------------------
# 7. API key never present in logs or session JSON
# ---------------------------------------------------------------------------
def test_api_key_never_in_logs_or_session_json(client, caplog):
    secret_key = "nvapi-secret-key-xyz-98765"
    up_resp = client.post("/api/upload", data={"file": (io.BytesIO(_make_csv()), "key_test.csv")})
    assert up_resp.status_code == 200
    session_id = up_resp.get_json()["session_id"]

    with caplog.at_level(logging.INFO):
        # Trigger chat call passing the secret API key
        client.post(
            f"/api/sessions/{session_id}/chat",
            json={"message": "Clean this", "api_key": secret_key, "model": "mock-model"}
        )

    # Raw secret key must NEVER be in captured logs
    assert secret_key not in caplog.text

    # Raw secret key must NEVER be persisted in session JSON
    session_data = load_session(session_id)
    raw_json = json.dumps(session_data)
    assert secret_key not in raw_json
    assert "api_key" not in session_data


# ---------------------------------------------------------------------------
# 8. Oversized upload -> 413; too many rows/columns -> clean 400
# ---------------------------------------------------------------------------
def test_oversized_upload_and_shape_caps(client, monkeypatch):
    # Oversized upload exceeding MAX_CONTENT_LENGTH -> 413
    huge_data = b"x" * (17 * 1024 * 1024)  # 17MB exceeds 16MB limit
    resp_413 = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(huge_data), "huge.csv")},
        content_type="multipart/form-data"
    )
    assert resp_413.status_code == 413
    assert "exceeds" in resp_413.get_json()["error"]

    # Too many rows -> clean 400
    from utils import upload_validator
    monkeypatch.setattr(upload_validator, "MAX_ROWS", 3)
    resp_rows = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(_make_csv(rows=10)), "too_many_rows.csv")},
        content_type="multipart/form-data"
    )
    assert resp_rows.status_code == 400
    assert "rows" in resp_rows.get_json()["error"].lower()

    # Too many columns -> clean 400
    monkeypatch.setattr(upload_validator, "MAX_COLS", 2)
    resp_cols = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(_make_csv(rows=2, cols=6)), "too_many_cols.csv")},
        content_type="multipart/form-data"
    )
    assert resp_cols.status_code == 400
    assert "column" in resp_cols.get_json()["error"].lower()


# ---------------------------------------------------------------------------
# 9. Rate limit exceeded -> 429
# ---------------------------------------------------------------------------
def test_rate_limit_exceeded_returns_429(client):
    # Enable rate limiting in test app config
    app.config["RATELIMIT_ENABLED"] = True

    # upload endpoint is limited to 10 per hour
    hit_429 = False
    for i in range(15):
        resp = client.post("/api/upload", data={"file": (io.BytesIO(_make_csv()), f"rate_{i}.csv")})
        if resp.status_code == 429:
            hit_429 = True
            body = resp.get_json()
            assert "Rate limit" in body.get("error", "") or "Too many" in body.get("error", "")
            break

    assert hit_429, "Expected rate limit 429 after rapid successive uploads"


# ---------------------------------------------------------------------------
# 10. Cleanup removes expired session + all associated files, keeps fresh ones
# ---------------------------------------------------------------------------
def test_cleanup_removes_expired_and_keeps_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "SESSION_TTL_SECONDS", 10)

    session_dir = tmp_path / "sweep_sessions"
    upload_dir = tmp_path / "sweep_uploads"
    output_dir = tmp_path / "sweep_outputs"
    session_dir.mkdir(); upload_dir.mkdir(); output_dir.mkdir()

    from flask import Flask
    sweep_app = Flask(__name__)
    sweep_app.config["SESSION_FOLDER"] = str(session_dir)
    sweep_app.config["UPLOAD_FOLDER"] = str(upload_dir)
    sweep_app.config["OUTPUT_FOLDER"] = str(output_dir)

    # 1. Expired session (20s ago)
    expired_id = "00000000-aaaa-bbbb-cccc-000000000001"
    old_ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=20)).isoformat()
    exp_upload = str(upload_dir / f"{expired_id}.csv")
    with open(exp_upload, "w") as f: f.write("expired data")
    exp_output = str(output_dir / f"cleaned_{expired_id}.xlsx")
    with open(exp_output, "w") as f: f.write("expired clean")
    exp_json = str(session_dir / f"{expired_id}.json")
    with open(exp_json, "w") as f:
        json.dump({
            "session_id": expired_id,
            "file_id": f"{expired_id}.csv",
            "cleaned_filename": f"cleaned_{expired_id}.xlsx",
            "charts": [],
            "last_accessed": old_ts
        }, f)

    # 2. Fresh session (now)
    fresh_id = "00000000-aaaa-bbbb-cccc-000000000002"
    fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    fresh_upload = str(upload_dir / f"{fresh_id}.csv")
    with open(fresh_upload, "w") as f: f.write("fresh data")
    fresh_json = str(session_dir / f"{fresh_id}.json")
    with open(fresh_json, "w") as f:
        json.dump({
            "session_id": fresh_id,
            "file_id": f"{fresh_id}.csv",
            "cleaned_filename": None,
            "charts": [],
            "last_accessed": fresh_ts
        }, f)

    # Run cleanup sweep
    with sweep_app.app_context():
        cleanup_mod._run_sweep(sweep_app)

    # Expired session & files must be removed
    assert not os.path.exists(exp_upload)
    assert not os.path.exists(exp_output)
    assert not os.path.exists(exp_json)

    # Fresh session & files must remain intact
    assert os.path.exists(fresh_upload)
    assert os.path.exists(fresh_json)


# ---------------------------------------------------------------------------
# 11. App refuses to start without SECRET_KEY when DEBUG is false
# ---------------------------------------------------------------------------
def test_app_refuses_to_start_without_secret_key_when_debug_false():
    insecure_keys = ["", "   ", "placeholder", "your_secret_key_here", "changeme", "secret", "dev_key"]
    for bad_key in insecure_keys:
        with pytest.raises(RuntimeError, match="FATAL: SECRET_KEY must be set"):
            validate_secret_key(bad_key, is_debug=False, is_testing=False)

    # Valid key passes
    valid_key = "my-super-secret-production-random-token-2026"
    result = validate_secret_key(valid_key, is_debug=False, is_testing=False)
    assert result == valid_key
