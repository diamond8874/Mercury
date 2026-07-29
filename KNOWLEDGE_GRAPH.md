# Knowledge Graph

This file serves as a lightweight structural index of the repository to minimize token consumption during context loading. Agents MUST consult this file before reading raw application source files.

## Module & Dependency Map

| File/Module | Type | Description | Dependencies |
|-------------|------|-------------|--------------|
| `app.py` | Flask Backend | Main entry point for the REST API and core backend logic. | `flask`, `pandas`, `numpy`, `openai`, `reportlab`, `threading`, `json` |
| `generate_test_data.py` | Script | Generates a synthetic dataset for testing data cleaning capabilities. | `pandas`, `numpy`, `random` |
| `static/app.js` | Frontend JS | Contains all client-side logic, API calls, and DOM manipulation. | None |
| `static/index.html` | Frontend UI | Main HTML layout and UI components. | `static/style.css`, `static/app.js` |

## Interface Summaries (`app.py`)

### Helper Functions
- `def _set_job_state(session_id, status, result=None, error=None, progress=0, progress_msg="")`: Sets thread-safe background job status.
- `def _update_job_progress(session_id, progress, progress_msg)`: Updates the progress of a background job.
- `def _get_job_state(session_id)`: Retrieves the current state of a background job.
- `def allowed_file(filename)`: Checks if the uploaded file type is supported (`xlsx`, `xls`, `csv`).
- `def get_openai_client(request_key=None)`: Returns configured OpenAI client using the Nvidia endpoint.
- `def parse_json_response(text)`: Cleans and parses markdown-formatted JSON responses.
- `def summarize_schema(df, max_samples=1)`: Creates a compact summary of a pandas DataFrame schema.
- `def load_session(session_id)`: Loads session state from a local JSON file.
- `def save_session(session_data)`: Saves session state to a local JSON file.
- `def download_lora_fonts()`: Downloads and registers Lora fonts for ReportLab.
- `def generate_mock_recommendations(df, goal)`: Fallback AI mock logic for testing purposes.
- `def generate_mock_charts(df)`: Generates simple distribution charts.

### API Routes & Endpoints
- `@app.route('/')`: Serves `index.html`.
- `@app.route('/api/sessions', methods=['GET'])`: Lists all available processing sessions.
- `@app.route('/api/sessions/<session_id>', methods=['GET'])`: Retrieves details for a specific session.
- `@app.route('/api/sessions/<session_id>', methods=['DELETE'])`: Deletes a session and its associated files.
- `@app.route('/api/upload', methods=['POST'])`: Handles file uploads.
- `@app.route('/api/analyze', methods=['POST'])`: Triggers schema analysis.
- `@app.route('/api/process', methods=['POST'])`: Starts data processing pipeline.
- `@app.route('/api/sessions/<session_id>/trigger_process', methods=['POST'])`: Triggers background processing.
- `@app.route('/api/sessions/<session_id>/status', methods=['GET'])`: Retrieves the status of the background job.
- `@app.route('/api/sessions/<session_id>/chat', methods=['POST'])`: Standard chat interface with AI.
- `@app.route('/api/sessions/<session_id>/chat/stream', methods=['POST'])`: Streaming chat interface.
- `@app.route('/api/sessions/<session_id>/pdf', methods=['POST'])`: Generates a PDF report.
- `@app.route('/api/sessions/<session_id>/download_pdf', methods=['GET'])`: Endpoint to download the generated PDF.
- `@app.route('/api/download/<filename>')`: Endpoint to download cleaned/processed data files.

### Background Processes
- `def run_background_process(session_id, api_key=None)`: Background worker thread execution function.
