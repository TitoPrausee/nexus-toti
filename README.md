<p align="center">
  <img src="https://img.shields.io/badge/version-9.3-blue?style=for-the-badge&labelColor=0a0a0a" alt="Version">
  <img src="https://img.shields.io/badge/python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=0a0a0a" alt="Python">
  <img src="https://img.shields.io/badge/license-GPL--3.0-blue?style=for-the-badge&labelColor=0a0a0a" alt="License">
  <img src="https://img.shields.io/badge/status-production-brightgreen?style=for-the-badge&labelColor=0a0a0a" alt="Status">
</p>

<h1 align="center">NEXUS v9.3</h1>

<p align="center">
  <strong>Autonomer KI-Agent mit Seele, Dual-Layer Memory und Multi-Agent-Delegation.</strong><br>
  GLM-5.2 · Hot Memory · Git-Versioned Cold Memory · 156 Skills
</p>

---

## 🆕 Was ist neu in v9.3

| Feature | Beschreibung |
|---|---|
| **L0 Hot Memory** | ~800 Tokens immer im Kontext — auto-promoted aus L3 (importance ≥ 0.8 oder access_count ≥ 3). Nie wieder wichtige Fakten vergessen. |
| **L3-Git Cold Memory** | Git-versionierte .md-Dateien, on-demand geladen. Mensch-lesbar, diff-bar, versioniert. |
| **Memory Tool erweitert** | `recall` sucht jetzt L3 + Git-Memory. `recall_deep` lädt volle .md-Dateien. `stats` zeigt L0 + Git-Stats. |
| **GLM-5.2:cloud** | Neues Hauptmodell mit 1M Token-Kontext. Research + Analysis beide auf glm-5.2:cloud. |
| **Ollama Direct** | Kein Merge-Proxy mehr — direkte lokale Ollama-Verbindung auf Port 11434, kein API-Key nötig. |
| **Memory-Fix** | l1_max_tokens: 8000→50000, compress_threshold: 0.7→0.9, keep_ratio: 60%→85%. Kein Kontextverlust mehr. |
| **Git im Docker** | git-Paket im Container für Cold Memory Versionierung. |

### v9.2 Features (bleiben erhalten)

| Feature | Beschreibung |
|---|---|
| **Fast Response Layer** | Template-Ack < 100ms + Hybrid fast-Model-Upgrade < 2s. |
| **Response Cache** | Wiederkehrende Fragen < 10ms, kein LLM-Call. |
| **Parallele Agenten** | Komplexe Aufgaben auf N Agenten verteilt (ThreadPoolExecutor). |
| **Agent Profile** | Persistente YAML-Profile mit Performance-Tracking und Auto-Evolution. |
| **Complexity Routing** | Intent → simple/moderate/complex/critical. |

---

## Diagramme

### System-Architektur (v9.2)

