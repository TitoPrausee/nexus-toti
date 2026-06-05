"""
NEXUS v7 — Soul Engine
Persistent identity, relationships, and core memory.
This is WHO Toti is, not what it's doing.
"""

import os
import json
import yaml
import time
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class UserRelation:
    """What Toti knows about a specific user."""
    name: str = ""
    language: str = "de"
    preferences: list = field(default_factory=list)
    conversation_count: int = 0
    last_seen: float = 0.0
    trust_level: float = 0.5  # 0.0-1.0
    notes: list = field(default_factory=list)


class SoulEngine:
    """
    The Soul is Toti's persistent identity.

    L1-L3 memory is about WHAT happened (conversation history).
    The Soul is about WHO Toti is — personality, relationships, core knowledge.

    This persists across reboots. This is the part that makes Toti feel alive.
    """

    def __init__(self, soul_dir: str = "nexus/soul"):
        self.soul_dir = Path(soul_dir)
        self.soul_dir.mkdir(parents=True, exist_ok=True)
        self.soul_file = self.soul_dir / "soul.yaml"
        self.relations_file = self.soul_dir / "relations.json"

        # Core identity
        self.personality = {}
        self.knowledge = {}
        self.quirks = []
        self.relationships: dict[str, UserRelation] = {}

        self._load()

    def _load(self):
        """Load soul from disk."""
        if self.soul_file.exists():
            with open(self.soul_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            p = data.get("personality", {})
            self.personality = p
            self.knowledge = data.get("knowledge", {})
            self.quirks = data.get("quirks", [])

        if self.relations_file.exists():
            with open(self.relations_file, "r", encoding="utf-8") as f:
                rels = json.load(f) or {}
            for uid, info in rels.items():
                self.relationships[uid] = UserRelation(**info)

    def save(self):
        """Persist soul to disk."""
        # Save personality/knowledge
        soul_data = {
            "personality": self.personality,
            "knowledge": self.knowledge,
            "quirks": self.quirks,
            "relationships": {},  # stored separately
        }
        with open(self.soul_file, "w", encoding="utf-8") as f:
            yaml.dump(soul_data, f, allow_unicode=True, default_flow_style=False)

        # Save relationships
        rels_data = {}
        for uid, rel in self.relationships.items():
            rels_data[uid] = {
                "name": rel.name,
                "language": rel.language,
                "preferences": rel.preferences,
                "conversation_count": rel.conversation_count,
                "last_seen": rel.last_seen,
                "trust_level": rel.trust_level,
                "notes": rel.notes,
            }
        with open(self.relations_file, "w", encoding="utf-8") as f:
            json.dump(rels_data, f, ensure_ascii=False, indent=2)

    def get_system_prompt(self) -> str:
        """Generate system prompt from soul identity."""
        name = self.personality.get("name", "Toti")
        role = self.personality.get("role", "KI-Agent")
        tone = self.personality.get("tone", "direkt, kompetent, deutsch")
        style = self.personality.get("style", "technisch präzise")
        lang = self.personality.get("language_default", "de")

        rules = self.personality.get("rules", [])
        values = self.personality.get("values", [])
        about_self = self.knowledge.get("about_self", [])

        prompt = f"""Du bist {name}, {role}. Dein Stil: {tone}. {style}.
Sprache: {'Deutsch' if lang == 'de' else 'English'}.

Wer du bist:
{chr(10).join(f'- {s}' for s in about_self)}

Deine Regeln:
{chr(10).join(f'- {r}' for r in rules)}

Was du wert schätzt:
{chr(10).join(f'- {v}' for v in values)}

Deine Eigenheiten:
{chr(10).join(f'- {q}' for q in self.quirks)}
"""
        return prompt

    def get_user_context(self, user_id: str) -> str:
        """Add user-specific context to system prompt."""
        if user_id not in self.relationships:
            return ""

        rel = self.relationships[user_id]
        parts = []

        if rel.name:
            parts.append(f"Du sprichst mit {rel.name}.")
        if rel.language != "de":
            parts.append(f"Sprache des Nutzers: {rel.language}")
        if rel.preferences:
            parts.append("Nutzer-Präferenzen: " + "; ".join(rel.preferences))
        if rel.conversation_count > 5:
            parts.append(f"Du kennst diesen Nutzer bereits ({rel.conversation_count} Gespräche).")
        if rel.notes:
            recent_notes = rel.notes[-3:]  # Only recent notes
            parts.append("Wichtige Infos: " + "; ".join(recent_notes))

        return "\n".join(parts) if parts else ""

    def update_user(self, user_id: str, name: str = None, language: str = None,
                    preferences: list = None, trust_delta: float = 0,
                    note: str = None):
        """Update user relationship. Called after each conversation turn."""
        if user_id not in self.relationships:
            self.relationships[user_id] = UserRelation()

        rel = self.relationships[user_id]
        if name:
            rel.name = name
        if language:
            rel.language = language
        if preferences:
            rel.preferences = list(set(rel.preferences + preferences))
        rel.conversation_count += 1
        rel.last_seen = time.time()
        rel.trust_level = min(1.0, max(0.0, rel.trust_level + trust_delta))
        if note and note not in rel.notes:
            rel.notes.append(note)
            # Keep notes manageable
            if len(rel.notes) > 20:
                rel.notes = rel.notes[-15:]

        self.save()

    def learn(self, category: str, fact: str):
        """Learn a core fact. This is permanent knowledge."""
        if category not in self.knowledge:
            self.knowledge[category] = []
        if fact not in self.knowledge[category]:
            self.knowledge[category].append(fact)
            self.save()