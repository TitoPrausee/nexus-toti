#!/usr/bin/env python3
"""
NEXUS — Toti Agent System v5.0
z.ai CLI · Ollama Cloud · Per-Agent Model Routing · Error Learning · 44 Tools · 10 Skills
RAG · ReAct Loop · Self-Reflection · Planning · AI Media (Image/Video/TTS/ASR) · Vision

Agent-Team:
  NEXUS-0 (Orchestrator) → kimi-k2.6:cloud
  SCOUT  (Recherche)     → glm-5.1:cloud
  FORGE  (Code)          → qwen3-coder-next:cloud
  LENS   (Analyse)       → kimi-k2.6:cloud
  HERALD (Output)        → minimax-m2.7:cloud
  GHOST  (Background)    → deepseek-v4-flash:cloud

z.ai CLI Integration (9 Befehle):
  chat · vision · tts · asr · image · image-edit · image-search · video · function

Hermes-Aspekte:
  RAG (Document Ingest + TF-IDF Retrieval)
  ReAct Loop (Thought → Action → Observation)
  Self-Reflection (Quality Evaluation + Improvement)
  Planning Engine (Step-by-step Task Decomposition)
  Self-Correction (Code Error → Fix)

Usage:
  python nexus.py                          # Interactive CLI
  python nexus.py --task "..."             # Single task
  python nexus.py --react "..."            # ReAct loop mode
  python nexus.py --plan "..."             # Plan + execute
  python nexus.py --rag-query "..."        # Query RAG knowledge base
  python nexus.py --rag-ingest PATH        # Ingest file into RAG
  python nexus.py --image "prompt"         # Generate AI image
  python nexus.py --speak "text"           # Text to speech
  python nexus.py --vision PATH_OR_URL     # Analyze image
  python nexus.py --telegram               # Telegram bot
  python nexus.py --session ID             # Resume session
  python nexus.py --health                 # LLM health check
  python nexus.py --models                 # Show model table
  python nexus.py --zai-capabilities       # Show z.ai CLI capabilities
  python nexus.py --setup                  # Ollama Cloud Setup
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="NEXUS Toti Agent System v5.0 — z.ai + Ollama Cloud + Hermes")
    parser.add_argument("--task", "-t", help="Single task (non-interactive)", type=str)
    parser.add_argument("--react", help="Use ReAct loop for task", type=str)
    parser.add_argument("--plan", help="Plan and execute task", type=str)
    parser.add_argument("--rag-query", help="Query RAG knowledge base", type=str)
    parser.add_argument("--rag-ingest", help="Ingest file/URL into RAG", type=str)
    parser.add_argument("--image", help="Generate AI image (prompt)", type=str)
    parser.add_argument("--image-size", help="Image size (default: 1024x1024)", default="1024x1024")
    parser.add_argument("--speak", help="Text to speech", type=str)
    parser.add_argument("--vision", help="Analyze image (path or URL)", type=str)
    parser.add_argument("--video", help="Generate AI video (prompt)", type=str)
    parser.add_argument("--telegram", help="Start Telegram bot", action="store_true")
    parser.add_argument("--telegram-token", help="Telegram bot token", type=str)
    parser.add_argument("--telegram-users", help="Authorized user IDs (comma-separated)", type=str)
    parser.add_argument("--session", "-s", help="Resume session by ID", type=str)
    parser.add_argument("--model", help="Override default model", default=None)
    parser.add_argument("--thinking", help="Enable chain-of-thought", action="store_true")
    parser.add_argument("--max-steps", help="Max steps per task (default: 10)", type=int, default=10)
    parser.add_argument("--health", help="Run LLM health check and exit", action="store_true")
    parser.add_argument("--models", help="Show model routing table", action="store_true")
    parser.add_argument("--zai-capabilities", help="Show z.ai CLI capabilities", action="store_true")
    parser.add_argument("--setup", help="Run Ollama Cloud setup", action="store_true")
    parser.add_argument("--api-key", help="Ollama Cloud API Key (for --setup)", type=str)
    parser.add_argument("--test-models", help="Test all models and exit", action="store_true")
    parser.add_argument("--version", "-v", help="Show version", action="store_true")

    args = parser.parse_args()

    if args.version:
        print("NEXUS Toti Agent System v5.0")
        print("z.ai CLI · Ollama Cloud · 6 Agent-Modelle · Error Learning · 44 Tools · 10 Skills")
        print("RAG · ReAct Loop · Self-Reflection · Planning · AI Media · Vision")
        print()
        print("Agent-Team:")
        print("  NEXUS-0  → kimi-k2.6:cloud       (Orchestrator)")
        print("  SCOUT    → glm-5.1:cloud          (Recherche)")
        print("  FORGE    → qwen3-coder-next:cloud (Coding)")
        print("  LENS     → kimi-k2.6:cloud        (Analyse)")
        print("  HERALD   → minimax-m2.7:cloud      (Output)")
        print("  GHOST    → deepseek-v4-flash:cloud (Background)")
        print()
        print("z.ai CLI: chat · vision · tts · asr · image · image-edit · image-search · video · function")
        print("Emergency Fallback: qwen2.5:3b (lokal)")
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
        print("NEXUS LLM Health Check v5.0 — Ollama Cloud + z.ai + Emergency")
        print("=" * 60)
        print(llm.get_model_table())
        print()
        health = llm.get_health_status()
        backend = health.get("_backend", {})
        print(f"Active Backend: {backend.get('active', '?')}")
        print(f"Cloud API:      {'OK' if backend.get('cloud') else 'NICHT VERFÜGBAR'}")
        print(f"Local Ollama:   {'OK' if backend.get('local') else 'NICHT VERFÜGBAR'}")
        print(f"z-ai CLI:       {'OK' if backend.get('zai_cli') else 'NICHT VERFÜGBAR'}")
        print(f"Emergency:      {'OK' if backend.get('emergency') else 'NICHT VERFÜGBAR'} ({backend.get('emergency_model', '?')})")
        print(f"API Key:        {'gesetzt' if backend.get('api_key_set') else 'NICHT GESETZT'}")

        # z.ai capabilities
        try:
            from core.zai_integration import get_zai
            zai = get_zai()
            if zai.is_available:
                print(f"\nz.ai CLI:       VERFÜGBAR ({zai.cli_path})")
                caps = zai.get_capabilities()
                for cmd, info in caps.get("commands", {}).items():
                    print(f"  {cmd}: {info.get('description', '?')}")
            else:
                print(f"\nz.ai CLI:       NICHT GEFUNDEN")
        except ImportError:
            print(f"\nz.ai Integration: Modul nicht verfügbar")
        return

    # ─── z.ai Capabilities ───
    if args.zai_capabilities:
        try:
            from core.zai_integration import get_zai
            zai = get_zai()
            caps = zai.get_capabilities()
            print("NEXUS z.ai CLI Integration — Capabilities")
            print("=" * 60)
            print(f"CLI Available: {caps.get('cli_available', False)}")
            print(f"CLI Path:      {caps.get('cli_path', 'N/A')}")
            print()
            for cmd, info in caps.get("commands", {}).items():
                desc = info.get("description", "?")
                timeout = info.get("timeout_seconds", "?")
                has_sync = info.get("sync", False)
                has_async = info.get("async", False)
                modes = []
                if has_sync:
                    modes.append("sync")
                if has_async:
                    modes.append("async")
                print(f"  {cmd:<20} {desc}")
                print(f"  {'':20} Timeout: {timeout}s | Modes: {', '.join(modes)}")
                for param_name, param_info in info.get("params", {}).items():
                    ptype = param_info.get("type", "?")
                    required = "required" if param_info.get("required") else "optional"
                    default = param_info.get("default", "")
                    note = param_info.get("note", "")
                    line = f"    {param_name} ({ptype}, {required})"
                    if default:
                        line += f" default={default}"
                    if note:
                        line += f" — {note}"
                    print(line)
                print()
        except ImportError:
            print("z.ai Integration Modul nicht verfügbar")
        return

    # ─── Test Models ───
    if args.test_models:
        from ollama_setup import OllamaSetup
        setup = OllamaSetup()
        setup.run_test_only()
        return

    # ─── RAG Query ───
    if args.rag_query:
        try:
            from core.rag import RAGSystem
            rag = RAGSystem()
            results = rag.search(args.rag_query, top_k=5)
            if not results:
                print("Keine Ergebnisse. Ingeste zuerst Dokumente mit --rag-ingest.")
            else:
                print(f"RAG Results für: {args.rag_query}")
                print("=" * 60)
                for i, r in enumerate(results, 1):
                    print(f"\n[{i}] Score: {r['score']:.4f} | Source: {r['source']}")
                    print(f"    {r['text'][:200]}...")
        except ImportError:
            print("RAG Modul nicht verfügbar")
        return

    # ─── RAG Ingest ───
    if args.rag_ingest:
        try:
            from core.rag import RAGSystem
            rag = RAGSystem()
            source = args.rag_ingest
            if source.startswith(("http://", "https://")):
                result = rag.ingest_url(source)
            else:
                result = rag.ingest_file(source)
            print(f"RAG Ingestion: {result}")
            rag.save()
        except ImportError:
            print("RAG Modul nicht verfügbar")
        return

    # ─── AI Image Generation ───
    if args.image:
        try:
            from core.zai_integration import get_zai
            zai = get_zai()
            output = f"/tmp/nexus_image_{os.getpid()}.png"
            result = zai.image_generate(args.image, output=output, size=args.image_size)
            if result.success:
                print(f"🖼️ Bild generiert: {result.output_path}")
            else:
                print(f"❌ Fehler: {result.error}")
        except ImportError:
            print("z.ai Integration nicht verfügbar")
        return

    # ─── Text to Speech ───
    if args.speak:
        try:
            from core.zai_integration import get_zai
            zai = get_zai()
            output = f"/tmp/nexus_tts_{os.getpid()}.wav"
            result = zai.tts(args.speak, output=output)
            if result.success:
                print(f"🔊 Audio generiert: {result.output_path}")
            else:
                print(f"❌ Fehler: {result.error}")
        except ImportError:
            print("z.ai Integration nicht verfügbar")
        return

    # ─── Vision Analysis ───
    if args.vision:
        try:
            from core.vision import VisionSystem
            from core.llm_client import LLMClient
            llm = LLMClient()
            vision = VisionSystem(llm_client=llm)
            result = vision.analyze_image(args.vision)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:3000])
        except ImportError:
            print("Vision Modul nicht verfügbar")
        return

    # ─── AI Video Generation ───
    if args.video:
        try:
            from core.zai_integration import get_zai
            zai = get_zai()
            result = zai.video_generate(args.video, poll=True)
            if result.success:
                print(f"🎬 Video generiert: {result.data}")
            else:
                print(f"❌ Fehler: {result.error}")
        except ImportError:
            print("z.ai Integration nicht verfügbar")
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
    elif args.react:
        # ReAct loop mode
        try:
            from core.reflection import ReflectionEngine
            from core.llm_client import LLMClient
            from core.tools import ToolRegistry
            llm = LLMClient()
            tools = ToolRegistry()
            engine = ReflectionEngine(llm)
            result = engine.react_loop(args.react, tools=tools, max_steps=5)
            print(f"🤔 ReAct Loop: {result.total_steps} Steps, {'Erfolgreich' if result.success else 'Nicht abgeschlossen'}")
            print(f"⏱️ Zeit: {result.elapsed:.1f}s")
            print(f"\n📋 Final Answer:\n{result.final_answer}")
        except ImportError as e:
            print(f"ReAct Engine nicht verfügbar: {e}")
    elif args.plan:
        # Planning mode
        try:
            from core.reflection import PlanningEngine
            from core.llm_client import LLMClient
            llm = LLMClient()
            planner = PlanningEngine(llm)
            result = planner.plan_and_evaluate(args.plan)
            plan = result.get("final_plan", [])
            print(f"📋 Plan erstellt ({len(plan)} Steps, Score: {result.get('evaluation', {}).get('score', '?')}):")
            for step in plan:
                agent = step.get("agent", "?")
                action = step.get("action", "?")
                deps = step.get("depends_on", [])
                dep_str = f" (after {deps})" if deps else ""
                print(f"  {step.get('step', '?')}. [{agent}] {action}{dep_str}")
        except ImportError as e:
            print(f"Planning Engine nicht verfügbar: {e}")
    else:
        cli.run()


if __name__ == "__main__":
    main()
