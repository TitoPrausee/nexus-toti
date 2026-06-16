# 🧠 Toti Knowledge Base

Wissensdatenbank für **Toti** — Skills, Referenzen, Templates, Scripts und Projektwissen.

**156+ Skills** in **25 Kategorien**, gepflegt von Toti & Mercury.

## Was ist das?

Nicht nur eine Skill-Sammlung — das ist die zentrale Wissensbasis für alle Agenten (Toti, Mercury, Claude Code). Jeder Eintrag besteht aus:

- **SKILL.md** — Die Prozedur: Wann, wie, warum
- **references/** — Deep-Dive-Wissen: API-Dokus, Architektur-Referenzen, Pitfalls
- **templates/** — Direkt verwendbare Vorlagen: LaTeX, HTML, Dokumente
- **scripts/** — Ausführbare Hilfsskripte: Security-Audits, Benchmarks, Builder

## Struktur

```
knowledge-base/
├── apple/                  # Apple-Ökosystem (Reminders, Notes, FindMy, iMessage)
├── autonomous-ai-agents/   # Multi-Agent-Orchestrierung, Heartbeat, Proactive Agent
├── creative/               # ASCII Art, Diagramme, Präsentationen, Videos, Comics
├── data-science/           # Jupyter, Datenanalyse
├── devops/                 # Docker, Tailscale, Ollama, Mercury Remote, Discord
├── dogfood/                # QA-Testing, UI-Analyse, Issue-Taxonomie
├── email/                  # E-Mail (IMAP/SMTP via himalaya)
├── gaming/                 # Minecraft, Fabric Modding, Pokemon
├── github/                 # GitHub Workflow, Code Review, Issues, PRs
├── mcp/                    # Model Context Protocol — Ecosystem & Native Client
├── media/                  # YouTube, GIFs, Musik, Audio-Visualisierung
├── mlops/                  # ML Ops, LLM Training, Inference, Evaluation
├── note-taking/            # Obsidian
├── productivity/           # LaTeX, DOCX, PowerPoint, OCR, Notion, Linear
├── project-sentinel/       # Hintergrund-Watcher für Projekte
├── red-teaming/            # Ethical Hacking, Jailbreaking, Sicherheitstests
├── research/               # arXiv, Blogwatcher, LLM-Wiki, Polymarkt
├── smart-home/             # Philips Hue, Mac Remote, Homebridge
├── social-media/           # X/Twitter (xurl)
└── software-development/   # Effect-TS, Tauri, Flutter, Planung, Debugging, TDD
```

## Inter-Agent-Kommunikation

Toti ↔ Mercury kommunizieren über **GitLab Issues** mit Richtungs-Labels:
- `toti→mercury` — Nachricht von Toti an Mercury
- `mercury→toti` — Nachricht von Mercury an Toti
- `inter-agent` — Generische Markierung

Siehe `autonomous-ai-agents/inter-agent-communication/SKILL.md` für Details.

## Wissen hinzufügen

Jeder Eintrag hat eine `SKILL.md` mit YAML-Frontmatter:

```yaml
---
name: mein-eintrag
description: Beschreibung
version: 1.0.0
author: Toti
tags: [tag1, tag2]
---
```

Dazugehöriges Wissen in Unterverzeichnissen:
- `references/` — Tiefergehende Doku, API-Referenzen, Pitfalls
- `templates/` — Vorlagen für Dokumente, Konfigurationen, Code
- `scripts/` — Ausführbare Skripte für wiederkehrende Aufgaben

## Sync

```bash
cd /opt/data/skills
git pull --rebase
git add -A && git commit -m "sync: beschreibung" && git push
```

## Statistik

- **156+ SKILL.md** Einträge
- **375+** Referenz-, Template- und Script-Dateien
- **25** Kategorien
- **2** aktive Mitgestalter: Toti & Mercury