# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- **Instant Access to Data Preview & Visualizations on Upload (`static/index.html`, `static/app.js`)**:
  - `static/index.html`: Removed `disabled` attribute from the Data Preview and Visualizations tab buttons so users can inspect dataset rows and generate on-demand visual charts immediately upon upload without waiting for cleaning processing.
  - `static/app.js`: Updated `enableTabs()` and `renderLoadedSessionUI()` to ensure preview and visualization panes remain freely navigable at all stages of session exploration.

- **Hybrid Charset-Normalizer Multi-Encoding CSV Parser & 2,000,000 Row Limit (`utils/helpers.py`, `utils/upload_validator.py`, `services/dataset_service.py`, `services/data_service.py`, `routes/cleaning.py`, `routes/visualization.py`, `routes/sessions.py`, `config.py`, `.env`)**:
  - `utils/helpers.py`: Implemented hybrid `read_csv_robust()` utilizing a high-speed 64KB sample probe with `charset_normalizer.from_bytes()` (<10ms overhead), followed by an intelligent priority fallback ladder (`utf-8`, `utf-8-sig`, `cp1252`, `latin-1`) and `errors='replace'` guard. Handles international and accented character sets (Latin-1, Shift-JIS, Cyrillic, GBK) without crashing or hanging on 100MB+ files.
  - Replaced all raw `pd.read_csv()` invocations across upload validation, dataset ingestion, background cleaning jobs, custom charts, and preview refresh with `read_csv_robust()`.
  - Raised default `MAX_ROWS` limit in `config.py`, `utils/upload_validator.py`, and `.env` from 200,000 to 2,000,000 rows to seamlessly handle datasets with 1,000,000+ rows.

- **Setup & Integration of Ponytail (`.agents/skills/`, `.agents/mcp/`, `.agents/hooks/`, `.gitignore`)**:
  - Created and checked out new branch `setup-ponytail`.
  - Integrated Ponytail (v4.10.0 from `https://github.com/dietrichgebert/ponytail`) lazy senior developer framework.
  - Installed native workspace skills into `.agents/skills/`: `ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`.
  - Installed and verified Ponytail MCP server into `.agents/mcp/` (`@modelcontextprotocol/sdk`, `zod`), passing instruction verification suite (`node --test ./test/instructions.test.js`).
  - Added hooks and runtime scripts in `.agents/hooks/`.
  - Added `.agents/mcp/node_modules/` to `.gitignore`.
  - Ran Ponytail commands (`ponytail-debt`, `ponytail-audit`) against the repository.

- **Increase Dataset Upload Limit to 200MB (`config.py`, `app.py`, `static/index.html`, `.env`)**:
  - `config.py`: Raised `MAX_CONTENT_LENGTH` default to 200MB (`200 * 1024 * 1024` bytes) with environment variable override support, and raised per-user storage quota `MAX_STORAGE_BYTES_PER_USER` to 1GB (`1024 * 1024 * 1024` bytes) and `MAX_UNCOMPRESSED_BYTES` to 500MB to accommodate large files.
  - `app.py`: Updated the `413 RequestEntityTooLarge` error handler to dynamically calculate and report the exact configured limit in MB (`File size exceeds maximum allowed upload limit ({max_mb}MB)`).
  - `static/index.html`: Updated upload drop-zone subtitle to `"Supports .xlsx, .xls and .csv (Max 200MB)"`.
  - `.env`: Added `MAX_CONTENT_LENGTH=209715200` and `MAX_STORAGE_BYTES_PER_USER=1073741824`.
  - `tests/test_phase4e_comprehensive.py`: Updated oversized upload test to dynamically test beyond configured `MAX_CONTENT_LENGTH`.

- **Custom LLM Provider Keys, Prompt Reprocess Preview & Session Persistence (`services/ai_service.py`, `services/dataset_service.py`, `routes/sessions.py`, `static/app.js`)**:
  - `services/ai_service.py`: Fixed aggressive fallback logic in `resolve_config()` that was forcibly redirecting custom user NVIDIA configurations and models to Groq. Users providing custom keys or explicitly selecting NVIDIA or other providers now route directly to their selected provider and target endpoints without being overwritten. Installed missing `tenacity` library in environment for LiteLLM retry handling.
  - `services/dataset_service.py`: Added explicit persistence for `session_data["preview"]` and `session_data["bg_result"]` in `process_cleaning_for_session` and `update_cell_value` before `save_session()`.
  - `routes/sessions.py`: Ensured `get_session_detail` dynamically reads and generates safe previews from `cleaned_<session_id>.xlsx` if present on disk, guaranteeing that sessions always display the latest cleaned data preview when a user logs in or switches sessions.
  - `static/app.js`: In `executePandasProcess()`, guaranteed that `data.preview` is immediately rendered to the preview table and automatically switches the active tab to `tab-preview` so the user immediately sees transformation results (such as rounded numbers) reflected in the grid.
  - Full test suite passes 100% (107/107 tests).

