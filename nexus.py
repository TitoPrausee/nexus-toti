#!/usr/bin/env python3
"""
NEXUS v9 — Main Entry Point
Soul-driven AI Agent mit 6-Agent Team. Cloud-only. Think-Act-Delegate.
Hot-reload: config changes are picked up automatically.

Usage:
    python nexus.py                    # CLI mode
    python nexus.py --telegram         # Telegram bot mode
    python nexus.py --web              # Web UI mode (Tailscale)
    python nexus.py --contributor-bot  # Discord contributor bot mode
    python nexus.py --test             # Quick self-test
    python nexus.py --reload           # Force config reload
    python nexus.py --health-check     # Docker HEALTHCHECK (exit 0/1)
    python nexus.py --version          # Print version and exit
"""

import os
import sys
import signal
import logging
import argparse
import importlib
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

__version__ = "9.0"

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")

from nexus.core.config import ConfigManager, apply_config_to_agent
from nexus.core.config_validation import validate_config, print_validation_report


def setup_logging(level: str = "INFO", log_format: str = "text"):
    """
    Configure logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: Output format — 'text' (human-readable) or 'json' (structured).
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove any existing handlers (from basicConfig or prior calls)
    root_logger.handlers.clear()

    if log_format == "json":
        # Structured JSON logging — ideal for Docker log aggregation
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for Docker/DevOps log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


# Global config manager — shared across all subsystems
_config_manager: ConfigManager = None


def get_config_manager() -> ConfigManager:
    """Get the global ConfigManager instance."""
    return _config_manager


def load_config(config_path: str = "config.yaml") -> dict:
    """Load config via ConfigManager. Returns current config dict."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_path, check_interval=5.0)
    return _config_manager.config


def run_cli(config: dict):
    """Run in CLI mode."""
    from nexus.interfaces.cli import main
    main()


def run_telegram(config: dict):
    """Run as Telegram bot."""
    import asyncio
    from nexus.core.agent import NexusAgent
    from nexus.interfaces.telegram_bot import NexusTelegramBot

    agent = NexusAgent(config)
    bot = NexusTelegramBot(agent, config.get("telegram", {}))

    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        bot.stop()


def run_web(config: dict):
    """Run Web UI server for Tailscale access."""
    from nexus.interfaces.web_ui import main as web_main
    web_main()


def run_contributor_bot():
    """Run Discord contributor onboarding bot."""
    from nexus.contributor_bot import main as bot_main
    bot_main()


def run_test(config: dict):
    """Quick self-test."""
    from nexus.core.agent import NexusAgent
    from nexus.core.llm_client import LLMClient, Message
    from nexus.core.config import ConfigManager

    print("=== NEXUS v9 Self-Test ===\n")

    # 1. Config
    print(f"[OK] Config loaded: {list(config.keys())}")

    # 1b. Config hot-reload
    config_mgr = get_config_manager()
    if config_mgr:
        print(f"[OK] Config hot-reload: check_interval={config_mgr.stats()['check_interval']}s")

    # 2. Agent
    agent = NexusAgent(config)
    print(f"[OK] Agent created")
    print(f"     Soul: {agent.soul.personality.get('name', 'Toti')}")
    print(f"     Tools: {', '.join(agent.tools.list_tools())}")
    print(f"     Models: {', '.join(agent.llm.models.keys())}")

    # 3. Memory
    agent.memory.add("system", "Self-test conversation")
    stats = agent.memory.stats()
    print(f"[OK] Memory: L1={stats['l1_entries']}, L2={stats['l2_entries']}, L3={stats['l3_entries']}")

    # 4. Tools
    result = agent.tools.execute("time")
    print(f"[OK] Time tool: {result.output}")

    calc = agent.tools.execute("calculator", expression="2 + 2")
    print(f"[OK] Calculator: 2+2 = {calc.output}")

    # 5. LLM (if available)
    llm = agent.llm
    print(f"\n[??] Testing LLM connection ({llm.mode} mode)...")
    response = llm.chat([Message("user", "Sag nur 'OK'")], model_key="default")
    if response.success:
        print(f"[OK] LLM responded: {response.content[:50]} (took {response.elapsed:.1f}s)")
    else:
        print(f"[FAIL] LLM error: {response.error}")
        print("       Check OLLAMA_API_KEY and OLLAMA_HOST env vars.")

    # 6. Soul
    print(f"[OK] Soul system prompt ({len(agent.soul.get_system_prompt())} chars)")

    # 7. Config hot-reload test
    if config_mgr:
        result = config_mgr.reload()
        print(f"[OK] Config reload: success={result.success}, changes={result.changed_keys}")

    agent.shutdown()
    print("\n=== Self-Test Complete ===")


def print_version():
    """Print version and exit."""
    print(f"NEXUS v{__version__}")


