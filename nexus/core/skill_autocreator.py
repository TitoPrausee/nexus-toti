"""
NEXUS v9 — Skill Auto-Creator
Automatically creates skill files when the agent learns something new.
Scans conversation for learnable patterns and writes .md skill files.
Also provides skill listing and summary generation for system prompt injection.
"""

import os
import re
import json
import time
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("nexus.skill_creator")

# Directory for storing skills (auto-created + curated)
SKILLS_DIR = Path("data/skills")


def _sanitize_name(name: str) -> str:
    """Create a filesystem-safe skill name from a topic."""
    name = name.lower().strip()
    name = re.sub(r'[äöüß]', lambda m: {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}[m.group()], name)
    name = re.sub(r'[^a-z0-9]+', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')[:64] or "untitled"


def _extract_learnable_topics(response: str, tool_calls: list, user_message: str) -> list[dict]:
    """Analyze a conversation turn for learnable patterns.

    Returns list of potential skills:
    [{name, summary, steps, category, trigger}]
    """
    skills = []

    # Pattern 1: Tool call sequences that worked (multi-step procedures)
    if len(tool_calls) >= 2:
        tool_names = [tc.get("tool", "") for tc in tool_calls]
        # If a sequence of tools was used successfully, that's a learnable pattern
        unique_tools = list(dict.fromkeys(tool_names))  # Preserve order, remove dupes
        if len(unique_tools) >= 2:
            name_parts = "-".join(unique_tools[:3])
            steps = [f"Ist {tc.get('tool', '?')} ausführen mit relevanten Argumenten" for tc in tool_calls[:5]]
            skills.append({
                "name": f"{name_parts}-workflow",
                "summary": f"Workflow: {' → '.join(unique_tools)} für '{user_message[:60]}'",
                "steps": steps,
                "category": "workflow",
                "trigger": user_message[:80],
            })

    # Pattern 2: Error resolution patterns
    error_patterns = [
        (r'(?:FEHLER|Error|fehlerhaft|fehlgeschlagen).*?(?:Lösung|lösung|workaround|behoben|fixed|gelöst)\s*[:=]\s*(.+?)(?:\n|$)', "error-resolution"),
        (r'(?:das\s+Problem\s+war|the\s+issue\s+was)\s+(.+?)(?:\.|$)', "debug-insight"),
    ]
    for pattern, cat in error_patterns:
        match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
        if match:
            detail = match.group(1).strip()[:200]
            skills.append({
                "name": f"{cat}-{_sanitize_name(detail[:30])}",
                "summary": f"Fehler-Lösung: {detail}",
                "steps": [f"Erkennen: {detail[:100]}", "Lösung anwenden"],
                "category": "debugging",
                "trigger": detail[:80],
            })

    # Pattern 3: Configuration/setup knowledge
    config_patterns = [
        (r'(?:konfiguriert|configured|eingestellt|set\s+up)\s+(.+?)(?:\.\s|$)', "config"),
        (r'(?:die\s+Einstellung\s+(?:ist|lautet))\s+(.+?)(?:\.|$)', "config"),
    ]
    for pattern, cat in config_patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            detail = match.group(1).strip()[:200]
            skills.append({
                "name": f"{cat}-{_sanitize_name(detail[:30])}",
                "summary": f"Konfiguration: {detail}",
                "steps": [f"Einstellung: {detail[:150]}"],
                "category": "configuration",
                "trigger": detail[:80],
            })

    return skills


def _skill_file_content(skill: dict) -> str:
    """Generate SKILL.md content for a learned skill."""
    now = datetime.now().strftime("%Y-%m-%d")
    steps_md = "\n".join(f"{i+1}. {s}" for i, s in enumerate(skill["steps"]))
    return f"""---
name: {skill['name']}
description: {skill['summary']}
version: 1.0.0
author: NEXUS Auto-Skill
created: {now}
category: {skill['category']}
trigger: "{skill['trigger']}"
---

# {skill['name']}

{skill['summary']}

## Schritte

{steps_md}

## Kontext

Auto-erstellt von NEXUS nach erfolgreicher Ausführung.

## Auslöser

Wenn der Nutzer etwas fragt wie: "{skill['trigger']}"
"""


def maybe_create_skill(response: str, tool_calls: list, user_message: str,
                       result_success: bool = True) -> list[str]:
    """Analyze a turn and create skill files for learnable patterns.

    Only creates skills when:
    - Tool calls were successful
    - A clear pattern can be extracted
    - No duplicate skill already exists

    Returns list of created skill names.
    """
    if not result_success:
        return []

    potential_skills = _extract_learnable_topics(response, tool_calls, user_message)

    # Only create max 1 skill per turn (avoid spam)
    if not potential_skills:
        return []

    # Pick the most relevant one (first = multi-step workflow > error > config)
    skill = potential_skills[0]
    skill_name = skill["name"]

    # Ensure skills directory exists
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    # Check if skill already exists
    skill_path = SKILLS_DIR / f"{skill_name}" / "SKILL.md"
    if skill_path.exists():
        log.debug(f"Skill already exists: {skill_name}")
        return []

    # Create the skill file
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    content = _skill_file_content(skill)

    try:
        skill_path.write_text(content, encoding="utf-8")
        log.info(f"Auto-created skill: {skill_name}")
        return [skill_name]
    except Exception as e:
        log.error(f"Failed to create skill {skill_name}: {e}")
        return []


def list_auto_skills() -> list[dict]:
    """List all skills with name and description from YAML frontmatter.

    Scans recursively: data/skills/category/skillname/SKILL.md
    and data/skills/skillname/SKILL.md (flat structure).
    """
    if not SKILLS_DIR.exists():
        return []

    skills = []
    # Find all SKILL.md files recursively (category/skillname/SKILL.md or skillname/SKILL.md)
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        # Determine category from parent directory structure
        # e.g. data/skills/devops/ollama-launch-setup/SKILL.md -> category=devops
        # e.g. data/skills/dogfood/SKILL.md -> category=general (flat structure)
        relative = skill_dir.relative_to(SKILLS_DIR)
        parts = relative.parts
        if len(parts) >= 2:
            # Nested: category/skillname
            category = parts[0]
        else:
            # Flat: skillname (no category directory)
            category = "general"

        skill_info = {
            "name": skill_dir.name,
            "path": str(skill_md),
            "description": "",
            "category": category,
            "created": skill_md.stat().st_mtime,
        }
        # Parse YAML frontmatter for name + description
        try:
            content = skill_md.read_text(encoding="utf-8")
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    frontmatter = content[3:end].strip()
                    for line in frontmatter.split("\n"):
                        line = line.strip()
                        if line.startswith("name:"):
                            skill_info["name"] = line.split(":", 1)[1].strip()
                        elif line.startswith("description:"):
                            desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                            skill_info["description"] = desc
                        elif line.startswith("category:"):
                            skill_info["category"] = line.split(":", 1)[1].strip()
        except Exception:
            pass
        skills.append(skill_info)
    return sorted(skills, key=lambda s: s["created"], reverse=True)


def get_skills_summary(max_skills: int = 200, max_chars: int = 4000) -> str:
    """Build a concise skill summary for the system prompt.

    Returns a compact category-grouped overview with skill names only.
    Not full descriptions — just enough for the LLM to know what categories
    and skills exist. Keeps the summary under max_chars to avoid bloating
    the system prompt.
    """
    skills = list_auto_skills()
    if not skills:
        return ""

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for skill in skills[:max_skills]:
        cat = skill.get("category", "general") or "general"
        by_category.setdefault(cat, []).append(skill)

    # Build compact lines: category: skill1, skill2, skill3
    lines = []
    for cat, cat_skills in sorted(by_category.items()):
        names = [s.get("name", "unknown") for s in cat_skills]
        lines.append(f"  {cat}: {', '.join(names)}")

    header = f"Verfuegbare Skills ({len(skills)} insgesamt):"
    result = header + "\n" + "\n".join(lines)

    # Truncate if too long for system prompt
    if len(result) > max_chars:
        # Shorten: only show skill counts per category
        short_lines = []
        for cat, cat_skills in sorted(by_category.items()):
            short_lines.append(f"  {cat}: {len(cat_skills)} Skills")
        result = header + "\n" + "\n".join(short_lines)

    return result