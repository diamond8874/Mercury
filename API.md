# Mercury REST API Reference

Base URL: `http://127.0.0.1:5000`
All request and response bodies are JSON unless stated otherwise.

---

## 1. The request lifecycle

Mercury runs a three-stage pipeline. **The stages are deliberately separated so
that uploading a file never triggers an AI analysis.** The dataset is read and
profiled first; the model is only consulted once the user states a goal.

```
POST /api/upload                     ──►  file saved, parsed, profiling thread started
GET  /api/sessions/<id>/status       ──►  "profiling" → "profile_ready"
        (user types their goal while this runs)
POST /api/analyze                    ──►  202 Accepted, analysis thread started
GET  /api/sessions/<id>/status       ──►  "analyzing" → "analyze_done"
                                          → "processing" → "done"
```

### Job status state machine

Every stage reports through the single poll endpoint
`GET /api/sessions/<session_id>/status`.

| `status`        | `phase`   | Meaning |
|-----------------|-----------|---------|
| `idle`          | `null`    | No job has ever run for this session. |
| `profiling`     | `profile` | Reading the file and computing statistics. **No AI call.** |
| `profile_ready` | `profile` | Profile complete. Mercury is waiting for the user's goal. |
| `analyzing`     | `analyze` | Goal received; producing column recommendations. |
| `analyze_done`  | `analyze` | Recommendations saved; cleaning starts next. |
| `processing`    | `process` | Applying actions, writing the clean file, building charts. |
| `done`          | `process` | Everything finished; `result` holds the full payload. |
| `error`         | *stage*   | Something failed; `error` holds the message. |

An analysis submitted before profiling completes is **not** a race: the worker
blocks on an internal handshake (`utils/job_tracker.wait_for_profile`) until the
profile exists.

### Shared LLM fields

Any endpoint that may reach a model accepts these four optional fields in its
body. They are resolved by `services/llm_provider.py` and never persisted as
secrets.

| Field | Type | Description |
|-------|------|-------------|
| `api_key`  | string | Any provider's key. `"MOCK"` forces the offline rule engine. Omit to use the server's environment. |
| `provider` | string | Optional override, e.g. `openai`, `anthropic`, `groq`. Auto-detected from the key prefix when omitted. |
| `model`    | string | Optional model id. Falls back to the provider's default. |
| `base_url` | string | Optional endpoint. Required only for `custom` / self-hosted servers. |

Resolution order per field: **explicit body value → environment variable →
provider registry default**.

---

## 2. Operations endpoints

Both probes are **exempt from authentication** so orchestrators can reach them.

### `GET /api/health`
Liveness. Always cheap, never touches disk or a provider.
```json
{ "status": "ok", "environment": "production" }
```

### `GET /api/ready`
Readiness. `200` when every storage directory is writable, `503` otherwise.
```json
{
  "status": "ready",
  "storage": { "uploads": true, "output_data": true, "sessions": true },
  "llm": { "provider": "groq", "model": "llama-3.3-70b-versatile", "has_key": true },
  "auth_required": false
}
```
`llm` is informational: Mercury runs fine with no key, on its offline engine.

---

## 3. Authentication

By default there is **none** — every session is visible to anyone who can reach
the app. When the server sets `MERCURY_API_TOKEN`, every `/api/*` route except
the two probes requires it, in any of these forms:

```http
X-API-Key: <token>
Authorization: Bearer <token>
GET /api/download/file.xlsx?token=<token>     # for <a download> links only
```

A missing or wrong token returns `401 {"error": "Unauthorized. Supply the X-API-Key header."}`.
The query-parameter form exists because an anchor cannot set headers; it is
visible in proxy logs, so front Mercury with an authenticating proxy when that
matters. See [DEPLOYMENT.md](./DEPLOYMENT.md) §5.

---

## 4. Provider & model configuration

### `GET /api/providers`

Returns the provider catalog used to build the settings UI. Adding a provider
to the registry requires no front-end change.

**Response `200`**
```json
{
  "providers": [
    {
      "id": "anthropic",
      "label": "Anthropic (Claude)",
      "base_url": "https://api.anthropic.com/v1",
      "default_model": "claude-sonnet-4-5",
      "key_prefixes": ["sk-ant-"],
      "env_keys": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
      "transport": "anthropic",
      "requires_key": true,
      "supports_model_listing": true,
      "docs": "https://console.anthropic.com/settings/keys"
    }
  ],
  "server_default": {
    "provider": "openai", "label": "OpenAI", "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1", "transport": "openai",
    "source": "env:OPENAI_API_KEY", "has_key": true
  },
  "notes": "Any OpenAI-compatible endpoint works..."
}
```
`server_default` never contains the key itself, only `has_key`.