```mermaid
graph TB
    subgraph Interfaces
        TG[Telegram Bot<br/>MarkdownV2 · Streaming · Rate-Limit]
        CLI[CLI Interface]
        WEB[Web UI<br/>FastAPI · Invite-Gate]
    end

    subgraph FastResponse["⚡ Fast Response Layer"]
        RC[Response Cache<br/>Q&A Pairs · Fuzzy Match · <10ms]
        QR[QuickResponder<br/>Template-Ack · Hybrid fast-Model]
    end

    subgraph NexusAgent["NEXUS v9.2 — Agent Core"]
        AG[Agent Core<br/>Think-Act Loop · Circular-Chain Detection]
        PR[Pair Router<br/>6-Agent Delegation · Complexity Routing]
        SOUL[SoulEngine<br/>Persönlichkeit · Beziehungen · DSGVO]
        MEM[MemorySystem<br/>L1 · L2 · L3 · L4 · Vector Search]
        TOOLS[ToolRegistry<br/>11 Werkzeuge]
        LLM[LLMClient<br/>Ollama Cloud · Merge Proxy]
        HB[Heartbeat<br/>Process Health · Auto-Restart]
        PT[Project Tracker<br/>Context · Status]
        SM[Session Manager<br/>Per-Chat Isolation · Timeout]
    end

    subgraph AgentTeam["5-Department Team + Parallel"]
        CEO["CEO<br/>glm-5.1:cloud<br/>Priorisierung · Synthese"]
        SC["Research<br/>glm-5.1:cloud<br/>Recherche · Analyse"]
        FG["Engineering<br/>qwen3-coder-next:cloud<br/>Code · Build · Deploy"]
        HD["Creative<br/>gemma4:cloud<br/>Design · Text · UI"]
        OPS["Operations<br/>deepseek-v4-flash:cloud<br/>Schnell · Effizient"]
    end

    subgraph AgentProfiles["📊 Persistente Profile"]
        Y1[ceo.yaml]
        Y2[research.yaml]
        Y3[engineering.yaml]
        Y4[creative.yaml]
        Y5[operations.yaml]
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
        CACHE[response_cache.json]
        DSGVO[dsgvo_config.yaml]
    end

    TG --> SM
    CLI --> SM
    WEB --> SM
    SM --> AG

    AG --> RC
    AG --> QR
    AG --> PR
    AG --> SOUL
    AG --> MEM
    AG --> TOOLS
    AG --> LLM
    AG --> HB
    AG --> PT

    PR --> CEO
    PR --> SC
    PR --> FG
    PR --> HD
    PR --> OPS

    CEO --> Y1
    SC --> Y2
    FG --> Y3
    HD --> Y4
    OPS --> Y5

    TOOLS --> T1
    TOOLS --> T2
    TOOLS --> T3
    TOOLS --> T4
    TOOLS --> T5

    SOUL --> SY
    SOUL --> RJ
    SOUL --> DSGVO
    MEM --> SJ
    MEM --> LJ
    AG --> CACHE

    style AG fill:#1a1a2e,stroke:#e94560,color:#fff
    style PR fill:#2a1a3e,stroke:#e94560,color:#fff
    style QR fill:#0a2a0a,stroke:#4CAF50,color:#fff
    style RC fill:#0a2a0a,stroke:#4CAF50,color:#fff
    style SOUL fill:#16213e,stroke:#0f3460,color:#fff
    style MEM fill:#16213e,stroke:#0f3460,color:#fff
    style TOOLS fill:#16213e,stroke:#0f3460,color:#fff
    style LLM fill:#16213e,stroke:#e94560,color:#fff
    style HB fill:#1a2e1a,stroke:#4CAF50,color:#fff
    style PT fill:#1a2e1a,stroke:#4CAF50,color:#fff
    style SM fill:#2e1a1a,stroke:#FF9800,color:#fff
    style CEO fill:#1a1a2e,stroke:#e94560,color:#fff
    style SC fill:#16213e,stroke:#533483,color:#fff
    style FG fill:#0f3460,stroke:#533483,color:#fff
    style HD fill:#2a1a3e,stroke:#e94560,color:#fff
    style OPS fill:#1a2e1a,stroke:#4CAF50,color:#fff
    style CACHE fill:#0a2a0a,stroke:#4CAF50,color:#4CAF50
```

### Request-Flow (v9.2) — Erste Antwort < 4s

```mermaid
sequenceDiagram
    participant U as Nutzer
    participant TG as Telegram
    participant RC as Response Cache
    participant QR as QuickResponder
    participant PR as Pair Router
    participant AG as NexusAgent
    participant TEAM as Agent Team
    participant LLM as LLMClient

    U->>TG: Nachricht
    TG->>AG: process(message)

    alt Cache Hit (wiederkehrende Frage)
        AG->>RC: lookup(message)
        RC-->>AG: CacheEntry (Hits ≥ 2)
        AG-->>TG: Instant-Antwort (< 10ms)
        TG-->>U: ✅ Antwort
    else Neue Frage
        AG->>RC: lookup(message) → MISS
        AG->>QR: generate_ack(message, routing)
        QR-->>AG: Template-Ack (< 100ms)
        AG-->>TG: "🧠 Analysiere..." (sofort)
        Note over QR,AG: Parallel: fast-Model generiert besseren Ack

        AG->>PR: classify_intent(message)
        PR-->>AG: Intent + Complexity

        alt Trivial (simple)
            PR-->>AG: Direkte Antwort
            AG->>RC: store(message, answer)
            AG-->>TG: Antwort
        else Complex (moderate/complex/critical)
            AG->>TEAM: delegate_parallel(task, complexity)

            alt Parallel (2-4 Agenten)
                TEAM->>LLM: Agent 1 (Research)
                TEAM->>LLM: Agent 2 (Engineering)
                TEAM->>LLM: Agent 3 (Creative)
                LLM-->>TEAM: Erster Agent fertig
                TEAM-->>TG: Zwischenergebnis
                LLM-->>TEAM: Alle Agenten fertig
                TEAM->>TEAM: CEO synthetisiert
            else Single Agent
                TEAM->>LLM: Spezialist-Antwort
            end

            AG->>RC: store(message, final_answer)
            AG-->>TG: Finale Antwort
        end
        TG-->>U: ✅ Antwort
    end
```

