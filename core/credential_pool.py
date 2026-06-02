"""
NEXUS Credential Pool — Centralized API key management with rotation and failover.

Manages multiple API keys per provider, supports key rotation when rate limited,
and provides the best available key for each request.

Inspired by Hermes Agent's credential_pool.py, adapted for NEXUS.
"""

import time
import json
import hashlib
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum


class KeyStatus(Enum):
    """Status of an API key."""
    ACTIVE = "active"           # Ready to use
    RATE_LIMITED = "rate_limited"  # Temporarily rate limited
    EXHAUSTED = "exhausted"       # Daily/monthly quota exhausted
    INVALID = "invalid"         # Key is invalid or revoked
    COOLING = "cooling"          # In cooldown period


@dataclass
class Credential:
    """A single API key with metadata and health tracking."""
    key_id: str                 # Unique identifier (hash-based)
    provider: str               # "ollama_cloud", "zai", "openai", etc.
    key: str                    # The actual API key
    name: str = ""              # Human-readable name
    status: KeyStatus = KeyStatus.ACTIVE

    # Usage tracking
    total_requests: int = 0
    total_tokens: int = 0
    last_used: float = 0.0
    last_error: float = 0.0

    # Rate limit tracking
    rate_limited_until: float = 0.0  # Unix timestamp
    daily_limit: int = 0       # Max requests per day
    daily_used: int = 0        # Requests today
    daily_reset: float = 0.0   # When daily counter resets
    cool_down_seconds: float = 60.0  # How long to cool down after rate limit

    # Failover tracking
    consecutive_errors: int = 0
    max_consecutive_errors: int = 5

    @property
    def is_available(self) -> bool:
        """Check if this key is available for use right now."""
        if self.status in (KeyStatus.INVALID, KeyStatus.EXHAUSTED):
            return False
        if self.status == KeyStatus.RATE_LIMITED:
            return time.time() >= self.rate_limited_until
        if self.status == KeyStatus.COOLING:
            return time.time() >= self.last_error + self.cool_down_seconds
        return True

    @property
    def usage_pct(self) -> float:
        """Daily usage percentage."""
        if self.daily_limit <= 0:
            return 0.0
        return (self.daily_used / self.daily_limit) * 100

    @property
    def health_score(self) -> float:
        """
        Health score from 0.0 (dead) to 1.0 (perfect).
        Lower = more likely to be skipped in rotation.
        """
        if self.status == KeyStatus.INVALID:
            return 0.0

        score = 1.0

        # Penalize consecutive errors
        if self.consecutive_errors > 0:
            score -= min(0.5, self.consecutive_errors * 0.1)

        # Penalize high daily usage
        if self.daily_limit > 0:
            score -= min(0.3, self.usage_pct / 100 * 0.3)

        # Penalize rate limits
        if self.status == KeyStatus.RATE_LIMITED:
            score -= 0.3

        return max(0.0, score)

    def to_dict(self) -> dict:
        """Serialize for storage (key is masked)."""
        return {
            "key_id": self.key_id,
            "provider": self.provider,
            "key_masked": f"{self.key[:4]}...{self.key[-4:]}" if len(self.key) > 8 else "***",
            "name": self.name,
            "status": self.status.value,
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "last_used": self.last_used,
            "daily_limit": self.daily_limit,
            "daily_used": self.daily_used,
            "health_score": round(self.health_score, 3),
        }


