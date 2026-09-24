"""
Logging Filter for Mercury.

Redacts API keys, bearer tokens, and sensitive credentials from log records
before they are emitted to terminal or file outputs.
"""

import logging
import re

# Comprehensive compiled regex patterns matching LLM provider keys and bearer tokens
KEY_PATTERNS = [
    # OpenAI & generic sk- keys
    re.compile(r'\bsk-[a-zA-Z0-9_\-]{20,}\b'),
    # Anthropic keys
    re.compile(r'\bsk-ant-[a-zA-Z0-9_\-]{20,}\b'),
    # Google Gemini / Cloud keys
    re.compile(r'\bAIzaSy[a-zA-Z0-9_\-]{30,}\b'),
    # Nvidia API keys
    re.compile(r'\bnvapi-[a-zA-Z0-9_\-]{20,}\b'),
    # Groq API keys
    re.compile(r'\bgsk_[a-zA-Z0-9_\-]{20,}\b'),
    # Bearer tokens in headers or logs
    re.compile(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}'),
    # Key-value pairs in URLs or JSON (e.g. api_key=..., "api_key": "...")
    re.compile(r'(?i)(api[_-]?key|secret[_-]?key|password|auth[_-]?token)\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.]{10,})["\']?'),
]

REDACTED_TEXT = "[REDACTED_API_KEY]"


def redact_sensitive_text(text: str) -> str:
    """
    Scans a string and masks any detected API keys or credentials.
    """
    if not isinstance(text, str):
        text = str(text)

    # First redact key-value pairs while preserving the key name
    def kv_replacer(match):
        key_name = match.group(1)
        return f"{key_name}={REDACTED_TEXT}"

    # Apply key-value pattern
    text = KEY_PATTERNS[-1].sub(kv_replacer, text)

    # Apply direct token patterns
    for pat in KEY_PATTERNS[:-1]:
        text = pat.sub(REDACTED_TEXT, text)

    return text


class APIKeyRedactionFilter(logging.Filter):
    """
    Logging filter that intercepts and sanitizes sensitive credentials from
    log records across the application.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg:
            if isinstance(record.msg, str):
                record.msg = redact_sensitive_text(record.msg)
            elif isinstance(record.msg, (dict, list, tuple)):
                record.msg = redact_sensitive_text(str(record.msg))

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_sensitive_text(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(redact_sensitive_text(a) if isinstance(a, str) else a for a in record.args)

        return True
