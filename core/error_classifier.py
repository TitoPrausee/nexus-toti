"""
NEXUS Error Classifier — Structured error taxonomy with smart failover and recovery.

Extends the basic ErrorClass from error_learning.py with a full FailoverReason
taxonomy and ClassifiedError recovery hints, inspired by Hermes Agent's
error_classifier.py but adapted for NEXUS's multi-agent Ollama Cloud architecture.

Key features:
- FailoverReason enum: AUTH, BILLING, SERVER, TRANSPORT, CONTEXT, POLICY, FORMAT, PROVIDER, UNKNOWN
- ClassifiedError with recovery hints: retryable, failover_model, failover_provider, backoff_seconds
- Map Ollama Cloud API errors to structured classifications
- Per-model error tracking for rate limiting and failover decisions
"""

import re
import time
import json
import enum
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
from collections import defaultdict


class FailoverReason(enum.Enum):
    """Why an API call failed — determines recovery strategy."""
    # Authentication / authorization
    AUTH_INVALID_KEY = "auth_invalid_key"
    AUTH_EXPIRED = "auth_expired"
    AUTH_PERMISSION = "auth_permission"

    # Billing / quota
    BILLING_QUOTA_EXCEEDED = "billing_quota_exceeded"
    BILLING_INSUFFICIENT_FUNDS = "billing_insufficient_funds"
    BILLING_RATE_LIMITED = "billing_rate_limited"

    # Server-side
    SERVER_OVERLOADED = "server_overloaded"
    SERVER_INTERNAL_ERROR = "server_internal_error"
    SERVER_MAINTENANCE = "server_maintenance"

    # Transport
    TRANSPORT_TIMEOUT = "transport_timeout"
    TRANSPORT_CONNECTION = "transport_connection"
    TRANSPORT_DNS = "transport_dns"
    TRANSPORT_SSL = "transport_ssl"

    # Context / payload
    CONTEXT_TOO_LONG = "context_too_long"
    CONTEXT_INVALID_FORMAT = "context_invalid_format"
    CONTEXT_CONTENT_FILTER = "context_content_filter"

    # Model / provider policy
    POLICY_MODEL_UNAVAILABLE = "policy_model_unavailable"
    POLICY_MODEL_REJECTED = "policy_model_rejected"
    POLICY_REGION_BLOCKED = "policy_region_blocked"

    # Request format
    FORMAT_INVALID_REQUEST = "format_invalid_request"
    FORMAT_INVALID_RESPONSE = "format_invalid_response"

    # Provider-specific
    PROVIDER_OLLAMA_CLOUD = "provider_ollama_cloud"
    PROVIDER_OLLAMA_LOCAL = "provider_ollama_local"
    PROVIDER_ZAI = "provider_zai"

    # Tool execution
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_PERMISSION_DENIED = "tool_permission_denied"

    # Catch-all
    UNKNOWN = "unknown"


@dataclass
class ClassifiedError:
    """Structured classification of an API error with recovery hints."""
    reason: FailoverReason
    message: str
    raw_error: str = ""
    model: str = ""
    provider: str = ""
    timestamp: float = field(default_factory=time.time)

    # Recovery hints — the retry loop checks these
    retryable: bool = False
    failover_model: str = ""        # Suggest a different model
    failover_provider: str = ""     # Suggest a different provider
    backoff_seconds: float = 0.0   # How long to wait before retry
    max_retries: int = 2           # Max retry attempts for this error type

    def to_dict(self) -> dict:
        return {
            "reason": self.reason.value,
            "message": self.message,
            "raw_error": self.raw_error[:200],
            "model": self.model,
            "provider": self.provider,
            "timestamp": self.timestamp,
            "retryable": self.retryable,
            "failover_model": self.failover_model,
            "failover_provider": self.failover_provider,
            "backoff_seconds": self.backoff_seconds,
            "max_retries": self.max_retries,
        }


# ── Ollama Cloud Error Patterns ─────────────────────────────────────