class CredentialPool:
    """
    Centralized credential management with rotation and failover.

    Keys are loaded from config.yaml and environment variables.
    The pool automatically rotates keys when rate limited and
    provides the healthiest key for each request.
    """

    STORAGE_PATH = Path("data/credentials")

    def __init__(self):
        self._pool: Dict[str, List[Credential]] = {}  # provider -> [Credential, ...]
        self._ensure_dir()
        self._load()

    def _ensure_dir(self):
        self.STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    def _key_id(self, key: str) -> str:
        """Generate a stable key ID from the key value."""
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    def add_key(self, provider: str, key: str, name: str = "",
                daily_limit: int = 0) -> Credential:
        """Add an API key to the pool."""
        cred = Credential(
            key_id=self._key_id(key),
            provider=provider,
            key=key,
            name=name or f"{provider}_{self._key_id(key)[:6]}",
            daily_limit=daily_limit,
        )

        if provider not in self._pool:
            self._pool[provider] = []

        # Check for duplicate
        for existing in self._pool[provider]:
            if existing.key_id == cred.key_id:
                # Update existing
                if key and key != existing.key:
                    existing.key = key
                if name:
                    existing.name = name
                if daily_limit:
                    existing.daily_limit = daily_limit
                self._save()
                return existing

        self._pool[provider].append(cred)
        self._save()
        return cred

    def get_key(self, provider: str) -> Optional[Credential]:
        """
        Get the best available key for a provider.

        Selects the healthiest, least-used key with rotation.
        Returns None if no keys are available.
        """
        keys = self._pool.get(provider, [])
        if not keys:
            return None

        # Filter available keys
        available = [k for k in keys if k.is_available]
        if not available:
            # All rate limited — find the one that resets soonest
            soonest = min(keys, key=lambda k: k.rate_limited_until or float("inf"))
            if soonest.rate_limited_until and soonest.rate_limited_until < time.time() + 300:
                return soonest  # Will be available within 5 min
            return None

        # Sort by health score (descending), then by usage (ascending)
        available.sort(key=lambda k: (-k.health_score, k.daily_used))
        return available[0]

    def report_success(self, key_id: str, tokens: int = 0) -> None:
        """Report a successful API call."""
        for provider_keys in self._pool.values():
            for cred in provider_keys:
                if cred.key_id == key_id:
                    cred.total_requests += 1
                    cred.total_tokens += tokens
                    cred.last_used = time.time()
                    cred.consecutive_errors = 0
                    if cred.status == KeyStatus.RATE_LIMITED:
                        cred.status = KeyStatus.ACTIVE
                    self._save()
                    return

    def report_error(self, key_id: str, error: str = "") -> None:
        """Report a failed API call."""
        for provider_keys in self._pool.values():
            for cred in provider_keys:
                if cred.key_id == key_id:
                    cred.consecutive_errors += 1
                    cred.last_error = time.time()

                    # Too many consecutive errors — mark invalid
                    if cred.consecutive_errors >= cred.max_consecutive_errors:
                        cred.status = KeyStatus.INVALID

                    # Rate limit detection
                    if "rate" in error.lower() or "429" in error:
                        cred.status = KeyStatus.RATE_LIMITED
                        cred.rate_limited_until = time.time() + cred.cool_down_seconds

                    self._save()
                    return

    def report_rate_limit(self, key_id: str, retry_after: float = 60.0) -> None:
        """Report a rate limit event for a key."""
        for provider_keys in self._pool.values():
            for cred in provider_keys:
                if cred.key_id == key_id:
                    cred.status = KeyStatus.RATE_LIMITED
                    cred.rate_limited_until = time.time() + retry_after
                    self._save()
                    return

    def load_from_env(self) -> int:
        """Load API keys from environment variables."""
        count = 0
        env_mappings = {
            "OLLAMA_API_KEY": ("ollama_cloud", ""),
            "ZAI_API_KEY": ("zai", ""),
            "OPENAI_API_KEY": ("openai", ""),
            "ANTHROPIC_API_KEY": ("anthropic", ""),
            "GEMINI_API_KEY": ("gemini", ""),
        }

        for env_var, (provider, name) in env_mappings.items():
            key = os.environ.get(env_var, "").strip()
            if key:
                self.add_key(provider, key, name=f"{provider}_env")
                count += 1

        return count

    def get_summary(self) -> Dict[str, dict]:
        """Get a summary of all keys (masked for safety)."""
        result = {}
        for provider, keys in self._pool.items():
            result[provider] = {
                "total_keys": len(keys),
                "available": sum(1 for k in keys if k.is_available),
                "keys": [k.to_dict() for k in keys],
            }
        return result

    def _save(self):
        """Persist credential metadata to disk (keys are stored encrypted)."""
        data = {
            "providers": {},
            "last_saved": time.time(),
        }

        for provider, keys in self._pool.items():
            data["providers"][provider] = [
                {
                    "key_id": k.key_id,
                    "key_encrypted": self._encrypt_key(k.key),
                    "name": k.name,
                    "status": k.status.value,
                    "total_requests": k.total_requests,
                    "total_tokens": k.total_tokens,
                    "daily_limit": k.daily_limit,
                    "daily_used": k.daily_used,
                    "cool_down_seconds": k.cool_down_seconds,
                    "max_consecutive_errors": k.max_consecutive_errors,
                }
                for k in keys
            ]

        state_file = self.STORAGE_PATH / "credential_pool.json"
        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self):
        """Load credential metadata from disk."""
        state_file = self.STORAGE_PATH / "credential_pool.json"
        if not state_file.exists():
            return

        try:
            with open(state_file, "r") as f:
                data = json.load(f)

            for provider, keys_data in data.get("providers", {}).items():
                for kd in keys_data:
                    cred = Credential(
                        key_id=kd["key_id"],
                        provider=provider,
                        key=self._decrypt_key(kd.get("key_encrypted", "")),
                        name=kd.get("name", ""),
                        status=KeyStatus(kd.get("status", "active")),
                        total_requests=kd.get("total_requests", 0),
                        total_tokens=kd.get("total_tokens", 0),
                        daily_limit=kd.get("daily_limit", 0),
                        daily_used=kd.get("daily_used", 0),
                        cool_down_seconds=kd.get("cool_down_seconds", 60.0),
                        max_consecutive_errors=kd.get("max_consecutive_errors", 5),
                    )
                    if provider not in self._pool:
                        self._pool[provider] = []
                    self._pool[provider].append(cred)
        except Exception:
            pass

    @staticmethod
    def _encrypt_key(key: str) -> str:
        """Simple obfuscation (not real encryption — use env vars for production)."""
        import base64
        return base64.b64encode(key.encode()).decode()

    @staticmethod
    def _decrypt_key(encrypted: str) -> str:
        """Decrypt an obfuscated key."""
        try:
            import base64
            return base64.b64decode(encrypted.encode()).decode()
        except Exception:
            return ""