### Think-Act Loop (v9.2)

```mermaid
sequenceDiagram
    participant U as Nutzer
    participant I as Interface<br/>(Telegram/CLI/Web)
    participant RC as Response Cache
    participant SM as Session Manager
    participant A as NexusAgent
    participant PR as Pair Router
    participant QR as QuickResponder
    participant M as Memory
    participant S as Soul + DSGVO
    participant L as LLMClient
    participant T as Tools
    participant TEAM as Agent Team
    participant HB as Heartbeat

    U->>I: Nachricht
    I->>SM: get_or_create_session(chat_id)
    SM->>A: process(message, user_id, quick_callback)

    A->>RC: lookup(message)
    alt Cache Hit
        RC-->>A: Cached Answer
        A-->>I: Instant response (< 10ms)
    else Cache Miss
        A->>QR: generate_ack(message, routing)
        QR-->>I: Template-Ack (sofort)
        A->>HB: heartbeat_pulse()
        A->>M: add(user, message)
        A->>S: get_system_prompt() + get_user_context()
        A->>M: get_context(max_tokens) + vector_search()
        A->>PR: route(message, context)
        PR-->>A: Intent + Complexity

        alt LLM gibt Tool-Call
            L-->>A: Response mit <tool>...</tool>
            A->>A: parse_tool_calls() + circular_chain_check()
            loop Für jeden Tool-Call
                A->>T: execute(tool, **args)
                T-->>A: ToolResult
                A->>HB: heartbeat_pulse()
                A->>L: chat(messages + result)
            end
            L-->>A: Finale Text-Antwort
        else LLM delegiert an Team
            A->>TEAM: delegate_parallel(task, complexity)
            TEAM-->>A: Synthetisierte Antwort
        else LLM gibt direkte Antwort
            L-->>A: Text-Antwort
        end

        A->>S: scrub_secrets(response)
        A->>M: add(assistant, response)
        A->>RC: store(message, response, importance)
        A->>S: update_user(user_id, trust_delta=+0.01)
        A-->>I: response (MarkdownV2 formatted)
    end
    I-->>U: Nachricht
```

### Memory-Hierarchie (v9.3)

```mermaid
graph TD
    subgraph L0["L0 — Hot Memory (immer im Kontext)"]
        direction LR
        L0A[Kritische Fakten] --> L0B[~800 Tokens]
        L0B --> L0C[Auto-Promoted<br/>importance ≥ 0.8]
    end

    subgraph L1["L1 — Working Memory"]
        direction LR
        L1A[Aktuelle Konversation] --> L1B[Auto-Trim<br/>bei 90% Token-Limit]
        L1B --> L1C[Komprimierung<br/>→ L2 + L3-Git]
    end

    subgraph L2["L2 — Session Memory"]
        direction LR
        L2A[Session-Zusammenfassungen] --> L2B[7 Tage TTL<br/>max 200 Einträge]
        L2B --> L2C[Verfall<br/>→ gelöscht]
    end

    subgraph L3["L3 — Long-Term Memory"]
        direction LR
        L3A[Wichtige Fakten] --> L3B[Vector + Keyword Recall<br/>max 500 Einträge]
        L3B --> L3C[Importance-Decay<br/>niedrige = verfallen]
    end

    subgraph L3G["L3-Git — Cold Memory (versioniert)"]
        direction LR
        G1[projects/*.md] --> G2[infrastructure/*.md]
        G2 --> G3[learnings/*.md]
        G3 --> G4[sessions/*.md]
    end

    subgraph L4["L4 — Soul (PERMANENT)"]
        direction LR
        L4A[Persönlichkeit] --> L4B[Beziehungen]
        L4B --> L4C[Kernwissen]
    end

    L3 -->|promotion ≥ 0.8| L0
    L1 -->|auto-compress| L2
    L2 -->|important facts| L3
    L3 -->|importance ≥ 0.7| L3G
    L3 -->|identity-level| L4

    style L1 fill:#0f3460,stroke:#e94560,color:#fff
    style L2 fill:#16213e,stroke:#533483,color:#fff
    style L3 fill:#1a1a2e,stroke:#0f3460,color:#fff
    style L4 fill:#0a0a0a,stroke:#e94560,color:#e94560
```

### LLM-Fallback-Chain (Cloud-Only)

