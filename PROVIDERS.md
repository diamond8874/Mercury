# AI Providers & Models

Mercury is **not tied to any vendor**. Paste a key from any supported provider
and it works; point it at a custom base URL and anything OpenAI-compatible
works, including models running on your own machine.

---

## 1. How a key becomes a working client

`services/llm_provider.py` resolves four settings independently. For each one
the first non-empty source wins:

```
explicit request value   →   environment variable   →   provider registry default
```

| Setting | Request field | Environment | Fallback |
|---------|---------------|-------------|----------|
| API key | `api_key` | `LLM_API_KEY`, then the provider's own var | none → offline mode |
| Provider | `provider` | `LLM_PROVIDER` | auto-detected from the key prefix |
| Model | `model` | `LLM_MODEL` | the provider's `default_model` |
| Base URL | `base_url` | `LLM_BASE_URL` | the provider's registry URL |

Because nothing is hardcoded at the call sites, switching from NVIDIA to
Anthropic is a settings change, not a code change.

---

## 2. Supported providers

Auto-detection reads the key prefix. Providers without a distinctive prefix
just need to be picked from the dropdown (or set via `LLM_PROVIDER`).

| Provider | Key prefix | Default model | Transport |
|----------|------------|---------------|-----------|
| OpenAI | `sk-proj-`, `sk-svcacct-`, `sk-` | `gpt-4o-mini` | openai |
| Anthropic (Claude) | `sk-ant-` | `claude-sonnet-4-5` | anthropic |
| NVIDIA NIM | `nvapi-` | `z-ai/glm-5.2` | openai |
| Google Gemini | `AIza` | `gemini-2.5-flash` | openai¹ |
| Groq | `gsk_` | `llama-3.3-70b-versatile` | openai |
| OpenRouter | `sk-or-v1-`, `sk-or-` | `openai/gpt-4o-mini` | openai |
| xAI (Grok) | `xai-` | `grok-4` | openai |
| Perplexity | `pplx-` | `sonar` | openai |
| Cerebras | `csk-` | `llama-3.3-70b` | openai |
| Fireworks AI | `fw_` | `llama-v3p3-70b-instruct` | openai |
| DeepSeek | *(pick manually)* | `deepseek-chat` | openai |
| Mistral AI | *(pick manually)* | `mistral-large-latest` | openai |
| Together AI | *(pick manually)* | `Llama-3.3-70B-Instruct-Turbo` | openai |
| Cohere | *(pick manually)* | `command-r-plus` | openai |
| Ollama (local) | *(no key needed)* | `llama3.1` | openai |
| LM Studio (local) | *(no key needed)* | `local-model` | openai |
| Custom endpoint | *(anything)* | *(you supply)* | openai |

¹ Gemini is reached through Google's OpenAI-compatibility layer at
`https://generativelanguage.googleapis.com/v1beta/openai`.

### Two transports, everything else shared

* **`openai`** — the OpenAI SDK pointed at a per-provider `base_url`. This
  covers every row above except Anthropic.
* **`anthropic`** — Anthropic's native `/v1/messages` API, implemented over
  stdlib `urllib`. System messages are hoisted to the top-level `system` field,
  consecutive same-role turns are merged, and SSE `content_block_delta` events
  are normalised into the same token stream the rest of the app expects.
  **No extra dependency is required.**

---

## 3. Setting it up

### From the UI (per browser)

Sidebar → **AI Provider & Model**:

1. Paste your key — the provider name appears under the dropdown as it is detected.
2. Optionally pick a provider explicitly, or type a model id.
3. **Load** fetches the model list from providers that expose one.
4. **Test connection** round-trips a one-word prompt and reports the latency.
5. **Save Settings** — stored in `localStorage` under `mercury_llm_config` and
   sent with each request. An older `nvidia_api_key` value is migrated
   automatically on first load.

### From the environment (per server)

```ini
# .env — generic form, provider auto-detected
LLM_API_KEY=sk-ant-api03-…
```

Anything the browser does not send falls back to these values, so a deployment
can ship a server key and let users override it individually.

---

## 4. Recipes

**Anthropic**
```ini
LLM_API_KEY=sk-ant-api03-…
LLM_MODEL=claude-sonnet-4-5     # optional
```

**Google Gemini**
```ini
LLM_API_KEY=AIzaSy…
LLM_MODEL=gemini-2.5-pro        # optional
```

**Groq (fast and free-tier friendly)**
```ini
LLM_API_KEY=gsk_…
```

**Local Ollama — no key, no cloud, no cost**
```bash
ollama pull llama3.1
ollama serve
```
```ini
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
```

**Any other OpenAI-compatible server** (vLLM, LocalAI, llama.cpp, LiteLLM,
a corporate gateway):
```ini
LLM_PROVIDER=custom
LLM_BASE_URL=https://my-gateway.internal/v1
LLM_MODEL=my-deployed-model
LLM_API_KEY=whatever-the-gateway-wants
```

**Fully offline, no provider at all**
```ini
LLM_API_KEY=MOCK
```
Recommendations come from the deterministic rule engine and charts from the
statistical planner. This is also what the test-suite uses.

---

## 5. Resilience

Providers differ in which optional parameters they accept, so `LLMClient` uses
a degradation ladder rather than failing on an unsupported flag:

```
{response_format, temperature, top_p, max_tokens}
  → {temperature, top_p, max_tokens}
    → {max_tokens}
      → {}                                 (bare request)
```

Streaming degrades the same way, ending in a single non-streamed chunk if the
provider refuses to stream at all.

Above that, the **application** degrades too:

| Failure | Behaviour |
|---------|-----------|
| No key configured | Offline rule engine; the UI shows "offline mode". |
| Key rejected / provider down | Offline engine; a `warning` explains why. |
| Model returns unparseable JSON | Offline engine for that step. |
| Model omits some columns | Missing columns filled in by the offline engine. |
| Model invents a column name | That chart or update is dropped by validation. |

A dead API key costs you AI-quality suggestions, never your analysis.

---

## 6. Adding a provider

Append one entry to `PROVIDERS` in `services/llm_provider.py`:

```python
"myvendor": {
    "label": "My Vendor",
    "base_url": "https://api.myvendor.com/v1",
    "default_model": "mv-large",
    "key_prefixes": ["mv-"],          # enables auto-detection
    "env_keys": ["MYVENDOR_API_KEY"],
    "transport": "openai",            # or "anthropic"
    "requires_key": True,
    "models_path": "/models",         # None if unsupported
    "docs": "https://myvendor.com/keys",
},
```

`GET /api/providers` serves the registry to the browser, so the settings
dropdown, auto-detection and the model loader all pick it up with **no
front-end change**.

---

## 7. Security notes

* Keys are sent per request and are never written to session JSON. Only
  `provider`, `model`, `base_url` and a boolean `has_key` are persisted.
* `LLMConfig.public_dict()` is the only shape returned to the browser and it
  deliberately omits the key.
* Browser-side keys live in `localStorage`, which any script on the origin can
  read. On a shared or public deployment, prefer a server-side `.env` key.
* **Never commit a real key.** An earlier revision of this repository had one
  hardcoded in `services/ai_service.py`; it has been removed, but anything ever
  committed must be treated as leaked and rotated at the provider.
