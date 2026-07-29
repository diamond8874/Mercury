"""
Integration tests for the Mercury backend.

Everything runs against the offline rule engine (``api_key="MOCK"``), so the
suite never touches a network or needs a real provider key.
"""

import io
import os
import time
import shutil

import pandas as pd
import pytest

from app import app
from utils.session_manager import load_session
from utils.job_tracker import reset_job


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'test_uploads')
    app.config['OUTPUT_FOLDER'] = os.path.join(os.getcwd(), 'test_output_data')
    app.config['SESSION_FOLDER'] = os.path.join(os.getcwd(), 'test_sessions')

    for key in ('UPLOAD_FOLDER', 'OUTPUT_FOLDER', 'SESSION_FOLDER'):
        os.makedirs(app.config[key], exist_ok=True)

    import config
    originals = (config.UPLOAD_FOLDER, config.OUTPUT_FOLDER, config.SESSION_FOLDER)
    config.UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
    config.OUTPUT_FOLDER = app.config['OUTPUT_FOLDER']
    config.SESSION_FOLDER = app.config['SESSION_FOLDER']

    with app.test_client() as test_client:
        yield test_client

    for key in ('UPLOAD_FOLDER', 'OUTPUT_FOLDER', 'SESSION_FOLDER'):
        shutil.rmtree(app.config[key], ignore_errors=True)
    config.UPLOAD_FOLDER, config.OUTPUT_FOLDER, config.SESSION_FOLDER = originals


def _dirty_frame(rows=40):
    """A frame containing one of every problem the cleaner should catch."""
    return pd.DataFrame({
        "User_ID": [f"U{i:05d}" for i in range(rows)],
        "Customer_Name": [f"Person {i}" for i in range(rows)],
        "Age": [None if i % 9 == 0 else 20 + (i % 40) for i in range(rows)],
        "Gender": [["Male", "Female", None][i % 3] for i in range(rows)],
        "Monthly_Fee": [20.0 + (i % 30) * 3.0 for i in range(rows)],
        "Duplicated_Fee": [20.0 + (i % 30) * 3.0 for i in range(rows)],
        "Empty_Col": [None] * rows,
        "Constant_Col": ["same"] * rows,
        "Signup_Date": [f"2024-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}" for i in range(rows)],
        "Churned": [i % 3 == 0 for i in range(rows)],
    })


def _upload(client, frame=None, filename="dataset.csv"):
    buffer = io.BytesIO()
    (frame if frame is not None else _dirty_frame()).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post('/api/upload', data={'file': (buffer, filename)},
                           content_type='multipart/form-data')
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _poll_until(client, session_id, statuses, timeout=45):
    """Poll the status endpoint until it reports one of ``statuses``."""
    deadline = time.time() + timeout
    job = {}
    while time.time() < deadline:
        job = client.get(f'/api/sessions/{session_id}/status').get_json()
        if job["status"] in statuses:
            return job
        time.sleep(0.1)
    pytest.fail(f"Job stayed in '{job.get('status')}' instead of reaching {statuses}")


def _session(session_id):
    with app.app_context():
        return load_session(session_id)


# ---------------------------------------------------------------------------
# Basic routes
# ---------------------------------------------------------------------------

def test_index_route(client):
    assert client.get('/').status_code in (200, 404)


def test_list_sessions_empty(client):
    response = client.get('/api/sessions')
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


# ---------------------------------------------------------------------------
# Provider-agnostic LLM layer
# ---------------------------------------------------------------------------

def test_providers_endpoint_lists_multiple_vendors(client):
    data = client.get('/api/providers').get_json()
    ids = {p["id"] for p in data["providers"]}
    # Not just NVIDIA any more.
    assert {"openai", "anthropic", "nvidia", "google", "groq",
            "openrouter", "ollama", "custom"} <= ids
    assert "server_default" in data
    for provider in data["providers"]:
        assert {"id", "label", "base_url", "default_model", "transport"} <= set(provider)