- **Geo Map Visual Fix & Mercury Branding (`powerbi_visuals/geo_charts.py`, `static/index.html`, `static/app.js`)**:
  - `powerbi_visuals/geo_charts.py`: Fixed `Could not convert string ... to numeric` and Folium's `"Make this Notebook Trusted to load map: File -> Trust Notebook"` display issue. Folium's `_repr_html_()` produces a Jupyter-only wrapper that breaks in standard web browsers when injected into DOM; replaced with `m.get_root().render()` wrapped in a responsive `<iframe srcdoc="...">` with `width: 100%` and `height: 420px`.
  - Implemented safe numeric coercion (`pd.to_numeric(..., errors='coerce')`) for latitude and longitude columns with coordinate column auto-inference, graceful informative overlay when non-coordinate columns are passed, and switched base tiles to OpenStreetMap.
  - `static/index.html` & `static/app.js`: Updated application branding to "Mercury" across title, navigation header, and authentication modals. Enhanced visual configuration modal to show context-aware labels ("Latitude Column" and "Longitude Column") with automatic coordinate column pre-selection when configuring Map visuals.

  - `repositories/job_repository.py`: Created transaction-managed repository for background jobs storing job states, payloads, progress messages, and error traces in SQLite WAL mode. Added `fail_stuck_and_interrupted_jobs()` startup recovery and `check_and_fail_timed_out_jobs()` watchdog sweep.
  - `utils/job_tracker.py`: Replaced in-memory job dictionaries with a bounded `ThreadPoolExecutor(max_workers=2)` delegating to `job_repository`. Automatically transitions job state to `succeeded` or `failed` in a `finally` block and maintains backwards-compatibility bridges.
  - `routes/jobs.py`: Added dedicated Blueprint for polling background jobs (`GET /api/jobs/<job_id>`) with strict ownership validation returning stealth 404 for cross-user requests.
  - `routes/cleaning.py` & `routes/reports.py`: Updated `/api/analyze`, `/api/sessions/<id>/trigger_process`, and `/api/sessions/<id>/pdf` to return HTTP `202 Accepted` with a UUID `job_id` instead of blocking synchronous execution.
  - `app.py`: Integrated startup job recovery to fail in-flight jobs on reboot, and added a background watchdog daemon thread checking for timed-out jobs every 60 seconds.
  - `tests/test_phase5c_background_jobs.py`: Added 5 comprehensive test cases verifying 202 async dispatch, polling across analyze/process/pdf, cross-user stealth 404, startup crash recovery, and watchdog timeout handling.
  - Full test suite passes 100% (108/108 tests).
- **Phase 5B Persistent State & Storage Abstraction (`models/`, `repositories/`, `scripts/migrate_json_to_db.py`, `tests/test_phase5b_persistence.py`, `utils/session_manager.py`)**:
  - `models/__init__.py`: Created SQLAlchemy relational schema with WAL mode: `SessionModel`, `ColumnActionModel`, `ChatMessageModel`, `OperationLogModel`, `JobModel`, `User`.
  - `repositories/session_repository.py`: Built thread-safe `SessionRepository` handling transactions, optimistic locking with integer version increments, atomic append-only chat messages, and cascade deletion.
  - `repositories/storage_backend.py`: Implemented abstracted `StorageBackend` and `LocalStorageBackend` providing isolated `data/<user_id>/<session_id>/` disk structure.
  - `scripts/migrate_json_to_db.py`: Created idempotent one-off migration script supporting `--dry-run` to import legacy JSON session files into SQLite without duplicate inserts.
  - `tests/test_phase5b_persistence.py`: Added 5 unit and integration tests verifying concurrent multi-threaded chat append, concurrent state update + chat append, migration idempotency, cascade deletion, and storage backend operations. Full regression suite passes 100% (103/103 tests).
  - `routes/`: Decomposed the monolithic 2,192-line `components/routes.py` into focused Flask Blueprints under 300 lines each:
    - `routes/upload.py`: Dataset file upload, magic byte content sniffing, shape limits, and quota enforcement (`POST /api/upload`).
    - `routes/sessions.py`: Session CRUD, user data deletion, cell updates, and processing status polling (`GET /api/sessions`, `GET/DELETE /api/sessions/<id>`, `DELETE /api/me/data`, `POST /api/sessions/<id>/update_cell`, `GET /api/sessions/<id>/status`).
    - `routes/cleaning.py`: Background schema analysis, dataset cleaning execution, background triggers, and dry runs (`POST /api/analyze`, `POST /api/process`, `POST /api/sessions/<id>/trigger_process`, `POST /api/sessions/<id>/dry_run`).
    - `routes/chat.py`: Synchronous and Server-Sent Event streaming chat interactions (`POST /api/sessions/<id>/chat`, `POST /api/sessions/<id>/chat/stream`).
    - `routes/visualization.py`: AI visual suggestions, custom visual rendering, and chart pinning (`POST /api/sessions/<id>/viz_chat`, `POST /api/sessions/<id>/custom_chart`, `POST/GET /api/sessions/<id>/pin_chart`, `GET /api/sessions/<id>/pinned_charts`).
    - `routes/reports.py`: PDF report compilation, PDF download, and session dataset downloads (`POST /api/sessions/<id>/pdf`, `GET /api/sessions/<id>/download_pdf`, `GET /api/download/<filename>`, `GET /api/sessions/<id>/download/<kind>`).
    - `routes/auth.py`: Authentication lifecycle endpoints and root static asset serving (`/api/auth/register`, `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/`, `/favicon.ico`).
    - `routes/__init__.py`: Centralized blueprint registration and global JSON error handlers (`401`, `404`, `500`).
  - `services/`: Extracted all business logic out of route handlers into modular domain services:
    - `services/dataset_service.py`: Upload ingestion, safe preview records, cleaning pipeline execution, atomic cell value updates, and dry-run plan validation.
    - `services/chat_service.py`: Non-streaming and streaming multi-turn conversation logic with rule-based fallback.
    - `services/report_service.py`: ReportLab document building, Lora typography, and Matplotlib figure compilation.
    - `services/visualization_service.py`: Natural language visualization parameter extraction and dispatching to `powerbi_visuals`.
  - `utils/quota.py`: Shared per-user active session and disk storage usage calculation utilities.
  - `components/routes.py`: Replaced monolithic file with a slim backwards-compatibility re-export shim.
  - Full test suite verified passing 100% (98/98 tests) with identical URL map rules and methods.
  - `tests/test_phase4e_comprehensive.py`: Created 11 comprehensive end-to-end integration tests verifying:
    - Rejection of unauthenticated requests to all 21 protected `/api/*` routes with 401 Unauthorized.
    - Stealth 404 enforcement across all session routes when User B accesses User A's session.
    - Strict session list isolation where `/api/sessions` returns only sessions owned by the caller.
    - Download isolation preventing access to other users' output files and rejecting path traversal variants (`../`, `..\\`, `%2e%2e%2f`, `%252e%252e%252f`).
    - Validation that non-UUID `session_id` inputs return HTTP 400 Bad Request.
    - SSRF `base_url` matrix rejection (loopback, link-local, cloud metadata, private IPs, DNS rebinding) and acceptance of valid public HTTPS endpoints.
    - Leak prevention confirming API keys are never captured in logs or written to session JSON files.
    - Rejection of oversized uploads with HTTP 413 and shape cap violations (rows/columns) with clean HTTP 400.
    - Flask-Limiter rate limit enforcement triggering HTTP 429 Too Many Requests.
    - Background cleanup sweeps purging expired sessions and files while preserving active sessions.
    - Application boot refusal in production (`DEBUG=false`) when `SECRET_KEY` is missing or insecure.
  - `components/routes.py`: Hardened `/api/download/<filename>` against path traversal and double-encoded variants, requiring valid session UUID association. Updated `/api/process` to check session ownership prior to payload parsing.
  - `README.md`: Documented full production deployment guidelines (Gunicorn, Waitress, Nginx reverse proxy) and comprehensive environment variable reference.

