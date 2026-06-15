<p align="center">
  <img src="https://img.shields.io/badge/version-9.0-blue?style=for-the-badge&labelColor=0a0a0a" alt="Version">
  <img src="https://img.shields.io/badge/python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=0a0a0a" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge&labelColor=0a0a0a" alt="License">
  <img src="https://img.shields.io/badge/status-production-orange?style=for-the-badge&labelColor=0a0a0a" alt="Status">
</p>

<h1 align="center">NEXUS v9</h1>

<p align="center">
  <strong>Autonomer KI-Agent mit Seele.</strong><br>
  Ein einziger Agent, der denkt, delegiert und sich erinnert — nicht nur reagiert.
</p>

---

## Diagramme

### System-Architektur

```mermaid
graph TB
    subgraph Interfaces
        TG[Telegram Bot]
        CLI[CLI Interface]
    end

    subgraph NexusAgent
        AG[Agent Core<br/>Think-Act Loop]
        SOUL[SoulEngine<br/>Persönlichkeit · Beziehungen]
        MEM[MemorySystem<br/>L1 · L2 · L3 · L4]
        TOOLS[ToolRegistry<br/>11 Werkzeuge]
        LLM[LLMClient<br/>Ollama Cloud]
    end

    subgraph LLM_Routing["LLM-Routing"]
        K[kimi-k2.6:cloud<br/>Orchestrator]
        Q[qwen3-coder:cloud<br/>Coding]
        G[glm-5.1:cloud<br/>Research]
        GM[gemma4:cloud<br/>Creative]
        FL[gemini-3-flash:cloud<br/>Fast]
    end

    subgraph Tools
        T1[terminal]
        T2[file_read · file_write<br/>file_search]
        T3[web_search · web_fetch]
        T4[code_exec · calculator]
        T5[time · memory<br/>delegation]
    end

    subgraph Persistence["Persistenz"]
        SY[soul.yaml]
        RJ[relations.json]
        LJ[longterm.json]
        SJ[session.json]
    end

    TG --> AG
    CLI --> AG

    AG --> SOUL
    AG --> MEM
    AG --> TOOLS
    AG --> LLM

    LLM --> K
    LLM --> Q
    LLM --> G
    LLM --> GM
    LLM --> FL

    TOOLS --> T1
    TOOLS --> T2
    TOOLS --> T3
    TOOLS --> T4
    TOOLS --> T5

    SOUL --> SY
    SOUL --> RJ
    MEM --> SJ
    MEM --> LJ

    style AG fill:#1a1a2e,stroke:#e94560,color:#fff
    style SOUL fill:#16213e,stroke:#0f3460,color:#fff
    style MEM fill:#16213e,stroke:#0f3460,color:#fff
    style TOOLS fill:#16213e,stroke:#0f3460,color:#fff
    style LLM fill:#16213e,stroke:#e94560,color:#fff
```

### Think-Act Loop

```mermaid
sequenceDiagram
    participant U as Nutzer
    participant I as Interface<br/>(Telegram/CLI)
    participant A as NexusAgent
    participant M as Memory
    participant S as Soul
    participant L as LLMClient
    participant T as Tools

    U->>I: Nachricht
    I->>A: process(message, user_id)
    A->>M: add(user, message)
    A->>S: get_system_prompt() + get_user_context()
    A->>M: get_context(max_tokens)
    A->>L: chat(messages)

    alt LLM gibt Tool-Call
        L-->>A: Response mit <tool>...</tool>
        A->>A: parse_tool_calls()
        loop Für jeden Tool-Call
            A->>T: execute(tool, **args)
            T-->>A: ToolResult
            A->>L: chat(messages + result)
        end
        L-->>A: Finale Text-Antwort
    else LLM gibt direkte Antwort
        L-->>A: Text-Antwort
    end

    A->>M: add(assistant, response)
    A->>S: update_user(user_id, trust_delta=+0.01)
    A-->>I: response
    I-->>U: Nachricht
```

### Memory-Hierarchie

```mermaid
graph TD
    subgraph L1["L1 — Working Memory"]
        direction LR
        L1A[Aktuelle Konversation] --> L1B[Auto-Trim<br/>bei Token-Limit]
        L1B --> L1C[Komprimierung<br/>→ L2]
    end

    subgraph L2["L2 — Session Memory"]
        direction LR
        L2A[Session-Zusammenfassungen] --> L2B[48h TTL<br/>max 50 Einträge]
        L2B --> L2C[Verfall<br/>→ gelöscht]
    end

    subgraph L3["L3 — Long-Term Memory"]
        direction LR
        L3A[Wichtige Fakten] --> L3B[Keyword-Recall<br/>max 200 Einträge]
        L3B --> L3C[Importance-Decay<br/>niedrige = verfallen]
    end

    subgraph L4["L4 — Soul (PERMANENT)"]
        direction LR
        L4A[Persönlichkeit] --> L4B[Beziehungen]
        L4B --> L4C[Kernwissen]
    end

    L1 -->|auto-compress| L2
    L2 -->|important facts| L3
    L3 -->|identity-level| L4

    style L1 fill:#0f3460,stroke:#e94560,color:#fff
    style L2 fill:#16213e,stroke:#533483,color:#fff
    style L3 fill:#1a1a2e,stroke:#0f3460,color:#fff
    style L4 fill:#0a0a0a,stroke:#e94560,color:#e94560
```

