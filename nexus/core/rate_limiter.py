"""
NEXUS v7 — Per-User Rate Limiter

Token-bucket rate limiting for Telegram messages.
Prevents abuse and respects Telegram API rate limits.

Features:
- Per-user token bucket (independent rate for each user)
- Configurable rate and burst
- Thread-safe via threading.Lock
- Automatic cleanup of stale buckets
- Stats for monitoring
"""

import time
import threading
import logging
from dataclasses import dataclass, field

log = logging.getLogger("nexus.rate_limiter")


@dataclass
class TokenBucket:
    """Token bucket for a single user.

    Each user gets an independent bucket that refills at a steady rate.
    Burst capacity allows short bursts above the steady rate.
    """
    tokens: float
    max_tokens: float
    refill_rate: float  # tokens per second
    last_refill: float = field(default_factory=time.time)

    def refill(self):
        """Refill tokens based on elapsed time since last refill."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if allowed, False if rate limited."""
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def wait_time(self, tokens: float = 1.0) -> float:
        """How long until enough tokens are available (in seconds)."""
        self.refill()
        if self.tokens >= tokens:
            return 0.0
        needed = tokens - self.tokens
        return needed / self.refill_rate


class RateLimiter:
    """
    Per-user rate limiter using token buckets.

    Configuration:
    - rate: messages per second (default: 1/3 ≈ 0.33 — one message every 3 seconds)
    - burst: maximum burst size (default: 5 — allows 5 rapid messages before throttling)
    - cleanup_interval: seconds between stale bucket cleanup (default: 300)
    - stale_after: seconds after which a bucket is considered stale (default: 3600)

    Usage:
        limiter = RateLimiter(rate=1/3, burst=5)

        if limiter.allow(user_id):
            send_message(...)
        else:
            wait_time = limiter.wait_time(user_id)
            # Queue or reject
    """

    def __init__(self, rate: float = None, burst: int = None, config: dict = None):
        cfg = config or {}

        # Rate: messages per second. Default: 1 message per 3 seconds
        self.rate = rate or cfg.get("rate", 1.0 / 3.0)
        # Burst: max tokens in bucket. Default: 5 quick messages allowed
        self.burst = burst or cfg.get("burst", 5)
        # Cleanup threshold: remove buckets not accessed in this many seconds
        self.stale_after = cfg.get("stale_after", 3600)  # 1 hour
        # How often to run cleanup
        self.cleanup_interval = cfg.get("cleanup_interval", 300)  # 5 minutes

        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

        # Stats
        self._total_allowed = 0
        self._total_rejected = 0

    def _get_bucket(self, user_id: str) -> TokenBucket:
        """Get or create a token bucket for a user."""
        if user_id in self._buckets:
            return self._buckets[user_id]

        bucket = TokenBucket(
            tokens=float(self.burst),  # Start with full bucket
            max_tokens=float(self.burst),
            refill_rate=self.rate,
        )
        self._buckets[user_id] = bucket
        return bucket

    def _maybe_cleanup(self):
        """Remove stale buckets that haven't been used recently."""
        now = time.time()
        if now - self._last_cleanup < self.cleanup_interval:
            return

        stale_users = []
        for user_id, bucket in self._buckets.items():
            if now - bucket.last_refill > self.stale_after:
                stale_users.append(user_id)

        for user_id in stale_users:
            del self._buckets[user_id]

        if stale_users:
            log.debug(f"Cleaned up {len(stale_users)} stale rate-limit buckets")

        self._last_cleanup = now

    def allow(self, user_id: str, tokens: float = 1.0) -> bool:
        """Check if a request from user_id is allowed.

        Args:
            user_id: The user identifier (e.g., Telegram user ID)
            tokens: How many tokens to consume (default 1 per message)

        Returns:
            True if the request is allowed, False if rate-limited.
        """
        with self._lock:
            self._maybe_cleanup()
            bucket = self._get_bucket(user_id)
            allowed = bucket.consume(tokens)

            if allowed:
                self._total_allowed += 1
            else:
                self._total_rejected += 1
                log.info(
                    f"Rate limited user {user_id}: "
                    f"{bucket.tokens:.1f}/{bucket.max_tokens:.0f} tokens, "
                    f"wait {bucket.wait_time(tokens):.1f}s"
                )

            return allowed

    def wait_time(self, user_id: str, tokens: float = 1.0) -> float:
        """How long a user must wait before they can send a message.

        Returns:
            Seconds until the user has enough tokens. 0.0 if already allowed.
        """
        with self._lock:
            bucket = self._get_bucket(user_id)
            return bucket.wait_time(tokens)

    def remaining(self, user_id: str) -> float:
        """How many tokens a user currently has available."""
        with self._lock:
            bucket = self._get_bucket(user_id)
            bucket.refill()
            return bucket.tokens

    def reset(self, user_id: str = None):
        """Reset rate limit for a specific user or all users.

        Args:
            user_id: Reset this user's bucket. If None, reset all buckets.
        """
        with self._lock:
            if user_id:
                if user_id in self._buckets:
                    del self._buckets[user_id]
            else:
                self._buckets.clear()

    def stats(self) -> dict:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "active_users": len(self._buckets),
                "total_allowed": self._total_allowed,
                "total_rejected": self._total_rejected,
                "rejection_rate": (
                    round(self._total_rejected / max(1, self._total_allowed + self._total_rejected), 3)
                ),
                "rate_per_second": self.rate,
                "burst_capacity": self.burst,
                "stale_after_seconds": self.stale_after,
            }