### `POST /api/llm/verify`

Round-trips a one-word prompt so the user can confirm a key works.

**Request** — the shared LLM fields.
**Response `200`** when reachable, **`400`** otherwise.
```json
{
  "ok": true,
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "latency_ms": 412,
  "sample": "ready",
  "message": "Connected to Groq using model 'llama-3.3-70b-versatile'."
}
```

### `POST /api/llm/models`

Lists the models a key can reach, when the provider exposes `/models`.
Always returns `200`; a provider that cannot list models returns an empty
array plus an `error` string rather than failing the request.

```json
{ "provider": "openai", "current_model": "gpt-4o-mini", "models": ["gpt-4o", "gpt-4o-mini", "o3"] }
```

---

## 5. Sessions

### `GET /api/sessions`
Summaries of every stored session, newest first.
```json
[{ "session_id": "…", "name": "churn.csv", "original_filename": "churn.csv",
   "goal": "Predict churn", "created_at": "2026-07-29T10:11:12" }]
```

### `GET /api/sessions/<session_id>`
The full session record: `columns`, `profile`, `column_actions`, `chat_history`,
`charts`, `bg_result`, `cleaned_filename`, `pdf_filename`, plus a live `job`
block matching the status endpoint. `404` when unknown.

### `DELETE /api/sessions/<session_id>`
Deletes the session JSON, the upload, the cleaned file and the PDF, and clears
its job state. → `{"success": true}` / `404`.

---

## 6. Stage 1 — upload and read the dataset

### `POST /api/upload`

`multipart/form-data` with a `file` field. Accepts `.csv`, `.xlsx`, `.xls`,
max 16 MB.

Saves the file, parses it for light metadata, creates the session, and **starts
background profiling**. It returns as soon as the file parses — it never calls a
model, because no goal has been stated yet.

**Response `200`**
```json
{
  "session_id": "…", "file_id": "…​.csv", "original_name": "churn.csv",
  "file_type": "csv", "sheets": ["Default"],
  "row_count": 1200, "col_count": 14,
  "columns": [{ "name": "Age", "type": "float64", "null_count": 31, "sample_values": ["25", "34"] }],
  "preview": [{ "Age": "25" }],
  "chat_history": [{ "role": "assistant", "content": "I've loaded …" }],
  "profiling": true,
  "next_step": "Submit a goal to POST /api/analyze to start the AI analysis."
}
```
Errors: `400` (no file / unsupported extension), `500` (unparseable).

### `GET /api/sessions/<session_id>/profile`

The cached profile. Returns **`202`** while profiling is still running.

**Response `200`**
```json
{
  "generated_at": "2026-07-29T10:11:13", "sheet_name": "Default",
  "shape": { "rows": 1200, "cols": 14 },
  "memory_bytes": 284912, "duplicate_rows": 4,
  "missing_cells": 118, "missing_pct": 0.7,
  "columns": [{
    "name": "Age", "type": "float64", "semantic_type": "numeric",
    "null_count": 31, "null_pct": 2.58, "unique_count": 47, "unique_pct": 3.92,
    "is_constant": false, "is_empty": false, "sample_values": [25, 34, 41],
    "stats": { "min": 18, "max": 70, "mean": 41.2, "median": 40, "std": 12.9,
               "skew": 0.11, "zeros": 0, "negatives": 0, "outliers": 3 }
  }],
  "numeric_columns": ["Age", "Fee"],
  "categorical_columns": ["Gender"],
  "datetime_columns": ["Signup_Date"],
  "identifier_columns": ["User_ID"],
  "correlations": [{ "x": "Fee", "y": "Duplicated_Fee", "r": 1.0 }],
  "warnings": ["'Empty_Col' is completely empty."],
  "preview": [{ "Age": 25 }]
}
```

`semantic_type` is one of `numeric`, `categorical`, `boolean`, `datetime`,
`identifier`, `text`, `empty`. Date-like strings are detected **before** the
identifier heuristic, so a unique date column is not written off as an id.

### `POST /api/sessions/<session_id>/sheet`

Switch the active Excel sheet and re-profile it in the background.
```json
{ "sheet_name": "Q3 Data" }        →  { "status": "profiling", "sheet_name": "Q3 Data" }
```
Errors: `400` (unknown sheet), `404`.

---

## 7. Stage 2 — analysis (only after a goal is stated)

### `POST /api/analyze`

