import logging
import io
import pandas as pd
import pytest
from utils.url_validator import validate_base_url
from utils.logging_filter import APIKeyRedactionFilter, redact_sensitive_text
from services.data_service import summarize_schema
from services.ai_service import UnifiedLLMClient, get_llm_client


# ---------------------------------------------------------
# 1. SSRF & Base URL Validator Unit Tests
# ---------------------------------------------------------
def test_validate_base_url_cloud_metadata():
    """Ensure cloud metadata addresses (AWS, GCP, Azure) are strictly rejected."""
    # 169.254.169.254 AWS/GCP metadata
    valid, err = validate_base_url("http://169.254.169.254/latest/meta-data/", is_debug=True)
    assert not valid
    assert "metadata" in err.lower() or "disallowed" in err.lower() or "forbidden" in err.lower()

    valid, err = validate_base_url("https://169.254.169.254", is_debug=False)
    assert not valid
    assert "metadata" in err.lower() or "link-local" in err.lower() or "forbidden" in err.lower()


def test_validate_base_url_private_networks():
    """Ensure private network IPs (RFC 1918) are rejected."""
    for private_url in [
        "https://10.0.0.1",
        "https://10.255.255.255",
        "https://172.16.0.1",
        "https://172.31.255.255",
        "https://192.168.1.1",
        "https://192.168.100.50",
    ]:
        valid, err = validate_base_url(private_url, is_debug=False)
        assert not valid, f"Expected {private_url} to be rejected"
        assert "private" in err.lower() or "disallowed" in err.lower() or "forbidden" in err.lower()


def test_validate_base_url_scheme_and_ports():
    """Ensure non-https schemes and non-standard ports are rejected."""
    # Invalid schemes
    assert not validate_base_url("ftp://api.example.com", is_debug=False)[0]
    assert not validate_base_url("file:///etc/passwd", is_debug=False)[0]
    assert not validate_base_url("javascript:alert(1)", is_debug=False)[0]

    # HTTP in production (non-debug)
    assert not validate_base_url("http://api.openai.com", is_debug=False)[0]

    # Non-443 port on public host
    assert not validate_base_url("https://api.openai.com:8080", is_debug=False)[0]
    assert not validate_base_url("https://api.openai.com:22", is_debug=False)[0]


def test_validate_base_url_ollama_local_exception():
    """Ensure Ollama local dev (http://localhost:11434) is allowed in debug mode, but rejected in production."""
    # In debug mode -> allowed
    valid, err = validate_base_url("http://localhost:11434", is_debug=True)
    assert valid, f"Expected localhost:11434 to be valid in debug, got: {err}"

    valid, err = validate_base_url("http://127.0.0.1:11434", is_debug=True)
    assert valid, f"Expected 127.0.0.1:11434 to be valid in debug, got: {err}"

    # In production (non-debug) -> rejected
    valid, err = validate_base_url("http://localhost:11434", is_debug=False)
    assert not valid
    assert "debug" in err.lower() or "forbidden" in err.lower() or "http" in err.lower()


def test_validate_base_url_valid_https():
    """Ensure standard HTTPS on 443 with valid public hostname is permitted."""
    valid, err = validate_base_url("https://api.openai.com/v1", is_debug=False)
    assert valid, f"Expected valid public URL, got: {err}"

    valid, err = validate_base_url("https://integrate.api.nvidia.com/v1", is_debug=False)
    assert valid, f"Expected valid Nvidia API URL, got: {err}"


# ---------------------------------------------------------
# 2. Key Redaction Filter Tests
# ---------------------------------------------------------
def test_log_redaction_text():
    """Ensure all key formats are scrubbed by the redaction filter."""
    samples = [
        ("OpenAI key: sk-abcdefghijklmnopqrstuvwxyz1234567890", "sk-abcdefghijklmnopqrstuvwxyz1234567890"),
        ("Anthropic key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456"),
        ("Gemini key: AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6", "AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6"),
        ("Nvidia key: nvapi-abcdefghijklmnopqrstuvwxyz1234567890", "nvapi-abcdefghijklmnopqrstuvwxyz1234567890"),
        ("Groq key: gsk_abcdefghijklmnopqrstuvwxyz1234567890", "gsk_abcdefghijklmnopqrstuvwxyz1234567890"),
        ("Authorization: Bearer mySecretToken1234567890abcdefghij", "mySecretToken1234567890abcdefghij"),
        ("Payload: api_key='sk-1234567890abcdefghijklmn'", "sk-1234567890abcdefghijklmn"),
    ]

    for raw, secret in samples:
        redacted = redact_sensitive_text(raw)
        assert secret not in redacted, f"Failed to redact {secret} from: {redacted}"
        assert "[REDACTED_API_KEY]" in redacted