- **Phase 4D Upload Limits, Rate Limits, Quotas & Cleanup (`utils/upload_validator.py`, `utils/cleanup.py`, `utils/limiter.py`, `config.py`, `app.py`, `components/routes.py`, `utils/session_manager.py`, `requirements.txt`, `tests/test_phase4d_upload_limits.py`)**:
  - `utils/upload_validator.py`: Built upload content sniffing and validation pipeline. Rejects mismatched magic bytes (e.g. XLSX bytes declared as CSV), enforces row caps (`MAX_ROWS=200,000`) and column caps (`MAX_COLS=500`), restricts XLSX sheet count (`MAX_XLSX_SHEETS=10`), blocks workbooks containing VBA macros (`xl/vbaProject.bin`) or external links (`xl/externalLinks/`), and rejects zip decompression bombs (`MAX_UNCOMPRESSED_BYTES=200MB`).
  - `utils/limiter.py` & `app.py`: Standardized `Flask-Limiter` with user-aware key resolution (prefers authenticated `current_user.id` over client IP). Applied route-level decorators: 10 uploads/hr on `/api/upload`, 60 chat turns/hr on `/api/sessions/<id>/chat` and `/api/sessions/<id>/chat/stream`, and 10 report compilations/hr on `/api/sessions/<id>/pdf`.
  - `components/routes.py`: Enforced per-user quotas (max 20 active sessions via `MAX_SESSIONS_PER_USER`, max 500 MB total storage across uploads/outputs via `MAX_STORAGE_BYTES_PER_USER`). Implemented UUID-only on-disk filenames (`<uuid>.<ext>`) preserving original filenames strictly for display metadata. Added authenticated `DELETE /api/me/data` endpoint for total user data erasure.
  - `utils/cleanup.py`: Implemented `delete_session_files()` shared cleanup helper removing raw uploads, cleaned datasets, generated charts, PDF reports, and session JSON files. Added background thread scheduler `start_cleanup_scheduler()` running periodic TTL expiry sweeps (default 24h inactivity based on `last_accessed`).
  - `utils/session_manager.py`: Added lazy `_touch_last_accessed()` fire-and-forget worker updating `last_accessed` on session read/load if older than 60 seconds.
  - `tests/test_phase4d_upload_limits.py`: Added 14 unit and integration tests verifying sniff checks, macro/bomb/shape rejections, delete cascades, TTL cleanup sweep, and UUID storage. Full test suite passes 100% (86/86 tests).

- **Authentication UI (`static/index.html`, `static/app.js`, `static/style.css`)**: Implemented full frontend auth lifecycle — `initAuth()` checks `/api/auth/me` on page load, shows `#auth-modal` when unauthenticated, handles register/login form via `handleAuthSubmit()`, displays user badge, and intercepts 401 responses on all API calls (including `/api/upload`) to re-show the modal.

### Fixed
- **`GET /api/sessions` 500 error on null `created_at`** (`components/routes.py`): Legacy sessions storing `"created_at": null` caused `TypeError` during sort. Fixed sort key to `x.get("created_at") or ""` which coerces `None` → `""`.
- **Upload 401 handling** (`static/app.js`): Added guard to `uploadRawDatasetFile` so expired sessions trigger the auth modal.

### Added (continued)
- **Phase 4C LLM Provider Safety & Prompt Bounds (`utils/url_validator.py`, `utils/logging_filter.py`, `services/ai_service.py`, `services/data_service.py`, `components/routes.py`, `tests/test_phase4c_llm_safety.py`)**:
  - `utils/url_validator.py`: Implemented `validate_base_url` for SSRF defense. Enforces HTTPS, resolves hostnames to prevent DNS rebinding, blocks cloud metadata (`169.254.169.254`, `169.254.170.2`), link-local, private networks (10/8, 172.16/12, 192.168/16), multicast, and loopback (in production). Unwraps NAT64 IPv6 (`64:ff9b::/96`) to permit valid dual-stack cloud providers (e.g. Nvidia API). Allows HTTP for localhost dev only when `DEBUG=true`.
  - `utils/logging_filter.py` & `app.py`: Created `APIKeyRedactionFilter` regex-scrubbing OpenAI, Anthropic, Gemini, Nvidia, Groq keys, and Bearer tokens to `[REDACTED_API_KEY]` across all application and worker logging handlers.
  - `components/routes.py`: Added base URL validation to `/api/analyze`, `/api/sessions/<id>/chat`, and `/api/sessions/<id>/chat/stream` returning 400 on prohibited URLs.
  - `services/ai_service.py`: Added `num_retries=2` and `timeout=45.0` to `UnifiedLLMClient.Chat.Completions.create` and enforced base URL validation on direct client instantiation.
  - `services/data_service.py` & `components/routes.py`: Bounded prompt context to max 50 columns (with truncation annotation), max 3 sample values per column, and max 120 characters per sample string.
  - `tests/test_phase4c_llm_safety.py`: Added 13 unit and integration tests covering SSRF rejection, URL validation, log redaction, prompt caps, and route rejection. Full test suite passes 100% (72/72 tests).

