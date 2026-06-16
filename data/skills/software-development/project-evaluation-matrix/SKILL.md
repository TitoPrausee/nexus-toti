---
name: project-evaluation-matrix
description: Structured evaluation framework with H/M/L ratings per criterion, justification, force field analysis, and LaTeX PDF output for project decisions.
trigger: evaluating a project, requirements spec, or making Go/No-Go decisions that need documented rationale
steps:
  - Create weighted dimension scores (each /10 with % weight, sum to /100)
  - Per dimension build criterion table with number, criterion, rating, justification
  - Use consistent rating symbols. green means strength, orange means concern, red means critical risk
  - Score individual requirements on 4 sub-dims (Feasibility, Clarity, Risk, Agent Executability) then aggregate to /10
  - Build force field analysis with Blockers vs Drivers, each referencing specific criteria
  - Concrete recommendations in 3 urgency tiers, each action linked to criterion IDs
  - Generate both Markdown and LaTeX PDF output
pitfalls:
  - Always add written justification because value is in why not what
  - Rebuild PDFs when modifying tex source because user expects this
  - HIGH label is ambiguous so always pair with color coding
  - LaTeX Unicode checkmark needs math mode and run pdflatex twice for TOC
---

# Project Evaluation Matrix

Structured evaluation framework for assessing projects with rated criteria and justification.

## Typical Dimensions

1. Requirements Maturity (15%)
2. Stakeholder Situation (25%)
3. Technical Architecture (20%)
4. Feasibility and Risk (20%)
5. Urgency (15%)
6. Agent Executability (5%)

## Rating System

Green HIGH means strength. Orange MEDIUM means needs attention. Red HIGH means critical risk. Always pair with written justification.

## Per-Requirement Scoring

4 sub-dims: Machbarkeit, Klarheit, Risiko, Agent. Each green/orange/red, then aggregate to /10.

## LaTeX Build

```bash
sudo apt-get install -y -qq texlive-latex-base texlive-latex-extra texlive-latex-recommended texlive-fonts-recommended texlive-lang-german
pdflatex -interaction=nonstopmode file.tex  # run twice
```

Commit both .tex and .pdf.