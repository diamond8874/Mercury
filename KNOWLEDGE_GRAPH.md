# Knowledge Graph

Lightweight structural index of the repository, kept so agents can locate code
without scanning full source files. **Consult this before reading raw sources,
and update it in the same commit as any structural change.**

## Module & Dependency Map

| File/Module | Type | Description | Dependencies |
|-------------|------|-------------|--------------|
| `app.py` | Flask Factory | `create_app()`: config, Blueprint, auth guard, security headers, JSON error handlers, health/ready probes, retention sweep. | `flask`, `config`, `components.routes`, `utils.*` |
| `wsgi.py` | WSGI Entrypoint | Exposes `application` for waitress/gunicorn. One worker, many threads. | `app` |
| `config.py` | Configuration | Environment-driven paths, limits, security, retention, LLM vars, plus `validate()`. | `os`, `secrets`, `dotenv` |
| `components/routes.py` | Blueprint Routes | All REST + SSE endpoints and PDF compilation. Thin layer over the services. | `flask`, `pandas`, `reportlab`, `services.*`, `utils.*` |
| `services/llm_provider.py` | AI Service | Provider registry, key detection, config resolution, `LLMClient` (openai + anthropic transports), model listing, verification. | `openai`, `urllib`, `os`, `json` |
| `services/ai_service.py` | Compat Shim | Backwards-compatible re-exports over `llm_provider`. No vendor logic of its own. | `services.llm_provider` |
| `services/profile_service.py` | Data Service | Dataset reading, semantic typing, column statistics, correlations, warnings, profiling worker. | `pandas`, `numpy`, `utils.*` |
| `services/data_service.py` | Data Service | Recommendation engines (AI + offline), `apply_actions` cleaning, analysis and processing workers. | `pandas`, `numpy`, `services.*`, `utils.*` |
| `services/chart_service.py` | Viz Service | Chart planning (AI + statistical), spec validation, Chart.js payloads, Matplotlib rendering. | `pandas`, `numpy`, `matplotlib`, `utils.helpers` |
| `utils/job_tracker.py` | Job Utility | Thread-safe pipeline state machine, disk-mirrored job state, profile-ready handshake. | `threading`, `json`, `os`, `utils.session_manager` |
| `utils/session_manager.py` | Session Utility | Atomic session load/save, pandas/numpy-aware encoder, retention sweep. | `json`, `os`, `datetime`, `pandas`, `numpy`, `flask`, `config` |
| `utils/helpers.py` | Helper | Filename validation and JSON extraction from model output. | `json`, `config` |
| `utils/fonts.py` | PDF Font Utility | Downloads and registers the Lora fonts, with a timeout. | `os`, `urllib`, `reportlab` |
| `generate_test_data.py` | Script | Generates a synthetic dirty dataset for testing. | `pandas`, `numpy`, `random` |
| `tests/test_app.py` | Test Suite | 73 offline tests: pipeline stages, routes, provider resolution, cleaning, charts, chat, auth, retention, config validation. | `pytest`, `pandas`, `app`, `wsgi` |
| `static/app.js` | Frontend JS | Client logic: settings, upload, read-out card, status polling, schema grid, charts, chat. | Chart.js |
| `static/index.html` | Frontend UI | Layout, sidebar drawer + backdrop, provider settings modal, dataset read-out card, dashboard tabs. | `style.css`, `app.js` |
| `static/style.css` | Stylesheet | Design system plus the responsive layer: 11 media queries (1440/1200/1024/820/640/420, short viewport, coarse pointer, reduced motion, print). | none |

## Interface Summaries

### `app.py`
- `def create_app()`: builds the configured app; raises on unsafe production config.
- `def _register_guards(app)`: `MERCURY_API_TOKEN` check (constant-time), CORS allowlist, security headers.
- `def _register_error_handlers(app)`: JSON for 401/404/405/413/500 and unhandled exceptions (re-raises in debug/testing).
- `def _register_ops_routes(app)`: `GET /api/health`, `GET /api/ready`.
- `PUBLIC_PATHS`: probe paths exempt from auth.

