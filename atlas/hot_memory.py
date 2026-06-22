#!/usr/bin/env python3
"""
Atlas L0 Hot Memory — immer im Context (~800 Tokens).
Kritische Fakten die immer verfügbar sein müssen.
Auto-Promotion aus L3 basierend auf Zugriffsfrequenz + Wichtigkeit.
Nie komprimiert — nur demoted wenn veraltet.
"""
import os
import time
from datetime import datetime
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None


class HotMemory:
    """L0 Hot Memory — immer im Context, nie komprimiert."""

    def __init__(self, path: str = None):
        self.path = path or os.path.expanduser("~/.atlas/memory/hot.yaml")
        self.max_tokens = 800
        self._data = self._load()

    def _load(self) -> dict:
        """Lädt Hot Memory aus YAML."""
        if not os.path.exists(self.path):
            return self._defaults()
        try:
            with open(self.path) as f:
                if yaml:
                    return yaml.safe_load(f) or self._defaults()
                return self._defaults()
        except Exception:
            return self._defaults()

    def _defaults(self) -> dict:
        return {
            "user": {"name": "tito", "communication": "Deutsch, direkt"},
            "active_projects": [],
            "infrastructure": {},
            "rules": [],
            "git_identity": {"name": "Atlas", "email": "atlas@local"},
            "_meta": {"version": 1, "updated_at": datetime.now().isoformat()},
        }

    def _save(self):
        """Speichert Hot Memory zurück."""
        self._data["_meta"]["updated_at"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            if yaml:
                yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)
            else:
                f.write(str(self._data))

    def get_context_block(self) -> str:
        """Gibt den Hot Memory Block fürs System-Prompt zurück (~800 Tokens)."""
        lines = ["[HOT MEMORY — immer verfügbar]", ""]

        # User
        u = self._data.get("user", {})
        lines.append(f"User: {u.get('name', 'tito')}")
        lines.append(f"Kommunikation: {u.get('communication', 'Deutsch')}")
        lines.append("")

        # Aktive Projekte (max 5)
        lines.append("Aktive Projekte:")
        for p in self._data.get("active_projects", [])[:5]:
            name = p.get("name", "?")
            tech = p.get("tech", "")
            priority = p.get("priority", 99)
            lines.append(f"  #{priority} {name} ({tech})")
        lines.append("")

        # Infrastruktur
        infra = self._data.get("infrastructure", {})
        if infra:
            lines.append("Infrastruktur:")
            for k, v in infra.items():
                lines.append(f"  {k}: {v}")
            lines.append("")

        # Regeln (max 5)
        rules = self._data.get("rules", [])[:5]
        if rules:
            lines.append("Regeln:")
            for r in rules:
                lines.append(f"  • {r}")
            lines.append("")

        return "\n".join(lines)

    def promote(self, key: str, value: dict):
        """Promoted einen Fakt aus L3 ins Hot Memory."""
        if key == "active_projects":
            # Projekt hinzufügen oder Priorität aktualisieren
            existing = [p for p in self._data.get("active_projects", [])
                       if p.get("name") == value.get("name")]
            if existing:
                existing[0].update(value)
            else:
                self._data.setdefault("active_projects", []).append(value)
        else:
            self._data[key] = value
        self._save()

    def demote(self, key: str, subkey: str = None):
        """Demoted einen Fakt aus dem Hot Memory (zurück zu L3)."""
        if subkey and key in self._data:
            if isinstance(self._data[key], list):
                self._data[key] = [p for p in self._data[key]
                                   if p.get("name") != subkey]
            elif isinstance(self._data[key], dict):
                self._data[key].pop(subkey, None)
        elif key in self._data:
            del self._data[key]
        self._save()

    def update(self, key: str, value: any):
        """Aktualisiert einen beliebigen Hot Memory Eintrag."""
        self._data[key] = value
        self._save()

    def get(self, key: str, default=None):
        """Liest einen Hot Memory Eintrag."""
        return self._data.get(key, default)

    def estimate_tokens(self, text: str) -> int:
        """Grober Token-Count (ca. 4 Zeichen pro Token)."""
        return len(text) // 4
