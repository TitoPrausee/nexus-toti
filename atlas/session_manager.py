#!/usr/bin/env python3
"""
Atlas L2 Session Memory — vergangene Sessions, strukturiert archiviert.
Jede Session wird als git-commitierte .md Datei gespeichert.
Relevanz-basiertes Laden: Nur Sessions mit Topic-Match kommen in den Context.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# GitMemory importieren
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from git_memory import GitMemory


class SessionManager:
    """L2 Session Memory — archiviert und lädt Sessions."""

    def __init__(self, git_memory: GitMemory = None):
        self.mem = git_memory or GitMemory()
        self.sessions_dir = "sessions"

    def archive(self, topic: str, key_facts: list[str],
                decisions: list[str], summary: str,
                duration: str = "unbekannt") -> bool:
        """Archiviert eine Session als git-commitierte Datei."""
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        path = f"{self.sessions_dir}/{timestamp}.md"

        content = f"""# Session: {topic}

**Datum:** {date_str}
**Dauer:** {duration}

## Topics
- {topic}

## Key Facts
"""
        for fact in key_facts:
            content += f"- {fact}\n"

        content += "\n## Decisions\n"
        for decision in decisions:
            content += f"- {decision}\n"

        content += f"""
## Summary
{summary}

---
*Archiviert von Atlas am {datetime.now().isoformat()}*
"""

        return self.mem.save(
            path, content,
            f"session: {topic}"
        )

    def find_relevant(self, query: str, max_results: int = 3) -> list[dict]:
        """Findet relevante Sessions zu einer Query."""
        results = self.mem.search(query, f"{self.sessions_dir}/*.md")

        # Nach Datei gruppieren und Relevanz scoren
        sessions = {}
        for r in results:
            fname = r["file"]
            if fname not in sessions:
                sessions[fname] = {
                    "file": fname,
                    "matches": 0,
                    "content_preview": "",
                }
            sessions[fname]["matches"] += 1
            if not sessions[fname]["content_preview"]:
                sessions[fname]["content_preview"] = r["content"][:200]

        # Nach Match-Häufigkeit sortieren
        sorted_sessions = sorted(
            sessions.values(),
            key=lambda s: s["matches"],
            reverse=True
        )

        return sorted_sessions[:max_results]

    def get_recent(self, count: int = 5) -> list[dict]:
        """Listet die letzten N Sessions."""
        entries = self.mem.log(self.sessions_dir, max_count=count)
        sessions = []
        for e in entries:
            # Datum aus Commit-Nachricht extrahieren
            topic = e["message"].replace("session: ", "", 1)
            sessions.append({
                "hash": e["hash"][:8],
                "date": e["date"],
                "topic": topic,
            })
        return sessions

    def get_context_block(self, query: str = None) -> str:
        """Gibt relevante Session-Kontexte fürs System-Prompt zurück."""
        lines = []

        if query:
            relevant = self.find_relevant(query)
            if relevant:
                lines.append("[SESSION MEMORY — relevante vergangene Sessions]")
                for s in relevant:
                    # Topic aus Datei extrahieren
                    content = self.mem.load(s["file"])
                    topic = "Unbekannt"
                    if content:
                        for line in content.split("\n"):
                            if line.startswith("# Session:"):
                                topic = line.replace("# Session:", "").strip()
                                break
                    lines.append(f"  📋 {topic} ({s['matches']} Treffer)")
                lines.append("")

        # Letzte 3 Sessions
        recent = self.get_recent(3)
        if recent:
            lines.append("[LETZTE SESSIONS]")
            for s in recent:
                lines.append(f"  {s['date'][:10]} {s['topic']}")
            lines.append("")

        return "\n".join(lines)