### `wsgi.py`
- `application` / `app`: the WSGI callable for `waitress-serve` / `gunicorn`.

### `config.py`
- `ENVIRONMENT`, `IS_PRODUCTION`, `SECRET_KEY`, `LOG_LEVEL`.
- `DATA_DIR`, `UPLOAD_FOLDER`, `OUTPUT_FOLDER`, `SESSION_FOLDER`.
- `ALLOWED_EXTENSIONS`, `MAX_UPLOAD_MB`, `MAX_CONTENT_LENGTH`.
- `API_TOKEN`, `TRUSTED_PROXY_COUNT`, `CORS_ORIGINS`.
- `RETENTION_DAYS`, `MAX_SESSIONS`.
- `LLM_API_KEY` / `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL`.
- `MAX_CHARTS`, `PROFILE_WAIT_TIMEOUT`.
- `def validate()`: returns fatal config problems; `create_app()` aborts on any.
- Helpers: `_env_flag`, `_env_int`.

### `services/llm_provider.py`
- `PROVIDERS`: registry of 17 providers (label, base_url, default_model, key_prefixes, env_keys, transport, requires_key, models_path, docs).
- `class LLMError(Exception)`: surfaced provider failure.
- `class LLMConfig`: resolved settings; `.is_mock`, `.is_live`, `.public_dict()` (never leaks the key).
- `class LLMClient`: uniform client.
  - `.chat(messages, temperature, max_tokens, json_mode)` -> str
  - `.stream_chat(messages, temperature, max_tokens)` -> iterator of text deltas
  - `.list_models(limit)` -> list[str]
  - `.verify()` -> dict consumed by the settings UI
  - `.describe` -> "Provider / model" label used in chat and reports
  - `.is_live`, `.is_mock`, `.model`, `.provider`
- `def detect_provider(api_key)`: provider id from key prefix, longest-match first.
- `def resolve_llm_config(api_key, provider, model, base_url)` -> `LLMConfig`.
- `def provider_catalog()`: registry rendered for `GET /api/providers`.
- `def get_llm_client(...)` / `client_from_request(data)` / `llm_options_from_request(data)`.
- Internals: `_split_system`, `_http_json`, `_http_stream`, `_is_param_error`.

### `services/ai_service.py`
- Re-exports `LLMClient`, `LLMConfig`, `LLMError`, `get_llm_client`, `resolve_llm_config`, `detect_provider`, `provider_catalog`, `client_from_request`, `llm_options_from_request`.
- `def get_openai_client(request_key, provider, model, base_url)`: legacy raw-SDK helper; returns `None` in offline/anthropic modes.

### `services/profile_service.py`
- `def read_dataset(file_path, file_ext, sheet_name)` -> DataFrame.
- `def profile_column(series, name, total_rows)` -> per-column stats block.
- `def build_profile(df, sheet_name, sample_rows)` -> full profile dict.
- `def compact_profile_for_llm(profile, max_columns)` -> token-trimmed profile.
- `def run_background_profile(app, session_id, sheet_name)`: **worker**, `profiling` -> `profile_ready`.
- Internals: `_semantic_type`, `_looks_like_dates` (checked before the identifier heuristic), `_json_safe`.
- Constants: `IDENTIFIER_UNIQUE_RATIO`, `MAX_CATEGORICAL_CARDINALITY`.

