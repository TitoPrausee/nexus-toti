"""
NEXUS v7 — Config Hot-Reload

Watches config.yaml for changes and reloads settings without restart.
Uses file mtime polling (portable, no dependency on watchdog/inotify).

Features:
- Background thread polls config file for mtime changes
- On change: reloads config, propagates to subsystems
- Debounced: won't reload more than once per check_interval
- Thread-safe: config updates are atomic from the caller's perspective
- Callbacks for subsystem-specific reloads (LLM reconfig, memory bounds, etc.)
"""

import os
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

import yaml

log = logging.getLogger("nexus.config")


@dataclass
class ConfigReloadResult:
    """Result of a config reload operation."""
    success: bool
    changed_keys: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    reload_time: float = 0.0


class ConfigManager:
    """
    Thread-safe config manager with hot-reload.

    Watches config.yaml for changes (via mtime polling) and reloads
    settings without restarting the agent. Subsystems register callbacks
    to be notified when config changes affect them.

    Usage:
        config_mgr = ConfigManager("config.yaml")
        config_mgr.register_callback("llm", on_llm_config_changed)
        config_mgr.start_watcher()

        # Get current config (thread-safe)
        cfg = config_mgr.config
        llm_cfg = cfg.get("llm", {})

        # Manual reload (e.g., on SIGHUP)
        config_mgr.reload()

        # Stop on shutdown
        config_mgr.stop_watcher()
    """

    def __init__(self, config_path: str = "config.yaml", check_interval: float = 5.0):
        """
        Initialize config manager.

        Args:
            config_path: Path to the YAML config file.
            check_interval: Seconds between file modification checks.
        """
        self._config_path = Path(config_path)
        self._check_interval = check_interval
        self._config: dict = {}
        self._last_mtime: float = 0.0
        self._last_size: int = 0
        self._last_reload: float = 0.0
        self._lock = threading.RLock()
        self._watcher_thread: Optional[threading.Thread] = None
        self._running = False
        self._callbacks: dict[str, list[Callable]] = {}
        self._reload_count: int = 0

        # Initial load
        self._load_config()

    # ─── Config Access ──────────────────────────────────

    @property
    def config(self) -> dict:
        """Get current config (thread-safe copy)."""
        with self._lock:
            return dict(self._config)

    def get(self, key: str, default=None):
        """Get a top-level config key (thread-safe)."""
        with self._lock:
            return self._config.get(key, default)

    def get_nested(self, *keys, default=None):
        """
        Get a nested config value, e.g. get_nested("llm", "timeout", default=120).
        Thread-safe.
        """
        with self._lock:
            value = self._config
            for key in keys:
                if not isinstance(value, dict):
                    return default
                value = value.get(key, default)
                if value is None:
                    return default
            return value

    # ─── Reload Logic ───────────────────────────────────

    def _load_config(self) -> bool:
        """Load config from disk. Returns True if file exists and was loaded."""
        try:
            if not self._config_path.exists():
                log.warning(f"Config file not found: {self._config_path}")
                return False

            with open(self._config_path, "r", encoding="utf-8") as f:
                new_config = yaml.safe_load(f) or {}

            stat = self._config_path.stat()
            self._last_mtime = stat.st_mtime
            self._last_size = stat.st_size

            with self._lock:
                old_config = dict(self._config)
                self._config = new_config
                self._reload_count += 1

            # Detect which top-level keys changed
            changed_keys = self._detect_changes(old_config, new_config)

            if changed_keys:
                log.info(f"Config loaded/reloaded. Changed keys: {changed_keys}")
                self._fire_callbacks(changed_keys)

            return True

        except Exception as e:
            log.error(f"Failed to load config: {e}")
            return False

    def _detect_changes(self, old: dict, new: dict) -> list[str]:
        """Detect which top-level keys changed between old and new config."""
        changed = []
        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            if key not in old:
                changed.append(f"+{key}")
            elif key not in new:
                changed.append(f"-{key}")
            elif old[key] != new[key]:
                changed.append(f"~{key}")
        return changed

    def reload(self) -> ConfigReloadResult:
        """
        Force a reload of the config file.

        Returns a ConfigReloadResult indicating what changed.
        Thread-safe and idempotent — calling reload() when nothing
        changed is a no-op.
        """
        start = time.time()

        with self._lock:
            old_config = dict(self._config)

        try:
            if not self._config_path.exists():
                return ConfigReloadResult(
                    success=False,
                    errors=[f"Config file not found: {self._config_path}"],
                    reload_time=time.time() - start,
                )

            with open(self._config_path, "r", encoding="utf-8") as f:
                new_config = yaml.safe_load(f) or {}

            changed_keys = self._detect_changes(old_config, new_config)

            stat = self._config_path.stat()
            self._last_mtime = stat.st_mtime
            self._last_size = stat.st_size

            with self._lock:
                self._config = new_config
                self._reload_count += 1

            if changed_keys:
                log.info(f"Config reloaded: {changed_keys}")
                self._fire_callbacks(changed_keys)
            else:
                log.debug("Config reloaded — no changes detected")

            return ConfigReloadResult(
                success=True,
                changed_keys=changed_keys,
                reload_time=time.time() - start,
            )

        except Exception as e:
            log.error(f"Config reload failed: {e}")
            return ConfigReloadResult(
                success=False,
                errors=[str(e)],
                reload_time=time.time() - start,
            )

    # ─── File Watching ──────────────────────────────────

    def start_watcher(self):
        """
        Start the background config file watcher.

        Polls the config file mtime every check_interval seconds.
        If the file was modified, triggers a reload with debouncing
        (ignores multiple rapid writes within the same check interval).
        """
        if self._watcher_thread and self._watcher_thread.is_alive():
            log.warning("Config watcher already running")
            return

        self._running = True
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            name="nexus-config-watcher",
            daemon=True,
        )
        self._watcher_thread.start()
        log.info(f"Config watcher started (checking every {self._check_interval}s)")

    def stop_watcher(self):
        """Stop the background config file watcher."""
        self._running = False
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=self._check_interval * 2)
        log.info("Config watcher stopped")

    def _watch_loop(self):
        """Background loop that checks for config file changes."""
        while self._running:
            try:
                self._check_for_changes()
            except Exception as e:
                log.error(f"Config watcher error: {e}")
            time.sleep(self._check_interval)

    def _check_for_changes(self):
        """Check if the config file has been modified since last load."""
        if not self._config_path.exists():
            return

        try:
            stat = self._config_path.stat()
        except OSError:
            return

        current_mtime = stat.st_mtime
        current_size = stat.st_size

        # Only reload if mtime or size changed since last load
        if (current_mtime != self._last_mtime or
                current_size != self._last_size):
            # Debounce: ensure file is done writing
            # Check if mtime is stable (not actively being written)
            time.sleep(0.1)
            try:
                stat2 = self._config_path.stat()
                if stat2.st_mtime != current_mtime:
                    # File changed during our check — skip, next cycle will catch it
                    return
            except OSError:
                return

            log.info(f"Config file change detected (mtime={current_mtime}, size={current_size})")
            self.reload()

    # ─── Callbacks ──────────────────────────────────────

    def register_callback(self, subsystem: str, callback: Callable[[dict], None]):
        """
        Register a callback to be called when config changes affect a subsystem.

        The callback receives the full new config dict.
        Callbacks are called synchronously on the watcher thread —
        keep them fast and non-blocking.

        Args:
            subsystem: Name of the subsystem (e.g., 'llm', 'memory', 'telegram').
            callback: Callable that receives the new config dict.
        """
        if subsystem not in self._callbacks:
            self._callbacks[subsystem] = []
        self._callbacks[subsystem].append(callback)
        log.debug(f"Registered config callback for subsystem '{subsystem}'")

    def _fire_callbacks(self, changed_keys: list[str]):
        """Fire registered callbacks for changed config keys."""
        # Determine which subsystems are affected
        subsystem_map = {
            "llm": ["llm", "performance"],
            "memory": ["memory"],
            "soul": ["soul"],
            "telegram": ["telegram"],
            "tools": ["tools"],
            "nexus": ["nexus"],
        }

        affected_subsystems = set()
        for key_change in changed_keys:
            # Strip change prefix (+, -, ~)
            key = key_change.lstrip("+-~")
            for subsystem, managed_keys in subsystem_map.items():
                if key in managed_keys:
                    affected_subsystems.add(subsystem)

        # If any key changed, also notify global watchers
        if changed_keys:
            affected_subsystems.add("global")

        with self._lock:
            current_config = dict(self._config)

        for subsystem in affected_subsystems:
            callbacks = self._callbacks.get(subsystem, [])
            for callback in callbacks:
                try:
                    callback(current_config)
                except Exception as e:
                    log.error(f"Config callback error ({subsystem}): {e}")

    # ─── Stats ──────────────────────────────────────────

    def stats(self) -> dict:
        """Get config manager stats."""
        with self._lock:
            return {
                "config_path": str(self._config_path),
                "reload_count": self._reload_count,
                "last_mtime": self._last_mtime,
                "last_size": self._last_size,
                "watcher_running": self._watcher_thread is not None and self._watcher_thread.is_alive(),
                "registered_subsystems": list(self._callbacks.keys()),
                "check_interval": self._check_interval,
                "top_level_keys": list(self._config.keys()),
            }