def run_health_check(config_path: str = "config.yaml") -> bool:
    """
    Docker HEALTHCHECK endpoint.
    Validates that all core modules are importable and config is present.
    Exits 0 (healthy) or 1 (unhealthy).
    """
    errors = []

    # 1. Config file exists and is valid YAML
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            import yaml
            cfg = yaml.safe_load(f)
            if not isinstance(cfg, dict):
                errors.append(f"Config file is not a valid YAML dict")
            else:
                # Schema validation — check config structure
                result = validate_config(cfg)
                if not result.ok:
                    errors.extend(result.errors)
    except FileNotFoundError:
        errors.append(f"Config file not found: {config_path}")
    except Exception as e:
        errors.append(f"Config parse error: {e}")

    # 2. Core modules importable
    required_modules = [
        ("nexus.core.agent", "NexusAgent"),
        ("nexus.core.config", "ConfigManager"),
        ("nexus.core.llm_client", "LLMClient"),
        ("nexus.core.memory", "MemorySystem"),
        ("nexus.core.tools", "ToolRegistry"),
        ("nexus.soul", "SoulEngine"),
    ]
    for module_name, class_name in required_modules:
        try:
            mod = importlib.import_module(module_name)
            if not hasattr(mod, class_name):
                errors.append(f"Module {module_name} missing class {class_name}")
        except ImportError as e:
            errors.append(f"Cannot import {module_name}: {e}")

    # 3. Data directories exist or are creatable
    for d in ["data/memory", "nexus/soul"]:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), d)
        if not os.path.isdir(path):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as e:
                errors.append(f"Cannot create directory {d}: {e}")

    if errors:
        for err in errors:
            print(f"UNHEALTHY: {err}", file=sys.stderr)
        return False

    print("healthy")
    return True


def print_startup_banner(config: dict):
    """Print startup banner with version, mode, and config overview."""
    nexus_cfg = config.get("nexus", {})
    llm_cfg = config.get("llm", {})
    mem_cfg = config.get("memory", {})
    tool_cfg = config.get("tools", {})

    banner = f"""
╔═══════════════════════════════════════════════════════╗
║  NEXUS v{__version__} — 6-Agent Soul-Driven AI                  ║
╠═══════════════════════════════════════════════════════╣
║  Name:     {nexus_cfg.get('name', 'Toti'):<42s}║
║  Language: {nexus_cfg.get('language', 'de'):<42s}║
║  LLM Mode: {llm_cfg.get('mode', 'cloud'):<42s}║
║  Model:    {llm_cfg.get('default_model', 'unknown'):<42s}║
║  Memory:   L1={mem_cfg.get('l1_max_tokens', '?')} L2={mem_cfg.get('l2_max_entries', '?')} L3={mem_cfg.get('l3_max_entries', '?')}                            ║
║  Tools:    {', '.join(tool_cfg.get('enabled', [])[:5]):<42s}║
║  Time:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<42s}║
║  Log:      {os.environ.get('NEXUS_LOG_LEVEL', 'INFO')} / {os.environ.get('NEXUS_LOG_FORMAT', 'text'):<37s}║
╚═══════════════════════════════════════════════════════╝"""
    print(banner)


def validate_startup(config_path: str = "config.yaml") -> list[str]:
    """
    Validate startup prerequisites.
    Returns a list of warning messages (empty = all good).
    """
    warnings = []

    # Check critical env vars
    critical_env = {
        "OLLAMA_HOST": False,  # Has sensible default
    }
    recommended_env = {
        "OLLAMA_API_KEY": "Required for cloud LLM mode",
        "NEXUS_TG_TOKEN": "Required for Telegram bot mode",
    }

    for var, required in critical_env.items():
        if not os.environ.get(var):
            if required:
                warnings.append(f"Missing critical env var: {var}")

    for var, reason in recommended_env.items():
        if not os.environ.get(var):
            warnings.append(f"Missing optional env var: {var} ({reason})")

    # Config sections check
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            import yaml
            cfg = yaml.safe_load(f)
            if cfg and "llm" not in cfg:
                warnings.append("Config: 'llm' section missing — LLM calls will fail")
            if cfg and "soul" not in cfg:
                warnings.append("Config: 'soul' section missing — soul engine disabled")
    except Exception:
        pass  # ConfigManager will handle the full error

    return warnings


# Global shutdown flag for SIGTERM handling
_shutdown_requested = False