### `services/data_service.py`
- `def summarize_schema(df, max_samples)`: legacy compact summary.
- `def generate_mock_recommendations(df, goal, profile)`: deterministic KEEP/DROP/TRANSFORM plan.
- `def generate_recommendations(llm, df, goal, profile)` -> `(recommendations, source, warning)`; AI with offline fallback.
- `def generate_mock_charts(df, goal)`: alias for the deterministic chart planner.
- `def apply_actions(df, actions)` -> `(cleaned_df, stats)`. **Single source of truth for cleaning.**
- `def run_analysis_job(app, session_id, goal, llm_opts, chain_process)`: **worker**, waits for the profile, then `analyzing` -> `analyze_done` -> chains cleaning.
- `def run_background_process(app, session_id, api_key, llm_opts)`: **worker**, `processing` -> `done`; cleans, writes the Excel file, builds charts.
- Internals: `_duplicate_column_map`, `_impute`, `_analysis_summary_message`, `_stringify`.
- Constants: `IDENTIFIER_HINTS`, `PII_HINTS`, `NOISE_HINTS`, `RECOMMENDATION_PROMPT`.

### `services/chart_service.py`
- `def generate_auto_charts(df, goal, max_charts)`: deterministic planner (distribution, breakdown, target relationship, scatter, trend, correlations).
- `def generate_ai_charts(llm, df, goal, profile, max_charts)` -> `(specs, source)`; AI plan validated, falls back to auto.
- `def validate_chart_specs(specs, df, max_charts)`: drops unknown columns, bad types and duplicates.
- `def build_chart_payload(df, specs)` -> Chart.js-ready dicts.
- `def render_chart_images(df, specs, output_dir, prefix, font_name)` -> `[(png_path, description)]` for the PDF.
- `def guess_target_column(df, goal)`: verb-window parsing, stops at "from"/"using"/... so features do not beat the target.
- Internals: `_numeric_columns`, `_categorical_columns`, `_datetime_columns`, `_histogram_bins`, `_top_correlations`.
- Constants: `CHART_TYPES`, `PALETTE`, `MAX_CHARTS`, `TARGET_VERBS`, `FEATURE_PREPOSITIONS`, `CHART_PROMPT`.

### `utils/job_tracker.py`
- Status constants: `STATUS_IDLE`, `STATUS_PROFILING`, `STATUS_PROFILE_READY`, `STATUS_ANALYZING`, `STATUS_ANALYZE_DONE`, `STATUS_PROCESSING`, `STATUS_DONE`, `STATUS_ERROR`.
- `def _set_job_state(session_id, status, result, error, progress, progress_msg, phase)`.
- `def _update_job_progress(session_id, progress, progress_msg)`.
- `def _get_job_state(session_id)` -> state dict (`idle` for unknown sessions).
- `def reset_job(session_id)`: forget state (delete / fresh run).
- `def clear_profile_ready` / `mark_profile_ready` / `wait_for_profile(session_id, timeout, poll_interval)` / `is_profile_ready`: the analysis/profiling handshake. `wait_for_profile` also re-checks the disk mirror between waits, so it works across processes.
- Disk mirror: `_job_path`, `_write_job_file` (atomic replace), `_read_job_file`. State lands in `<session>.job.json`.

### `utils/session_manager.py`
- `class CustomJSONEncoder`: pandas Timestamps, numpy scalars and arrays.
- `def load_session(session_id)` / `def save_session(session_data)` (atomic write-then-rename).
- `def get_session_folder()`: prefers `current_app.config`, falls back to `config`.
- `def iter_session_files(session_folder)`: yields real session records, skipping `.job.json` mirrors.
- `def purge_old_sessions(session_folder, upload_folder, output_folder, retention_days, max_sessions)`: retention sweep; removes the record plus its upload, cleaned file, chart PNGs, PDF and job mirror.

### `utils/helpers.py`
- `def allowed_file(filename)`.
- `def parse_json_response(text)`: three strategies - parse as-is, strip a markdown fence, then extract the outermost balanced `{...}`. Raises `ValueError` if none work. Needed because only OpenAI-compatible providers honour `response_format` reliably.
- `def _strip_code_fence(text)` / `def _outermost_json_object(text)`: string-aware brace scanner.

### `utils/fonts.py`
- `FONT_SOURCES`, `DOWNLOAD_TIMEOUT`.
- `def download_lora_fonts()`: fetch + register; degrades to Helvetica.

