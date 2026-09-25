# Knowledge Graph - Mercury Multi-Provider LLM Abstraction

This file serves as a lightweight structural index of the repository to minimize token consumption during context loading. It defines the current architecture, data flow, modules, and environment matrices for the multi-provider LLM system.

---

## 🗺️ Multi-Provider LLM Architecture & Data Flow

Mercury uses a clean, decoupled **Adapter/Factory Pattern** to resolve, configure, and route LLM calls across multiple providers including **OpenAI, Anthropic (Claude), Google (Gemini), Ollama, OpenRouter, and Nvidia**.

```
[ Frontend: Settings UI / Chat / Schema ]
                   │
                   ▼ (HTTP JSON Payload)
   [ Flask routes: routes.py ]
                   │
                   ▼ (get_llm_client)
 [ UnifiedLLMClient: services/ai_service.py ]
                   │
                   ├─► Auto-resolves Provider & Model Name
                   ├─► Maps proper API Keys & Base URLs
                   │
                   ▼ (Completion Interface)
        [ LiteLLM Engine Wrapper ]
                   │
  ┌────────────────┼────────────────┬────────────────┐
  ▼                ▼                ▼                ▼
[OpenAI]      [Anthropic]        [Gemini]        [Ollama/Local]
```

### Key Components:
1. **Frontend Settings Panel (`static/index.html` & `static/app.js`)**: Allows users to select an LLM Provider, select/type an LLM Model, override the API Key, or provide a Custom Base URL. These settings are persisted in `localStorage` and sent with every API request.
2. **REST API Endpoints (`components/routes.py`)**: Endpoints `/api/analyze`, `/api/sessions/<id>/chat`, and `/api/sessions/<id>/chat/stream` parse the frontend's LLM configuration parameters and pass them to the backend client creator.
3. **Unified LLM Client (`services/ai_service.py`)**: Standardizes prompt formatting, system messages, streaming responses, and error handling. It utilizes LiteLLM to communicate with diverse AI providers while exposing an OpenAI-compatible interface (`client.chat.completions.create(...)`).

---

## 📦 Module & Dependency Map