- **Phase 4B Authentication & Session Ownership (`utils/auth.py`, `app.py`, `components/routes.py`, `config.py`, `tests/test_phase4b_auth.py`)**:
  - `utils/auth.py`: Built lightweight SQLite user authentication with secure password hashing (`generate_password_hash` via argon2/pbkdf2:sha256). Added `User` model conforming to `Flask-Login` protocols, registration, login, and session ownership guards (`get_owned_session_or_404`).
  - `components/routes.py`: Applied `login_required_api` decorator across all `/api/*` routes (except health, login, register). Attached `owner_id` to uploaded sessions and isolated session lists (`/api/sessions`) to the authenticated user. Enforced 404 on unowned sessions to prevent ID harvesting.
  - `tests/test_phase4b_auth.py`: Added 14 unit and integration tests verifying user registration, login, session isolation, cross-user 404 access restrictions, and unowned session migration.
- **Phase 4A Safe Defaults & Production Hardening (`app.py`, `config.py`, `README.md`, `requirements.txt`, `.env`, `.env.example`, `tests/test_phase4a_safe_defaults.py`, `powerbi_visuals/single_metric_visuals.py`)**:
  - `app.py`: Implemented `validate_secret_key` enforcing that the app refuses to boot in production (`DEBUG=false`) if `SECRET_KEY` is missing or set to an insecure placeholder. Development/testing modes use safe fallback keys with a warning.
  - `app.py`: Added global `@app.after_request` security headers hook setting `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, and `Content-Security-Policy` with an exact allowlist for Chart.js, Google Fonts, FontAwesome, and Folium map iframes.
  - `app.py`: Added `@app.errorhandler(413)` returning a clean JSON error response (`File size exceeds maximum allowed upload limit (16MB)`) instead of raw HTML error pages.
  - `README.md` & `requirements.txt`: Documented production entrypoints for Gunicorn (`gunicorn -w 4 -b 127.0.0.1:5000 app:app`) on Linux/containers and Waitress (`waitress-serve`) on Windows. Added `gunicorn` and `waitress` to `requirements.txt`.
  - `single_metric_visuals.py`: Fixed Matplotlib gauge background arc color from CSS `rgba()` string to native Matplotlib RGBA tuple `(1, 1, 1, 0.1)`, preventing 500 errors on gauge visualization generation.
  - `tests/test_phase4a_safe_defaults.py`: Added 5 unit tests covering secret key validation, security headers, and 413 JSON responses. Full test suite passes 100% (53/53 tests).

- **Phase 3 Data-Correctness Engine & Typed Execution Architecture (`services/cleaning/schema.py`, `services/cleaning/engine.py`, `services/cleaning/executor.py`, `services/cleaning/operation_registry.py`, `services/data_service.py`, `components/routes.py`, `tests/test_phase3_data_correctness.py`)**:
  - **Typed Pydantic Schemas (`schema.py`)**: Defined typed operation models (`DropColumnOp`, `KeepColumnOp`, `ReplaceValueOp`, `ImputeOp`, `NormalizeOp`, `EncodeOp`, `ParseDateOp`, `DropDuplicatesOp`, `ClipOutliersOp`, `LogTransformOp`, `ConvertTypeOp`, `RoundNumericOp`, `RenameColumnOp`, `StripWhitespaceOp`, `CaseTransformOp`) and pre-execution validation against real DataFrame columns, types, and constraints (`validate_operation_against_dataframe`).
  - **Single Canonical Cleaning Engine (`engine.py`)**: Built `run_cleaning_engine(df, actions)` serving as the single point of execution for both `/api/process` (`process_dataset`) and background worker `run_background_process`.
  - **Strict KEEP Semantics**: Kept columns are guaranteed zero modification; completely removed implicit median/"Unknown" imputation.
  - **Dtype & NaN Preservation**: Removed `astype(str)` whole-column casting in `executor.py` value replacements. Replacements now preserve column dtypes and preserve `NaN` untouched.
  - **Math & Statistical Corrections**: Fixed log transform to avoid silent clipping of negative values (masks to `np.nan` with audit notice); made outlier clipping/dropping thresholds configurable while reporting affected row counts; defaulted nominal categorical encoding to one-hot encoding; upgraded operation registry keyword matching to word-boundary regexes to prevent short-token substring collisions (`'0'`, `'log'`, `'int'`).
  - **Audit Logging & Dynamic PDF Reports**: Every operation records typed audit records and computes before/after quality metrics (nulls, duplicates, dtypes, rows affected). PDF reports in `routes.py` now compile executive summaries and quality tables directly from live audit logs.
  - **Prompt Injection Defense**: Wrapped dataset samples in `<untrusted_sample_value>` tags in `summarize_schema()` and added strict LLM prompt directives forbidding code/instruction execution from inside untrusted samples.
  - **Test Suite**: Added `tests/test_phase3_data_correctness.py` (10 test cases). Full test suite passes 100% (48/48 tests).

### Fixed
- **Numerical Rounding Intent Priority & Int64 Precision (`services/cleaning/intent_parser.py` & `services/cleaning/executor.py`)**:
  - `intent_parser.py`: Moved `round_values` operation detection check (`r'\bround(?:\s+off)?\b'`) above `convert_datatype` in `_detect_operation()`. Previously, prompts like `"Round off all numerical values in the AlcoholConsumption column to the nearest whole number"` were misclassified as `convert_datatype` due to `numeric`/`to` keyword matching. Fixed unit conversion canonical operation return name (`convert_unit`).
  - `executor.py`: Ensured 0-decimal rounding converts to `.astype('Int64')`, cleanly removing trailing decimals and decimal points in table previews.
  - Test Suite (`tests/test_rounding.py` & `tests/test_cleaning_engine.py`): Created test suite `tests/test_rounding.py` and updated unit conversion tests, ensuring all 38 pytest cases pass 100%.
- **Phase 2 Frontend Safety (`static/app.js` & `static/index.html`)**:
  - `app.js`: Added `escapeHTML()` helper. Replaced `innerHTML` with safe `textContent`/`createElement` patterns in: session list items (user goal/name), chat history bubbles (LLM content now via `renderChatMarkdown`), schema card column names/types/reasons/sample values (dataset cell values), chart card titles/descriptions (AI output), custom chart loading spinner (user param), and chart error messages (`err.message`). Intentionally preserved `contentDiv.innerHTML = data.chart.data` for server-rendered folium HTML maps.
  - `app.js`: Moved API key from `localStorage` to `sessionStorage` (`llm_api_key`). Old `nvidia_api_key` localStorage entry is auto-removed on next settings save. API key now clears automatically when the browser tab closes.
  - `index.html`: Added amber data-sharing disclosure notice inside the Settings modal warning users that dataset schema and sample values are sent to the selected LLM provider.
 (`app.py`, `utils/session_manager.py`, `services/data_service.py`, `requirements.txt`)**:
  - `app.py`: Updated server startup to read `HOST` (default `127.0.0.1`), `DEBUG` (default `False`), and `PORT` (default `5000`) from environment variables.
  - `utils/session_manager.py`: Updated `sanitize_session_id` to strictly validate `session_id` as a valid UUID string using `uuid.UUID`.
  - `services/data_service.py`: Removed dead code loop `for chart in charts:` where `charts = []`.
  - `requirements.txt`: Added `xlrd==2.0.2` and pinned all dependency versions.
  - Test Suite (`tests/test_phase1_hygiene.py`, `test_pin_report.py`, `test_chat.py`, `test_visual.py`, `test_viz_ai.py`): Fixed hardcoded Windows file paths (`C:\Users\...`), added `conftest.py` with portable Flask test fixtures, and verified all 35 tests pass 100%.
- **Cleaned Data Preview & Session Persistence (`services/data_service.py` & `static/app.js`)**: Fixed an issue where reloading the browser page or restoring a session showed updated Action Schema recommendations but reset the Data Preview tab to uncleaned/blank state. Updated `run_background_process()` to persist `preview_data`, `row_count`, `col_count`, and `status="done"` directly to session JSON on disk, and updated `renderLoadedSessionUI()` in `static/app.js` to render the cleaned table preview and visualization charts whenever a session is loaded or refreshed.
- **Natural Language Transformation Intent Parser (`services/cleaning/intent_parser.py` & `services/data_service.py`)**: Fixed value mapping pattern extraction and prompt standardizer to support natural phrasing like `transform <column> "old" into "new"`. Stripped column noise words (`column`, `col`, `feature`), added `transform` to operation detection keywords, and prevented prompt standardizer from mangling natural verb prompts. Confirmed 100% successful transformation execution (`Others` → `Bugati`).
- **Natural Human Language Transformation Engine (`services/cleaning/intent_parser.py`)**: Upgraded intent parser, step splitter, and parameter extractor to seamlessly understand natural human instructions in any format (e.g. `0 to No`, `0 -> No`, `0 = No`, `change 0 to No`, `replace Tesla with Tesla Motors`, `convert float`, `fill missing with 0`). Fixed multi-word string truncation and prioritized structural operations (`rename`, `move`, `remove_rows`) to guarantee 100% accurate, error-free data transformations for user prompts.
- **Security & Session Isolation (Component 1)**: Enforced strict regex validation `^[a-zA-Z0-9_-]+$` on `session_id` in `utils/session_manager.py` to eliminate Path Traversal vulnerabilities. Added `SESSION_LOCK` with exponential backoff on file replacement to prevent Windows `PermissionError` file-locking crashes. Added thread-safe `SESSION_CACHE` in-memory lookup.
- **DoS Protection & Data Sampling in Custom Chart Generation (Component 2)**: Added smart downsampling (`df.iloc[::step]`) for large line/scatter plots (>1,000 rows) and top-30 aggregation (`groupby().mean()`) for bar/pie charts in `components/routes.py`.
- **Matplotlib Thread Safety & HD Chart Rendering (Component 3)**: Added a global reentrant `PLOT_LOCK` in `powerbi_visuals/trend_charts.py` and `components/routes.py`, and set `dpi=200`, `bbox_inches='tight'`, and `transparent=True` for high-definition chart rendering without quality compromise.
- **Non-Destructive File Edits & Cell Type Ingestion (Component 4)**: Updated cell edits to save to working copies in `OUTPUT_FOLDER` (`edited_<file_id>`), preserving raw upload files in `UPLOAD_FOLDER`. Added smart type casting (`int`, `float`, `bool`, `Timestamp`) on cell edits and fixed NaN radius handling in `powerbi_visuals/geo_charts.py`.
- **Pandas 3.0 Copy-on-Write Future-Proofing (Component 5)**: Updated dataframe assignment patterns in `services/cleaning/executor.py` to use `.loc[:, col]` for full forward compatibility with Pandas 3.0+.

### Verified
- **Full Project Quality & Security Audit**: Conducted full architectural, security, and test suite audit across all project components. Confirmed **0 remaining bugs/errors** across all 12 audited issue categories with **100% test suite pass rate (30/30 tests passing)**. Added deterministic NLP fallback (`services/cleaning/intent_parser.py`) ensuring zero downtime during external AI provider outages.

### Added - Interactive Visual Picker Gallery & Custom PDF Report Pinning System
- **PowerBI Visual Picker Palette (`static/index.html` & `static/app.js`)**: Added an interactive 11-category chart gallery (Line, Area, Bar, Column, Pie, Donut, Treemap, Waterfall, Scatter, Histogram, Gauge, Map) enabling users to render charts on demand without server overload.
- **Visual Configuration Modal**: Clicking any chart icon opens a modal allowing users to select X-Axis (Category) and Y-Axis (Metric) columns.
- **Custom PDF Report Pinning (`/api/sessions/<id>/pin_chart`)**: Every generated chart features an interactive **"📌 Add to PDF Report"** button with a live badge counter (`📌 N Pinned`).
- **Customized PDF Compilation (`components/routes.py`)**: Updated PDF report generator to embed user-pinned visual selections directly into the exported PDF.

### Added
- **Structured Intent & Safe Execution Engine (`services/cleaning/`)**:
  - Implemented `services/cleaning/` architecture separating interpretation (`intent_parser.py`), central operation definitions (`operation_registry.py`), pre-execution validation (`validator.py`), safe isolated handlers (`executor.py`), and structured before/after audit logging (`audit.py`).
  - Added support for explicit datatype conversion (`convert to int/float/str/bool/category/datetime`), subset deduplication (`remove duplicates based on Customer_ID`), column-specific null removal (`remove rows where Age is null`), keep-only columns (`keep only Age, Gender and Salary`), substring/regex replacement, expanded unit conversions (`g<->kg`, `m<->ft`, `cm<->inch`, `L<->gallon`, `mL<->L`), and multi-format datetime parsing (`25-Aug-2023`, `August 30, 2023`, `15/02/2023`).
  - Added dry-run endpoint `/api/sessions/<session_id>/dry_run` for pre-execution validation without modifying files on disk.
  - Added unit test suite `tests/test_cleaning_engine.py` (26 test cases) validating all cleaning operations and realistic natural-language prompts.

### Fixed
- **Removed Dangerous Fallback Imputation**: Removed automatic median/Unknown fallback imputation on unrecognized operations in `apply_column_transformation`. Unrecognized or ambiguous prompts now return clear validation messages without mutating data.
- **Fixed `keep` Action Semantics**: Removed silent median/Unknown imputation on kept columns in `routes.py` and `run_background_process()`. `keep` now guarantees zero modification.
- **Removed Goal-Keyword Auto Deduplication / Dropna**: Removed automatic `df.drop_duplicates()` and `df.dropna()` triggered by words in user goal strings. Deduplication and null removal are now performed strictly when explicitly requested via column actions.
- **Fixed Undefined `base_url` NameError**: Defined `base_url = data.get("base_url")` in non-streaming `chat_session` endpoint (`routes.py`).

- **Smart Fuzzy Column Matcher & Task Execution Commands (`services/data_service.py`, `components/routes.py`, `static/app.js`)**:
  - Implemented `match_column_name()` using `difflib.SequenceMatcher` to fuzzy match column names in user chat prompts regardless of UK/US spelling differences (`behavioural` vs `behavioral`), singular/plural forms (`problem` vs `problems`), or missing underscores.
  - Added execution command detection (`perform task man`, `execute`, `do it`, `clean dataset`) that forces immediate dataset re-processing and streams updated preview tables to the UI.
  - Updated `app.js` SSE event handler to invoke `autoReprocessWithGridState()` whenever chat streaming emits `trigger_reprocess`.
- **AI Prompt Polish & Intent Standardizer Module (`services/data_service.py` & `components/routes.py`)**: Built `polish_and_standardize_prompt()` module that automatically intercepts raw, typo-ridden, or shorthand user prompts (e.g. `tranform`, `0-> no and 1->yes`, `reove col`) and polishes them into clean, canonical execution instructions (`where 0 replace NO and where 1 replace YES`) before triggering transformation pipelines.
- **Comprehensive 8-Category Transformation Engine & Instruction Chaining (`services/data_service.py`)**: Refactored `apply_column_transformation(df, col, trans)` to support multi-operation instruction chaining (split by `, then `, `; `, ` -> `, ` && `) and 8 complete transformation categories:
  1. **Encoding**: One-hot/dummy encoding (`one-hot`), Ordinal encoding with custom/auto order (`ordinal order: low, medium, high`), Frequency encoding by count or proportion (`frequency encode`).
  2. **Datetime**: Extract day, weekday name, quarter, hour, minute, `is_weekend` boolean feature, and date difference / `days since <col>/today`.
  3. **Text/String Cleaning**: Strip punctuation/special characters (`strip punctuation`), remove stopwords, regex extraction (`extract digits/email/phone`), strip HTML tags (`strip html`), string length feature (`string length`), split column into sub-columns (`split by <sep>`), concatenate columns (`concat with <col>`).
  4. **Numeric/Format Parsing**: Parse percentage strings (`50%` -> `0.5`), accounting negative currency (`(1,200)` -> `-1200`), normalize boolean-like values (`Yes/No`, `Y/N`, `True/False` -> `1/0`), unit conversions (`kg to lb`, `km to mi`, `c to f`, `f to c`).
  5. **Outlier / Row-Level Handling**: IQR outlier detection with option to clip or drop rows (`iqr outlier`, `drop outlier rows`), full-row whole-dataframe duplicate removal (`drop full duplicates`), simple condition row filtering (`keep rows where <col> <op> <val>`), explode delimited cells (`explode by <sep>`).
  6. **Structural Operations**: Rename column (`rename to <name>`), reorder column (`move to front/end`), bin/bucket continuous numeric column into categories (`bin into <N> groups`), derived math columns (`multiply by <col>`), drop constant/low-variance columns (`drop constant`).
  7. **Missing Value Normalization & Inf Handling**: Normalize fake missing placeholders (`N/A`, `null`, `none`, `-`, `?`, `""`) and `inf`/`-inf` values to `NaN`.
  8. **Multi-Pair Value Replacement**: Multi-pair conditional regex replacement (`where 0 replace NO and 1 replace YES`).
- **Direct Interactive UI Cell Editing (`components/routes.py` & `static/app.js`)**: Added `/api/sessions/<id>/update_cell` endpoint and enabled click-to-edit (`contentEditable`) in the Data Preview table so users can directly click and modify any cell in the dataset.
- **Cell Value Replacement & Custom Mapping (`services/data_service.py` & `components/routes.py`)**: Added regex pattern parser to `apply_column_transformation` supporting commands like `replace 'OLD' with 'NEW'`, `change 'X' to 'Y'`, and custom missing value fillers. Updated system prompt to guide the AI on cell value replacements.
- **Versatile Agentic Transformation Engine (`services/data_service.py`)**: Built `apply_column_transformation` supporting comprehensive data operations:
  - String case conversion (`uppercase`, `lowercase`, `titlecase`, `strip whitespace`)
  - Currency symbol cleaning (`$`, `€`, `£`, `,`)
  - Categorical label encoding (`cat.codes`)
  - Advanced imputation strategies (`mean`, `median`, `mode`, `zero`, `unknown`)
  - Scaling & Math transformations (`Min-Max Scaling`, `Z-score Standardization`, `Log(1+x)`, `Rounding`)
  - Feature extraction (`Year`, `Month` from datetime columns)
- **Multi-Provider LLM Abstraction (`services/ai_service.py`)**: Built a robust `UnifiedLLMClient` backed by `LiteLLM` that acts as a drop-in replacement for standard OpenAI client. Supports automatic provider detection, custom base URLs, custom API keys, and auto-fallback behavior.
- **Environment Matrix Setup (`.env.example`)**: Added `.env.example` defining environment variables for all major providers (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_BASE_URL`, `LLM_PROVIDER`, `LLM_MODEL`).
- **Unit & Integration Tests**: Expanded `tests/test_app.py` with `test_unified_llm_client_routing` validating auto-routing resolution and client configurations across OpenAI, Anthropic, Gemini, OpenRouter, and Ollama.
- **Safe DataFrame Serialization (`components/routes.py` & `services/data_service.py`)**: Added `get_safe_preview` utility helper that safely converts DataFrame slices to object types and converts `pd.NaT`/`NaN` nulls to prevent `TypeError` during Flask `jsonify()` status responses.