**Request**
```json
{
  "session_id": "…",
  "goal": "Predict churn from payment history and demographics",
  "sheet_name": "Default",
  "wait": false,
  "chain_process": true,
  "api_key": "…", "provider": "", "model": "", "base_url": ""
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `goal` | *required* | Free text. Drives recommendations, target detection and chart selection. |
| `wait` | `false` | `true` runs inline and returns recommendations in the body. |
| `chain_process` | `true` | `true` continues automatically into cleaning + plotting. |

**Async response `202`** (the default, used by the browser)
```json
{ "status": "analyzing", "session_id": "…", "goal": "…",
  "poll_url": "/api/sessions/…/status",
  "message": "Analysis started. Poll the status endpoint for progress." }
```

**Sync response `200`** (`"wait": true`)
```json
{
  "recommendations": [{ "column": "User_ID", "action": "drop",
                        "reason": "Near-unique identifier…", "transformation": null }],
  "column_actions": { "User_ID": { "action": "drop", "reason": "…", "transformation": null } },
  "chat_history": [ … ],
  "source": "ai",
  "llm": { "provider": "groq", "model": "llama-3.3-70b-versatile", "has_key": true },
  "warning": "…only present when a provider failed and the offline engine was used"
}
```

`action` ∈ `keep` | `drop` | `transform`. `source` is `"ai"` or `"offline"`.
A provider outage is **never** a hard failure: the deterministic rule engine
takes over and the reason appears in `warning`.

Errors: `400` (missing `session_id`/`goal`), `404` (unknown session or the
upload disappeared), `500` (sync path only).

---

## 8. Stage 3 — cleaning, plotting and status

### `GET /api/sessions/<session_id>/status`

The single poll target for the whole pipeline.
```json
{ "status": "processing", "phase": "process", "progress": 75,
  "progress_msg": "Designing visualisations for the cleaned data...",
  "result": null, "error": null }
```

On `done`, `result` contains:
```json
{
  "download_url": "/api/download/cleaned_<file_id>.xlsx",
  "stats": { "initial_rows": 1200, "initial_cols": 14,
             "final_rows": 1200, "final_cols": 9,
             "dropped_columns": ["User_ID"],
             "transformations_applied": ["Transformed 'Age': …"] },
  "charts": [ /* Chart.js-ready payloads, see below */ ],
  "preview": [ { "Age": 25 } ],
  "chart_source": "ai",
  "cleaned_profile": { "shape": { "rows": 1200, "cols": 9 }, "missing_pct": 0.0, "duplicate_rows": 0 }
}
```

Unknown sessions return `{"status": "idle", …}` rather than a 404, so the
browser can poll safely.

### `POST /api/process`

Synchronous clean + chart build. Mostly for scripts; the UI uses the async path.

**Request** `{ "session_id": "…", "actions": { … }, "sheet_name": "Default", …LLM fields }`
**Response `200`** `{ "success": true, "download_url": "…", "stats": {…}, "charts": [...], "preview": [...], "chat_history": [...] }`
Errors: `400` (missing `session_id`/`actions`), `404`, `500`.

### `POST /api/sessions/<session_id>/trigger_process`

Re-runs cleaning + plotting in the background after manual schema edits.
```json
{ "column_actions": { "Age": { "action": "drop", "reason": "manual", "transformation": null } },
  "sheet_name": "Default", "api_key": "…" }
      →  { "status": "processing", "message": "Background processing started." }
```
`actions` is accepted as an alias for `column_actions`.

### `POST /api/sessions/<session_id>/charts`

Rebuild the visualisations without re-cleaning.

| Field | Description |
|-------|-------------|
| `instruction` | Natural-language steer, e.g. `"plot age against churn"`. |
| `specs` | Explicit chart specs; skips the model entirely. |

**Response `200`** `{ "charts": [...], "specs": [...], "source": "ai" | "auto" | "manual" }`
Errors: `400` (no cleaned dataset yet), `404`.

### Chart payload shape

Every chart returned to the browser is Chart.js-ready:

```json
{ "chart_type": "histogram", "title": "Distribution of Age",
  "description": "How values of 'Age' are spread…",
  "x_axis": "Age", "y_axis": null,
  "labels": ["18 - 23.2", "23.2 - 28.4"], "values": [41, 88] }
