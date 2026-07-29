# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added - Deployment readiness
- `wsgi.py` production entry point plus an `app.create_app()` factory.
- `Dockerfile` (non-root, healthcheck, `/data` volume), `docker-compose.yml`,
  `Procfile` and `.dockerignore`.
- `GET /api/health` (liveness) and `GET /api/ready` (storage writability +
  resolved provider), both exempt from authentication.
- Optional shared-secret auth: setting `MERCURY_API_TOKEN` requires
  `X-API-Key` / `Authorization: Bearer` / `?token=` on every `/api/*` route
  except the probes. Compared in constant time.
- Security headers on every response (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, HSTS in production), a `CORS_ORIGINS`
  allowlist, and `ProxyFix` gated behind `TRUSTED_PROXY_COUNT`.
- Environment-driven configuration: `ENVIRONMENT`, `SECRET_KEY`, `DATA_DIR`,
  `MAX_UPLOAD_MB`, `RETENTION_DAYS`, `MAX_SESSIONS`, `LOG_LEVEL`, `FLASK_*`.
- `config.validate()` aborts startup when a production process has no
  `SECRET_KEY` or has the Werkzeug debugger enabled.
- Retention sweep (`purge_old_sessions`) that removes expired sessions together
  with their uploads, cleaned files, chart PNGs, PDFs and job mirrors.
- `DEPLOYMENT.md`: Docker/Compose/PaaS/bare-metal, configuration reference,
  nginx config, health probes, sizing, pre-flight checklist, troubleshooting.

### Added - Responsive UI
- Full responsive layer: breakpoints at 1440/1200/1024/820/640/420 plus
  short-viewport, coarse-pointer, `prefers-reduced-motion` and print styles.
  The stylesheet previously had a single 1024px media query.
- Off-canvas sidebar drawer below 1024px, with a hamburger toggle, backdrop,
  body scroll lock, Escape-to-close and auto-close on session selection.
- `viewport-fit=cover` plus `env(safe-area-inset-*)` padding for notched phones.

### Fixed - Layout
- **Step 1 was clipped with no scrollbar.** `.step-section` used
  `overflow: hidden`, so on any short viewport the upload, read-out and goal
  cards were cut off and the "Start AI Analysis" button was unreachable. It now
  scrolls. (Measured: 670px of content in a 274px box at 900x420.)
- **The settings modal could not be scrolled or dismissed** on short screens.
  It now has `max-height: min(88dvh, 900px)` with a scrolling body.
- `.split-layout` hardcoded `height: calc(100vh - 120px)`, which overflowed
  whenever the header wrapped. It now sizes from its flex parent.
- Added `min-height: 0` / `min-width: 0` across the flex chain; without it a
  flex child never shrinks below its content and `overflow-y: auto` is inert.
- Grid tracks changed to `minmax(min(Npx, 100%), 1fr)` so schema cards and
  charts shrink instead of forcing horizontal page scroll.
- The tab strip scrolls horizontally on narrow screens instead of overflowing.
- Long column names, goals and model ids now wrap (`overflow-wrap: anywhere`)
  rather than pushing the layout sideways.
- `100dvh` alongside `100vh` so mobile browser chrome cannot clip the last row.

### Fixed - Correctness
- `parse_json_response` now recovers JSON from markdown fences, leading prose
  and trailing commentary using a string-aware brace scanner. Only
  OpenAI-compatible providers honour `response_format` reliably, so strict
  parsing was pushing every other provider into the offline fallback.
- All API errors are JSON, including 401/404/405/413/500, which Flask
  previously rendered as HTML pages.
- `app.run()` no longer defaults to `debug=True` on `0.0.0.0`; the Werkzeug
  debugger is remote code execution. Debug now binds loopback and is refused
  outright in production.
- Session writes are atomic (write-then-rename), so a concurrent reader can no
  longer see a half-written file.
- Job state is mirrored to `<session>.job.json`, so status survives a restart
  and stays readable if a poll lands on another worker. `wait_for_profile`
  re-checks that mirror instead of relying only on an in-process event.
- `GET /api/sessions` no longer lists `.job.json` mirrors as sessions.
- `DELETE /api/sessions/<id>` now also removes the generated PDF and job mirror.
- `__pycache__/` and `desktop.ini` untracked; `.gitignore` rewritten to cover
  runtime data, test artifacts and `.env`.

### Security
- **Removed a hardcoded live NVIDIA API key** from `services/ai_service.py`.
  The key is still present in this repository's git history and must be treated
  as leaked - revoke it at the provider.
- Fixed stored XSS in the schema grid and chat panel. Column names, sample
  values and session names are now HTML-escaped; assistant messages pass through
  a tag allowlist instead of raw `innerHTML`.
- API keys are no longer persisted in session JSON. Only `provider`, `model`,
  `base_url` and a `has_key` boolean are stored.

