---
name: skill-repo-management
description: Manage the Toti Skills git repository on GitLab — sync, evaluate third-party skill repos, and import new skills.
version: 1.0.0
author: Toti
metadata:
  hermes:
    tags: [Skills, Git, GitLab, Import]
---

# Toti Skills Repo Management

## Repo Location

- **Local**: `/opt/data/skills/` (git repo, branch `main`)
- **Remote**: `https://gitlab.com/<GITHUB_USER>e/toti-skills.git`
- **GitLab Token**: `glpat-3_MBbz8_m7IR0TOsIT7yrGM6MQpvOjEKdTpoMnFhNQ8.01.170tcmqo9`
- **GitLab User**: `<GITHUB_USER>e`

## Sync Workflow

```bash
cd /opt/data/skills
git add -A
git commit -m "sync: <description>"
git push origin main
```

## Structure Convention

```
skills/
├── category/
│   └── skill-name/
│       ├── SKILL.md          # Required — main skill definition
│       ├── references/       # Optional — reference docs
│       ├── templates/        # Optional — templates
│       ├── scripts/          # Optional — executable scripts
│       └── examples/         # Optional — example files
├── README.md
└── .gitignore
```

Categories: apple, autonomous-ai-agents, creative, data-science, devops, dogfood, email, gaming, github, mcp, media, mlops, note-taking, productivity, project-sentinel, red-teaming, research, smart-home, social-media, software-development

## Naming Conventions

Git directory names may differ from Hermes canonical names:

| Hermes Canonical | Git Directory | Category |
|---|---|---|
| `audiocraft-audio-generation` | `audiocraft` | mlops/models |
| `evaluating-llms-harness` | `lm-evaluation-harness` | mlops/evaluation |
| `fine-tuning-with-trl` | `trl-fine-tuning` | mlops/training |
| `ideation` | `creative-ideation` | creative |
| `segment-anything-model` | `segment-anything` | mlops/models |
| `serving-llms-vllm` | `vllm` | mlops/inference |

Sub-categorized skills (mlops/) use nested dirs: `mlops/inference/llama-cpp/`, `mlops/training/axolotl/`, etc.

## Evaluating Third-Party Skill Repos

When importing skills from external repos (GitHub, etc.):

### Step 1: Clone & Analyze

```bash
cd /tmp && git clone <repo-url>
cd <repo-name>
# Count SKILL.md files
find . -name "SKILL.md" | wc -l
# List all skill names
find . -name "SKILL.md" -exec dirname {} \; | sed 's|./||'
# Total size
du -sh .
# Check license
cat LICENSE 2>/dev/null | head -5
# Check for Claude Code specific files (commands/, hooks/, .claude-plugin/)
ls commands/ hooks/ .claude-plugin/ 2>/dev/null
```

### Step 2: Check Compatibility\n\n- **License**: CC BY-NC is OK for personal/academic use, not for commercial\n- **SKILL.md format**: Must have YAML frontmatter with `name`, `description`\n- **Claude Code specifics**: `commands/`, `hooks/`, `.claude-plugin/`, `scripts/` dirs are Claude Code only — not needed for Hermes\n- **Symlinks**: Resolve any symlinks before copying (e.g., `skills/` dir with symlinks to actual skill dirs)\n- **Size**: If repo is >10MB, consider curating (drop tests, CI, .github)\n- **Multi-agent architecture**: Skills with 10+ sub-agent `.md` files in `agents/` dirs are usually Claude Code agent-team systems, not simple skills. These typically DON'T work in Hermes because they require Claude Code's agent spawning and slash-command infrastructure. **Red flags**: `agents/` directory with 5+ files, `/ars-*` or other slash commands, Plugin packaging (`.claude-plugin/`), Hook systems (`hooks.json`)\n- **Cross-skill routing**: Skills referencing `.claude/CLAUDE.md` for routing discipline are Claude Code specific\n- **Adaptation vs. Import**: For architectural skills (not tool-specific), adapt the CONCEPTS into a Hermes-compatible SKILL.md. Map platform-specific terms (SESSION-STATE → Hermes memory, systemEvent → Hermes cronjob, etc.). Keep the ideas, rewrite the implementation

### Step 3: Import Strategy

Three levels of import:

1. **Komplett** — Copy everything as-is. Use for small repos (<5MB) with clean structure
2. **Kuratiert** — Copy SKILL.md + references/ + templates/ + examples/. Drop: tests/, scripts/ (if CI-only), .github/, .claude-plugin/, hooks.json. Use for medium repos (5-20MB)
3. **Minimal** — Copy only SKILL.md files. Use for large repos or when only the skill definition is needed

### Step 4: Copy to Categories

```bash
# Copy curated skill into appropriate category
cp -r /tmp/<repo>/<skill-name>/ /opt/data/skills/<category>/<skill-name>/

# Resolve symlinks first if any
cp -Lr /tmp/<repo>/<skill-name>/ /opt/data/skills/<category>/<skill-name>/
```

### Step 5: Commit & Push

```bash
cd /opt/data/skills
git add -A
git commit -m "feat: add <skill-name> from <repo-source>"
git push origin main
```

## Rejection Patterns

Skills that look impressive but should be **rejected** for Hermes:

- **Claude Code Agent Teams**: 10+ agent `.md` files with complex routing, session management, and slash commands. Examples: academic-research-skills (38 agents, Passport-Resume mechanism). Even if concepts are good, the integration is too deep to extract.
- **Plugin-packaged skills**: `.claude-plugin/` directory, `hooks.json`, slash commands — all require Claude Code runtime.
- **Cross-repo orchestration**: Skills that spawn other skills via `.claude/CLAUDE.md` routing discipline.
- **Heavy test suites with CI**: `pytest/`, `.github/workflows/`, integration tests — bloat without Hermes benefit.

**Action**: When you encounter these, extract just the CONCEPTS into a new minimal SKILL.md. Don't copy the repo structure.

## Current Stats (2026-05)

- 114 skills in 19 categories (including proactive-agent adapted from Hal Stack v3.1)
- ~711 files total
- GitLab repo: `<GITHUB_USER>e/toti-skills` (id: 82380049)