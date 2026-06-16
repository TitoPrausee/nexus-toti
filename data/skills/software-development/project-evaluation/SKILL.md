---
name: project-evaluation
version: 1.0
description: Produce a structured multi-dimensional evaluation of a project with scored justification and actionable recommendations.
---

# Project Evaluation & Decision Rationale

Produce a structured, multi-dimensional evaluation of a project with scored justification and actionable recommendations.

## When to Use
- Assessing a project's viability, priority, or readiness before committing resources
- Making a case for/against pursuing a project with specific evidence
- Evaluating competing projects for limited capacity

## Steps

### 1. Gather All Project Artifacts
Read every available document: requirements, architecture specs, meeting notes, stakeholder analyses, roadmaps, open questions. Use `search_files` and `read_file` to leave no source unread.

### 2. Evaluate Across 6 Dimensions
Score each dimension 1-10 with explicit Pro/Con bullet points:

| Dimension | What to Assess |
|-----------|---------------|
| **Anforderungsreife** (Requirements Maturity) | Are requirements quantified with acceptance criteria, or just qualitative wishes? Are dependencies between requirements modeled? |
| **Stakeholder-Lage** (Stakeholder Situation) | Are stakeholders identified, aligned, and reachable? Is there a clear decision-maker (Product Owner)? Are access/permissions in place? |
| **Technische Architektur** (Technical Architecture) | Is the architecture documented, justified (with comparison tables), and implementable? Are API specs, data models, and deployment plans concrete or aspirational? |
| **Machbarkeit & Risiko** (Feasibility & Risk) | What are the top risks? Are timelines realistic given scope? Are there organizational blockers (access, expertise, budget)? |
| **Dringlichkeit** (Urgency) | Are there external deadlines, stakeholder expectations, or funding timelines? What happens if we delay? |
| **Agenten-Umsetzbarkeit** (Agent Executability) | What % of work can autonomous agents do vs. what requires human coordination, access, or decisions? |

### 3. Compute Weighted Score
Assign realistic weights (total 100%). Typical defaults:
- Requirements: 15%
- Stakeholders: 25% (highest — org blockers kill projects)
- Architecture: 20%
- Feasibility: 20%
- Urgency: 15%
- Agent Executability: 5%

Calculate: `sum(dimension_score × weight)` → map to 0-100 scale.

### 4. Write Two Decision Sections
**Why this project has priority** — concrete reasons with evidence from artifacts.
**Why this project should NOT start blindly** — blockers, risks, prerequisites that must be resolved first.

### 5. Actionable Recommendations (Time-Boxed)
Group recommendations by time horizon:
- **Sofort (This Week)** — organizational blockers (access, meetings, decisions)
- **Next 2 Weeks** — preparatory technical work (specs, schemas, mock APIs)
- **Month 1-2** — first implementation sprints

### 6. Commit & Push
Save the evaluation to the project repo (e.g., `04_analysen/bewertung-entscheidung.md`) and git push. Update memory with project priority status.

## Pitfalls
- Don't give all dimensions the same score — real projects always have strengths AND weaknesses
- Don't skip the "why NOT" section — it's the most valuable part for decision-making
- Stakeholder dimension is typically the biggest risk factor; score it honestly
- Agent executability matters for resource planning — be specific about what agents CAN'T do (access, decisions, external review)
- Always commit evaluation to git so it persists across sessions