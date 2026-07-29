# System Overview & Architecture

## Architecture

Mercury is a Flask application with a threaded background pipeline and a
provider-agnostic AI layer.

- **Frontend:** vanilla HTML/CSS/JS in `static/`, Chart.js for visualisation.
- **Backend:** Flask, all routes on one Blueprint (`components/routes.py`).
- **Data Processing:** pandas + numpy.
- **AI Integration:** a provider registry (`services/llm_provider.py`) that
  turns any key into a client. No vendor, model id or base URL is hardcoded
  anywhere else in the codebase.
- **Visualisation:** Chart.js payloads for the browser, Matplotlib PNGs for the PDF.
- **Reporting:** ReportLab.
- **Background Jobs:** `threading` plus a thread-safe state machine
  (`utils/job_tracker.py`).

## The pipeline

The central design decision: **reading the data and analysing it are separate
stages, with the user's input in between.**

```
  POST /api/upload
        │ save + parse (fast) ────────────────────────► 200 returned immediately
        └─► thread: run_background_profile
                 status: profiling ──► profile_ready
                 (dtypes, nulls, cardinality, correlations, warnings)
                 NO model is contacted in this stage

        ⋯ the user reads the read-out card and types a goal ⋯

  POST /api/analyze  (202 Accepted)
        └─► thread: run_analysis_job
                 wait_for_profile()          ← handshake, never a race
                 status: analyzing ──► analyze_done
                 generate_recommendations()  ← AI, with offline fallback
                 └─► run_background_process
                          status: processing ──► done
                          apply_actions()          clean / impute / convert
                          generate_ai_charts()     chart plan + fallback
                          build_chart_payload()    Chart.js data
```

`GET /api/sessions/<id>/status` is the single poll target for all of it. Full
state table in [API.md](./API.md).

### Why the handshake matters

A user can submit their goal a millisecond after the upload response lands, well
before profiling has finished. `run_analysis_job` blocks on a per-session
`threading.Event` (`wait_for_profile`) rather than assuming the profile exists,
so early submission is correct instead of racy.

### Degradation strategy

Every AI step has a deterministic counterpart, and failure falls through to it
rather than aborting:

| AI step | Fallback |
|---------|----------|
| `generate_recommendations` | `generate_mock_recommendations` (statistical + name heuristics) |
| `generate_ai_charts` | `generate_auto_charts` (dtype/correlation-driven planner) |
| chat schema updates | `_local_schema_parse` (keyword rule engine) |

## Module responsibilities

| Module | Responsibility |
|--------|----------------|
| `app.py` | Boot the Flask app, apply config, register the Blueprint and PDF fonts. |
| `config.py` | Folder paths, upload limits, LLM env variables, tuning knobs. |
| `components/routes.py` | Every REST + SSE endpoint. Thin: parses requests, spawns workers, formats responses. |
| `services/llm_provider.py` | Provider registry, key detection, config resolution, the `LLMClient` (openai + anthropic transports), model listing, verification. |
| `services/ai_service.py` | Backwards-compatible re-export shim over `llm_provider`. |
| `services/profile_service.py` | Dataset reading, semantic typing, per-column statistics, correlations, warnings, the profiling worker. |
| `services/data_service.py` | Recommendation engines (AI + offline), `apply_actions` cleaning, the analysis and processing workers. |
| `services/chart_service.py` | Chart planning (AI + statistical), spec validation, Chart.js payloads, Matplotlib rendering. |
| `utils/job_tracker.py` | Thread-safe job state machine and the profile-ready handshake. |
| `utils/session_manager.py` | Session JSON load/save with a pandas/numpy-aware encoder. |
| `utils/helpers.py` | Extension validation, JSON extraction from model output. |
| `utils/fonts.py` | Download + register the Lora fonts for the PDF. |
| `wsgi.py` | Production entry point (`wsgi:application`). |

### Single source of truth for cleaning

`services/data_service.apply_actions` is the only place cleaning logic lives.
Both the synchronous `/api/process` route and the background worker call it, so
the two paths cannot drift apart.

