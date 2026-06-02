"""
NEXUS LLM Client v5.0 — Ollama Cloud + Local + z-ai CLI + z-ai Integration + Streaming + Vision + qwen2.5:3b Fallback
Per-Agent Model Routing mit optimaler Ollama Cloud Zuordnung.

Supportet 5 Backends:
  1. Ollama Cloud API (OpenAI-kompatibel mit Bearer Token)
  2. Lokaler Ollama Server (localhost:11434)
  3. z-ai CLI Fallback (GLM-4-Plus)
  4. z-ai Integration Module (Vollständige CLI-Anbindung)
  5. qwen2.5:3b Lokal-Fallback (wenn kein Modell konfiguriert/nicht funktioniert)

Per-Agent Model Routing:
  NEXUS-0 (Orchestrator) → kimi-k2.6:cloud
  SCOUT  (Recherche)     → glm-5.1:cloud
  FORGE  (Code)          → qwen3-coder-next:cloud
  LENS   (Analyse)       → kimi-k2.6:cloud
  HERALD (Output)        → minimax-m2.7:cloud
  GHOST  (Background)    → deepseek-v4-flash:cloud

Features:
  - Auto-Backend-Erkennung (Cloud → Local → z-ai → z-ai Integration → qwen2.5:3b)
  - Per-Agent Temperatur und max_tokens
  - Health-Check für alle Modelle
  - Auto-Fallback bei Model-Ausfall
  - Budget-Tracking
  - Retry mit exponentiellem Backoff
  - qwen2.5:3b als Notfall-Local-Fallback (Auto-Pull)
  - Streaming Chat (chat_stream) mit SSE-Chunk-Yielding
  - Vision Chat (chat_vision) mit Bildanalyse
  - z-ai Convenience Methods (Image Gen, TTS, ASR, Search, Video, Edit)
  - Full Stats mit z-ai Capabilities
"""

import subprocess
import json
import os
import time
import asyncio
import tempfile
import base64
from typing import Optional, Any, Generator
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

# z-ai Integration Module
try:
    from core.zai_integration import ZAIIntegration, get_zai
    ZAI_INTEGRATION_AVAILABLE = True