### LLM-Fallback-Chain

```mermaid
flowchart TD
    REQ[Anfrage] --> PRIM{Primary Model<br/>kimi-k2.6:cloud}

    PRIM -->|Erfolg| RESP[Antwort an Agent]
    PRIM -->|Fehler| CF1{Cloud Fallback<br/>glm-5.1:cloud}

    CF1 -->|Erfolg| RESP
    CF1 -->|Fehler| CF2{Local Fallback<br/>qwen2.5:3b}

    CF2 -->|Erfolg| RESP
    CF2 -->|Fehler| ERR[Graceful Error<br/>Nutzer benachrichtigen]

    RESP --> AGENT[NexusAgent verarbeitet]

    style PRIM fill:#1a1a2e,stroke:#e94560,color:#fff
    style CF1 fill:#16213e,stroke:#533483,color:#fff
    style CF2 fill:#0f3460,stroke:#0f3460,color:#fff
    style ERR fill:#2a0a0a,stroke:#e94560,color:#e94560
```

### Soul-Komponenten

```mermaid
classDiagram
    class SoulEngine {
        +personality: dict
        +knowledge: dict
        +quirks: list
        +relationships: dict
        +get_system_prompt() str
        +get_user_context(user_id) str
        +update_user(user_id, name, language, trust_delta)
        +learn(category, fact)
        +save()
        +_load()
    }

    class UserRelation {
        +name: str
        +language: str
        +preferences: list
        +conversation_count: int
        +trust_level: float
        +notes: list
    }

    class MemorySystem {
        +l1: list
        +l2: list
        +l3: list
        +add(role, content, importance)
        +get_context(max_tokens) list
        +remember(content, category, importance)
        +recall(query, limit) list
        +end_session()
    }

    class NexusAgent {
        +llm: LLMClient
        +memory: MemorySystem
        +soul: SoulEngine
        +tools: ToolRegistry
        +process(message, user_id) str
        +process_stream(message, user_id) AsyncIterator
        +shutdown()
    }

    NexusAgent --> SoulEngine : uses
    NexusAgent --> MemorySystem : uses
    SoulEngine --> UserRelation : manages
```

## Architektur

```
nexus.py                    Entry Point ─ CLI · Telegram · Self-Test
config.yaml                 Zentrale Konfiguration (LLM · Memory · Tools · Telegram)
requirements.txt            Python-Dependencies

nexus/
  core/
    agent.py                NexusAgent ─ Orchestrator, Think-Act Loop, Tool-Dispatch
    llm_client.py           Ollama Cloud Client ─ Streaming · Fallback-Chain · Retry
    memory.py               L1→L2→L3→L4 Memory ─ Working → Session → Long-Term → Soul
    tools.py                ToolRegistry ─ 11 produktive Werkzeuge, null Stubs
  interfaces/
    telegram_bot.py         Telegram Interface ─ Streaming · Typing-Indicator · Auth
    cli.py                  CLI Interface ─ interaktiver Test-Modus
  soul/
    __init__.py             SoulEngine ─ persistente Identität, Beziehungen, Eigenheiten
    soul.yaml               Persönlichkeits-Definition (Werte, Regeln, Stil)
  memory/                   Runtime-Daten (gitignored · persistent via Docker Volume)
```

## Quick Start

```bash
# 1 — Install
pip install -r requirements.txt

# 2 — Configure
cp .env.example .env
# Edit .env: OLLAMA_API_KEY, NEXUS_TG_TOKEN, NEXUS_TG_USERS

# 3 — Self-Test
python nexus.py --test

# 4 — Run
python nexus.py              # CLI-Modus
python nexus.py --telegram   # Telegram-Bot
```

### Docker

```bash
git clone https://github.com/***REMOVED***/nexus-toti.git && cd nexus-toti
cp .env.example .env         # Api-Keys eintragen
docker compose up nexus-telegram
```

## Soul-Driven Architecture

Toti besitzt eine **Seele** — persistent, adaptiv, einzigartig:

| Schicht | Funktion | Persistenz |
|---|---|---|
| **Persönlichkeit** | Werte, Regeln, Kommunikationsstil | soul.yaml — manuell &
auto |
| **Beziehungen** | Nutzer-Erkennung, Vertrauens-Modell, Präferenzen | relations.json — pro Nutzer |
| **Kernwissen** | Fakten, die über Sessions hinweg bleiben | longterm.json — L3 |
| **Eigenheiten** | Humor, Effizienz-Fokus, Deutsch-first | soul.yaml — wächst mit |

