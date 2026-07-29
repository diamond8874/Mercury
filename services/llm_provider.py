"""
Provider-agnostic LLM layer.

Mercury is not tied to any single vendor. This module turns *any* API key
(plus optional model / base URL overrides) into a working chat client.

Two transports cover the whole market:

* ``openai``    – every OpenAI-compatible ``/chat/completions`` endpoint.
                  That is OpenAI, NVIDIA NIM, Google Gemini (OpenAI compat
                  layer), Groq, OpenRouter, DeepSeek, Mistral, Together,
                  Fireworks, xAI, Perplexity, Cerebras, Cohere, Ollama,
                  LM Studio, vLLM, and anything else that speaks the spec.
* ``anthropic`` – Anthropic's native ``/v1/messages`` API, spoken over
                  stdlib ``urllib`` so no extra dependency is required.

Resolution order for every setting (first non-empty wins):

    explicit request argument  ->  environment variable  ->  registry default

Nothing in the rest of the codebase may hardcode a vendor, base URL or
model id: it all comes from here.
"""

import os
import json
import time
import logging
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------
# ``key_prefixes``  – used to auto-detect the provider from the key alone.
# ``requires_key``  – False for local runtimes (Ollama / LM Studio / vLLM).
# ``models_path``   – relative path used to list models, None if unsupported.

PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "key_prefixes": ["sk-proj-", "sk-svcacct-", "sk-"],
        "env_keys": ["OPENAI_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-5",
        "key_prefixes": ["sk-ant-"],
        "env_keys": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        "transport": "anthropic",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "z-ai/glm-5.2",
        "key_prefixes": ["nvapi-"],
        "env_keys": ["NVIDIA_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://build.nvidia.com/",
    },
    "google": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
        "key_prefixes": ["AIza"],
        "env_keys": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "key_prefixes": ["gsk_"],
        "env_keys": ["GROQ_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://console.groq.com/keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
        "key_prefixes": ["sk-or-v1-", "sk-or-"],
        "env_keys": ["OPENROUTER_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://openrouter.ai/keys",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "key_prefixes": [],
        "env_keys": ["DEEPSEEK_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://platform.deepseek.com/api_keys",
    },
    "mistral": {
        "label": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "key_prefixes": [],
        "env_keys": ["MISTRAL_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://console.mistral.ai/api-keys/",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "key_prefixes": [],
        "env_keys": ["TOGETHER_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://api.together.ai/settings/api-keys",
    },
    "fireworks": {
        "label": "Fireworks AI",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "key_prefixes": ["fw_"],
        "env_keys": ["FIREWORKS_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://fireworks.ai/account/api-keys",
    },
    "xai": {
        "label": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-4",
        "key_prefixes": ["xai-"],
        "env_keys": ["XAI_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://console.x.ai/",
    },
    "perplexity": {
        "label": "Perplexity",
        "base_url": "https://api.perplexity.ai",
        "default_model": "sonar",
        "key_prefixes": ["pplx-"],
        "env_keys": ["PERPLEXITY_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": None,
        "docs": "https://www.perplexity.ai/settings/api",
    },
    "cerebras": {
        "label": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "default_model": "llama-3.3-70b",
        "key_prefixes": ["csk-"],
        "env_keys": ["CEREBRAS_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://cloud.cerebras.ai/",
    },
    "cohere": {
        "label": "Cohere",
        "base_url": "https://api.cohere.ai/compatibility/v1",
        "default_model": "command-r-plus",
        "key_prefixes": [],
        "env_keys": ["COHERE_API_KEY"],
        "transport": "openai",
        "requires_key": True,
        "models_path": "/models",
        "docs": "https://dashboard.cohere.com/api-keys",
    },
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1",
        "key_prefixes": [],
        "env_keys": ["OLLAMA_API_KEY"],
        "transport": "openai",
        "requires_key": False,
        "models_path": "/models",
        "docs": "https://ollama.com/",
    },
    "lmstudio": {
        "label": "LM Studio (local)",
        "base_url": "http://localhost:1234/v1",
        "default_model": "local-model",
        "key_prefixes": [],
        "env_keys": [],
        "transport": "openai",
        "requires_key": False,
        "models_path": "/models",
        "docs": "https://lmstudio.ai/",
    },
    "custom": {
        "label": "Custom OpenAI-compatible endpoint",
        "base_url": None,
        "default_model": None,
        "key_prefixes": [],
        "env_keys": [],
        "transport": "openai",
        "requires_key": False,
        "models_path": "/models",
        "docs": "",
    },
}

# Generic env vars that win over per-provider ones.
GENERIC_KEY_ENV = "LLM_API_KEY"
GENERIC_MODEL_ENV = "LLM_MODEL"
GENERIC_BASE_URL_ENV = "LLM_BASE_URL"
GENERIC_PROVIDER_ENV = "LLM_PROVIDER"

MOCK_SENTINEL = "MOCK"

# Longest prefixes first so "sk-ant-" beats "sk-".
_PREFIX_INDEX = sorted(
    ((prefix, pid) for pid, meta in PROVIDERS.items() for prefix in meta["key_prefixes"]),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


class LLMError(Exception):
    """Raised when a provider call fails in a way the caller should surface."""


class LLMConfig:
    """Fully resolved connection settings for one chat call."""

    def __init__(self, provider, label, base_url, model, api_key, transport,
                 source="explicit", requires_key=True):
        self.provider = provider
        self.label = label
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.transport = transport          # openai | anthropic | mock | none
        self.source = source                # where the key came from
        self.requires_key = requires_key

    @property
    def is_mock(self):
        return self.transport == "mock"

    @property
    def is_live(self):
        return self.transport in ("openai", "anthropic")

    def public_dict(self):
        """Safe to hand back to the browser - never includes the key itself."""
        return {
            "provider": self.provider,
            "label": self.label,
            "base_url": self.base_url,
            "model": self.model,
            "transport": self.transport,
            "source": self.source,
            "has_key": bool(self.api_key),
        }

    def __repr__(self):
        return f"<LLMConfig {self.provider}:{self.model} via {self.transport}>"


# ---------------------------------------------------------------------------
# Detection & resolution
# ---------------------------------------------------------------------------

def detect_provider(api_key):
    """Guess the provider id from an API key prefix. Returns None if unknown."""
    if not api_key:
        return None
    key = api_key.strip()
    for prefix, provider_id in _PREFIX_INDEX:
        if key.startswith(prefix):
            return provider_id
    return None


def _env(name):
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _key_from_env(provider_id=None):
    """Return (key, source_label) from the environment, or (None, None)."""
    generic = _env(GENERIC_KEY_ENV)
    if generic:
        return generic, f"env:{GENERIC_KEY_ENV}"

    if provider_id and provider_id in PROVIDERS:
        for env_name in PROVIDERS[provider_id]["env_keys"]:
            value = _env(env_name)
            if value:
                return value, f"env:{env_name}"

    # No provider hint - take the first provider-specific key we can find.
    for pid, meta in PROVIDERS.items():
        for env_name in meta["env_keys"]:
            value = _env(env_name)
            if value:
                return value, f"env:{env_name}"
    return None, None


def resolve_llm_config(api_key=None, provider=None, model=None, base_url=None):
    """
    Turn whatever the caller supplied into a usable :class:`LLMConfig`.

    Every argument is optional. Passing ``api_key="MOCK"`` forces the
    offline deterministic engine, which is what the test-suite uses.
    """
    api_key = (api_key or "").strip() or None
    provider = (provider or "").strip() or None
    model = (model or "").strip() or None
    base_url = (base_url or "").strip() or None

    if api_key and api_key.upper() == MOCK_SENTINEL:
        return LLMConfig(
            provider="mock", label="Offline rule engine", base_url=None,
            model="mock", api_key=MOCK_SENTINEL, transport="mock",
            source="explicit", requires_key=False,
        )

    source = "explicit"
    if not api_key:
        api_key, source = _key_from_env(provider)
        source = source or "none"

    if not provider:
        provider = _env(GENERIC_PROVIDER_ENV)
    if not provider:
        provider = detect_provider(api_key)
    if not provider:
        # An explicit base URL means "some OpenAI-compatible server".
        provider = "custom" if (base_url or _env(GENERIC_BASE_URL_ENV)) else None

    meta = PROVIDERS.get(provider) if provider else None
    if meta is None:
        # Unknown provider id, or no key at all: fall back to a generic
        # OpenAI-compatible profile so an explicit base_url still works.
        meta = PROVIDERS["custom"]
        provider = provider or "custom"
        label = f"Custom ({provider})" if provider != "custom" else meta["label"]
    else:
        label = meta["label"]

    base_url = base_url or _env(GENERIC_BASE_URL_ENV) or meta["base_url"]
    model = model or _env(GENERIC_MODEL_ENV) or meta["default_model"]
    requires_key = meta["requires_key"]
    transport = meta["transport"]

    if requires_key and not api_key:
        transport = "none"
        source = "missing"

    return LLMConfig(
        provider=provider, label=label, base_url=base_url, model=model,
        api_key=api_key, transport=transport, source=source,
        requires_key=requires_key,
    )


def provider_catalog():
    """Registry rendered for the settings UI (no secrets involved)."""
    catalog = []
    for pid, meta in PROVIDERS.items():
        catalog.append({
            "id": pid,
            "label": meta["label"],
            "base_url": meta["base_url"],
            "default_model": meta["default_model"],
            "key_prefixes": meta["key_prefixes"],
            "env_keys": meta["env_keys"],
            "transport": meta["transport"],
            "requires_key": meta["requires_key"],
            "supports_model_listing": bool(meta["models_path"]),
            "docs": meta["docs"],
        })
    return catalog


# ---------------------------------------------------------------------------
# Transport helpers
# ---------------------------------------------------------------------------

def _split_system(messages):
    """Split OpenAI-style messages into (system_text, non_system_messages)."""
    system_parts = []
    rest = []
    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(str(msg.get("content", "")))
        else:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            rest.append({"role": role, "content": str(msg.get("content", ""))})

    # Anthropic requires the first message to be from the user.
    while rest and rest[0]["role"] != "user":
        rest.pop(0)

    # ...and it rejects two consecutive messages with the same role.
    merged = []
    for msg in rest:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(dict(msg))

    if not merged:
        merged = [{"role": "user", "content": " "}]
    return "\n\n".join(system_parts).strip(), merged


def _http_json(url, payload=None, headers=None, method="POST", timeout=120):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise LLMError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"Could not reach {url}: {exc.reason}") from exc


def _http_stream(url, payload, headers=None, timeout=180):
    """Yield decoded SSE ``data:`` payloads from a streaming endpoint."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "text/event-stream")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body or body == "[DONE]":
                    continue
                try:
                    yield json.loads(body)
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise LLMError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"Could not reach {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

class LLMClient:
    """
    One uniform chat interface over every supported provider.

    Callers only ever use :meth:`chat`, :meth:`stream_chat`, :meth:`list_models`
    and :attr:`is_live`; the transport differences stay in here.
    """

    def __init__(self, config):
        self.config = config
        self._openai_client = None

    # -- properties ---------------------------------------------------------
    @property
    def is_live(self):
        return self.config.is_live

    @property
    def is_mock(self):
        return self.config.is_mock

    @property
    def model(self):
        return self.config.model

    @property
    def provider(self):
        return self.config.provider

    @property
    def describe(self):
        """Human-readable "Provider / model" label used in chat + reports."""
        if self.config.is_mock:
            return "the offline rule engine"
        if not self.config.is_live:
            return "the offline rule engine (no API key configured)"
        return f"{self.config.label} / {self.config.model}"

    # -- lazy openai sdk client --------------------------------------------
    def _openai(self):
        if self._openai_client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise LLMError("The 'openai' package is required for OpenAI-compatible providers.") from exc
            kwargs = {"api_key": self.config.api_key or "not-needed"}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._openai_client = OpenAI(**kwargs)
        return self._openai_client

    # -- non-streaming chat -------------------------------------------------
    def chat(self, messages, temperature=0.0, max_tokens=1500, json_mode=False):
        """Send a chat completion and return the assistant text."""
        if not self.is_live:
            raise LLMError("No live LLM configured (offline mode).")
        if self.config.transport == "anthropic":
            return self._chat_anthropic(messages, temperature, max_tokens)
        return self._chat_openai(messages, temperature, max_tokens, json_mode)

    def _chat_openai(self, messages, temperature, max_tokens, json_mode):
        client = self._openai()
        base = {"model": self.config.model, "messages": messages}

        # Providers vary wildly in which optional params they accept, so we
        # degrade gracefully instead of hard-failing on an unsupported flag.
        attempts = []
        if json_mode:
            attempts.append({**base, "temperature": temperature, "top_p": 1,
                             "max_tokens": max_tokens,
                             "response_format": {"type": "json_object"}})
        attempts.append({**base, "temperature": temperature, "top_p": 1, "max_tokens": max_tokens})
        attempts.append({**base, "max_tokens": max_tokens})
        attempts.append(dict(base))

        last_error = None
        for kwargs in attempts:
            try:
                completion = client.chat.completions.create(**kwargs)
                choices = getattr(completion, "choices", None) or []
                if not choices:
                    raise LLMError("Provider returned no choices.")
                return (choices[0].message.content or "").strip()
            except Exception as exc:  # noqa: BLE001 - provider SDKs raise many types
                last_error = exc
                if not _is_param_error(exc):
                    break
        raise LLMError(f"{self.config.label} chat call failed: {last_error}") from last_error

    def _chat_anthropic(self, messages, temperature, max_tokens):
        system_text, converted = _split_system(messages)
        payload = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": converted,
        }
        if system_text:
            payload["system"] = system_text
        data = _http_json(
            f"{self.config.base_url.rstrip('/')}/messages",
            payload,
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        parts = [block.get("text", "") for block in data.get("content", [])
                 if block.get("type") == "text"]
        return "".join(parts).strip()

    # -- streaming chat -----------------------------------------------------
    def stream_chat(self, messages, temperature=0.3, max_tokens=1500):
        """Yield text deltas. Falls back to one chunk if streaming is unsupported."""
        if not self.is_live:
            raise LLMError("No live LLM configured (offline mode).")
        if self.config.transport == "anthropic":
            yield from self._stream_anthropic(messages, temperature, max_tokens)
            return
        yield from self._stream_openai(messages, temperature, max_tokens)

    def _stream_openai(self, messages, temperature, max_tokens):
        client = self._openai()
        try:
            stream = client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=temperature,
                top_p=1,
                max_tokens=max_tokens,
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001
            if not _is_param_error(exc):
                raise LLMError(f"{self.config.label} streaming failed: {exc}") from exc
            # Provider rejected an optional param - retry bare, then give up
            # to a single non-streaming chunk.
            try:
                stream = client.chat.completions.create(
                    model=self.config.model, messages=messages, stream=True)
            except Exception:  # noqa: BLE001
                yield self._chat_openai(messages, temperature, max_tokens, False)
                return

        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            token = getattr(delta, "content", None)
            if token:
                yield token

    def _stream_anthropic(self, messages, temperature, max_tokens):
        system_text, converted = _split_system(messages)
        payload = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": converted,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text
        events = _http_stream(
            f"{self.config.base_url.rstrip('/')}/messages",
            payload,
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        for event in events:
            if event.get("type") == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]

    # -- model discovery ----------------------------------------------------
    def list_models(self, limit=300):
        """Best-effort model list for the settings dropdown."""
        meta = PROVIDERS.get(self.config.provider, PROVIDERS["custom"])
        if not meta["models_path"] or not self.config.base_url:
            return []

        url = f"{self.config.base_url.rstrip('/')}{meta['models_path']}"
        if self.config.transport == "anthropic":
            data = _http_json(url, None, method="GET", headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
            }, timeout=30)
            ids = [m.get("id") for m in data.get("data", [])]
        else:
            headers = {}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            data = _http_json(url, None, method="GET", headers=headers, timeout=30)
            entries = data.get("data") if isinstance(data, dict) else data
            ids = []
            for entry in entries or []:
                if isinstance(entry, dict):
                    # Gemini's compat layer returns "models/gemini-..." ids.
                    ids.append(str(entry.get("id") or entry.get("name") or "").split("models/")[-1])
                else:
                    ids.append(str(entry))
        return sorted({i for i in ids if i})[:limit]

    # -- health check -------------------------------------------------------
    def verify(self):
        """Round-trip a tiny prompt. Returns a dict the settings UI renders."""
        result = dict(self.config.public_dict())
        if self.config.is_mock:
            result.update(ok=True, message="Offline rule engine active - no API calls are made.")
            return result
        if not self.is_live:
            result.update(ok=False, message="No API key found for this provider.")
            return result

        started = time.time()
        try:
            reply = self.chat(
                [{"role": "user", "content": "Reply with the single word: ready"}],
                temperature=0.0, max_tokens=16,
            )
            result.update(
                ok=True,
                latency_ms=int((time.time() - started) * 1000),
                sample=(reply or "")[:80],
                message=f"Connected to {self.config.label} using model '{self.config.model}'.",
            )
        except Exception as exc:  # noqa: BLE001
            result.update(ok=False, message=str(exc)[:400])
        return result


def _is_param_error(exc):
    """True when a provider rejected an optional parameter rather than the request."""
    text = str(exc).lower()
    markers = (
        "unsupported", "unrecognized", "not supported", "invalid_request_error",
        "unknown field", "unexpected keyword", "response_format", "temperature",
        "top_p", "max_tokens", "extra fields", "does not support",
    )
    return any(marker in text for marker in markers)


def get_llm_client(api_key=None, provider=None, model=None, base_url=None):
    """Convenience factory used by the routes and background workers."""
    return LLMClient(resolve_llm_config(api_key, provider, model, base_url))


def client_from_request(data):
    """
    Build a client from a request body.

    Accepts both the modern keys (``provider``/``model``/``base_url``) and the
    legacy single ``api_key`` field, so old front-ends keep working.
    """
    data = data or {}
    return get_llm_client(
        api_key=data.get("api_key"),
        provider=data.get("provider"),
        model=data.get("model"),
        base_url=data.get("base_url"),
    )


def llm_options_from_request(data):
    """Extract the four connection fields so they can be handed to a thread."""
    data = data or {}
    return {
        "api_key": data.get("api_key"),
        "provider": data.get("provider"),
        "model": data.get("model"),
        "base_url": data.get("base_url"),
    }


logging.getLogger(__name__).addHandler(logging.NullHandler())
