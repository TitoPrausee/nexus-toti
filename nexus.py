#!/usr/bin/env python3
"""
NEXUS — Toti Agent System v2.0
Powered by GLM (z-ai) · Hermes-inspired Architecture · Error Learning · 22 Tools · 10 Skills

Usage:
  python nexus.py                    # Interactive CLI
  python nexus.py --task "..."       # Single task
  python nexus.py --telegram         # Telegram bot
  python nexus.py --session ID       # Resume session
  python nexus.py --health           # LLM health check only
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="NEXUS Toti Agent System v2.0")
    parser.add_argument("--task", "-t", help="Single task (non-interactive)", type=str)
    parser.add_argument("--telegram", help="Start Telegram bot", action="store_true")
    parser.add_argument("--telegram-token", help="Telegram bot token", type=str)
    parser.add_argument("--telegram-users", help="Authorized user IDs (comma-separated)", type=str)
    parser.add_argument("--session", "-s", help="Resume session by ID", type=str)
    parser.add_argument("--model", help="GLM model (default: glm-4-plus)", default="glm-4-plus")
    parser.add_argument("--thinking", help="Enable chain-of-thought", action="store_true")
    parser.add_argument("--max-steps", help="Max steps per task (default: 10)", type=int, default=10)
    parser.add_argument("--health", help="Run LLM health check and exit", action="store_true")
    parser.add_argument("--version", "-v", help="Show version", action="store_true")

    args = parser.parse_args()

    if args.version:
        print("NEXUS Toti Agent System v2.0")
        print("22 Tools · 10 Skills · Error Learning · GLM Powered")
        return

    # ─── Health Check Only ───
    if args.health:
        from core.llm_client import LLMClient
        llm = LLMClient()
        print("NEXUS LLM Health Check v2.0")
        print("=" * 40)
        health = llm.run_health_check()
        for level, h in health.items():
            status = "✓ OK" if h.available else f"✗ {h.error}"
            rt = f"{h.response_time:.1f}s" if h.response_time else "n/a"
            print(f"  Level {level} ({h.model_name}): {status} ({rt})")
        stats = llm.get_stats()
        print(f"\nOllama Available: {'Yes' if stats.get('ollama_available', stats.get('cli_available', False)) else 'No'}")
        print(f"Ollama Host: {stats.get('ollama_host', stats.get('cli_path', 'n/a'))}")
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

    if args.model:
        cli.llm.default_level = 2  # Will use GLM standard
    if args.thinking:
        cli.llm.default_level = 3
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