Die Seele ist kein gimmick — sie definiert **wer Toti ist**, nicht was er tut. Session-State wird gelöscht; die Seele bleibt.

## LLM-Routing

| Rolle | Modell | Einsatzgebiet |
|---|---|---|
| **Orchestrator** | `kimi-k2.6:cloud` | Gespräche, Planung, Tool-Dispatch |
| **Coding** | `qwen3-coder-next:cloud` | Code schreiben, debuggen, refactor |
| **Research** | `glm-5.1:cloud` | Recherche, Analyse, Zusammenfassungen |
| **Creative** | `gemma4:cloud` | Kreative Aufgaben, Text-Generation |
| **Fast** | `gemini-3-flash-preview:cloud` | Schnelle Antworten, Monitoring |
| **Fallback Cloud** | `glm-5.1:cloud` | Wenn primary nicht erreichbar |
| **Fallback Local** | `qwen2.5:3b` | Offline-Notbetrieb |

Der Agent entscheidet selbst wann delegiert wird — über das `delegation`-Tool.

## Memory-System

```
L1 ─ Working Memory     Aktuelle Konversation, auto-getrimmt bei Token-Limit
 │
L2 ─ Session Memory     Zusammenfassungen vergangener Sessions, 48h TTL
 │
L3 ─ Long-Term Memory   Wichtige Fakten & Präferenzen, keyword-recall, 200 Einträge
 │
L4 ─ Soul               Identität, Beziehungen, Kernwissen — PERMANENT
```

Jede Schicht hat eigene Limits, Compression- und Eviction-Strategien.  
L1 wird automatisch komprimiert, L3-Einträge decayen nach Wichtigkeit, L4 ist unantastbar.

## Tools

Alle **produktiv implementiert** — keine Platzhalter, keine Stubs:

| Tool | Beschreibung |
|---|---|
| `terminal` | Shell-Befehle ausführen (timeout, workdir) |
| `file_read` | Dateien lesen (offset, limit, Line-Numbers) |
| `file_write` | Dateien erstellen/überschreiben |
| `file_search` | Grep-artige Volltextsuche |
| `web_search` | DuckDuckGo-Suche mit Fallback-Scraper |
| `web_fetch` | URL-Inhalte abrufen und extrahieren |
| `code_exec` | Python-Code in Sandbox ausführen |
| `calculator` | Mathematische Ausdrücke berechnen |
| `time` | Aktuelle Datum/Zeit |
| `delegation` | Aufgabe an Spezialisten-Modell delegieren |
| `memory` | L1→L4 Gedächtnis verwalten (remember/recall/stats) |

Tool-Aufrufe erfolgen über XML-Tags im LLM-Output: `<tool>{"tool": "terminal", "command": "ls"}</tool>`

## Konfiguration

Alle Einstellungen zentral in `config.yaml`:

```yaml
llm:
  mode: cloud                        # cloud | local | hybrid
  default_model: kimi-k2.6:cloud
  stream: true                       # Streaming-Responses

soul:
  enabled: true                      # Persistente Persönlichkeit

memory:
  l1_max_tokens: 8000               # Working Memory Budget
  l2_max_entries: 50                 # Session Summaries
  l3_max_entries: 200                # Long-Term Facts
  auto_compress: true                # L1 automatisch komprimieren

telegram:
  streaming: true                    # Token-by-Token senden
  typing_indicator: true             # "Tippt..." anzeigen
```

Umgebungsvariablen in `.env`: `OLLAMA_API_KEY`, `NEXUS_TG_TOKEN`, `NEXUS_TG_USERS`.

## v5/v6 → v7 Migration

| | v5/v6 | v7 |
|---|---|---|
| **Agenten** | 6 separate, unkoordiniert | 1 Orchestrator + Delegation |
| **LLM** | z-ai CLI (fiktiv) | Ollama Cloud (produktiv) |
| **Tools** | 44+ Stubs | 11 implementierte Werkzeuge |
| **Gedächtnis** | Session-Files, flüchtig | L1→L4 persistent + Soul |
| **Identität** | Statische Config-Prompts | Adaptive Seele mit Beziehungen |
| **Streaming** | Nein | Ja (Token-by-Token) |
| **Codebasis** | 21.000+ Zeilen | ~1.600 Zeilen |
| **Fallback** | Kein | Cloud → Local → Graceful |

## Entwicklung

```
python nexus.py --test     # Self-Test (Imports · Tools · LLM · Soul)
python nexus.py            # CLI-Modus (interaktiv)
python nexus.py --telegram # Telegram-Bot (produktiv)
```

## Lizenz

MIT