"""
NEXUS 3-Level Memory System — Toti Edition
L1 — Session Memory (volatile, per conversation)
L2 — Skill Memory (persistent, solution patterns)
L3 — Long-Term Memory (persistent, facts/preferences)
Plus: Rolling Summary compression, State-driven memory
"""

import json
import os
import time
from typing import Optional, Any
from pathlib import Path


class MemorySystem:
    """3-Level hierarchical memory with file-based persistence and rolling summary."""

    BASE_DIR = Path(__file__).parent.parent / "memory"

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or f"session_{int(time.time())}"
        self._l1: dict[str, Any] = {}
        self._l1_history: list[dict] = []
        self._rolling_summary: str = ""  # Toti's compressed history
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in ["sessions", "skills", "longterm"]:
            (self.BASE_DIR / d).mkdir(parents=True, exist_ok=True)

    # ─── L1: Session Memory ───

    def session_write(self, key: str, value: Any):
        self._l1[key] = value

    def session_read(self, key: str, default: Any = None) -> Any:
        return self._l1.get(key, default)

    def session_log(self, role: str, content: str, agent: str = "TOTI"):
        entry = {
            "timestamp": time.time(),
            "agent": agent,
            "role": role,
            "content": content,
        }
        self._l1_history.append(entry)

        # Auto-compress rolling summary when history gets long
        if len(self._l1_history) % 10 == 0:
            self._compress_rolling_summary()

    def session_get_history(self, last_n: Optional[int] = None) -> list[dict]:
        if last_n:
            return self._l1_history[-last_n:]
        return self._l1_history

    def session_clear(self):
        self._l1.clear()
        self._l1_history.clear()
        self._rolling_summary = ""

    def session_save(self):
        path = self.BASE_DIR / "sessions" / f"{self.session_id}.json"
        data = {
            "id": self.session_id,
            "memory": self._l1,
            "history": self._l1_history,
            "rolling_summary": self._rolling_summary,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def session_load(self, session_id: str) -> bool:
        path = self.BASE_DIR / "sessions" / f"{session_id}.json"
        if not path.exists():
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.session_id = session_id
        self._l1 = data.get("memory", {})
        self._l1_history = data.get("history", [])
        self._rolling_summary = data.get("rolling_summary", "")
        return True

    # ─── L2: Skill Memory ───

    def skill_write(self, name: str, pattern: str, description: str = ""):
        path = self.BASE_DIR / "skills" / f"{name}.json"
        data = {"name": name, "pattern": pattern, "description": description, "updated": time.time()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def skill_read(self, name: str) -> Optional[dict]:
        path = self.BASE_DIR / "skills" / f"{name}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def skill_list(self) -> list[str]:
        skill_dir = self.BASE_DIR / "skills"
        return [p.stem for p in skill_dir.glob("*.json")]

    # ─── L3: Long-Term Memory ───

    def longterm_write(self, key: str, value: Any):
        path = self.BASE_DIR / "longterm" / f"{key}.json"
        data = {"key": key, "value": value, "updated": time.time()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def longterm_read(self, key: str, default: Any = None) -> Any:
        path = self.BASE_DIR / "longterm" / f"{key}.json"
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("value", default)

    def longterm_list(self) -> list[str]:
        lt_dir = self.BASE_DIR / "longterm"
        return [p.stem for p in lt_dir.glob("*.json")]

    # ─── Rolling Summary ───

    def _compress_rolling_summary(self):
        """
        Compress history into a rolling summary.
        Keeps the summary under 300 chars — runs locally (no model call).
        """
        if not self._l1_history:
            return

        # Simple local compression: extract key points from recent history
        recent = self._l1_history[-20:]
        key_points = []
        for entry in recent:
            agent = entry.get("agent", "?")
            role = entry.get("role", "?")
            content = entry.get("content", "")[:80]
            if role == "task_start":
                key_points.append(f"{agent} startete: {content}")
            elif role == "task_complete":
                key_points.append(f"{agent} fertig: {content}")

        # Keep rolling summary under 300 chars
        new_summary = " | ".join(key_points[-5:])
        if len(new_summary) > 300:
            new_summary = new_summary[-300:]
        self._rolling_summary = new_summary

    def get_rolling_summary(self) -> str:
        return self._rolling_summary

    # ─── Memory Context Builder ───

    def build_context(self, task: str) -> str:
        parts = []

        if self._rolling_summary:
            parts.append(f"[HISTORY SUMMARY: {self._rolling_summary}]")

        if self._l1_history:
            recent = self._l1_history[-3:]
            parts.append("[RECENT]")
            for entry in recent:
                parts.append(f"  {entry['agent']} ({entry['role']}): {entry['content'][:150]}")

        skills = self.skill_list()
        if skills:
            parts.append(f"[SKILLS: {', '.join(skills)}]")

        lt_keys = self.longterm_list()
        if lt_keys:
            for key in lt_keys[:5]:
                val = self.longterm_read(key)
                if val:
                    parts.append(f"MEMORY:{key} = {str(val)[:200]}")

        if self._l1:
            parts.append("[SESSION STATE]")
            for k, v in self._l1.items():
                parts.append(f"  {k} = {str(v)[:200]}")

        return "\n".join(parts)

    # ─── Checkpoints ───

    def save_checkpoint(self, task_id: str, step: str, state: dict):
        cp_dir = Path(__file__).parent.parent / "data" / "checkpoints"
        cp_dir.mkdir(parents=True, exist_ok=True)
        path = cp_dir / f"{task_id}_{step}.json"
        data = {"task_id": task_id, "step": step, "state": state, "timestamp": time.time()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_checkpoint(self, task_id: str, step: str) -> Optional[dict]:
        cp_dir = Path(__file__).parent.parent / "data" / "checkpoints"
        path = cp_dir / f"{task_id}_{step}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
