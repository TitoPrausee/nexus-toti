---
name: git-context-memory
description: Store persistent agent context in Git repos when in-memory storage is limited. Survives server restarts, session resets, and cross-session context loss.
version: 1.0.0
author: Toti
metadata:
  hermes:
    tags: [Memory, Persistence, Git, Context, Cross-Session]
    related_skills: [claude-code, hermes-agent]
---

# Git Context Memory

## openpyxl Pitfall
When adding rows to an existing openpyxl worksheet, do NOT use `copy()` on cell style proxies (Font, Fill, Border, Alignment). StyleProxy objects are unhashable and will throw `TypeError: unhashable type: 'StyleProxy'`. Instead, create new style objects directly:
```python
# BAD — crashes with StyleProxy
cell.font = copy(existing_cell.font)

# GOOD — create fresh objects
cell.font = Font(name='Calibri', bold=True, size=10)
cell.fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
cell.border = Border(left=Side('thin', color='CCCCCC'), right=Side('thin', color='CCCCCC'), top=Side('thin', color='CCCCCC'), bottom=Side('thin', color='CCCCCC'))
```

## Project Data Propagation
When new requirements or data points (e.g., A52-A56 from meeting notes) are added to a project, systematically update ALL interconnected documents in one pass:

1. **Requirements list** (e.g., `A01-A51_anforderungen.md`) — append new entries with full metadata
2. **Excel matrix** — add rows + update pilot assignment sheets
3. **Evaluation/decision doc** — add to quadrant tables + full matrix
4. **Unklarheiten doc** — add new open questions per requirement
5. **Offene Fragen** — add new action items (N-01, N-02, etc.)
6. **Stakeholder roadmap** — update stakeholder→requirement mappings + phases
7. **Cloud document list** — update count and entries

After all updates, commit with a descriptive message listing all changed files. This prevents inconsistent state where some docs reference A56 but others stop at A51. — Persistent Agent Memory via Repository

When Hermes agent memory is limited (e.g. 2,200 chars), use a committed file in the Git repo as long-term memory. This file survives server reboots, session resets, and provides instant context recovery.

## When to Use

- Agent memory is near capacity and you need to offload context
- User will be away for extended periods (days/weeks)
- Multiple agent sessions work on the same project
- You need project state, decisions, and progress to persist beyond one conversation

## The AGENT_CONTEXT.md Pattern

### Creating the File

Write a structured markdown file at the project root with these sections:

```markdown
# [Project Name] — Agent Context & State

> This file serves as persistent memory. Updated automatically.

## Project Overview
- Name, stack, repo URLs, branch

## Architecture
- Layer-by-layer status with completion percentages
- Key design decisions

## Packages / Modules
- List with brief descriptions

## Current Test Status
- Pass/fail/skip counts
- Known failures and their causes

## Open Issues / Sprint Status
- Issue table with priorities

## Known Bugs / TS Issues
- Technical debt items that need fixing

## Environment
- API endpoints, proxy configs, PATH quirks
- Binary locations, version numbers

## Key Decisions
- Naming conventions, dependency directions, constraints

## Pending Work
- Checkbox list of outstanding tasks

## Agent Runs Log
| Date | Agent | Task | Result |
|------|-------|------|--------|
```

### Committing & Pushing

Always commit and push immediately after writing:

```bash
git add AGENT_CONTEXT.md
git commit -m "docs: update agent context for cross-session memory"
git push
```

### Reading on Session Resume

When starting a fresh session or after user returns from absence:

1. Pull latest: `git pull`
2. Read `AGENT_CONTEXT.md` with `read_file`
3. Confirm understanding with user
4. Continue work based on the stored context

### Updating Rules

- **Commit after every meaningful change** — don't batch updates
- **Keep it factual** — no prose, just tables and bullets
- **Update test status after every test run** — this is the most volatile section
- **Prune completed items** from Pending Work
- **Log agent runs** with cost and outcome

## Project Document Structure Convention

When organizing a multi-document Git repo (especially for university/project deliverables):

### Directory Pattern
Every subject directory gets its own `export/` subfolder:
```
01_meetingprotokolle/
  ├── 2026-05-05_meeting-01.md    ← Working version (Git-tracked)
  ├── notizen-2026-05.md
  └── export/
      ├── 2026-05-05_meeting-01.docx
      └── notizen-2026-05.docx
```

### Rules
1. **`.md` files** = source of truth, always in the root of the subject folder
2. **`export/`** = generated deliverables (DOCX via pandoc, PDF via LaTeX, XLSX via openpyxl)
3. **Match filenames**: `anforderungscluster.md` → `export/anforderungscluster.docx` (not `CMS-Systemvergleich_FSU-Connect.docx`)
4. **No mixing**: Never put `.md` and `.docx` in the same folder level
5. **README.md** at repo root = complete document index with MD↔export mapping
6. **No umlauts in folder names**: `06_praesentationen` not `06_präsentationen` (Git-safe)

### Batch pandoc conversion
```bash
cd /tmp/project && for f in 04_analysen/*.md; do
  base=$(basename "$f" .md)
  pandoc "$f" -o "04_analysen/export/${base}.docx" --wrap=none
done
```

### German formal documents convention (from Tito's preferences)
- No author names in PDF/LaTeX documents
- Use "abzustimmen" instead of "mit Product Owner"
- Use "Verantwortliche" instead of "Product Owner"
- Use "Investiv" instead of "Strategisch" for high-effort/high-benefit quadrant
- Use "Solo-Entwicklung" not "Solo-Entwickler (Tito)"

## Memory Strategy

Split memory across three layers:

| Layer | Storage | Capacity | Persistence | Use For |
|-------|---------|----------|-------------|---------|
| Hermes memory | Built-in | ~2,200 chars | Cross-session but limited | User preferences, credentials, env facts |
| AGENT_CONTEXT.md | Git repo | Unlimited | Survives everything | Project state, architecture, decisions, agent logs |
| Session search | Conversation history | Very large | Searchable but slow | Detailed conversation recall |

### What Goes Where

**Hermes memory** (2,200 chars):
- User name, communication style, preferences
- GitHub/GitLab usernames and auth notes
- Environment paths and key binaries
- Project name and branch
- Critical rules ("never delete repos", "no Claude co-author")

**AGENT_CONTEXT.md** (unlimited):
- Architecture details and completion percentages
- Test status and known failures
- Issue/sprint tracking
- Key decisions and their rationale
- Agent run logs with costs
- Pending work checklist
- Detailed environment config

## Pitfalls

1. **Don't store secrets** — AGENT_CONTEXT.md is committed to Git. Use Hermes memory for tokens/keys (still not ideal, but at least not in a repo).
2. **Don't duplicate** — if something is in Hermes memory, reference it briefly in AGENT_CONTEXT.md rather than copying.
3. **Keep dates** — always date agent runs and status updates so you can tell what's stale.
4. **Pull before push** — if other agents may have pushed changes, `git pull --rebase` first.