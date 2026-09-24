import io
import json
import pytest
from app import app
from utils.auth import init_db, create_user, authenticate_user, migrate_unowned_sessions
from utils.session_manager import save_session

def test_unauthenticated_api_rejection(unauthenticated_client):
    """Verify that unauthenticated requests to protected /api/ routes return 401."""
    protected_endpoints = [
        ('/api/sessions', 'GET', None),
        ('/api/sessions/00000000-0000-0000-0000-000000000000', 'GET', None),
        ('/api/sessions/00000000-0000-0000-0000-000000000000', 'DELETE', None),
        ('/api/upload', 'POST', {'file': (io.BytesIO(b"a,b\n1,2"), 'test.csv')}),
        ('/api/analyze', 'POST', {'session_id': '00000000-0000-0000-0000-000000000000', 'goal': 'clean'}),
        ('/api/process', 'POST', {'session_id': '00000000-0000-0000-0000-000000000000', 'actions': {}}),
    ]

    for path, method, data in protected_endpoints:
        if method == 'GET':
            resp = unauthenticated_client.get(path)
        elif method == 'DELETE':
            resp = unauthenticated_client.delete(path)
        else:
            if data and 'file' in data:
                resp = unauthenticated_client.post(path, data=data)
            else:
                resp = unauthenticated_client.post(path, json=data or {})
        assert resp.status_code == 401, f"Expected 401 for {method} {path}, got {resp.status_code}"

        assert resp.get_json().get("status") == "unauthorized"

def test_registration_and_password_validation(unauthenticated_client):
    """Verify registration requirements: minimum 8 characters, unique username."""
    # Too short password
    resp = unauthenticated_client.post('/api/auth/register', json={"username": "alice", "password": "123"})
    assert resp.status_code == 400
    assert "at least 8 characters" in resp.get_json()["error"]

    # Valid registration
    resp = unauthenticated_client.post('/api/auth/register', json={"username": "alice", "password": "password123"})
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "success"

    # Duplicate username
    resp2 = unauthenticated_client.post('/api/auth/register', json={"username": "alice", "password": "password123"})
    assert resp2.status_code == 400
    assert "already taken" in resp2.get_json()["error"]

def test_login_rate_limiting(unauthenticated_client):
    """Verify brute-force rate limiter triggers 429 after 5 failed attempts."""
    # Attempt 5 incorrect logins
    for _ in range(5):
        resp = unauthenticated_client.post('/api/auth/login', json={"username": "target_user", "password": "wrongpassword"})
        assert resp.status_code in (401, 429)

    # 6th attempt should be blocked with 429
    resp_blocked = unauthenticated_client.post('/api/auth/login', json={"username": "target_user", "password": "wrongpassword"})
    assert resp_blocked.status_code == 429
    assert "Too many failed login attempts" in resp_blocked.get_json()["error"]

def test_user_session_isolation_and_stealth_404(client, tmp_path):
    """Verify User B cannot access or detect User A's session (stealth 404)."""
    # 1. User A (testadmin) creates a session
    csv_data = io.BytesIO(b"age,salary\n25,50000\n30,60000")
    up_resp = client.post('/api/upload', data={'file': (csv_data, 'user_a_data.csv')})
    assert up_resp.status_code == 200
    session_id_a = up_resp.get_json()['session_id']

    # User A can access it
    assert client.get(f'/api/sessions/{session_id_a}').status_code == 200

    # 2. Register & login as User B in a separate test client
    with app.test_client() as client_b:
        reg_b = client_b.post('/api/auth/register', json={"username": "user_b", "password": "password123"})
        assert reg_b.status_code == 201

        # User B calling User A's session receives 404 (stealth 404)
        get_resp = client_b.get(f'/api/sessions/{session_id_a}')
        assert get_resp.status_code == 404
        assert get_resp.get_json()["error"] == "Session not found"

        # User B calling delete receives 404
        del_resp = client_b.delete(f'/api/sessions/{session_id_a}')
        assert del_resp.status_code == 404

        # User B calling chat receives 404
        chat_resp = client_b.post(f'/api/sessions/{session_id_a}/chat', json={"message": "hello"})
        assert chat_resp.status_code == 404

        # User B listing sessions does NOT see User A's session
        list_resp = client_b.get('/api/sessions')
        assert list_resp.status_code == 200
        user_b_sessions = [s["session_id"] for s in list_resp.get_json()]
        assert session_id_a not in user_b_sessions

def test_invalid_session_id_format(client):
    """Verify non-UUID session IDs return 400."""
    resp = client.get('/api/sessions/invalid-not-a-uuid')
    assert resp.status_code == 400
    assert "Invalid session ID format" in resp.get_json()["error"]

def test_download_traversal_rejection(client):
    """Verify download endpoint rejects paths with '..' and slashes."""
    bad_paths = ['../config.py', '..\\config.py', 'foo/bar', 'foo\\bar']
    for p in bad_paths:
        resp = client.get(f'/api/download/{p}')
        assert resp.status_code in (400, 404)

def test_unowned_session_migration(tmp_path):
    """Verify existing unowned sessions are assigned to the admin user."""
    test_session_id = "11111111-2222-3333-4444-555555555555"
    session_data = {
        "session_id": test_session_id,
        "name": "legacy_data.csv",
        "owner_id": None
    }
    save_session(session_data)

    admin_id = "admin-uuid-1234"
    migrated_count = migrate_unowned_sessions(admin_id)
    assert migrated_count >= 1

    from utils.session_manager import load_session
    migrated = load_session(test_session_id)
    assert migrated["owner_id"] == admin_id