def test_logging_filter_handler():
    """Ensure logging.Filter intercepts and modifies log record messages."""
    logger = logging.getLogger("test_redaction_logger")
    logger.setLevel(logging.INFO)

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.addFilter(APIKeyRedactionFilter())
    logger.addHandler(handler)

    test_key = "sk-12345678901234567890abcdefghij"
    logger.info("Attempted request using key: %s", test_key)

    output = log_stream.getvalue()
    assert test_key not in output
    assert "[REDACTED_API_KEY]" in output


# ---------------------------------------------------------
# 3. Prompt Size Capping Unit Tests
# ---------------------------------------------------------
def test_summarize_schema_caps_columns():
    """Ensure datasets with excessive columns (>50) are capped and annotated."""
    # Create DataFrame with 65 columns
    data = {f"col_{i}": [i, i * 2, i * 3] for i in range(65)}
    df = pd.DataFrame(data)

    summary = summarize_schema(df, max_samples=1, max_columns=50)

    # 50 real columns + 1 truncation notification item
    assert len(summary) == 51
    assert summary[-1]["column_name"].startswith("[... 15 additional columns")


def test_summarize_schema_caps_sample_length_and_count():
    """Ensure sample count is bounded (<=3) and sample text is truncated (<=120 chars)."""
    giant_string = "A" * 500
    df = pd.DataFrame({
        "text_col": [giant_string, "second", "third", "fourth", "fifth"]
    })

    # Request 10 samples (should be capped at 3)
    summary = summarize_schema(df, max_samples=10, max_val_chars=120)

    samples = summary[0]["sample_values"]
    assert len(samples) == 3
    # Check that the 500-char string was truncated to 120 chars inside delimiter
    assert len(giant_string) not in [len(s) for s in samples]
    assert len(samples[0]) <= 120 + len("<untrusted_sample_value></untrusted_sample_value>")


# ---------------------------------------------------------
# 4. Route-Level Base URL SSRF Rejection Integration Tests
# ---------------------------------------------------------
def test_route_analyze_rejects_ssrf(client):
    """POST /api/analyze must reject SSRF base_url with 400."""
    # First upload dummy CSV to get a valid session
    df = pd.DataFrame({"id": [1, 2], "val": [10, 20]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    up_resp = client.post('/api/upload', data={'file': (buf, 'ssrf_test.csv')}, content_type='multipart/form-data')
    assert up_resp.status_code == 200
    session_id = up_resp.get_json()["session_id"]

    # Attempt SSRF via /api/analyze
    resp = client.post('/api/analyze', json={
        "session_id": session_id,
        "goal": "Test SSRF",
        "api_key": "MOCK",
        "base_url": "http://169.254.169.254/latest/meta-data/"
    })
    assert resp.status_code == 400
    assert "Invalid base_url" in resp.get_json()["error"]


def test_route_chat_rejects_ssrf(client):
    """POST /api/sessions/<id>/chat must reject SSRF base_url with 400."""
    df = pd.DataFrame({"id": [1, 2], "val": [10, 20]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    up_resp = client.post('/api/upload', data={'file': (buf, 'ssrf_chat_test.csv')}, content_type='multipart/form-data')
    session_id = up_resp.get_json()["session_id"]

    resp = client.post(f'/api/sessions/{session_id}/chat', json={
        "message": "Hello",
        "api_key": "MOCK",
        "model": "gpt-4o",
        "base_url": "https://10.0.0.1"
    })
    assert resp.status_code == 400
    assert "Invalid base_url" in resp.get_json()["error"]


def test_route_chat_stream_rejects_ssrf(client):
    """POST /api/sessions/<id>/chat/stream must reject SSRF base_url with 400."""
    df = pd.DataFrame({"id": [1, 2], "val": [10, 20]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    up_resp = client.post('/api/upload', data={'file': (buf, 'ssrf_stream_test.csv')}, content_type='multipart/form-data')
    session_id = up_resp.get_json()["session_id"]

    resp = client.post(f'/api/sessions/{session_id}/chat/stream', json={
        "message": "Hello",
        "api_key": "MOCK",
        "model": "gpt-4o",
        "base_url": "http://192.168.1.1"
    })
    assert resp.status_code == 400
    assert "Invalid base_url" in resp.get_json()["error"]


# ---------------------------------------------------------
# 5. Client Safeguards (Direct Class Instantiation)
# ---------------------------------------------------------
def test_unified_llm_client_prohibits_ssrf_base_url():
    """UnifiedLLMClient directly raises ValueError on invalid base_url."""
    with pytest.raises(ValueError, match="Prohibited or invalid base_url"):
        UnifiedLLMClient(api_key="test", base_url="http://169.254.169.254")