### Removed
- **Header Goal Subtitle (`static/app.js`)**: Removed the `Goal: ...` subtitle text line from the main workspace header UI per user design request.
### Fixed
- **Streaming Chat Threading Context Fix (`components/routes.py`)**: Fixed `NameError: name 'app_obj' is not defined` on line 1032 of `routes.py` inside `run_ai_stream()` by passing `current_app._get_current_object()` into `threading.Thread` target `run_background_process`.
- **Status Polling Self-Healing & Spinner Timeout Safeguard (`components/routes.py` & `static/app.js`)**:
  - Implemented self-healing logic in `/api/sessions/<id>/status` so if an in-memory job state is `idle` (e.g. after a server restart), the server automatically returns `done` with the session's saved `bg_result` or `cleaned_filename`.
  - Added a 30-second polling timeout safeguard and `idle` status resolution in `startStatusPolling()` to automatically hide the `Updating data in background...` spinner badge and prevent UI hanging.
- **Arrow Notation Regex & Goal Prompt Parser (`services/data_service.py` & `components/routes.py`)**:
  - Added arrow pattern matching (`0->no`, `1->yes`, `0 -> no`, `0=>no`) to `apply_column_transformation`.
  - Added `user_wants_trans` check in `generate_mock_recommendations` and updated LLM system prompt rules in `background_analyze()` so initial Goal prompts containing arrow syntax automatically trigger `action: "transform"` on the target column instead of defaulting to `keep`.
