"""
GHOST — Background & Persistence Agent (Toti-derived)
Includes Smart Scheduler integration.
"""

import time
from core.agent_base import AgentBase
from core.llm_client import LLMClient
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.scheduler import SmartScheduler


class GhostAgent(AgentBase):
    AGENT_ID = "GHOST"
    AGENT_NAME = "Ghost Background Agent"
    SYSTEM_PROMPT_FILE = "ghost.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry, **kwargs):
        super().__init__(llm, memory, tools, **kwargs)
        self.scheduler = SmartScheduler()
        self._pattern_count: dict[str, int] = {}

    def register_scheduled_task(self, task_id: str, trigger: str,
                                 fn=None, model_level: int = 0, **kwargs):
        """Register a smart scheduled task."""
        self.scheduler.register(task_id, trigger, fn, model_level, **kwargs)

    async def scheduler_tick(self) -> list[dict]:
        """Run one scheduler tick."""
        return await self.scheduler.tick()

    def check_stuck(self, task_history: list[dict], threshold: int = 3) -> list[dict]:
        """Check if tasks are stuck."""
        alerts = []
        recent = task_history[-threshold * 2:] if len(task_history) > threshold * 2 else task_history
        agent_counts: dict[str, int] = {}
        for entry in recent:
            agent = entry.get("agent", "")
            role = entry.get("role", "")
            if role == "task_start":
                agent_counts[agent] = agent_counts.get(agent, 0) + 1
        for agent, count in agent_counts.items():
            if count >= threshold:
                alerts.append({
                    "type": "STUCK_DETECTION",
                    "agent": agent,
                    "message": f"Agent {agent} hat {count} Task-Starts ohne Completion",
                    "action": "Replan oder Task neu zuweisen",
                })
        return alerts

    def detect_patterns(self, task: str) -> list[dict]:
        """Detect recurring tasks."""
        task_key = task.lower().strip()[:50]
        self._pattern_count[task_key] = self._pattern_count.get(task_key, 0) + 1
        alerts = []
        if self._pattern_count[task_key] >= 3:
            alerts.append({
                "type": "PATTERN_ALERT",
                "message": f"Task '{task_key[:50]}' appeared {self._pattern_count[task_key]} times",
                "action": "SKILL für diesen wiederkehrenden Task erstellen",
            })
        return alerts

    def save_session_state(self):
        """Persist critical state to L3 memory."""
        history = self.memory.session_get_history()
        self.memory.longterm_write(
            f"session_snapshot_{int(time.time())}",
            {
                "history_count": len(history),
                "last_tasks": [h.get("content", "")[:100] for h in history[-5:]],
                "pattern_counts": self._pattern_count,
            },
        )
