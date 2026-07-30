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
                    "stream": stream
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
        model_name = requested_model or self.model or os.environ.get("LLM_MODEL") or "z-ai/glm-5.2"
        model_lower = model_name.lower()

        # Resolve provider
        provider = self.provider or os.environ.get("LLM_PROVIDER")
        if not provider:
            if "claude" in model_lower:
                provider = "anthropic"
            elif "gemini" in model_lower:
                provider = "gemini"
            elif "openrouter" in model_lower:
                provider = "openrouter"
            elif "ollama" in model_lower:
                provider = "ollama"
            elif "gpt-" in model_lower:
                provider = "openai"
            elif "glm" in model_lower or "nvidia" in model_lower:
                provider = "nvidia"
            else:
                provider = "nvidia"  # Default fallback

        provider = provider.lower()

        # Resolve API key and Base URL based on resolved provider
        api_key = self.api_key
        base_url = self.base_url

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
                api_key = os.environ.get("GEMINI_API_KEY")
            if not model_name.startswith("gemini/"):
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
                api_key = os.environ.get("NVIDIA_API_KEY") or "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"
            base_url = "https://integrate.api.nvidia.com/v1"
            if not model_name.startswith("openai/"):
                model_name = f"openai/{model_name}"

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