def _register_signal_handlers(agent, config_mgr: ConfigManager):
    """Register OS signal handlers for hot-reload and graceful shutdown.

    SIGHUP:  Reload config without restart (Unix convention).
    SIGUSR1: Reload and show stats.
    SIGTERM: Graceful shutdown (Docker sends this on stop/restart).
    """
    global _shutdown_requested
    import logging
    log = logging.getLogger("nexus")

    def sighup_handler(signum, frame):
        log.info("SIGHUP received — reloading config...")
        result = config_mgr.reload()
        if result.success:
            changes = apply_config_to_agent(agent, config_mgr.config)
            log.info(f"Config reloaded: {changes if changes else 'no changes'}")
        else:
            log.error(f"Config reload failed: {result.errors}")

    def sigusr1_handler(signum, frame):
        log.info("SIGUSR1 received — config stats:")
        stats = config_mgr.stats()
        for k, v in stats.items():
            log.info(f"  {k}: {v}")

    def sigterm_handler(signum, frame):
        log.info("SIGTERM received — shutting down gracefully...")
        _shutdown_requested = True
        try:
            agent.shutdown()
        except Exception as e:
            log.error(f"Error during shutdown: {e}")
        config_mgr.stop_watcher()
        sys.exit(0)

    try:
        signal.signal(signal.SIGHUP, sighup_handler)
        log.info("Registered SIGHUP for config hot-reload")
    except (AttributeError, OSError):
        # Windows or no SIGHUP — that's fine
        pass

    try:
        signal.signal(signal.SIGUSR1, sigusr1_handler)
        log.info("Registered SIGUSR1 for config stats")
    except (AttributeError, OSError):
        pass

    signal.signal(signal.SIGTERM, sigterm_handler)
    log.info("Registered SIGTERM for graceful shutdown")


def main():
    parser = argparse.ArgumentParser(description="NEXUS v9 — 6-Agent Soul-Driven AI")
    parser.add_argument("--telegram", action="store_true", help="Run as Telegram bot")
    parser.add_argument("--web", action="store_true", help="Run Web UI server (Tailscale)")
    parser.add_argument("--contributor-bot", action="store_true", help="Run Discord contributor onboarding bot")
    parser.add_argument("--test", action="store_true", help="Run self-test")
    parser.add_argument("--reload", action="store_true", help="Force config reload and show changes")
    parser.add_argument("--health-check", action="store_true", help="Docker health check (exit 0=healthy, 1=unhealthy)")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--log-level", default=os.environ.get("NEXUS_LOG_LEVEL", "INFO"), help="Log level (env: NEXUS_LOG_LEVEL)")
    parser.add_argument("--log-format", default=os.environ.get("NEXUS_LOG_FORMAT", "text"), choices=["text", "json"], help="Log format: text or json (env: NEXUS_LOG_FORMAT)")
    args = parser.parse_args()

    # --version: print and exit
    if args.version:
        print_version()
        return

    # --health-check: validate and exit
    if args.health_check:
        healthy = run_health_check(args.config)
        sys.exit(0 if healthy else 1)

    setup_logging(args.log_level, args.log_format)

    global _config_manager
    _config_manager = ConfigManager(args.config, check_interval=5.0)
    config = _config_manager.config

    # Print startup banner
    print_startup_banner(config)

    # Validate config schema
    validation = validate_config(config)
    print_validation_report(validation)
    if not validation.ok:
        logging.getLogger("nexus").error(f"Config validation failed: {validation.errors}")
        sys.exit(1)

    # Validate startup prerequisites (env vars, dirs)
    warnings = validate_startup(args.config)
    for w in warnings:
        logging.getLogger("nexus").warning(f"STARTUP WARNING: {w}")

    if args.reload:
        # One-shot reload and display
        result = _config_manager.reload()
        if result.success:
            print(f"Config reloaded successfully.")
            print(f"Changed keys: {result.changed_keys}")
            print(f"Stats: {_config_manager.stats()}")
        else:
            print(f"Config reload failed: {result.errors}")
        return

    if args.test:
        run_test(config)
    elif args.telegram:
        from nexus.core.agent import NexusAgent
        from nexus.core.heartbeat import HeartbeatSystem
        from nexus.core.project_tracker import ProjectTracker
        agent = NexusAgent(config)

        # Start autonomous heartbeat (health checks, memory cleanup)
        heartbeat = HeartbeatSystem(agent, config)
        heartbeat.start()

        # Load project tracker for context injection
        tracker = ProjectTracker(config.get("project_tracker", {}))
        agent.project_tracker = tracker

        # Register hot-reload callback for LLM config changes
        def on_config_change(new_config: dict):
            changes = apply_config_to_agent(agent, new_config)
            if changes:
                import logging
                logging.getLogger("nexus").info(f"Hot-reload applied: {changes}")

        _config_manager.register_callback("llm", on_config_change)
        _config_manager.register_callback("memory", on_config_change)
        _config_manager.register_callback("global", on_config_change)

        # Start watching for config changes
        _config_manager.start_watcher()

        # Register SIGHUP for manual reload
        _register_signal_handlers(agent, _config_manager)

        from nexus.interfaces.telegram_bot import NexusTelegramBot
        bot = NexusTelegramBot(agent, config.get("telegram", {}))

        try:
            import asyncio
            asyncio.run(bot.start())
        except KeyboardInterrupt:
            bot.stop()
        finally:
            heartbeat.stop()
            _config_manager.stop_watcher()

    elif args.web:
        from nexus.interfaces.web_ui import main as web_main
        web_main()
    elif args.contributor_bot:
        run_contributor_bot()
    else:
        run_cli(config)


if __name__ == "__main__":
    main()