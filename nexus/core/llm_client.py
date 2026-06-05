"""
NEXUS v7 — LLM Client
Ollama Cloud native, streaming-first, cost-aware.
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


class LLMClient:
    """
    Single LLM client with Ollama Cloud, local fallback, and streaming.
    No z-ai. No gimmicks. Just working inference.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.base_url = self.config.get("base_url", os.environ.get("OLLAMA_HOST", "https://api.ollama.ai"))
        self.local_url = self.config.get("local_url", "http://localhost:11434")
        self.api_key = self.config.get("api_key") or os.environ.get("OLLAMA_API_KEY", "")
        self.mode = self.config.get("mode", "cloud")  # cloud, local, hybrid

        # Load model configs
        self.models = dict(DEFAULT_MODELS)
        for key, mcfg in self.config.get("models", {}).items():
            self.models[key] = ModelConfig(
                name=mcfg.get("model", "kimi-k2.6:cloud"),
                temperature=mcfg.get("temperature", 0.7),
                max_tokens=mcfg.get("max_tokens", 4096),
            )

        self.max_retries = self.config.get("max_retries", 2)
        self.timeout = self.config.get("timeout", 120)

        # Stats
        self._call_count = 0
        self._total_tokens = 0
        self._total_time = 0.0

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_url(self) -> str:
        if self.mode == "local":
            return f"{self.local_url}/api/chat"
        return f"{self.base_url}/api/chat"

    def chat(self, messages: list[Message], model_key: str = "default",
             temperature: float = None, max_tokens: int = None,
             stream: bool = False) -> LLMResponse:
        """Synchronous chat completion."""
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

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self._get_url(),
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()

                if stream:
                    # Return first chunk for sync calls
                    data = resp.json()
                else:
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
                log.warning(f"LLM call attempt {attempt+1} failed: {e}")
                if attempt == self.max_retries:
                    # Try fallback
                    if model_key != "fallback_cloud":
                        log.info("Trying cloud fallback...")
                        return self.chat(messages, "fallback_cloud", temperature, max_tokens, stream)
                    elif self.mode != "local":
                        log.info("Trying local fallback...")
                        old_mode = self.mode
                        self.mode = "local"
                        result = self.chat(messages, "fallback_local", temperature, max_tokens, stream)
                        self.mode = old_mode
                        return result

                return LLMResponse(
                    content="",
                    model=model_name,
                    elapsed=time.time() - start,
                    success=False,
                    error=str(e),
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
                                       timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
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
            "total_tokens": self._total_tokens,
            "total_time": round(self._total_time, 1),
            "avg_time": round(self._total_time / max(1, self._call_count), 2),
        }