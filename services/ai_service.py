"""
Backwards-compatible thin wrapper over :mod:`services.llm_provider`.

Historically this module hardcoded an NVIDIA base URL (and a committed API
key). Mercury is now vendor-neutral, so everything here simply delegates to
the provider registry. New code should import from ``services.llm_provider``
directly.
"""

from services.llm_provider import (  # noqa: F401 - re-exported for callers
    LLMClient,
    LLMConfig,
    LLMError,
    client_from_request,
    detect_provider,
    get_llm_client,
    llm_options_from_request,
    provider_catalog,
    resolve_llm_config,
)


def get_openai_client(request_key=None, provider=None, model=None, base_url=None):
    """
    Legacy helper: return a raw OpenAI-SDK client, or ``None`` when the
    session should run offline (``api_key="MOCK"``, or no key configured).

    Prefer :func:`get_llm_client`, which also supports Anthropic's native API
    and normalises streaming across providers.
    """
    config = resolve_llm_config(request_key, provider, model, base_url)
    if config.transport != "openai":
        return None
    return LLMClient(config)._openai()
