#!/usr/bin/env python3
"""
Atlas Skill Consolidator
Merged alle Skills aus Hermes, Nova, Nexus und Claude.
Dedupliziert per (Kategorie, Skill-Name, Content-Hash).
Taggt mit Source-Provenance.
"""
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/.atlas"))
from git_memory import GitMemory


class SkillConsolidator:
    """Konsolidiert Skills aus allen Agenten-Quellen."""

    def __init__(self):
        self.mem = GitMemory()
        self.skills_dir = os.path.expanduser("~/.atlas/skills")
        self.seen = {}  # (category, name, hash) -> source
        self.stats = {"imported": 0, "skipped": 0, "conflicts": 0, "errors": 0}

    def scan_skills(self) -> list[dict]:
        """Scannt alle Skill-Quellen und sammelt Metadaten."""
        sources = [
            ("hermes", os.path.expanduser("~/.hermes/skills")),
            ("nova", os.path.expanduser("~/.nova/skills")),
            ("nova-custom", os.path.expanduser("~/.nova/home/nova-skills")),
            ("nexus", os.path.expanduser("/Users/tito1/nexus-toti/data/skills")),
        ]

        all_skills = []
        for source_name, base_path in sources:
            if not os.path.exists(base_path):
                print(f"  ⚠️  {source_name}: nicht gefunden ({base_path})")
                continue

            for category in sorted(os.listdir(base_path)):
                cat_path = os.path.join(base_path, category)
                if not os.path.isdir(cat_path) or category.startswith("."):
                    continue
                if category in ("README.md", "SKILLS.md"):
                    continue

                for skill_name in sorted(os.listdir(cat_path)):
                    skill_path = os.path.join(cat_path, skill_name)
                    if not os.path.isdir(skill_path):
                        continue

                    skill_file = os.path.join(skill_path, "SKILL.md")
                    if not os.path.exists(skill_file):
                        continue

                    try:
                        with open(skill_file, "r", errors="replace") as f:
                            content = f.read()
                        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                        all_skills.append({
                            "source": source_name,
                            "category": category,
                            "name": skill_name,
                            "content": content,
                            "hash": content_hash,
                            "path": skill_file,
                        })
                    except Exception as e:
                        print(f"  ⚠️  Fehler beim Lesen von {skill_file}: {e}")

        return all_skills

    def consolidate(self, all_skills: list[dict]):
        """Konsolidiert alle Skills, dedupliziert und schreibt sie."""
        # Gruppieren nach (category, name)
        groups = {}
        for skill in all_skills:
            key = (skill["category"], skill["name"])
            if key not in groups:
                groups[key] = []
            groups[key].append(skill)

        print(f"\n📊 Gefunden: {len(all_skills)} Skills in {len(groups)} Gruppen\n")

        for (category, name), versions in sorted(groups.items()):
            # Deduplizieren nach Content-Hash
            unique = {}
            for v in versions:
                h = v["hash"]
                if h not in unique:
                    unique[h] = []
                unique[h].append(v["source"])

            target_dir = os.path.join(self.skills_dir, category, name)
            target_file = os.path.join(target_dir, "SKILL.md")

            if len(unique) == 1:
                # Kein Konflikt — einfach kopieren
                content_hash = list(unique.keys())[0]
                sources = unique[content_hash]
                original = next(v for v in versions if v["hash"] == content_hash)

                # Prüfen ob schon identisch existiert
                if os.path.exists(target_file):
                    with open(target_file) as f:
                        existing = f.read()
                    if existing == original["content"]:
                        self.stats["skipped"] += 1
                        continue

                os.makedirs(target_dir, exist_ok=True)
                with open(target_file, "w") as f:
                    f.write(original["content"])
                self.stats["imported"] += 1
                print(f"  ✅ {category}/{name} (von {', '.join(sources)})")

            else:
                # Konflikt — mehrere Versionen
                self.stats["conflicts"] += 1
                os.makedirs(target_dir, exist_ok=True)

                # Primäre Version (von hermes bevorzugen, dann nova, dann nexus)
                priority = {"hermes": 0, "nova": 1, "nova-custom": 2, "nexus": 3}
                sorted_versions = sorted(versions, key=lambda v: priority.get(v["source"], 99))

                # Alle Versionen speichern
                for i, v in enumerate(sorted_versions):
                    version_file = os.path.join(
                        target_dir, f"SKILL-{v['source']}.md"
                    )
                    with open(version_file, "w") as f:
                        f.write(v["content"])

                    if i == 0:
                        # Erste = primäre = SKILL.md
                        shutil.copy2(version_file, target_file)

                print(f"  🔀 {category}/{name} ({len(unique)} Versionen: {', '.join(unique.keys())})")

        # Claude Skills kopieren
        claude_skills_dir = os.path.expanduser("~/.claude/skills")
        if os.path.exists(claude_skills_dir):
            for fname in os.listdir(claude_skills_dir):
                if fname.endswith(".md"):
                    src = os.path.join(claude_skills_dir, fname)
                    dst = os.path.join(self.skills_dir, "claude", fname)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    self.stats["imported"] += 1
                    print(f"  ✅ claude/{fname}")

        claude_commands_dir = os.path.expanduser("~/.claude/commands")
        if os.path.exists(claude_commands_dir):
            for fname in os.listdir(claude_commands_dir):
                if fname.endswith(".md"):
                    src = os.path.join(claude_commands_dir, fname)
                    dst = os.path.join(self.skills_dir, "commands", fname)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    self.stats["imported"] += 1
                    print(f"  ✅ commands/{fname}")

    def write_index(self):
        """Schreibt den Skill-Index."""
        index_path = os.path.join(self.skills_dir, "index.md")
        categories = sorted([
            d for d in os.listdir(self.skills_dir)
            if os.path.isdir(os.path.join(self.skills_dir, d)) and not d.startswith(".")
        ])

        lines = [
            "# Atlas Skill Index",
            "",
            "> Konsolidierte Skills aus Hermes, Nova, Nexus und Claude.",
            f"> Zuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"**{sum(len(os.listdir(os.path.join(self.skills_dir, c))) for c in categories)} Skills in {len(categories)} Kategorien**",
            "",
        ]

        for cat in categories:
            cat_path = os.path.join(self.skills_dir, cat)
            skills = sorted([
                d for d in os.listdir(cat_path)
                if os.path.isdir(os.path.join(cat_path, d))
            ])
            if skills:
                lines.append(f"## {cat}")
                for skill in skills:
                    # Prüfen auf Konflikte
                    versions = [
                        f for f in os.listdir(os.path.join(cat_path, skill))
                        if f.startswith("SKILL-") and f.endswith(".md")
                    ]
                    tag = " 🔀" if len(versions) > 1 else ""
                    lines.append(f"- [{skill}]({cat}/{skill}/SKILL.md){tag}")
                lines.append("")

        with open(index_path, "w") as f:
            f.write("\n".join(lines))

        print(f"\n📝 Skill-Index geschrieben: {len(categories)} Kategorien")

    def run(self):
        """Führt die Konsolidierung aus."""
        print("=" * 60)
        print("Atlas Skill Consolidator")
        print("=" * 60)

        all_skills = self.scan_skills()
        self.consolidate(all_skills)
        self.write_index()

        print()
        print("=" * 60)
        print("Konsolidierung abgeschlossen!")
        print(f"  ✅ Importiert: {self.stats['imported']}")
        print(f"  ⏭️  Übersprungen: {self.stats['skipped']}")
        print(f"  🔀 Konflikte: {self.stats['conflicts']}")
        print(f"  ❌ Fehler: {self.stats['errors']}")
        print("=" * 60)


if __name__ == "__main__":
    cons = SkillConsolidator()
    cons.run()
