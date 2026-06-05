#!/usr/bin/env python3
"""
NEXUS v7 — Main Entry Point
One agent. Soul-driven. Tool-empowered. Stream-fast.

Usage:
    python nexus.py                    # CLI mode
    python nexus.py --telegram         # Telegram bot mode
    python nexus.py --web              # Web UI mode (Tailscale)
    python nexus.py --contributor-bot  # Discord contributor bot mode
    python nexus.py --test             # Quick self-test
"""

import os
import sys
import yaml
import logging
import argparse

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def setup_logging(level: str = "INFO"):
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(config_path: str = "config.yaml") -> dict:
    """Load YAML config."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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

    print("=== NEXUS v7 Self-Test ===\n")

    # 1. Config
    print(f"[OK] Config loaded: {list(config.keys())}")

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

    agent.shutdown()
    print("\n=== Self-Test Complete ===")


def main():
    parser = argparse.ArgumentParser(description="NEXUS v7 — Autonomous AI Agent")
    parser.add_argument("--telegram", action="store_true", help="Run as Telegram bot")
    parser.add_argument("--web", action="store_true", help="Run Web UI server (Tailscale)")
    parser.add_argument("--contributor-bot", action="store_true", help="Run Discord contributor onboarding bot")
    parser.add_argument("--test", action="store_true", help="Run self-test")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    setup_logging(args.log_level)
    config = load_config(args.config)

    if args.test:
        run_test(config)
    elif args.telegram:
        run_telegram(config)
    elif args.web:
        run_web(config)
    elif args.contributor_bot:
        run_contributor_bot()
    else:
        run_cli(config)


if __name__ == "__main__":
    main()