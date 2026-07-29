# Mercury - AI Data Cleaning Workbench

Mercury is a Flask web application that reads a dataset, profiles it, proposes a
cleaning plan for **your** stated goal, applies it, and plots the result - then
lets you argue with it in chat and export an Excel file and a PDF report.

Two design rules shape everything:

1. **Read first, analyse second.** Uploading a file never triggers an AI call.
   Mercury reads and profiles the data in a background thread while you type
   your goal. Only when you submit that goal does the analysis run - and it then
   continues straight through cleaning and plotting.
2. **No vendor lock-in.** Any API key from any provider is accepted. The
   provider is auto-detected from the key prefix, and any OpenAI-compatible
   endpoint - including a local Ollama or LM Studio server - works too.

## Key Features

- **Data Ingestion** - upload `.csv`, `.xls` or `.xlsx` (max 16 MB, multi-sheet aware).
- **Background Profiling** - dtypes, semantic types, null rates, cardinality,
  distributions, outliers, duplicate rows, correlations and data-quality
  warnings, computed before any model is consulted.
- **Goal-Driven Cleaning** - KEEP / DROP / TRANSFORM recommendations with an
  explanation for every column, editable in a grid.
- **Automatic Visualisation** - the model proposes charts; a deterministic
  statistical planner covers the cases where it cannot. Rendered with Chart.js
  in the browser and Matplotlib in the PDF.
- **Conversational Refinement** - streaming chat that can change the schema
  ("drop Age") or build plots ("show me fee vs churn") and reprocesses in the
  background.
- **Exports** - cleaned Excel plus a Lora-styled PDF diagnostics report.
- **Graceful Degradation** - no key, a bad key or a provider outage all fall
  back to a deterministic offline engine instead of failing.
- **Responsive UI** - one layout from a 360 px phone to a 4K display: an
  off-canvas sidebar on mobile, scrollable panes everywhere, touch-sized
  targets, and `prefers-reduced-motion` and print styles.
- **Deployment Ready** - WSGI entry point, Dockerfile, Compose file, health and
  readiness probes, JSON error handling, security headers, optional token auth,
  disk-backed job state and an automatic retention sweep.

## Getting Started

### Prerequisites
- Python 3.9+
- An API key from any provider (optional - Mercury runs offline without one).

### Installation

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in a key, or leave it blank
python app.py
```

Open <http://127.0.0.1:5000>.

### Configuring the AI provider

Either paste a key into **AI Provider & Model** in the sidebar, or set it in
`.env`:

```ini
# The provider is auto-detected from the key prefix
LLM_API_KEY=sk-ant-api03-…      # or sk-…, nvapi-…, AIza…, gsk_…, sk-or-v1-…

# Optional overrides
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
LLM_BASE_URL=https://api.anthropic.com/v1
```

`LLM_API_KEY=MOCK` runs everything offline with no API calls at all.
Full details, including local-model recipes: **[PROVIDERS.md](./PROVIDERS.md)**.

## How a session flows

```
1. Upload            file saved + parsed, profiling thread starts   (no AI)
2. Read-out          rows, columns, missing %, dtypes, warnings     (no AI)
                     ── you type your goal while this runs ──
3. Analyse           column recommendations for your goal           (AI)
4. Clean             drop / impute / convert / encode               (pandas)
5. Plot              chart plan + Chart.js payloads                 (AI + fallback)
6. Refine            chat edits the schema and re-runs 4 and 5
7. Export            cleaned .xlsx and a PDF diagnostics report
```

Steps 3-5 run in one background job. The browser follows a single poll endpoint;
see the state machine in **[API.md](./API.md)**.

## Deploying

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export LLM_API_KEY=sk-…          # any provider, or omit to run offline
docker compose up -d --build
```

Or without Docker:

```bash
export ENVIRONMENT=production
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
waitress-serve --host=0.0.0.0 --port=5000 --threads=8 wsgi:application
```

**Run one worker process with several threads** - the pipeline uses in-process
background threads. Full guide, including reverse-proxy config, health probes,
retention and auth: **[DEPLOYMENT.md](./DEPLOYMENT.md)**.

## Testing

Run the suite (73 tests, entirely offline - no key or network needed):

```bash
pytest tests/ -q
```

Generate a synthetic dirty dataset to play with:

```bash
python generate_test_data.py
```

This writes `test_dirty_data.xlsx`, which contains an empty column, a constant
column, a duplicated column, a random identifier, PII, a date stored as text and
missing values - one of every problem the cleaner is meant to catch.

## Documentation

| File | Contents |
|------|----------|
| **[API.md](./API.md)** | Every REST/SSE route, request and response shapes, the job state machine, auth, error codes, cURL walkthrough. |
| **[DEPLOYMENT.md](./DEPLOYMENT.md)** | Docker/Compose/PaaS/bare-metal, configuration reference, reverse proxy, health probes, sizing, checklist, troubleshooting. |
| **[PROVIDERS.md](./PROVIDERS.md)** | Supported providers, key detection, model selection, local models, adding a provider. |
| **[ARCHITECTURE.md](./ARCHITECTURE.md)** | System overview, module responsibilities, threading model, directory map. |
| **[KNOWLEDGE_GRAPH.md](./KNOWLEDGE_GRAPH.md)** | Structural index of every module, function and route. Read this before opening source files. |
| **[AGENTS.md](./AGENTS.md)** | Governance and execution rules for contributing agents. |
| **[COMMIT.md](./COMMIT.md)** | Conventional Commits and branch naming. |
| **[CHANGELOG.md](./CHANGELOG.md)** / **[COMMIT_LOG.md](./COMMIT_LOG.md)** | Mandatory change tracking logs. |

## Security

API keys are sent per request and are never written to session files - only the
provider name, model id and a `has_key` boolean are stored.

> **A previous revision hardcoded a live NVIDIA API key in
> `services/ai_service.py`.** It has been removed, but it remains in this
> repository's git history. If that key was ever real, revoke it at
> <https://build.nvidia.com/>.