| File/Module | Type | Description | Dependencies |
|-------------|------|-------------|--------------|
| `app.py` | Flask Entrypoint | Lean main entry point booting Flask, registering modular Blueprints via `routes.register_blueprints(app)`, setting security headers and rate limits. | `flask`, `config`, `routes`, `utils` |
| `config.py` | Configuration | Defines folder paths, extension restrictions, and loads environment variables. | `os`, `dotenv` |
| `routes/` | Subpackage | Modular Flask Blueprints (under 300 lines each): `upload.py` (file uploads & quotas), `sessions.py` (CRUD, delete, cell edits, status), `cleaning.py` (analyze, process, dry-run), `chat.py` (SSE streaming & JSON chat), `visualization.py` (AI viz suggestions, custom charts, pinning), `reports.py` (PDF report generation, downloads), `jobs.py` (owner-only job polling), `auth.py` (auth lifecycle & static assets), `__init__.py` (central registration & error handlers). | `flask`, `routes.*`, `services`, `utils`, `repositories` |
| `components/routes.py` | Compatibility Shim | Backwards-compatibility re-export shim referencing `routes`. | `routes` |
| `services/dataset_service.py` | Domain Service | Upload ingest & parsing, safe preview generation, unified cleaning execution, cell value updates, and dry-run validation. | `pandas`, `flask`, `utils.session_manager`, `utils.upload_validator`, `services.cleaning` |
| `services/chat_service.py` | Domain Service | Synchronous chat turn handling, SSE token streaming generator, and offline heuristic parsing fallback. | `services.ai_service`, `utils.session_manager`, `utils.helpers` |
| `services/report_service.py` | Domain Service | High-DPI chart rendering and ReportLab PDF document compilation using Lora typography. | `reportlab`, `matplotlib`, `pandas`, `powerbi_visuals.trend_charts` |
| `services/visualization_service.py` | Domain Service | LLM parameter extraction from natural language prompts, downsampling/pre-aggregation, and visual dispatching. | `services.ai_service`, `powerbi_visuals.*`, `pandas` |
| `services/ai_service.py` | Service | Contains `UnifiedLLMClient` implementing multi-provider LLM routing, auto-resolving, LiteLLM compatibility, and OpenAI base URL routing for Nvidia (`https://integrate.api.nvidia.com/v1`). | `litellm`, `os`, `logging` |
| `.agents/skills/` | Agent Skills | Ponytail lazy senior dev framework (`ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`) enforcing YAGNI, standard library over dependencies, and minimal working code. | None (Markdown agent guidelines) |
| `.agents/mcp/` | MCP Server | Ponytail MCP server exposing `ponytail` prompt and `ponytail_instructions` tool via stdio for host integration. | `@modelcontextprotocol/sdk`, `zod` |
| `services/data_service.py` | Service | Core data operations, `apply_column_transformation` engine delegating to `services.cleaning`, schema summary, mock suggestions, and background worker threads. | `pandas`, `numpy`, `os`, `logging`, `utils`, `services.cleaning` |
| `utils/quota.py` | Utility Helper | Functions for counting active user sessions and calculating total disk storage usage per user. | `os`, `json`, `flask` |
| `services/cleaning/` | Subpackage | Safe, modular AI cleaning engine featuring `schema.py` (typed Pydantic operation models), `engine.py` (canonical cleaning engine for `/api/process` & background worker), `operation_registry.py` (op definitions & word-boundary matching), `intent_parser.py` (NL → structured plan conversion), `validator.py` (pre-execution validation against real DataFrame), `executor.py` (isolated handlers preserving dtypes and NaNs), `audit.py` (structured audit logs). | `pandas`, `numpy`, `re`, `difflib`, `pydantic`, `logging` |
| `utils/helpers.py` | Utility Helper | Functions for filename validation and JSON response parsing. | `json`, `config` |
| `models/` | Subpackage | SQLAlchemy declarative models: `SessionModel`, `ColumnActionModel`, `ChatMessageModel`, `OperationLogModel`, `JobModel`, `User` with SQLite WAL mode and JSON serialization decorators. | `sqlalchemy`, `config` |
| `repositories/job_repository.py` | Repository | Thread-safe, transaction-managed data access layer for background jobs: CRUD, `fail_stuck_and_interrupted_jobs()` startup recovery, and `check_and_fail_timed_out_jobs()` watchdog sweep. | `sqlalchemy`, `models`, `config` |
| `repositories/session_repository.py` | Repository | Thread-safe, transaction-managed data access layer for session persistence, optimistic locking version counters, atomic chat message appending, and cascading deletions. | `sqlalchemy`, `models` |
| `repositories/storage_backend.py` | Storage Layer | Abstract `StorageBackend` and `LocalStorageBackend` maintaining structured dataset storage (`data/<user_id>/<session_id>/`) with size calculation and file lifecycles. | `os`, `shutil`, `config` |
| `scripts/migrate_json_to_db.py` | CLI Script | Idempotent one-off migration script importing legacy JSON session files into SQLite and structured file storage with `--dry-run` inspection support. | `models`, `repositories` |
| `tests/test_phase5b_persistence.py` | Test Suite | Unit & integration tests for Phase 5B: multi-threaded concurrent chat appends, concurrent cell edit + chat persistence, migration idempotency, cascade deletion, and storage backend operations (5 test cases). | `pytest`, `models`, `repositories`, `scripts` |
| `tests/test_phase5c_background_jobs.py` | Test Suite | Unit & integration tests for Phase 5C: 202 async dispatch for analyze, process, and PDF generation, owner-only `/api/jobs/<id>` polling, crash recovery, and watchdog timeout handling (5 test cases). | `pytest`, `models`, `repositories`, `routes` |
| `utils/session_manager.py` | Session Manager | Facade delegating session reads/writes to `SessionRepository` with fast in-memory caching and debug JSON export support. | `json`, `repositories.session_repository`, `models` |
| `powerbi_visuals/trend_charts.py` | Trend Charts Visualizer | Generates line, area, column, and combo charts with thread safety (`PLOT_LOCK`) and high DPI (`dpi=200`) image rendering. | `matplotlib`, `pandas`, `threading` |
| `powerbi_visuals/geo_charts.py` | Geo Charts Visualizer | Generates interactive bubble and choropleth maps with NaN radius safeguards. | `folium`, `pandas` |
| `utils/fonts.py` | PDF Font Utility | Core downloader and registrar for PDF report fonts. | `os`, `urllib`, `reportlab` |
| `utils/job_tracker.py` | Job Tracking Utility | Bounded `ThreadPoolExecutor` worker pool (max 2 workers) with SQLite DB persistence, auto-completion, exception capture, and legacy API bridges. | `threading`, `concurrent.futures`, `repositories.job_repository` |
| `generate_test_data.py` | Script | Generates a synthetic dataset for testing data cleaning capabilities. | `pandas`, `numpy`, `random` |
| `tests/conftest.py` | Test Fixture | Shared pytest fixtures providing isolated temporary directories for test sessions and upload files. | `pytest`, `app`, `config` |
| `tests/test_cleaning_engine.py` | Test Suite | Comprehensive unit tests for intent parsing, validation, execution safety, datatype conversions, and realistic NL prompts (26 test cases). | `pytest`, `pandas`, `numpy`, `services.cleaning` |
| `tests/test_phase1_hygiene.py` | Test Suite | Unit & integration tests for environment variables, UUID session validation, route rejection, and portable PDF report pinning flow. | `pytest`, `pandas`, `uuid` |
| `tests/test_phase3_data_correctness.py` | Test Suite | Unit & integration tests for Phase 3 data correctness: KEEP no-op, replacement dtype/NaN preservation, single cleaning engine, Pydantic schemas, log transform, outlier reporting, and untrusted delimiters (10 test cases). | `pytest`, `pandas`, `numpy`, `services.cleaning` |
| `tests/test_phase4a_safe_defaults.py` | Test Suite | Unit & integration tests for Phase 4A: SECRET_KEY production refusal, security headers (nosniff, DENY, CSP), and 413 JSON error response (5 test cases). | `pytest`, `flask`, `app` |
| `utils/auth.py` | Authentication Utility | SQLite-backed user authentication module managing Argon2/pbkdf2 password hashing, user registration, role flags, session ownership binding, and ownership route guards (`get_owned_session_or_404`). | `sqlite3`, `werkzeug.security`, `flask_login` |
| `utils/url_validator.py` | Security Utility | Validates custom `base_url` values for SSRF protection: enforces HTTPS, resolves IPs, blocks loopback/private/link-local/cloud metadata (`169.254.169.254`), permits NAT64 public mappings and debug localhost Ollama. | `ipaddress`, `socket`, `urllib.parse` |
| `utils/logging_filter.py` | Security Utility | Redacts API keys (OpenAI, Anthropic, Gemini, Nvidia, Groq) and Bearer tokens from all log output using `APIKeyRedactionFilter`. | `logging`, `re` |
| `utils/upload_validator.py` | Security Utility | Validates upload integrity: content sniffing (magic bytes), row/column caps (200k/500), xlsx sheet cap (10), macro (`vbaProject.bin`) & external link rejection, and zip decompression bomb protection. | `pandas`, `zipfile`, `os`, `logging` |
| `utils/cleanup.py` | Maintenance Utility | Session lifecycle manager: `delete_session_files()` file eraser and `start_cleanup_scheduler()` daemon thread executing periodic TTL expiry sweeps (default 24h). | `os`, `json`, `datetime`, `threading`, `logging` |
| `utils/limiter.py` | Rate Limiter Utility | Shared `Flask-Limiter` instance providing per-user / per-IP rate limiting across upload, chat, and PDF generation routes. | `flask_limiter`, `flask_login` |
| `tests/test_phase4b_auth.py` | Test Suite | Unit & integration tests for Phase 4B: user registration, login, session isolation, cross-user 404 enforcement, and migration (14 test cases). | `pytest`, `flask`, `utils.auth` |
| `tests/test_phase4c_llm_safety.py` | Test Suite | Unit & integration tests for Phase 4C: SSRF defenses, URL validation, log redaction filter, prompt size caps, and client safeguards (13 test cases). | `pytest`, `services`, `utils.url_validator`, `utils.logging_filter` |
| `tests/test_phase4d_upload_limits.py` | Test Suite | Unit & integration tests for Phase 4D: upload sniffing, decompression bombs, macro rejection, shape limits, delete cascade, TTL cleanup sweep, and UUID file safety (14 test cases). | `pytest`, `flask`, `utils.upload_validator`, `utils.cleanup` |
| `tests/test_phase4e_comprehensive.py` | Test Suite | Comprehensive end-to-end security & regression suite for Phase 4E: 401 unauth, 404 stealth across all routes, own session listing, traversal rejection, non-UUID 400, SSRF base_url validation, API key log/JSON redaction, 413/400 upload bounds, 429 rate limits, TTL cleanup, and SECRET_KEY boot refusal (11 test cases). | `pytest`, `flask`, `utils` |
| `static/app.js` | Frontend JS | Full auth lifecycle (`initAuth`, `showAuthModal`, `handleAuthSubmit`, `handleLogout`, 401 interception on upload), dynamic settings state, safe DOM generation, cell editing. | None |
| `static/index.html` | Frontend UI | Auth modal (`#auth-modal`) + user badge (`#user-badge`), LLM provider settings panel, data privacy notice. | `static/style.css`, `static/app.js` |
| `static/style.css` | Frontend CSS | Auth modal overlay/form styles, user badge, error message classes for login/register forms. | None |


