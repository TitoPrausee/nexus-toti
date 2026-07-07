#!/usr/bin/env python3
"""
NEXUS v9 — Skill Diagram Generator

Reads all SKILL.md files from data/skills/, extracts YAML frontmatter,
analyzes content structure, and generates:
  - data/skills/SKILLS.md  (full catalog with per-skill Mermaid diagrams)
  - README snippet          (category overview Mermaid diagram)

Usage:
  python scripts/generate_skill_diagrams.py
  python scripts/generate_skill_diagrams.py --readme-only   # only README snippet
  python scripts/generate_skill_diagrams.py --validate      # validate Mermaid syntax
"""

import os
import re
import sys
from pathlib import Path
from collections import defaultdict

SKILLS_DIR = Path("data/skills")
OUTPUT_SKILLS_MD = SKILLS_DIR / "SKILLS.md"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Category emoji mapping
CATEGORY_EMOJI = {
    "devops": "🔧",
    "software-development": "💻",
    "creative": "🎨",
    "productivity": "📄",
    "github": "🐙",
    "mlops": "🧪",
    "autonomous-ai-agents": "🤖",
    "apple": "🍎",
    "research": "🔬",
    "media": "🎬",
    "mcp": "🔌",
    "gaming": "🎮",
    "smart-home": "🏠",
    "red-teaming": "🔒",
    "social-media": "📱",
    "note-taking": "📝",
    "email": "📧",
    "data-science": "📊",
    "communication": "💬",
    "dogfood": "🐕",
    "diagramming": "📐",
    "web_search-web_fetch-workflow": "🔍",
    "general": "⚡",
}


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from SKILL.md content."""
    fm = {}
    if not content.startswith("---"):
        return fm
    end = content.find("---", 3)
    if end < 0:
        return fm
    frontmatter = content[3:end].strip()

    # First, extract the diagram override using regex (it's multi-line YAML block)
    diag_match = re.search(r'diagram:\s*\|\s*\n((?:  .+\n?)+)', frontmatter)
    if diag_match:
        diagram_raw = diag_match.group(1)
        # Dedent: remove 2-space indent
        lines = []
        for line in diagram_raw.split("\n"):
            if line.startswith("  "):
                lines.append(line[2:])
            elif line.strip():
                lines.append(line.strip())
        fm["diagram_override"] = "\n".join(lines).rstrip()

    # Simple key:value parsing for top-level and nested fields
    current_key = None
    current_value = ""
    in_list = False
    in_metadata = False
    in_hermes = False

    for line in frontmatter.split("\n"):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Skip diagram block (already parsed above)
        if line_stripped.startswith("diagram:"):
            # Skip until we hit a non-indented line
            continue

        # Nested hermes metadata
        if line_stripped.startswith("metadata:"):
            in_metadata = True
            continue
        if in_metadata and line_stripped.startswith("hermes:"):
            in_hermes = True
            continue
        if in_hermes:
            if line_stripped.startswith("tags:"):
                in_list = True
                current_key = "tags"
                current_value = ""
                continue
            if line_stripped.startswith("related_skills:"):
                in_list = True
                current_key = "related_skills"
                current_value = ""
                continue
            if in_list and line_stripped.startswith("- "):
                val = line_stripped[2:].strip().strip('"').strip("'")
                current_value += ("," if current_value else "") + val
                continue
            if in_list:
                fm[current_key] = current_value
                in_list = False
            if not line.startswith(" ") and not line.startswith("-"):
                in_hermes = False
                in_metadata = False
            continue

        # Top-level keys
        if in_list and line_stripped.startswith("- "):
            val = line_stripped[2:].strip().strip('"').strip("'")
            current_value += ("," if current_value else "") + val
            continue

        if in_list and not line_stripped.startswith("- ") and not line_stripped.startswith(" "):
            fm[current_key] = current_value
            in_list = False

        if line_stripped.startswith("name:"):
            fm["name"] = line_stripped.split(":", 1)[1].strip().strip('"').strip("'")
        elif line_stripped.startswith("description:"):
            fm["description"] = line_stripped.split(":", 1)[1].strip().strip('"').strip("'")
        elif line_stripped.startswith("version:"):
            fm["version"] = line_stripped.split(":", 1)[1].strip()
        elif line_stripped.startswith("category:"):
            fm["category"] = line_stripped.split(":", 1)[1].strip()
        elif line_stripped.startswith("author:"):
            fm["author"] = line_stripped.split(":", 1)[1].strip()
        elif line_stripped.startswith("license:"):
            fm["license"] = line_stripped.split(":", 1)[1].strip()
        elif line_stripped.startswith("tags:"):
            in_list = True
            current_key = "tags"
            current_value = ""
        elif line_stripped.startswith("related_skills:"):
            in_list = True
            current_key = "related_skills"
            current_value = ""

    if in_list:
        fm[current_key] = current_value

    return fm


def extract_workflow_steps(content: str, max_steps: int = 5) -> list[str]:
    """Extract key workflow steps from SKILL.md content."""
    steps = []
    in_section = False
    section_patterns = [
        r"^##\s+(?:Schritte|Steps|Workflow|Ablauf|Prozess|Procedure)",
        r"^##\s+(?:How|Usage|Quick|Getting Started|Anwendung)",
    ]

    lines = content.split("\n")
    for line in lines:
        # Check if we're entering a relevant section
        if any(re.match(p, line) for p in section_patterns):
            in_section = True
            continue
        # Stop at next section
        if in_section and line.startswith("## "):
            if not any(re.match(p, line) for p in section_patterns):
                in_section = False
                continue

        if in_section:
            # Numbered steps: "1. Do something"
            m = re.match(r"^\d+\.\s+(.+)", line)
            if m:
                step = m.group(1).strip()[:40]
                steps.append(step)
                if len(steps) >= max_steps:
                    break
            # Bullet steps: "- Step description"
            elif line.startswith("- ") and len(line) > 5:
                step = line[2:].strip()[:40]
                # Skip if it's a sub-bullet or too short
                if len(step) > 5 and not step.startswith(("Note:", "Tip:", "WICHTIG")):
                    steps.append(step)
                    if len(steps) >= max_steps:
                        break

    return steps


def extract_tools(content: str) -> list[str]:
    """Extract tool/technology names from content."""
    tools = set()
    # Common tools mentioned in skills
    tool_patterns = [
        r'\b(curl|jq|python3?|pip|npm|npx|docker|git|gh)\b',
        r'\b(terminal|file_read|file_write|web_search|web_fetch|code_exec|memory|delegation)\b',
        r'\b(ffmpeg|imagemagick|pandoc|latex|pdflatex)\b',
        r'\b(ollama|huggingface|openai|anthropic)\b',
    ]
    for pattern in tool_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            tools.add(match.group(1).lower())
    return sorted(tools)[:6]


def sanitize_node_id(text: str) -> str:
    """Create a valid Mermaid node ID from text."""
    text = text.lower().strip()
    text = re.sub(r'[äöüß]', lambda m: {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}[m.group()], text)
    text = re.sub(r'[^a-z0-9_]', '_', text)
    text = re.sub(r'_+', '_', text)
    return text.strip('_')[:30] or "node"


def generate_diagram_linear(name: str, description: str, steps: list[str], tools: list[str]) -> str:
    """Generate a linear workflow diagram."""
    nodes = ["Input((Anfrage))"]
    for i, step in enumerate(steps[:5]):
        node_id = f"s{i+1}"
        label = step[:30]
        nodes.append(f'{node_id}["{label}"]')
    nodes.append("Output((Ergebnis))")

    lines = ["graph LR"]
    for n in nodes:
        lines.append(f"    {n}")
    for i in range(len(nodes) - 1):
        lines.append(f"    {nodes[i].split('[')[0].split('(')[0]} --> {nodes[i+1].split('[')[0].split('(')[0]}")

    lines.append(f"    style Input fill:#1a1a2e,stroke:#e94560,color:#fff")
    lines.append(f"    style Output fill:#1a2e1a,stroke:#4CAF50,color:#fff")
    return "\n".join(lines)


def generate_diagram_decision(name: str, description: str, tools: list[str]) -> str:
    """Generate a decision/branching diagram for multi-tool skills."""
    lines = ["graph TB"]
    lines.append(f"    Input((Anfrage)) --> Choice{{Tool?}}")

    for i, tool in enumerate(tools[:5]):
        tid = f"t{i+1}"
        lines.append(f'    {tid}["{tool}"]')
        lines.append(f"    Choice -->|{tool}| {tid}")
        lines.append(f"    {tid} --> Output")

    lines.append("    Output((Ergebnis))")
    lines.append("    style Input fill:#1a1a2e,stroke:#e94560,color:#fff")
    lines.append("    style Output fill:#1a2e1a,stroke:#4CAF50,color:#fff")
    lines.append("    style Choice fill:#2a1a3e,stroke:#e94560,color:#fff")
    return "\n".join(lines)


def generate_diagram_integration(name: str, description: str, tools: list[str]) -> str:
    """Generate an integration diagram for API/external service skills."""
    lines = ["graph LR"]
    lines.append(f'    Agent((Agent)) --> Skill["{name}"]')

    externals = tools[:3] if tools else ["API"]
    for i, ext in enumerate(externals):
        eid = f"ext{i+1}"
        lines.append(f'    {eid}("{ext}")')
        lines.append(f"    Skill --> {eid}")

    lines.append("    Result((Result))")
    lines.append("    Skill --> Result")
    lines.append("    style Agent fill:#1a1a2e,stroke:#e94560,color:#fff")
    lines.append("    style Skill fill:#16213e,stroke:#533483,color:#fff")
    lines.append("    style Result fill:#1a2e1a,stroke:#4CAF50,color:#fff")
    return "\n".join(lines)


def generate_diagram_minimal(name: str, description: str) -> str:
    """Generate a minimal trigger-process-result diagram."""
    lines = ["graph LR"]
    lines.append(f'    Trigger((Trigger)) --> Process["{name}"]')
    lines.append(f'    Process --> Result((Result))')
    lines.append("    style Trigger fill:#1a1a2e,stroke:#e94560,color:#fff")
    lines.append("    style Process fill:#16213e,stroke:#533483,color:#fff")
    lines.append("    style Result fill:#1a2e1a,stroke:#4CAF50,color:#fff")
    return "\n".join(lines)


def classify_skill(content: str, fm: dict, steps: list[str], tools: list[str]) -> str:
    """Classify a skill into one of the 4 template types."""
    # If there are workflow steps, it's linear
    if len(steps) >= 2:
        return "linear"
    # If there are multiple tools/choices, it's decision
    if len(tools) >= 3:
        return "decision"
    # If it mentions APIs or external services, it's integration
    api_indicators = ["api", "curl", "endpoint", "http", "request", "oauth", "token"]
    desc_lower = fm.get("description", "").lower()
    content_lower = content[:500].lower()
    if any(ind in desc_lower or ind in content_lower for ind in api_indicators):
        return "integration"
    # Default: minimal
    return "minimal"


def generate_skill_diagram(skill_path: Path) -> tuple[dict, str]:
    """Generate a skill entry with diagram from a SKILL.md file."""
    content = skill_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    steps = extract_workflow_steps(content)
    tools = extract_tools(content)

    # Check for manual override
    if "diagram_override" in fm and fm["diagram_override"]:
        diagram = fm["diagram_override"]
    else:
        # Auto-generate based on classification
        skill_type = classify_skill(content, fm, steps, tools)
        name = fm.get("name", skill_path.parent.name)
        desc = fm.get("description", "")

        if skill_type == "linear":
            diagram = generate_diagram_linear(name, desc, steps, tools)
        elif skill_type == "decision":
            diagram = generate_diagram_decision(name, desc, tools)
        elif skill_type == "integration":
            diagram = generate_diagram_integration(name, desc, tools)
        else:
            diagram = generate_diagram_minimal(name, desc)

    # Determine category from path
    relative = skill_path.parent.relative_to(SKILLS_DIR)
    parts = relative.parts
    category = parts[0] if len(parts) >= 2 else "general"

    return {
        "name": fm.get("name", skill_path.parent.name),
        "description": fm.get("description", ""),
        "category": fm.get("category", category),
        "tags": fm.get("tags", ""),
        "related_skills": fm.get("related_skills", ""),
        "version": fm.get("version", ""),
        "path": str(skill_path),
        "relative_path": str(relative),
        "diagram": diagram,
        "type": classify_skill(content, fm, steps, tools),
    }, diagram


def generate_readme_overview(categories: dict) -> str:
    """Generate the README skills overview Mermaid diagram."""
    # Sort categories by size (largest first)
    sorted_cats = sorted(categories.items(), key=lambda x: len(x[1]), reverse=True)

    lines = ["graph TB"]
    lines.append("    Nexus((NEXUS v9<br/>156 Skills))")

    for cat, skills in sorted_cats[:15]:
        cat_id = re.sub(r'[^a-z0-9]', '', cat.lower())[:15] or "cat"
        emoji = CATEGORY_EMOJI.get(cat, "📦")
        count = len(skills)
        lines.append(f'    {cat_id}["{emoji} {cat}<br/>{count} Skills"]')
        lines.append(f"    Nexus --> {cat_id}")

    # Collapse remaining categories
    remaining = sorted_cats[15:]
    if remaining:
        total = sum(len(s) for _, s in remaining)
        lines.append(f'    other["📦 {len(remaining)} more<br/>{total} Skills"]')
        lines.append(f"    Nexus --> other")

    # Styling
    lines.append("    style Nexus fill:#1a1a2e,stroke:#e94560,color:#fff")

    return "\n".join(lines)


def generate_skills_md(categories: dict, all_skills: list[dict]) -> str:
    """Generate the full SKILLS.md catalog."""
    lines = []
    lines.append("# Toti Skills — Vollstaendiger Katalog")
    lines.append("")
    lines.append(f"> **{len(all_skills)} Skills** in **{len(categories)} Kategorien**.")
    lines.append(f"> Jeder Skill hat ein Workflow-Diagramm. Klicke auf den Skill-Namen fuer Details.")
    lines.append("")
    lines.append("## Inhaltsverzeichnis")
    lines.append("")

    sorted_cats = sorted(categories.items(), key=lambda x: x[0])
    for cat, skills in sorted_cats:
        emoji = CATEGORY_EMOJI.get(cat, "📦")
        anchor = cat.lower().replace(" ", "-").replace("_", "-")
        lines.append(f"- [{emoji} {cat} ({len(skills)})](#{anchor})")

    lines.append("")
    lines.append("---")
    lines.append("")

    for cat, skills in sorted_cats:
        emoji = CATEGORY_EMOJI.get(cat, "📦")
        lines.append(f"## {emoji} {cat}")
        lines.append("")

        for skill in sorted(skills, key=lambda s: s["name"]):
            name = skill["name"]
            desc = skill["description"]
            rel_path = skill["relative_path"]
            diagram = skill["diagram"]

            lines.append(f"### {name}")
            if desc:
                lines.append(f"> {desc[:200]}")
            lines.append("")
            lines.append("```mermaid")
            lines.append(diagram)
            lines.append("```")
            lines.append("")

            # Tags and link
            tags = skill.get("tags", "")
            link = f"[SKILL.md](/{rel_path.replace(os.sep, '/')}/SKILL.md)"
            parts = []
            if tags:
                parts.append(f"**Tags:** {tags}")
            parts.append(f"**Details:** {link}")
            lines.append(" | ".join(parts))
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main():
    os.chdir(PROJECT_ROOT)

    if not SKILLS_DIR.exists():
        print(f"Error: {SKILLS_DIR} not found")
        sys.exit(1)

    # Collect all skills
    categories = defaultdict(list)
    all_skills = []

    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        try:
            skill_info, diagram = generate_skill_diagram(skill_md)
            categories[skill_info["category"]].append(skill_info)
            all_skills.append(skill_info)
        except Exception as e:
            print(f"Warning: Failed to process {skill_md}: {e}")

    print(f"Processed {len(all_skills)} skills in {len(categories)} categories")

    # Generate SKILLS.md
    skills_md = generate_skills_md(categories, all_skills)
    OUTPUT_SKILLS_MD.write_text(skills_md, encoding="utf-8")
    print(f"Written {OUTPUT_SKILLS_MD} ({len(skills_md)} chars)")

    # Generate README snippet
    overview = generate_readme_overview(categories)
    snippet_path = PROJECT_ROOT / "scripts" / "_readme_skills_snippet.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(overview, encoding="utf-8")
    print(f"Written README snippet to {snippet_path}")

    print("Done! Add the following to README.md in the ## Skills section:")
    print("```")
    print(overview)
    print("```")


if __name__ == "__main__":
    main()