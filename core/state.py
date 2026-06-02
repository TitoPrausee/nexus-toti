"""
NEXUS State Manager — Toti's persistent state between sessions.
Handles save/load, rolling summary, and state compression.
"""

import json
import time
from typing import Optional, Any
from pathlib import Path


STATE_DIR = Path(__file__).parent.parent / "data" / "state"
DEFAULT_STATE = {
    "session_id": "",
    "agent": "toti",
    "personality_active": True,
    "current_task": {
        "id": "",
        "goal": "",
        "step": 0,
        "max_steps": 10,
        "status": "idle",
    },
    "memory": {
        "last_output_summary": "",
        "history_summary": "",
        "user_context": "",
    },
    "system": {
        "budget_used_pct": 0,
        "llm_calls": 0,
        "total_tokens": 0,
        "active_tasks": 0,
        "scheduler_tasks_pending": 0,
    },
    "flags": [],
    "scheduled_tasks": [],
}


class StateManager:
    """Manages Toti's persistent state — survives session resets."""

    def __init__(self, state_path: Optional[str] = None):
        self.state_path = Path(state_path) if state_path else STATE_DIR / "toti_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict = self._load()

    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # Merge with defaults (adds new fields)
                merged = {**DEFAULT_STATE, **saved}
                return merged
            except Exception:
                return dict(DEFAULT_STATE)
        return dict(DEFAULT_STATE)

    def save(self):
        """Save state to disk — called after every significant step."""
        self.state["memory"]["history_summary"] = self.state["memory"].get("history_summary", "")[:300]
        self.state["memory"]["last_output_summary"] = self.state["memory"].get("last_output_summary", "")[:200]
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get nested state value via dot-path: 'current_task.goal'"""
        keys = key_path.split(".")
        obj = self.state
        for k in keys:
            if isinstance(obj, dict) and k in obj:
                obj = obj[k]
            else:
                return default
        return obj

    def set(self, key_path: str, value: Any):
        """Set nested state value via dot-path."""
        keys = key_path.split(".")
        obj = self.state
        for k in keys[:-1]:
            if k not in obj or not isinstance(obj[k], dict):
                obj[k] = {}
            obj = obj[k]
        obj[keys[-1]] = value

    def update_task(self, task_id: str = "", goal: str = "", step: int = None,
                    max_steps: int = None, status: str = None):
        """Update current task state."""
        if task_id:
            self.state["current_task"]["id"] = task_id
        if goal:
            self.state["current_task"]["goal"] = goal
        if step is not None:
            self.state["current_task"]["step"] = step
        if max_steps is not None:
            self.state["current_task"]["max_steps"] = max_steps
        if status:
            self.state["current_task"]["status"] = status
        self.save()

    def update_system(self, **kwargs):
        """Update system metrics."""
        for k, v in kwargs.items():
            if k in self.state["system"]:
                self.state["system"][k] = v
        self.save()

    def add_flag(self, flag: str):
        if flag not in self.state["flags"]:
            self.state["flags"].append(flag)
            self.save()

    def clear_flags(self):
        self.state["flags"] = []
        self.save()

    def compress_memory(self):
        """Compress memory summaries — keep under limits."""
        mem = self.state["memory"]
        if len(mem.get("history_summary", "")) > 300:
            mem["history_summary"] = mem["history_summary"][-300:]
        if len(mem.get("last_output_summary", "")) > 200:
            mem["last_output_summary"] = mem["last_output_summary"][-200:]
        self.save()

    def get_state_json(self) -> str:
        """Get state as JSON string for injection into Toti's prompt."""
        return json.dumps(self.state, ensure_ascii=False, indent=2)

    def reset(self):
        """Full state reset."""
        self.state = dict(DEFAULT_STATE)
        self.save()