```mermaid
flowchart TD
    REQ[Anfrage] --> PRIM{Primary Model<br/>kimi-k2.6:cloud<br/>via Merge Proxy}

    PRIM -->|Erfolg| RESP[Antwort an Agent]
    PRIM -->|Fehler| CF1{Cloud Fallback<br/>deepseek-v4-flash:cloud}

    CF1 -->|Erfolg| RESP
    CF1 -->|Fehler| CF2{Universal Fallback<br/>glm-5.1:cloud}

    CF2 -->|Erfolg| RESP
    CF2 -->|Fehler| ERR[Graceful Error<br/>Nutzer benachrichtigen]

    RESP --> AGENT[NexusAgent verarbeitet]
    RESP --> PAIR[Pair Router → Spezialist]

    style PRIM fill:#1a1a2e,stroke:#e94560,color:#fff
    style CF1 fill:#16213e,stroke:#533483,color:#fff
    style CF2 fill:#0f3460,stroke:#533483,color:#fff
    style ERR fill:#2a0a0a,stroke:#e94560,color:#e94560
    style PAIR fill:#2a1a3e,stroke:#e94560,color:#fff
```

### Agent Profile & Evolution

```mermaid
graph LR
    subgraph Task["Aufgabe"]
        T1[User Message] --> PR[Pair Router]
    end

    PR -->|simple| OPS_OPS[Operations<br/>1 Agent, fast]
    PR -->|moderate| MOD_TEAM[Research +<br/>Engineering<br/>2 Agenten]
    PR -->|complex| COMPLEX_TEAM[Research + Engineering<br/>+ Creative<br/>3 Agenten parallel]
    PR -->|critical| CRIT_TEAM[CEO + Research +<br/>Engineering + Operations<br/>4 Agenten + Synthese]

    subgraph Profiles["Persistente Profile (YAML)"]
        P1[ceo.yaml<br/>Tasks: N ✅ Rate: X%<br/>Ø Zeit: Ys]
        P2[research.yaml<br/>Skills: arxiv, blogwatcher<br/>Evolution: N Insights]
        P3[engineering.yaml<br/>Skills: terminal, code_exec<br/>Performance Tracking]
        P4[creative.yaml<br/>Auto-Evolution<br/>alle 10 Tasks]
        P5[operations.yaml<br/>Fast Model<br/>Quick Responses]
    end

    COMPLEX_TEAM --> SYN[CEO Synthese]
    CRIT_TEAM --> SYN

    subgraph Evolution["Auto-Evolution"]
        EV1[Performance Track<br/>Erfolg ✅ / Fehler ❌]
        EV2[Pattern Detection<br/>Niedrige Rate → Prompt-Verbesserung]
        EV3[LLM-Evolution<br/>/agent evolve → Prompt-Vorschläge]
    end

    Profiles -.->|nach 10 Tasks| Evolution
    Evolution -.->|neue Insights| Profiles

    style PR fill:#2a1a3e,stroke:#e94560,color:#fff
    style OPS_OPS fill:#1a2e1a,stroke:#4CAF50,color:#fff
    style MOD_TEAM fill:#16213e,stroke:#533483,color:#fff
    style COMPLEX_TEAM fill:#0f3460,stroke:#e94560,color:#fff
    style CRIT_TEAM fill:#1a1a2e,stroke:#e94560,color:#fff
    style SYN fill:#2a0a0a,stroke:#FF9800,color:#fff
    style Evolution fill:#0a2a0a,stroke:#4CAF50,color:#fff
```

### Soul-Komponenten

