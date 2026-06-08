"""
NEXUS v7 — LLM Client
Ollama Cloud native, streaming-first, cost-aware.
Robust retry with exponential backoff and fallback chain.
"""

import os
import time
import json
import logging
import asyncio
from typing import Optional, AsyncIterator
from dataclasses import dataclass, field

import requests

log = logging.getLogger("nexus.llm")

# ─── Models ──────────────────────────────────────────────

@dataclass
class Message:
    role: str  # system, user, assistant
    content: str
    name: str = ""

    def to_dict(self):
        d = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed: float = 0.0
    success: bool = True
    error: str = ""

    @property
    def total_tokens(self):
        return self.tokens_in + self.tokens_out


@dataclass
class ModelConfig:
    name: str
    temperature: float = 0.7
    max_tokens: int = 4096
    description: str = ""


DEFAULT_MODELS = {
    "default": ModelConfig("kimi-k2.6:cloud", 0.7, 4096, "Orchestrator"),
    "coding": ModelConfig("qwen3-coder-next:cloud", 0.3, 8192, "Code"),
    "research": ModelConfig("glm-5.1:cloud", 0.5, 8192, "Research"),
    "analysis": ModelConfig("kimi-k2.6:cloud", 0.4, 4096, "Analysis"),
    "creative": ModelConfig("gemma4:cloud", 0.8, 4096, "Creative"),
    "fast": ModelConfig("gemini-3-flash-preview:cloud", 0.5, 2048, "Fast/Cheap"),
    "fallback_cloud": ModelConfig("glm-5.1:cloud", 0.5, 4096, "Cloud Fallback"),
    "fallback_local": ModelConfig("qwen2.5:3b", 0.5, 2048, "Local Emergency"),
}

# Error categories for smarter retry decisions
class ErrorCategory:
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    CONNECTION = "connection"
    MODEL_NOT_FOUND = "model_not_found"
    UNKNOWN = "unknown"


def _categorize_error(error: Exception) -> str:
    """Categorize an error for retry decision-making."""
    if isinstance(error, requests.exceptions.Timeout):
        return ErrorCategory.TIMEOUT
    if isinstance(error, requests.exceptions.ConnectionError):
        return ErrorCategory.CONNECTION
    if isinstance(error, requests.exceptions.HTTPError):
        # requests.HTTPError stores the response in error.response
        status_code = 0
        if hasattr(error, "response") and error.response is not None:
            status_code = getattr(error.response, "status_code", 0)
        if status_code == 429:
            return ErrorCategory.RATE_LIMIT
        if 500 <= status_code < 600:
            return ErrorCategory.SERVER_ERROR
        if status_code == 404:
            return ErrorCategory.MODEL_NOT_FOUND
    return ErrorCategory.UNKNOWN


