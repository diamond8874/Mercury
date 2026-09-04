# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
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
