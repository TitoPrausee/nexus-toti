"""
NEXUS Secret Redaction — Regex-based secret redaction for logs and tool output.

Prevents API keys, tokens, passwords, and other secrets from
leaking into logs, Telegram messages, or conversation history.

Inspired by Hermes Agent's redact.py, adapted for NEXUS's
Ollama Cloud + z.ai architecture.

Usage:
    from core.redact import redact_secrets, redact_text

    # Redact a string
    safe = redact_text("My API key is ***")
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
    (r"sk-ant-[a-zA-Z0-9]{20,}", "sk-ant-***"),
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
    r"""["']?(""" + "|".join(re.escape(k) for k in SENSITIVE_BODY_KEYS) + r""")["']?\s*:\s*["']?([a-zA-Z0-9\-._~+/]{8,})["']?""",
    re.IGNORECASE,
)

# ── Environment Variable Leaks ──────────────────────────────────────

_ENV_VAR_PATTERN = re.compile(
    r"""(?:(?:export|set|SET)\s+)?([A-Z_][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIAL|AUTH)[A-Z0-9_]*)\s*=\s*["']?([a-zA-Z0-9\-._~+/]{8,})["']?""",
    re.IGNORECASE,
)

# ── Combined pattern for quick detection ─────────────────────────────

_QUICK_SECRET_PATTERN = re.compile(
    r"(?:sk-|sk-ant-|ghp_|github_pat_|ollama-|hf_|AIza|Bearer\s+|api[_-]?key\s*[:=]|secret\s*[:=]|password\s*[:=]|token\s*[:=])",
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    """Redact secrets from a text string."""
    if not _REDACT_ENABLED or not text:
        return text

    result = text

    # API key patterns (most specific first)
    for pattern, replacement in API_KEY_PATTERNS:
        if callable(replacement):
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        else:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # URL query parameters
    result = _URL_QUERY_PATTERN.sub(
        lambda m: f"{m.group(1)}{m.group(2)}=***", result
    )

    # JSON body patterns
    result = _JSON_BODY_PATTERN.sub(
        lambda m: m.group(0).replace(m.group(2), "***"), result
    )

    # Environment variable leaks
    result = _ENV_VAR_PATTERN.sub(
        lambda m: m.group(0).replace(m.group(2), "***"), result
    )

    return result


def contains_secrets(text: str) -> bool:
    """Check if text likely contains secrets without full redaction."""
    if not text:
        return False
    # Quick check first
    if _QUICK_SECRET_PATTERN.search(text):
        return True
    # Full patterns
    for pattern, _ in API_KEY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    if _URL_QUERY_PATTERN.search(text) or _JSON_BODY_PATTERN.search(text):
        return True
    if _ENV_VAR_PATTERN.search(text):
        return True
    return False


def redact_dict(data: dict, max_depth: int = 10) -> dict:
    """Redact secrets from a dictionary (e.g., tool results, config)."""
    if not _REDACT_ENABLED or max_depth <= 0:
        return data

    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        str_key = str(key).lower()
        if isinstance(value, str):
            if str_key in SENSITIVE_BODY_KEYS or any(
                kw in str_key for kw in ("token", "key", "secret", "password", "credential", "auth")
            ):
                result[key] = "***" if len(value) > 4 else "***"
            else:
                result[key] = redact_text(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value, max_depth - 1)
        elif isinstance(value, list):
            result[key] = [
                redact_text(item) if isinstance(item, str)
                else redact_dict(item, max_depth - 1) if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def redact_tool_output(output: str) -> str:
    """Redact secrets from tool output, preserving structure."""
    return redact_text(output)


# ── Telegram-specific redaction ──────────────────────────────────────

_TELEGRAM_PATTERNS = [
    # Telegram bot tokens (123456:ABC-DEF...)
    (r"\d{8,10}:[a-zA-Z0-9\-_]{30,}", "***:***"),
    # Chat IDs (negative numbers)
    (r"(?<=chat_id[=:]\s*)\-?\d{8,}", "***"),
]


def redact_telegram(text: str) -> str:
    """Extra redaction for Telegram-specific patterns."""
    result = redact_text(text)
    for pattern, replacement in _TELEGRAM_PATTERNS:
        result = re.sub(pattern, replacement, result)
    return result


# ── Export ──────────────────────────────────────────────────────────

__all__ = [
    "redact_text",
    "contains_secrets",
    "redact_dict",
    "redact_tool_output",
    "redact_telegram",
    "API_KEY_PATTERNS",
    "SENSITIVE_QUERY_PARAMS",
    "SENSITIVE_BODY_KEYS",
    "_REDACT_ENABLED",
]