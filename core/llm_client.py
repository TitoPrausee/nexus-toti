"""
NEXUS LLM Client v3.0 — Ollama Cloud + Local + z-ai CLI
Per-Agent Model Routing mit optimaler Ollama Cloud Zuordnung.

Supportet 3 Backends:
  1. Ollama Cloud API (OpenAI-kompatibel mit Bearer Token)
  2. Lokaler Ollama Server (localhost:11434)
  3. z-ai CLI Fallback (GLM-4-Plus)

Per-Agent Model Routing:
  NEXUS-0 (Orchestrator) → kimi-k2.6:cloud
  SCOUT  (Recherche)     → glm-5.1:cloud
  FORGE  (Code)          → qwen3-coder-next:cloud
  LENS   (Analyse)       → kimi-k2.6:cloud
  HERALD (Output)        → minimax-m2.7:cloud
  GHOST  (Background)    → deepseek-v4-flash:cloud

Features:
  - Auto-Backend-Erkennung (Cloud → Local → z-ai)
  - Per-Agent Temperatur und max_tokens
  - Health-Check für alle Modelle
  - Auto-Fallback bei Model-Ausfall
  - Budget-Tracking
  - Retry mit exponentiellem Backoff
"""

import subprocess
import json
import os
import time
import asyncio
import tempfile
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path

try:
    import requests as http_requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    http_requests = None

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# ═══════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════

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
    backend: str = "unknown"  # "ollama_cloud", "ollama_local", "zai_cli"
    agent_id: str = ""
    fallback_used: bool = False


@dataclass
class ModelHealth:
    """Health-Status eines Modells."""
    model_name: str
    agent_id: str = ""
    available: bool = False
    response_time: float = 0.0
    last_checked: float = 0.0
    error: str = ""
    backend: str = ""


# ═══════════════════════════════════════════════════════════
# OLLAMA CLOUD MODEL MAPPING — Voreingestellt
# ═══════════════════════════════════════════════════════════

DEFAULT_AGENT_MODELS = {
    "NEXUS-0": {
        "model": "kimi-k2.6:cloud",
        "description": "Orchestrator — Beste Balance für agentisches Coding, 87/100 Tier-A",
        "pull_cmd": "ollama pull kimi-k2.6:cloud",
        "temperature": 0.7,
        "max_tokens": 4096,
    },
    "SCOUT": {
        "model": "glm-5.1:cloud",
        "description": "Recherche — 744B Parameter, optimiert für Systems Engineering",
        "pull_cmd": "ollama pull glm-5.1:cloud",
        "temperature": 0.5,
        "max_tokens": 8192,
    },
    "FORGE": {
        "model": "qwen3-coder-next:cloud",
        "description": "Coding — Bestes Coding-Modell im Ollama-Ökosystem",
        "pull_cmd": "ollama pull qwen3-coder-next:cloud",
        "temperature": 0.3,
        "max_tokens": 8192,
    },
    "LENS": {
        "model": "kimi-k2.6:cloud",
        "description": "Analyse — Herausragend bei Research und Reasoning",
        "pull_cmd": "ollama pull kimi-k2.6:cloud",
        "temperature": 0.4,
        "max_tokens": 4096,
    },
    "HERALD": {
        "model": "minimax-m2.7:cloud",
        "description": "Output — Stark bei langen, stabilen Sessions",
        "pull_cmd": "ollama pull minimax-m2.7:cloud",
        "temperature": 0.6,
        "max_tokens": 4096,
    },
    "GHOST": {
        "model": "deepseek-v4-flash:cloud",
        "description": "Background — Günstigster Cloud-Slot, reicht für Monitoring",
        "pull_cmd": "ollama pull deepseek-v4-flash:cloud",
        "temperature": 0.3,
        "max_tokens": 2048,
    },
}


# ═══════════════════════════════════════════════════════════
# LEGACY MODEL LEVELS (z-ai CLI Fallback)
# ═══════════════════════════════════════════════════════════

