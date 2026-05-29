"""
NEXUS-0 Orchestrator Agent
Central coordinator that decomposes tasks, delegates to sub-agents, and synthesizes results.
"""

from typing import Optional
from core.agent_base import AgentBase
from core.llm_client import LLMClient, Message
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.delegation import DelegationEngine, DelegationPlan


class NexusOrchestrator(AgentBase):
    """NEXUS-0 — The Orchestrator. Decomposes, delegates, synthesizes."""

    AGENT_ID = "NEXUS-0"
    AGENT_NAME = "NEXUS Orchestrator"
    SYSTEM_PROMPT_FILE = "orchestrator.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry):
        super().__init__(llm, memory, tools)
        self.delegation = DelegationEngine(llm, memory, tools)
        self._auto_delegate = True  # Automatically delegate complex tasks

    def register_agent(self, agent_id: str, agent_instance: AgentBase):
        """Register a sub-agent for delegation."""
        self.delegation.register_agent(agent_id, agent_instance)

    def process(self, user_input: str) -> str:
        """
        Main entry point: receive user input, decide approach, execute, return result.
        """
        # Check for special commands
        if user_input.startswith("/"):
            return self._handle_command(user_input)

        # Check if this is a simple task (direct response) or complex (delegation)
        complexity = self._assess_complexity(user_input)

        if complexity == "simple":
            # Direct response — no delegation needed
            result = self.execute(task=user_input)
            return result["result"]

        elif complexity == "moderate":
            # Single-agent delegation
            agent_id = self._pick_agent(user_input)
            if agent_id and agent_id in self.delegation._agents:
                agent = self.delegation._agents[agent_id]
                result = agent.execute(
                    task=user_input,
                    context=self.memory.build_context(user_input),
                )
                return result["result"]
            else:
                result = self.execute(task=user_input)
                return result["result"]

        else:
            # Complex — full DAG decomposition
            return self._delegate_complex(user_input)

    def _assess_complexity(self, task: str) -> str:
        """
        Assess task complexity to determine execution strategy.
        Returns: 'simple', 'moderate', or 'complex'
        """
        # Quick heuristic-based assessment
        complex_indicators = [
            "und", "sowie", "danach", "zuerst", "dann",  # German connectors
            "and then", "after that", "first", "also",  # English connectors
            "analyse", "research", "recherch",  # Multi-step tasks
            "baue", "erstelle", "implementier", "develop",  # Building tasks
            "debug", "fix", "reparier",  # Debug tasks
        ]

        task_lower = task.lower()
        indicator_count = sum(1 for ind in complex_indicators if ind in task_lower)

        # Word count heuristic
        word_count = len(task.split())

        if indicator_count >= 3 or word_count > 40:
            return "complex"
        elif indicator_count >= 1 or word_count > 15:
            return "moderate"
        else:
            return "simple"

    def _pick_agent(self, task: str) -> str:
        """Pick the best single agent for a moderate task."""
        task_lower = task.lower()

        # Keyword-based routing
        if any(kw in task_lower for kw in ["recherch", "such", "find", "info", "web", "look up", "search"]):
            return "SCOUT"
        if any(kw in task_lower for kw in ["code", "implementier", "baue", "schreib", "script", "program", "build", "write"]):
            return "FORGE"
        if any(kw in task_lower for kw in ["analyse", "review", "prüf", "bewert", "check", "analyze", "evaluat"]):
            return "LENS"
        if any(kw in task_lower for kw in ["format", "ausgabe", "darstell", "present", "format", "output"]):
            return "HERALD"

        # Default to SCOUT for information gathering
        return "SCOUT"

    def _delegate_complex(self, task: str) -> str:
        """Decompose and delegate a complex task."""
        context = self.memory.build_context(task)

        # Decompose
        plan = self.delegation.decompose_task(task, context)

        # Execute plan
        result = self.delegation.execute_plan(plan)

        # Synthesize if needed
        if isinstance(result, dict) and "result" in result:
            return result["result"]
        elif isinstance(result, dict):
            # Aggregate results from multiple agents
            parts = []
            for task_id, task_result in result.get("results", {}).items():
                if isinstance(task_result, dict) and "result" in task_result:
                    parts.append(f"### {task_result.get('agent', task_id)}\n{task_result['result']}")
            return "\n\n".join(parts) if parts else str(result)

        return str(result)

    def _handle_command(self, command: str) -> str:
        """Handle special NEXUS commands."""
        cmd = command.strip().lower()

        if cmd == "/status":
            agents_status = {}
            for aid, agent in self.delegation._agents.items():
                agents_status[aid] = agent.get_status()
            return f"**NEXUS System Status**\n" \
                   f"Session: {self.memory.session_id}\n" \
                   f"History: {len(self.memory.session_get_history())} entries\n" \
                   f"Skills: {', '.join(self.memory.skill_list()) or 'none'}\n" \
                   f"Long-term: {', '.join(self.memory.longterm_list()) or 'none'}\n" \
                   f"Agents: {len(self.delegation._agents)} registered\n" \
                   f"Tools: {len(self.tools.list_tools())} available"

        elif cmd == "/memory":
            skills = self.memory.skill_list()
            lt = self.memory.longterm_list()
            hist = self.memory.session_get_history(last_n=5)
            return f"**Memory Overview**\n" \
                   f"L1 (Session): {len(self.memory.session_get_history())} entries\n" \
                   f"L2 (Skills): {', '.join(skills) or 'none'}\n" \
                   f"L3 (Long-term): {', '.join(lt) or 'none'}\n" \
                   f"Recent: {len(hist)} last entries shown"

        elif cmd == "/reset":
            self.memory.session_clear()
            self.reset_conversation()
            for agent in self.delegation._agents.values():
                agent.reset_conversation()
            return "Session reset. All conversation history cleared."

        elif cmd.startswith("/evolve"):
            task_name = cmd.replace("/evolve", "").strip()
            return self._gepa_evolve(task_name)

        elif cmd == "/help":
            return (
                "**NEXUS Commands**\n"
                "/status — System status\n"
                "/memory — Memory overview\n"
                "/reset — Reset session\n"
                "/evolve <task> — GEPA self-improvement\n"
                "/help — This help\n\n"
                "Or just type your task and NEXUS will handle it."
            )

        return f"Unknown command: {command}. Type /help for available commands."

    def _gepa_evolve(self, task_name: str) -> str:
        """
        GEPA Self-Improvement Protocol.
        Analyzes what worked, what didn't, and proposes improvements.
        """
        history = self.memory.session_get_history()

        # Build evolution prompt
        evolve_prompt = f"""GEPA SELF-IMPROVEMENT PROTOCOL

Task: {task_name or 'General session review'}

Session History Summary:
{self._summarize_history(history)}

TRACE_ANALYSIS:
  Was hat funktioniert: <analyse>
  Was hat nicht funktioniert: <analyse>
  Warum es nicht funktioniert hat: <root cause>

IMPROVEMENT_PROPOSAL:
  Tool-Beschreibung verbessern? <ja/nein + was>
  Skill-Vorlage verbessern? <ja/nein + was>
  Delegation-Prompt schärfen? <ja/nein + was>

PARETO_CHECK:
  Bringt diese Verbesserung >20% bessere Ergebnisse? <ja/nein>

Sei konkret und ehrlich. Kein Fülltext."""

        messages = [
            Message(role="system", content=self._system_prompt),
            Message(role="user", content=evolve_prompt),
        ]

        response = self.llm.chat(messages)

        # Store improvement suggestion in L3 memory
        self.memory.longterm_write(
            f"gepa_{task_name or 'general'}",
            {
                "analysis": response.content[:2000],
                "timestamp": __import__("time").time(),
            },
        )

        return response.content

    def _summarize_history(self, history: list[dict]) -> str:
        """Summarize session history for GEPA analysis."""
        if not history:
            return "No session history available."

        summary_parts = []
        for entry in history[-20:]:  # Last 20 entries
            agent = entry.get("agent", "?")
            role = entry.get("role", "?")
            content = entry.get("content", "")[:150]
            summary_parts.append(f"[{agent}/{role}] {content}")

        return "\n".join(summary_parts)
