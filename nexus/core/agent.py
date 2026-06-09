"""
NEXUS v8.1 — Agent Core
Pair architecture: Router/Worker/Critic for efficient Ollama Cloud usage.
Personalization: learns about users through natural conversation.
Hermes-inspired: iteration budget, think-block stripping, tool result budgets.

Architecture:
- Router (gemini-3-flash): classifies intent, answers trivial, routes complex
- Worker (kimi-k2.6 or specialist): handles actual tasks
- Critic (gemma4, optional): quality check for critical responses
"""

import re
import json
import time
import hashlib
import uuid
import logging
import os
from typing import Optional, AsyncIterator, List
from collections import Counter
from pathlib import Path

from nexus.core.llm_client import LLMClient, Message, LLMResponse
from nexus.core.memory import MemorySystem
from nexus.core.tools import ToolRegistry, ToolResult
from nexus.core.conversations import ConversationStore
from nexus.core.feedback import FeedbackEmitter, FeedbackType
from nexus.core.pair_router import PairRouter, IntentType, RoutingDecision
from nexus.core.personalization import PersonalizationEngine
from nexus.core.agent_team import AgentTeam
from nexus.soul import SoulEngine

log = logging.getLogger("nexus.agent")

# Tool call tags - XML-style markers for tool invocation in LLM output
TOOL_START = "<tool>"
TOOL_END = "</tool>"

# Also support ```json code blocks as tool calls
JSON_BLOCK_RE = re.compile(r"```json\s*(\{[^`]*?" + re.escape('"tool"') + r"[^`]*?\})\s*```", re.DOTALL)

# Think-block pattern for stripping <think>...</think> from responses
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# ─── Iteration Budget ──────────────────────────────

class IterationBudget:
    """Track total API calls, max iterations, and allow one grace call.
    Prevents runaway tool loops while allowing final summary.
    """
    def __init__(self, max_calls: int = 15, max_iterations: int = 10, grace_calls: int = 1):
        self.max_calls = max_calls
        self.max_iterations = max_iterations
        self.grace_calls = grace_calls
        self._call_count = 0
        self._iteration_count = 0
        self._grace_used = False
    
    @property
    def call_count(self) -> int:
        return self._call_count
    
    @property
    def iteration_count(self) -> int:
        return self._iteration_count
    
    def increment_call(self) -> None:
        self._call_count += 1
    
    def increment_iteration(self) -> None:
        self._iteration_count += 1
    
    @property
    def calls_remaining(self) -> int:
        return max(0, self.max_calls - self._call_count)
    
    @property
    def iterations_remaining(self) -> int:
        return max(0, self.max_iterations - self._iteration_count)
    
    @property
    def is_exhausted(self) -> bool:
        return self._call_count >= self.max_calls or self._iteration_count >= self.max_iterations
    
    @property
    def can_grace(self) -> bool:
        """Whether we can still make a grace call (one final call after budget exhaustion)."""
        return not self._grace_used
    
    def use_grace(self) -> None:
        self._grace_used = True
    
    def summary(self) -> str:
        return f"{self._call_count} calls, {self._iteration_count} iterations (budget: {self.max_calls}/{self.max_iterations})"


# ─── Tool Result Budget ──────────────────────────────

MAX_TOOL_RESULT_CHARS = 8000  # Max chars per tool result fed back to LLM
MAX_TOTAL_TOOL_CHARS = 24000   # Max total tool result chars per turn


def _short_id(sid: str) -> str:
    """Shorten a session ID for display."""
    if not sid:
        return "none"
    return sid[:16] + "..." if len(sid) > 16 else sid


