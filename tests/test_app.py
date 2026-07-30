import os
import json
import io
import pytest
import pandas as pd
from app import app
from utils.session_manager import load_session

@pytest.fixture
def client():
    app.config['TESTING'] = True
    # Use temporary folders for testing to avoid polluting real folders
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'test_uploads')
    app.config['OUTPUT_FOLDER'] = os.path.join(os.getcwd(), 'test_output_data')
    app.config['SESSION_FOLDER'] = os.path.join(os.getcwd(), 'test_sessions')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
    os.makedirs(app.config['SESSION_FOLDER'], exist_ok=True)

    # Patch config variables
    import config
    orig_upload = config.UPLOAD_FOLDER
    orig_output = config.OUTPUT_FOLDER
    orig_session = config.SESSION_FOLDER

    config.UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
    config.OUTPUT_FOLDER = app.config['OUTPUT_FOLDER']
    config.SESSION_FOLDER = app.config['SESSION_FOLDER']

    with app.test_client() as client:
        yield client

    # Clean up test directories
    import shutil
    shutil.rmtree(app.config['UPLOAD_FOLDER'], ignore_errors=True)
    shutil.rmtree(app.config['OUTPUT_FOLDER'], ignore_errors=True)
    shutil.rmtree(app.config['SESSION_FOLDER'], ignore_errors=True)

    config.UPLOAD_FOLDER = orig_upload
    config.OUTPUT_FOLDER = orig_output
    config.SESSION_FOLDER = orig_session

def test_index_route(client):
    """Test index route loads or can serve static file."""
    response = client.get('/')
    # If static index.html doesn't exist, we might get a 404, but let's make sure it doesn't crash
    assert response.status_code in [200, 404]

def test_list_sessions_empty(client):
    """Test session list is initially empty."""
    response = client.get('/api/sessions')
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)