### `components/routes.py`

**Operations** (defined in `app.py`, not the Blueprint)
- `GET /api/health` - liveness; auth-exempt.
- `GET /api/ready` - storage writability + resolved provider; auth-exempt; `503` when degraded.

**Provider configuration**
- `GET  /api/providers` - registry + server default for the settings UI.
- `POST /api/llm/verify` - round-trip test of a key/model.
- `POST /api/llm/models` - list reachable models.

**Session CRUD**
- `GET    /api/sessions` - session summaries.
- `GET    /api/sessions/<id>` - full record plus the live `job` block.
- `DELETE /api/sessions/<id>` - delete record, upload, cleaned file, PDF, job state.

**Stage 1 - read (no AI)**
- `POST /api/upload` - save, parse, start profiling, return immediately.
- `GET  /api/sessions/<id>/profile` - cached profile; `202` while building.
- `POST /api/sessions/<id>/sheet` - switch Excel sheet and re-profile.

**Stage 2 - analyse (after the goal)**
- `POST /api/analyze` - async by default (`202`); `{"wait": true}` runs inline.

**Stage 3 - clean, plot, poll**
- `GET  /api/sessions/<id>/status` - single poll target for the whole pipeline.
- `POST /api/process` - synchronous clean + charts.
- `POST /api/sessions/<id>/trigger_process` - background re-clean after edits.
- `POST /api/sessions/<id>/charts` - regenerate visualisations.

**Chat**
- `POST /api/sessions/<id>/chat` - non-streaming.
- `POST /api/sessions/<id>/chat/stream` - SSE; events `token`, `schema_updates`, `charts`, `done`.

**Reporting**
- `POST /api/sessions/<id>/pdf` - compile the ReportLab report.
- `GET  /api/sessions/<id>/download_pdf` - stream the PDF.
- `GET  /api/download/<filename>` - stream a cleaned `.xlsx`.

- Helpers: `_spawn`, `_app`, `_schema_context`, `_chat_system_prompt`, `_local_schema_parse`, `_wants_charts`, `_apply_chart_request`, `_extract_block`, `_apply_explicit_charts`, `_analyze_sync`.
- Constants: `SCHEMA_MARKER_START/END`, `CHART_MARKER_START/END`, `CHART_INTENT_WORDS`.

### `static/app.js`
- State: `appState` (`llm`, `providers`, `serverDefault`, `activeSessionId`, `sessionData`, `chartInstances`, `schemaRendered`).
- Settings: `loadLlmConfig` (migrates the legacy `nvidia_api_key`), `saveLlmConfig`, `llmPayload`, `fetchProviders`, `renderProviderOptions`, `detectProviderFromKey`, `syncProviderHint`, `updateApiStatus`, `testLlmConnection`, `loadAvailableModels`.
- Stage 1: `uploadRawDatasetFile`, `beginProfileReadout`, `renderProfileSummary`, `changeActiveSheet`.
- Stage 2/3: `runAiSchemaAnalysis`, `reprocessWithCurrentSchema`, `startStatusPolling`, `pollStatusOnce`, `applyProcessResult`, `showBgProcessingIndicator`.
- Rendering: `renderLoadedSessionUI`, `renderSchemaActionsGrid`, `renderTablePreview`, `renderCharts`, `buildChartConfig`, `renderChatMessages`.
- Safety: `esc` (HTML escaping), `sanitizeAssistantHtml` (tag allowlist), `nextDomId` (unicode-safe ids).
- Transport: `apiFetch` (injects `X-API-Key` when a deployment token is stored), `withToken` (query-param form for `<a download>`).
- Responsive: `initSidebarDrawer`, `setSidebarOpen`, `closeSidebarOnMobile`, `isMobileLayout`, `MOBILE_BREAKPOINT`.
- Chat: `sendChatUserMessage` (SSE reader), `renderChatMarkdown`.
- Export: `compilePdfDiagnosticsReport`.
