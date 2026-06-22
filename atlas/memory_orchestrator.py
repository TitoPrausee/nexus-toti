#!/usr/bin/env python3
"""
Atlas Memory Orchestrator — Ties L0-L4 together.
Keine Kompression. Immer versionieren. Relevanz-basiertes Laden.

L0: Hot Memory — immer im Context
L1: Working Memory — aktuelle Konversation (nie komprimiert)
L2: Session Memory — archivierte Sessions
L3: Long-term Memory — git-versionierte Fakten
L4: Git Archive — unendlich, versioniert
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from git_memory import GitMemory
from hot_memory import HotMemory
from session_manager import SessionManager
from context_loader import ContextLoader


class MemoryOrchestrator:
    """Zentrale Memory-Steuerung — alle 5 Layer."""

    def __init__(self):
        self.mem = GitMemory()
        self.hot = HotMemory()
        self.sessions = SessionManager(self.mem)
        self.context = ContextLoader()

    # ─── L4: Git Archive ─────────────────────────────────────

    def save_fact(self, domain: str, name: str, content: str) -> bool:
        """Speichert einen Fakt in L3/L4."""
        return self.mem.save_fact(domain, name, content)

    def search(self, keyword: str) -> list[dict]:
        """Durchsucht L4 (komplettes Git-Archiv)."""
        return self.mem.search(keyword)

    def log(self, path: str = None, count: int = 20) -> list[dict]:
        """Zeigt L4 Git-Log."""
        return self.mem.log(path, count)

    def diff(self, path: str, h1: str = "HEAD~1", h2: str = "HEAD") -> str:
        """Zeigt L4 Diff."""
        return self.mem.diff(path, h1, h2)

    def rollback(self, path: str, hash: str) -> bool:
        """Rollback in L4."""
        return self.mem.rollback(path, hash)

    # ─── L3: Long-term Memory ─────────────────────────────────

    def load_fact(self, domain: str, name: str) -> str:
        """Lädt einen Fakt aus L3."""
        return self.mem.load_fact(domain, name)

    def list_domain(self, domain: str) -> list[str]:
        """Listet alle Fakten in einer L3-Domain."""
        return self.mem.list_domain(domain)

    # ─── L2: Session Memory ───────────────────────────────────

    def archive_session(self, topic: str, key_facts: list[str],
                        decisions: list[str], summary: str) -> bool:
        """Archiviert eine Session in L2."""
        return self.sessions.archive(topic, key_facts, decisions, summary)

    def find_sessions(self, query: str) -> list[dict]:
        """Findet Sessions in L2."""
        return self.sessions.find_relevant(query)

    # ─── L0: Hot Memory ───────────────────────────────────────

    def promote_project(self, name: str, tech: str, priority: int):
        """Promoted ein Projekt in L0."""
        self.hot.promote("active_projects", {
            "name": name, "tech": tech, "priority": priority
        })

    def demote_project(self, name: str):
        """Demoted ein Projekt aus L0 zurück zu L3."""
        self.hot.demote("active_projects", name)

    def get_hot_context(self) -> str:
        """Gibt L0 Context Block."""
        return self.hot.get_context_block()

    # ─── Context Loading (statt Kompression) ──────────────────

    def load_context(self, query: str = "") -> str:
        """Lädt relevanten Kontext aus L0+L2+L3 — keine Kompression."""
        return self.context.load_for_query(query)

    def get_memory_index(self) -> str:
        """Lädt MEMORY.md Index."""
        return self.context.load_memory_index()

    # ─── Status ──────────────────────────────────────────────

    def status(self) -> dict:
        """Zeigt Status aller Memory-Layer."""
        git_status = self.mem.status()
        hot = self.hot.get("active_projects", [])
        sessions = self.sessions.get_recent(3)

        return {
            "L0_hot": {
                "projects": len(hot),
                "entries": list(hot),
            },
            "L2_sessions": {
                "recent": sessions,
            },
            "L3_longterm": {
                "files": git_status["file_count"],
            },
            "L4_git": {
                "branch": git_status["branch"],
                "last_commit": git_status["last_commit"],
                "dirty": git_status["dirty"],
            },
        }


def main():
    """CLI für Memory-Operationen."""
    import argparse
    parser = argparse.ArgumentParser(description="Atlas Memory Orchestrator")
    parser.add_argument("command", choices=[
        "status", "search", "log", "diff", "context",
        "archive", "promote", "demote", "hot"
    ])
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()

    orch = MemoryOrchestrator()

    if args.command == "status":
        s = orch.status()
        print("=== Atlas Memory Status ===")
        print(f"\nL0 Hot Memory: {s['L0_hot']['projects']} Projekte")
        for p in s['L0_hot']['entries']:
            print(f"  #{p.get('priority')} {p.get('name')} ({p.get('tech')})")
        print(f"\nL2 Sessions: {len(s['L2_sessions']['recent'])} recent")
        for ses in s['L2_sessions']['recent']:
            print(f"  {ses['date'][:10]} {ses['topic']}")
        print(f"\nL3 Long-term: {s['L3_longterm']['files']} Dateien")
        print(f"\nL4 Git: {s['L4_git']['branch']}")
        print(f"  Letzter Commit: {s['L4_git']['last_commit']}")

    elif args.command == "search":
        results = orch.search(" ".join(args.args))
        for r in results:
            print(f"{r['file']}:{r['line']}: {r['content']}")

    elif args.command == "log":
        entries = orch.log(count=10)
        for e in entries:
            print(f"{e['hash'][:8]} {e['date']} {e['message']}")

    elif args.command == "context":
        query = " ".join(args.args) if args.args else ""
        print(orch.load_context(query))

    elif args.command == "archive":
        topic = args.args[0] if args.args else "Unbenannt"
        orch.archive_session(topic, [], [], "Manuell archiviert")
        print(f"Session '{topic}' archiviert")

    elif args.command == "promote":
        name = args.args[0] if args.args else "?"
        tech = args.args[1] if len(args.args) > 1 else ""
        prio = int(args.args[2]) if len(args.args) > 2 else 5
        orch.promote_project(name, tech, prio)
        print(f"Projekt '{name}' in L0 promoted")

    elif args.command == "hot":
        print(orch.get_hot_context())


if __name__ == "__main__":
    main()
