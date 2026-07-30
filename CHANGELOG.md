# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Multi-Provider LLM Abstraction (`services/ai_service.py`)**: Built a robust `UnifiedLLMClient` backed by `LiteLLM` that acts as a drop-in replacement for standard OpenAI client. Supports automatic provider detection, custom base URLs, custom API keys, and auto-fallback behavior.
- **Environment Matrix Setup (`.env.example`)**: Added `.env.example` defining environment variables for all major providers (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_BASE_URL`, `LLM_PROVIDER`, `LLM_MODEL`).
- **Unit & Integration Tests**: Expanded `tests/test_app.py` with `test_unified_llm_client_routing` validating auto-routing resolution and client configurations across OpenAI, Anthropic, Gemini, OpenRouter, and Ollama.

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