@pytest.mark.parametrize("key,expected", [
    ("sk-ant-api03-xyz", "anthropic"),
    ("sk-proj-xyz", "openai"),
    ("sk-classic", "openai"),
    ("nvapi-xyz", "nvidia"),
    ("AIzaSyXYZ", "google"),
    ("gsk_xyz", "groq"),
    ("sk-or-v1-xyz", "openrouter"),
    ("xai-xyz", "xai"),
    ("pplx-xyz", "perplexity"),
    ("csk-xyz", "cerebras"),
    ("fw_xyz", "fireworks"),
    ("totally-unknown", None),
])
def test_provider_detection_from_key_prefix(key, expected):
    from services.llm_provider import detect_provider
    assert detect_provider(key) == expected


def test_resolve_config_honours_explicit_overrides():
    from services.llm_provider import resolve_llm_config

    anthropic = resolve_llm_config(api_key="sk-ant-test")
    assert anthropic.provider == "anthropic"
    assert anthropic.transport == "anthropic"
    assert anthropic.model  # a default model is always chosen

    custom = resolve_llm_config(api_key="anything", base_url="http://localhost:8000/v1",
                                model="my-local-model")
    assert custom.transport == "openai"
    assert custom.base_url == "http://localhost:8000/v1"
    assert custom.model == "my-local-model"

    # An explicit model must beat the provider default.
    pinned = resolve_llm_config(api_key="nvapi-x", model="meta/llama-3.3-70b-instruct")
    assert pinned.provider == "nvidia"
    assert pinned.model == "meta/llama-3.3-70b-instruct"

    # The public dict must never leak the key itself.
    assert "api_key" not in pinned.public_dict()
    assert pinned.public_dict()["has_key"] is True


def test_mock_key_forces_offline_engine():
    from services.llm_provider import get_llm_client
    client = get_llm_client(api_key="MOCK")
    assert client.is_mock and not client.is_live


def test_verify_endpoint_reports_offline_mode(client):
    response = client.post('/api/llm/verify', json={"api_key": "MOCK"})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_verify_endpoint_rejects_missing_key(client):
    response = client.post('/api/llm/verify', json={"provider": "openai", "api_key": ""})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Stage 1: upload reads the dataset and waits for input
# ---------------------------------------------------------------------------

def test_upload_profiles_dataset_without_running_analysis(client):
    """The core of issue #1: uploading must read, not analyse."""
    upload = _upload(client)
    session_id = upload["session_id"]
    assert upload["profiling"] is True

    job = _poll_until(client, session_id, {"profile_ready", "error"})
    assert job["status"] == "profile_ready"
    assert job["progress"] == 100

    # Nothing AI-driven may have happened yet.
    session = _session(session_id)
    assert session["goal"] == ""
    assert session["column_actions"] == {}
    assert session["cleaned_filename"] is None

    summary = job["result"]["profile_summary"]
    assert summary["shape"]["rows"] == 40
    assert summary["shape"]["cols"] == 10
    assert summary["missing_pct"] > 0
    assert any("Empty_Col" in warning for warning in summary["warnings"])
    reset_job(session_id)


