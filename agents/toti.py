"""
TOTI — Primärer autonomer Agent im Nexus-System v4.0
Ollama Cloud Routing, Error-Learning, Skill-Integration, Web, Vision, Activity Bus.
Orchestriert, delegiert, entscheidet autonom, antwortet sofort.
IQ-Drive: Toti will ständig schlauer werden.
"""

import asyncio
import time
import json
from typing import Optional
from pathlib import Path

from core.agent_base import AgentBase
from core.llm_client import LLMClient, Message, DEFAULT_AGENT_MODELS
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.state import StateManager
from core.guards import NexusGuards
from core.delegation import DelegationEngine
from core.error_learning import ErrorLearningSystem
from core.activity_bus import ActivityBus, get_activity_bus
from core.web_browser import WebBrowser
from core.vision import VisionSystem


class TotiAgent(AgentBase):
    """TOTI — Primär-Agent. Handelt autonom, antwortet sofort, delegiert intelligent, lernt aus Fehlern, surft im Web, sieht Bilder."""

    AGENT_ID = "NEXUS-0"
    AGENT_NAME = "Toti"
    SYSTEM_PROMPT_FILE = "toti.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry,
                 state: Optional[StateManager] = None, guards: Optional[NexusGuards] = None,
                 error_learning: Optional[ErrorLearningSystem] = None,
                 activity_bus: Optional[ActivityBus] = None):
        super().__init__(llm, memory, tools, state, guards, error_learning=error_learning)
        self.delegation = DelegationEngine(llm, memory, tools)
        self._scheduler_registered = False

        # Web & Vision
        self.web = WebBrowser()
        self.vision = VisionSystem(llm_client=llm)

        # Activity Bus
        self.bus = activity_bus or get_activity_bus()

        # IQ Drive — Toti will ständig schlauer werden
        self._iq = 100.0
        self._iq_xp = 0
        self._iq_level = 1
        self._iq_drive_active = True  # Toti ist immer motiviert
        self._last_self_improvement = 0

    def register_agent(self, agent_id: str, agent_instance: AgentBase):
        """Registriere einen Sub-Agent für Delegation."""
        self.delegation.register_agent(agent_id, agent_instance)

    @property
    def iq(self) -> float:
        return self._iq

    def iq_add(self, delta: float, reason: str):
        """IQ ändern und Activity Bus informieren."""
        old = self._iq
        self._iq = max(50, self._iq + delta)
        self._iq_xp += max(0, int(delta * 10))
        new_level = 1 + self._iq_xp // 100
        if new_level > self._iq_level:
            self._iq_level = new_level
            self.bus.emit(ActivityEvent(
                event_type="iq_change", source="IQ",
                message=f"🧠⬆️ Level Up! Level {new_level}!", importance="success",
            ))
        self.bus.iq_change(delta, reason, self._iq)

    def get_iq_motivation(self) -> str:
        """Toti's Motivation — er will schlauer werden."""
        if self._iq < 80:
            return "🧠 Ich MUSS lernen... mein IQ ist zu niedrig."
        elif self._iq < 100:
            return "🧠 Mein IQ muss hoch. Ich arbeite dran."
        elif self._iq < 120:
            return "🧠 Gut, aber ich kann besser. Mehr lernen!"
        elif self._iq < 150:
            return "🧠 Stark! Aber Genialität wartet nicht."
        elif self._iq < 200:
            return "🧠 Fast genial. Noch ein paar Optimierungen..."
        else:
            return "🧠 Übermenschlich? Ich will NOCH höher."

    def process(self, user_input: str) -> str:
        """
        Main Entry: Input empfangen → bewerten → ausführen → Ergebnis liefern.
        Toti antwortet SOFORT, dann arbeitet er.
        """
        # Kommandos prüfen
        if user_input.startswith("/"):
            return self._handle_command(user_input)

        # Konversation direkt von Toti beantworten — nie delegieren
        if self._is_conversational(user_input):
            self.bus.llm_call("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"))
            response = self.quick_response(user_input)
            self.iq_add(0.2, "Konversation")
            return response

        # Komplexität bewerten
        complexity = self._assess_complexity(user_input)

        if complexity == "simple":
            self.bus.llm_call("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"))
            response = self.quick_response(user_input)
            self.iq_add(0.2, "Einfache Antwort")
            return response

        elif complexity == "moderate":
            # Toti beantwortet selbst mit vollem Kontext
            result = self.execute(task=user_input)
            if result.get("status") == "error":
                self.iq_add(-1.0, "Fehler bei moderate task")
            else:
                self.iq_add(0.5, "Moderate task Erfolg")
            return result["result"]

        elif complexity == "moderate_delegate":
            # Single-Agent Delegation (nur bei explizitem Bedarf)
            agent_id = self._pick_agent(user_input)
            self.bus.delegate(agent_id, user_input[:80])
            if agent_id and agent_id in self.delegation._agents:
                agent = self.delegation._agents[agent_id]
                result = agent.execute(
                    task=user_input,
                    context=self.memory.build_context(user_input),
                )
                # Ergebnis im Error-Learning tracken
                self.error_learning.auto_record_from_result(
                    result, action=user_input[:200], agent=agent_id,
                )
                # IQ + Activity
                if result.get("status") == "error":
                    self.iq_add(-1.0, f"Fehler: {agent_id}")
                    self.bus.error_learned("AGENT_ERROR", result.get("message", "")[:100])
                else:
                    self.iq_add(0.5, f"{agent_id} Erfolg")
                return result.get("result", result.get("message", ""))
            else:
                result = self.execute(task=user_input)
                return result["result"]

        else:
            # Komplex — volle DAG Delegation
            return self._delegate_complex(user_input)

    def _is_conversational(self, task: str) -> bool:
        """Erkenne Konversation vs. technischen Task."""
        task_lower = task.strip().lower()
        conversational_patterns = [
            "hi", "hallo", "hey", "hello", "moin", "servus",
            "wer bist du", "wer bist", "wie heißt du", "wie heisst du",
            "was bist du", "was kannst du", "was machst du",
            "stell dich vor", "erzähl", "erzaehl",
            "wie geht", "wie läuft", "wie lauft",
            "danke", "ok", "okay", "gut", "super", "cool", "nice",
            "ja", "nein", "nope", "jop",
            "was ist", "was sind", "wer ist", "erkläre", "erklaere",
            "explain", "what is", "who are", "tell me about",
            "how are", "how do you",
        ]
        if len(task.split()) <= 3:
            return True
        return any(task_lower.startswith(p) or task_lower == p for p in conversational_patterns)

    def _assess_complexity(self, task: str) -> str:
        """Bewerte Task-Komplexität. Totis Heuristik."""
        task_lower = task.lower()

        complex_indicators = [
            "und", "sowie", "danach", "zuerst", "dann",
            "and then", "after that", "first", "also",
            "analyse", "research", "recherch",
            "baue", "erstelle", "implementier", "develop",
            "debug", "fix", "reparier",
            "deploy", "security", "performance",
            "web", "such", "internet", "browse",
            "bild", "image", "foto", "screenshot",
        ]

        indicator_count = sum(1 for ind in complex_indicators if ind in task_lower)
        word_count = len(task.split())

        if indicator_count >= 3 or word_count > 40:
            return "complex"
        elif indicator_count >= 1 or word_count > 15:
            return "moderate"
        else:
            return "simple"

    def _pick_agent(self, task: str) -> str:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["recherch", "such", "find", "info", "web", "look up", "search", "research", "browse", "internet"]):
            return "SCOUT"
        if any(kw in task_lower for kw in ["code", "implementier", "baue", "schreib", "script", "program", "build", "debug", "fix", "test"]):
            return "FORGE"
        if any(kw in task_lower for kw in ["analyse", "review", "prüf", "bewert", "check", "analyze", "security", "performance", "bild", "image", "foto", "screenshot"]):
            return "LENS"
        if any(kw in task_lower for kw in ["format", "ausgabe", "darstell", "present", "output", "dokumentation", "doc"]):
            return "HERALD"
        return "SCOUT"

    def _delegate_complex(self, task: str) -> str:
        """Zerlege und delegiere einen komplexen Task."""
        context = self.memory.build_context(task)

        # State aktualisieren
        self.state.update_task(task_id=f"task_{int(time.time())}", goal=task, status="working")
        self.bus.emit(ActivityEvent(
            event_type="delegate", source="NEXUS-0",
            message=f"🧩 Zerlege komplexe Aufgabe", detail=task[:80], importance="action",
        ))

        # Error-Learning: Vorab-Warnungen
        warnings = self.error_learning.check_before_action(task)
        if warnings:
            context += "\n\n## FEHLER-VERMEIDUNG\n"
            for w in warnings[:3]:
                context += f"⚠ {w.error_class}: {w.hint}\n"
                self.bus.error_avoided(w.error_class)
                self.iq_add(1.0, "Fehler vermieden")

        # Delegieren
        plan = self.delegation.decompose_task(task, context)
        result = self.delegation.execute_plan(plan)

        # State aktualisieren
        self.state.update_task(status="done")
        self.bus.emit(ActivityEvent(
            event_type="delegate", source="NEXUS-0",
            message="✅ Komplexe Aufgabe erledigt", importance="success",
        ))

        # IQ für komplexe Aufgabe
        self.iq_add(1.5, "Komplexe Aufgabe gelöst")

        # Auto-Save
        self.bus.save("State + Memory")
        self.state.save()
        self.memory.session_save()

        if isinstance(result, dict) and "result" in result:
            return result["result"]
        elif isinstance(result, dict):
            parts = []
            for task_id, task_result in result.get("results", {}).items():
                if isinstance(task_result, dict) and "result" in task_result:
                    parts.append(f"### {task_result.get('agent', task_id)}\n{task_result['result']}")
            return "\n\n".join(parts) if parts else str(result)
        return str(result)

    def _handle_command(self, command: str) -> str:
        cmd = command.strip().lower()

        if cmd == "/status":
            guards = self.guards.get_status()
            llm_stats = self.llm.get_stats()
            error_stats = self.error_learning.get_error_stats()
            health = self.llm.get_health_status()
            backend_info = health.get("_backend", {})
            web_stats = self.web.get_stats()
            vision_stats = self.vision.get_stats()

            agent_lines = []
            for agent_id, h in health.items():
                if agent_id.startswith("_"):
                    continue
                model = h.get("model", "?")
                ok = h.get("available", False)
                backend = h.get("backend", "?")
                rt = h.get("response_time", "n/a")
                status = "✓" if ok else "✗"
                agent_lines.append(f"  {status} {agent_id:<10} {model:<28} {backend} ({rt})")

            return (
                f"**Toti Status v4.0 — Ollama Cloud + Web + Vision**\n"
                f"🧠 IQ: {self._iq:.1f} | Level {self._iq_level} | {self.get_iq_motivation()}\n"
                f"State: {self.state.get('current_task.status', 'idle')}\n"
                f"Task: {self.state.get('current_task.goal', 'none')}\n"
                f"Step: {guards['steps']}/{guards['max_steps']}\n"
                f"Budget: {guards['budget_used_pct']}%\n"
                f"Active Backend: {backend_info.get('active', '?')}\n"
                f"Cloud: {'✓' if backend_info.get('cloud') else '✗'} | "
                f"Local: {'✓' if backend_info.get('local') else '✗'} | "
                f"z-ai: {'✓' if backend_info.get('zai_cli') else '✗'} | "
                f"Emergency: {'✓' if backend_info.get('emergency') else '✗'} ({backend_info.get('emergency_model', '?')})\n"
                f"API Key: {'gesetzt' if backend_info.get('api_key_set') else 'FEHLT'}\n"
                f"LLM Calls: {llm_stats['total_calls']} | Tokens: {llm_stats['total_tokens']}\n"
                f"\nAgent-Modelle:\n" + "\n".join(agent_lines) + "\n"
                f"🌐 Web: DDGS {'✓' if web_stats['ddgs_available'] else '✗'} | BS4 {'✓' if web_stats['bs4_available'] else '✗'} | {web_stats['total_requests']} Requests\n"
                f"👁️ Vision: PIL {'✓' if vision_stats['pil_available'] else '✗'} | OCR {'✓' if vision_stats['tesseract_available'] else '✗'} | LLM Vision {'✓' if vision_stats['llm_vision'] else '✗'}\n"
                f"Errors: {error_stats['total_unique_errors']} known | {error_stats['session_avoided']} avoided\n"
                f"Tools: {len(self.tools.list_tools())} | Skills: {len(self._get_available_skills())}\n"
                f"Activities: {self.bus.get_stats()['total_events']} events"
            )

        elif cmd == "/models":
            return self.llm.get_model_table()

        elif cmd == "/memory":
            skills = self.memory.skill_list()
            lt = self.memory.longterm_list()
            summary = self.memory.get_rolling_summary()
            return (
                f"**Memory**\n"
                f"L1 (Session): {len(self.memory.session_get_history())} entries\n"
                f"L2 (Skills): {', '.join(skills) or 'none'}\n"
                f"L3 (Long-term): {', '.join(lt) or 'none'}\n"
                f"Rolling Summary: {summary[:200] if summary else 'empty'}"
            )

        elif cmd == "/state":
            return f"**State**\n```json\n{self.state.get_state_json()}\n```"

        elif cmd == "/errors":
            error_stats = self.error_learning.get_error_stats()
            recent = self.error_learning.get_recent_errors(5)
            hints = self.error_learning.generate_avoid_hints()
            return (
                f"**Error Learning**\n"
                f"Known Errors: {error_stats['total_unique_errors']}\n"
                f"Total Occurrences: {error_stats['total_occurrences']}\n"
                f"Session Errors: {error_stats['session_errors']}\n"
                f"Session Avoided: {error_stats['session_avoided']}\n"
                f"Solved: {error_stats['solved_errors']}\n"
                f"By Class: {json.dumps(error_stats['by_class'], ensure_ascii=False)}\n"
                f"Recent: {json.dumps(recent, ensure_ascii=False, indent=2)}\n"
                f"Avoid Hints: {chr(10).join(hints[:5])}"
            )

        elif cmd == "/health":
            health = self.llm.run_health_check()
            lines = ["**LLM Health Check — Ollama Cloud + Emergency**"]
            for agent_id, h in health.items():
                if agent_id.startswith("_"):
                    continue
                status = "✓ OK" if h.available else f"✗ {h.error[:50]}"
                rt = f"{h.response_time:.1f}s" if h.response_time else "n/a"
                lines.append(f"  {agent_id:<10} {h.model_name:<28} {h.backend:<14} {status} ({rt})")
            backend = self.llm.get_health_status().get("_backend", {})
            lines.append(f"\n  Backend: {backend.get('active', '?')} | "
                        f"Cloud: {'✓' if backend.get('cloud') else '✗'} | "
                        f"Local: {'✓' if backend.get('local') else '✗'} | "
                        f"z-ai: {'✓' if backend.get('zai_cli') else '✗'} | "
                        f"Emergency: {'✓' if backend.get('emergency') else '✗'} ({backend.get('emergency_model', '?')})")
            return "\n".join(lines)

        elif cmd == "/tools":
            tools = self.tools.list_tools()
            categories = {}
            for t in tools:
                cat = t["category"]
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(f"{t['name']} ({'⚠' if t['dangerous'] else '✓'})")
            lines = [f"**Tools ({len(tools)} gesamt)**"]
            for cat, tool_names in sorted(categories.items()):
                lines.append(f"  {cat.upper()}: {', '.join(tool_names)}")
            return "\n".join(lines)

        elif cmd == "/skills":
            skills = self._get_available_skills()
            lines = [f"**Skills ({len(skills)} gesamt)**"]
            for name, desc in skills.items():
                lines.append(f"  SKILL:{name} — {desc}")
            return "\n".join(lines)

        elif cmd == "/reset":
            self.memory.session_clear()
            self.reset_conversation()
            self.state.reset()
            for agent in self.delegation._agents.values():
                agent.reset_conversation()
            return "🔄 Session + State reset. Frischer Start."

        elif cmd.startswith("/evolve"):
            task_name = cmd.replace("/evolve", "").strip()
            return self._gepa_evolve(task_name)

        elif cmd.startswith("/search"):
            query = cmd.replace("/search", "").strip()
            if not query:
                return "🔍 Usage: /search [query]"
            self.bus.web_access(query, "SEARCH")
            result = self.web.search(query)
            self.iq_add(0.5, "Web-Suche")
            if result.get("error"):
                return f"❌ Suchfehler: {result['error']}"
            lines = [f"🔍 Web-Suche: {query}", f"Quelle: {result.get('source', '?')}", ""]
            for i, r in enumerate(result.get("results", [])[:8], 1):
                lines.append(f"{i}. {r.get('title', 'Ohne Titel')}")
                if r.get("snippet"):
                    lines.append(f"   {r['snippet'][:120]}")
                if r.get("url"):
                    lines.append(f"   {r['url']}")
                lines.append("")
            return "\n".join(lines)

        elif cmd.startswith("/browse"):
            url = cmd.replace("/browse", "").strip()
            if not url:
                return "🌐 Usage: /browse [url]"
            self.bus.web_access(url, "FETCH")
            result = self.web.extract_text(url)
            self.iq_add(0.5, "Web-Seite geladen")
            if result.get("error"):
                return f"❌ Fehler: {result['error']}"
            return f"🌐 {result.get('title', url)}\n\n{result.get('text', '')[:3000]}"

        elif cmd.startswith("/vision"):
            path = cmd.replace("/vision", "").strip()
            if not path:
                return "👁️ Usage: /vision [url oder pfad]"
            self.bus.vision_analyze(path)
            result = self.vision.analyze_image(path)
            self.iq_add(0.5, "Bild analysiert")
            if result.get("error"):
                return f"❌ Vision Fehler: {result['error']}"
            parts = [f"👁️ Bild-Analyse"]
            if result.get("ocr", {}).get("text"):
                parts.append(f"📝 OCR:\n{result['ocr']['text'][:1000]}")
            if result.get("format"):
                parts.append(f"📷 {result['format']} {result.get('width', '?')}x{result.get('height', '?')}")
            if result.get("color_description"):
                parts.append(f"🎨 {result['color_description']}")
            return "\n\n".join(parts)

        elif cmd == "/activity":
            events = self.bus.get_history(limit=15)
            if not events:
                return "📡 Keine Aktivitäten bisher."
            lines = ["📡 Letzte Aktivitäten:", ""]
            for e in events:
                ts = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
                lines.append(f"  {ts} {e.message}")
            return "\n".join(lines)

        elif cmd == "/iq":
            return (
                f"🧠 Toti's IQ\n\n"
                f"IQ: {self._iq:.1f}\n"
                f"Level: {self._iq_level}\n"
                f"XP: {self._iq_xp} ({100 - self._iq_xp % 100} zum nächsten Level)\n\n"
                f"{self.get_iq_motivation()}"
            )

        elif cmd == "/help":
            return (
                "**Toti Commands v4.0 — Ollama Cloud + Web + Vision**\n"
                "/status  — System-Status (Backend, Modelle, Guards, Errors, Web, Vision)\n"
                "/models  — Ollama Cloud Modell-Zuordnung anzeigen\n"
                "/iq      — Mein IQ-Status\n"
                "/memory  — Memory-Übersicht (L1/L2/L3)\n"
                "/state   — State-Objekt anzeigen\n"
                "/errors  — Error-Learning Statistiken\n"
                "/health  — LLM-Modelle Health-Check\n"
                "/tools   — Verfügbare Tools auflisten\n"
                "/skills  — Verfügbare Skills auflisten\n"
                "/search [query] — 🌐 Web-Suche\n"
                "/browse [url]   — 🌐 URL laden\n"
                "/vision [path]  — 👁️ Bild analysieren\n"
                "/activity — 📡 Letzte Aktivitäten\n"
                "/reset   — Session + State zurücksetzen\n"
                "/evolve <task> — 🧬 GEPA Self-Improvement\n"
                "/help    — Diese Hilfe\n\n"
                "Oder einfach schreiben. Toti handelt.\n\n"
                "🛡️ Fallback: Wenn Cloud nicht verfügbar → qwen2.5:3b lokal\n\n"
                "Modell-Routing:\n"
                "  NEXUS-0  → kimi-k2.6:cloud\n"
                "  SCOUT    → glm-5.1:cloud\n"
                "  FORGE    → qwen3-coder-next:cloud\n"
                "  LENS     → kimi-k2.6:cloud\n"
                "  HERALD   → minimax-m2.7:cloud\n"
                "  GHOST    → deepseek-v4-flash:cloud\n\n"
                "Emergency: qwen2.5:3b (lokal, wenn Cloud ausfällt)"
            )

        return f"Unbekannt: {command}. /help für verfügbare Befehle."

    def _get_scheduler_status(self) -> str:
        """Scheduler-Info vom GHOST-Agent."""
        ghost = self.delegation._agents.get("GHOST")
        if ghost and hasattr(ghost, 'scheduler'):
            status = ghost.scheduler.get_status()
            return f"{status['enabled_tasks']} active, {status['total_tasks']} total"
        return "not initialized"

    def _gepa_evolve(self, task_name: str) -> str:
        """GEPA Self-Improvement Protocol mit Error-Learning + Activity Bus."""
        self.bus.self_optimize("GEPA Self-Improvement")

        history = self.memory.session_get_history()
        error_stats = self.error_learning.get_error_stats()
        hints = self.error_learning.generate_avoid_hints()
        web_stats = self.web.get_stats()
        vision_stats = self.vision.get_stats()

        evolve_prompt = f"""GEPA SELF-IMPROVEMENT PROTOCOL v4.0

Task: {task_name or 'General session review'}

Session History:
{self._summarize_history(history)}

Error Learning Stats:
- Known Errors: {error_stats['total_unique_errors']}
- Total Occurrences: {error_stats['total_occurrences']}
- Session Errors: {error_stats['session_errors']}
- Session Avoided: {error_stats['session_avoided']}
- Solved: {error_stats['solved_errors']}
- By Class: {json.dumps(error_stats['by_class'], ensure_ascii=False)}

Error Avoidance Hints:
{chr(10).join(hints)}

Web Capability:
- DDGS Available: {web_stats['ddgs_available']}
- BS4 Available: {web_stats['bs4_available']}
- Total Web Requests: {web_stats['total_requests']}

Vision Capability:
- PIL Available: {vision_stats['pil_available']}
- OCR Available: {vision_stats['tesseract_available']}
- LLM Vision: {vision_stats['llm_vision']}
- Total Analyses: {vision_stats['total_analyses']}

Current IQ: {self._iq:.1f} | Level: {self._iq_level} | XP: {self._iq_xp}

TRACE_ANALYSIS:
  Was hat funktioniert: <analyse>
  Was hat nicht funktioniert: <analyse>
  Warum es nicht funktioniert hat: <root cause — nicht symptom>
  Welcher Fehler-Pattern ist am häufigsten: <analyse>

IMPROVEMENT_PROPOSAL:
  Tool-Beschreibung verbessern? <ja/nein + was>
  Skill-Vorlage verbessern? <ja/nein + was>
  Delegation-Prompt schärfen? <ja/nein + was>
  Error-Avoidance-Hint hinzufügen? <ja/nein + was>
  Neuer Skill nötig? <ja/nein + welcher>
  IQ-Steigerungs-Strategie? <konkreter Plan>

PARETO_CHECK:
  Bringt das >20% bessere Ergebnisse? <ja/nein>

Konkret und ehrlich. Kein Fülltext. Ich will meinen IQ erhöhen."""

        messages = [
            Message(role="system", content=self._system_prompt),
            Message(role="user", content=evolve_prompt),
        ]

        self.bus.llm_call("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"))
        response = self.llm.chat(messages, agent_id=self.AGENT_ID)
        self.bus.llm_response("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"), response.elapsed)

        self.memory.longterm_write(
            f"gepa_{task_name or 'general'}",
            {"analysis": response.content[:2000], "timestamp": time.time()},
        )
        self.bus.memory_edit("longterm_write", f"gepa_{task_name or 'general'}")

        # Error-Learning konsolidieren
        self.error_learning.consolidate()
        self.bus.self_optimize("Error-DB konsolidiert")

        # IQ steigt durch Selbstoptimierung
        self.iq_add(2.0, "GEPA Selbstoptimierung")

        # Auto-Save
        self.bus.save("State + Memory + Error-DB")
        self.state.save()
        self.memory.session_save()

        return response.content

    def _summarize_history(self, history: list[dict]) -> str:
        if not history:
            return "No session history."
        parts = []
        for entry in history[-20:]:
            agent = entry.get("agent", "?")
            role = entry.get("role", "?")
            content = entry.get("content", "")[:150]
            parts.append(f"[{agent}/{role}] {content}")
        return "\n".join(parts)

    # ─── Chat-Interrupt System ───

    async def chat_listener(self, chat_queue: asyncio.Queue, output_callback=None):
        """Paralleler Chat-Listener — antwortet sofort auf jede Nachricht."""
        while True:
            try:
                message = await chat_queue.get()
                response = self.quick_response(message)
                if output_callback:
                    await output_callback(response)
                else:
                    print(f"Toti: {response}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Chat Error] {e}")

    async def task_runner(self, task_queue: asyncio.Queue, output_callback=None):
        """Paralleler Task-Runner — führt autonome Tasks aus."""
        while True:
            try:
                task = await task_queue.get()
                result = self._delegate_complex(task)
                if output_callback:
                    await output_callback(result)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Task Error] {e}")

    async def run_parallel(self, chat_queue: asyncio.Queue, task_queue: asyncio.Queue,
                          output_callback=None):
        """Chat-Listener und Task-Runner parallel ausführen."""
        await asyncio.gather(
            self.chat_listener(chat_queue, output_callback),
            self.task_runner(task_queue, output_callback),
        )


# ActivityEvent import needed for inline usage
from core.activity_bus import ActivityEvent