class LLMClient:
    """
    Single LLM client with Ollama Cloud, local fallback, and streaming.
    Robust retry with exponential backoff and configurable fallback chain.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.base_url = self.config.get("base_url", os.environ.get("OLLAMA_HOST", "https://api.ollama.ai"))
        self.local_url = self.config.get("local_url", "http://localhost:11434")
        self.api_key = self.config.get("api_key") or os.environ.get("OLLAMA_API_KEY", "")
        self.mode = self.config.get("mode", "cloud")  # cloud, local, hybrid

        # Load model configs — supports both string shorthand and full dict
        self.models = dict(DEFAULT_MODELS)
        for key, mcfg in self.config.get("models", {}).items():
            if isinstance(mcfg, str):
                # Shorthand: "coding: qwen3-coder-next:cloud"
                self.models[key] = ModelConfig(name=mcfg)
            elif isinstance(mcfg, dict):
                self.models[key] = ModelConfig(
                    name=mcfg.get("model", "kimi-k2.6:cloud"),
                    temperature=mcfg.get("temperature", 0.7),
                    max_tokens=mcfg.get("max_tokens", 4096),
                )

        # Build fallback chain from config or use defaults
        fallback_raw = self.config.get("fallback", [])
        if fallback_raw:
            # Config specifies fallback models: ["glm-5.1:cloud", "qwen2.5:3b"]
            self.fallback_chain = []
            for entry in fallback_raw:
                # Find matching ModelConfig or create one
                found = False
                for key, mc in self.models.items():
                    if mc.name == entry:
                        self.fallback_chain.append((key, mc))
                        found = True
                        break
                if not found:
                    self.fallback_chain.append((f"fb_{entry}", ModelConfig(entry)))
        else:
            # Default fallback: try cloud fallback, then local
            self.fallback_chain = [
                ("fallback_cloud", self.models["fallback_cloud"]),
                ("fallback_local", self.models["fallback_local"]),
            ]

        self.max_retries = self.config.get("max_retries", 2)
        self.timeout = self.config.get("timeout", 120)

        # Separate connect and read timeouts for smarter timeout handling
        self.connect_timeout = self.config.get("connect_timeout", 10)
        self.read_timeout = self.config.get("read_timeout", 90)

        # Stats
        self._call_count = 0
        self._total_tokens = 0
        self._total_time = 0.0
        self._error_count = 0
        self._fallback_count = 0

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_url(self, use_local: bool = False) -> str:
        if use_local or self.mode == "local":
            return f"{self.local_url}/api/chat"
        return f"{self.base_url}/api/chat"

    def _backoff_delay(self, attempt: int, error_category: str) -> float:
        """Calculate backoff delay based on attempt number and error type."""
        # Base exponential: 1s, 2s, 4s, 8s, ...
        base_delay = min(2 ** attempt, 16)

        # Rate limit gets longer backoff
        if error_category == ErrorCategory.RATE_LIMIT:
            base_delay *= 2

        # Connection errors get slightly shorter backoff (server might be back soon)
        elif error_category == ErrorCategory.CONNECTION:
            base_delay *= 0.5

        # Add small jitter (0-500ms) to avoid thundering herd
        import random
        jitter = random.uniform(0, 0.5)

        return base_delay + jitter

    def chat(self, messages: list[Message], model_key: str = "default",
             temperature: float = None, max_tokens: int = None,
             stream: bool = False, _fallback_depth: int = 0) -> LLMResponse:
        """
        Synchronous chat completion with retry and fallback.

        Retry flow:
        1. Try primary model with exponential backoff (up to max_retries)
        2. If all retries fail, try each model in fallback chain
        3. If all fallbacks fail, return error response

        _fallback_depth is internal — prevents infinite fallback recursion.
        """
        model_cfg = self.models.get(model_key, self.models["default"])
        model_name = model_cfg.name
        temp = temperature if temperature is not None else model_cfg.temperature
        max_tok = max_tokens if max_tokens is not None else model_cfg.max_tokens

        payload = {
            "model": model_name,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
            "options": {
                "temperature": temp,
                "num_predict": max_tok,
            }
        }

        start = time.time()
        last_error = None

        # Phase 1: Retry primary model with exponential backoff
        for attempt in range(self.max_retries + 1):
            try:
                # Progressive timeout: shorter first attempt, longer later ones
                attempt_timeout = (self.connect_timeout, self.read_timeout)
                if attempt > 0:
                    # Longer timeout for retries
                    attempt_timeout = (self.connect_timeout, self.read_timeout + attempt * 15)

                resp = requests.post(
                    self._get_url(use_local=(model_key == "fallback_local")),
                    json=payload,
                    headers=self._headers(),
                    timeout=attempt_timeout,
                )
                resp.raise_for_status()

                data = resp.json()
                content = data.get("message", {}).get("content", "")
                tokens_in = data.get("prompt_eval_count", 0)
                tokens_out = data.get("eval_count", 0)
                elapsed = time.time() - start

                self._call_count += 1
                self._total_tokens += tokens_in + tokens_out
                self._total_time += elapsed

                return LLMResponse(
                    content=content,
                    model=model_name,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    elapsed=elapsed,
                    success=True,
                )

            except requests.exceptions.RequestException as e:
                last_error = e
                error_cat = _categorize_error(e)
                log.warning(
                    f"LLM call attempt {attempt+1}/{self.max_retries+1} "
                    f"failed ({error_cat}): {e}"
                )

                # Don't retry for model-not-found — try fallback instead
                if error_cat == ErrorCategory.MODEL_NOT_FOUND:
                    log.info(f"Model {model_name} not found, skipping to fallback")
                    break

                # If we have more retries, backoff and continue
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt, error_cat)
                    log.info(f"Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    continue

        # Phase 2: Try fallback chain (only if not already in a fallback call)
        if _fallback_depth < len(self.fallback_chain):
            for fb_idx, (fb_key, fb_cfg) in enumerate(self.fallback_chain):
                if _fallback_depth > 0 and fb_idx < _fallback_depth:
                    # Skip fallbacks we've already tried (for nested fallback)
                    continue
                if fb_key == model_key:
                    # Don't try the same model we just failed on
                    continue

                log.info(f"Trying fallback model: {fb_cfg.name} (key={fb_key})")
                self._fallback_count += 1
                try:
                    result = self.chat(
                        messages, fb_key, temperature, max_tokens, stream,
                        _fallback_depth=fb_idx + 1,
                    )
                    if result.success:
                        log.info(f"Fallback to {fb_cfg.name} succeeded!")
                        return result
                    # If fallback also failed, try next fallback
                    log.warning(f"Fallback {fb_cfg.name} failed: {result.error}")
                except Exception as e:
                    log.error(f"Fallback {fb_cfg.name} error: {e}")
                    continue

        # All retries and fallbacks exhausted
        self._error_count += 1
        elapsed = time.time() - start
        log.error(f"All LLM attempts failed for {model_name}. Last error: {last_error}")

        return LLMResponse(
            content="",
            model=model_name,
            elapsed=elapsed,
            success=False,
            error=str(last_error) if last_error else "All attempts failed",
        )

    async def chat_stream(self, messages: list[Message], model_key: str = "default",
                          temperature: float = None, max_tokens: int = None) -> AsyncIterator[str]:
        """Async streaming chat completion. Yields tokens as they arrive."""
        import aiohttp

        model_cfg = self.models.get(model_key, self.models["default"])
        model_name = model_cfg.name
        temp = temperature if temperature is not None else model_cfg.temperature
        max_tok = max_tokens if max_tokens is not None else model_cfg.max_tokens

        payload = {
            "model": model_name,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            "options": {
                "temperature": temp,
                "num_predict": max_tok,
            }
        }

        url = self._get_url()
        headers = self._headers()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers,
                                       timeout=aiohttp.ClientTimeout(
                                           total=self.timeout,
                                           connect=self.connect_timeout,
                                       )) as resp:
                    async for line in resp.content:
                        line = line.decode("utf-8").strip()
                        if not line:
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        try:
                            data = json.loads(line)
                            if data.get("done"):
                                break
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            log.error(f"Stream error: {e}")
            yield f"[Fehler: {e}]"

    def stats(self) -> dict:
        """Return usage statistics."""
        return {
            "calls": self._call_count,
            "errors": self._error_count,
            "fallbacks": self._fallback_count,
            "total_tokens": self._total_tokens,
            "total_time": round(self._total_time, 1),
            "avg_time": round(self._total_time / max(1, self._call_count), 2),
        }