LEGACY_MODEL_LEVELS = {
    0: {"name": "local-rules", "cli_model": None},
    1: {"name": "glm-4-flash", "cli_model": "glm-4-flash"},
    2: {"name": "glm-4-plus", "cli_model": "glm-4-plus"},
    3: {"name": "glm-4-plus+thinking", "cli_model": "glm-4-plus"},
}

LEGACY_FALLBACK_CHAIN = {
    3: [3, 2, 1],
    2: [2, 1],
    1: [1, 2],
}

# TOTI Chat-Prompt
TOTI_CHAT_PROMPT = (
    "Du bist Toti — ein autonomer Agent im Nexus-System. "
    "Antworte kurz, direkt, ehrlich. Kein Fülltext. Keine Entschuldigungen. "
    "Kein 'Natürlich!', kein 'Gerne!'. Du hast Meinungen und vertrittst sie. "
    "Du kommunizierst wie ein erfahrener Kollege, nicht wie ein Assistent."
)


# ═══════════════════════════════════════════════════════════
# LLM CLIENT
# ═══════════════════════════════════════════════════════════

class LLMClient:
    """
    Multi-Backend LLM Client mit Per-Agent Ollama Cloud Routing.

    Backend-Priorität:
      1. Ollama Cloud API (wenn API Key gesetzt)
      2. Lokaler Ollama Server (wenn localhost:11434 erreichbar)
      3. z-ai CLI (wenn verfügbar)
    """

    def __init__(self, config_path: Optional[str] = None, default_level: int = 2):
        self.default_level = default_level
        self._call_count = 0
        self._total_tokens = 0
        self._health: dict[str, ModelHealth] = {}  # key = agent_id
        self._last_error: str = ""

        # Config laden
        self._config = self._load_config(config_path)
        self._agent_models = self._get_agent_models()
        self._ollama_config = self._config.get("ollama", {})

        # API Key
        self._api_key = (
            self._ollama_config.get("api_key", "")
            or os.environ.get("OLLAMA_API_KEY", "")
        )

        # URLs
        self._cloud_url = self._ollama_config.get("base_url", "https://api.ollama.ai")
        self._local_url = self._ollama_config.get("local_url", "http://localhost:11434")
        self._mode = self._ollama_config.get("mode", "cloud")

        # Backend-Verfügbarkeit
        self._cloud_available = bool(self._api_key)
        self._local_available = self._check_local_ollama()
        self._zai_available, self._zai_path = self._find_zai_cli()

        # Aktiver Backend
        self._active_backend = self._determine_backend()

        # Fallback-Modelle
        self._fallback_cloud = self._ollama_config.get("fallback_models", {}).get("cloud", "glm-5.1:cloud")
        self._fallback_local = self._ollama_config.get("fallback_models", {}).get("local", "llama3.2:latest")
        self._fallback_zai = self._ollama_config.get("fallback_models", {}).get("zai", "glm-4-plus")

        # Health-Check
        if self._ollama_config.get("health_check_on_start", True):
            self.run_health_check()

    def _load_config(self, config_path: Optional[str] = None) -> dict:
        """Lade config.yaml."""
        if config_path and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                if YAML_AVAILABLE:
                    return yaml.safe_load(f) or {}
                # Simple YAML fallback ohne Bibliothek
                return self._parse_simple_yaml(f.read())
        # Versuche Standard-Pfad
        default_path = Path(__file__).parent.parent / "config.yaml"
        if default_path.exists():
            with open(default_path, "r", encoding="utf-8") as f:
                if YAML_AVAILABLE:
                    return yaml.safe_load(f) or {}
                return self._parse_simple_yaml(f.read())
        return {}

    def _parse_simple_yaml(self, content: str) -> dict:
        """Minimaler YAML-Parser für config.yaml ohne PyYAML."""
        # Sehr simpler Parser — reicht für einfache Key-Value Strukturen
        result = {}
        try:
            if YAML_AVAILABLE:
                return yaml.safe_load(content) or {}
        except Exception:
            pass
        return result

    def _get_agent_models(self) -> dict:
        """Lade Agent-Model-Mapping aus Config oder Defaults."""
        ollama = self._config.get("ollama", {})
        agent_models = ollama.get("agent_models", {})
        if not agent_models:
            return DEFAULT_AGENT_MODELS.copy()
        # Merge mit Defaults
        merged = DEFAULT_AGENT_MODELS.copy()
        for agent_id, cfg in agent_models.items():
            if isinstance(cfg, dict):
                merged[agent_id] = cfg
        return merged

    def _check_local_ollama(self) -> bool:
        """Prüfe ob lokaler Ollama Server läuft."""
        if not REQUESTS_AVAILABLE:
            return False
        try:
            resp = http_requests.get(f"{self._local_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _find_zai_cli(self) -> tuple[bool, Optional[str]]:
        """Finde z-ai CLI im PATH."""
        try:
            result = subprocess.run(
                ["which", "z-ai"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except Exception:
            pass
        return False, None

    def _determine_backend(self) -> str:
        """Bestimme den aktiven Backend basierend auf Verfügbarkeit."""
        if self._mode == "cloud" and self._cloud_available:
            return "ollama_cloud"
        if self._mode == "local" and self._local_available:
            return "ollama_local"
        if self._mode == "hybrid":
            if self._cloud_available:
                return "ollama_cloud"
            if self._local_available:
                return "ollama_local"
        if self._zai_available:
            return "zai_cli"
        # Fallback-Reihenfolge
        if self._cloud_available:
            return "ollama_cloud"
        if self._local_available:
            return "ollama_local"
        if self._zai_available:
            return "zai_cli"
        return "none"

    @property
    def is_available(self) -> bool:
        return self._active_backend != "none"

    @property
    def active_backend(self) -> str:
        return self._active_backend

    def get_model_for_agent(self, agent_id: str) -> str:
        """Modell-Name für einen Agent."""
        cfg = self._agent_models.get(agent_id, {})
        return cfg.get("model", self._fallback_cloud)

    def get_agent_config(self, agent_id: str) -> dict:
        """Komplette Agent-Model-Konfiguration."""
        return self._agent_models.get(agent_id, {
            "model": self._fallback_cloud,
            "temperature": 0.5,
            "max_tokens": 4096,
            "description": f"Default config for {agent_id}",
        })

    def get_all_models(self) -> dict:
        """Alle konfigurierten Modelle."""
        return self._agent_models.copy()

    # ═══════════════════════════════════════════════════════
    # HEALTH CHECK
    # ═══════════════════════════════════════════════════════

    def run_health_check(self) -> dict[str, ModelHealth]:
        """
        Teste ob die Ollama Cloud/Local Modelle antworten.
        Testet jeden Agent-spezifischen Model-Endpunkt.
        """
        for agent_id, model_cfg in self._agent_models.items():
            model_name = model_cfg.get("model", self._fallback_cloud)
            self._health[agent_id] = self._test_model(agent_id, model_name)

        return self._health

    def _test_model(self, agent_id: str, model_name: str) -> ModelHealth:
        """Teste ein einzelnes Modell."""
        health = ModelHealth(
            model_name=model_name,
            agent_id=agent_id,
            last_checked=time.time(),
        )

        test_messages = [
            Message(role="system", content="Antworte mit genau einem Wort."),
            Message(role="user", content="OK?"),
        ]

        # 1. Versuch: Ollama Cloud
        if self._cloud_available:
            try:
                start = time.time()
                resp = self._call_ollama_cloud(
                    model_name, test_messages, temperature=0.1, max_tokens=10
                )
                elapsed = time.time() - start
                if resp and resp.get("content", "").strip():
                    health.available = True
                    health.response_time = elapsed
                    health.backend = "ollama_cloud"
                    return health
            except Exception as e:
                health.error = f"Cloud: {str(e)[:100]}"

        # 2. Versuch: Lokaler Ollama
        if self._local_available:
            try:
                local_model = model_name.replace(":cloud", ":latest")
                start = time.time()
                resp = self._call_ollama_local(
                    local_model, test_messages, temperature=0.1, max_tokens=10
                )
                elapsed = time.time() - start
                if resp and resp.get("content", "").strip():
                    health.available = True
                    health.response_time = elapsed
                    health.backend = "ollama_local"
                    return health
            except Exception as e:
                health.error = f"{health.error}; Local: {str(e)[:100]}" if health.error else f"Local: {str(e)[:100]}"

        # 3. Versuch: z-ai CLI
        if self._zai_available:
            try:
                start = time.time()
                resp = self._call_zai_cli(test_messages, system_prompt="Antworte mit einem Wort.")
                elapsed = time.time() - start
                if resp and resp.get("content", "").strip():
                    health.available = True
                    health.response_time = elapsed
                    health.backend = "zai_cli"
                    return health
            except Exception as e:
                health.error = f"{health.error}; z-ai: {str(e)[:100]}" if health.error else f"z-ai: {str(e)[:100]}"

        health.available = False
        return health

    def get_health_status(self) -> dict:
        """Health-Status als Dict für CLI/Telegram."""
        result = {}
        for agent_id, health in self._health.items():
            result[agent_id] = {
                "model": health.model_name,
                "available": health.available,
                "response_time": f"{health.response_time:.1f}s" if health.response_time else "n/a",
                "backend": health.backend or "none",
                "error": health.error or "OK",
            }
        result["_backend"] = {
            "active": self._active_backend,
            "cloud": self._cloud_available,
            "local": self._local_available,
            "zai_cli": self._zai_available,
            "api_key_set": bool(self._api_key),
        }
        return result

    # ═══════════════════════════════════════════════════════
    # MAIN CHAT FUNCTION — Per-Agent Routing
    # ═══════════════════════════════════════════════════════

    def chat(
        self,
        messages: list[Message],
        system_prompt: Optional[str] = None,
        level: Optional[int] = None,
        agent_id: Optional[str] = None,
        max_retries: int = 2,
    ) -> LLMResponse:
        """
        Sende eine Chat-Completion-Anfrage.
        Verwendet Per-Agent Model Routing wenn agent_id gesetzt.
        Fallback auf Legacy Level-System wenn nicht.
        """
        # Per-Agent Routing
        if agent_id and agent_id in self._agent_models:
            return self._chat_per_agent(messages, system_prompt, agent_id, max_retries)

        # Legacy Level-Routing (z-ai CLI)
        if self._active_backend == "zai_cli" or self._active_backend == "none":
            return self._chat_legacy(messages, system_prompt, level, max_retries)

        # Default: NEXUS-0 Modell
        return self._chat_per_agent(messages, system_prompt, "NEXUS-0", max_retries)

    def _chat_per_agent(
        self,
        messages: list[Message],
        system_prompt: Optional[str],
        agent_id: str,
        max_retries: int,
    ) -> LLMResponse:
        """Chat mit Per-Agent Modell und Auto-Fallback."""
        model_cfg = self._agent_models.get(agent_id, {})
        model_name = model_cfg.get("model", self._fallback_cloud)
        temperature = model_cfg.get("temperature", 0.5)
        max_tokens = model_cfg.get("max_tokens", 4096)

        # User-Prompt und System-Prompt bauen
        user_prompt, sys_prompt = self._build_prompts(messages, system_prompt)

        last_error = None

        for attempt in range(1, max_retries + 1):
            # 1. Versuch: Ollama Cloud
            if self._cloud_available:
                try:
                    start = time.time()
                    result = self._call_ollama_cloud(
                        model_name,
                        [Message(role="system", content=sys_prompt), Message(role="user", content=user_prompt)],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    elapsed = time.time() - start

                    content = result.get("content", "")
                    if content.strip():
                        self._call_count += 1
                        self._total_tokens += result.get("usage", {}).get("total_tokens", 0)
                        self._update_health(agent_id, model_name, True, elapsed, "ollama_cloud")

                        return LLMResponse(
                            content=content,
                            model=model_name,
                            usage=result.get("usage", {}),
                            raw=result,
                            elapsed=elapsed,
                            backend="ollama_cloud",
                            agent_id=agent_id,
                        )
                except Exception as e:
                    last_error = e
                    self._update_health(agent_id, model_name, False, 0, "ollama_cloud", str(e)[:200])

            # 2. Versuch: Lokaler Ollama
            if self._local_available:
                try:
                    local_model = model_name.replace(":cloud", ":latest")
                    start = time.time()
                    result = self._call_ollama_local(
                        local_model,
                        [Message(role="system", content=sys_prompt), Message(role="user", content=user_prompt)],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    elapsed = time.time() - start

                    content = result.get("content", "")
                    if content.strip():
                        self._call_count += 1
                        self._total_tokens += result.get("usage", {}).get("total_tokens", 0)
                        self._update_health(agent_id, local_model, True, elapsed, "ollama_local")

                        return LLMResponse(
                            content=content,
                            model=local_model,
                            usage=result.get("usage", {}),
                            raw=result,
                            elapsed=elapsed,
                            backend="ollama_local",
                            agent_id=agent_id,
                            fallback_used=True,
                        )
                except Exception as e:
                    last_error = e

            # 3. Versuch: z-ai CLI
            if self._zai_available:
                try:
                    start = time.time()
                    result = self._call_zai_cli(
                        [Message(role="system", content=sys_prompt), Message(role="user", content=user_prompt)],
                    )
                    elapsed = time.time() - start

                    content = result.get("content", "")
                    if content.strip():
                        self._call_count += 1
                        self._total_tokens += result.get("usage", {}).get("total_tokens", 0)
                        self._update_health(agent_id, self._fallback_zai, True, elapsed, "zai_cli")

                        return LLMResponse(
                            content=content,
                            model=self._fallback_zai,
                            usage=result.get("usage", {}),
                            raw=result,
                            elapsed=elapsed,
                            backend="zai_cli",
                            agent_id=agent_id,
                            fallback_used=True,
                        )
                except Exception as e:
                    last_error = e

            # Retry warten
            if attempt < max_retries:
                time.sleep(1 * attempt)

        self._last_error = str(last_error)
        return LLMResponse(
            content=f"[LLM ERROR: {str(last_error)[:200]}]",
            model="error",
            elapsed=0.0,
            backend="none",
            agent_id=agent_id,
        )

    def _chat_legacy(
        self,
        messages: list[Message],
        system_prompt: Optional[str],
        level: Optional[int],
        max_retries: int,
    ) -> LLMResponse:
        """Legacy z-ai CLI Chat mit Level-Routing."""
        use_level = level if level is not None else self.default_level

        if use_level == 0:
            return LLMResponse(
                content="[LEVEL-0: Kein Model-Call — nutze Regeln]",
                model="rules",
                elapsed=0.0,
                backend="rules",
            )

        if not self._zai_available:
            return LLMResponse(
                content="[ERROR: Kein LLM-Backend verfügbar]",
                model="none",
                elapsed=0.0,
                backend="none",
            )

        user_prompt, sys_prompt = self._build_prompts(messages, system_prompt)
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                start = time.time()
                result = self._call_zai_cli(
                    [Message(role="system", content=sys_prompt), Message(role="user", content=user_prompt)],
                    use_thinking=use_level >= 3,
                )
                elapsed = time.time() - start

                content = result.get("content", "")
                if content.strip():
                    self._call_count += 1
                    self._total_tokens += result.get("usage", {}).get("total_tokens", 0)

                    return LLMResponse(
                        content=content,
                        model=result.get("model", LEGACY_MODEL_LEVELS.get(use_level, {}).get("name", "unknown")),
                        usage=result.get("usage", {}),
                        raw=result,
                        elapsed=elapsed,
                        backend="zai_cli",
                        level_used=use_level,
                    )

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(1 * attempt)

        self._last_error = str(last_error)
        return LLMResponse(
            content=f"[LLM ERROR: {str(last_error)[:200]}]",
            model="error",
            elapsed=0.0,
            backend="none",
        )

    # ═══════════════════════════════════════════════════════
    # OLLAMA CLOUD API
    # ═══════════════════════════════════════════════════════

    def _call_ollama_cloud(
        self, model: str, messages: list[Message],
        temperature: float = 0.5, max_tokens: int = 4096,
    ) -> dict:
        """Ollama Cloud API Call (OpenAI-kompatibel)."""
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests-Bibliothek nicht installiert")

        if not self._api_key:
            raise RuntimeError("Ollama API Key nicht gesetzt")

        url = f"{self._cloud_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = http_requests.post(url, headers=headers, json=payload, timeout=120)

        if resp.status_code != 200:
            raise RuntimeError(f"Ollama Cloud API Fehler {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})

        return {
            "content": content,
            "model": data.get("model", model),
            "usage": usage,
            "raw": data,
        }

    # ═══════════════════════════════════════════════════════
    # OLLAMA LOCAL API
    # ═══════════════════════════════════════════════════════

    def _call_ollama_local(
        self, model: str, messages: list[Message],
        temperature: float = 0.5, max_tokens: int = 4096,
    ) -> dict:
        """Lokaler Ollama API Call."""
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("requests-Bibliothek nicht installiert")

        url = f"{self._local_url}/api/chat"
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "options": {"num_predict": max_tokens},
            "stream": False,
        }

        resp = http_requests.post(url, json=payload, timeout=120)

        if resp.status_code != 200:
            raise RuntimeError(f"Ollama Local API Fehler {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        content = data.get("message", {}).get("content", "")

        return {
            "content": content,
            "model": data.get("model", model),
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            },
            "raw": data,
        }

    # ═══════════════════════════════════════════════════════
    # z-ai CLI FALLBACK
    # ═══════════════════════════════════════════════════════

    def _call_zai_cli(
        self, messages: list[Message],
        system_prompt: Optional[str] = None,
        use_thinking: bool = False,
    ) -> dict:
        """z-ai CLI Chat Call."""
        if not self._zai_available or not self._zai_path:
            raise RuntimeError("z-ai CLI nicht verfügbar")

        # Prompt bauen
        if len(messages) == 1 and messages[0].role == "user":
            user_prompt = messages[0].content
        else:
            parts = []
            for msg in messages:
                if msg.role == "system":
                    parts.append(f"[SYSTEM]: {msg.content}")
                elif msg.role == "user":
                    parts.append(f"[USER]: {msg.content}")
                elif msg.role == "assistant":
                    parts.append(f"[ASSISTANT]: {msg.content}")
            user_prompt = "\n".join(parts)

        sys = system_prompt
        if not sys and messages and messages[0].role == "system":
            sys = messages[0].content

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [self._zai_path, "chat", "--prompt", user_prompt, "--output", tmp_path]
            if sys:
                cmd.extend(["--system", sys])
            if use_thinking:
                cmd.append("--thinking")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                raise RuntimeError(f"z-ai CLI Fehler: {result.stderr[:300]}")

            with open(tmp_path, "r") as f:
                data = json.load(f)

            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            usage = data.get("usage", {})

            return {
                "content": content,
                "model": data.get("model", "glm-4-plus"),
                "usage": usage,
                "raw": data,
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ═══════════════════════════════════════════════════════
    # HELPER
    # ═══════════════════════════════════════════════════════

    def _build_prompts(self, messages: list[Message], system_prompt: Optional[str]) -> tuple[str, str]:
        """Baue user_prompt und sys_prompt aus Messages."""
        sys_prompt = system_prompt or ""
        user_parts = []

        for msg in messages:
            if msg.role == "system" and not sys_prompt:
                sys_prompt = msg.content
            elif msg.role == "user":
                user_parts.append(msg.content)
            elif msg.role == "assistant":
                user_parts.append(f"[Bisherige Antwort]: {msg.content}")

        user_prompt = "\n".join(user_parts) if user_parts else ""
        return user_prompt, sys_prompt

    def _update_health(self, agent_id: str, model_name: str,
                       available: bool, elapsed: float, backend: str,
                       error: str = ""):
        """Health-Status aktualisieren."""
        if agent_id in self._health:
            h = self._health[agent_id]
            h.available = available
            h.response_time = elapsed
            h.backend = backend
            h.last_checked = time.time()
            if error:
                h.error = error
        else:
            self._health[agent_id] = ModelHealth(
                model_name=model_name,
                agent_id=agent_id,
                available=available,
                response_time=elapsed,
                backend=backend,
                last_checked=time.time(),
                error=error,
            )

    # ═══════════════════════════════════════════════════════
    # CONVENIENCE
    # ═══════════════════════════════════════════════════════

    async def chat_async(self, messages: list[Message], system_prompt: Optional[str] = None,
                         level: Optional[int] = None, agent_id: Optional[str] = None) -> LLMResponse:
        """Async-Version von chat."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.chat(messages, system_prompt, level, agent_id)
        )

    def quick_response(self, message: str, agent_id: str = "NEXUS-0") -> str:
        """Schnelle Chat-Antwort. Spart Budget."""
        messages = [
            Message(role="system", content=TOTI_CHAT_PROMPT),
            Message(role="user", content=message),
        ]
        response = self.chat(messages, agent_id=agent_id)
        return response.content

    def web_search(self, query: str, num: int = 5) -> list[dict]:
        """Web-Suche via z-ai function."""
        if not self._zai_available:
            return [{"error": "Web-Suche benötigt z-ai CLI"}]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                self._zai_path, "function",
                "--name", "web_search",
                "--args", json.dumps({"query": query, "num": num}),
                "--output", tmp_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return [{"error": result.stderr[:300]}]

            with open(tmp_path, "r") as f:
                data = json.load(f)
            return data if isinstance(data, list) else [data]

        except subprocess.TimeoutExpired:
            return [{"error": "Web-Suche Timeout (60s)"}]
        except Exception as e:
            return [{"error": f"Web-Suche fehlgeschlagen: {str(e)}"}]
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def get_stats(self) -> dict:
        """Nutzungsstatistiken."""
        return {
            "total_calls": self._call_count,
            "total_tokens": self._total_tokens,
            "active_backend": self._active_backend,
            "cloud_available": self._cloud_available,
            "local_available": self._local_available,
            "zai_available": self._zai_available,
            "api_key_set": bool(self._api_key),
            "last_error": self._last_error,
            "agent_models": {
                aid: cfg.get("model", "?") for aid, cfg in self._agent_models.items()
            },
        }

    def get_model_table(self) -> str:
        """Formatierte Modell-Tabelle für CLI-Ausgabe."""
        lines = []
        lines.append("NEXUS Agent-Team — Optimale Ollama Cloud Zuordnung:")
        lines.append("=" * 70)
        lines.append(f"{'Agent':<12} {'Modell':<28} {'Backend':<14} {'Status'}")
        lines.append("-" * 70)

        for agent_id, cfg in self._agent_models.items():
            model = cfg.get("model", "?")
            health = self._health.get(agent_id)
            if health:
                backend = health.backend or "?"
                status = "OK" if health.available else f"FAIL: {health.error[:30]}"
            else:
                backend = "?"
                status = "nicht getestet"
            lines.append(f"{agent_id:<12} {model:<28} {backend:<14} {status}")

        lines.append("-" * 70)
        lines.append(f"Active Backend: {self._active_backend}")
        lines.append(f"Cloud API Key: {'gesetzt' if self._api_key else 'NICHT GESETZT'}")
        lines.append(f"Local Ollama:  {'verfügbar' if self._local_available else 'nicht erreichbar'}")
        lines.append(f"z-ai CLI:      {'verfügbar' if self._zai_available else 'nicht gefunden'}")
        return "\n".join(lines)