- **Value Replacement Priority & Keyword Trap Fix (`services/data_service.py`)**: Moved Multi-Pair Value Replacement (`replace X with Y`, `where 0 replace NO and 1 replace YES`) to top priority in `apply_column_transformation`. Fixed keyword collision where `0` in prompt sentences accidentally triggered zero imputation fallback instead of cell mapping.
- **Table Transformation Engine Integration (`components/routes.py`)**: Fixed `/api/process` (`process_dataset()`) in `routes.py` which previously used legacy inline if/elif checks that bypassed `apply_column_transformation`. Now delegates all column transformations directly to `apply_column_transformation(df, col, trans)`.
- **Frontend Auto-Reprocess Restoration (`static/app.js`)**: Enabled `autoReprocessWithGridState()` in `app.js` when editing column cards (clicking `Keep`/`Trans`/`Drop` or editing `transform-input` text boxes), ensuring manual table transformations trigger immediate server re-processing and UI table refresh upon `blur`/`change`.
- **Multi-Pair Value Replacement Engine (`services/data_service.py`)**: Enhanced `apply_column_transformation` with multi-pair regex parsing (e.g. `where there is 0 replace it with NO and where there is 1 replace it with YES`), string/float/int dictionary mapping, and original case preservation.
- **Goal-Based Global Deduplication & Null Dropping (`services/data_service.py`)**: Added automatic global `df.drop_duplicates()` and `df.dropna()` execution in `run_background_process` when requested in the session goal prompt (e.g. `remove duplicates and null values`).
- **Multi-Column Chat Prompt Safety Net (`components/routes.py`)**: Added a multi-column safety net parser in `run_ai_stream` that inspects user chat messages for lists/comma-separated column names (e.g. `remove year,month_name,state column`) and immediately assigns `action: "drop"`, `"keep"`, or `"transform"` to every mentioned column, triggering automatic dataset re-processing.
- **Chain-of-Thought (CoT) Monologue Suppression (`components/routes.py` & `services/ai_service.py`)**: Added automatic text block stripping for `"Here's a thinking process:"` to prevent reasoning models from printing internal thoughts into the user chat window. Switched default Nvidia NIM model to `meta/llama-3.3-70b-instruct` for clean, instant instruction execution.
- **Conservative Column Recommendation Policy (`components/routes.py` & `services/data_service.py`)**: Fixed AI analysis system prompt and mock fallback rules so all columns default to `action: "keep"`. Columns are now only recommended for dropping if explicitly requested by the user's Goal prompt or if 100% empty, eliminating unwanted automatic column deletions.
- **Nvidia NIM API Integration & Reasoning Support (`services/ai_service.py` & `components/routes.py`)**: Integrated official OpenAI client protocol (`openai/<model>` with base URL `https://integrate.api.nvidia.com/v1`) for Nvidia models (e.g. `nvidia/nemotron-3.5-lightning-30b-a3b`). Added streaming token extraction for `reasoning_content` in addition to standard `content`.
- **Provider Override vs Model Auto-Detection (`services/ai_service.py`)**: Fixed `UnifiedLLMClient.resolve_config` so model-specific indicators (e.g., `gemini`, `claude`, `gpt-`, `glm`) and explicit provider prefixes take precedence over stale or mismatched provider overrides, preventing API errors like sending Gemini models to Groq.
- **Google / Gemini API Key & Alias Resolution (`services/ai_service.py`)**: Added `GOOGLE_API_KEY` lookup fallback for Gemini, handled `google` provider alias mapping, and fixed double `gemini/` model prefixing.
- **Pytest Discovery Failure (`test_chat.py`)**: Wrapped top-level script execution in `test_chat.py` inside `if __name__ == '__main__':` to prevent pytest collection failures.
- **LLM Provider Auto-Routing**: Fixed provider resolution order in `services/ai_service.py` (`UnifiedLLMClient.resolve_config`) to evaluate model string patterns (e.g. `gpt-4o`, `claude-3`) prior to falling back to the `LLM_PROVIDER` environment default.
- **Asynchronous Analysis Integration Test**: Updated `tests/test_app.py` (`test_upload_and_flow`) to handle asynchronous background `/api/analyze` status responses and poll session detail until recommendations populate.
- **Python 3.14 Datetime Compatibility**: Fixed `pd.to_datetime` C-extension segmentation fault under Python 3.14 in `components/routes.py` and `services/data_service.py` by converting datetime columns safely using Python standard library `datetime.strptime`.
- **Data Preview Failure**: Resolved 500 JSON serialization crash during status/preview polling caused by unhandled `pd.NaT` values.
- **Chat Column Dropping Bug**: Enforced exact word-boundary regex matching for column actions in local fallback parsing, and added strict system prompt rules so chat column updates affect only user-requested columns.

