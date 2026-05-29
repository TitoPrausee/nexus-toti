"""
NEXUS LLM Client — Ollama Integration
Model-Level-Routing, Auto-Fallback, Health-Checks via Ollama REST API.

Model-Level:
  Level 0 = Lokale Regeln (kein Model-Call, 0 Kosten)
  Level 1 = Schnell (kleines/schnelles Model)
  Level 2 = Standard (Standard-Model)
  Level 3 = Thinking (bestes verfuegbares Model)
"""

import json
import os
import time
import asyncio
import urllib.request
import urllib.error
from typing import Optional
from dataclasses import dataclass, field


OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


@dataclass
class Message:
    role: str  # "system", "user", "assistant"
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    elapsed: float = 0.0
    level_used: int = 2
    fallback_used: bool = False


@dataclass
class ModelHealth:
    model_name: str
    available: bool = False
    response_time: float = 0.0
    last_checked: float = 0.0
    error: str = ""


class LLMClient:
    """
    Ollama-basierter LLM Client.
    Model-Level-Routing, Auto-Fallback, Health-Checks.
    """

    # Modelle konfigurierbar via Env-Vars oder direkt
    MODEL_LEVELS = {
        0: {"name": "local-rules",  "description": "Kein Model-Call",       "cost": 0, "ollama_model": None},
        1: {"name": "qwen2.5:3b",   "description": "Schnell, 2GB RAM",       "cost": 1, "ollama_model": os.environ.get("NEXUS_MODEL_FAST",     "qwen2.5:3b")},
        2: {"name": "qwen2.5:3b",   "description": "Standard",               "cost": 2, "ollama_model": os.environ.get("NEXUS_MODEL_STANDARD", "qwen2.5:3b")},
        3: {"name": "qwen2.5:3b",   "description": "Thinking (bestes local)", "cost": 3, "ollama_model": os.environ.get("NEXUS_MODEL_THINK",    "qwen2.5:3b")},
    }

    FALLBACK_CHAIN = {
        3: [3, 2, 1],
        2: [2, 1],
        1: [1, 2],
    }

    TOTI_CHAT_PROMPT = (
        "Du bist Toti, ein autonomer Agent. "
        "Antworte kurz, direkt, ehrlich. Kein Fuelltext. "
        "Du kommunizierst wie ein erfahrener Kollege."
    )

    def __init__(self, default_level: int = 2):
        self.default_level = default_level
        self._call_count = 0
        self._total_tokens = 0
        self._health: dict[int, ModelHealth] = {}
        self._last_error: str = ""
        self._ollama_available = self._check_ollama()

        if self._ollama_available:
            self.run_health_check()

    def _check_ollama(self) -> bool:
        try:
            req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _ollama_request(self, model: str, messages: list[dict], stream: bool = False, timeout: int = 120) -> dict:
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 2048},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @property
    def is_available(self) -> bool:
        return self._ollama_available

    def get_model_for_level(self, level: int) -> str:
        info = self.MODEL_LEVELS.get(level, self.MODEL_LEVELS[2])
        return info["name"]

    def run_health_check(self) -> dict[int, ModelHealth]:
        if not self._ollama_available:
            for level in [1, 2, 3]:
                self._health[level] = ModelHealth(
                    model_name=self.MODEL_LEVELS[level]["ollama_model"] or "none",
                    available=False,
                    error="Ollama nicht erreichbar",
                )
            return self._health

        tested: set[str] = set()

        for level in [1, 2, 3]:
            model_name = self.MODEL_LEVELS[level]["ollama_model"]
            if not model_name:
                continue

            if model_name in tested:
                prev = next(
                    (h for h in self._health.values() if h.model_name == model_name),
                    None,
                )
                if prev:
                    self._health[level] = ModelHealth(
                        model_name=model_name,
                        available=prev.available,
                        response_time=prev.response_time,
                        last_checked=prev.last_checked,
                        error=prev.error,
                    )
                continue

            tested.add(model_name)
            try:
                start = time.time()
                data = self._ollama_request(
                    model_name,
                    [{"role": "user", "content": "Antworte mit einem Wort: OK"}],
                    timeout=30,
                )
                elapsed = time.time() - start
                content = data.get("message", {}).get("content", "")
                self._health[level] = ModelHealth(
                    model_name=model_name,
                    available=bool(content.strip()),
                    response_time=elapsed,
                    last_checked=time.time(),
                )
            except Exception as e:
                self._health[level] = ModelHealth(
                    model_name=model_name,
                    available=False,
                    last_checked=time.time(),
                    error=str(e)[:200],
                )

        return self._health

    def get_health_status(self) -> dict:
        result = {}
        for level, health in self._health.items():
            result[self.MODEL_LEVELS[level]["name"]] = {
                "available": health.available,
                "response_time": f"{health.response_time:.1f}s" if health.response_time else "n/a",
                "error": health.error or "OK",
            }
        result["ollama_available"] = self._ollama_available
        result["ollama_host"] = OLLAMA_BASE_URL
        return result

    def _get_working_level(self, requested_level: int) -> tuple[int, bool]:
        health = self._health.get(requested_level)
        if health and health.available:
            return requested_level, False

        chain = self.FALLBACK_CHAIN.get(requested_level, [requested_level])
        for level in chain:
            health = self._health.get(level)
            if health and health.available:
                return level, True

        if not self._health:
            return requested_level, False

        return 1, True

    def chat(
        self,
        messages: list[Message],
        system_prompt: Optional[str] = None,
        level: Optional[int] = None,
        max_retries: int = 2,
    ) -> LLMResponse:
        use_level = level if level is not None else self.default_level

        if use_level == 0:
            return LLMResponse(
                content="[LEVEL-0: Kein Model-Call]",
                model="rules",
                level_used=0,
            )

        if not self._ollama_available:
            return LLMResponse(
                content="[ERROR: Ollama nicht erreichbar. Starte Ollama: `ollama serve`]",
                model="none",
                level_used=0,
            )

        actual_level, fallback_used = self._get_working_level(use_level)
        model_name = self.MODEL_LEVELS[actual_level]["ollama_model"]

        # Messages fuer Ollama aufbauen
        ollama_messages = []
        if system_prompt:
            ollama_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            if msg.role == "system" and not system_prompt:
                ollama_messages.append({"role": "system", "content": msg.content})
            elif msg.role in ("user", "assistant"):
                ollama_messages.append({"role": msg.role, "content": msg.content})

        if not ollama_messages or ollama_messages[-1]["role"] != "user":
            # Fallback: letzten User-Content aus messages holen
            user_parts = [m.content for m in messages if m.role == "user"]
            if user_parts:
                ollama_messages.append({"role": "user", "content": user_parts[-1]})

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                start = time.time()
                data = self._ollama_request(model_name, ollama_messages, timeout=120)
                elapsed = time.time() - start

                content = data.get("message", {}).get("content", "")
                if not content.strip():
                    raise RuntimeError("Leere Antwort vom Model")

                usage = {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                }

                self._call_count += 1
                self._total_tokens += usage["total_tokens"]

                if actual_level in self._health:
                    self._health[actual_level].available = True
                    self._health[actual_level].response_time = elapsed

                return LLMResponse(
                    content=content,
                    model=model_name,
                    usage=usage,
                    raw=data,
                    elapsed=elapsed,
                    level_used=actual_level,
                    fallback_used=fallback_used,
                )

            except urllib.error.URLError as e:
                last_error = RuntimeError(f"Ollama nicht erreichbar: {e}")
                self._ollama_available = False
                break

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(1 * attempt)

        self._last_error = str(last_error)
        return LLMResponse(
            content=f"[LLM ERROR: {str(last_error)[:200]}]",
            model="error",
            level_used=actual_level,
            fallback_used=fallback_used,
        )

    async def chat_async(self, messages: list[Message], system_prompt: Optional[str] = None,
                         level: Optional[int] = None) -> LLMResponse:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.chat(messages, system_prompt, level)
        )

    def quick_response(self, message: str) -> str:
        messages = [
            Message(role="system", content=self.TOTI_CHAT_PROMPT),
            Message(role="user", content=message),
        ]
        return self.chat(messages, level=1).content

    def web_search(self, query: str, num: int = 5) -> list[dict]:
        # Ollama hat kein natives Web-Search — Tool-Aufruf via tools.py
        return [{"error": "Web-Search nicht verfuegbar ohne z-ai. Nutze tools.py web_search Tool."}]

    def get_stats(self) -> dict:
        return {
            "total_calls": self._call_count,
            "total_tokens": self._total_tokens,
            "default_level": self.default_level,
            "ollama_available": self._ollama_available,
            "ollama_host": OLLAMA_BASE_URL,
            "last_error": self._last_error,
            "health": {
                self.MODEL_LEVELS[l]["name"]: h.available
                for l, h in self._health.items()
            },
        }
