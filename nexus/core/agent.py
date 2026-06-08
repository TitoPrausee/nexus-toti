"""
NEXUS v7 — Agent Core
One smart agent. Thinks first, acts second, delegates when needed.
Robust tool-call loop with duplicate detection and error recovery.
"""

import re
import json
import time
import hashlib
import uuid
import logging
import os
from typing import Optional, AsyncIterator
from collections import Counter
from pathlib import Path

from nexus.core.llm_client import LLMClient, Message, LLMResponse
from nexus.core.memory import MemorySystem
from nexus.core.tools import ToolRegistry, ToolResult
from nexus.core.conversations import ConversationStore
from nexus.core.feedback import FeedbackEmitter, FeedbackType
from nexus.soul import SoulEngine

log = logging.getLogger("nexus.agent")

# Tool call tags - XML-style markers for tool invocation in LLM output
# Using angle-bracket style to avoid conflicts: <tool>...</tool>
TOOL_START = "<tool>"
TOOL_END = "</tool>"

# Also support ```json code blocks as tool calls (LLM might output this format)
JSON_BLOCK_RE = re.compile(r"```json\s*(\{[^`]*?" + re.escape('"tool"') + r"[^`]*?\})\s*```", re.DOTALL)


def _short_id(sid: str) -> str:
    """Shorten a session ID for display."""
    if not sid:
        return "none"
    return sid[:16] + "..." if len(sid) > 16 else sid