```

* `histogram`, `bar`, `pie`, `line`, `box` → `labels` + `values`
* `scatter` → `points: [{ "x": 1.0, "y": 2.0 }]`
* `correlation` → returned as a horizontal `bar` with `orientation: "horizontal"`
  and signed `values`

Specs are validated against the cleaned DataFrame before rendering, so a model
that hallucinates a column name simply loses that one chart.

---

## 9. Chat

### `POST /api/sessions/<session_id>/chat`

Non-streaming. Request `{ "message": "Drop the Age column", …LLM fields }`.

**Response `200`**
```json
{ "message": "Done! I've updated Age.",
  "schema_updates": { "Age": { "action": "drop", "reason": "…", "transformation": null } },
  "column_actions": { … },
  "chat_history": [ … ],
  "llm": { "provider": "openai", "model": "gpt-4o-mini", "has_key": true } }
```
Errors: `400` (missing `message`), `404`.

### `POST /api/sessions/<session_id>/chat/stream`

Server-Sent Events (`text/event-stream`).

| Event | Data |
|-------|------|
| *(default)* | `{"token": "partial text "}` |
| `schema_updates` | `{"schema_updates": {…}, "column_actions": {…}, "trigger_reprocess": true}` |
| `charts` | `{"charts": [ …Chart.js payloads… ]}` |
| `done` | `{"full_message": "the complete assistant reply"}` |

```
data: {"token": "Dropping "}

event: schema_updates
data: {"schema_updates": {"Age": {"action": "drop", …}}, "column_actions": {…}, "trigger_reprocess": true}

event: done
data: {"full_message": "Dropping Age for you."}
```

When `trigger_reprocess` is `true` the server has already started a background
re-clean; the client just resumes polling `/status`. Asking for a plot
("show me a chart of fee vs churn") emits a `charts` event.

Internally the model is asked to append `<<<SCHEMA_UPDATES>>>…<<<END>>>` and
`<<<CHARTS>>>…<<<END_CHARTS>>>` blocks. These are stripped from the visible
stream and never reach the user.

---

## 10. Reporting and downloads

### `POST /api/sessions/<session_id>/pdf`
Renders the saved chart plan with Matplotlib and compiles a ReportLab PDF
(executive summary, before/after metrics, applied rules, descriptive stats,
figures). Accepts the LLM fields so a session with no chart plan can build one.

`200` → `{ "success": true, "pdf_url": "/api/sessions/<id>/download_pdf", "charts_included": 5, "chat_history": [...] }`
Errors: `400` (nothing cleaned yet), `404`, `500` (ReportLab missing).

### `GET /api/sessions/<session_id>/download_pdf`
Streams the PDF as an attachment. `404` if not generated.

### `GET /api/download/<filename>`
Streams a cleaned `.xlsx` from `output_data/`. The filename is passed through
`secure_filename`, so path traversal is not possible.

---

## 11. Errors

Every failure returns `{"error": "human readable message"}` with:

| Code | Meaning |
|------|---------|
| `400` | Missing/invalid fields, unsupported file type, wrong pipeline stage. |
| `401` | `MERCURY_API_TOKEN` is set and the request did not supply it. |
| `404` | Unknown session, or a file that vanished from disk. |
| `405` | Wrong HTTP method for the route. |
| `413` | Upload over `MAX_UPLOAD_MB` (16 MB by default). |
| `500` | Unparseable file, PDF failure, or an unexpected server error. |

All of these are JSON, including the ones Flask would normally render as HTML
(401/404/405/413/500) — app-level handlers convert them.

Provider failures are the deliberate exception: they degrade to the offline
engine and surface as a `warning` field on a `200`, so a dead API key never
costs the user their analysis.

---

## 12. Quick cURL walkthrough

```bash
BASE=http://127.0.0.1:5000

# 1. Upload - reads the file, starts profiling, calls no model
SID=$(curl -s -F "file=@test_dirty_data.xlsx" $BASE/api/upload | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

# 2. Watch the read stage finish (no goal needed yet)
curl -s $BASE/api/sessions/$SID/status
curl -s $BASE/api/sessions/$SID/profile

# 3. Submit the goal - this is what starts the AI work
curl -s -X POST $BASE/api/analyze -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"goal\":\"Predict churn\",\"api_key\":\"$LLM_API_KEY\"}"

# 4. Poll until done, then grab the outputs
curl -s $BASE/api/sessions/$SID/status
curl -s -X POST $BASE/api/sessions/$SID/pdf -H 'Content-Type: application/json' -d '{}'
curl -sO -J $BASE/api/sessions/$SID/download_pdf
```

Swap `api_key` for any provider's key — OpenAI, Anthropic, Gemini, Groq,
OpenRouter, NVIDIA, a local Ollama server — without changing anything else.
See [PROVIDERS.md](./PROVIDERS.md).