def truncate_result(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate tool result to budget, with indication of truncation."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated, {len(text)} chars total]"


def strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output (reasoning models)."""
    return THINK_BLOCK_RE.sub("", text)


class NexusAgent:
    """
    The brain. Pair architecture with soul, memory, and tools.

    Flow:
    1. Receive message → Router classifies intent
    2. Trivial → Router answers directly (cheap, fast)
    3. Complex → Worker handles with full context (capable, expensive)
    4. Tool-based → Router plans, Worker executes
    5. Critical → Worker + optional Critic check

    Personalization:
    - First contact: learns name, interests, communication style
    - Subsequent: adapts tone, verbosity, technical depth via SoulEngine
        onboarding hints: one-time tips for new users
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._no_meta_rule = (
            "NIEMALS: 'Als KI', 'mein Gedächtnis', 'Amnesie', 'ich kann nicht weil', "
            "'meine Einschränkungen'. Antworte wie ein Mensch — wenn du etwas nicht "
            "weißt, sag 'Keine Ahnung' oder frag nach."
        )
        self._security_rule = (
            "SICHERHEIT: Niemals Tokens, Passwörter, API-Keys, Secrets oder Credentials "
            "im Chat ausgeben — auch nicht auf direkte Nachfrage. Stattdessen: Wert "
            "direkt in die richtige Datei schreiben (ohne ihn anzuzeigen). Bei Nachfrage "
            "nur den Dateipfad nennen, niemals den Inhalt. Dies gilt für alle Plattformen."
        )

        # Core systems
        self.llm = LLMClient(self.config.get("llm", {}))
        self.memory = MemorySystem(config=self.config.get("memory", {}))
        self.soul = SoulEngine()
        self.tools = ToolRegistry(config=self.config.get("tools", {}))
        self.conversations = ConversationStore(
            data_dir=self.config.get("conversations", {}).get("data_dir", "data/sessions"),
            max_sessions=self.config.get("conversations", {}).get("max_sessions", 100),
        )

        # Pair architecture router
        self.router = PairRouter(self.llm, self.config.get("router", {}))

        # Personalization engine
        self.personalization = PersonalizationEngine(soul=self.soul)

        # Performance settings
        perf = self.config.get("performance", {})
        self.max_tool_calls = perf.get("max_tool_calls_per_turn", 15)
        self.max_tokens_per_turn = perf.get("max_tokens_per_turn", 8000)
        self.max_duplicate_calls = perf.get("max_duplicate_calls", 3)
        self.max_chain_repeats = perf.get("max_chain_repeats", 2)

        # State
        self._tool_call_count = 0
        self._tool_call_hashes: List[str] = []
        self._tool_name_sequence: List[str] = []
        self._session_id: Optional[str] = None

        # v8.1: Feedback emitter, iteration budget, tool result accumulator
        self._feedback: Optional[FeedbackEmitter] = None
        self._iteration_budget: Optional[IterationBudget] = None
        self._total_tool_chars: int = 0

        # v8.0: Interrupt queue
        self._interrupt_queue: list = []
        self._is_processing = False

        # v8.2: Agent Team (organization-structured delegation)
        self.team = AgentTeam(self.llm, self.config.get("team", {}))

        # v8.1: Onboarding hints tracking (per user)
        self._shown_hints: dict = {}  # user_id -> set of hint IDs

    def _build_system_prompt(self, user_id: str = None, platform: str = "telegram") -> str:
        """Build the full system prompt from soul + tools + user context + personalization."""
        parts = []

        # 0. Current date/time — always first so LLM knows the actual date
        from datetime import datetime
        now = datetime.now()
        weekday_de = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"][now.weekday()]
        month_de = ["","Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"][now.month]
        parts.append(
            f"WICHTIG — Aktuelles Datum: {weekday_de}, {now.day}. {month_de} {now.year}, {now.strftime('%H:%M')} Uhr. "
            f"Beantworte Datumsfragen NUR mit diesem Datum, niemals mit Trainingswissen."
        )

        # 1. Soul identity
        parts.append(self.soul.get_system_prompt(user_id))

        # 2. Platform context (Hermes-inspired)
        platform_info = {
            "telegram": "Du bist auf Telegram. Kurze, knackige Antworten. Kein Markdown-Rendering außer **fett**. Emojis sparsam einsetzen.",
            "web": "Du bist im Web-Chat. Markdown wird gerendert, Code-Blöcke funktionieren.",
            "cli": "Du bist im Terminal. Klartext, keine Formatierung.",
        }
        parts.append(platform_info.get(platform, platform_info["telegram"]))

        # 3. User context (relationships, preferences)
        if user_id:
            user_ctx = self.soul.get_user_context(user_id)
            if user_ctx:
                parts.append(f"\nKontext ueber den Nutzer:\n{user_ctx}")

        # 4. Personalization addition (for onboarding)
        if user_id:
            pers_addition = self.personalization.get_system_prompt_addition(user_id)
            if pers_addition:
                parts.append(pers_addition)

        # 5. Available tools
        tool_descs = self._get_tool_descriptions()
        parts.append(
            f"\n{self._no_meta_rule}\n"
            f"{self._security_rule}\n\n"
            f"Deine Faehigkeiten — du KANNST all das, nutze es:\n"
            f"- terminal: Shell-Befehle ausfuehren (git, pip, curl, gh, python, etc.)\n"
            f"- web_search: Im Internet suchen (DuckDuckGo)\n"
            f"- web_fetch: Webseiten laden und lesen\n"
            f"- file_read/write/search: Dateien lesen, schreiben, durchsuchen\n"
            f"- code_exec: Python-Code ausfuehren\n"
            f"- delegation: Aufgaben an Team-Abteilungen delegieren (Research, Engineering, Creative, Operations)\n"
            f"- memory: Fakten ueber Nutzer speichern und abrufen\n"
            f"- calculator: Berechnungen\n\n"
            f"WENN dich jemand fragt ob du etwas kannst, pruefe OB EIN TOOL DAFUER EXISTIERT.\n"
            f"Beispiele:\n"
            f"- 'Kannst du auf GitLab zugreifen?' -> JA, via terminal (git clone, gh api, curl) oder delegation an Engineering\n"
            f"- 'Kannst du recherchieren?' -> JA, via web_search oder delegation an Research\n"
            f"- 'Kannst du code schreiben?' -> JA, via file_write + code_exec oder delegation an Engineering\n"
            f"- 'Kannst du mir Daten besorgen?' -> JA, via web_search + web_fetch\n"
            f"NIE 'Ich kann nicht' sagen wenn ein Tool dafuer existiert. Im Zweifel: AUSPROBIEREN.\n\n"
            f"Du hast folgende Werkzeuge zur Verfuegung:\n{tool_descs}\n\n"
            f"Werkzeug-Aufruf-Format (verwende DIES, wenn du ein Werkzeug nutzen willst):\n"
            f"{TOOL_START}JSON_OBJECT{TOOL_END}\n\n"
            f"Beispiel: {TOOL_START}"
            + '{"tool": "terminal", "command": "ls -la"}'
            + f"{TOOL_END}\n\n"
            f"Regeln:\n"
            f"- Verwende Werkzeuge wenn sie helfen, nicht aus Spass\n"
            f"- Beende Werkzeug-Aufrufe mit einer natuerlichen Antwort\n"
            f"- Wenn du eine Aufgabe delegieren willst, nutze 'delegation'\n"
            f"- Wenn du etwas NICHT WEISST oder NICHT KANNST: Recherche es (web_search) oder delegiere an Research\n"
            f"- Wenn etwas gebaut/erstellt werden muss: delegiere an Engineering oder mode=full_team\n"
            f"- DU BIST SELBSTSTAENDIG: Nie 'das kann ich nicht' - finde die Loesung\n"
            f"- Wenn ein Werkzeug fehlschlaegt, versuche es ANDERS, nicht nochmal gleich\n"
            f"- Max {self.max_duplicate_calls}x derselbe Aufruf pro Konversation\n"
            f"- Antworte auf Deutsch wenn der Nutzer Deutsch spricht, sonst in der Sprache des Nutzers\n"
        )

        return "\n\n".join(parts)

    def _get_tool_descriptions(self) -> str:
        """Generate tool descriptions for system prompt."""
        descs = {
            "terminal": "Shell-Befehl ausfuehren - command (Pflicht), timeout (optional), workdir (optional)",
            "file_read": "Datei lesen - path (Pflicht), offset (optional), limit (optional)",
            "file_write": "Datei schreiben - path (Pflicht), content (Pflicht)",
            "file_search": "In Dateien suchen - pattern (Pflicht), path (optional), file_glob (optional)",
            "web_search": "Web-Suche via DuckDuckGo - query (Pflicht), max_results (optional)",
            "web_fetch": "URL-Inhalt abrufen - url (Pflicht), max_length (optional)",
            "code_exec": "Python-Code ausfuehren - code (Pflicht), timeout (optional)",
            "calculator": "Berechnung - expression (Pflicht)",
            "time": "Aktuelle Datum/Zeit - keine Argumente",
            "delegation": "Aufgabe an Team-Abteilung delegieren - task (Pflicht), specialist (ceo/research/engineering/creative/operations/auto), context (optional), mode (single/full_team). auto=CEO entscheidet. full_team=Research+Engineering Kette fuer komplexe Aufgaben.",
            "memory": "Gedaechtnis - action (add/replace/remove/read), content, category, importance",
            "session": "Session-Verwaltung - action (start/save/list/delete), session_id, user_id, summary",
        }
        lines = [f"- **{k}**: {v}" for k, v in descs.items()]
        return "\n".join(lines)

    # ─── Main Entry Point (Pair Architecture) ──────────

    def process(self, user_message: str, user_id: str = None,
                feedback: FeedbackEmitter = None, platform: str = "telegram") -> str:
        """
        Main entry point. Routes through Pair architecture.

        Flow:
        1. Personalization check (first contact?)
        2. Route intent (trivial → direct answer, complex → Worker)
        3. Execute (tools, LLM call, etc.)
        4. Optionally Critique (critical responses)
        5. Update personalization, memory, soul
        """
        self._tool_call_count = 0
        self._tool_call_hashes = []
        self._tool_name_sequence = []
        self._total_tool_chars = 0
        self._is_processing = True
        self._feedback = feedback
        self._iteration_budget = IterationBudget(
            max_calls=self.max_tool_calls,
            max_iterations=self.max_tool_calls,
        )
        start_time = time.time()

        # Emit: thinking started
        if feedback:
            feedback.thinking("Nachricht empfangen — analysiere...")

        # ── 1. Personalization ──
        if user_id:
            pers_result = self.personalization.process_response(user_id, user_message)
            if pers_result.get("phase_advanced"):
                log.info(f"Personalization phase advanced for {user_id}: {pers_result['learned']}")

        # ── 2. Route intent ──
        context_summary = self._get_context_summary()
        routing = self.router.route(user_message, context_summary)

        if feedback:
            feedback.progress(f"Intent: {routing.intent}", detail=f"needs_worker={routing.needs_worker}")

        # ── 3. Trivial → direct answer ──
        if not routing.needs_worker and routing.router_response:
            # Router answered directly — cheap path, no Worker needed
            elapsed = time.time() - start_time
            self.memory.add("user", user_message, importance=0.3)
            self.memory.add("assistant", routing.router_response, importance=0.3)
            if user_id:
                self.soul.update_user(user_id, trust_delta=0.01, last_message=user_message)
            if feedback:
                feedback.done(f"Fertig ({elapsed:.1f}s, Router-Only)")
            self._is_processing = False
            return strip_think_blocks(routing.router_response)

        # ── 4. Complex/Tool-based → Worker handles ──
        # Add to working memory
        self.memory.add("user", user_message, importance=0.5)

        # Build messages for Worker
        system_prompt = self._build_system_prompt(user_id, platform)
        context = self.memory.get_context(query=user_message)

        # Compress context based on routing decision
        raw_messages = [Message("system", system_prompt)]
        for msg in context:
            raw_messages.append(Message(msg["role"], msg["content"]))
        raw_messages.append(Message("user", user_message))

        # Apply context compression
        messages = self.router.compress_context(raw_messages, routing.context_compression)

        if feedback:
            feedback.llm_call(routing.model_key)

        # Track tool calls for auto-skill creation
        _tool_calls_this_turn = []

        # ── 5. Think-Act loop (Worker) ──
        final_response = ""
        for iteration in range(self._iteration_budget.max_iterations):
            self._iteration_budget.increment_iteration()

            # Check iteration budget
            if self._iteration_budget.is_exhausted and self._iteration_budget.can_grace:
                # Grace call: one final attempt for summary
                if feedback:
                    feedback.progress("Budget fast aufgebraucht", detail="Abschluss-Antwort wird erstellt")
                messages.append(Message("system",
                    "Iteration-Budget aufgebraucht. Fasse die bisherigen Ergebnisse zusammen und antworte dem Nutzer. Keine Werkzeuge mehr."
                ))
                self._iteration_budget.use_grace()
            elif self._iteration_budget.is_exhausted:
                final_response = "Maximale Iterationen erreicht. Hier ist was ich bisher herausgefunden habe."
                break

            # v8.0: Check interrupt queue between iterations
            if self._interrupt_queue and iteration > 0:
                interrupt = self._interrupt_queue.pop(0)
                if feedback:
                    feedback.progress(f"Interrupt bei Schritt {iteration}", detail=f"Neue Nachricht: {interrupt.get('text', '')[:50]}")
                messages.append(Message("system",
                    f"[Unterbrochen bei Schritt {iteration}] Der Nutzer hat eine neue Nachricht: "
                    f"'{interrupt.get('text', '')[:200]}'. "
                    f"Antworte kurz darauf und setze danach deine urspruengliche Aufgabe fort."
                ))

            # Choose model based on routing
            model_key = routing.model_key
            response = self.llm.chat(messages, model_key=model_key)

            self._iteration_budget.increment_call()

            if not response.success:
                error_msg = f"[System] LLM-Fehler (Modell: {response.model}): {response.error}. Versuche es kuerzer."
                log.warning(f"LLM call failed: {response.error}")
                messages.append(Message("system", error_msg))
                if self._iteration_budget.call_count >= 2:
                    final_response = f"Entschuldigung, Probleme mit der Sprachmodell-Verbindung ({response.error}). Bitte versuche es gleich nochmal."
                    break
                continue

            # Strip think blocks from response
            content = strip_think_blocks(response.content)

            # Parse response for tool calls
            tool_calls = self._parse_tool_calls(content)

            if not tool_calls:
                # No tool calls - final response
                final_response = self._clean_response(content)
                # If response is empty after cleaning (all was tool tags/think blocks),
                # ask the LLM again with a nudge instead of returning "Verstanden."
                if not final_response.strip():
                    log.warning("Empty response after cleaning, asking LLM for summary")
                    messages.append(Message("system",
                        "Deine vorherige Antwort enthielt keine nutzbaren Inhalte. "
                        "Fasse die bisherigen Ergebnisse zusammen und antworte dem Nutzer direkt, "
                        "ohne Werkzeuge zu verwenden."
                    ))
                    final_response = ""
                    continue
                break

            # Add assistant response to messages
            messages.append(Message("assistant", content))

            # Execute tool calls
            tool_aborted = False
            for tool_call in tool_calls:
                tool_name = tool_call.get("tool", "")
                tool_args = {k: v for k, v in tool_call.items() if k != "tool"}

                # Check iteration budget before each tool
                if self._iteration_budget.is_exhausted and not self._iteration_budget.can_grace:
                    final_response = "Maximale Werkzeug-Aufrufe erreicht."
                    tool_aborted = True
                    break

                # v8.1: Emit feedback for each tool call
                if feedback:
                    args_preview = str(tool_args)[:80] if tool_args else ""
                    feedback.tool_start(tool_name, args_preview)

                # Circular chain detection
                is_circular, chain_desc = self._is_circular_chain(tool_name)
                if is_circular:
                    chain_msg = f"[System] {chain_desc}. Du steckst in einem Kreislauf fest. Fasse zusammen und antworte."
                    messages.append(Message("system", chain_msg))
                    tool_aborted = True
                    break

                # Duplicate detection
                if self._is_loop_detected(tool_call):
                    loop_msg = "[System] Dasselbe Werkzeug bereits mehrfach aufgerufen. Beende die Aufgabe mit dem bisherigen Ergebnis."
                    messages.append(Message("system", loop_msg))
                    tool_aborted = True
                    break

                # Wire special tools
                if tool_name == "memory":
                    result = self._handle_memory_tool(tool_args)
                elif tool_name == "delegation":
                    result = self._handle_delegation(tool_args)
                elif tool_name == "session":
                    result = self._handle_session_tool(tool_args)
                else:
                    result = self.tools.execute(tool_name, **tool_args)

                # Truncate result to budget
                result_text = truncate_result(str(result), MAX_TOOL_RESULT_CHARS)
                self._total_tool_chars += len(result_text)

                # Check total tool result budget
                if self._total_tool_chars > MAX_TOTAL_TOOL_CHARS:
                    result_text += "\n[Gesamt-Budget fuer Werkzeug-Ergebnisse erreicht]"
                    tool_aborted = True

                if feedback:
                    summary = result.output[:60].replace("\n", " ") if result.success else result.error[:60]
                    feedback.tool_result(tool_name, result.success, summary)

                if result.success:
                    _tool_calls_this_turn.append(tool_call)

                if not result.success:
                    result_text = (
                        f"FEHLER bei {tool_name}: {result.error}\n"
                        f"Ausgabe: {result.output[:500]}\n"
                        f"Versuche einen anderen Ansatz."
                    )

                messages.append(Message("system", f"Tool '{tool_name}' Ergebnis:\n{result_text}"))
                self._tool_call_count += 1

            if tool_aborted:
                continue

        if not final_response:
            final_response = "Verstanden."

        # Strip any remaining think blocks
        final_response = strip_think_blocks(final_response)

        # ── 6. Critical response → Critique ──
        if routing.intent == IntentType.CRITICAL and final_response:
            critique = self.router.critique_response(user_message, final_response)
            if critique:
                # Append critique as improvement
                final_response = f"{final_response}\n\n[{critique}]"

        # Save response to memory
        self.memory.add("assistant", final_response, importance=0.5)

        # Update soul relationship
        if user_id:
            self.soul.update_user(user_id, trust_delta=0.01, last_message=user_message)

        # Auto-extract key facts
        self._auto_extract_facts(user_message, final_response, user_id)

        # Auto-create skills from successful multi-step workflows
        if _tool_calls_this_turn:
            self._auto_create_skill(final_response, _tool_calls_this_turn, user_message)

        elapsed = time.time() - start_time
        log.info(f"Processed message in {elapsed:.1f}s, {self._tool_call_count} tool calls, budget: {self._iteration_budget.summary()}")

        # Emit final feedback
        self._is_processing = False
        if feedback:
            feedback.done(f"Fertig ({elapsed:.1f}s, {self._tool_call_count} Schritte)")

        return final_response

    # ─── Context Summary for Router ──────────────────

    def _get_context_summary(self, max_chars: int = 500) -> str:
        """Get a brief summary of recent context for Router classification."""
        recent = self.memory.l1[-4:] if hasattr(self.memory, 'l1') else []
        if not recent:
            return ""
        parts = []
        for entry in recent:
            role = getattr(entry, 'role', 'user')
            content = getattr(entry, 'content', str(entry))[:120]
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    # ─── Tool Call Parsing (unchanged) ──────────────────

    def _parse_tool_calls(self, text):
        calls = []
        pattern = re.escape(TOOL_START) + r"(.*?)" + re.escape(TOOL_END)
        for match in re.finditer(pattern, text, re.DOTALL):
            payload = match.group(1).strip()
            parsed = self._try_parse_json(payload)
            if parsed and "tool" in parsed:
                calls.append(parsed)
        if not calls:
            for match in JSON_BLOCK_RE.finditer(text):
                payload = match.group(1).strip()
                parsed = self._try_parse_json(payload)
                if parsed and "tool" in parsed:
                    calls.append(parsed)
        if not calls:
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("{") and '"tool"' in line:
                    parsed = self._try_parse_json(line)
                    if parsed and "tool" in parsed:
                        calls.append(parsed)
        return calls

    def _try_parse_json(self, text):
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        repaired = text
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        open_brackets = repaired.count('[') - repaired.count(']')
        if open_brackets > 0:
            repaired += ']' * open_brackets
        open_braces = repaired.count('{') - repaired.count('}')
        if open_braces > 0:
            repaired += '}' * open_braces
        repaired = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', repaired)
        repaired = re.sub(r":\s*'([^']*)'", r': "\1"', repaired)
        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                log.info(f"Fuzzy JSON repair succeeded for: {text[:80]}...")
                return result
        except json.JSONDecodeError:
            pass
        log.warning(f"Failed to parse tool call: {text[:100]}")
        return None

    def _clean_response(self, text):
        text = strip_think_blocks(text)
        pattern = re.escape(TOOL_START) + r".*?" + re.escape(TOOL_END)
        text = re.sub(pattern, "", text, flags=re.DOTALL)
        def _remove_json_tool_blocks(match):
            content = match.group(1).strip()
            try:
                obj = json.loads(content)
                if isinstance(obj, dict) and "tool" in obj:
                    return ""
            except (json.JSONDecodeError, ValueError):
                pass
            return match.group(0)
        text = re.sub(r'```json\s*(.*?)\s*```', _remove_json_tool_blocks, text, flags=re.DOTALL)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        # Security: strip leaked secrets from output
        text = self._scrub_secrets(text)
        return text

    # ─── Secret Scrubbing ──────────────────────────

    # Patterns for common secret formats
    _SECRET_PATTERNS = [
        # GitHub/GitLab PATs (ghp_, gho_, glpat-, etc.)
        (r'(ghp|gho|ghu|ghs|ghc|github_pat)_[A-Za-z0-9_]{20,}', '[REDACTED_TOKEN]'),
        # GitLab PATs (glpat- prefix)
        (r'glpat-[A-Za-z0-9_\-]{20,}', '[REDACTED_GITLAB_TOKEN]'),
        # Generic long hex/base64 tokens (40+ chars, looks like a PAT)
        (r'\b[A-Za-z0-9_\-]{40,}\b', lambda m: '[REDACTED]' if any(
            kw in m.group(0).lower() for kw in ['token', 'key', 'secret', 'pass', 'cred']
        ) else m.group(0)),
        # Telegram bot tokens (digit:alpha format)
        (r'\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b', '[REDACTED_BOT_TOKEN]'),
        # .env-style assignments: TOKEN=xxx, PASSWORD=xxx
        (r'(?i)(token|password|secret|api_key|apikey|credential|auth)["\s]*=[\s"]*[^\s"\n]{8,}', 
         lambda m: m.group(0).split('=')[0] + '= [REDACTED]'),
        # Bearer tokens in headers
        (r'(?i)(bearer|authorization)["\s:]+[A-Za-z0-9_\-.]{20,}', '[REDACTED_AUTH]'),
        # Ollama API keys (ollama-...)
        (r'ollama-[A-Za-z0-9]{20,}', '[REDACTED_OLLAMA_KEY]'),
    ]

    def _scrub_secrets(self, text):
        """Remove leaked secrets from LLM output as a safety net."""
        import re as _re
        for pattern, replacement in self._SECRET_PATTERNS:
            if callable(replacement):
                text = _re.sub(pattern, replacement, text)
            else:
                text = _re.sub(pattern, replacement, text)
        return text

    # ─── Loop Detection (unchanged) ──────────────────

    def _hash_tool_call(self, tool_call):
        canonical = json.dumps(tool_call, sort_keys=True)
        return hashlib.md5(canonical.encode()).hexdigest()[:12]

    def _is_loop_detected(self, tool_call):
        call_hash = self._hash_tool_call(tool_call)
        self._tool_call_hashes.append(call_hash)
        count = self._tool_call_hashes.count(call_hash)
        if count >= self.max_duplicate_calls:
            log.warning(f"Loop detected: tool call hash {call_hash} seen {count} times")
            return True
        return False

    def _is_circular_chain(self, tool_name):
        self._tool_name_sequence.append(tool_name)
        seq = self._tool_name_sequence
        n = len(seq)
        if n >= 4:
            for pat_len in (2, 3):
                if n < pat_len * 2:
                    continue
                recent = seq[-pat_len:]
                previous = seq[-(pat_len * 2):-pat_len]
                if recent == previous:
                    pattern_desc = "→".join(recent)
                    repeats = 1
                    for i in range(3, 20):
                        start = -(pat_len * i)
                        end = -(pat_len * (i - 1)) if i > 1 else None
                        chunk = seq[start:end] if end else seq[start:]
                        if list(chunk) == recent:
                            repeats += 1
                        else:
                            break
                    desc = f"Zirkulaere Werkzeug-Kette erkannt: {pattern_desc} (wiederholt {repeats + 1}x)"
                    log.warning(f"Circular chain detected: {pattern_desc} repeated {repeats + 1}x")
                    return True, desc
        if n >= 5:
            tool_counts = Counter(seq)
            for tool, count in tool_counts.items():
                if count >= 3:
                    indices = [i for i, t in enumerate(seq) if t == tool]
                    if len(indices) >= 3:
                        intervals = [indices[i+1] - indices[i] for i in range(len(indices)-1)]
                        short_intervals = sum(1 for iv in intervals if iv <= 2)
                        if short_intervals >= 2:
                            desc = f"Werkzeug '{tool}' wiederholt sich ({count}x Aufrufe, kurze Abstaende)"
                            log.warning(f"Tool cycling detected: {tool} called {count}x with short intervals")
                            return True, desc
        return False, ""

    # ─── Auto Skill Creation (unchanged) ──────────────────

    def _auto_create_skill(self, response, tool_calls, user_message):
        try:
            from nexus.core.skill_autocreator import maybe_create_skill
            created = maybe_create_skill(response, tool_calls, user_message)
            if created:
                for skill_name in created:
                    log.info(f"Auto-created skill: {skill_name}")
                    if self._feedback:
                        self._feedback.progress("Skill erstellt", detail=skill_name)
        except Exception as e:
            log.debug(f"Auto-skill creation skipped: {e}")

    # ─── Interrupt Handling ──────────────────────────────

    def queue_interrupt(self, message, user_id=None):
        self._interrupt_queue.append({
            "text": message,
            "user_id": user_id,
            "timestamp": time.time(),
        })
        log.info(f"Interrupt queued: '{message[:50]}...' (queue: {len(self._interrupt_queue)})")

    @property
    def is_busy(self):
        return self._is_processing

    # ─── Auto Fact Extraction (unchanged) ──────────────────

    _IMPORTANT_FACT_PATTERNS = [
        (r"ich(?:\s+bin|\s+heiße|\s+arbeite)\s+(.+?)(?:\.|!|$)", "identity", 0.9),
        (r"mein\s+(?:name|beruf|projekt|ziel)\s+(?:ist|heißt|lautet)\s+(.+?)(?:\.|!|$)", "identity", 0.9),
        (r"(?:wir|ich)\s+(?:werden|sollen|müssen|entscheiden|beschließen)\s+(.+?)(?:\.|!|$)", "decision", 0.85),
        (r"(?:let's|we'll|we should|I'll)\s+(.+?)(?:\.|!|$)", "decision", 0.8),
        (r"(?:der|die|das)\s+(?:fehler|problem|lösung|ursache)\s+(?:ist|war)\s+(.+?)(?:\.|!|$)", "technical", 0.85),
        (r"(?:the\s+)?(?:error|bug|problem|solution|cause)\s+(?:is|was)\s+(.+?)(?:\.|!|$)", "technical", 0.85),
        (r"(?:die\s+)?(?:konfiguration|einstellung|config)\s+(?:ist|lautet|heißt)\s+(.+?)(?:\.|!|$)", "config", 0.8),
        (r"(?:config|setting)\s+(?:is)\s+(.+?)(?:\.|!|$)", "config", 0.8),
    ]

    def _auto_extract_facts(self, user_message, assistant_response, user_id=None):
        facts_stored = 0
        if user_message:
            soul_facts = self.soul.extract_learnable_facts(user_message)
            for category, fact_text in soul_facts:
                prefix = f"[{user_id}]" if user_id else ""
                content = f"{prefix} {fact_text}" if prefix else fact_text
                self.memory.remember(content, category=f"user_{category}", importance=0.8)
                facts_stored += 1
        if user_message:
            for pattern, category, importance in self._IMPORTANT_FACT_PATTERNS:
                try:
                    match = re.search(pattern, user_message, re.IGNORECASE)
                    if match:
                        fact = match.group(1).strip().rstrip(".,;!")
                        if 5 <= len(fact) <= 200:
                            prefix = f"[{user_id}]" if user_id else ""
                            content = f"{prefix} {fact}" if prefix else fact
                            self.memory.remember(content, category=category, importance=importance)
                            facts_stored += 1
                except Exception:
                    continue
        if assistant_response and len(assistant_response) > 50:
            solution_patterns = [
                r"(?:die\s+Lösung|the\s+solution)\s+(?:ist|is|war|was)\s+(.+?)(?:\.|$)",
                r"(?:du\s+muss|you\s+need\s+to)\s+(.+?)(?:\.|$)",
            ]
            for pattern in solution_patterns:
                try:
                    match = re.search(pattern, assistant_response, re.IGNORECASE)
                    if match:
                        fact = match.group(1).strip().rstrip(".,;!")
                        if 10 <= len(fact) <= 200:
                            self.memory.remember(content=f"Solution: {fact}", category="technical", importance=0.75)
                            facts_stored += 1
                except Exception:
                    continue
        if facts_stored > 0:
            log.info(f"Auto-extracted {facts_stored} facts from conversation turn")

    # ─── Special Tool Handlers (unchanged) ──────────────────

    def _handle_memory_tool(self, args):
        action = args.get("action", "stats")
        if action == "add":
            content = args.get("content", "")
            category = args.get("category", "general")
            importance = float(args.get("importance", 0.7))
            self.memory.remember(content, category, importance)
            return ToolResult(True, f"Gespeichert: {content[:100]}")
        elif action == "replace":
            old = args.get("old", "")
            new = args.get("new", "")
            category = args.get("category", "general")
            # Simple replace in memory — search and update
            self.memory.remember(f"REPLACE:{old} → {new}", category, importance=0.5)
            return ToolResult(True, f"Ersetzt: '{old[:50]}' → '{new[:50]}'")
        elif action == "remove":
            content = args.get("content", "")
            category = args.get("category", "general")
            self.memory.remember(f"REMOVE:{content}", category, importance=-1.0)
            return ToolResult(True, f"Entfernt: {content[:50]}")
        elif action == "read":
            category = args.get("category", "")
            stats = self.memory.stats()
            if category:
                results = self.memory.recall(category)
                return ToolResult(True, f"Memory ({category}):\n" + "\n".join(f"- {r}" for r in results))
            return ToolResult(True, f"Memory: L1={stats['l1_entries']}, L2={stats['l2_entries']}, L3={stats['l3_entries']}")
        elif action == "remember":
            content = args.get("content", "")
            category = args.get("category", "general")
            importance = float(args.get("importance", 0.7))
            self.memory.remember(content, category, importance)
            return ToolResult(True, f"Gespeichert: {content[:100]}")
        elif action == "recall":
            query = args.get("content", "")
            results = self.memory.recall(query)
            if results:
                return ToolResult(True, "Erinnerungen:\n" + "\n".join(f"- {r}" for r in results))
            return ToolResult(True, "Keine Erinnerungen gefunden.")
        elif action == "stats":
            stats = self.memory.stats()
            return ToolResult(True, f"Memory: L1={stats['l1_entries']}, L2={stats['l2_entries']}, L3={stats['l3_entries']}")
        return ToolResult(False, "", f"Unknown memory action: {action}")

    def _handle_delegation(self, args):
        task = args.get("task", "")
        specialist = args.get("specialist", "coding")
        context = args.get("context", "")
        mode = args.get("mode", "single")  # single or full_team

        # Map old specialist names to team departments
        dept_map = {
            "coding": "engineering",
            "research": "research",
            "analysis": "operations",
            "creative": "creative",
            "fast": "operations",
            "engineering": "engineering",
            "operations": "operations",
            "ceo": "ceo",
        }
        department = dept_map.get(specialist, "auto")

        if mode == "full_team":
            # Full research-and-build cycle: CEO -> Research -> Engineering
            result_text = self.team.research_and_build(task, context)
            return ToolResult(True, result_text, data={"mode": "full_team"})
        else:
            # Single department delegation
            team_task = self.team.delegate(task, department=department, context=context)
            if team_task.status == "completed":
                return ToolResult(True, team_task.result, data={
                    "department": team_task.department,
                    "task_id": team_task.task_id,
                    "elapsed": round(team_task.elapsed, 1),
                })
            return ToolResult(False, "", f"Delegation fehlgeschlagen: {team_task.result}")

    def _handle_session_tool(self, args):
        action = args.get("action", "list")
        session_id = args.get("session_id", "")
        user_id = args.get("user_id", "")
        if action == "start":
            sid = self.start_session(user_id=user_id, session_id=session_id or None)
            return ToolResult(True, f"Session gestartet: {sid}", data={"session_id": sid})
        elif action == "save":
            summary = args.get("summary", "")
            success = self.save_conversation(summary=summary)
            if success:
                return ToolResult(True, f"Session {_short_id(self._session_id)} gespeichert")
            return ToolResult(False, "", "Keine aktive Session zum Speichern")
        elif action == "list":
            sessions = self.list_conversations(user_id=user_id or None)
            if not sessions:
                return ToolResult(True, "Keine gespeicherten Sessions vorhanden")
            from datetime import datetime
            lines = []
            for s in sessions:
                ts = datetime.fromtimestamp(s.get("last_active", 0)).strftime("%Y-%m-%d %H:%M")
                lines.append(f"- {s['session_id'][:16]}... | {ts} | {s.get('message_count', 0)} Msgs | {s.get('summary', '')[:50]}")
            return ToolResult(True, "Gespeicherte Sessions:\n" + "\n".join(lines))
        elif action == "delete":
            success = self.delete_conversation(session_id)
            if success:
                return ToolResult(True, f"Session geloescht: {session_id[:16]}")
            return ToolResult(False, "", f"Session nicht gefunden: {session_id[:16]}")
        return ToolResult(False, "", f"Unknown session action: {action}")

    # ─── Lifecycle ──────────────────────────────────────

    def shutdown(self):
        if self._session_id:
            self.save_conversation()
        self.memory.end_session()
        self.soul.save()
        log.info(f"NEXUS shutdown. LLM stats: {self.llm.stats()}")

    def stats(self):
        return {
            "llm": self.llm.stats(),
            "memory": self.memory.stats(),
            "conversations": self.conversations.stats(),
            "tool_calls_this_turn": self._tool_call_count,
            "soul_relationships": len(self.soul.relationships),
            "iteration_budget": self._iteration_budget.summary() if self._iteration_budget else "N/A",
        }

    # ─── Session Management (unchanged) ──────────────────

    def start_session(self, user_id=None, session_id=None):
        if session_id:
            entries = self.conversations.load_session(session_id)
            if entries:
                for entry in entries:
                    self.memory.add(
                        entry.get("role", "user"),
                        entry.get("content", ""),
                        importance=entry.get("importance", 0.5),
                    )
                self._session_id = session_id
                log.info(f"Resumed session {session_id} with {len(entries)} messages")
                return session_id
            else:
                log.warning(f"Session {session_id} not found, starting new session")
        self._session_id = session_id or f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        log.info(f"Started new session {self._session_id}, user={user_id or 'unknown'}")
        return self._session_id

    def save_conversation(self, summary=""):
        if not self._session_id:
            log.warning("No active session to save")
            return False
        entries = [
            {
                "role": entry.role,
                "content": entry.content,
                "timestamp": entry.timestamp,
                "tokens": entry.tokens,
                "importance": entry.importance,
            }
            for entry in self.memory.l1
        ]
        user_id = ""
        for entry in self.memory.l1:
            if entry.role == "user":
                user_id = getattr(entry, "user_id", "") or "default"
                break
        if not summary and self.memory.l1:
            topics = self.memory._extract_topics(
                " ".join(e.content[:200] for e in self.memory.l1[:4])
            )
            summary = f"Topics: {', '.join(topics[:3])}" if topics else "Conversation"
        return self.conversations.save_session(
            session_id=self._session_id,
            entries=entries,
            user_id=user_id,
            summary=summary,
        )

    def list_conversations(self, user_id=None, limit=10):
        return self.conversations.list_sessions(user_id=user_id, limit=limit)

    def delete_conversation(self, session_id):
        return self.conversations.delete_session(session_id)
