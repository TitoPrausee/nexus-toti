"""
NEXUS v8.2 — Project Tracker
Tracks active projects, their status, and injects project context into conversations.
Inspired by Mercury's MEMORY.md system — always know what's happening.

Projects are loaded from data/projects.json and kept in sync with
the soul's knowledge section. When Toti learns about a new project
or a status change, it updates the tracker automatically.

Usage:
    tracker = ProjectTracker(config)
    tracker.load()
    context = tracker.get_context_for_message("wie läuft block_sync?")
    tracker.update_project("block_sync", status="active", note="Sprint 2 gestartet")
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

log = logging.getLogger("nexus.projects")


@dataclass
class Project:
    """A tracked project with status and metadata."""
    name: str
    status: str = "active"  # active, paused, completed, planned
    priority: int = 5  # 1=lowest, 10=highest
    description: str = ""
    tech_stack: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)
    last_updated: str = ""
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ProjectTracker:
    """
    Track active projects and provide context for conversations.
    Like Mercury's MEMORY.md but dynamic and queryable.
    """

    # Default projects — Nexus learns projects through conversations, not hardcoded defaults
    DEFAULT_PROJECTS = {
        "nexus": {
            "name": "nexus",
            "status": "active",
            "priority": 10,
            "description": "Nexus — autonomer KI-Agent mit Seele und 6-Agenten-Team",
            "tech_stack": ["Python", "Ollama Cloud", "Telegram Bot API", "Docker"],
            "next_steps": ["Skills integrieren", "DSGVO-Modul testen", "Pair Router optimieren"],
            "notes": ["GitHub: github.com/***REMOVED***/nexus-toti (privat)"],
        },
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.data_dir = Path(self.config.get("data_dir", "data"))
        self.projects_file = self.data_dir / "projects.json"
        self.projects: dict[str, Project] = {}
        self._load()

    def _load(self):
        """Load projects from file, falling back to defaults."""
        if self.projects_file.exists():
            try:
                data = json.loads(self.projects_file.read_text(encoding="utf-8"))
                for name, pdata in data.items():
                    self.projects[name] = Project.from_dict(pdata)
                log.info(f"[PROJECTS] Loaded {len(self.projects)} projects from {self.projects_file}")
                return
            except Exception as e:
                log.error(f"[PROJECTS] Failed to load: {e}")

        # Fall back to defaults
        for name, pdata in self.DEFAULT_PROJECTS.items():
            self.projects[name] = Project.from_dict(pdata)
        self._save()
        log.info(f"[PROJECTS] Initialized {len(self.projects)} default projects")

    def _save(self):
        """Save projects to file."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            data = {name: p.to_dict() for name, p in self.projects.items()}
            self.projects_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.error(f"[PROJECTS] Failed to save: {e}")

    def get_project(self, name: str) -> Optional[Project]:
        """Get a project by name (case-insensitive partial match)."""
        name_lower = name.lower().replace("-", "_")
        for pname, project in self.projects.items():
            if name_lower in pname.lower().replace("-", "_"):
                return project
        return None

    def update_project(self, name: str, **kwargs) -> Project:
        """Update a project's fields. Creates project if it doesn't exist."""
        name_key = name.lower().replace("-", "_").replace(" ", "_")
        if name_key in self.projects:
            project = self.projects[name_key]
            for k, v in kwargs.items():
                if hasattr(project, k):
                    setattr(project, k, v)
            project.last_updated = datetime.now().isoformat()
        else:
            kwargs["name"] = name_key
            kwargs.setdefault("last_updated", datetime.now().isoformat())
            project = Project.from_dict(kwargs)
            self.projects[name_key] = project

        self._save()
        return project

    def get_active_projects(self) -> list[Project]:
        """Get all active projects sorted by priority."""
        return sorted(
            [p for p in self.projects.values() if p.status == "active"],
            key=lambda p: p.priority,
            reverse=True,
        )

    def get_context_for_message(self, message: str) -> str:
        """Generate project context to inject into conversation.

        Detects project mentions in the message and returns
        relevant project info for the LLM context.
        """
        message_lower = message.lower()
        relevant = []

        for name, project in self.projects.items():
            # Check various forms of the project name
            name_variants = [
                name,
                name.replace("_", " "),
                name.replace("_", "-"),
            ]
            # Also check description keywords
            desc_words = project.description.lower().split()

            if any(v in message_lower for v in name_variants) or \
               any(w in message_lower for w in desc_words[:3]):
                relevant.append(project)

        if not relevant:
            # Return summary of all active projects for general queries
            active = self.get_active_projects()
            if active:
                lines = ["Aktive Projekte:"]
                for p in active[:5]:  # Top 5 by priority
                    lines.append(f"  • {p.name} ({p.status}, P{p.priority}): {p.description}")
                    if p.next_steps:
                        lines.append(f"    Next: {p.next_steps[0]}")
                return "\n".join(lines)
            return ""

        # Return detailed info for matched projects
        lines = []
        for p in relevant:
            lines.append(f" Projekt: {p.name}")
            lines.append(f" Status: {p.status}, Priorität: {p.priority}")
            lines.append(f" Beschreibung: {p.description}")
            if p.tech_stack:
                lines.append(f" Tech: {', '.join(p.tech_stack)}")
            if p.next_steps:
                lines.append(f" Nächste Schritte: {p.next_steps[0]}")
            if p.notes:
                lines.append(f" Notizen: {p.notes[0]}")
        return "\n".join(lines)

    def get_status_summary(self) -> str:
        """Get a concise status summary for heartbeat messages."""
        active = [p for p in self.projects.values() if p.status == "active"]
        paused = [p for p in self.projects.values() if p.status == "paused"]
        return f"{len(active)} aktiv, {len(paused)} pausiert"

    def list_all(self) -> list[dict]:
        """List all projects as dicts."""
        return [p.to_dict() for p in sorted(self.projects.values(), key=lambda p: p.priority, reverse=True)]