#!/usr/bin/env python3
"""
NEXUS — Toti Agent System v3.0
Ollama Cloud · Per-Agent Model Routing · Error Learning · 22 Tools · 10 Skills

Agent-Team:
  NEXUS-0 (Orchestrator) → kimi-k2.6:cloud
  SCOUT  (Recherche)     → glm-5.1:cloud
  FORGE  (Code)          → qwen3-coder-next:cloud
  LENS   (Analyse)       → kimi-k2.6:cloud
  HERALD (Output)        → minimax-m2.7:cloud
  GHOST  (Background)    → deepseek-v4-flash:cloud

Usage:
  python nexus.py                          # Interactive CLI
  python nexus.py --task "..."             # Single task
  python nexus.py --telegram               # Telegram bot
  python nexus.py --session ID             # Resume session
  python nexus.py --health                 # LLM health check
  python nexus.py --models                 # Show model table
  python nexus.py --setup                  # Ollama Cloud Setup
  python nexus.py --setup --api-key KEY    # API Key setzen
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="NEXUS Toti Agent System v3.0 — Ollama Cloud")
    parser.add_argument("--task", "-t", help="Single task (non-interactive)", type=str)
    parser.add_argument("--telegram", help="Start Telegram bot", action="store_true")
    parser.add_argument("--telegram-token", help="Telegram bot token", type=str)
    parser.add_argument("--telegram-users", help="Authorized user IDs (comma-separated)", type=str)
    parser.add_argument("--session", "-s", help="Resume session by ID", type=str)
    parser.add_argument("--model", help="Override default model", default=None)
    parser.add_argument("--thinking", help="Enable chain-of-thought", action="store_true")
    parser.add_argument("--max-steps", help="Max steps per task (default: 10)", type=int, default=10)
    parser.add_argument("--health", help="Run LLM health check and exit", action="store_true")
    parser.add_argument("--models", help="Show model routing table", action="store_true")
    parser.add_argument("--setup", help="Run Ollama Cloud setup", action="store_true")
    parser.add_argument("--api-key", help="Ollama Cloud API Key (for --setup)", type=str)
    parser.add_argument("--test-models", help="Test all models and exit", action="store_true")
    parser.add_argument("--version", "-v", help="Show version", action="store_true")

    args = parser.parse_args()

    if args.version:
        print("NEXUS Toti Agent System v3.0")
        print("Ollama Cloud · 6 Agent-Modelle · Error Learning · 22 Tools · 10 Skills")
        print()
        print("Agent-Team:")
        print("  NEXUS-0  → kimi-k2.6:cloud       (Orchestrator)")
        print("  SCOUT    → glm-5.1:cloud          (Recherche)")
        print("  FORGE    → qwen3-coder-next:cloud (Coding)")
        print("  LENS     → kimi-k2.6:cloud        (Analyse)")
        print("  HERALD   → minimax-m2.7:cloud      (Output)")
        print("  GHOST    → deepseek-v4-flash:cloud (Background)")
        return

    # ─── Ollama Setup ───
    if args.setup:
        from ollama_setup import OllamaSetup
        setup = OllamaSetup()
        if args.api_key:
            setup.run_api_key_setup(args.api_key)
        else:
            setup.run_interactive()
        return

    # ─── Model Table ───
    if args.models:
        from core.llm_client import LLMClient
        llm = LLMClient()
        print(llm.get_model_table())
        return

    # ─── Health Check ───
    if args.health:
        from core.llm_client import LLMClient
        llm = LLMClient()
        print("NEXUS LLM Health Check v3.0 — Ollama Cloud")
        print("=" * 50)
        print(llm.get_model_table())
        print()
        health = llm.get_health_status()
        backend = health.get("_backend", {})
        print(f"Active Backend: {backend.get('active', '?')}")
        print(f"Cloud API:      {'OK' if backend.get('cloud') else 'NICHT VERFÜGBAR'}")
        print(f"Local Ollama:   {'OK' if backend.get('local') else 'NICHT VERFÜGBAR'}")
        print(f"z-ai CLI:       {'OK' if backend.get('zai_cli') else 'NICHT VERFÜGBAR'}")
        print(f"API Key:        {'gesetzt' if backend.get('api_key_set') else 'NICHT GESETZT'}")
        return

    # ─── Test Models ───
    if args.test_models:
        from ollama_setup import OllamaSetup
        setup = OllamaSetup()
        setup.run_test_only()
        return

    # ─── Telegram Mode ───
    if args.telegram:
        token = args.telegram_token or os.environ.get("NEXUS_TG_TOKEN")
        if not token:
            print("ERROR: Telegram token required. Set NEXUS_TG_TOKEN or use --telegram-token")
            sys.exit(1)

        authorized = None
        if args.telegram_users:
            try:
                authorized = [int(uid.strip()) for uid in args.telegram_users.split(",")]
            except ValueError:
                print("ERROR: Invalid user IDs")
                sys.exit(1)

        from interfaces.telegram_bot import NexusTelegramBot
        bot = NexusTelegramBot(token=token, authorized_users=authorized)
        bot.run()
        return

    # ─── CLI Mode ───
    from interfaces.cli import NexusCLI

    cli = NexusCLI(session_id=args.session)

    if args.max_steps:
        cli.guards.max_steps = args.max_steps

    if args.session:
        loaded = cli.memory.session_load(args.session)
        if loaded:
            cli.print(f"  [toti.success]Session {args.session} geladen.[/]")
        else:
            cli.print(f"  [toti.warning]Session {args.session} nicht gefunden.[/]")

    if args.task:
        response = cli.process_single(args.task)
        print(response)
    else:
        cli.run()


if __name__ == "__main__":
    main()
