#!/usr/bin/env python3
"""
Atlas Migration Engine
Importiert alle Agenten-Memories in Atlas' Git-basiertes Memory.
Dedupliziert per Content-Hash, taggt mit Provenance.
"""
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

# Atlas GitMemory importieren
sys.path.insert(0, os.path.expanduser("~/.atlas"))
from git_memory import GitMemory


class MigrationEngine:
    """Importiert Agenten-Memories in Atlas' Git-Memory."""

    def __init__(self):
        self.mem = GitMemory()
        self.seen_hashes = set()  # Für Deduplizierung
        self.stats = {"imported": 0, "skipped": 0, "errors": 0}

    def scan_sources(self) -> dict:
        """Scannt alle Agenten-Quellen und katalogisiert sie."""
        sources = {
            "hermes": {
                "path": os.path.expanduser("~/.hermes"),
                "files": [
                    "memories/MEMORY.md",
                    "memories/USER.md",
                    "SOUL.md",
                    "config.yaml",
                ]
            },
            "mercury-v2": {
                "path": os.path.expanduser("~/.mercury-v2"),
                "files": [
                    "memories/MEMORY.md",
                    "memories/USER.md",
                    "SOUL.md",
                    "config.yaml",
                ]
            },
            "mercury-v1": {
                "path": os.path.expanduser("~/.mercury"),
                "files": [
                    "memories/MEMORY.md",
                    "memories/USER.md",
                    "SOUL.md",
                ]
            },
            "nova": {
                "path": os.path.expanduser("~/.nova"),
                "files": [
                    "memories/MEMORY.md",
                    "memories/USER.md",
                    "SOUL.md",
                    "config.yaml",
                ]
            },
            "claude": {
                "path": os.path.expanduser("~/.claude/projects/-Users-tito1/memory"),
                "files": [
                    "CONTEXT.md",
                    "DECISIONS.md",
                    "LEARNINGS.md",
                    "SNIPPETS.md",
                    "RULES.md",
                    "SOUL.md",
                ]
            },
        }
        return sources

    def get_content_hash(self, content: str) -> str:
        """Erzeugt SHA-256 Hash für Deduplizierung."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def import_file(self, source_name: str, source_path: str,
                    relative_path: str, content: str) -> bool:
        """Importiert eine Datei mit Provenance-Tag."""
        content_hash = self.get_content_hash(content)

        # Deduplizierung
        if content_hash in self.seen_hashes:
            self.stats["skipped"] += 1
            print(f"  ⏭️  {source_name}/{relative_path} (Duplikat)")
            return False

        self.seen_hashes.add(content_hash)

        # Ziel-Pfad: agents/<source>/<datei>
        target_path = f"agents/{source_name}/{relative_path.replace('/', '-')}"

        # Provenance-Header
        provenance = f"""---
source: {source_name}
original_path: {source_path}/{relative_path}
imported_at: {datetime.now().isoformat()}
content_hash: {content_hash}
---

"""
        # Speichern mit Git-Commit
        success = self.mem.save(
            target_path,
            provenance + content,
            f"import: {source_name}/{relative_path}"
        )

        if success:
            self.stats["imported"] += 1
            print(f"  ✅ {source_name}/{relative_path}")
        else:
            self.stats["errors"] += 1
            print(f"  ❌ {source_name}/{relative_path} (Fehler)")

        return success

    def run(self):
        """Führt die Migration aus."""
        print("=" * 60)
        print("Atlas Migration Engine")
        print("=" * 60)
        print()

        sources = self.scan_sources()

        for source_name, source_info in sources.items():
            base_path = source_info["path"]
            if not os.path.exists(base_path):
                print(f"⚠️  {source_name}: Verzeichnis nicht gefunden ({base_path})")
                continue

            print(f"\n📂 {source_name} ({base_path})")
            for rel_path in source_info["files"]:
                full_path = os.path.join(base_path, rel_path)
                if not os.path.exists(full_path):
                    print(f"  ⚠️  {rel_path} nicht gefunden")
                    continue

                try:
                    with open(full_path, "r", errors="replace") as f:
                        content = f.read()
                    self.import_file(source_name, base_path, rel_path, content)
                except Exception as e:
                    self.stats["errors"] += 1
                    print(f"  ❌ {rel_path}: {e}")

        print()
        print("=" * 60)
        print("Migration abgeschlossen!")
        print(f"  ✅ Importiert: {self.stats['imported']}")
        print(f"  ⏭️  Übersprungen (Duplikat): {self.stats['skipped']}")
        print(f"  ❌ Fehler: {self.stats['errors']}")
        print("=" * 60)


if __name__ == "__main__":
    engine = MigrationEngine()
    engine.run()