OLLAMA_ERROR_PATTERNS = [
    # Auth errors
    (r"(invalid.api.key|unauthorized|authentication.failed)", FailoverReason.AUTH_INVALID_KEY, False),
    (r"(expired.token|token.expired)", FailoverReason.AUTH_EXPIRED, False),
    (r"(permission.denied|forbidden|access.denied)", FailoverReason.AUTH_PERMISSION, False),

    # Billing / quota
    (r"(quota.exceeded|rate.limit|too.many.requests|429)", FailoverReason.BILLING_RATE_LIMITED, True),
    (r"(insufficient.funds|payment.required|billing)", FailoverReason.BILLING_INSUFFICIENT_FUNDS, False),

    # Context
    (r"(context.length.exceeded|too.many.tokens|maximum.context|token.limit)", FailoverReason.CONTEXT_TOO_LONG, True),
    (r"(content.filter|safety.filter|refused.to.generate)", FailoverReason.CONTEXT_CONTENT_FILTER, True),
    (r"(invalid.format|json.decode|parse.error)", FailoverReason.FORMAT_INVALID_REQUEST, True),

    # Transport
    (r"(timeout|timed.out|deadline.exceeded)", FailoverReason.TRANSPORT_TIMEOUT, True),
    (r"(connection.refused|connection.reset|network.error|ECONNREFUSED)", FailoverReason.TRANSPORT_CONNECTION, True),
    (r"(dns|name.resolution|ENOTFOUND)", FailoverReason.TRANSPORT_DNS, True),
    (r"(ssl|certificate|tls|CERT_VERIFY_FAILED)", FailoverReason.TRANSPORT_SSL, False),

    # Server
    (r"(500|internal.server|overloaded|service.unavailable|503)", FailoverReason.SERVER_OVERLOADED, True),
    (r"(maintenance|under.deployment)", FailoverReason.SERVER_MAINTENANCE, True),

    # Model / policy
    (r"(model.not.found|model.unavailable|does.not.exist)", FailoverReason.POLICY_MODEL_UNAVAILABLE, True),
    (r"(model.rejected|unsupported.model)", FailoverReason.POLICY_MODEL_REJECTED, True),
]

# ── Fallback model chain per NEXUS config ───────────────────────────

DEFAULT_FAILOVER_CHAIN = {
    "NEXUS-0": ["kimi-k2.6:cloud", "glm-5.1:cloud", "qwen3-coder-next:cloud"],
    "SCOUT": ["glm-5.1:cloud", "kimi-k2.6:cloud", "qwen2.5:3b"],
    "FORGE": ["qwen3-coder-next:cloud", "glm-5.1:cloud", "qwen2.5:3b"],
    "LENS": ["kimi-k2.6:cloud", "glm-5.1:cloud", "qwen2.5:3b"],
    "HERALD": ["minimax-m2.7:cloud", "glm-5.1:cloud", "qwen2.5:3b"],
    "GHOST": ["deepseek-v4-flash:cloud", "glm-5.1:cloud", "qwen2.5:3b"],
}

DEFAULT_BACKOFF = {
    FailoverReason.BILLING_RATE_LIMITED: 30.0,
    FailoverReason.SERVER_OVERLOADED: 10.0,
    FailoverReason.SERVER_MAINTENANCE: 60.0,
    FailoverReason.TRANSPORT_TIMEOUT: 5.0,
    FailoverReason.TRANSPORT_CONNECTION: 3.0,
    FailoverReason.TRANSPORT_DNS: 5.0,
    FailoverReason.CONTEXT_TOO_LONG: 0.0,  # Don't retry same model — failover instead
    FailoverReason.POLICY_MODEL_UNAVAILABLE: 5.0,
}