# ─── Integration Helper ──────────────────────────────────

def apply_config_to_agent(agent, new_config: dict):
    """
    Apply a new config to an existing NexusAgent instance.

    This is the primary callback for hot-reload — when config changes,
    update the agent's subsystems to match.

    Handles:
    - LLM model config, fallback chain, timeouts
    - Memory limits and thresholds
    - Tool enablement
    - Performance settings

    Args:
        agent: NexusAgent instance to update.
        new_config: Full config dict from config.yaml.
    """
    changes = []

    # ─── LLM Config ─────────────────────────────────────
    llm_cfg = new_config.get("llm", {})
    if llm_cfg:
        llm = agent.llm

        # Update model configurations
        models_cfg = llm_cfg.get("models", {})
        if models_cfg:
            from nexus.core.llm_client import ModelConfig
            for key, mcfg in models_cfg.items():
                if isinstance(mcfg, str):
                    llm.models[key] = ModelConfig(name=mcfg)
                elif isinstance(mcfg, dict):
                    llm.models[key] = ModelConfig(
                        name=mcfg.get("model", "kimi-k2.6:cloud"),
                        temperature=mcfg.get("temperature", 0.7),
                        max_tokens=mcfg.get("max_tokens", 4096),
                    )
            changes.append("llm.models")

        # Update timeouts
        if "timeout" in llm_cfg:
            llm.timeout = llm_cfg["timeout"]
            changes.append("llm.timeout")
        if "max_retries" in llm_cfg:
            llm.max_retries = llm_cfg["max_retries"]
            changes.append("llm.max_retries")

        # Update fallback chain
        fallback_raw = llm_cfg.get("fallback", [])
        if fallback_raw:
            llm.fallback_chain = []
            for entry in fallback_raw:
                found = False
                from nexus.core.llm_client import ModelConfig
                for key, mc in llm.models.items():
                    if mc.name == entry:
                        llm.fallback_chain.append((key, mc))
                        found = True
                        break
                if not found:
                    llm.fallback_chain.append((f"fb_{entry}", ModelConfig(entry)))
            changes.append("llm.fallback")

    # ─── Memory Config ───────────────────────────────────
    mem_cfg = new_config.get("memory", {})
    if mem_cfg:
        mem = agent.memory
        if "l1_max_tokens" in mem_cfg:
            mem.l1_max_tokens = mem_cfg["l1_max_tokens"]
            changes.append("memory.l1_max_tokens")
        if "l2_max_entries" in mem_cfg:
            mem.l2_max_entries = mem_cfg["l2_max_entries"]
            changes.append("memory.l2_max_entries")
        if "l2_max_age_hours" in mem_cfg:
            mem.l2_max_age_hours = mem_cfg["l2_max_age_hours"]
            changes.append("memory.l2_max_age_hours")
        if "l3_max_entries" in mem_cfg:
            mem.l3_max_entries = mem_cfg["l3_max_entries"]
            changes.append("memory.l3_max_entries")
        if "compress_threshold" in mem_cfg:
            mem.compress_threshold = mem_cfg["compress_threshold"]
            changes.append("memory.compress_threshold")

    # ─── Performance Config ──────────────────────────────
    perf_cfg = new_config.get("performance", {})
    if perf_cfg:
        if "max_tool_calls_per_turn" in perf_cfg:
            agent.max_tool_calls = perf_cfg["max_tool_calls_per_turn"]
            changes.append("performance.max_tool_calls_per_turn")
        if "max_tokens_per_turn" in perf_cfg:
            agent.max_tokens_per_turn = perf_cfg["max_tokens_per_turn"]
            changes.append("performance.max_tokens_per_turn")

    if changes:
        log.info(f"Config applied: {changes}")
    return changes