## Deployment shape

`app.py` exposes `create_app()`; `wsgi.py` builds `application` for a real WSGI
server. `config.py` reads everything from the environment and `config.validate()`
refuses to boot a production process with no `SECRET_KEY` or with the Werkzeug
debugger enabled.

The app layer adds what a hosted service needs:

- `GET /api/health` (liveness) and `GET /api/ready` (storage writability plus
  the resolved provider), both exempt from auth.
- JSON error handlers for 401/404/405/413/500, so the API contract holds even
  for errors Flask would normally render as HTML.
- Security headers on every response, HSTS in production.
- `ProxyFix` when `TRUSTED_PROXY_COUNT > 0`, so `X-Forwarded-*` is honoured
  behind a reverse proxy and ignored when nothing sets it.
- An optional shared-secret gate (`MERCURY_API_TOKEN`) compared in constant time.
- A retention sweep at startup that removes expired sessions together with
  their uploads, cleaned files, chart PNGs, PDFs and job mirrors.

See [DEPLOYMENT.md](./DEPLOYMENT.md).

## Threading model

- Workers are daemon threads holding a real app object (never the request
  proxy), obtained via `current_app._get_current_object()` and entered with
  `app.app_context()`.
- Job state lives in a module-level dict behind a `threading.Lock`, mirrored
  atomically to `<session>.job.json`. Reads fall back to the file, so a status
  poll that lands on another process still sees the truth, and state survives a
  restart.
- The profiling/analysis handshake is still in-process, so **run one worker
  process with several threads**. `wait_for_profile` degrades to polling the
  disk mirror rather than deadlocking if that rule is broken. Scale with more
  containers, or move job state to Redis by reimplementing the four functions in
  `utils/job_tracker.py`.
- Session data is the durable record; job state is a transient view. Results are
  also written to `session["bg_result"]` so reloading a session restores the
  full dashboard.

## Frontend layout model

The UI is a fixed-height flex shell whose regions scroll independently. Two
rules keep it working at every size:

1. **Every scroll container carries `min-height: 0`** on its whole flex chain.
   Without it a flex child refuses to shrink below its content, and
   `overflow-y: auto` never engages.
2. **A growing region never uses `overflow: hidden`.** That silently traps
   content with no scrollbar, which is exactly how the upload/goal screen used
   to become unusable on short viewports.

Breakpoints: 1440 / 1200 / 1024 / 820 / 640 / 420, plus short-viewport,
coarse-pointer, reduced-motion and print. At ≤1024px the sidebar becomes an
off-canvas drawer (`.sidebar-open` on `#app-container`, with a backdrop and a
body scroll lock) and the chat/workspace split stacks into one scrolling column.
Grid tracks use `minmax(min(Npx, 100%), 1fr)` so they shrink instead of
overflowing, and the tab strip scrolls horizontally rather than wrapping.

## Directory Map

- `/` - project root.
  - `app.py` - Flask entry point.
  - `config.py` - configuration and environment loading.
  - `generate_test_data.py` - synthetic dirty dataset generator.
  - `wsgi.py` - production WSGI entry point.
  - `Dockerfile`, `docker-compose.yml`, `Procfile`, `.dockerignore` - packaging.
  - `requirements.txt`, `.env.example` - dependencies and configuration template.
- `components/` - `routes.py`, the API Blueprint.
- `services/` - `llm_provider.py`, `ai_service.py`, `profile_service.py`,
  `data_service.py`, `chart_service.py`.
- `utils/` - `job_tracker.py`, `session_manager.py`, `helpers.py`, `fonts.py`.
- `static/` - `index.html`, `app.js`, `style.css`.
- `tests/` - `test_app.py`, the offline integration suite.
- `uploads/` - raw uploaded files.
- `output_data/` - cleaned `.xlsx`, chart PNGs, PDF reports.
- `sessions/` - one JSON file per session.
- `fonts/` - Lora TTFs for PDF rendering.