class ErrorClassifier:
    """
    Classifies API errors into structured FailoverReason with recovery hints.
    Tracks per-model error rates for smarter failover decisions.
    """

    def __init__(self, failover_chain: dict = None):
        self.failover_chain = failover_chain or DEFAULT_FAILOVER_CHAIN
        self._model_errors: dict[str, list[float]] = defaultdict(list)
        self._max_model_history = 100

    def classify(self, error: str, model: str = "", provider: str = "") -> ClassifiedError:
        """
        Classify a raw error string into a structured ClassifiedError.

        Args:
            error: Raw error message from API call
            model: Model name that produced the error
            provider: Provider name (ollama_cloud, ollama_local, zai)

        Returns:
            ClassifiedError with recovery hints
        """
        error_lower = error.lower()

        # Check against known patterns
        for pattern, reason, retryable in OLLAMA_ERROR_PATTERNS:
            if re.search(pattern, error_lower):
                return self._build_classification(reason, error, model, provider, retryable)

        # Unmatched — unknown error
        return ClassifiedError(
            reason=FailoverReason.UNKNOWN,
            message=f"Unclassified error: {error[:200]}",
            raw_error=error,
            model=model,
            provider=provider,
            retryable=True,  # Unknown errors get one retry
            backoff_seconds=2.0,
            max_retries=1,
        )

    def _build_classification(
        self, reason: FailoverReason, raw_error: str, model: str, provider: str, retryable: bool
    ) -> ClassifiedError:
        """Build a ClassifiedError with appropriate recovery hints."""
        backoff = DEFAULT_BACKOFF.get(reason, 1.0)

        # Determine failover model
        failover_model = ""
        failover_provider = ""
        if model:
            chain = self.failover_chain.get("NEXUS-0", [])  # Default chain
            # Find model in chain and pick next
            for i, m in enumerate(chain):
                if m == model and i + 1 < len(chain):
                    failover_model = chain[i + 1]
                    break

            # Suggest provider failover
            if "ollama.ai" in provider or "cloud" in provider:
                failover_provider = "ollama_local"
            elif "local" in provider:
                failover_provider = "zai"

        # Content filter errors need model change, not retry
        if reason == FailoverReason.CONTEXT_CONTENT_FILTER:
            retryable = False

        # Auth errors are never retryable
        if reason in (FailoverReason.AUTH_INVALID_KEY, FailoverReason.AUTH_EXPIRED, FailoverReason.AUTH_PERMISSION):
            retryable = False

        # Context too long: don't retry same request
        if reason == FailoverReason.CONTEXT_TOO_LONG:
            retryable = False

        return ClassifiedError(
            reason=reason,
            message=self._human_message(reason, model),
            raw_error=raw_error,
            model=model,
            provider=provider,
            retryable=retryable,
            failover_model=failover_model,
            failover_provider=failover_provider,
            backoff_seconds=backoff,
        )

    def _human_message(self, reason: FailoverReason, model: str) -> str:
        """Generate a human-friendly error message."""
        model_str = f" on {model}" if model else ""
        messages = {
            FailoverReason.AUTH_INVALID_KEY: f"Authentication failed{model_str}. Check API key.",
            FailoverReason.AUTH_EXPIRED: f"API key expired{model_str}. Refresh credentials.",
            FailoverReason.AUTH_PERMISSION: f"Permission denied{model_str}. Check access rights.",
            FailoverReason.BILLING_QUOTA_EXCEEDED: f"Quota exceeded{model_str}. Wait or upgrade plan.",
            FailoverReason.BILLING_RATE_LIMITED: f"Rate limited{model_str}. Backing off.",
            FailoverReason.BILLING_INSUFFICIENT_FUNDS: f"Insufficient funds{model_str}. Top up balance.",
            FailoverReason.SERVER_OVERLOADED: f"Server overloaded{model_str}. Retrying with backoff.",
            FailoverReason.SERVER_INTERNAL_ERROR: f"Internal server error{model_str}.",
            FailoverReason.SERVER_MAINTENANCE: f"Server under maintenance{model_str}.",
            FailoverReason.TRANSPORT_TIMEOUT: f"Request timed out{model_str}. Retrying.",
            FailoverReason.TRANSPORT_CONNECTION: f"Connection failed{model_str}.",
            FailoverReason.TRANSPORT_DNS: f"DNS resolution failed{model_str}.",
            FailoverReason.TRANSPORT_SSL: f"SSL/TLS error{model_str}.",
            FailoverReason.CONTEXT_TOO_LONG: f"Context too long{model_str}. Shorten or switch model.",
            FailoverReason.CONTEXT_CONTENT_FILTER: f"Content filtered{model_str}. Rephrase request.",
            FailoverReason.POLICY_MODEL_UNAVAILABLE: f"Model unavailable{model_str}. Switching to fallback.",
            FailoverReason.POLICY_MODEL_REJECTED: f"Model rejected request{model_str}.",
            FailoverReason.FORMAT_INVALID_REQUEST: f"Invalid request format{model_str}.",
            FailoverReason.FORMAT_INVALID_RESPONSE: f"Invalid response{model_str}.",
        }
        return messages.get(reason, f"Error{model_str}: {reason.value}")

    def record_model_error(self, model: str) -> None:
        """Track that a model had an error (for error rate tracking)."""
        self._model_errors[model].append(time.time())
        # Trim to max history
        if len(self._model_errors[model]) > self._max_model_history:
            self._model_errors[model] = self._model_errors[model][-self._max_model_history:]

    def get_model_error_rate(self, model: str, window_seconds: float = 300) -> float:
        """Get error rate for a model in the last N seconds (0.0 to 1.0)."""
        now = time.time()
        recent = [t for t in self._model_errors[model] if now - t < window_seconds]
        return len(recent) / max(1, self._max_model_history) if recent else 0.0

    def should_failover(self, model: str, threshold: float = 0.3) -> bool:
        """Check if a model's error rate exceeds threshold (suggests failover)."""
        return self.get_model_error_rate(model) > threshold

    def get_failover_model(self, current_model: str, agent: str = "NEXUS-0") -> str:
        """Get next model in failover chain after current_model."""
        chain = self.failover_chain.get(agent, self.failover_chain["NEXUS-0"])
        for i, m in enumerate(chain):
            if m == current_model:
                # Return next that isn't failing
                for j in range(i + 1, len(chain)):
                    if not self.should_failover(chain[j]):
                        return chain[j]
                # All failing — return last resort
                return chain[-1]
        # Current model not in chain — return first that isn't failing
        for m in chain:
            if not self.should_failover(m):
                return m
        return chain[0]