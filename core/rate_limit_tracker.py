"""
NEXUS Rate Limit Tracker — Per-model rate limit tracking from API response headers.

Parses x-ratelimit-* headers from Ollama Cloud API responses, tracks
usage per model, and provides auto-backoff recommendations.

Inspired by Hermes Agent's rate_limit_tracker.py, adapted for NEXUS.
"""

import time
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
from pathlib import Path
from collections import defaultdict


@dataclass
class RateLimitBucket:
    """One rate-limit window (e.g. requests per minute)."""
    limit: int = 0          # Maximum allowed
    remaining: int = 0      # Currently remaining
    reset_at: float = 0.0  # Unix timestamp when limit resets

    @property
    def used(self) -> int:
        return max(0, self.limit - self.remaining)

    @property
    def usage_pct(self) -> float:
        return (self.used / self.limit * 100) if self.limit > 0 else 0.0

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.reset_at - time.time())


@dataclass
class RateLimitState:
    """Full rate-limit state parsed from response headers."""
    requests_per_minute: Optional[RateLimitBucket] = None
    tokens_per_minute: Optional[RateLimitBucket] = None
    requests_per_day: Optional[RateLimitBucket] = None
    last_updated: float = 0.0
    model: str = ""

    @property
    def has_data(self) -> bool:
        return any(b is not None for b in [
            self.requests_per_minute, self.tokens_per_minute, self.requests_per_day
        ])

    @property
    def age_seconds(self) -> float:
        return time.time() - self.last_updated if self.last_updated > 0 else float("inf")

    def is_rate_limited(self) -> bool:
        """Check if any bucket is exhausted."""
        for bucket in [self.requests_per_minute, self.tokens_per_minute, self.requests_per_day]:
            if bucket and bucket.remaining <= 0:
                return True
        return False

    def recommended_backoff(self) -> float:
        """How many seconds to wait before next request."""
        backoff = 0.0
        for bucket in [self.requests_per_minute, self.tokens_per_minute, self.requests_per_day]:
            if bucket and bucket.remaining <= 0:
                backoff = max(backoff, bucket.remaining_seconds)
        return backoff

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "last_updated": self.last_updated,
            "requests_per_minute": asdict(self.requests_per_minute) if self.requests_per_minute else None,
            "tokens_per_minute": asdict(self.tokens_per_minute) if self.tokens_per_minute else None,
            "requests_per_day": asdict(self.requests_per_day) if self.requests_per_day else None,
        }


class RateLimitTracker:
    """
    Track rate limits across models and provide backoff recommendations.
    Persists state across sessions for continuity.
    """

    STORAGE_PATH = Path("data/rate_limits")

    def __init__(self):
        self._states: Dict[str, RateLimitState] = {}
        self._ensure_dir()
        self._load()

    def _ensure_dir(self):
        self.STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    def _load(self):
        """Load rate limit state from disk."""
        state_file = self.STORAGE_PATH / "rate_limits.json"
        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    data = json.load(f)
                for model, state_data in data.get("models", {}).items():
                    state = RateLimitState(model=model)
                    state.last_updated = state_data.get("last_updated", 0)

                    for key, bucket_key in [
                        ("requests_per_minute", "rpm"),
                        ("tokens_per_minute", "tpm"),
                        ("requests_per_day", "rpd"),
                    ]:
                        if bucket_data := state_data.get(bucket_key):
                            bucket = RateLimitBucket(
                                limit=bucket_data.get("limit", 0),
                                remaining=bucket_data.get("remaining", 0),
                                reset_at=bucket_data.get("reset_at", 0),
                            )
                            setattr(state, key, bucket)

                    self._states[model] = state
            except Exception:
                pass

    def _save(self):
        """Persist rate limit state to disk."""
        data = {
            "models": {
                model: state.to_dict()
                for model, state in self._states.items()
            },
            "last_saved": time.time(),
        }
        state_file = self.STORAGE_PATH / "rate_limits.json"
        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)

    def update_from_headers(self, model: str, headers: Dict[str, str]) -> RateLimitState:
        """
        Update rate limit state from API response headers.

        Looks for standard x-ratelimit-* headers and Ollama-specific variants.
        """
        state = self._states.get(model, RateLimitState(model=model))
        state.last_updated = time.time()

        # Parse standard rate limit headers
        # x-ratelimit-limit-requests-minute, x-ratelimit-remaining-requests-minute, etc.
        for prefix, attr in [
            ("x-ratelimit-limit-requests-minute", "requests_per_minute"),
            ("x-ratelimit-limit-tokens-minute", "tokens_per_minute"),
            ("x-ratelimit-limit-requests-day", "requests_per_day"),
        ]:
            limit_val = self._safe_int(headers.get(prefix))
            remain_key = prefix.replace("-limit-", "-remaining-")
            remaining_val = self._safe_int(headers.get(remain_key))
            reset_key = prefix.replace("-limit-", "-reset-")
            reset_val = self._safe_float(headers.get(reset_key))

            if limit_val is not None:
                bucket = RateLimitBucket(
                    limit=limit_val,
                    remaining=remaining_val or 0,
                    reset_at=time.time() + (reset_val or 60),
                )
                setattr(state, attr, bucket)

        # Also check retry-after header (when rate limited)
        retry_after = headers.get("retry-after") or headers.get("x-ratelimit-retry-after")
        if retry_after:
            # Apply to whichever bucket is exhausted
            for bucket in [state.requests_per_minute, state.tokens_per_minute, state.requests_per_day]:
                if bucket and bucket.remaining <= 0:
                    bucket.reset_at = time.time() + float(retry_after)

        self._states[model] = state
        self._save()
        return state

    def get_state(self, model: str) -> Optional[RateLimitState]:
        """Get rate limit state for a model."""
        return self._states.get(model)

    def should_backoff(self, model: str, threshold_pct: float = 80.0) -> bool:
        """
        Check if we should back off from requests to this model.
        Returns True if any bucket exceeds threshold_pct usage.
        """
        state = self._states.get(model)
        if not state:
            return False

        for bucket in [state.requests_per_minute, state.tokens_per_minute, state.requests_per_day]:
            if bucket and bucket.usage_pct >= threshold_pct:
                return True
        return False

    def get_backoff_seconds(self, model: str) -> float:
        """Get recommended backoff seconds for a model."""
        state = self._states.get(model)
        if not state:
            return 0.0
        return state.recommended_backoff()

    def is_rate_limited(self, model: str) -> bool:
        """Check if a model is currently rate limited."""
        state = self._states.get(model)
        if not state:
            return False
        return state.is_rate_limited()

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all model rate limits."""
        return {
            "models": {
                model: {
                    "rate_limited": state.is_rate_limited(),
                    "rpm_remaining": state.requests_per_minute.remaining if state.requests_per_minute else None,
                    "rpm_limit": state.requests_per_minute.limit if state.requests_per_minute else None,
                    "rpm_usage": f"{state.requests_per_minute.usage_pct:.1f}%" if state.requests_per_minute else None,
                    "backoff": f"{state.recommended_backoff():.1f}s",
                }
                for model, state in self._states.items()
            }
        }

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None