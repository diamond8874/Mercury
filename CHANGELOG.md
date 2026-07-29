# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
