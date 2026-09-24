import io
import pytest
from app import validate_secret_key, app

def test_secret_key_refusal_in_production():
    """Verify app refuses to start without valid SECRET_KEY when DEBUG is false."""
    insecure_examples = [None, "", "   ", "placeholder", "your_secret_key_here", "changeme", "dev_key"]
    for bad_key in insecure_examples:
        with pytest.raises(RuntimeError, match="FATAL: SECRET_KEY must be set"):
            validate_secret_key(bad_key, is_debug=False, is_testing=False)

def test_secret_key_allowed_in_debug_and_testing():
    """Verify dev/testing mode allows fallback without throwing fatal error."""
    dev_key = validate_secret_key(None, is_debug=True, is_testing=False)
    assert dev_key == "dev-insecure-secret-key-change-in-production"

    test_key = validate_secret_key("", is_debug=False, is_testing=True)
    assert test_key == "dev-insecure-secret-key-change-in-production"

def test_valid_secret_key_accepted():
    """Verify strong custom secret keys are accepted cleanly."""
    valid_key = "super-secret-random-hex-string-123456"
    assert validate_secret_key(valid_key, is_debug=False, is_testing=False) == valid_key

def test_security_headers_present(client):
    """Verify security headers (nosniff, DENY, same-origin, CSP) are set on responses."""
    resp = client.get('/api/sessions')
    assert resp.status_code == 200
    headers = resp.headers

    assert headers.get('X-Content-Type-Options') == 'nosniff'
    assert headers.get('X-Frame-Options') == 'DENY'
    assert headers.get('Referrer-Policy') == 'same-origin'
    
    csp = headers.get('Content-Security-Policy')
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "script-src 'self' https://cdn.jsdelivr.net" in csp
    assert "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com" in csp
    assert "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com" in csp
    assert "img-src 'self' data: blob:" in csp
    assert "frame-src 'self' data:" in csp

def test_max_content_length_413_rejection(client):
    """Verify uploads exceeding MAX_CONTENT_LENGTH receive a clean JSON 413 error."""
    # Temporarily set max content length to 100 bytes for test
    orig_limit = client.application.config.get('MAX_CONTENT_LENGTH')
    client.application.config['MAX_CONTENT_LENGTH'] = 100

    try:
        oversized_data = io.BytesIO(b"A" * 500)
        resp = client.post('/api/upload', data={'file': (oversized_data, 'too_large.csv')})
        assert resp.status_code == 413
        json_data = resp.get_json()
        assert json_data is not None
        assert json_data.get('status') == 'error'
        assert "exceeds maximum allowed upload limit" in json_data.get('error', '').lower()
    finally:
        client.application.config['MAX_CONTENT_LENGTH'] = orig_limit