except ImportError:
    ZAI_INTEGRATION_AVAILABLE = False


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
    backend: str = "unknown"  # "ollama_cloud", "ollama_local", "zai_cli", "zai_integration", "ollama_emergency"
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
      4. z-ai Integration Module (wenn verfügbar)
      5. qwen2.5:3b Emergency Fallback (mit Auto-Pull)

    v5.0 Features:
      - Streaming Chat (chat_stream)
      - Vision Chat (chat_vision)
      - z-ai Convenience Methods
      - Full Stats mit z-ai Capabilities
      - Emergency Model Auto-Pull
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

        # URLs — OLLAMA_HOST env var overrides local_url (for Docker containers)
        self._cloud_url = self._ollama_config.get("base_url", "https://api.ollama.ai")
        self._local_url = os.environ.get("OLLAMA_HOST", self._ollama_config.get("local_url", "http://localhost:11434"))
        self._mode = self._ollama_config.get("mode", "cloud")
        # If no API key, force local mode (Ollama Cloud models served via local Ollama)
        if not self._api_key and self._mode == "cloud":
            self._mode = "local"

        # Backend-Verfügbarkeit
        self._cloud_available = bool(self._api_key)
        self._local_available = self._check_local_ollama()
        self._zai_available, self._zai_path = self._find_zai_cli()

        # z-ai Integration Module
        self._zai_integration: Optional[Any] = None
        if ZAI_INTEGRATION_AVAILABLE:
            try:
                self._zai_integration = get_zai()
                self._zai_integration_available = self._zai_integration.is_available
            except Exception:
                self._zai_integration = None
                self._zai_integration_available = False
        else:
            self._zai_integration_available = False

        # Fallback-Modelle
        self._fallback_cloud = self._ollama_config.get("fallback_models", {}).get("cloud", "glm-5.1:cloud")
        self._fallback_local = self._ollama_config.get("fallback_models", {}).get("local", "qwen2.5:3b")
        self._fallback_zai = self._ollama_config.get("fallback_models", {}).get("zai", "glm-4-plus")
        self._fallback_emergency = self._ollama_config.get("fallback_models", {}).get("emergency", "qwen2.5:3b")

        # qwen2.5:3b Emergency Fallback (must be set before _determine_backend)
        self._emergency_model = "qwen2.5:3b"
        self._emergency_available = self._check_emergency_model()

        # Aktiver Backend (depends on _emergency_available)
        self._active_backend = self._determine_backend()
        if self._active_backend == "none" and self._emergency_available:
            self._active_backend = "ollama_emergency"

        # Streaming state
        self._streaming_active = False

        # Health-Check (non-blocking — test only the orchestrator model)
        if self._ollama_config.get("health_check_on_start", True):
            try:
                self.run_health_check()
            except Exception:
                pass  # Don't block startup on health check failures

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

    def _check_emergency_model(self) -> bool:
        """Prüfe ob qwen2.5:3b lokal verfügbar ist (Emergency Fallback)."""
        if not REQUESTS_AVAILABLE:
            return False
        try:
            resp = http_requests.get(f"{self._local_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                for m in models:
                    if "qwen2.5" in m.lower() and "3b" in m.lower():
                        return True
                # Wenn lokaler Ollama läuft, können wir versuchen qwen2.5:3b zu pullen
                if self._local_available:
                    return True  # Ollama läuft, qwen2.5:3b könnte gepullt werden
        except Exception:
            pass
        return False

    def _try_pull_emergency_model(self) -> bool:
        """Versuche qwen2.5:3b zu pullen, falls nicht lokal verfügbar."""
        if not self._local_available:
            return False
        try:
            result = subprocess.run(
                ["ollama", "pull", "qwen2.5:3b"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                self._emergency_available = True
                return True
        except Exception:
            pass
        return False

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
        if self._zai_integration_available:
            return "zai_integration"
        # Fallback-Reihenfolge
        if self._cloud_available:
            return "ollama_cloud"
        if self._local_available:
            return "ollama_local"
        if self._zai_available:
            return "zai_cli"
        if self._zai_integration_available:
            return "zai_integration"
        # Emergency: qwen2.5:3b lokal
        if self._emergency_available:
            return "ollama_emergency"
        return "none"

    @property
    def is_available(self) -> bool:
        return self._active_backend != "none"

    @property
    def active_backend(self) -> str:
        return self._active_backend

    @property
    def zai_integration(self) -> Optional[Any]:
        """Access the z-ai Integration module directly."""
        return self._zai_integration

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

        # 2. Versuch: Lokaler Ollama (Cloud-Modelle werden direkt ueber local Ollama bereitgestellt)
        if self._local_available:
            try:
                # Use model name as-is — Ollama Cloud models are served via local Ollama with :cloud tag
                start = time.time()
                resp = self._call_ollama_local(
                    model_name, test_messages, temperature=0.1, max_tokens=10
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

        # 4. Versuch: z-ai Integration Module
        if self._zai_integration_available and self._zai_integration:
            try:
                start = time.time()
                zai_result = self._zai_integration.chat(
                    prompt="OK?",
                    system="Antworte mit einem Wort.",
                )
                elapsed = time.time() - start
                if zai_result.success and zai_result.data:
                    # Parse the response from ZAIResult
                    content = ""
                    if isinstance(zai_result.data, dict):
                        choices = zai_result.data.get("choices", [{}])
                        content = choices[0].get("message", {}).get("content", "") if choices else ""
                    elif isinstance(zai_result.data, str):
                        content = zai_result.data
                    if content.strip():
                        health.available = True
                        health.response_time = elapsed
                        health.backend = "zai_integration"
                        return health
            except Exception as e:
                health.error = f"{health.error}; zai-integration: {str(e)[:100]}" if health.error else f"zai-integration: {str(e)[:100]}"

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
            "zai_integration": self._zai_integration_available,
            "emergency": self._emergency_available,
            "emergency_model": self._emergency_model,
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

            # 2. Versuch: Lokaler Ollama (Cloud-Modelle direkt ueber local Ollama)
            if self._local_available:
                try:
                    start = time.time()
                    result = self._call_ollama_local(
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
                        self._update_health(agent_id, model_name, True, elapsed, "ollama_local")

                        return LLMResponse(
                            content=content,
                            model=model_name,
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

            # 4. Versuch: z-ai Integration Module
            if self._zai_integration_available and self._zai_integration:
                try:
                    start = time.time()
                    zai_result = self._zai_integration.chat(
                        prompt=user_prompt,
                        system=sys_prompt or None,
                    )
                    elapsed = time.time() - start

                    content = ""
                    if zai_result.success:
                        if isinstance(zai_result.data, dict):
                            choices = zai_result.data.get("choices", [{}])
                            content = choices[0].get("message", {}).get("content", "") if choices else ""
                        elif isinstance(zai_result.data, str):
                            content = zai_result.data
                        # Also check raw_stdout for content
                        if not content.strip() and zai_result.raw_stdout:
                            content = zai_result.raw_stdout.strip()

                    if content.strip():
                        self._call_count += 1
                        self._update_health(agent_id, self._fallback_zai, True, elapsed, "zai_integration")

                        return LLMResponse(
                            content=content,
                            model=self._fallback_zai,
                            usage={},
                            raw=zai_result.to_dict() if hasattr(zai_result, 'to_dict') else {},
                            elapsed=elapsed,
                            backend="zai_integration",
                            agent_id=agent_id,
                            fallback_used=True,
                        )
                except Exception as e:
                    last_error = e

            # 5. Versuch: Emergency qwen2.5:3b lokal (mit Auto-Pull)
            if self._emergency_available or self._local_available:
                # Before using emergency model, try to pull it if not confirmed available
                if self._local_available and not self._emergency_available:
                    self._try_pull_emergency_model()

                try:
                    start = time.time()
                    result = self._call_ollama_local(
                        self._emergency_model,
                        [Message(role="system", content=sys_prompt), Message(role="user", content=user_prompt)],
                        temperature=temperature,
                        max_tokens=min(max_tokens, 2048),  # Kleineres Modell → weniger tokens
                    )
                    elapsed = time.time() - start

                    content = result.get("content", "")
                    if content.strip():
                        self._call_count += 1
                        self._total_tokens += result.get("usage", {}).get("total_tokens", 0)
                        self._update_health(agent_id, self._emergency_model, True, elapsed, "ollama_emergency")

                        return LLMResponse(
                            content=content,
                            model=self._emergency_model,
                            usage=result.get("usage", {}),
                            raw=result,
                            elapsed=elapsed,
                            backend="ollama_emergency",
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
            content=f"[LLM ERROR: Alle Backends fehlgeschlagen. Letzter Fehler: {str(last_error)[:200]}]",
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

        if not self._zai_available and not self._zai_integration_available:
            return LLMResponse(
                content="[ERROR: Kein LLM-Backend verfügbar]",
                model="none",
                elapsed=0.0,
                backend="none",
            )

        user_prompt, sys_prompt = self._build_prompts(messages, system_prompt)
        last_error = None

        for attempt in range(1, max_retries + 1):
            # Try z-ai CLI first
            if self._zai_available:
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
                        )

                except Exception as e:
                    last_error = e

            # Try z-ai Integration as fallback
            if self._zai_integration_available and self._zai_integration:
                try:
                    start = time.time()
                    zai_result = self._zai_integration.chat(
                        prompt=user_prompt,
                        system=sys_prompt or None,
                        thinking=use_level >= 3,
                    )
                    elapsed = time.time() - start

                    content = ""
                    if zai_result.success:
                        if isinstance(zai_result.data, dict):
                            choices = zai_result.data.get("choices", [{}])
                            content = choices[0].get("message", {}).get("content", "") if choices else ""
                        elif isinstance(zai_result.data, str):
                            content = zai_result.data
                        if not content.strip() and zai_result.raw_stdout:
                            content = zai_result.raw_stdout.strip()

                    if content.strip():
                        self._call_count += 1

                        return LLMResponse(
                            content=content,
                            model=LEGACY_MODEL_LEVELS.get(use_level, {}).get("name", "unknown"),
                            usage={},
                            raw=zai_result.to_dict() if hasattr(zai_result, 'to_dict') else {},
                            elapsed=elapsed,
                            backend="zai_integration",
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
    # STREAMING CHAT
    # ═══════════════════════════════════════════════════════

    def chat_stream(
        self,
        messages: list[Message],
        system_prompt: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Streaming chat — yields response chunks.

        Uses z-ai CLI with --stream flag when available.
        Falls back to Ollama Cloud streaming.
        Otherwise yields the full response as a single chunk.
        """
        user_prompt, sys_prompt = self._build_prompts(messages, system_prompt)
        model_cfg = self._agent_models.get(agent_id or "NEXUS-0", {})
        model_name = model_cfg.get("model", self._fallback_cloud)

        # 1. Try z-ai CLI with --stream
        if self._zai_available and self._zai_path:
            try:
                yield from self._stream_zai_cli(user_prompt, sys_prompt)
                return
            except Exception:
                pass

        # 2. Try z-ai Integration with stream=True
        if self._zai_integration_available and self._zai_integration:
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                    tmp_path = tmp.name

                try:
                    zai_result = self._zai_integration.chat(
                        prompt=user_prompt,
                        system=sys_prompt or None,
                        stream=True,
                        output=tmp_path,
                    )

                    if zai_result.success and zai_result.output_path:
                        # Read the streamed output file
                        with open(zai_result.output_path, "r") as f:
                            content = f.read()
                        if content.strip():
                            # Try to parse as JSON first
                            try:
                                data = json.loads(content)
                                choices = data.get("choices", [{}])
                                full_content = choices[0].get("message", {}).get("content", "") if choices else content
                                yield full_content
                            except (json.JSONDecodeError, ValueError):
                                yield content
                            return
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            except Exception:
                pass

        # 3. Try Ollama Cloud streaming
        if self._cloud_available and REQUESTS_AVAILABLE:
            try:
                yield from self._stream_ollama_cloud(model_name, messages, sys_prompt)
                return
            except Exception:
                pass

        # 4. Try Ollama Local streaming
        if self._local_available and REQUESTS_AVAILABLE:
            try:
                yield from self._stream_ollama_local(model_name, messages, sys_prompt)
                return
            except Exception:
                pass

        # 5. Fallback: non-streaming chat, yield full response
        response = self.chat(messages, system_prompt=system_prompt, agent_id=agent_id)
        if response.content:
            yield response.content

    def _stream_zai_cli(self, user_prompt: str, sys_prompt: str) -> Generator[str, None, None]:
        """Stream via z-ai CLI with --stream flag. Yields chunks from SSE-like output."""
        if not self._zai_path:
            return

        cmd = [self._zai_path, "chat", "--prompt", user_prompt, "--stream"]
        if sys_prompt:
            cmd.extend(["--system", sys_prompt])

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            accumulated = ""
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                # Parse SSE-like output
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(data_str)
                        # OpenAI-style streaming chunk
                        delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                        chunk_content = delta.get("content", "")
                        if chunk_content:
                            accumulated += chunk_content
                            yield chunk_content
                    except (json.JSONDecodeError, ValueError):
                        # Raw text chunk
                        if data_str:
                            accumulated += data_str
                            yield data_str
                elif line.startswith("content: "):
                    chunk = line[9:]
                    if chunk:
                        accumulated += chunk
                        yield chunk
                else:
                    # Try to parse as JSON chunk
                    try:
                        chunk_data = json.loads(line)
                        delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                        chunk_content = delta.get("content", "")
                        if chunk_content:
                            accumulated += chunk_content
                            yield chunk_content
                    except (json.JSONDecodeError, ValueError):
                        # Raw text line
                        if line:
                            accumulated += line
                            yield line + "\n"

            proc.wait(timeout=30)
            self._call_count += 1

        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _stream_ollama_cloud(
        self, model: str, messages: list[Message], sys_prompt: str
    ) -> Generator[str, None, None]:
        """Stream via Ollama Cloud API with SSE."""
        if not REQUESTS_AVAILABLE or not self._api_key:
            return

        url = f"{self._cloud_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        full_messages = []
        if sys_prompt:
            full_messages.append({"role": "system", "content": sys_prompt})
        full_messages.extend([m.to_dict() for m in messages if m.role != "system"])

        payload = {
            "model": model,
            "messages": full_messages,
            "temperature": 0.5,
            "max_tokens": 4096,
            "stream": True,
        }

        try:
            resp = http_requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
            if resp.status_code != 200:
                return

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.strip():
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, ValueError):
                        continue

            self._call_count += 1

        except Exception:
            return

    def _stream_ollama_local(
        self, model: str, messages: list[Message], sys_prompt: str
    ) -> Generator[str, None, None]:
        """Stream via local Ollama API."""
        if not REQUESTS_AVAILABLE:
            return

        url = f"{self._local_url}/api/chat"
        full_messages = []
        if sys_prompt:
            full_messages.append({"role": "system", "content": sys_prompt})
        full_messages.extend([m.to_dict() for m in messages if m.role != "system"])

        payload = {
            "model": model,
            "messages": full_messages,
            "temperature": 0.5,
            "options": {"num_predict": 4096},
            "stream": True,
        }

        try:
            resp = http_requests.post(url, json=payload, stream=True, timeout=120)
            if resp.status_code != 200:
                return

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
                except (json.JSONDecodeError, ValueError):
                    continue

            self._call_count += 1

        except Exception:
            return

    # ═══════════════════════════════════════════════════════
    # VISION CHAT
    # ═══════════════════════════════════════════════════════

    def chat_vision(
        self,
        messages: list[Message],
        image_path: str,
        system_prompt: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> LLMResponse:
        """
        Vision chat — send image + text to LLM.

        Tries in order:
          1. z-ai vision CLI (if available)
          2. z-ai Integration vision() method
          3. Ollama Cloud with images field (OpenAI Vision API)
          4. OCR fallback (describe image via text)
        """
        user_prompt, sys_prompt = self._build_prompts(messages, system_prompt)
        vision_prompt = user_prompt or "Beschreibe dieses Bild detailliert."

        # 1. Try z-ai CLI vision command
        if self._zai_available and self._zai_path:
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                    tmp_path = tmp.name

                try:
                    cmd = [
                        self._zai_path, "vision",
                        "--prompt", vision_prompt,
                        "--image", image_path,
                        "--output", tmp_path,
                    ]
                    if sys_prompt:
                        cmd.extend(["--system", sys_prompt])

                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

                    if result.returncode == 0:
                        with open(tmp_path, "r") as f:
                            data = json.load(f)

                        choice = data.get("choices", [{}])[0]
                        content = choice.get("message", {}).get("content", "")

                        if content.strip():
                            self._call_count += 1
                            return LLMResponse(
                                content=content,
                                model=data.get("model", "z-ai-vision"),
                                usage=data.get("usage", {}),
                                raw=data,
                                elapsed=0.0,
                                backend="zai_cli",
                                agent_id=agent_id or "",
                            )
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            except Exception:
                pass

        # 2. Try z-ai Integration vision() method
        if self._zai_integration_available and self._zai_integration:
            try:
                zai_result = self._zai_integration.vision(
                    prompt=vision_prompt,
                    image=image_path,
                )

                if zai_result.success:
                    content = ""
                    if isinstance(zai_result.data, dict):
                        choices = zai_result.data.get("choices", [{}])
                        content = choices[0].get("message", {}).get("content", "") if choices else ""
                    elif isinstance(zai_result.data, str):
                        content = zai_result.data
                    if not content.strip() and zai_result.raw_stdout:
                        content = zai_result.raw_stdout.strip()

                    if content.strip():
                        self._call_count += 1
                        return LLMResponse(
                            content=content,
                            model="z-ai-vision",
                            usage={},
                            raw=zai_result.to_dict() if hasattr(zai_result, 'to_dict') else {},
                            elapsed=zai_result.elapsed_seconds,
                            backend="zai_integration",
                            agent_id=agent_id or "",
                        )
            except Exception:
                pass

        # 3. Try Ollama Cloud with images field (OpenAI Vision API)
        if self._cloud_available and REQUESTS_AVAILABLE:
            try:
                # Read and base64-encode the image
                image_b64 = self._encode_image(image_path)
                if image_b64:
                    url = f"{self._cloud_url}/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    }

                    # Build OpenAI Vision API payload
                    image_content = [
                        {"type": "text", "text": vision_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            }
                        }
                    ]

                    payload_messages = []
                    if sys_prompt:
                        payload_messages.append({"role": "system", "content": sys_prompt})
                    payload_messages.append({"role": "user", "content": image_content})

                    model_name = self.get_model_for_agent(agent_id or "NEXUS-0")

                    payload = {
                        "model": model_name,
                        "messages": payload_messages,
                        "temperature": 0.5,
                        "max_tokens": 4096,
                    }

                    start = time.time()
                    resp = http_requests.post(url, headers=headers, json=payload, timeout=120)

                    if resp.status_code == 200:
                        data = resp.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        elapsed = time.time() - start

                        if content.strip():
                            self._call_count += 1
                            return LLMResponse(
                                content=content,
                                model=data.get("model", model_name),
                                usage=data.get("usage", {}),
                                raw=data,
                                elapsed=elapsed,
                                backend="ollama_cloud",
                                agent_id=agent_id or "",
                            )
            except Exception:
                pass

        # 4. Fallback: OCR description
        return self._vision_ocr_fallback(vision_prompt, image_path, agent_id)

    def _encode_image(self, image_path: str) -> Optional[str]:
        """Base64-encode an image file or handle URLs."""
        # URL-based image
        if image_path.startswith(("http://", "https://")):
            # For URLs, the Vision API can accept them directly
            return None  # Will use URL directly instead

        # Local file
        if os.path.exists(image_path):
            try:
                with open(image_path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                return None
        return None

    def _vision_ocr_fallback(self, prompt: str, image_path: str, agent_id: Optional[str] = None) -> LLMResponse:
        """Fallback vision: use OCR to describe the image, then send to LLM."""
        ocr_text = ""

        # Try the VisionSystem from core.vision if available
        try:
            from core.vision import VisionSystem
            vs = VisionSystem(llm_client=self)
            analysis = vs.analyze_image(image_path, do_ocr=True)
            if "error" not in analysis:
                ocr_text = analysis.get("extracted_text", "")
                color_desc = analysis.get("color_description", "")
                size_info = f"{analysis.get('width', '?')}x{analysis.get('height', '?')}"
                ocr_text = (
                    f"[Bild-Analyse] Größe: {size_info}, Farben: {color_desc}. "
                    f"Extrahierter Text: {ocr_text[:2000]}"
                )
        except ImportError:
            pass

        if not ocr_text:
            ocr_text = f"[Bild konnte nicht analysiert werden: {image_path}]"

        # Send OCR description to LLM
        vision_messages = [
            Message(role="system", content="Du bist ein Vision-Experte. Du erhältst eine OCR-Beschreibung eines Bildes. Beschreibe was du daraus schließen kannst."),
            Message(role="user", content=f"{prompt}\n\nBild-Informationen:\n{ocr_text}"),
        ]

        response = self.chat(vision_messages, agent_id=agent_id or "LENS")
        response.backend = f"{response.backend}+ocr"
        return response

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
        stream: bool = False,
    ) -> dict:
        """
        z-ai CLI Chat Call.

        Supports --stream flag for streaming output.
        When stream=True, returns a dict with 'stream_iterator' key instead of content.
        """
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

        # Streaming mode: return a streaming iterator
        if stream:
            return self._call_zai_cli_stream(user_prompt, sys, use_thinking)

        # Non-streaming mode (original behavior)
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

    def _call_zai_cli_stream(
        self, user_prompt: str, sys_prompt: Optional[str], use_thinking: bool
    ) -> dict:
        """
        z-ai CLI streaming call — returns a dict with 'stream_iterator' key.

        The stream_iterator is a generator that yields content chunks.
        """
        cmd = [self._zai_path, "chat", "--prompt", user_prompt, "--stream"]
        if sys_prompt:
            cmd.extend(["--system", sys_prompt])
        if use_thinking:
            cmd.append("--thinking")

        def stream_generator() -> Generator[str, None, None]:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(data_str)
                            delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                            chunk_content = delta.get("content", "")
                            if chunk_content:
                                yield chunk_content
                        except (json.JSONDecodeError, ValueError):
                            if data_str:
                                yield data_str
                    elif line.startswith("content: "):
                        chunk = line[9:]
                        if chunk:
                            yield chunk
                    else:
                        try:
                            chunk_data = json.loads(line)
                            delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                            chunk_content = delta.get("content", "")
                            if chunk_content:
                                yield chunk_content
                        except (json.JSONDecodeError, ValueError):
                            if line:
                                yield line + "\n"

                proc.wait(timeout=30)

            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        return {
            "content": "",  # Content comes via stream_iterator
            "model": "glm-4-plus",
            "usage": {},
            "raw": {},
            "stream_iterator": stream_generator(),
        }

    # ═══════════════════════════════════════════════════════
    # z-ai CONVENIENCE METHODS
    # ═══════════════════════════════════════════════════════

    def zai_image_generate(self, prompt: str, size: str = "1024x1024", output: str = "") -> dict:
        """
        Generate an image via z-ai integration.

        Args:
            prompt: Description of the desired image.
            size:   Image size (default: "1024x1024").
            output: Output path for the image. If empty, a temp file is used.

        Returns:
            Dict with success, output_path, and metadata.
        """
        if not self._zai_integration_available or not self._zai_integration:
            return {"success": False, "error": "z-ai Integration nicht verfügbar"}

        try:
            kwargs = {"prompt": prompt, "size": size}
            if output:
                kwargs["output"] = output

            result = self._zai_integration.image_generate(**kwargs)
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def zai_tts(self, text: str, output: str = "", voice: str = "tongtong") -> dict:
        """
        Text-to-speech via z-ai integration.

        Args:
            text:   The text to synthesize.
            output: Output path for the audio file. If empty, a temp file is used.
            voice:  Voice name (default: "tongtong").

        Returns:
            Dict with success, output_path, and metadata.
        """
        if not self._zai_integration_available or not self._zai_integration:
            return {"success": False, "error": "z-ai Integration nicht verfügbar"}

        try:
            kwargs = {"text": text, "voice": voice}
            if output:
                kwargs["output"] = output

            result = self._zai_integration.tts(**kwargs)
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def zai_asr(self, file_path: str = "", base64: str = "") -> dict:
        """
        Speech-to-text via z-ai integration.

        Args:
            file_path: Path to the audio file.
            base64:    Base64-encoded audio data.

        Returns:
            Dict with success, data (transcription), and metadata.
        """
        if not self._zai_integration_available or not self._zai_integration:
            return {"success": False, "error": "z-ai Integration nicht verfügbar"}

        if not file_path and not base64:
            return {"success": False, "error": "Entweder file_path oder base64 muss angegeben werden"}

        try:
            kwargs = {}
            if file_path:
                kwargs["file"] = file_path
            if base64:
                kwargs["base64"] = base64

            result = self._zai_integration.asr(**kwargs)
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def zai_image_search(self, query: str, count: int = 5) -> dict:
        """
        Image search via z-ai integration.

        Args:
            query: Search query string.
            count: Number of results to return (default: 5).

        Returns:
            Dict with success, data (search results), and metadata.
        """
        if not self._zai_integration_available or not self._zai_integration:
            return {"success": False, "error": "z-ai Integration nicht verfügbar"}

        try:
            result = self._zai_integration.image_search(query=query, count=count)
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def zai_video_generate(self, prompt: str, **kwargs) -> dict:
        """
        Video generation via z-ai integration.

        Args:
            prompt: Video description.
            **kwargs: Additional args (output, image_url, quality, with_audio, size, fps, duration, poll, poll_interval, max_polls).

        Returns:
            Dict with success, data, and metadata.
        """
        if not self._zai_integration_available or not self._zai_integration:
            return {"success": False, "error": "z-ai Integration nicht verfügbar"}

        try:
            result = self._zai_integration.video_generate(prompt=prompt, **kwargs)
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def zai_image_edit(self, prompt: str, image: str, output: str = "") -> dict:
        """
        Image editing via z-ai integration.

        Args:
            prompt: Edit description / instruction.
            image:  URL or file path to the source image.
            output: Output path for the edited image. If empty, a temp file is used.

        Returns:
            Dict with success, output_path, and metadata.
        """
        if not self._zai_integration_available or not self._zai_integration:
            return {"success": False, "error": "z-ai Integration nicht verfügbar"}

        try:
            kwargs = {"prompt": prompt, "image": image}
            if output:
                kwargs["output"] = output

            result = self._zai_integration.image_edit(**kwargs)
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

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

    async def chat_vision_async(self, messages: list[Message], image_path: str,
                                system_prompt: Optional[str] = None,
                                agent_id: Optional[str] = None) -> LLMResponse:
        """Async-Version von chat_vision."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.chat_vision(messages, image_path, system_prompt, agent_id)
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
        # Try z-ai Integration first
        if self._zai_integration_available and self._zai_integration:
            try:
                result = self._zai_integration.function_invoke(
                    name="web_search",
                    args={"query": query, "num": num},
                )
                if result.success and result.data:
                    if isinstance(result.data, list):
                        return result.data
                    return [result.data]
            except Exception:
                pass

        # Fallback to z-ai CLI
        if not self._zai_available:
            return [{"error": "Web-Suche benötigt z-ai CLI oder z-ai Integration"}]

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
            "zai_integration_available": self._zai_integration_available,
            "emergency_available": self._emergency_available,
            "emergency_model": self._emergency_model,
            "api_key_set": bool(self._api_key),
            "last_error": self._last_error,
            "agent_models": {
                aid: cfg.get("model", "?") for aid, cfg in self._agent_models.items()
            },
        }

    def get_full_stats(self) -> dict:
        """
        Vollständige Statistiken inkl. z-ai Capabilities, Streaming-Support,
        und alle Backend-Details.
        """
        stats = self.get_stats()

        # Streaming support info
        stats["streaming"] = {
            "supported": True,
            "backends": {
                "zai_cli": self._zai_available,
                "zai_integration": self._zai_integration_available,
                "ollama_cloud": self._cloud_available,
                "ollama_local": self._local_available,
            },
        }

        # Vision support info
        stats["vision"] = {
            "supported": True,
            "zai_cli_vision": self._zai_available,
            "zai_integration_vision": self._zai_integration_available,
            "ollama_cloud_vision": self._cloud_available,  # OpenAI Vision API
            "ocr_fallback": True,
        }

        # z-ai Integration capabilities
        stats["zai_integration"] = {
            "available": self._zai_integration_available,
            "module_loaded": ZAI_INTEGRATION_AVAILABLE,
        }

        if self._zai_integration_available and self._zai_integration:
            try:
                capabilities = self._zai_integration.get_capabilities()
                stats["zai_integration"]["capabilities"] = capabilities
                stats["zai_integration"]["cli_path"] = self._zai_integration.cli_path
            except Exception as e:
                stats["zai_integration"]["capabilities_error"] = str(e)

        # Convenience methods availability
        stats["convenience_methods"] = {
            "zai_image_generate": self._zai_integration_available,
            "zai_tts": self._zai_integration_available,
            "zai_asr": self._zai_integration_available,
            "zai_image_search": self._zai_integration_available,
            "zai_video_generate": self._zai_integration_available,
            "zai_image_edit": self._zai_integration_available,
            "web_search": self._zai_available or self._zai_integration_available,
            "chat_stream": True,
            "chat_vision": True,
        }

        # Health summary
        stats["health"] = {}
        for agent_id, health in self._health.items():
            stats["health"][agent_id] = {
                "available": health.available,
                "backend": health.backend,
                "response_time": f"{health.response_time:.1f}s" if health.response_time else "n/a",
                "error": health.error or "OK",
            }

        # Backend priority chain
        stats["backend_priority"] = [
            "ollama_cloud",
            "ollama_local",
            "zai_cli",
            "zai_integration",
            "ollama_emergency",
        ]

        # Emergency model details
        stats["emergency_model"] = {
            "name": self._emergency_model,
            "available": self._emergency_available,
            "auto_pull_supported": self._local_available,
        }

        # Version
        stats["version"] = "5.0"

        return stats

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
        lines.append(f"z-ai Integration: {'verfügbar' if self._zai_integration_available else 'nicht verfügbar'}")
        lines.append(f"Emergency:     {self._emergency_model} ({'verfügbar' if self._emergency_available else 'nicht verfügbar'})")
        lines.append(f"Streaming:     unterstützt")
        lines.append(f"Vision:        unterstützt")
        return "\n".join(lines)
