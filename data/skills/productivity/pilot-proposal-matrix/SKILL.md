---
name: pilot-proposal-matrix
version: 1.0
created: 2026-05-06
description: Create structured effort-benefit matrices with multiple pilot/MVP proposals from requirements lists, with transparent reasoning and comparison tables.
category: productivity
---

# Pilot Proposal Matrix

Create structured evaluation matrices with multiple pilot/MVP proposals from a list of requirements.

## When to Use
- Evaluating project requirements with effort/benefit ratings
- Creating pilot or MVP proposals instead of sprint plans
- User wants transparent reasoning for why requirements are grouped together
- Multiple stakeholder groups need different proposal options

## Key Principles

1. **Vorschlag, not Festlegung** — All groupings are proposals/suggestions, not final assignments. Label every quadrant and proposal as "Vorschlag, final zu entscheiden mit Product Owner"

2. **No warning boxes for individual items** — Don't single out requirements with special warning callouts (e.g., "this needs external review"). Treat them as normal matrix entries. If there's a dependency, mention it in the comparison table's "risk" column.

3. **4 Pilot proposals instead of sequential sprints** — User explicitly rejected sprint sequences. Create 3-5 pilot proposals that could each be a standalone viable product by a deadline.

4. **Each pilot needs:**
   - Requirement table with ID, name, effort (S/M/L/XL), benefit (HIGH/MED/LOW), and "Why in this pilot" column
   - Total effort calculation in person-days/weeks
   - Feasibility check against deadline (with buffer)
   - Pros/cons matrix (Speed, UX, Stakeholder, Risk — at minimum)
   - PlantUML effort distribution diagram
   - Clear statement of what's missing (lücken)

5. **Pilot comparison table** at the end with columns: Focus, Requirements count, Total effort, Person-days, Risk level, Standalone viability, Stakeholder alignment

6. **Effort/benefit rating rationale** — Every H/M/L rating must have a one-line justification. Not just "HIGH" but "HIGH — Kern-UX, ohne Filter keine Zielgruppenansprache"

7. **Both MD and LaTeX/PDF** — Maintain both formats. Rebuild PDF after changes with `pdflatex` (2 passes for TOC). Commit and push.

8. **German language** — All content in German unless user specifies otherwise.

## File Structure
- `{project}/04_analysen/bewertung-entscheidung.md` — Markdown source
- `{project}/06_präsentationen/{project}-bewertungsmatrix.tex` — LaTeX source
- `{project}/06_präsentationen/{project}-bewertungsmatrix.pdf` — Built PDF

## LaTeX Tips
- Use `longtable` for requirement tables (spans pages)
- Define color commands (`\QUICK`, `\STRAT`, `\FILL`, `\ICE`) for quadrant labels
- Use `tcolorbox` for styled boxes (quickbox, stratbox, fillbox, icebox)
- Use `tabularx` for comparison tables with line-wrapping columns
- Run pdflatex twice for correct TOC
- German: `\usepackage[ngerman]{babel}`

## Pitfalls
- Don't create warning callout boxes for individual requirements — user explicitly rejected this
- Don't use "Agent-gestützte Analyse" as author — use actual person name
- Don't assign concrete requirements to quadrants as final decisions — keep as proposals
- Don't use abstract evaluation dimensions (feasibility, clarity, risk) — use effort vs. benefit only