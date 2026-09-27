import os
import litellm
import logging
from utils.url_validator import validate_base_url

class UnifiedLLMClient:
    """
    A unified multi-provider LLM client that acts as a drop-in replacement
    for the standard OpenAI client, utilizing LiteLLM as its execution engine.
    """
    def __init__(self, api_key=None, provider=None, model=None, base_url=None):
        if base_url:
            is_debug = os.environ.get("DEBUG", "false").lower() in ("true", "1", "t")
            valid, err = validate_base_url(base_url, is_debug=is_debug)
            if not valid:
                raise ValueError(f"Prohibited or invalid base_url: {err}")

        self.api_key = api_key
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.chat = self.Chat(self)

    class Chat:
        def __init__(self, client):
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self.client = client

            def create(self, model=None, messages=None, temperature=None, top_p=None, max_tokens=None, seed=None, stream=False, **kwargs):
                # Resolve provider, model name, api key, and base URL
                provider, model_name, api_key, base_url = self.client.resolve_config(model)

                logging.info(f"UnifiedLLMClient routing to provider: {provider}, model: {model_name}")

                # Prepare standard parameters for LiteLLM with timeouts and retry bounds
                litellm_args = {
                    "model": model_name,
                    "messages": messages,
                    "stream": stream,
                    "timeout": 45.0,  # 45s timeout to allow large models to complete response
                    "num_retries": 2   # Maximum retry limit on transient network failures
                }
                if temperature is not None:
                    litellm_args["temperature"] = temperature
                if top_p is not None:
                    litellm_args["top_p"] = top_p
                if max_tokens is not None:
                    litellm_args["max_tokens"] = max_tokens
                if api_key:
                    litellm_args["api_key"] = api_key
                if base_url:
                    is_debug = os.environ.get("DEBUG", "false").lower() in ("true", "1", "t")
                    valid, err = validate_base_url(base_url, is_debug=is_debug)
                    if not valid:
                        raise ValueError(f"Prohibited or invalid base_url: {err}")
                    litellm_args["api_base"] = base_url

                # Litellm doesn't support seed for all models; only pass for OpenAI/Nvidia/compatible
                if seed is not None and (provider in ["openai", "nvidia"]):
                    litellm_args["seed"] = seed

                # Allow passing custom arguments directly
                for k, v in kwargs.items():
                    litellm_args[k] = v

                return litellm.completion(**litellm_args)

    def resolve_config(self, requested_model):
        """
        Determines the correct provider, model identifier, API key, and base URL.
        """
        # Check if the user explicitly provided their own key or provider
        has_custom_key = bool(self.api_key and str(self.api_key).strip())
        is_user_nvidia = (self.provider or "").lower() == "nvidia" or (self.api_key or "").startswith("nvapi-")

        # Fallback sanitize ONLY if user did not provide an explicit key/nvidia provider
        if not has_custom_key and not is_user_nvidia:
            _deprecated_nvidia_tokens = [
                "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-70b-8192", "llama3-8b-8192"
            ]
            _groq_fallback = "groq/openai/gpt-oss-120b"
            for _tok in _deprecated_nvidia_tokens:
                if self.model and _tok in (self.model or "").lower():
                    self.model = _groq_fallback
                    self.provider = "groq"
                    break
            # Also redirect if provider is nvidia but no valid key is set anywhere
            if (self.provider or "").lower() == "nvidia" and not os.environ.get("NVIDIA_API_KEY"):
                if os.environ.get("GROQ_API_KEY"):
                    self.provider = "groq"
                    if not (self.model or "").startswith("groq/"):
                        self.model = _groq_fallback

        # Resolve target model name without prematurely falling back to LLM_MODEL env var
        model_name = requested_model or self.model
        
        # If no model is explicitly requested, auto-select based on provider or available API keys
        if not model_name or str(model_name).strip() == "":
            prov = (self.provider or "").lower()
            
            # Pass 1: explicit provider selection wins
            if prov == "nvidia" or (self.api_key or "").startswith("nvapi-"):
                model_name = "z-ai/glm-5.2"
            elif prov == "groq":
                model_name = "groq/openai/gpt-oss-120b"
            elif prov in ["gemini", "google"]:
                model_name = "gemini/gemini-3.8-flash"
            elif prov == "openai":
                model_name = "gpt-4o-mini"
            elif prov == "anthropic":
                model_name = "claude-3-5-haiku-20241022"
            elif prov == "openrouter":
                model_name = "openrouter/auto"
            elif prov == "ollama":
                model_name = "ollama/llama3"
                
            # Pass 2: only fall back to env vars if nothing was explicitly selected
            elif os.environ.get("NVIDIA_API_KEY"):
                model_name = "z-ai/glm-5.2"
            elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                model_name = "gemini/gemini-3.8-flash"
            elif os.environ.get("OPENAI_API_KEY"):
                model_name = "gpt-4o-mini"
            elif os.environ.get("ANTHROPIC_API_KEY"):
                model_name = "claude-3-5-haiku-20241022"
            elif os.environ.get("GROQ_API_KEY"):
                model_name = "groq/openai/gpt-oss-120b"
            else:
                model_name = os.environ.get("LLM_MODEL") or "z-ai/glm-5.2"

        # Replace deprecated/end-of-life models for Groq only if user is using Groq
        if (self.provider or "").lower() == "groq" or model_name.startswith("groq/"):
            deprecated_groq = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768", "gemma2-9b-it", "llama-3.3-70b-specdec"]
            if any(tok in model_name for tok in deprecated_groq):
                model_name = "groq/openai/gpt-oss-120b"

        model_lower = model_name.lower()

        # Check if model has a provider prefix like "gemini/gemini-1.5-flash"
        detected_provider = None
        if "/" in model_name:
            prefix = model_name.split("/")[0].lower()
            if prefix in ["openai", "anthropic", "gemini", "google", "groq", "openrouter", "ollama", "nvidia"]:
                detected_provider = "gemini" if prefix in ["google", "google-gemini"] else prefix

        if not detected_provider:
            if "claude" in model_lower:
                detected_provider = "anthropic"
            elif "gemini" in model_lower:
                detected_provider = "gemini"
            elif "openrouter" in model_lower:
                detected_provider = "openrouter"
            elif "ollama" in model_lower:
                detected_provider = "ollama"
            elif "gpt-" in model_lower or "gpt" in model_lower:
                detected_provider = "openai"
            elif "glm" in model_lower or "nvidia" in model_lower or "nemotron" in model_lower or "llama" in model_lower:
                detected_provider = "nvidia"

        # Resolve provider: Explicit provider selection ALWAYS takes precedence over heuristic model detection
        explicit_provider = (self.provider or "").strip().lower()
        if explicit_provider in ["google", "google-gemini"]:
            explicit_provider = "gemini"

        # If user explicitly chose a provider, strip foreign provider prefixes from model_name
        if explicit_provider and "/" in model_name:
            foreign_prefix = model_name.split("/")[0].lower()
            if foreign_prefix in ["openai", "anthropic", "gemini", "google", "groq", "openrouter", "ollama", "nvidia"] and foreign_prefix != explicit_provider:
                if explicit_provider == "gemini":
                    model_name = "gemini/gemini-3.8-flash"
                elif explicit_provider == "openai":
                    model_name = "gpt-4o-mini"
                elif explicit_provider == "anthropic":
                    model_name = "claude-3-5-haiku-20241022"
                elif explicit_provider == "nvidia":
                    model_name = "z-ai/glm-5.2"
                elif explicit_provider == "groq":
                    model_name = "groq/openai/gpt-oss-120b"
                else:
                    model_name = model_name.split("/", 1)[1]

        provider = explicit_provider or detected_provider or os.environ.get("LLM_PROVIDER")
        if not provider or provider.strip() == "":
            if "gemini" in model_lower:
                provider = "gemini"
            elif "groq" in model_lower:
                provider = "groq"
            elif "gpt" in model_lower or "openai" in model_lower:
                provider = "openai"
            elif "nvidia" in model_lower or "nemotron" in model_lower or "glm" in model_lower or "llama" in model_lower:
                provider = "nvidia"
            else:
                provider = "nvidia"

        provider = provider.lower()
        if provider in ["google", "google-gemini"]:
            provider = "gemini"

        # Resolve API key and Base URL based on resolved provider
        api_key = self.api_key
        base_url = self.base_url

        if api_key:
            api_key = str(api_key).strip().strip("'").strip('"')
            if api_key.startswith("nvapi-"):
                provider = "nvidia"
            elif api_key.startswith("sk-proj-") or (api_key.startswith("sk-") and not api_key.startswith("sk-ant-")):
                provider = "openai"
            elif api_key.startswith("AIzaSy"):
                provider = "gemini"
            elif api_key.startswith("gsk_"):
                provider = "groq"
            elif api_key.startswith("sk-ant-"):
                provider = "anthropic"

        if provider == "openai":
            if not api_key:
                api_key = os.environ.get("OPENAI_API_KEY")
            clean_model = model_name.split("/", 1)[1] if "/" in model_name else model_name
            if "gpt-oss" in clean_model or "glm" in clean_model:
                clean_model = "gpt-4o-mini"
            model_name = f"openai/{clean_model}"

        elif provider == "anthropic":
            if not api_key:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            clean_model = model_name.split("/", 1)[1] if "/" in model_name else model_name
            if "gpt-oss" in clean_model or "glm" in clean_model:
                clean_model = "claude-3-5-haiku-20241022"
            model_name = f"anthropic/{clean_model}"

        elif provider == "gemini":
            if not api_key:
                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            clean_model = model_name.split("/", 1)[1] if "/" in model_name else model_name
            if "gpt-oss" in clean_model or "glm" in clean_model or not clean_model:
                clean_model = "gemini-3.8-flash"
            elif clean_model in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest"]:
                clean_model = "gemini-3.8-flash"
            model_name = f"gemini/{clean_model}"

        elif provider == "openrouter":
            if not api_key:
                api_key = os.environ.get("OPENROUTER_API_KEY")
            if not model_name.startswith("openrouter/"):
                model_name = f"openrouter/{model_name}"

        elif provider == "ollama":
            if not base_url:
                base_url = os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
            if not model_name.startswith("ollama/"):
                model_name = f"ollama/{model_name}"

        elif provider == "nvidia":
            if not api_key:
                api_key = os.environ.get("NVIDIA_API_KEY")
            if not api_key:
                raise ValueError("NVIDIA_API_KEY not set")
            if not base_url:
                base_url = "https://integrate.api.nvidia.com/v1"
            
            clean_name = model_name.replace("openai/", "").replace("nvidia/", "")
            model_mapping = {
                "nemotron": "nvidia/llama-3.1-nemotron-70b-instruct",
                "nemotron-3.5-lightning": "nvidia/nemotron-3.5-lightning-30b-a3b",
                "llama3": "nvidia/llama-3.1-nemotron-70b-instruct",
                "llama-3.3-70b": "nvidia/llama-3.1-nemotron-70b-instruct",
                "llama-3.3-70b-instruct": "nvidia/llama-3.1-nemotron-70b-instruct",
                "meta/llama-3.3-70b-instruct": "nvidia/llama-3.1-nemotron-70b-instruct",
                "llama-3.1-70b": "nvidia/llama-3.1-nemotron-70b-instruct",
                "llama-3.1-70b-instruct": "nvidia/llama-3.1-nemotron-70b-instruct",
                "meta/llama-3.1-70b-instruct": "nvidia/llama-3.1-nemotron-70b-instruct",
                "glm-5.2": "z-ai/glm-5.2"
            }

            raw_lower = clean_name.lower().strip()
            mapped_name = model_mapping.get(raw_lower, model_name.replace("openai/", ""))
            model_name = f"openai/{mapped_name}"

        elif provider == "groq":
            if not api_key:
                api_key = os.environ.get("GROQ_API_KEY")
            if not model_name.startswith("groq/"):
                model_name = f"groq/{model_name}"

        else:
            # Fallback for custom / OpenAI-compatible endpoint
            if base_url and not model_name.startswith("openai/"):
                model_name = f"openai/{model_name}"

        return provider, model_name, api_key, base_url


def get_llm_client(api_key=None, provider=None, model=None, base_url=None):
    """
    Returns an instance of UnifiedLLMClient.
    """
    if api_key == "MOCK":
        return None
    return UnifiedLLMClient(api_key=api_key, provider=provider, model=model, base_url=base_url)


def get_openai_client(request_key=None):
    """
    Legacy wrapper for backward compatibility.
    """
    return get_llm_client(api_key=request_key)
