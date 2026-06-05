# NEXUS v7

Autonomer KI-Agent mit Seele. Eins entscheidet, delegiert bei Bedarf.

## Architektur

```
nexus.py              # Entry Point (CLI / Telegram / Test)
config.yaml           # Zentrale Konfiguration
requirements.txt       # Dependencies

nexus/
  core/
    agent.py           # NexusAgent — das Gehirn
    llm_client.py      # Ollama Cloud Client (Streaming, Fallback)
    memory.py          # L1-L4 Gedächtnis (Working → Soul)
    tools.py           # 11 echte Tools (terminal, file, web, code, delegation)
  interfaces/
    telegram_bot.py    # Streaming-Telegram-Interface
    cli.py             # Minimal-CLI für Tests
  soul/
    __init__.py        # SoulEngine — persistente Identität
    soul.yaml          # Persönlichkeit, Werte, Eigenheiten
  memory/              # Runtime-Daten (gitignored)
```

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env  # Edit with your keys

# 3. Test
python nexus.py --test

# 4. Run CLI
python nexus.py

# 5. Run Telegram
python nexus.py --telegram
```

## Kern-Konzept: Soul-Driven

Toti hat eine **Seele** — nicht nur Kontext, sondern Identität:
- **Persönlichkeit**: Wer ist Toti, wie spricht er, was wertet er
- **Beziehungen**: Erkennt Nutzer, merkt sich Präferenzen
- **Wissen**: Lernt Fakten die über Sessions hinweg bleiben
- **Eigenheiten**: Trockener Humor, Effizienz-Fokus, Deutsch-first

## LLM-Routing

| Spezialist | Modell | Einsatz |
|---|---|---|
| Default/Orchestration | kimi-k2.6:cloud | Gespräche, Planung |
| Coding | qwen3-coder-next:cloud | Code schreiben, debuggen |
| Research | glm-5.1:cloud | Recherche, Analyse |
| Fast/Cheap | gemini-3-flash-preview:cloud | Schnelle Antworten |

## Tools

Alle **echt implementiert** — keine Stubs:
- `terminal` — Shell-Befehle
- `file_read` / `file_write` / `file_search` — Dateisystem
- `web_search` / `web_fetch` — Web-Recherche
- `code_exec` — Python-Code ausführen
- `calculator` — Math
- `time` — Datum/Zeit
- `delegation` — An Spezialisten delegieren
- `memory` — L1-L4 Gedächtnis verwalten

## vs. v5/v6

| | v5/v6 | v7 |
|---|---|---|
| Agenten | 6 separate | 1 + Delegation |
| LLM | z-ai CLI (fiktiv) | Ollama Cloud (real) |
| Tools | 44+ Stubs | 11 echte |
| Gedächtnis | Session-Files | L1-L4 + Soul |
| Identität | Config-Prompts | Persistente Seele |
| Streaming | Nein | Ja |
| Persönlichkeit | Templates | Lernend, adaptiv |