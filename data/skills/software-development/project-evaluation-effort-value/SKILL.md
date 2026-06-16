---
name: project-evaluation-effort-value
description: Evaluate project requirements using Effort-Value matrix instead of abstract quality scores. Produces actionable prioritization with Quick Wins / Strategic / Needs-based / On Ice quadrants.
---

# Project Evaluation: Effort-Value Matrix

When evaluating project requirements or feature lists, use an **effort-value matrix** — NOT abstract quality dimensions.

## Why

Abstract dimensions like "feasibility", "clarity", "risk", "agent-compatibility" are academically interesting but **not actionable**. The user wants to know: _What should I build first? What can wait? What's not worth doing?_

The effort-value approach answers this directly.

## Method

### Axes
- **Effort (Y-axis):** S (hours–1 day), M (2–5 days), L (1–2 weeks), XL (3+ weeks, complex dependencies)
- **Value (X-axis):** HIGH (core feature, MVP-relevant, directly visible), MED (important but not blocking, improves product), LOW (nice-to-have, marginal benefit)

### 4 Quadrants

| Quadrant | Effort | Value | Action |
|----------|--------|-------|--------|
| **Quick Wins** | S/M | HIGH/MED | Build immediately |
| **Strategic** | L/XL | HIGH | Plan into dedicated sprints |
| **Needs-based** | M/L | MED/LOW | Phase 2, if time permits |
| **On Ice** | any | LOW | Defer indefinitely |

### Output Format

1. **Quick Wins table** — sorted by effort ascending, value descending. Include "Why" column.
2. **Strategic investments table** — include "Why expensive" and "Strategy" columns (e.g., "Mock-API first", "Start with fallback").
3. **Needs-based table** — group by feature area if possible.
4. **On Ice table** — include "Why defer" column. Be explicit about what's being cut.
5. **Complete matrix** — all requirements in one sorted table with quadrant classification.
6. **Sprint recommendation** — group by quadrant into actual sprints with effort estimates.

### Critical Items to Flag

- **XL + HIGH value items** get a special warning box — they need separate planning, external expertise, or dedicated budget. Don't bury them in a normal sprint.
- **Organizational blockers** (access, product owner, decisions) listed as **pre-Sprint-1 blockers** with WHO resolves them.

### What NOT to Do

- Don't rate on abstract dimensions like "clarity", "feasibility", "risk" unless the user explicitly asks for it
- Don't create "agent-compatibility" scores unless specifically requested
- Don't use numbered scores (7/10, 4/10) as the primary output — use the quadrant classification
- Don't list pros/cons without connecting them to actionable next steps

## LaTeX PDF Generation

When the evaluation needs to be a PDF:
1. Use `scrartcl` document class with German babel
2. Define color-coded row macros: `\QUICK`, `\STRAT`, `\FILL`, `\ICE` for quadrant labels
3. Use `\rowcolor` for visual grouping in the complete matrix
4. Use `tcolorbox` for quadrant explanation boxes (quickbox, stratbox, fillbox, icebox, warnbox)
5. Use `longtable` for the complete matrix so it flows across pages
6. Run pdflatex twice for TOC/references
7. Check for Unicode characters that break LaTeX (✓ → `$\checkmark$`, × → `\texttimes`)

## Terminology

- The user prefers **"Investiv"** over "Strategisch" for the L/XL + HIGH quadrant. It emphasizes the investment character (high effort, high return) rather than vague "strategic" framing.
- Always use neutral terminology in formal documents: "abzustimmen" not "mit Product Owner", "Verantwortliche" not "Product Owner (Name)". No personal names in action items.

## Excel Output

When also producing an Excel (.xlsx) matrix:
1. Use `openpyxl` (available via `apt install python3-openpyxl`)
2. Add a separate **Legende** sheet with color-coded sections: Aufwand (S/M/L/XL), Nutzen (HIGH/MED/LOW), Quadrants explanation, Pilot proposals
3. Use `PatternFill` for quadrant colors: Quick Win = green, Investiv = blue, Bedarfsorientiert = orange, Auf Eis = red
4. Include Pilot proposals (A–D) as readable text in the legend, not just codes
5. Map requirements to Pilot codes in the main matrix sheet

## Planning Phase vs Implementation Phase

**Critical distinction:** When a project is in **planning phase**, the user wants planning documents, NOT implementation:
- ✅ Concept documents, dependency maps, contact lists, resource requirements
- ✅ "Who do we need to contact?" lists, "What access do we need?" tables
- ✅ Prioritized task lists for HUMANS to execute (call people, request access, research CI)
- ❌ Mock APIs, code prototypes, database schema implementations, Docker setups
- ❌ Technical implementation tasks that require infrastructure not yet available

When assigning tasks, consider WHO does them. In planning phase, most tasks are human-facing (stakeholder coordination, access requests, research). Only suggest technical implementation when the user explicitly asks or when all dependencies are resolved.

## Pitfalls

- The user will reject abstract/academic ratings. Always connect ratings to **actionable decisions**: build now, plan, defer, cut.
- Effort estimates should be realistic for a small team (1–2 people), not an enterprise team
- Flag items that need external dependencies (APIs, experts, access) — these are blockers, not effort items
- Don't put legends inside the main data sheet — use a separate tab. The user explicitly rejected inline legends above the table.
- When requirements grow (e.g., A01-A51 → A01-A56), update ALL artifacts: markdown matrix, Excel, LaTeX, stakeholder roadmap, open questions, and cloud document list. Keep everything in sync.
- Use `apt install python3-openpyxl` for Excel generation — `pip` and `python-docx` are NOT available via pip