class NexusAgent:
    """
    The brain. One agent with soul, memory, and tools.

    Thinking flow:
    1. Receive message -> load context (soul + memory + tools)
    2. Build system prompt (identity + user context + available tools)
    3. Call LLM -> parse response for tool calls
    4. Execute tools -> feed results back
    5. Iterate until LLM gives final text response
    6. Save to memory -> update soul -> auto-extract facts -> respond

    v8.0: Active feedback — emits step-by-step progress during processing.
    v8.0: Interrupt handling — queue for incoming messages during long tasks.
    v8.0: Auto-skill creation — learns from successful multi-step workflows.
    v7.6: Circular chain detection — prevents A→B→A alternating loops.
    v7.3: Auto fact extraction — key facts saved to L3 automatically.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

        # Core systems
        self.llm = LLMClient(self.config.get("llm", {}))
        self.memory = MemorySystem(config=self.config.get("memory", {}))
        self.soul = SoulEngine()
        self.tools = ToolRegistry(config=self.config.get("tools", {}))
        self.conversations = ConversationStore(
            data_dir=self.config.get("conversations", {}).get("data_dir", "data/sessions"),
            max_sessions=self.config.get("conversations", {}).get("max_sessions", 100),
        )

        # Performance settings
        perf = self.config.get("performance", {})
        self.max_tool_calls = perf.get("max_tool_calls_per_turn", 15)
        self.max_tokens_per_turn = perf.get("max_tokens_per_turn", 8000)
        self.max_duplicate_calls = perf.get("max_duplicate_calls", 3)  # Same tool+args repeated
        self.max_chain_repeats = perf.get("max_chain_repeats", 2)  # Same A→B pattern repeated

        # State
        self._tool_call_count = 0
        self._tool_call_hashes = []  # Track tool call hashes for loop detection
        self._tool_name_sequence = []  # Track tool name sequence for circular chain detection
        self._session_id: Optional[str] = None  # Current conversation session

        # v8.0: Feedback emitter for real-time progress
        self._feedback: Optional[FeedbackEmitter] = None

        # v8.0: Interrupt queue — messages that arrive while processing
        self._interrupt_queue: list[dict] = []
        self._is_processing = False

    def _build_system_prompt(self, user_id: str = None) -> str:
        """Build the full system prompt from soul + tools + user context."""
        parts = []

        # 1. Soul identity
        parts.append(self.soul.get_system_prompt())

        # 2. User context (relationships, preferences)
        if user_id:
            user_ctx = self.soul.get_user_context(user_id)
            if user_ctx:
                parts.append(f"\nKontext ueber den Nutzer:\n{user_ctx}")

        # 3. Available tools
        tool_descs = self._get_tool_descriptions()
        parts.append(
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
            f"- Wenn ein Werkzeug fehlschlaegt, versuche es ANDERS, nicht nochmal gleich\n"
            f"- Max {self.max_duplicate_calls}x derselbe Aufruf pro Konversation\n"
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
            "delegation": "Aufgabe an Spezialisten - task (Pflicht), specialist (coding/research/analysis/creative/fast), context (optional)",
            "memory": "Gedaechtnis - action (remember/recall/stats), content, category, importance",
            "session": "Session-Verwaltung - action (start/save/list/delete), session_id, user_id, summary",
        }
        lines = [f"- **{k}**: {v}" for k, v in descs.items()]
        return "\n".join(lines)

    def _hash_tool_call(self, tool_call: dict) -> str:
        """Create a hash of a tool call for duplicate detection."""
        # Sort keys for deterministic hashing
        canonical = json.dumps(tool_call, sort_keys=True)
        return hashlib.md5(canonical.encode()).hexdigest()[:12]

    def _is_loop_detected(self, tool_call: dict) -> bool:
        """Check if we've seen the same tool call too many times (= infinite loop)."""
        call_hash = self._hash_tool_call(tool_call)
        self._tool_call_hashes.append(call_hash)
        count = self._tool_call_hashes.count(call_hash)
        if count >= self.max_duplicate_calls:
            log.warning(f"Loop detected: tool call hash {call_hash} seen {count} times")
            return True
        return False

    def _is_circular_chain(self, tool_name: str) -> "tuple[bool, str]":
        """Detect circular tool-call chains like A→B→A, A→B→C→A, A→B→A→B.

        Tracks sequences of tool names and detects when the same pattern
        repeats, indicating the agent is cycling between tools without progress.

        Returns:
            (is_circular, description) — description explains which pattern was detected.
        """
        self._tool_name_sequence.append(tool_name)
        seq = self._tool_name_sequence
        n = len(seq)

        # Check patterns of length 2: A→B repeating
        # e.g., [terminal, file_read, terminal, file_read] → terminal→file_read repeats
        if n >= 4:
            for pat_len in (2, 3):
                if n < pat_len * 2:
                    continue
                # Check if the last `pat_len` elements match the `pat_len` elements before them
                recent = seq[-pat_len:]
                previous = seq[-(pat_len * 2):-pat_len]
                if recent == previous:
                    pattern_desc = "→".join(recent)
                    repeats = 1
                    # Count how many times the pattern repeats consecutively
                    for i in range(3, 20):
                        start = -(pat_len * i)
                        end = -(pat_len * (i - 1)) if i > 1 else None
                        if end is None:
                            chunk = seq[start:]
                        else:
                            chunk = seq[start:end]
                        if list(chunk) == recent:
                            repeats += 1
                        else:
                            break
                    desc = f"Zirkulaere Werkzeug-Kette erkannt: {pattern_desc} (wiederholt {repeats + 1}x)"
                    log.warning(f"Circular chain detected: {pattern_desc} repeated {repeats + 1}x")
                    return True, desc

        # Check for return-to-same-tool patterns: A appears multiple times
        # separated by different tools, suggesting the agent keeps coming back
        # e.g., [terminal, file_read, terminal, code_exec, terminal] → terminal keeps returning
        if n >= 5:
            tool_counts = Counter(seq)
            for tool, count in tool_counts.items():
                if count >= 3:
                    # Find the indices where this tool appears
                    indices = [i for i, t in enumerate(seq) if t == tool]
                    # Check if intervals between calls are shrinking (getting stuck)
                    if len(indices) >= 3:
                        intervals = [indices[i+1] - indices[i] for i in range(len(indices)-1)]
                        # If the tool was called 3+ times with short intervals (1-2 tools between)
                        # that's a sign of cycling
                        short_intervals = sum(1 for iv in intervals if iv <= 2)
                        if short_intervals >= 2:
                            desc = f"Werkzeug '{tool}' wiederholt sich ({count}x Aufrufe, kurze Abstaende)"
                            log.warning(f"Tool cycling detected: {tool} called {count}x with short intervals")
                            return True, desc

        return False, ""

    def process(self, user_message: str, user_id: str = None,
                feedback: FeedbackEmitter = None) -> str:
        """
        Main entry point. Process a user message and return response.
        Synchronous - for Telegram bot.

        v8.0: Accepts optional FeedbackEmitter for real-time step display.
        v8.0: Checks interrupt queue between iterations.
        v8.0: Auto-creates skills from successful multi-step workflows.

        Includes:
        - LLM error recovery (don't crash on LLM failure)
        - Tool call loop detection (same call N times = break)
        - Tool error feedback to LLM (try differently)
        - Max tool call safety limit
        """
        self._tool_call_count = 0
        self._tool_call_hashes = []
        self._tool_name_sequence = []  # Reset for circular chain detection
        self._is_processing = True
        self._feedback = feedback
        start_time = time.time()

        # Emit: thinking started
        if feedback:
            feedback.thinking("Nachricht empfangen — analysiere...")

        # 1. Add to working memory
        self.memory.add("user", user_message, importance=0.5)

        # 2. Build messages for LLM
        system_prompt = self._build_system_prompt(user_id)
        context = self.memory.get_context(query=user_message)

        if feedback:
            feedback.llm_call(self.llm._get_model_name("default"))

        messages = [Message("system", system_prompt)]
        for msg in context:
            messages.append(Message(msg["role"], msg["content"]))
        messages.append(Message("user", user_message))

        # Track tool calls for auto-skill creation
        _tool_calls_this_turn = []

        # 3. Think-Act loop
        final_response = ""
        for iteration in range(self.max_tool_calls):
            # v8.0: Check interrupt queue between iterations
            if self._interrupt_queue and iteration > 0:
                interrupt = self._interrupt_queue.pop(0)
                if feedback:
                    feedback.progress(
                        f"Interrupt bei Schritt {iteration}",
                        detail=f"Neue Nachricht: {interrupt.get('text', '')[:50]}"
                    )
                # Queue the current task and acknowledge interrupt
                interrupt_ack = f"⚡ Unterbreche aktuelle Aufgabe (Schritt {iteration}). Antworte kurz auf deine Nachricht und setze danach fort."
                # Add interrupt context to messages
                messages.append(Message("system",
                    f"[Unterbrochen bei Schritt {iteration}] Der Nutzer hat eine neue Nachricht: "
                    f"'{interrupt.get('text', '')[:200]}'. "
                    f"Antworte kurz darauf und setze danach deine ursprüngliche Aufgabe fort."
                ))
                # We'll continue the current loop — the LLM will see the interrupt

            response = self.llm.chat(messages, model_key="default")

            if not response.success:
                # LLM failed - add error context and let the loop continue
                # This gives the agent a chance to recover or inform the user
                error_msg = (
                    f"[System] LLM-Fehler (Modell: {response.model}): {response.error}. "
                    f"Versuche es ohne Werkzeuge zu beantworten oder kuerzer zu formulieren."
                )
                log.warning(f"LLM call failed: {response.error}")
                messages.append(Message("system", error_msg))

                # After 2 consecutive LLM failures, give up gracefully
                if iteration >= 1:
                    final_response = (
                        f"Entschuldigung, ich hatte Probleme mit der Sprachmodell-Verbindung "
                        f"({response.error}). Bitte versuche es gleich nochmal."
                    )
                    break
                continue

            # Parse response for tool calls
            tool_calls = self._parse_tool_calls(response.content)

            if not tool_calls:
                # No tool calls - final response
                final_response = self._clean_response(response.content)
                break

            # Add assistant response to messages
            messages.append(Message("assistant", response.content))

            # Execute tool calls
            tool_aborted = False
            for tool_call in tool_calls:
                tool_name = tool_call.get("tool", "")
                tool_args = {k: v for k, v in tool_call.items() if k != "tool"}

                # v8.0: Emit feedback for each tool call
                if feedback:
                    args_preview = str(tool_args)[:80] if tool_args else ""
                    feedback.tool_start(tool_name, args_preview)

                # Circular chain detection: A→B→A pattern where the agent
                # cycles between tools without making progress
                # Checked BEFORE duplicate detection since circular chains
                # can have different args each time (more subtle loop)
                is_circular, chain_desc = self._is_circular_chain(tool_name)
                if is_circular:
                    chain_msg = (
                        f"[System] {chain_desc}. "
                        f"Du steckst in einem Kreislauf fest. "
                        f"Fasse die bisherigen Ergebnisse zusammen und antworte dem Nutzer. "
                        f"Versuche NICHT, dasselbe nochmal mit leicht anderen Argumenten."
                    )
                    messages.append(Message("system", chain_msg))
                    log.warning(f"Circular chain detected: {chain_desc}")
                    tool_aborted = True
                    break

                # Duplicate detection: same tool call repeated too many times
                if self._is_loop_detected(tool_call):
                    loop_msg = (
                        f"[System] Du hast dasselbe Werkzeug bereits mehrfach mit "
                        f"denselben Argumenten aufgerufen. Beende die Aufgabe mit dem "
                        f"bisherigen Ergebnis oder aendere deinen Ansatz."
                    )
                    messages.append(Message("system", loop_msg))
                    log.warning(f"Loop detected for tool call: {tool_name}")
                    tool_aborted = True
                    break

                # Wire special tools to their handlers
                if tool_name == "memory":
                    result = self._handle_memory_tool(tool_args)
                elif tool_name == "delegation":
                    result = self._handle_delegation(tool_args)
                elif tool_name == "session":
                    result = self._handle_session_tool(tool_args)
                else:
                    result = self.tools.execute(tool_name, **tool_args)

                result_text = str(result)

                # v8.0: Emit feedback for tool result
                if feedback:
                    summary = result.output[:60].replace("\n", " ") if result.success else result.error[:60]
                    feedback.tool_result(tool_name, result.success, summary)

                # v8.0: Track successful tool calls for auto-skill creation
                if result.success:
                    _tool_calls_this_turn.append(tool_call)

                # Provide better feedback for failed tools
                if not result.success:
                    result_text = (
                        f"FEHLER bei {tool_name}: {result.error}\n"
                        f"Ausgabe: {result.output[:500]}\n"
                        f"Versuche einen anderen Ansatz oder beende ohne dieses Werkzeug."
                    )

                messages.append(Message("system", f"Tool '{tool_name}' Ergebnis:\n{result_text}"))
                self._tool_call_count += 1

                if self._tool_call_count >= self.max_tool_calls:
                    final_response = "Maximale Werkzeug-Aufrufe erreicht."
                    tool_aborted = True
                    break

            if tool_aborted:
                # Continue one more iteration so the LLM can provide a final answer
                # after loop detection or max calls
                continue

        if not final_response:
            final_response = "Verstanden."

        # Save response to memory
        self.memory.add("assistant", final_response, importance=0.5)

        # Update user relationship (with language detection and mood tracking)
        if user_id:
            self.soul.update_user(user_id, trust_delta=0.01, last_message=user_message)

        # Auto-extract key facts from this conversation turn to L3
        self._auto_extract_facts(user_message, final_response, user_id)

        # v8.0: Auto-create skills from successful multi-step workflows
        if _tool_calls_this_turn:
            self._auto_create_skill(final_response, _tool_calls_this_turn, user_message)

        elapsed = time.time() - start_time
        log.info(f"Processed message in {elapsed:.1f}s, {self._tool_call_count} tool calls")

        # v8.0: Emit final feedback
        self._is_processing = False
        if feedback:
            feedback.done(f"Fertig ({elapsed:.1f}s, {self._tool_call_count} Schritte)")

        return final_response

    async def process_stream(self, user_message: str, user_id: str = None):
        """Stream response token by token. Yields partial text."""
        self.memory.add("user", user_message, importance=0.5)

        system_prompt = self._build_system_prompt(user_id)
        context = self.memory.get_context()

        messages = [Message("system", system_prompt)]
        for msg in context:
            messages.append(Message(msg["role"], msg["content"]))
        messages.append(Message("user", user_message))

        full_response = ""
        async for token in self.llm.chat_stream(messages, model_key="default"):
            # Skip tool call syntax in stream
            if TOOL_START in token or "```json" in token:
                continue
            full_response += token
            yield token

        self.memory.add("assistant", full_response, importance=0.5)
        if user_id:
            self.soul.update_user(user_id, trust_delta=0.01, last_message=user_message)

        # Auto-extract key facts from this conversation turn to L3
        self._auto_extract_facts(user_message, full_response, user_id)

    # ─── Tool Call Parsing ──────────────────────────────

    def _parse_tool_calls(self, text: str) -> list:
        """Extract tool calls from LLM response.

        Supports two formats:
        1. XML-style: <tool>JSON</tool>
        2. Code block: ```json {"tool": ...} ```
        Also attempts fuzzy JSON repair for malformed calls.
        """
        calls = []

        # Format 1: <tool>...</tool>
        pattern = re.escape(TOOL_START) + r"(.*?)" + re.escape(TOOL_END)
        for match in re.finditer(pattern, text, re.DOTALL):
            payload = match.group(1).strip()
            parsed = self._try_parse_json(payload)
            if parsed and "tool" in parsed:
                calls.append(parsed)

        # Format 2: ```json ... ```
        if not calls:
            for match in JSON_BLOCK_RE.finditer(text):
                payload = match.group(1).strip()
                parsed = self._try_parse_json(payload)
                if parsed and "tool" in parsed:
                    calls.append(parsed)

        # Format 3: Inline JSON on its own line (LLM sometimes outputs raw JSON)
        if not calls:
            # Look for lines that start with { and contain "tool"
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("{") and '"tool"' in line:
                    parsed = self._try_parse_json(line)
                    if parsed and "tool" in parsed:
                        calls.append(parsed)

        return calls

    def _try_parse_json(self, text: str) -> "dict | None":
        """Try to parse JSON, with fuzzy repair for common LLM mistakes."""
        # First attempt: clean parse
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Second attempt: repair common issues
        repaired = text

        # Fix trailing commas before } or ]
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)

        # Fix missing closing brackets/braces — add in reverse nesting order
        # (inner ] before outer }) so the JSON is structurally valid
        open_brackets = repaired.count('[') - repaired.count(']')
        if open_brackets > 0:
            repaired += ']' * open_brackets

        open_braces = repaired.count('{') - repaired.count('}')
        if open_braces > 0:
            repaired += '}' * open_braces

        # Fix single quotes instead of double quotes
        # Only replace quotes around keys and string values
        repaired = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', repaired)  # keys
        repaired = re.sub(r":\s*'([^']*)'", r': "\1"', repaired)  # values

        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                log.info(f"Fuzzy JSON repair succeeded for: {text[:80]}...")
                return result
        except json.JSONDecodeError:
            pass

        log.warning(f"Failed to parse tool call: {text[:100]}")
        return None

    def _clean_response(self, text: str) -> str:
        """Remove tool call blocks from final response."""
        # First: remove <tool>...</tool> blocks
        pattern = re.escape(TOOL_START) + r".*?" + re.escape(TOOL_END)
        text = re.sub(pattern, "", text, flags=re.DOTALL)
        # Second: remove ```json ... ``` code blocks that contain "tool" key
        # Use a two-pass approach: extract JSON blocks, check if they contain "tool"
        def _remove_json_tool_blocks(match):
            content = match.group(1).strip()
            # Only remove if it's a valid JSON object containing "tool" key
            try:
                obj = json.loads(content)
                if isinstance(obj, dict) and "tool" in obj:
                    return ""
            except (json.JSONDecodeError, ValueError):
                pass
            return match.group(0)  # Keep non-tool JSON blocks
        text = re.sub(r'```json\s*(.*?)\s*```', _remove_json_tool_blocks, text, flags=re.DOTALL)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ─── Auto Skill Creation ──────────────────────────────

    def _auto_create_skill(self, response: str, tool_calls: list, user_message: str):
        """Auto-create a skill from successful multi-step workflows."""
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

    def queue_interrupt(self, message: str, user_id: str = None):
        """Queue an incoming message while the agent is busy processing.

        The agent will see this message in the next iteration of its
        think-act loop and briefly respond before continuing.
        """
        self._interrupt_queue.append({
            "text": message,
            "user_id": user_id,
            "timestamp": time.time(),
        })
        log.info(f"Interrupt queued: '{message[:50]}...' (queue: {len(self._interrupt_queue)})")

    @property
    def is_busy(self) -> bool:
        """Whether the agent is currently processing a message."""
        return self._is_processing

    # ─── Auto Fact Extraction ──────────────────────────

    # Patterns indicating important facts worth remembering in L3
    _IMPORTANT_FACT_PATTERNS = [
        # User identity and preferences
        (r"ich(?:\s+bin|\s+heiße|\s+arbeite)\s+(.+?)(?:\.|!|$)", "identity", 0.9),
        (r"mein\s+(?:name|beruf|projekt|ziel)\s+(?:ist|heißt|lautet)\s+(.+?)(?:\.|!|$)", "identity", 0.9),
        # Decisions and commitments
        (r"(?:wir|ich)\s+(?:werden|sollen|müssen|entscheiden|beschließen)\s+(.+?)(?:\.|!|$)", "decision", 0.85),
        (r"(?:let's|we'll|we should|I'll)\s+(.+?)(?:\.|!|$)", "decision", 0.8),
        # Important technical facts
        (r"(?:der|die|das)\s+(?:fehler|problem|lösung|ursache)\s+(?:ist|war)\s+(.+?)(?:\.|!|$)", "technical", 0.85),
        (r"(?:the\s+)?(?:error|bug|problem|solution|cause)\s+(?:is|was)\s+(.+?)(?:\.|!|$)", "technical", 0.85),
        # Configuration and setup facts
        (r"(?:die\s+)?(?:konfiguration|einstellung|config)\s+(?:ist|lautet|heißt)\s+(.+?)(?:\.|!|$)", "config", 0.8),
        (r"(?:config|setting)\s+(?:is)\s+(.+?)(?:\.|!|$)", "config", 0.8),
    ]

    def _auto_extract_facts(self, user_message: str, assistant_response: str, user_id: str = None):
        """Extract key facts from the conversation turn and save to L3.

        This runs automatically after each turn, without requiring an explicit
        'memory remember' tool call. Facts are extracted using pattern matching
        and the soul's extract_learnable_facts() method, then deduplicated
        before storage.

        Only extracts from user messages — assistant responses are not mined
        for facts (the user's stated facts are what matters for personalization).

        v7.3: Added to complement proactive L3 learning from soul patterns.
        """
        facts_stored = 0

        # 1. Use soul's pattern-based extraction (already exists)
        if user_message:
            soul_facts = self.soul.extract_learnable_facts(user_message)
            for category, fact_text in soul_facts:
                prefix = f"[{user_id}]" if user_id else ""
                content = f"{prefix} {fact_text}" if prefix else fact_text
                self.memory.remember(
                    content=content,
                    category=f"user_{category}",
                    importance=0.8,
                )
                facts_stored += 1

        # 2. Pattern-based extraction for important facts
        if user_message:
            for pattern, category, importance in self._IMPORTANT_FACT_PATTERNS:
                try:
                    match = re.search(pattern, user_message, re.IGNORECASE)
                    if match:
                        fact = match.group(1).strip().rstrip(".,;!")
                        if 5 <= len(fact) <= 200:
                            prefix = f"[{user_id}]" if user_id else ""
                            content = f"{prefix} {fact}" if prefix else fact
                            self.memory.remember(
                                content=content,
                                category=category,
                                importance=importance,
                            )
                            facts_stored += 1
                except Exception:
                    continue

        # 3. Extract high-importance items from assistant response
        # If the response contains a definitive answer or solution, save it
        if assistant_response and len(assistant_response) > 50:
            # Check for solution patterns in the response
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
                            self.memory.remember(
                                content=f"Solution: {fact}",
                                category="technical",
                                importance=0.75,
                            )
                            facts_stored += 1
                except Exception:
                    continue

        if facts_stored > 0:
            log.info(f"Auto-extracted {facts_stored} facts from conversation turn")

    # ─── Special Tool Handlers ──────────────────────────

    def _handle_memory_tool(self, args: dict) -> ToolResult:
        """Wire memory tool to actual MemorySystem."""
        action = args.get("action", "stats")

        if action == "remember":
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

    def _handle_delegation(self, args: dict) -> ToolResult:
        """Handle delegation to specialist models."""
        task = args.get("task", "")
        specialist = args.get("specialist", "coding")
        context = args.get("context", "")

        model_map = {
            "coding": "coding",
            "research": "research",
            "analysis": "analysis",
            "creative": "creative",
            "fast": "fast",
        }
        model_key = model_map.get(specialist, "default")

        prompt = f"Spezial-Aufgabe ({specialist}): {task}"
        if context:
            prompt += f"\nKontext: {context}"

        messages = [
            Message("system", f"Du bist ein Spezialist fuer {specialist}. Loese die Aufgabe praezise."),
            Message("user", prompt),
        ]

        response = self.llm.chat(messages, model_key=model_key)

        if response.success:
            return ToolResult(True, response.content, data={"model": response.model, "tokens": response.total_tokens})
        return ToolResult(False, "", f"Delegation fehlgeschlagen: {response.error}")

    def _handle_session_tool(self, args: dict) -> ToolResult:
        """
        Handle session management tool calls.

        Actions:
        - start: Start a new or resume an existing session.
        - save: Save current conversation to disk.
        - list: List available sessions.
        - delete: Delete a session.
        """
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
            lines = []
            for s in sessions:
                from datetime import datetime
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
        """Graceful shutdown - save everything including conversation session."""
        # Auto-save current session if active
        if self._session_id:
            self.save_conversation()
        self.memory.end_session()
        self.soul.save()
        log.info(f"NEXUS shutdown. LLM stats: {self.llm.stats()}")

    def stats(self) -> dict:
        """Get overall stats."""
        return {
            "llm": self.llm.stats(),
            "memory": self.memory.stats(),
            "conversations": self.conversations.stats(),
            "tool_calls_this_turn": self._tool_call_count,
            "soul_relationships": len(self.soul.relationships),
        }

    # ─── Session Management ──────────────────────────────────

    def start_session(self, user_id: str = None, session_id: str = None) -> str:
        """
        Start a new conversation session or resume an existing one.

        If session_id is provided and exists, loads that session's L1 messages
        into working memory. Otherwise, creates a new session with a unique ID.

        Args:
            user_id: The user starting this session.
            session_id: Optional existing session to resume.

        Returns:
            The session ID (new or resumed).
        """
        if session_id:
            # Try to resume existing session
            entries = self.conversations.load_session(session_id)
            if entries:
                # Restore L1 working memory from saved session
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

        # Create new session
        self._session_id = session_id or f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        log.info(f"Started new session {self._session_id}, user={user_id or 'unknown'}")
        return self._session_id

    def save_conversation(self, summary: str = "") -> bool:
        """
        Save the current conversation session to disk.

        Persists all L1 working memory entries along with metadata.
        Can be called at any time to create a checkpoint.

        Args:
            summary: Optional summary of the conversation so far.

        Returns:
            True if saved successfully.
        """
        if not self._session_id:
            log.warning("No active session to save")
            return False

        # Collect L1 entries as serializable dicts
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

        # Extract user_id from memory entries if available
        user_id = ""
        for entry in self.memory.l1:
            if entry.role == "user":
                user_id = getattr(entry, "user_id", "") or "default"
                break

        # Auto-generate summary from L1 content if not provided
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

    def list_conversations(self, user_id: str = None, limit: int = 10) -> list[dict]:
        """
        List available conversation sessions.

        Args:
            user_id: Filter by user (None for all).
            limit: Maximum sessions to return.

        Returns:
            List of session metadata dicts.
        """
        return self.conversations.list_sessions(user_id=user_id, limit=limit)

    def delete_conversation(self, session_id: str) -> bool:
        """Delete a conversation session by ID."""
        return self.conversations.delete_session(session_id)