---

## ⚙️ Environment Matrix

The LLM abstraction dynamically routes API calls. It checks settings sent from the UI setting overrides first, then falls back to environment variables.

| Environment Variable | Provider Target | Usage / Description |
|----------------------|-----------------|---------------------|
| `NVIDIA_API_KEY` | NVIDIA | Default API Key used for Nvidia endpoints (e.g. `meta/llama-3.3-70b-instruct`). |
| `OPENAI_API_KEY` | OpenAI | API Key for authenticating with official OpenAI models (e.g. `gpt-4o`). |
| `ANTHROPIC_API_KEY` | Anthropic | API Key for authenticating with Anthropic Claude models (e.g. `claude-3-7-sonnet`). |
| `GEMINI_API_KEY` | Google Gemini | API key for authenticating with Google Gemini models (e.g. `gemini-2.5-flash`). |
| `OPENROUTER_API_KEY` | OpenRouter | API key for routing requests through OpenRouter. |
| `OLLAMA_BASE_URL` | Ollama (Local) | Custom local base URL (defaults to `http://localhost:11434`). |
| `LLM_PROVIDER` | System Default | Default provider to use if none is selected in the UI (e.g., `nvidia`, `openai`). |
| `LLM_MODEL` | System Default | Default model to use if none is specified (defaults to `meta/llama-3.3-70b-instruct`). |
| `MAX_ROWS` | Upload Limits | Maximum allowed rows in an uploaded file (default: 200,000). |
| `MAX_COLS` | Upload Limits | Maximum allowed columns in an uploaded file (default: 500). |
| `MAX_XLSX_SHEETS` | Upload Limits | Maximum allowed sheets in an Excel workbook (default: 10). |
| `MAX_CONTENT_LENGTH` | Upload Limits | Maximum HTTP upload payload in bytes (default: 200MB / 209715200 bytes). |
| `MAX_UNCOMPRESSED_BYTES` | Upload Limits | Maximum uncompressed size for zipped Excel files / bomb protection (default: 500MB). |
| `MAX_SESSIONS_PER_USER` | Quotas | Maximum active sessions per authenticated user (default: 20). |
| `MAX_STORAGE_BYTES_PER_USER` | Quotas | Maximum disk storage in bytes per user (default: 1GB / 1073741824 bytes). |
| `SESSION_TTL_SECONDS` | Cleanup | Session inactivity time-to-live before automatic deletion (default: 86400s / 24h). |
| `CLEANUP_INTERVAL_SECONDS` | Cleanup | Interval in seconds between background cleanup sweep runs (default: 3600s / 1h). |
| `RATELIMIT_STORAGE_URI` | Rate Limiter | Storage backend URI for Flask-Limiter (default: `memory://`). |