```mermaid
classDiagram
    class SoulEngine {
        +personality: dict
        +knowledge: dict
        +quirks: list
        +relationships: dict
        +security_rules: list
        +get_system_prompt() str
        +get_user_context(user_id) str
        +update_user(user_id, name, language, trust_delta)
        +learn(category, fact)
        +scrub_secrets(text) str
        +save()
        +_load()
    }

    class DSGVOCompliance {
        +config: dict
        +check_response(text) bool
        +anonymize(text) str
        +log_processing(purpose, category)
        +enforce_retention(user_id)
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
        +vector_search(query) list
        +end_session()
    }

    class ResponseCache {
        +entries: list
        +lookup(question) CacheEntry
        +store(question, answer, importance) bool
        +add_manual(question, answer) bool
        +search(query, limit) list
        +stats() dict
    }

    class QuickResponder {
        +llm: LLMClient
        +generate_ack(message, routing) AckResult
        +generate_progress_ack(completed, total) str
        +generate_delegation_ack(dept, task) str
    }

    class AgentProfile {
        +name: str
        +role: str
        +model: str
        +system_prompt: str
        +skills: list
        +performance: PerformanceMetrics
        +evolution: list
    }

    class NexusAgent {
        +llm: LLMClient
        +memory: MemorySystem
        +soul: SoulEngine
        +tools: ToolRegistry
        +pair_router: PairRouter
        +quick_responder: QuickResponder
        +response_cache: ResponseCache
        +team: AgentTeam
        +process(message, user_id, quick_callback) str
        +shutdown()
    }

    NexusAgent --> SoulEngine : uses
    NexusAgent --> MemorySystem : uses
    NexusAgent --> PairRouter : delegates
    NexusAgent --> ResponseCache : caches
    NexusAgent --> QuickResponder : fast ack
    NexusAgent --> AgentTeam : parallel delegation
    SoulEngine --> UserRelation : manages
    SoulEngine --> DSGVOCompliance : enforces
    AgentTeam --> AgentProfile : loads profiles
```

## Architektur

```
nexus.py                    Entry Point ─ CLI · Telegram · Self-Test
config.yaml                 Zentrale Konfiguration (LLM · Memory · Tools · Telegram)
requirements.txt            Python-Dependencies

nexus/
  core/
    agent.py                NexusAgent ─ Orchestrator, Think-Act Loop, Cache, QuickResponder
    agent_team.py            5-Department Team ─ Parallel Delegation, Complexity Classification
    agent_profiles.py        Persistente Profile ─ YAML, Performance, Auto-Evolution
    llm_client.py           Ollama Cloud Client ─ Streaming · Fallback-Chain · Merge Proxy
    pair_router.py           Pair Router ─ Intent + Complexity Classification
    memory.py               L0→L1→L2→L3→L4 Memory ─ Hot → Working → Session → Long-Term → Soul
    hot_memory.py            L0 Hot Memory ─ Always-in-context facts, auto-promoted from L3
    git_memory.py            L3-Git Cold Memory ─ Versioned .md files, on-demand loaded
    config.py               ConfigManager ─ Hot-Reload · mtime-Watcher · SIGHUP
    config_validation.py    Config-Validierung ─ Schema · Defaults · Migration
    session_manager.py      Per-Chat Sessions ─ Isolation · Timeout · Eviction
    heartbeat.py            Process Health ─ Watchdog · Auto-Restart
    project_tracker.py      Project Context ─ Status · Milestones · Progress
    conversations.py        Session Persistence ─ Speichern · Laden · Resumieren
    vector_store.py         Vector Search ─ sentence-transformers · Hybrid-Scoring
    rate_limiter.py         Token-Bucket ─ Per-User · Burst · Auto-Cleanup
    feedback.py              Feedback Loop ─ Self-Improvement · Response Quality
    personalization.py       Adaptive Personalisierung ─ Mood · Style · Preferences
    skill_autocreator.py     Skill-Auto-Erstellung ─ Pattern Detection · Template
    fast_response.py          ⚡ QuickResponder ─ Template-Ack · Hybrid fast-Model (< 4s)
    response_cache.py         ⚡ Response Cache ─ Q&A Pairs · Fuzzy Match · < 10ms
    dsgvo.py                DSGVO Compliance ─ Data Handling · Privacy · Anonymization
  interfaces/
    telegram_bot.py         Telegram Interface ─ MarkdownV2 · Streaming · /agent Command
    markdown_utils.py       MarkdownV2 Formatter ─ Escaping · Splitting · Conversion
    cli.py                  CLI Interface ─ interaktiver Test-Modus
    web_ui.py               Web UI ─ FastAPI · Chat · Invite-Gate · Rate-Limit
  soul/
    __init__.py             SoulEngine ─ persistente Identität, Beziehungen, Eigenheiten, DSGVO
    soul.yaml               Persönlichkeits-Definition (Werte, Regeln, Stil, Security)
  memory/                   Runtime-Daten (gitignored · persistent via Docker Volume)

data/
  agents/                   ⚡ Persistente Agent-Profile (YAML)
    ceo.yaml                CEO ─ Orchestrierung, Synthese
    research.yaml           Research ─ Recherche, Analyse
    engineering.yaml        Engineering ─ Code, Build, Deploy
    creative.yaml           Creative ─ Design, Text, UI
    operations.yaml        Operations ─ Schnell, Effizient
  skills/                   156 Skills in 22 Kategorien
```

