import os
from openai import OpenAI

def get_openai_client(request_key=None):
    """
    Returns an OpenAI client pointing to the Nvidia endpoint.
    """
    api_key = request_key or os.environ.get("NVIDIA_API_KEY") or "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"
    if api_key == "MOCK":
        return None
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key
    )
