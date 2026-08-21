# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

### Fixed
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
