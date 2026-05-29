"""
TOTI — Primärer autonomer Agent im Nexus-System v2.0
Orchestriert, delegiert, entscheidet autonom, antwortet sofort.
Mit Error-Learning, LLM-Health-Check und Skill-Integration.
"""

import asyncio
import time
import json
from typing import Optional
from pathlib import Path

from core.agent_base import AgentBase
from core.llm_client import LLMClient, Message
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.state import StateManager
from core.guards import NexusGuards
from core.delegation import DelegationEngine
from core.error_learning import ErrorLearningSystem


class TotiAgent(AgentBase):
    """TOTI — Primär-Agent. Handelt autonom, antwortet sofort, delegiert intelligent, lernt aus Fehlern."""

    AGENT_ID = "TOTI"
    AGENT_NAME = "Toti"
    SYSTEM_PROMPT_FILE = "toti.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry,
                 state: Optional[StateManager] = None, guards: Optional[NexusGuards] = None,
                 error_learning: Optional[ErrorLearningSystem] = None):
        super().__init__(llm, memory, tools, state, guards, error_learning=error_learning)
        self.delegation = DelegationEngine(llm, memory, tools)
        self._scheduler_registered = False

    def register_agent(self, agent_id: str, agent_instance: AgentBase):
        """Registriere einen Sub-Agent für Delegation."""
        self.delegation.register_agent(agent_id, agent_instance)

    def process(self, user_input: str) -> str:
        """
        Main Entry: Input empfangen → bewerten → ausführen → Ergebnis liefern.
        Toti antwortet SOFORT, dann arbeitet er.
        """
        # Kommandos prüfen
        if user_input.startswith("/"):
            return self._handle_command(user_input)

        # Konversation oder technischer Task?
        if self._is_conversational(user_input):
            return self.quick_response(user_input)

        # Komplexität bewerten
        complexity = self._assess_complexity(user_input)

        if complexity == "simple":
            return self.quick_response(user_input)

        elif complexity == "moderate":
            # Toti beantwortet selbst mit vollem Kontext
            result = self.execute(task=user_input)
            return result["result"]

        else:
            # Komplex — volle DAG Delegation
            return self._delegate_complex(user_input)

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
        ]

        indicator_count = sum(1 for ind in complex_indicators if ind in task_lower)
        word_count = len(task.split())

        if indicator_count >= 3 or word_count > 40:
            return "complex"
        elif indicator_count >= 1 or word_count > 15:
            return "moderate"
        else:
            return "simple"

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

        # Exakt kurze Nachrichten (<=3 Wörter) immer als Konversation
        if len(task.split()) <= 3:
            return True

        return any(task_lower.startswith(p) or task_lower == p for p in conversational_patterns)

    def _pick_agent(self, task: str) -> str:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["recherch", "such", "find", "info", "web", "look up", "search", "research"]):
            return "SCOUT"
        if any(kw in task_lower for kw in ["code", "implementier", "baue", "schreib", "script", "program", "build", "debug", "fix", "test"]):
            return "FORGE"
        if any(kw in task_lower for kw in ["analyse", "review", "prüf", "bewert", "check", "analyze", "security", "performance"]):
            return "LENS"
        if any(kw in task_lower for kw in ["format", "ausgabe", "darstell", "present", "output", "dokumentation", "doc"]):
            return "HERALD"
        return "SCOUT"

    def _delegate_complex(self, task: str) -> str:
        """Zerlege und delegiere einen komplexen Task."""
        context = self.memory.build_context(task)

        # State aktualisieren
        self.state.update_task(task_id=f"task_{int(time.time())}", goal=task, status="working")

        # Error-Learning: Vorab-Warnungen
        warnings = self.error_learning.check_before_action(task)
        if warnings:
            context += "\n\n## FEHLER-VERMEIDUNG\n"
            for w in warnings[:3]:
                context += f"⚠ {w.error_class}: {w.hint}\n"

        # Delegieren
        plan = self.delegation.decompose_task(task, context)
        result = self.delegation.execute_plan(plan)

        # State aktualisieren
        self.state.update_task(status="done")

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
            scheduler_status = self._get_scheduler_status()
            error_stats = self.error_learning.get_error_stats()
            health = self.llm.get_health_status()
            return (
                f"**Toti Status v2.0**\n"
                f"State: {self.state.get('current_task.status', 'idle')}\n"
                f"Task: {self.state.get('current_task.goal', 'none')}\n"
                f"Step: {guards['steps']}/{guards['max_steps']}\n"
                f"Budget: {guards['budget_used_pct']}% | Fallback: {guards['cloud_fallback']}\n"
                f"LLM Calls: {llm_stats['total_calls']} | Tokens: {llm_stats['total_tokens']}\n"
                f"Ollama: {'✓' if llm_stats.get('ollama_available', llm_stats.get('cli_available', False)) else '✗'} | Host: {llm_stats.get('ollama_host', llm_stats.get('cli_path', 'n/a'))}\n"
                f"Models: {json.dumps({k: '✓' if v else '✗' for k, v in health.get('health', {}).items()})}\n"
                f"Agents: {len(self.delegation._agents)} | Scheduler: {scheduler_status}\n"
                f"Errors: {error_stats['total_unique_errors']} known | {error_stats['session_avoided']} avoided\n"
                f"Tools: {len(self.tools.list_tools())} | Skills: {len(self._get_available_skills())}"
            )

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
            lines = ["**LLM Health Check**"]
            for level, h in health.items():
                model_name = self.llm.MODEL_LEVELS.get(level, {}).get("name", f"Level {level}")
                status = "✓ OK" if h.available else f"✗ {h.error}"
                rt = f"{h.response_time:.1f}s" if h.response_time else "n/a"
                lines.append(f"  {model_name}: {status} ({rt})")
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
            return "Session + State reset. Frischer Start."

        elif cmd.startswith("/evolve"):
            task_name = cmd.replace("/evolve", "").strip()
            return self._gepa_evolve(task_name)

        elif cmd == "/help":
            return (
                "**Toti Commands v2.0**\n"
                "/status — System-Status (Guards, Budget, LLM, Errors)\n"
                "/memory — Memory-Übersicht (L1/L2/L3)\n"
                "/state — State-Objekt anzeigen\n"
                "/errors — Error-Learning Statistiken\n"
                "/health — LLM-Modelle Health-Check\n"
                "/tools — Verfügbare Tools auflisten\n"
                "/skills — Verfügbare Skills auflisten\n"
                "/reset — Session + State zurücksetzen\n"
                "/evolve <task> — GEPA Self-Improvement\n"
                "/help — Diese Hilfe\n\n"
                "Oder einfach schreiben. Toti handelt."
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
        """GEPA Self-Improvement Protocol mit Error-Learning."""
        history = self.memory.session_get_history()
        error_stats = self.error_learning.get_error_stats()
        hints = self.error_learning.generate_avoid_hints()

        evolve_prompt = f"""GEPA SELF-IMPROVEMENT PROTOCOL v2.0

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

PARETO_CHECK:
  Bringt das >20% bessere Ergebnisse? <ja/nein>

Konkret und ehrlich. Kein Fülltext."""

        messages = [
            Message(role="system", content=self._system_prompt),
            Message(role="user", content=evolve_prompt),
        ]

        response = self.llm.chat(messages, level=2)
        self.memory.longterm_write(
            f"gepa_{task_name or 'general'}",
            {"analysis": response.content[:2000], "timestamp": time.time()},
        )

        # Error-Learning konsolidieren
        self.error_learning.consolidate()

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
