# Deployment Guide

Mercury ships production-ready: a WSGI entry point, a container image, health
probes, JSON error handling, security headers, optional token auth, disk-backed
job state and a retention sweeper.

---

## 1. Quick start

### Docker Compose (recommended)

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export LLM_API_KEY=sk-…            # any provider; omit to run offline
docker compose up -d --build
```

App on <http://localhost:5000>, state on the `mercury-data` volume.

### Bare metal / VM

```bash
pip install -r requirements.txt

export ENVIRONMENT=production
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export DATA_DIR=/var/lib/mercury

waitress-serve --host=0.0.0.0 --port=5000 --threads=8 --channel-timeout=300 wsgi:application
```

On Linux, gunicorn works too:

```bash
gunicorn --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:5000 wsgi:application
```

### Platform-as-a-Service

A `Procfile` is included, so Heroku/Railway/Render pick it up automatically.
Set `SECRET_KEY`, `ENVIRONMENT=production` and your `LLM_API_KEY` in the
dashboard, and point `DATA_DIR` at a persistent disk.

---

## 2. ⚠️ One worker, many threads

**Run a single worker process.** Use threads for concurrency.

Mercury's pipeline uses in-process background threads and a per-session
`threading.Event` handshake between the profiling and analysis stages. Job
state is mirrored to `<session>.job.json`, so a status poll landing on another
process still reads the truth — but the *handshake* is in-process. With several
workers, an analysis submitted before profiling completes would fall back to
polling the disk mirror instead of being woken instantly.

Threads are the right lever anyway: the heavy work is pandas and network I/O,
both of which release the GIL.

To scale further, run more **containers** behind a load balancer with sticky
sessions and a shared `DATA_DIR` (NFS/EFS), or move job state to Redis by
reimplementing the four functions in `utils/job_tracker.py`.

---

## 3. Configuration

Everything is environment-driven. See `.env.example` for a copy-paste template.

### Required in production

| Variable | Notes |
|----------|-------|
| `ENVIRONMENT` | Set to `production`. Enables strict cookies and HSTS. |
| `SECRET_KEY` | 64 hex chars. **Startup aborts without it** when `ENVIRONMENT=production`. |

### Storage

| Variable | Default | Notes |
|----------|---------|-------|
| `DATA_DIR` | cwd | One parent for uploads, output and sessions. Mount this. |
| `UPLOAD_FOLDER` / `OUTPUT_FOLDER` / `SESSION_FOLDER` | under `DATA_DIR` | Override individually if needed. |
| `MAX_UPLOAD_MB` | `16` | Raise the reverse proxy's body limit to match. |

### Retention

| Variable | Default | Notes |
|----------|---------|-------|
| `RETENTION_DAYS` | `7` in production, `0` in dev | Sessions older than this are swept at startup. `0` disables. |
| `MAX_SESSIONS` | `0` | Keep only the N newest. `0` disables. |

The sweep removes the session record, its upload, cleaned file, chart PNGs, PDF
and job mirror together, so nothing is orphaned.

### Security

| Variable | Default | Notes |
|----------|---------|-------|
| `MERCURY_API_TOKEN` | unset | When set, every `/api/*` call needs it. See §5. |
| `TRUSTED_PROXY_COUNT` | `1` in production | Number of reverse proxies to trust `X-Forwarded-*` from. `0` to disable. |
| `CORS_ORIGINS` | empty | Comma-separated allowlist. Empty = same-origin only. |
| `FLASK_DEBUG` | `0` in production | **Startup aborts if this is on in production** — the Werkzeug debugger is remote code execution. |

### AI provider

Any provider works and the key prefix is auto-detected. See
[PROVIDERS.md](./PROVIDERS.md).

```ini
LLM_API_KEY=sk-ant-api03-…
# LLM_PROVIDER=anthropic   # optional
# LLM_MODEL=…              # optional
# LLM_BASE_URL=…           # only for custom/self-hosted endpoints
```

Leaving `LLM_API_KEY` unset is valid: Mercury runs on its deterministic offline
engine. Users can still supply their own key in the browser.

---

## 4. Health checks

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GET /api/health` | Liveness. `200` + `{"status": "ok"}`. | never required |
| `GET /api/ready` | Readiness: storage writability + resolved provider. `503` if a directory is unwritable. | never required |

Kubernetes:

```yaml
livenessProbe:
  httpGet: { path: /api/health, port: 5000 }
  initialDelaySeconds: 15
readinessProbe:
  httpGet: { path: /api/ready, port: 5000 }
  periodSeconds: 10
```

---

## 5. Authentication

**Mercury has no user accounts.** Every session is visible to everyone who can
reach the app. Choose one:

1. **Private network / localhost** — the default assumption.
2. **Authenticating reverse proxy** — oauth2-proxy, Cloudflare Access, an
   nginx `auth_request`. Recommended for anything public.
3. **Built-in shared token** — set `MERCURY_API_TOKEN`. Every `/api/*` call
   then needs it, except the health probes:

   ```bash
   curl -H "X-API-Key: $MERCURY_API_TOKEN" https://mercury.example.com/api/sessions
   ```

   The browser UI prompts for it under **AI Provider & Model → Server access
   token** and stores it locally. Download links use `?token=…` because an
   `<a download>` cannot set a header — that value appears in proxy logs, so
   prefer option 2 when it matters.

---

## 6. Reverse proxy

```nginx
server {
    listen 443 ssl http2;
    server_name mercury.example.com;

    client_max_body_size 16m;          # must match MAX_UPLOAD_MB

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # The chat endpoint streams Server-Sent Events.
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

`proxy_buffering off` matters: with buffering on, nginx holds the SSE stream and
chat appears frozen. Analysis of a large dataset can exceed the default 60s
read timeout, hence `300s`.

---

## 7. Sizing

- **Memory:** roughly 6-10× the dataset size while pandas is working, plus
  ~150 MB baseline. A 16 MB upload wants ~512 MB; 1 GB is comfortable.
- **CPU:** profiling and cleaning are single-threaded per session. 2 vCPU
  handles several concurrent users.
- **Disk:** each session keeps its upload, a cleaned `.xlsx`, up to 6 PNGs and
  a PDF — budget ~3× the upload size, and set `RETENTION_DAYS`.
- **Timeouts:** 300s. A goal submission runs analysis, cleaning and plotting;
  a slow provider can take a minute on its own.

---

## 8. Pre-flight checklist

- [ ] `ENVIRONMENT=production` and a real `SECRET_KEY` (startup enforces both)
- [ ] `FLASK_DEBUG` unset or `0` (startup enforces this)
- [ ] `DATA_DIR` on a persistent, writable volume
- [ ] `RETENTION_DAYS` set so disk does not fill
- [ ] Exactly **one** worker process, several threads
- [ ] TLS terminated; `TRUSTED_PROXY_COUNT` matches your proxy depth
- [ ] `client_max_body_size` ≥ `MAX_UPLOAD_MB`; `proxy_buffering off`
- [ ] Auth decided: private network, auth proxy, or `MERCURY_API_TOKEN`
- [ ] `/api/health` and `/api/ready` wired to your orchestrator
- [ ] `.env` is **not** in the image or in git
- [ ] `pytest tests/ -q` green (73 tests, fully offline)

---

## 9. Verifying a deployment

```bash
BASE=https://mercury.example.com

curl -s $BASE/api/health                       # {"status":"ok",...}
curl -s $BASE/api/ready                        # storage all true
curl -sI $BASE/api/health | grep -i x-frame    # security headers present

# Full pipeline, offline engine, no provider key needed
SID=$(curl -s -F "file=@test_dirty_data.xlsx" $BASE/api/upload | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
curl -s $BASE/api/sessions/$SID/status         # -> profile_ready, with no goal given
curl -s -X POST $BASE/api/analyze -H 'Content-Type: application/json' \
     -d "{\"session_id\":\"$SID\",\"goal\":\"test\",\"api_key\":\"MOCK\"}"
sleep 10
curl -s $BASE/api/sessions/$SID/status         # -> done, charts populated
```

---

## 10. Troubleshooting

| Symptom | Cause |
|---------|-------|
| Startup aborts: "Refusing to start" | `SECRET_KEY` missing, or debug on, in production. Read the logged reason. |
| Status stuck on `profiling` | More than one worker process. Use `--workers 1 --threads N`. |
| Chat never streams | Proxy buffering. Set `proxy_buffering off`. |
| Upload returns 413 | `MAX_UPLOAD_MB` or the proxy's `client_max_body_size` is too small. |
| Analysis times out | Proxy read timeout below 300s. |
| Disk filling | `RETENTION_DAYS=0`. Set a value. |
| PDF uses Helvetica, not Lora | Font download failed at build time; cosmetic only. |
| Everything falls back to offline recommendations | Key rejected. Check `POST /api/llm/verify`. |
