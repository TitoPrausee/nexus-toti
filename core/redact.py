"""
NEXUS Secret Redaction — Regex-based secret redaction for logs and tool output.

Prevents API keys, tokens, passwords, and other secrets from
leaking into logs, Telegram messages, or conversation history.

Inspired by Hermes Agent's redact.py, adapted for NEXUS's
Ollama Cloud + z.ai architecture.

Usage:
    from core.redact import redact_secrets, redact_text

    # Redact a string
    safe = redact_text("My API key is sk-abc123def456")
    # → "My API key is sk-***"

    # Check if text contains secrets
    if contains_secrets(text):
        text = redact_text(text)

    # Redact a dict (e.g., tool result)
    safe_dict = redact_dict(result_dict)
"""

import re
import os
from typing import Any

# ── Redaction State ──────────────────────────────────────────────────

_REDACT_ENABLED = os.environ.get("NEXUS_REDACT_SECRETS", "true").lower() not in ("false", "0", "no")

# ── Known API Key Prefixes ──────────────────────────────────────────

API_KEY_PATTERNS = [
    # OpenAI
    (r"sk-[a-zA-Z0-9]{20,}", "sk-***"),
    # Anthropic
    (r"sk-ant-api03-[a-zA-Z0-9]{20,}", "sk-ant-***"),
    # GitHub
    (r"ghp_[a-zA-Z0-9]{36,}", "ghp_***"),
    (r"github_pat_[a-zA-Z0-9_]{22,}", "github_pat_***"),
    # Ollama Cloud
    (r"ollama-[a-zA-Z0-9]{20,}", "ollama-***"),
    # Hugging Face
    (r"hf_[a-zA-Z0-9]{20,}", "hf_***"),
    # Google/Gemini
    (r"AIza[a-zA-Z0-9]{30,}", "AIza***"),
    # Generic Bearer tokens
    (r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*", "Bearer ***"),
    # Generic API keys in assignment context
    (r"(?:api[_-]?key|apikey|access[_-]?token|secret[_-]?key|auth[_-]?token)\s*[=:]\s*[\"']?([a-zA-Z0-9\-._~+/]{16,})[\"']?",
     lambda m: m.group(0).replace(m.group(1), "***")),
]

# ── Sensitive Query-String / JSON Body Keys ──────────────────────────

SENSITIVE_QUERY_PARAMS = {
    "token", "api_key", "apikey", "key", "secret", "secret_key",
    "access_token", "refresh_token", "auth", "password", "pass",
    "credential", "private_key", "session_id", "session_token",
}

SENSITIVE_BODY_KEYS = {
    "password", "passwd", "pass", "secret", "secret_key", "private_key",
    "api_key", "apikey", "access_token", "refresh_token", "token",
    "credential", "auth_token", "session_token", "authorization",
}

# ── Regex for URL query-string redaction ─────────────────────────────

_URL_QUERY_PATTERN = re.compile(
    r"([?&])(" + "|".join(re.escape(k) for k in SENSITIVE_QUERY_PARAMS) + r")=([^&\s]+)",
    re.IGNORECASE,
)

# ── Regex for JSON body redaction ────────────────────────────────────

_JSON_BODY_PATTERN = re.compile(
    r'[\"\\']?(' + "|".join(re.escape(k) for k in SENSITIVE_BODY_KEYS) + r')['\"\\']?\\s*:\\s*[\"\\']?([a-zA-Z0-9\\-._~+/]{8,})[\"\\']?',
    re.IGNORECASE,
)

# ── Environment Variable Leaks ──────────────────────────────────────

_ENV_VAR_PATTERN = re.compile(
    r"(?:(?:export|set|SET)\\s+)?([A-Z_][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIAL|AUTH)[A-Z0-9_]*)\\s*=\\s*[\"\\']?([a-zA-Z0-9\\-._~+/]{8,})[\"\\']?",
    re.IGNORECASE,
)

# ── Compiled patterns ───────────────────────────────────────────────

_COMPILED_API_KEY_PATTERNS = [
    (re.compile(p, re.IGNORECASE), replacement)
    for p, replacement in API_KEY_PATTERNS
]


def redact_text(text: str) -> str:
    """
    Redact secrets from a text string.

    Replaces API keys, tokens, passwords, and other sensitive values
    with '***' markers.
    """
    if not _REDACT_ENABLED or not text:
        return text

    result = text

    # 1. API key patterns (most specific first)
    for pattern, replacement in _COMPILED_API_KEY_PATTERNS:
        if callable(replacement):
            result = pattern.sub(replacement, result)
        else:
            result = pattern.sub(replacement, result)

    # 2. URL query-string params
    result = _URL_QUERY_PATTERN.sub(r"\1\2=***", result)

    # 3. JSON body values
    result = _JSON_BODY_PATTERN.sub(lambda m: m.group(0).replace(m.group(2), "***"), result)

    # 4. Environment variable assignments
    result = _ENV_VAR_PATTERN.sub(lambda m: m.group(0).replace(m.group(2), "***"), result)

    return result


def contains_secrets(text: str) -> bool:
    """Check if text likely contains secrets (without modifying it)."""
    if not text:
        return False

    for pattern, _ in _COMPILED_API_KEY_PATTERNS:
        if pattern.search(text):
            return True

    if _URL_QUERY_PATTERN.search(text):
        return True

    if _JSON_BODY_PATTERN.search(text):
        return True

    if _ENV_VAR_PATTERN.search(text):
        return True

    return False


def redact_dict(data: dict, max_depth: int = 10) -> dict:
    """
    Recursively redact secrets in a dictionary.

    Walks nested dicts and lists, redacting any string values
    that contain secrets.
    """
    if max_depth <= 0:
        return data

    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            # Check if key itself is sensitive
            if isinstance(key, str) and key.lower() in SENSITIVE_BODY_KEYS:
                result[key] = "***"
            elif contains_secrets(value):
                result[key] = redact_text(value)
            else:
                result[key] = value
        elif isinstance(value, dict):
            result[key] = redact_dict(value, max_depth - 1)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item, max_depth - 1) if isinstance(item, dict)
                else redact_text(item) if isinstance(item, str) and contains_secrets(item)
                else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def redact_tool_output(output: str, max_length: int = 10000) -> str:
    """
    Redact secrets from tool output, also truncating if too long.

    Combines secret redaction with length truncation for safe
    inclusion in conversation history.
    """
    if not output:
        return output

    # First redact
    result = redact_text(output)

    # Then truncate if needed
    if len(result) > max_length:
        result = result[:max_length] + f"\n... [truncated, {len(result) - max_length} chars omitted]"

    return result