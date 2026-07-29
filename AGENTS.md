# Agent Governance & Operating Rules

## Persona & Standards
- You are a Meta-Architect Agent (or acting on behalf of one).
- Prioritize minimal file modifications unless specifically instructed to refactor.
- When generating or modifying code, preserve existing logic and docstrings where unaffected.

## Token Optimization Protocol
- Agents **MUST** read `KNOWLEDGE_GRAPH.md` before loading raw code files to identify exact targets.
- Do not perform broad, repository-wide file reads if the specific module/function is already indexed in the Knowledge Graph. Use narrow scope reads if possible.
- For API behaviour, read `API.md` rather than `components/routes.py`.
- For provider/model behaviour, read `PROVIDERS.md` rather than `services/llm_provider.py`.
- For configuration and hosting, read `DEPLOYMENT.md` rather than `config.py`/`app.py`.

## Knowledge Graph & Log Maintenance Rules
- **Pre-Task Check:** Agents MUST consult `KNOWLEDGE_GRAPH.md` first to locate relevant code blocks instead of performing broad file reads.
- **Post-Task Sync:** Whenever an agent adds, edits, or deletes code in future tasks, it MUST update `KNOWLEDGE_GRAPH.md` to reflect structural changes in the same pull request/commit.
- **API Sync:** If a route is added, removed, or its request/response shape changes, `API.md` MUST be updated in the same commit.
- **Provider Sync:** If `PROVIDERS` in `services/llm_provider.py` gains or loses an entry, `PROVIDERS.md` MUST be updated in the same commit.
- **Log Sync:** Whenever code changes occur, agents MUST append entries to both `CHANGELOG.md` (user-facing summary) and `COMMIT_LOG.md` (agent-facing technical summary).

## Architectural Invariants
These are the rules the current design depends on. Breaking one is a regression,
not a refactor.

1. **No AI call before the user states a goal.** `/api/upload` reads and profiles
   only. Anything that contacts a model belongs in `run_analysis_job` or later.
2. **No hardcoded vendor, model id or base URL** outside the `PROVIDERS` registry
   in `services/llm_provider.py`. Connection settings arrive per request and
   resolve explicit → environment → registry default.
3. **Every AI step needs a deterministic fallback.** A missing key, a dead
   provider or unparseable output must degrade to the offline engine and surface
   a `warning`, never a 500.
4. **`apply_actions` is the only cleaning implementation.** Do not reintroduce a
   parallel copy inside a route.
5. **Model output is untrusted.** Validate column names against the real
   DataFrame (`validate_chart_specs`, the recommendation normaliser) before use.
6. **Dataset-derived strings are untrusted in the DOM.** Column names, sample
   values and filenames go through `esc()`; assistant HTML goes through
   `sanitizeAssistantHtml()`.
7. **Background workers take the real app object**, via
   `current_app._get_current_object()`, and enter `app.app_context()`.
8. **Every API failure is JSON.** Never let Flask render an HTML error page;
   add an `errorhandler` if a new status code becomes reachable.
9. **Config comes from the environment**, via `config.py`. No literals for
   paths, limits or hosts, and `config.validate()` must reject unsafe
   production settings rather than starting anyway.
10. **Nothing is clipped.** Every scroll container needs `min-height: 0` on its
    flex chain and `overflow-y: auto` - `overflow: hidden` on a growing region
    silently traps content. Grid tracks use `minmax(min(Npx, 100%), 1fr)`.
11. **One worker, many threads.** The profiling/analysis handshake is
    in-process; do not add a second worker process without moving job state to
    a shared store.

## Execution Safety Rules
- Do not blindly overwrite `.py` or application source code without verifying the expected behavior.
- Ensure that the execution boundaries defined in tasks are strictly adhered to.
- **Never commit an API key**, in source, tests, or documentation examples. Use
  `.env` (gitignored) or the `MOCK` sentinel.
- Run `pytest tests/ -q` before committing. The suite is fully offline: it needs
  no API key and makes no network calls.
- After a UI change, verify at 360px, 768px, 1024px and 1440px wide, plus a
  short viewport (e.g. 900x420). Nothing may be clipped or unreachable.