## Quick Start

### Einzeilen-Installation (empfohlen)

```bash
curl -fsSL https://raw.githubusercontent.com/***REMOVED***/nexus-toti/main/install.sh | bash
```

Oder nicht-interaktiv mit Telegram-Token:

```bash
curl -fsSL https://raw.githubusercontent.com/***REMOVED***/nexus-toti/main/install.sh | bash -s -- --token 123456:ABC-DEF --chat-id ***REMOVED***
```

Deinstallation:

```bash
curl -fsSL https://raw.githubusercontent.com/***REMOVED***/nexus-toti/main/install.sh | bash -s -- --uninstall
```

### Docker (manuell)

```bash
git clone https://github.com/***REMOVED***/nexus-toti.git && cd nexus-toti
cp .env.example .env         # Api-Keys eintragen
docker compose up -d nexus-telegram
```

### Lokale Installation (ohne Docker)

```bash
pip install -r requirements.txt
cp .env.example .env         # Api-Keys eintragen
python nexus.py --test       # Self-Test
python nexus.py --telegram   # Telegram-Bot starten
```

## Soul-Driven Architecture

Toti besitzt eine **Seele** — persistent, adaptiv, einzigartig:

| Schicht | Funktion | Persistenz |
|---|---|---|
| **Persönlichkeit** | Werte, Regeln, Kommunikationsstil | soul.yaml — manuell & auto |
| **Beziehungen** | Nutzer-Erkennung, Vertrauens-Modell, Präferenzen | relations.json — pro Nutzer |
| **Kernwissen** | Fakten, die über Sessions hinweg bleiben | longterm.json — L3 |
| **Eigenheiten** | Humor, Effizienz-Fokus, Deutsch-first | soul.yaml — wächst mit |

Die Seele ist kein gimmick — sie definiert **wer Toti ist**, nicht was er tut. Session-State wird gelöscht; die Seele bleibt.

## 5-Department Team (v9.3)

| Department | Modell | Rolle | Parallel | Profile |
|---|---|---|---|---|
| **CEO** | `glm-5.2:cloud` | Priorisierung, Delegation, Synthese | ✅ Synthese | `data/agents/ceo.yaml` |
| **Research** | `glm-5.2:cloud` | Recherche, Analyse, Fakten | ✅ Parallel | `data/agents/research.yaml` |
| **Engineering** | `qwen3-coder-next:cloud` | Code, Build, Deploy | ✅ Parallel | `data/agents/engineering.yaml` |
| **Creative** | `gemma4:cloud` | Design, Text, UI/UX | ✅ Parallel | `data/agents/creative.yaml` |
| **Operations** | `deepseek-v4-flash:cloud` | Planung, Monitoring, Schnelles | ✅ Parallel | `data/agents/operations.yaml` |

| Fallback | Modell | Einsatzgebiet |
|---|---|---|
| **Cloud Fallback 1** | `deepseek-v4-flash:cloud` | Schneller Fallback bei Primärmodell-Ausfall |
| **Cloud Fallback 2** | `glm-5.2:cloud` | Universeller Fallback |

### Complexity Routing

| Level | Agenten | Modelle | Synthese | Beispiel |
|---|---|---|---|---|
| **simple** | 1 | fast | Nein | "Wie spät ist es?" |
| **moderate** | 1-2 | default + specialist | Nein | "Erkläre mir Docker" |
| **complex** | 2-4 | research + engineering + creative | ✅ CEO | "Baue mir eine API mit Tests" |
| **critical** | 3-4 | CEO + research + engineering + ops | ✅ CEO | "Produktions-Deployment überprüfen" |

### `/agent` Telegram-Commands

| Command | Beschreibung |
|---|---|
| `/agent` | Alle Agenten auflisten (mit Stats) |
| `/agent create <name> <rolle>` | Neuen Agenten erstellen |
| `/agent assign <name> <skill>` | Skill einem Agenten zuweisen |
| `/agent stats <name>` | Performance-Statistiken |
| `/agent evolve <name>` | LLM-basierte Auto-Evolution triggern |

## Fast Response Layer

