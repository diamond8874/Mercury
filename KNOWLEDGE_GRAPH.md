# Knowledge Graph

This file serves as a lightweight structural index of the repository to minimize token consumption during context loading. Agents MUST consult this file before reading raw application source files.

## Module & Dependency Map

| File/Module | Type | Description | Dependencies |
|-------------|------|-------------|--------------|
| `app.py` | Flask Entrypoint | Lean main entry point for booting and initializing the Flask application. | `flask`, `config`, `components.routes`, `utils.fonts` |
| `config.py` | Configuration | Defines folder paths, extension restrictions, and loads environment variables. | `os`, `dotenv` |
| `components/routes.py` | Blueprint Routes | Contains all REST API endpoints and PDF generation code. | `flask`, `pandas`, `numpy`, `matplotlib`, `reportlab`, `services`, `utils` |
| `services/ai_service.py` | Service | Initializes configured OpenAI/Nvidia spec compatible client. | `openai`, `os` |
| `services/data_service.py` | Service | Core data operations, schema summary, mock suggestions, and background worker threads. | `pandas`, `numpy`, `os`, `logging`, `utils` |
| `utils/helpers.py` | Utility Helper | Functions for filename validation and JSON response parsing. | `json`, `config` |
| `utils/session_manager.py` | Session Utility | Session load/save and custom JSON encoder to serialize pandas/numpy objects. | `json`, `os`, `pandas`, `numpy`, `flask`, `config` |
| `utils/fonts.py` | PDF Font Utility | Core downloader and registrar for PDF report fonts. | `os`, `urllib`, `reportlab` |
| `utils/job_tracker.py` | Job Tracking Utility | Thread-safe tracking and polling of background cleaning jobs. | `threading` |
| `generate_test_data.py` | Script | Generates a synthetic dataset for testing data cleaning capabilities. | `pandas`, `numpy`, `random` |
| `static/app.js` | Frontend JS | Contains all client-side logic, API calls, and DOM manipulation. | None |
| `static/index.html` | Frontend UI | Main HTML layout and UI components. | `static/style.css`, `static/app.js` |

## Interface Summaries

### `config.py`
- `UPLOAD_FOLDER`: Directory path for user uploads.
- `OUTPUT_FOLDER`: Directory path for generated files/PDFs.
- `SESSION_FOLDER`: Directory path for JSON session files.
- `ALLOWED_EXTENSIONS`: Allowed file formats (`xlsx`, `xls`, `csv`).
- `MAX_CONTENT_LENGTH`: Maximum permitted upload file size (16MB).

### `utils/helpers.py`
- `def allowed_file(filename)`: Checks if the uploaded file format is supported.
- `def parse_json_response(text)`: Extracts and parses valid JSON from markdown-formatted text.

### `utils/session_manager.py`
- `class CustomJSONEncoder`: Custom JSON encoder supporting Pandas Timestamps, NumPy types, and NumPy arrays.
- `def load_session(session_id)`: Loads session data from its JSON file.
- `def save_session(session_data)`: Saves session data to its JSON file using the custom encoder.

### `utils/fonts.py`
- `def download_lora_fonts()`: Downloads and registers Lora fonts for ReportLab.

### `utils/job_tracker.py`
- `_background_jobs`: Dictionary tracking current background operations.
- `def _set_job_state(...)`: Safe state initializer.
- `def _update_job_progress(...)`: Thread-safe progress percentage/message updater.
- `def _get_job_state(...)`: Safely fetches job progress/errors.

### `services/ai_service.py`
- `def get_openai_client(request_key=None)`: Configures and returns OpenAI client pointing to Nvidia's integrate endpoint.

### `services/data_service.py`
- `def summarize_schema(df, max_samples=1)`: Summarizes dataframe column data types, nulls, and sample counts.
- `def generate_mock_recommendations(df, goal)`: Fallback deterministic suggestion generator.
- `def generate_mock_charts(df)`: Generates dictionary schemas for test plots.
- `def run_background_process(app, session_id, api_key=None)`: Thread worker implementing data processing, cleaning, and stats preparation.

### `components/routes.py`
- `@api_blueprint.route('/')`: Serves `index.html`.
- `@api_blueprint.route('/api/sessions', methods=['GET'])`: Lists all active session summaries.
- `@api_blueprint.route('/api/sessions/<session_id>', methods=['GET'])`: Detail getter.
- `@api_blueprint.route('/api/sessions/<session_id>', methods=['DELETE'])`: Detail cleaner.
- `@api_blueprint.route('/api/upload', methods=['POST'])`: Multi-part uploader.
- `@api_blueprint.route('/api/analyze', methods=['POST'])`: Triggers schema analysis recommendation flow.
- `@api_blueprint.route('/api/process', methods=['POST'])`: Clean-process trigger.
- `@api_blueprint.route('/api/sessions/<session_id>/trigger_process', methods=['POST'])`: Background clean-processing trigger.
- `@api_blueprint.route('/api/sessions/<session_id>/status', methods=['GET'])`: Job status getter.
- `@api_blueprint.route('/api/sessions/<session_id>/chat', methods=['POST'])`: Conversational analysis chat route.
- `@api_blueprint.route('/api/sessions/<session_id>/chat/stream', methods=['POST'])`: SSE-based conversational analysis streaming route.
- `@api_blueprint.route('/api/sessions/<session_id>/pdf', methods=['POST'])`: Compiles and exports diagnostics ReportLab PDF.
- `@api_blueprint.route('/api/sessions/<session_id>/download_pdf', methods=['GET'])`: Serves PDF document.
- `@api_blueprint.route('/api/download/<filename>')`: Serves processed dataset files.
