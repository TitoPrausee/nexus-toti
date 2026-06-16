---
name: toti-presentations
description: "Generate Toti-branded project status presentations after each heartbeat work cycle. Dark theme with teal accents, consistent visual identity."
tags: [toti, presentation, pptx, status-report]
---

# Toti Presentations

Auto-generate project status slide decks after every heartbeat WORK phase. Maintains a consistent Toti visual identity across all presentations.

## Setup (one-time)

```bash
mkdir -p /tmp/toti-training/presentations
cd /tmp/toti-training/presentations
export PATH="$PATH:/opt/data/home/.bun/bin"
bun add pptxgenjs
```

**Important**: 
- Global `npm install -g pptxgenjs` fails with permission errors in the Docker container. Always install locally in the presentations directory.
- Prefer `bun` over `npm` — it's already available at `/opt/data/home/.bun/bin/bun`.
- Scripts should use `.mjs` extension for ESM imports.

## Visual Identity

| Element | Value |
|---------|-------|
| Background dark | `1a1a2e` |
| Background mid | `16213e` |
| Teal primary | `028090` |
| Teal light | `00A896` |
| Mint accent | `02C39A` |
| White text | `FFFFFF` |
| Gray text | `a0a0b0` |
| Layout | `LAYOUT_WIDE` (16:9) |

## Slide Templates

Each presentation should follow this structure:

### 1. Title Slide
- Project name (48pt bold, white)
- Subtitle/description (28pt, teal light)
- Tech stack tagline (16pt, gray)
- Date (14pt, gray)
- Teal accent bar below subtitle

### 2. Architecture Slide
- Section title + teal underline
- 6x2 grid of rounded-rect boxes (BG_MID fill, teal border)
- Each box: Component name (18pt bold, teal) + description (12pt, gray)
- Components: Gateway, Memory, Agent Runtime, Team, Skills, CLI+UI

### 3. Feature Slide
- Feature name as title
- Bullet points with teal circle markers
- One feature capability per line (15pt, white)

### 4. Progress Slide
- 3 large stat callouts (72pt bold)
  - Test count (mint), failures (white), test files (teal)
- Timeline bar with milestone dots
  - Each: version label + test count

### 5. Next Steps Slide
- Rounded-rect cards (BG_MID, teal border)
- Priority badge (HIGH = red `FF6B6B`, MED = yellow `FFD93D`)
- Title (18pt bold) + description (12pt, gray)

### 6. Closing Slide
- "Toti" centered (64pt bold)
- Tagline (22pt, teal light)
- Mint accent bar
- Repo URL (14pt, gray)

## Script Pattern

```javascript
import pptxgen from "pptxgenjs";

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "Toti Agent";
pptx.title = "Feature Name — Toti";

// ... build slides using templates above ...

const outPath = `/tmp/toti-training/presentations/${new Date().toISOString().split("T")[0]}-feature-name.pptx`;
await pptx.writeFile({ fileName: outPath });
```

Run with: `cd /tmp/toti-training/presentations && export PATH="$PATH:/opt/data/home/.bun/bin" && bun run script.mjs`

Alternatively, for one-shot scripts without persisting a project: `cd /tmp/toti-training/presentations && bun run script.mjs` (bun auto-installs deps from import specifiers).

## File Naming

`/tmp/toti-training/presentations/YYYY-MM-DD-feature-name.pptx`

## Also Create

For each `.pptx`, also write a companion `.md` summary:
`/tmp/toti-training/presentations/YYYY-MM-DD-feature-name.md`

Content: Title, what was built, key code snippet, test results, next steps.

## Pitfalls

- **No global npm**: Container permissions block `npm install -g`. Use local install in presentations dir, or let `bun` auto-install deps.
- **Use bun**: `bun run script.mjs` is preferred over `node script.mjs`. Bun is at `/opt/data/home/.bun/bin/bun` — add to PATH first.
- **No pip/markitdown**: Container has no pip, so QA via `python -m markitdown` won't work. Rely on pptxgenjs output verification instead.
- **Keep slides visual**: No walls of text. Use shapes, colors, icons. One concept per slide.
- **RAM awareness**: pptxgenjs uses ~50-100MB. Acceptable in heartbeat context but check `free -h` before generating.
- **write_file tool risk**: In automated cycles, NEVER use the hermes `write_file` tool to create .pptx or companion .md files — it can silently zero files. Use Python `open()` + write for .md files instead.
- **Script debugging**: If `bun run script.mjs` fails, check for syntax errors in the .mjs file. Use `bun eval` for quick testing of snippets.