### Added
- **Provider-agnostic AI layer** (`services/llm_provider.py`). Any API key from
  any vendor is accepted; the provider is auto-detected from the key prefix.
  17 providers are registered (OpenAI, Anthropic, NVIDIA, Google Gemini, Groq,
  OpenRouter, DeepSeek, Mistral, Together, Fireworks, xAI, Perplexity, Cerebras,
  Cohere, Ollama, LM Studio, custom), plus two transports: OpenAI-compatible and
  Anthropic's native Messages API (over stdlib `urllib`, no new dependency).
- Parameter-degradation ladder so providers that reject `response_format`,
  `temperature` or `top_p` still work, including a non-streaming fallback.
- **Background dataset profiling** (`services/profile_service.py`): semantic
  typing, null rates, cardinality, distributions, outliers, duplicate rows,
  correlations and data-quality warnings. Starts on upload, runs while the user
  types, and consults no model.
- **Visualisation engine** (`services/chart_service.py`): AI chart planning with
  a deterministic statistical fallback, spec validation against the real
  DataFrame, Chart.js payloads and Matplotlib rendering for the PDF.
- New endpoints: `GET /api/providers`, `POST /api/llm/verify`,
  `POST /api/llm/models`, `GET /api/sessions/<id>/profile`,
  `POST /api/sessions/<id>/sheet`, `POST /api/sessions/<id>/charts`.
- Explicit pipeline state machine in `utils/job_tracker.py`
  (`idle → profiling → profile_ready → analyzing → analyze_done → processing →
  done | error`) plus a `wait_for_profile` handshake.
- Dataset read-out card in the UI: live rows/columns/missing/duplicates,
  detected column types and quality warnings, filled in while the user types.
- Provider settings modal with auto-detection, model listing and a
  test-connection button.
- Documentation: `API.md` (full route reference), `PROVIDERS.md` (provider and
  model configuration), `.env.example`.
- Test suite grown from 3 to 45 tests, covering provider detection, config
  resolution, the profiling stage, the async pipeline, cleaning primitives,
  chart planning and validation, chat, PDF and error paths.

### Fixed
- **Uploading a dataset no longer triggers an AI analysis.** `/api/upload` now
  reads and profiles the file and returns; the model is only consulted once the
  user submits a goal, which then runs analysis, cleaning and plotting in one
  background job.
- **The analysis loader no longer hangs forever.** `/api/analyze` was fully
  synchronous while the browser polled for `analyzing` / `analyze_done` job
  states that the backend never emitted, so the overlay never closed. Analysis
  is now genuinely asynchronous and emits those states.
- **Charts are generated again.** Both `/api/process` and the background worker
  hardcoded `charts = []` with a "do not generate visualisations" comment, so
  the Visualizations tab was permanently empty and the PDF's figures section was
  always blank. `generate_mock_charts` was imported but never called.
- Submitting a goal before profiling finishes no longer races; the analysis
  worker blocks on the profile handshake.
- The "Process Data" button lived in the step-1 footer, which is hidden once the
  dashboard appears, so it could never be clicked. It is now "Apply & Reprocess"
  in the schema tab header.
- Reloading or reopening a session restored neither stats, preview nor charts,
  and displayed the raw row count as a placeholder. The last completed run is
  now persisted in `session["bg_result"]` and fully restored.
- Date columns stored as text were misclassified as identifiers (and dropped)
  because the uniqueness heuristic ran before date detection.
- An imputation instruction mentioning "the most frequent category" wrongly
  triggered label encoding; encoding now requires an explicit encoding verb.
- `btoa(column_name)` threw on non-Latin-1 column headers, breaking the entire
  schema grid render. Replaced with a counter-based id.
- Histograms of continuous numeric columns used `value_counts()` instead of
  binning, producing one bar per distinct value.
- Target detection picked a feature over the target for goals of the form
  "predict X from Y"; the search window now stops at the feature preposition.
- Fonts are registered at import time, so the PDF uses Lora under a WSGI server
  and not only under `python app.py`. Downloads now have a 10s timeout.
- `/api/analyze` returned a hard error when no key was configured; it now falls
  back to the offline engine with a warning.
- Deleting a session now also removes its generated PDF and clears job state.

### Changed
- Cleaning logic consolidated into `services/data_service.apply_actions`, used
  by both the synchronous route and the background worker, replacing two
  divergent ~80-line copies.
- `services/ai_service.py` is now a thin backwards-compatible shim over the
  provider registry.
- Chat prompts, PDF text and UI copy no longer name a specific vendor; they
  render the active provider and model.
- Requirements relaxed from hard pins to minimum versions, because the pinned
  `pandas`/`Flask` releases have no wheels for Python 3.13+.

## [0.1.0] - 2026-07-29

### Added
- Phase 1 & 2 baseline documentation for Agent Readiness (`AGENTS.md`,
  `ARCHITECTURE.md`, `COMMIT.md`, `CHANGELOG.md`, `COMMIT_LOG.md`,
  `KNOWLEDGE_GRAPH.md`).
- Established the Token Optimization Protocol and Knowledge Graph Maintenance Rules.
- Refactored the monolithic `app.py` into `config.py`, `components/routes.py`,
  `services/` and `utils/` modules with an initial regression test suite.