def test_profile_endpoint_returns_full_statistics(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    profile = client.get(f'/api/sessions/{session_id}/profile').get_json()
    assert profile["shape"] == {"rows": 40, "cols": 10}
    assert "Monthly_Fee" in profile["numeric_columns"]
    assert "Signup_Date" in profile["datetime_columns"]        # not misread as an id
    assert "User_ID" in profile["identifier_columns"]
    assert profile["correlations"]                             # duplicate cols correlate at 1.0

    by_name = {c["name"]: c for c in profile["columns"]}
    assert by_name["Empty_Col"]["is_empty"] is True
    assert by_name["Constant_Col"]["is_constant"] is True
    assert by_name["Monthly_Fee"]["stats"]["min"] is not None
    reset_job(session_id)


def test_profile_endpoint_404_for_unknown_session(client):
    assert client.get('/api/sessions/does-not-exist/profile').status_code == 404


# ---------------------------------------------------------------------------
# Stage 2 & 3: goal -> analysis -> cleaning -> plotting
# ---------------------------------------------------------------------------

def test_async_analysis_runs_full_pipeline_and_plots(client):
    """Issue #1's second half: one goal submission produces charts too."""
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    response = client.post('/api/analyze', json={
        "session_id": session_id,
        "goal": "Predict Churned using Age and Monthly_Fee",
        "api_key": "MOCK",
    })
    assert response.status_code == 202
    assert response.get_json()["status"] == "analyzing"

    job = _poll_until(client, session_id, {"done", "error"})
    assert job["status"] == "done", job.get("error")

    result = job["result"]
    assert result["stats"]["final_cols"] < result["stats"]["initial_cols"]
    assert result["download_url"].endswith(".xlsx")
    assert result["preview"]

    # Plotting must actually happen - this was dead code before.
    assert len(result["charts"]) >= 3
    for chart in result["charts"]:
        assert chart["chart_type"] in ("histogram", "bar", "pie", "line", "scatter")
        assert chart.get("labels") or chart.get("points")

    actions = _session(session_id)["column_actions"]
    assert actions["Empty_Col"]["action"] == "drop"
    assert actions["Constant_Col"]["action"] == "drop"
    assert actions["Duplicated_Fee"]["action"] == "drop"
    assert actions["User_ID"]["action"] == "drop"
    assert actions["Age"]["action"] == "transform"
    reset_job(session_id)


def test_analysis_waits_for_profile_when_goal_submitted_immediately(client):
    """Submitting the goal before profiling finishes must not lose the profile."""
    session_id = _upload(client)["session_id"]

    # Deliberately no _poll_until here - fire straight after upload.
    response = client.post('/api/analyze', json={
        "session_id": session_id, "goal": "predict churn", "api_key": "MOCK"})
    assert response.status_code == 202

    job = _poll_until(client, session_id, {"done", "error"})
    assert job["status"] == "done", job.get("error")
    assert _session(session_id)["profile"] is not None
    reset_job(session_id)


def test_synchronous_analysis_returns_recommendations_inline(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    response = client.post('/api/analyze', json={
        "session_id": session_id,
        "goal": "Predict churn based on subscription fee and age",
        "api_key": "MOCK",
        "wait": True,
        "chain_process": False,
    })
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["recommendations"]) == 10
    assert data["source"] == "offline"
    assert {r["action"] for r in data["recommendations"]} <= {"keep", "drop", "transform"}
    reset_job(session_id)


def test_analyze_requires_session_and_goal(client):
    assert client.post('/api/analyze', json={"goal": "x"}).status_code == 400
    assert client.post('/api/analyze', json={"session_id": "abc"}).status_code == 400
    assert client.post('/api/analyze', json={"session_id": "nope", "goal": "x"}).status_code == 404


def test_synchronous_process_endpoint_cleans_and_charts(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK", "wait": True, "chain_process": False})

    actions = _session(session_id)["column_actions"]
    response = client.post('/api/process', json={
        "session_id": session_id, "actions": actions, "api_key": "MOCK"})
    assert response.status_code == 200

    data = response.get_json()
    assert data["success"] is True
    assert data["stats"]["final_cols"] < data["stats"]["initial_cols"]
    assert len(data["charts"]) >= 1
    assert client.get(data["download_url"]).status_code == 200
    reset_job(session_id)


def test_trigger_process_respects_manual_overrides(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK", "wait": True, "chain_process": False})

    actions = _session(session_id)["column_actions"]
    actions["Monthly_Fee"] = {"action": "drop", "reason": "manual override",
                              "transformation": None}

    response = client.post(f'/api/sessions/{session_id}/trigger_process',
                           json={"api_key": "MOCK", "column_actions": actions})
    assert response.status_code == 200

    job = _poll_until(client, session_id, {"done", "error"})
    assert job["status"] == "done", job.get("error")
    assert "Monthly_Fee" in job["result"]["stats"]["dropped_columns"]
    reset_job(session_id)


def test_charts_endpoint_regenerates_visualisations(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK"})
    _poll_until(client, session_id, {"done", "error"})

    response = client.post(f'/api/sessions/{session_id}/charts',
                           json={"api_key": "MOCK", "instruction": "distribution of Age"})
    assert response.status_code == 200
    assert len(response.get_json()["charts"]) >= 1

    explicit = client.post(f'/api/sessions/{session_id}/charts', json={
        "specs": [{"chart_type": "histogram", "title": "Age spread",
                   "x_axis": "Age", "y_axis": None, "description": "manual"}]})
    charts = explicit.get_json()["charts"]
    assert explicit.get_json()["source"] == "manual"
    assert charts[0]["title"] == "Age spread"
    reset_job(session_id)


# ---------------------------------------------------------------------------
# Cleaning primitives
# ---------------------------------------------------------------------------

def test_apply_actions_drops_transforms_and_imputes():
    from services.data_service import apply_actions

    frame = _dirty_frame()
    cleaned, stats = apply_actions(frame, {
        "User_ID": {"action": "drop", "reason": "", "transformation": None},
        "Age": {"action": "transform", "reason": "",
                "transformation": "Impute missing values using the column median"},
        "Signup_Date": {"action": "transform", "reason": "",
                        "transformation": "Convert to datetime object"},
        "Gender": {"action": "keep", "reason": "", "transformation": None},
        "Monthly_Fee": {"action": "keep", "reason": "", "transformation": None},
    })

    assert "User_ID" not in cleaned.columns
    assert stats["dropped_columns"] == ["User_ID"]
    assert cleaned["Age"].isnull().sum() == 0
    assert cleaned["Gender"].isnull().sum() == 0
    assert pd.api.types.is_datetime64_any_dtype(cleaned["Signup_Date"])
    # An imputation instruction mentioning "category" must not label-encode.
    assert not pd.api.types.is_numeric_dtype(cleaned["Gender"])


def test_apply_actions_label_encodes_only_on_explicit_request():
    from services.data_service import apply_actions

    cleaned, _ = apply_actions(_dirty_frame(), {
        "Gender": {"action": "transform", "reason": "",
                   "transformation": "Label encode the categories"},
    })
    assert pd.api.types.is_numeric_dtype(cleaned["Gender"])


def test_apply_actions_ignores_unknown_columns():
    from services.data_service import apply_actions
    cleaned, stats = apply_actions(_dirty_frame(), {
        "Ghost_Column": {"action": "drop", "reason": "", "transformation": None}})
    assert stats["dropped_columns"] == []
    assert len(cleaned.columns) == 10


def test_chart_planner_produces_valid_specs():
    from services.chart_service import generate_auto_charts, build_chart_payload

    frame = _dirty_frame().drop(columns=["Empty_Col"])
    specs = generate_auto_charts(frame, "Predict Churned from Age")
    assert specs
    assert all(spec["chart_type"] in
               ("histogram", "bar", "pie", "line", "scatter", "box", "correlation")
               for spec in specs)

    payload = build_chart_payload(frame, specs)
    assert payload
    for chart in payload:
        assert chart.get("labels") or chart.get("points")


def test_chart_validator_rejects_unknown_columns():
    from services.chart_service import validate_chart_specs
    frame = _dirty_frame()
    specs = validate_chart_specs([
        {"chart_type": "histogram", "x_axis": "Nope", "title": "bad"},
        {"chart_type": "banana", "x_axis": "Age", "title": "bad type"},
        {"chart_type": "scatter", "x_axis": "Age", "y_axis": "Gender", "title": "non-numeric y"},
        {"chart_type": "histogram", "x_axis": "Age", "title": "good"},
    ], frame)
    assert len(specs) == 1
    assert specs[0]["title"] == "good"


def test_target_detection_prefers_the_predicted_column():
    from services.chart_service import guess_target_column
    frame = _dirty_frame()
    assert guess_target_column(frame, "Predict Churned from Age and Monthly_Fee") == "Churned"


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def test_chat_applies_schema_updates(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK", "wait": True, "chain_process": False})

    response = client.post(f'/api/sessions/{session_id}/chat',
                           json={"message": "Please drop Monthly_Fee", "api_key": "MOCK"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["schema_updates"]["Monthly_Fee"]["action"] == "drop"
    assert data["column_actions"]["Monthly_Fee"]["action"] == "drop"
    reset_job(session_id)


def test_chat_stream_emits_all_event_types(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK"})
    _poll_until(client, session_id, {"done", "error"})

    response = client.post(f'/api/sessions/{session_id}/chat/stream',
                           json={"message": "Please keep Gender", "api_key": "MOCK"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["Content-Type"]

    body = response.get_data(as_text=True)
    assert "event: schema_updates" in body
    assert "event: done" in body
    reset_job(session_id)


def test_chat_stream_can_build_charts_on_request(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK"})
    _poll_until(client, session_id, {"done", "error"})

    response = client.post(f'/api/sessions/{session_id}/chat/stream',
                           json={"message": "show me a chart of Monthly_Fee", "api_key": "MOCK"})
    body = response.get_data(as_text=True)
    assert "event: charts" in body
    reset_job(session_id)


def test_chat_requires_a_message(client):
    session_id = _upload(client)["session_id"]
    assert client.post(f'/api/sessions/{session_id}/chat', json={}).status_code == 400
    reset_job(session_id)


# ---------------------------------------------------------------------------
# Reporting, downloads and session lifecycle
# ---------------------------------------------------------------------------

def test_pdf_report_embeds_generated_figures(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK"})
    _poll_until(client, session_id, {"done", "error"})

    response = client.post(f'/api/sessions/{session_id}/pdf', json={"api_key": "MOCK"})
    assert response.status_code == 200
    assert response.get_json()["charts_included"] >= 1

    download = client.get(f'/api/sessions/{session_id}/download_pdf')
    assert download.status_code == 200
    assert download.get_data()[:4] == b'%PDF'
    reset_job(session_id)


def test_pdf_requires_a_cleaned_dataset(client):
    session_id = _upload(client)["session_id"]
    response = client.post(f'/api/sessions/{session_id}/pdf', json={"api_key": "MOCK"})
    assert response.status_code == 400
    reset_job(session_id)


def test_session_lifecycle(client):
    upload = _upload(client, filename="lifecycle.csv")
    session_id = upload["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    listing = client.get('/api/sessions').get_json()
    assert any(item["session_id"] == session_id for item in listing)

    detail = client.get(f'/api/sessions/{session_id}').get_json()
    assert detail["original_filename"] == "lifecycle.csv"
    assert detail["row_count"] == 40
    assert detail["job"]["status"] == "profile_ready"

    assert client.delete(f'/api/sessions/{session_id}').status_code == 200
    assert client.get(f'/api/sessions/{session_id}').status_code == 404


def test_upload_rejects_unsupported_extension(client):
    buffer = io.BytesIO(b"not a spreadsheet")
    response = client.post('/api/upload', data={'file': (buffer, 'notes.txt')},
                           content_type='multipart/form-data')
    assert response.status_code == 400


def test_upload_requires_a_file(client):
    assert client.post('/api/upload', data={}, content_type='multipart/form-data').status_code == 400


def test_status_of_unknown_session_is_idle(client):
    assert client.get('/api/sessions/unknown-id/status').get_json()["status"] == "idle"


def test_oversized_upload_returns_json_not_html(client):
    """The API contract says every failure is JSON, including the 413."""
    original = app.config['MAX_CONTENT_LENGTH']
    app.config['MAX_CONTENT_LENGTH'] = 512
    try:
        payload = io.BytesIO(b"col\n" + b"x\n" * 4096)
        response = client.post('/api/upload', data={'file': (payload, 'big.csv')},
                               content_type='multipart/form-data')
        assert response.status_code == 413
        assert "error" in response.get_json()
    finally:
        app.config['MAX_CONTENT_LENGTH'] = original


# ---------------------------------------------------------------------------
# Model-output parsing
#
# Only OpenAI-compatible providers honour response_format reliably, so replies
# arrive fenced, prefixed with prose, or trailed by commentary. Being strict
# would force the offline fallback on every non-OpenAI provider.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('```\n{"a": 1}\n```', {"a": 1}),
    ('Here is the JSON you asked for:\n{"a": 1}', {"a": 1}),
    ('{"a": 1}\n\nLet me know if you need changes!', {"a": 1}),
    ('Sure!\n```json\n{"a": 1}\n```\nHope that helps.', {"a": 1}),
    ('{"reason": "drop {this} column"}', {"reason": "drop {this} column"}),
    ('{"reason": "he said \\"no\\""}', {"reason": 'he said "no"'}),
    ('{"nested": {"deep": {"x": 2}}}', {"nested": {"deep": {"x": 2}}}),
])
def test_parse_json_response_recovers_from_provider_formatting(raw, expected):
    from utils.helpers import parse_json_response
    assert parse_json_response(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "no json at all here", "{unbalanced: "])
def test_parse_json_response_raises_on_unrecoverable_text(raw):
    from utils.helpers import parse_json_response
    with pytest.raises(ValueError):
        parse_json_response(raw)


# ---------------------------------------------------------------------------
# Deployment readiness
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_ready_endpoint_reports_storage_and_llm(client):
    response = client.get('/api/ready')
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ready"
    assert all(data["storage"].values())
    assert "provider" in data["llm"] and "has_key" in data["llm"]
    assert data["auth_required"] is False


def test_security_headers_are_set(client):
    headers = client.get('/api/health').headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "Referrer-Policy" in headers


def test_api_token_guard(client, monkeypatch):
    """When MERCURY_API_TOKEN is set, /api/* needs it - but probes stay open."""
    import config
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-token")

    assert client.get('/api/sessions').status_code == 401
    assert "error" in client.get('/api/sessions').get_json()

    # Health/readiness probes must not need credentials.
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/ready').get_json()["auth_required"] is True

    assert client.get('/api/sessions', headers={"X-API-Key": "s3cret-token"}).status_code == 200
    assert client.get('/api/sessions',
                      headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    # Query-param form, for <a download> links that cannot set headers.
    assert client.get('/api/sessions?token=s3cret-token').status_code == 200
    assert client.get('/api/sessions', headers={"X-API-Key": "wrong"}).status_code == 401


def test_job_state_survives_process_memory_loss(client):
    """The disk mirror is what lets a poll on another worker see the truth."""
    from utils import job_tracker

    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    # Simulate a fresh process: memory empty, disk intact.
    with job_tracker._bg_jobs_lock:
        job_tracker._background_jobs.clear()

    recovered = client.get(f'/api/sessions/{session_id}/status').get_json()
    assert recovered["status"] == "profile_ready"
    assert recovered["progress"] == 100
    reset_job(session_id)


def test_job_files_are_not_listed_as_sessions(client):
    """`<id>.job.json` lives beside session records and must be filtered out."""
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    job_file = os.path.join(app.config['SESSION_FOLDER'], f"{session_id}.job.json")
    assert os.path.exists(job_file), "job state should be mirrored to disk"

    listing = client.get('/api/sessions').get_json()
    assert len(listing) == 1
    assert all(item["session_id"] for item in listing)
    reset_job(session_id)


def test_delete_removes_every_artifact(client):
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})
    client.post('/api/analyze', json={"session_id": session_id, "goal": "predict churn",
                                      "api_key": "MOCK"})
    _poll_until(client, session_id, {"done", "error"})
    client.post(f'/api/sessions/{session_id}/pdf', json={"api_key": "MOCK"})

    session = _session(session_id)
    upload = os.path.join(app.config['UPLOAD_FOLDER'], session["file_id"])
    cleaned = os.path.join(app.config['OUTPUT_FOLDER'], session["cleaned_filename"])
    pdf = os.path.join(app.config['OUTPUT_FOLDER'], session["pdf_filename"])
    job_file = os.path.join(app.config['SESSION_FOLDER'], f"{session_id}.job.json")
    assert all(os.path.exists(p) for p in (upload, cleaned, pdf, job_file))

    assert client.delete(f'/api/sessions/{session_id}').status_code == 200
    assert not any(os.path.exists(p) for p in (upload, cleaned, pdf, job_file))


def test_retention_sweep_removes_old_sessions_and_their_files(client):
    """Without this, uploads and reports accumulate on disk forever."""
    import datetime as dt
    from utils.session_manager import purge_old_sessions, save_session

    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    with app.app_context():
        session = load_session(session_id)
        session["created_at"] = (dt.datetime.now() - dt.timedelta(days=30)).isoformat()
        save_session(session)

    upload = os.path.join(app.config['UPLOAD_FOLDER'], session["file_id"])
    assert os.path.exists(upload)

    removed = purge_old_sessions(
        app.config['SESSION_FOLDER'], app.config['UPLOAD_FOLDER'],
        app.config['OUTPUT_FOLDER'], retention_days=7)

    assert removed == 1
    assert not os.path.exists(upload)
    assert client.get(f'/api/sessions/{session_id}').status_code == 404


def test_retention_sweep_is_a_no_op_when_disabled(client):
    from utils.session_manager import purge_old_sessions
    session_id = _upload(client)["session_id"]
    _poll_until(client, session_id, {"profile_ready"})

    assert purge_old_sessions(app.config['SESSION_FOLDER'], app.config['UPLOAD_FOLDER'],
                              app.config['OUTPUT_FOLDER'], retention_days=0, max_sessions=0) == 0
    assert client.get(f'/api/sessions/{session_id}').status_code == 200
    reset_job(session_id)


def test_max_sessions_trims_to_the_newest(client):
    from utils.session_manager import purge_old_sessions

    ids = [_upload(client, filename=f"s{i}.csv")["session_id"] for i in range(3)]
    for session_id in ids:
        _poll_until(client, session_id, {"profile_ready"})

    purge_old_sessions(app.config['SESSION_FOLDER'], app.config['UPLOAD_FOLDER'],
                       app.config['OUTPUT_FOLDER'], max_sessions=1)
    assert len(client.get('/api/sessions').get_json()) == 1


def test_production_config_rejects_missing_secret_key(monkeypatch):
    """A production boot without SECRET_KEY must fail fast, not run insecurely."""
    import config
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "SECRET_KEY", None)
    problems = config.validate()
    assert any("SECRET_KEY" in problem for problem in problems)


def test_production_config_rejects_debug_mode(monkeypatch):
    import config
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 32)
    monkeypatch.setenv("FLASK_DEBUG", "1")
    problems = config.validate()
    assert any("FLASK_DEBUG" in problem for problem in problems)


def test_development_config_is_valid_by_default():
    import config
    assert config.validate() == []


def test_wsgi_entrypoint_builds_an_app():
    """Deployment targets import wsgi:application - it must construct cleanly."""
    import wsgi
    assert wsgi.application is not None
    assert wsgi.app is wsgi.application
