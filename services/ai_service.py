import os
import litellm
import logging

class UnifiedLLMClient:
    """
    A unified multi-provider LLM client that acts as a drop-in replacement
    for the standard OpenAI client, utilizing LiteLLM as its execution engine.
    """
    def __init__(self, api_key=None, provider=None, model=None, base_url=None):
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

                # Prepare standard parameters for LiteLLM
                litellm_args = {
                    "model": model_name,
                    "messages": messages,
                    "stream": stream,
                    "timeout": 45.0  # 45s timeout to allow large 70B models to complete response
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
        # Resolve target model name
        model_name = requested_model or self.model or os.environ.get("LLM_MODEL")
        
        # If no model is explicitly requested, auto-select based on available API keys
        if not model_name or model_name.strip() == "":
            if self.api_key or os.environ.get("NVIDIA_API_KEY"):
                model_name = "nvidia/llama-3.1-nemotron-70b-instruct"
            elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                model_name = "gemini-2.5-flash"
            elif os.environ.get("GROQ_API_KEY"):
                model_name = "llama-3.1-70b-versatile"
            elif os.environ.get("OPENAI_API_KEY"):
                model_name = "gpt-4o-mini"
            elif os.environ.get("ANTHROPIC_API_KEY"):
                model_name = "claude-3-5-haiku-20241022"
            else:
                model_name = "nvidia/llama-3.1-nemotron-70b-instruct"

        # Replace deprecated/end-of-life models globally
        deprecated_tokens = ["llama-3.3-70b", "llama-3.1-70b", "llama-3.3-70b-instruct", "llama-3.1-70b-instruct", "meta/llama-3.3-70b-instruct", "meta/llama-3.1-70b-instruct"]
        if any(tok in model_name for tok in deprecated_tokens):
            model_name = "nvidia/llama-3.1-nemotron-70b-instruct"

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

        # Resolve provider: Model-based auto-detection takes precedence if explicit model implies a provider
        provider = detected_provider or self.provider or os.environ.get("LLM_PROVIDER")
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
            if not model_name.startswith("openai/"):
                model_name = f"openai/{model_name}"

        elif provider == "anthropic":
            if not api_key:
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not model_name.startswith("anthropic/"):
                model_name = f"anthropic/{model_name}"

        elif provider == "gemini":
            if not api_key:
                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if model_name.startswith("gemini/gemini/"):
                model_name = model_name[7:]
            elif not model_name.startswith("gemini/"):
                model_name = f"gemini/{model_name}"

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
            
            clean_name = model_name.replace("openai/", "")
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

            mapped_name = model_mapping.get(clean_name.lower(), clean_name)
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