def test_upload_and_flow(client):
    """Upload a mock CSV, analyze schema, and trigger processing."""
    # 1. Create a dummy CSV file
    df = pd.DataFrame({
        "User_ID": [1, 2, 3],
        "Age": [25, 34, None],
        "Gender": ["Male", "Female", "Male"],
        "Registration_Date": ["2021-01-01", "2021-02-01", "2021-03-01"],
        "Subscription_Fee": [50.0, 60.0, 70.0],
        "Churned": [0, 1, 0]
    })

    csv_buffer = io.BytesIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    # 2. Upload the file
    upload_response = client.post(
        '/api/upload',
        data={'file': (csv_buffer, 'mock_dataset.csv')},
        content_type='multipart/form-data'
    )
    assert upload_response.status_code == 200
    upload_data = upload_response.get_json()
    assert "session_id" in upload_data
    session_id = upload_data["session_id"]

    # 3. List sessions and check if our session is listed
    sessions_response = client.get('/api/sessions')
    assert sessions_response.status_code == 200
    sessions = sessions_response.get_json()
    assert any(s["session_id"] == session_id for s in sessions)

    # 4. Get specific session detail
    detail_response = client.get(f'/api/sessions/{session_id}')
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    assert detail["original_filename"] == "mock_dataset.csv"
    assert detail["row_count"] == 3
    assert detail["col_count"] == 6

    # 5. Analyze schema (using MOCK API key)
    analyze_payload = {
        "session_id": session_id,
        "goal": "Predict churn based on subscription fee and age",
        "api_key": "MOCK"
    }
    analyze_response = client.post(
        '/api/analyze',
        json=analyze_payload
    )
    assert analyze_response.status_code == 200
    analyze_data = analyze_response.get_json()
    assert "recommendations" in analyze_data
    assert len(analyze_data["recommendations"]) > 0

    # 6. Chat with the assistant (using MOCK)
    chat_payload = {
        "message": "Please drop User_ID",
        "api_key": "MOCK"
    }
    chat_response = client.post(
        f'/api/sessions/{session_id}/chat',
        json=chat_payload
    )
    assert chat_response.status_code == 200
    chat_data = chat_response.get_json()
    assert "schema_updates" in chat_data
    assert "User_ID" in chat_data["schema_updates"]
    assert chat_data["schema_updates"]["User_ID"]["action"] == "drop"

    # 7. Process dataset manually (synchronous)
    process_payload = {
        "session_id": session_id,
        "actions": chat_data["column_actions"]
    }
    process_response = client.post(
        '/api/process',
        json=process_payload
    )
    assert process_response.status_code == 200
    process_data = process_response.get_json()
    assert process_data["success"] is True
    assert "download_url" in process_data
    assert "stats" in process_data
    assert process_data["stats"]["final_cols"] < process_data["stats"]["initial_cols"] # User_ID was dropped

    # 8. Trigger background process and poll status
    trigger_response = client.post(
        f'/api/sessions/{session_id}/trigger_process',
        json={"api_key": "MOCK", "actions": chat_data["column_actions"]}
    )
    assert trigger_response.status_code == 200

    # Poll status until done
    import time
    for _ in range(10):
        status_response = client.get(f'/api/sessions/{session_id}/status')
        assert status_response.status_code == 200
        status_data = status_response.get_json()
        if status_data["status"] == "done":
            break
        time.sleep(0.5)
    else:
        pytest.fail("Background job did not finish in time")

    # Check background result is correct
    assert status_data["status"] == "done"
    assert "result" in status_data
    assert status_data["result"]["stats"]["final_cols"] < status_data["result"]["stats"]["initial_cols"]

    # 9. Test file downloading
    download_url = process_data["download_url"]
    download_response = client.get(download_url)
    assert download_response.status_code == 200

    # 10. Streaming Chat endpoint (MOCK)
    stream_response = client.post(
        f'/api/sessions/{session_id}/chat/stream',
        json={"message": "Please keep Registration_Date", "api_key": "MOCK"}
    )
    assert stream_response.status_code == 200
    assert "text/event-stream" in stream_response.headers["Content-Type"]

    # Verify we can read events
    data_content = stream_response.get_data(as_text=True)
    assert "event: schema_updates" in data_content
    assert "event: done" in data_content

    # 11. Delete session
    delete_response = client.delete(f'/api/sessions/{session_id}')
    assert delete_response.status_code == 200

    # Confirm it is deleted
    get_del_response = client.get(f'/api/sessions/{session_id}')
    assert get_del_response.status_code == 404


def test_unified_llm_client_routing():
    """Test the configuration and routing resolution logic of UnifiedLLMClient."""
    from services.ai_service import UnifiedLLMClient

    # Test automatic detection from model name
    client1 = UnifiedLLMClient()

    # OpenAI auto-routing
    prov, name, key, url = client1.resolve_config("gpt-4o")
    assert prov == "openai"
    assert name == "openai/gpt-4o"

    # Anthropic auto-routing
    prov, name, key, url = client1.resolve_config("claude-3-7-sonnet")
    assert prov == "anthropic"
    assert name == "anthropic/claude-3-7-sonnet"

    # Gemini auto-routing
    prov, name, key, url = client1.resolve_config("gemini-2.5-flash")
    assert prov == "gemini"
    assert name == "gemini/gemini-2.5-flash"

    # OpenRouter auto-routing
    prov, name, key, url = client1.resolve_config("openrouter/meta/llama3")
    assert prov == "openrouter"
    assert name == "openrouter/meta/llama3"

    # Ollama auto-routing
    prov, name, key, url = client1.resolve_config("ollama/llama3")
    assert prov == "ollama"
    assert name == "ollama/llama3"
    assert url == "http://localhost:11434"

    # Explicit client-level provider and model
    client2 = UnifiedLLMClient(provider="anthropic", model="custom-claude-model")
    prov, name, key, url = client2.resolve_config(None)
    assert prov == "anthropic"
    assert name == "anthropic/custom-claude-model"