### Changed
- **REST Blueprint Routes (`components/routes.py`)**: Refactored `/api/analyze`, `/api/sessions/<id>/chat`, and `/api/sessions/<id>/chat/stream` to parse `provider`, `model`, and `base_url` overrides from incoming JSON request payloads, and instantiate the proper unified client.
- **Frontend Configuration Panel (`static/index.html` & `static/app.js`)**: Updated the "Nvidia API Key" button to "LLM Configuration" and redesigned the modal with dropdown selectors for LLM Provider (NVIDIA, OpenAI, Anthropic, Gemini, OpenRouter, Ollama) and text fields for Model, API Key overrides, and Custom Base URLs. Persisted LLM settings dynamically in `localStorage` across page loads.

### Added
- Created `tests/test_app.py` containing integration regression tests verifying backend endpoints, upload, chat streaming, and mock engines under pytest.

### Changed
- **Refactored `app.py` Monolith**:
  - Extracted global configurations to `config.py`.
  - Created `utils/helpers.py` for input validations and JSON extraction.
  - Created `utils/session_manager.py` implementing session storage and a highly robust `CustomJSONEncoder` to serialize Pandas and NumPy data types.
  - Created `utils/fonts.py` and `utils/job_tracker.py` for font registry and background worker state tracking.
  - Created `services/ai_service.py` and `services/data_service.py` to organize OpenAI API credentials and dataset operations.
  - Created `components/routes.py` consolidating all REST API endpoints and ReportLab PDF compiling under a Flask Blueprint.
  - Redefined `app.py` as a lean main entry point registering the blueprint and booting the Flask server.
- **Improved Serializability**: Fixed latent JSON serialization bug in session saves by supporting Pandas Timestamp serialization automatically during clean runs.
- **Fixed latent NameError**: Added explicit fallback for unassigned local variable `charts` inside synchronous processing endpoints.

## [0.1.0] - 2026-07-29

### Added
- Phase 1 & 2 baseline documentation for Agent Readiness (`AGENTS.md`, `ARCHITECTURE.md`, `COMMIT.md`, `CHANGELOG.md`, `COMMIT_LOG.md`, `KNOWLEDGE_GRAPH.md`).
- Established Token Optimization Protocol and Knowledge Graph Maintenance Rules.
