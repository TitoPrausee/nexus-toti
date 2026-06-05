"""
NEXUS v7 — Agent Core
One smart agent. Thinks first, acts second, delegates when needed.
"""

import re
import json
import time
import logging
from typing import Optional, AsyncIterator

from nexus.core.llm_client import LLMClient, Message, LLMResponse
from nexus.core.memory import MemorySystem
from nexus.core.tools import ToolRegistry, ToolResult
from nexus.soul import SoulEngine

log = logging.getLogger("nexus.agent")

# Tool call tags - XML-style markers for tool invocation in LLM output
# Using angle-bracket style to avoid conflicts: <tool>...</tool>
TOOL_START = "<tool>"
TOOL_END = "</tool>"


class NexusAgent:
    """
    The brain. One agent with soul, memory, and tools.

    Thinking flow:
    1. Receive message -> load context (soul + memory + tools)
    2. Build system prompt (identity + user context + available tools)
    3. Call LLM -> parse response for tool calls
    4. Execute tools -> feed results back
    5. Iterate until LLM gives final text response
    6. Save to memory -> update soul -> respond

    Delegation happens WITHIN this agent - when Toti decides
    a specialist model would handle something better, it delegates
    through the tool system, not by spawning separate agents.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

        # Core systems
        self.llm = LLMClient(self.config.get("llm", {}))
        self.memory = MemorySystem(config=self.config.get("memory", {}))
        self.soul = SoulEngine()
        self.tools = ToolRegistry(config=self.config.get("tools", {}))

        # Performance settings
        perf = self.config.get("performance", {})
        self.max_tool_calls = perf.get("max_tool_calls_per_turn", 15)
        self.max_tokens_per_turn = perf.get("max_tokens_per_turn", 8000)

        # State
        self._tool_call_count = 0

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
        }
        lines = [f"- **{k}**: {v}" for k, v in descs.items()]
        return "\n".join(lines)

    def process(self, user_message: str, user_id: str = None) -> str:
        """
        Main entry point. Process a user message and return response.
        Synchronous - for Telegram bot.
        """
        self._tool_call_count = 0
        start_time = time.time()

        # 1. Add to working memory
        self.memory.add("user", user_message, importance=0.5)

        # 2. Build messages for LLM
        system_prompt = self._build_system_prompt(user_id)
        context = self.memory.get_context()

        messages = [Message("system", system_prompt)]
        for msg in context:
            messages.append(Message(msg["role"], msg["content"]))
        messages.append(Message("user", user_message))

        # 3. Think-Act loop
        final_response = ""
        for iteration in range(self.max_tool_calls):
            response = self.llm.chat(messages, model_key="default")

            if not response.success:
                final_response = f"Fehler bei der Verarbeitung: {response.error}"
                break

            # Parse response for tool calls
            tool_calls = self._parse_tool_calls(response.content)

            if not tool_calls:
                # No tool calls - final response
                final_response = self._clean_response(response.content)
                break

            # Add assistant response to messages
            messages.append(Message("assistant", response.content))

            # Execute tool calls
            for tool_call in tool_calls:
                tool_name = tool_call.get("tool", "")
                tool_args = {k: v for k, v in tool_call.items() if k != "tool"}

                # Wire special tools to their handlers
                if tool_name == "memory":
                    result = self._handle_memory_tool(tool_args)
                elif tool_name == "delegation":
                    result = self._handle_delegation(tool_args)
                else:
                    result = self.tools.execute(tool_name, **tool_args)

                result_text = str(result)
                messages.append(Message("system", f"Tool '{tool_name}' Ergebnis:\n{result_text}"))
                self._tool_call_count += 1

                if self._tool_call_count >= self.max_tool_calls:
                    final_response = "Maximale Werkzeug-Aufrufe erreicht."
                    break

        if not final_response:
            final_response = "Verstanden."

        # Save response to memory
        self.memory.add("assistant", final_response, importance=0.5)

        # Update user relationship
        if user_id:
            self.soul.update_user(user_id, trust_delta=0.01)

        elapsed = time.time() - start_time
        log.info(f"Processed message in {elapsed:.1f}s, {self._tool_call_count} tool calls")

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
            self.soul.update_user(user_id, trust_delta=0.01)

    # ─── Tool Call Parsing ──────────────────────────────

    def _parse_tool_calls(self, text: str) -> list:
        """Extract tool calls from LLM response using XML-style tags."""
        calls = []
        pattern = re.escape(TOOL_START) + r"(.*?)" + re.escape(TOOL_END)
        for match in re.finditer(pattern, text, re.DOTALL):
            payload = match.group(1).strip()
            try:
                call = json.loads(payload)
                if "tool" in call:
                    calls.append(call)
            except json.JSONDecodeError:
                log.warning(f"Failed to parse tool call: {payload[:100]}")
                continue
        return calls

    def _clean_response(self, text: str) -> str:
        """Remove tool call blocks from final response."""
        pattern = re.escape(TOOL_START) + r".*?" + re.escape(TOOL_END)
        text = re.sub(pattern, "", text, flags=re.DOTALL)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

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

    # ─── Lifecycle ──────────────────────────────────────

    def shutdown(self):
        """Graceful shutdown - save everything."""
        self.memory.end_session()
        self.soul.save()
        log.info(f"NEXUS shutdown. LLM stats: {self.llm.stats()}")

    def stats(self) -> dict:
        """Get overall stats."""
        return {
            "llm": self.llm.stats(),
            "memory": self.memory.stats(),
            "tool_calls_this_turn": self._tool_call_count,
            "soul_relationships": len(self.soul.relationships),
        }