```
Nutzer-Nachricht
    │
    ├─ Response Cache Check (< 10ms, bei Hit: sofortige Antwort)
    ├─ Router klassifiziert Intent + Complexity
    ├─ QuickResponder: Template-Ack SOFORT (< 100ms)
    ├─ Parallel: fast-Model generiert besseren Ack → editiert Nachricht
    │
    ├─ Simple? → Einzelner Agent, Ergebnis senden
    │
    └─ Complex/Critical? → delegate_parallel()
           ├─ Agent 1 (Research)    ──┐
           ├─ Agent 2 (Engineering) ──┤ ThreadPoolExecutor
           └─ Agent 3 (Creative)    ──┘
           Erster fertig → Zwischenergebnis
           Alle fertig → CEO synthetisiert → Finale Antwort
```

## Memory-System

```
L0 ─ Hot Memory         Immer im Kontext (~800 Tokens), auto-promoted aus L3
 │
L1 ─ Working Memory     Aktuelle Konversation, auto-getrimmt bei 90% Token-Limit
 │
L2 ─ Session Memory     Zusammenfassungen vergangener Sessions, 7 Tage TTL
 │
L3 ─ Long-Term Memory   Wichtige Fakten & Präferenzen, vector+keyword recall, 500 Einträge
 │
L3-Git ─ Cold Memory    Versionierte .md-Dateien, on-demand geladen, git-versioniert
 │
L4 ─ Soul               Identität, Beziehungen, Kernwissen — PERMANENT
```

**L0 Hot Memory** ist der Schlüssel-Unterschied zu v9.2: Die wichtigsten Fakten (importance ≥ 0.8 oder access_count ≥ 3) sind **immer** im System-Prompt, ohne dass der Agent sie erst suchen muss. Nie wieder "ich erinnere mich nicht" bei kritischen Infos.

**L3-Git Cold Memory** speichert Details on-demand in versionierten .md-Dateien. Nur wenn der Agent etwas tiefgreifendes braucht, lädt er die entsprechende Datei. Spart Tokens und ist trotzdem vollständig verfügbar.

Promotion/Demotion: L3 → L0 (auto bei Wichtigkeit/Häufigkeit), L0 → L3 (auto bei Veraltung), L3 → L3-Git (auto bei importance ≥ 0.7).

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
| `delegation` | Aufgabe an Team-Abteilung delegieren (single/parallel/full_team) |
| `memory` | L0→L4 Gedächtnis verwalten (remember/recall/recall_deep/stats) |

Tool-Aufrufe erfolgen über XML-Tags im LLM-Output: `<tool>{"tool": "terminal", "command": "ls"}</tool>`

## Skills

Toti verfügt über **156 Skills** in 22 Kategorien — von DevOps über Creative bis Red Teaming.

```mermaid
graph TB
    Nexus((NEXUS v9.2<br/>156 Skills))
    devops["🔧 DevOps<br/>33 Skills"]
    Nexus --> devops
    softdev["💻 Software Dev<br/>31 Skills"]
    Nexus --> softdev
    creative["🎨 Creative<br/>17 Skills"]
    Nexus --> creative
    prod["📄 Productivity<br/>14 Skills"]
    Nexus --> prod
    mlops["🧪 MLOps<br/>13 Skills"]
    Nexus --> mlops
    github["🐙 GitHub<br/>8 Skills"]
    Nexus --> github
    agents["🤖 Autonomous Agents<br/>7 Skills"]
    Nexus --> agents
    apple["🍎 Apple<br/>6 Skills"]
    Nexus --> apple
    research["🔬 Research<br/>5 Skills"]
    Nexus --> research
    media["🎬 Media<br/>4 Skills"]
    Nexus --> media
    mcp["🔌 MCP<br/>3 Skills"]
    Nexus --> mcp
    gaming["🎮 Gaming<br/>3 Skills"]
    Nexus --> gaming
    smarthome["🏠 Smart Home<br/>2 Skills"]
    Nexus --> smarthome
    redteam["🔒 Red Teaming<br/>2 Skills"]
    Nexus --> redteam
    workflow["🔍 Workflow<br/>1 Skill"]
    Nexus --> workflow
    other["📦 7 more<br/>7 Skills"]
    Nexus --> other

    style Nexus fill:#1a1a2e,stroke:#e94560,color:#fff
    style devops fill:#16213e,stroke:#533483,color:#fff
    style softdev fill:#16213e,stroke:#533483,color:#fff
    style creative fill:#2a1a3e,stroke:#e94560,color:#fff
    style mlops fill:#1a2e1a,stroke:#4CAF50,color:#fff
    style agents fill:#0f3460,stroke:#533483,color:#fff
```

👉 **Vollständige Skill-Dokumentation mit Workflow-Diagrammen:** [data/skills/SKILLS.md](data/skills/SKILLS.md)

## Konfiguration

