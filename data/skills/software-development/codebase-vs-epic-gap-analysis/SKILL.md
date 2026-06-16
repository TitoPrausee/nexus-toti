---
name: codebase-vs-epic-gap-analysis
description: Compare EPIC checklists, user stories, and architecture docs against actual code to identify truly missing features, partial implementations, and unplanned code.
trigger:
  - compare codebase against epics
  - gap analysis
  - sprint readiness
  - what features are missing
  - checklist audit
---

# Codebase vs EPIC Gap Analysis

Compare planning documents (EPICs, user stories, sprint checklists) against actual codebase implementation to identify what's truly missing, partially done, or unplanned.

## When to Use
- Comparing specs/user stories against implemented features
- Sprint readiness assessments
- Pre-launch feature audits
- Determining what work remains vs what's done

## Steps

1. **Find all planning documents**: Search for EPIC, sprint, checklist, user-stories, TODO, and architecture markdown files. Check `docs/`, project root, wiki/, and `.github/` directories.

2. **Extract requirements**: From each planning doc, list every user story, acceptance criterion, and feature requirement. Note priority (MUST-HAVE, SHOULD-HAVE, NICE-TO-HAVE).

3. **Survey the actual codebase**:
   - List all feature directories (e.g., `lib/features/*/`)
   - Read the router/navigation config to see all screens/pages
   - Check database migrations for schema completeness
   - Scan test directories for test coverage
   - Read key config files (pubspec.yaml, package.json, etc.) for declared but unused dependencies
   - Check CI/CD workflows for deployment status

4. **Cross-reference**: For each EPIC requirement, check:
   - ✅ DONE — Feature exists in code (screen, provider, service, migration)
   - ⚠️ PARTIAL — Some parts exist but acceptance criteria may not be fully met
   - ❌ MISSING — No implementation found
   - ❓ UNCLEAR — Implementation exists but verification needed (e.g., deployment, deep linking)
   - 🆕 UNPLANNED — Feature exists in code but not in any EPIC/story

5. **Identify critical gaps**:
   - MUST-HAVE features with ❌ or ⚠️ status
   - Architecture plan vs actual code structure mismatches
   - Dependencies declared but not used (implementation gap)
   - Test files that are stubs/placeholders
   - Sprint checklist items still marked as incomplete

6. **Report format**: Use a table with Status column (emoji + label), grouping by EPIC or sprint. Add a "Truly Missing" summary at the end focusing on what blocks release/MVP.

## Key Pitfalls
- Don't assume a file exists means a feature works — check if test files contain actual logic or are just stubs
- Planning docs may be outdated — features may exist in code that aren't documented
- Check for route definitions separately from screen files — a screen file without a route is dead code
- Migration files reveal planned features even if frontend code is missing
- Backend services without corresponding frontend screens indicate incomplete feature integration