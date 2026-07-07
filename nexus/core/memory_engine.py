"""
Nexus Memory Engine — Atlas Git-basiertes Memory (5 Layer).
Nie komprimieren — immer versionieren.

L0: Hot Memory — immer im Context
L1: Working Memory — aktuelle Konversation (nie komprimiert)
L2: Session Memory — archivierte Sessions
L3: Long-term Memory — git-versionierte Fakten
L4: Git Archive — unendlich, versioniert
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "atlas"))
from git_memory import GitMemory
from hot_memory import HotMemory
from session_manager import SessionManager
from context_loader import ContextLoader
from memory_orchestrator import MemoryOrchestrator


class NexusMemory:
    """Nexus Memory — Atlas' 5-Layer Git Memory System."""

    def __init__(self, data_dir: str = "/opt/data"):
        self.data_dir = data_dir
        self.orch = MemoryOrchestrator()
        self.git = self.orch.mem
        self.hot = self.orch.hot
        self.sessions = self.orch.sessions
        self.context = self.orch.context

    def load_context(self, query: str = "") -> str:
        return self.orch.load_context(query)

    def save_fact(self, domain: str, name: str, content: str) -> bool:
        return self.orch.save_fact(domain, name, content)

    def search(self, keyword: str) -> list:
        return self.orch.search(keyword)

    def archive_session(self, topic: str, facts: list, decisions: list, summary: str) -> bool:
        return self.orch.archive_session(topic, facts, decisions, summary)

    def promote_project(self, name: str, tech: str, priority: int):
        self.orch.promote_project(name, tech, priority)

    def status(self) -> dict:
        return self.orch.status()

    def rollback(self, path: str, hash: str) -> bool:
        return self.orch.rollback(path, hash)

    def diff(self, path: str, h1: str = "HEAD~1", h2: str = "HEAD") -> str:
        return self.orch.diff(path, h1, h2)