Alle Einstellungen zentral in `config.yaml`:

```yaml
llm:
  mode: cloud                        # cloud ONLY — direkt über lokales Ollama
  default_model: glm-5.2:cloud       # 1M Token-Kontext
  stream: true                       # Streaming-Responses

  # 5-Department Delegation via Pair Router
  models:
    coding: "qwen3-coder-next:cloud"
    research: "glm-5.2:cloud"
    analysis: "glm-5.2:cloud"
    creative: "gemma4:cloud"
    fast: "deepseek-v4-flash:cloud"

  # Cloud-only Fallback (direkt, kein Merge-Proxy)
  fallback: ["deepseek-v4-flash:cloud", "glm-5.2:cloud"]

soul:
  enabled: true                      # Persistente Persönlichkeit + DSGVO

memory:
  # v9.3: Memory-Fix + Dual-Layer
  l1_max_tokens: 50000              # GLM-5.2 hat 1M Kontext
  l2_max_entries: 200                 # 7 Tage Historie
  l2_max_age_hours: 168
  l3_max_entries: 500
  auto_compress: true
  compress_threshold: 0.9             # erst bei 90% komprimieren
  # L0 Hot Memory (immer im Kontext)
  hot_max_tokens: 1000               # ~800 Tokens soft limit
  hot_max_facts: 10
  hot_promotion_importance: 0.8      # auto-promote bei importance >= 0.8
  hot_promotion_access_count: 3      # oder access_count >= 3
  # L3-Git Cold Memory (versioniert, on-demand)
  git_enabled: true                  # git versioning
  git_remote: ""                     # leer = lokal nur
  git_sync_interval_seconds: 3600    # stündlicher sync
  vector_search:
    enabled: true                    # Semantische Suche in L3
fast_response:
  enabled: true
  hybrid_ack_timeout: 2.0           # Sekunden für Hybrid-Ack-Upgrade

# ⚡ Response Cache (v9.2)
response_cache:
  max_cache_size: 500                # Max gecachte Q&A-Paare
  cache_ttl: 604800                  # 7 Tage
  similarity_threshold: 0.85         # Fuzzy-Match Schwelle

session_manager:
  timeout_seconds: 3600              # 1h Session-Timeout
  max_sessions: 50                    # Max parallele Sessions

telegram:
  streaming: true                    # Token-by-Token senden
  typing_indicator: true             # "Tippt..." anzeigen
  parse_mode: "MarkdownV2"          # Rich Formatting
  rate_limiter:
    rate: 0.33                       # 1 Nachricht / 3s
    burst: 5                          # Max Burst

heartbeat:
  enabled: true                      # Process Health Monitoring
  interval: 60                        # Check alle 60s
```

Umgebungsvariablen in `.env`: `OLLAMA_API_KEY`, `NEXUS_TG_TOKEN`, `NEXUS_TG_USERS`.

## v9.1 → v9.2 Migration

| | v9.1 | v9.2 |
|---|---|---|
| **Erste Antwort** | Warte auf Worker (2-10s) | Template-Ack < 100ms + Cache < 10ms |
| **Agenten** | Sequentielle Delegation | Parallel (ThreadPoolExecutor, N Agenten) |
| **Routing** | Intent nur (trivial/complex) | Intent + Complexity (simple/moderate/complex/critical) |
| **Agent-Profile** | Hardcoded DEPARTMENTS | Persistente YAML-Profile mit Performance-Tracking |
| **Auto-Evolution** | Nein | Pattern-basiert (alle 10 Tasks) + LLM-basiert (`/agent evolve`) |
| **Response Cache** | Nein | Q&A-Cache mit Fuzzy-Match für wiederkehrende Fragen |
| **Telegram Commands** | /start, /status, /team, /einstellungen | + `/agent` (create, assign, stats, evolve) |

## Entwicklung

```
python nexus.py --test     # Self-Test (Imports · Tools · LLM · Soul · Cache)
python nexus.py            # CLI-Modus (interaktiv)
python nexus.py --telegram # Telegram-Bot (produktiv)
```

## Lizenz

GNU General Public License v3.0 (GPL-3.0)

Freie Nutzung, Modifikation und Verbreitung erlaubt — auch kommerziell.
**Aber:** Derivate müssen unter derselben Lizenz veröffentlicht werden (Copyleft).
Das verhindert Code-Klau: wer Nexus nutzt und verbessert, muss die Verbesserungen offenlegen.

Siehe [LICENSE](LICENSE) für den vollständigen Lizenztext.