# NEXUS v6.0 — Autonomous Multi-Agent Framework

> **44+ Tools · 20+ Skills via Skill Hub · 6 Agents mit per-agent LLM-Routing · Fehlerklassifikation · Secret Redaction · Activity Feedback · Rate Limit Tracking · Iteration Budget**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Version](https://img.shields.io/badge/Version-6.0-blueviolet.svg)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Ollama](https://img.shields.io/badge/Ollama-Cloud%20%7C%20Local-green.svg)](https://ollama.ai)

---

**🇩🇪 NEXUS ist ein autonomes Multi-Agenten-Framework.** Es koordiniert ein Team spezialisierter KI-Agenten, die selbstständig denken, delegieren, Code ausführen und Probleme lösen — mit nur einem Ziel: komplexe Aufgaben vollständig autonom zu erledigen. Per-agent LLM-Routing, intelligentes Fehlermanagement (Error Classifier mit 20+ Fehlertypen) und ein lebendiges Activity-Feedback-System machen NEXUS zu einem der fortschrittlichsten Open-Source-Frameworks für KI-Agenten-Orchestrierung.

---

## Table of Contents

- [What is NEXUS?](#what-is-nexus)
- [Architecture](#architecture)
- [Agent Team](#agent-team)
- [Key Features v6.0](#key-features-v60)
- [Phase 1 — Security](#phase-1--security)
- [Phase 2 — Performance](#phase-2--performance)
- [Phase 3 — UX](#phase-3--ux)
- [Phase 4 — Advanced](#phase-4--advanced)
- [Phase 5 — Activity Feedback](#phase-5--activity-feedback)
- [Skill Hub](#skill-hub)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Commands](#commands)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## What is NEXUS?

NEXUS is an **autonomous multi-agent system** built around **Toti** (NEXUS-0) — a primary agent that thinks, delegates, learns, and acts autonomously. Unlike typical chatbot wrappers, NEXUS runs shell commands, writes and executes code, manages Docker containers, queries databases, and coordinates specialized sub-agents to tackle complex multi-step tasks.

**Core philosophy:** *Act first, report after.* No confirmation loops for routine operations.

### What's New in v6.0

| Area | Feature | Description |
|------|---------|-------------|
| 🔒 **Security** | Error Classifier | 20+ error types with FailoverReason taxonomy |
| 🔒 **Security** | Secret Redaction | API keys, tokens, passwords — 15+ regex patterns |
| 🔒 **Security** | File Safety | Protected paths, denied filenames |
| ⚡ **Performance** | Context References | `@file:path`, `@url:url` syntax |
| ⚡ **Performance** | Rate Limit Tracker | Per-model `x-ratelimit-*` header parsing |
| ⚡ **Performance** | Iteration Budget | Per-turn and per-conversation limits |
| 🎨 **UX** | Think Scrubber | Strips 6 thinking block types from output |
| 🎨 **UX** | Title Generator | German/English pattern matching |
| 🎨 **UX** | Message Sanitization | Telegram, history, and logging-safe output |
| 🧠 **Advanced** | Skill Bundles | coding, research, devops, creative, monitoring, full |
| 🧠 **Advanced** | Credential Pool | Key rotation, health scoring, failover |
| 🧠 **Advanced** | Skill Hub | 10 built-in + 10 downloadable skills, 5 categories |
| 💬 **Activity** | Activity Feedback | 19 thinking, 10 working, 8 progress messages (German) |
| 💬 **Activity** | Streaming Feedback | Periodic updates during long operations |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERFACES                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  CLI (Rich)  │  │  Telegram    │  │  --task Single-Shot │  │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                │                      │              │
└─────────┼────────────────┼──────────────────────┼──────────────┘
          │                │                      │
          ▼                ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    NEXUS-0 / TOTI (kimi-k2.6:cloud)              │
│                                                                  │
│  ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────────┐ │
│  │  Routing  │ │ Guards   │ │ Delegation│ │ Error Classifier │ │
│  │   Engine  │ │ Loop/Step│ │   Engine  │ │  FailoverReason  │ │
│  └───────────┘ └──────────┘ └───────────┘ └──────────────────┘ │
│  ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────────┐ │
│  │  Tool     │ │  Skill   │ │  Memory   │ │   Activity       │ │
│  │  Registry │ │  Hub     │ │  L1/L2/L3 │ │   Feedback       │ │
│  └───────────┘ └──────────┘ └───────────┘ └──────────────────┘ │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┬──────────────────┐
          ▼                ▼                ▼                  ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│    SCOUT     │ │    FORGE     │ │    LENS      │ │     HERALD       │
│  glm-5.1:cloud│ │qwen3-coder:cloud│ │kimi-k2.6:cloud│ │minimax-m2.7:cloud│
│  Research    │ │  Coding/Dev  │ │  Analysis    │ │   Output/Docs    │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │     GHOST        │
                  │deepseek-v4:cloud │
                  │ Background/Monitor│
                  └──────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     LLM BACKEND STACK                            │
│  ┌────────────────┐    ┌──────────────┐    ┌───────────────┐   │
│  │ ◉ Ollama Cloud │───▶│  Local Ollama │───▶│  z-ai CLI    │   │
│  │ api.ollama.ai  │    │ localhost:11434│   │  GLM Fallback │   │
│  └────────────────┘    └──────────────┘    └───────────────┘   │
│           Auto-detected · Auto-fallback · Per-agent model routing│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    SECURITY · PERFORMANCE · UX                   │
│  ┌────────────┐ ┌──────────────┐ ┌────────────┐ ┌────────────┐ │
│  │   Redact   │ │File Safety   │ │Rate Limit  │ │Iteration   │ │
│  │ 15 patterns│ │Protected Paths│ │Tracker     │ │Budget      │ │
│  └────────────┘ └──────────────┘ └────────────┘ └────────────┘ │
│  ┌────────────┐ ┌──────────────┐ ┌────────────┐ ┌────────────┐ │
│  │Think       │ │Title Gen     │ │Sanitization│ │Credential  │ │
│  │Scrubber    │ │DE/EN Patterns│ │3 modes     │ │Pool        │ │
│  └────────────┘ └──────────────┘ └────────────┘ └────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Team

NEXUS v6.0 coordinates **6 specialized agents**, each running on the LLM best suited for its role.

| Agent | Model | Role | Temperature | Max Tokens |
|-------|-------|------|-------------|------------|
| **NEXUS-0 / Toti** | `kimi-k2.6:cloud` | Orchestration, decision-making, tool dispatch | 0.7 | 4096 |
| **SCOUT** | `glm-5.1:cloud` | Web research, data extraction, fact-finding | 0.5 | 8192 |
| **FORGE** | `qwen3-coder-next:cloud` | Code generation, debugging, deployment | 0.3 | 8192 |
| **LENS** | `kimi-k2.6:cloud` | Code review, security analysis, profiling | 0.4 | 4096 |
| **HERALD** | `minimax-m2.7:cloud` | Documentation, formatting, structured output | 0.6 | 4096 |
| **GHOST** | `deepseek-v4-flash:cloud` | Background monitoring, state persistence | 0.3 | 2048 |

Each agent routes to its configured model automatically. If a model becomes unavailable, NEXUS falls back through the stack: Cloud → Local → z-ai CLI.

---

## Key Features v6.0

### Phase 1 — Security

#### 🔒 Error Classifier (`error_classifier.py`)
A sophisticated error classification system with a **FailoverReason taxonomy** covering 20+ error types:

| Error Type | Description |
|------------|-------------|
| `TOOL_NOT_FOUND` | Referenced tool doesn't exist in registry |
| `TOOL_EXECUTION_FAILED` | Tool returned non-zero or exception |
| `TOOL_TIMEOUT` | Tool call exceeded time limit |
| `AGENT_BUSY` | Target agent is already processing |
| `AGENT_NOT_FOUND` | Referenced agent ID not registered |
| `AGENT_OVERRIDE_REJECTED` | Agent refused the task |
| `LLM_CONNECTION_ERROR` | Cannot reach LLM backend |
| `LLM_RATE_LIMITED` | Rate limit exceeded |
| `LLM_INVALID_RESPONSE` | Response failed parsing |
| `LLM_TIMEOUT` | LLM call timed out |
| `CONTEXT_LIMIT_EXCEEDED` | Token budget exhausted |
| `PARSE_ERROR` | Output parsing failure |
| `VALIDATION_ERROR` | Validation check failed |
| `PERMISSION_ERROR` | Operation not permitted |
| `LOOP_DETECTED` | Agent entered infinite loop |
| `DEPENDENCY_FAILED` | Subtask dependency failed |
| `RESOURCE_EXHAUSTED` | System resource limit hit |
| `UNKNOWN_ERROR` | Unclassified failure |

**Failover behavior:** Each error type triggers automatic recovery — retry with backoff, agent reassignment, or graceful degradation.

#### 🔒 Secret Redaction (`redact.py`)
Automatic detection and redaction of sensitive information in all outputs:
- API keys (OpenAI, Anthropic, Google, AWS, GitHub, etc.)
- Bearer tokens, JWT tokens
- Passwords, connection strings
- Private SSH keys
- 15+ regex patterns total
- Configurable **redaction modes**: `mask` (shows prefix), `full` (completely hidden), `off`

#### 🔒 File Safety (`file_safety.py`)
Protection against dangerous file operations:
- **Protected paths** — system directories never modified (e.g., `/etc`, `/sys`, `/proc`)
- **Denied filenames** — dangerous names blocked (e.g., `*.key`, `*.pem` in certain contexts)
- **Path traversal detection** — blocks `../` escape attempts
- **Extension whitelist** — only safe file types for write operations

---

### Phase 2 — Performance

#### ⚡ Context References (`context_references.py`)
Enables agents to reference files and URLs inline:
- `@file:path/to/file.txt` — reads file content into context
- `@url:https://example.com/data` — fetches URL content into context
- Recursive resolution (nested references)
- Auto-caching with TTL

#### ⚡ Rate Limit Tracker (`rate_limit_tracker.py`)
Intelligent rate limit monitoring per model:
- Parses `x-ratelimit-*` headers from Ollama Cloud responses
- Tracks remaining, limit, and reset time per model
- **Auto-pause** when approaching limits
- **Request smoothing** — distributes calls to avoid bursts
- Per-agent-model granularity

#### ⚡ Iteration Budget (`iteration_budget.py`)
Controls computational resource usage:
- **Per-turn budget** — max tool calls or LLM rounds per user request
- **Per-conversation budget** — cumulative limit across a session
- **Budget exhaustion modes**: `warn` (continue with warning), `summarize` (compress and continue), `stop` (halt gracefully)
- Rolling window tracking

---

### Phase 3 — UX

#### 🎨 Think Scrubber (`think_scrubber.py`)
Strips internal thinking/scratchpad blocks from agent output:
- 6 block types removed: ````think`, ````thinking`, ````scratchpad`, ````internal`, ````reasoning`, ````plan`
- Also strips inline markers like `[thinking]`, `[internal]`
- Clean, user-ready output every time

#### 🎨 Title Generator (`title_generator.py`)
Intelligent conversation and task titling:
- **German pattern matching** — `"Erstelle eine Webseite"` → `"Webseite erstellen"`
- **English pattern matching** — `"Create a React app"` → `"Create React app"`
- Extracts key nouns and verbs for meaningful titles
- Used for session naming, history labels, and log entries

#### 🎨 Message Sanitization (`message_sanitization.py`)
Multi-mode output cleaning:
- **Telegram mode** — removes unsupported markdown, truncates long messages, escapes special chars
- **History mode** — filters sensitive data for persistent storage
- **Logging mode** — strip newlines, truncate for log lines
- Configurable per interface

---

### Phase 4 — Advanced

#### 🧠 Skill Bundles (`skill_bundles.py`)
Pre-configured skill collections for different use cases:

| Bundle | Skills Included |
|--------|----------------|
| `coding` | code_debug, code_review, test_gen, dependency_check |
| `research` | web_research, data_extract, doc_gen |
| `devops` | deploy_prep, dependency_check, security_scan |
| `creative` | doc_gen, data_extract, web_research |
| `monitoring` | performance, dependency_check, security_scan |
| `full` | All available skills |

#### 🧠 Credential Pool (`credential_pool.py`)
Enterprise-grade API key management:
- **Multiple keys per service** with automatic rotation
- **Health scoring** — tracks success/failure per key
- **Failover** — degraded keys are deprioritized; dead keys are quarantined
- **Pool lifecycle** — initialize → select → use → report → rotate
- Supports `OLLAMA_API_KEY` primary + pool fallback

#### 🧠 Skill Hub (`skill_hub.py`)
A dynamic skill marketplace — the crown jewel of v6.0:

**10 Built-in Skills:**

| Skill | Category | Description |
|-------|----------|-------------|
| `web_research` | Research | Deep web research with source triangulation |
| `code_debug` | Coding | Root-cause error analysis and fix |
| `code_review` | Coding | Structured code review with quality verdict |
| `security_scan` | DevOps | Code and dependency vulnerability scanning |
| `data_extract` | Analysis | Process data from CSV, JSON, APIs, databases |
| `test_gen` | Coding | Auto-generate unit tests (Python/JS) |
| `doc_gen` | Creative | Generate README, API docs, CHANGELOG |
| `deploy_prep` | DevOps | Validate Docker, K8s, VPS deployments |
| `dependency_check` | DevOps | Updates, conflicts, security for dependencies |
| `performance` | Analysis | Profile and optimize code performance |

**10 Hub-Downloadable Skills:**
Skills can be fetched from a remote hub registry at runtime, expanding NEXUS's capabilities without code changes.

**Categories:**
- `coding` — Code generation, debugging, testing
- `research` — Web search, data extraction, fact-finding
- `devops` — Deployment, security, infrastructure
- `creative` — Documentation, content generation
- `analysis` — Data analysis, performance profiling

---

### Phase 5 — Activity Feedback

#### 💬 Activity Feedback System (`activity_feedback.py`)
NEXUS v6.0 feels **alive** — with a rich library of German-language status messages that update in real-time:

**19 Thinking Messages** — displayed during LLM reasoning:
> *"Ich denke nach…", "Analysiere die Anfrage…", "Verarbeite Informationen…", "Strukturierte Überlegungen…"*

**10 Working Messages** — shown during tool execution:
> *"Ich arbeite daran…", "Führe Aufgabe aus…", "Prozess läuft…", "In Bearbeitung…"*

**8 Progress Messages** — periodic updates during long operations:
> *"Das dauert einen Moment…", "Fast fertig…", "Noch ein kleiner Schritt…", "Gleich geschafft…"*

#### 📡 Streaming Feedback
Periodic status updates during long-running operations:
- Every N seconds during tool calls
- Rotates through the message pools
- Context-aware: shows thinking vs. working vs. progress
- Makes multi-minute operations feel responsive

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Ollama** ([install guide](https://ollama.ai)) — for local mode
- Or an **Ollama Cloud API key** — for cloud mode

### Local Setup

```bash
# Clone the repository
git clone https://github.com/***REMOVED***/nexus-toti.git
cd nexus-toti

# Install core dependencies
pip install rich pyyaml

# Optional: Telegram support
pip install python-telegram-bot

# Pull a local model
ollama pull qwen2.5:3b

# Start NEXUS
python nexus.py
```

### Cloud Setup (Recommended)

```bash
# Option A: Environment variable
export OLLAMA_API_KEY="your-key-here"
python nexus.py

# Option B: Setup wizard
python nexus.py --setup

# Option C: Edit config.yaml directly
# ollama.api_key: "your-key-here"
```

### Docker

```bash
cp .env.example .env  # edit as needed

# Interactive CLI
docker compose run --rm nexus

# Telegram bot (background daemon)
docker compose --profile telegram up nexus-telegram -d

# Single task
docker compose run --rm nexus --task "List all Python files in /app"
```

### First Commands

```bash
python nexus.py                          # Interactive CLI
python nexus.py --task "Analyze this repo"  # Single task
python nexus.py --telegram               # Telegram bot
python nexus.py --health                 # Health check
python nexus.py --models                 # Show model routing
python nexus.py --session abc123         # Resume session
```

---

## Configuration

All configuration lives in **`config.yaml`** at the project root. Key sections:

```yaml
ollama:
  base_url: "https://api.ollama.ai"
  local_url: "http://localhost:11434"
  api_key: ""                     # or OLLAMA_API_KEY env var
  mode: "cloud"                   # cloud | local | hybrid
  agent_models:
    NEXUS-0:                      # Per-agent model routing
      model: "kimi-k2.6:cloud"
      temperature: 0.7
      max_tokens: 4096

guards:
  max_steps: 10
  budget_limit_pct: 90.0
  loop_detection_window: 3

redact:
  mode: "mask"                    # mask | full | off
  patterns: ["api_key", "token", "password", "ssh_key"]

rate_limits:
  enabled: true
  auto_pause: true
  smoothing: true

iteration_budget:
  per_turn: 20
  per_conversation: 200
  exhaustion_mode: "summarize"    # warn | summarize | stop

skill_hub:
  categories: [coding, research, devops, creative, analysis]
  auto_install: false

activity_feedback:
  enabled: true
  language: "de"                  # German feedback messages
  interval_seconds: 5             # Streaming feedback interval
```

For the full configuration reference, see `config.yaml` in the repository.

---

## Commands

| Command | Description |
|---------|-------------|
| `/status` | System status: guards, budget, LLM calls, agents, scheduler |
| `/health` | Run LLM health check for all configured models |
| `/memory` | Memory overview: L1 session, L2 skills, L3 long-term |
| `/state` | Raw state JSON |
| `/errors` | Error Classifier stats: known errors, recent failures, avoidance count |
| `/tools` | All 44+ tools listed by category |
| `/skills` | All skills with descriptions (Skill Hub) |
| `/bundles` | Available skill bundles |
| `/reset` | Clear session memory and state |
| `/evolve` | GEPA self-improvement: analyze session, generate proposals |
| `/help` | Show all commands |

---

## Project Structure

```
nexus-toti/
│
├── nexus.py                  # Entry point
├── config.yaml               # Configuration
├── requirements.txt
│
├── agents/
│   ├── toti.py               # NEXUS-0: Primary orchestrator
│   ├── scout.py              # Research agent
│   ├── forge.py              # Coding agent
│   ├── lens.py               # Analysis agent
│   ├── herald.py             # Output / docs agent
│   └── ghost.py              # Background / monitoring agent
│
├── core/
│   ├── agent_base.py         # Agent base class
│   ├── llm_client.py         # Multi-backend LLM client
│   ├── memory.py             # L1/L2/L3 memory system
│   ├── tools.py              # Tool registry (44+ tools)
│   ├── delegation.py         # DAG task decomposition
│   ├── error_learning.py     # Base error learning
│   ├── guards.py             # Loop/step/budget guards
│   ├── scheduler.py          # Smart scheduler
│   ├── state.py              # Persistent state
│   │
│   ├── error_classifier.py   # v6.0: 20+ error types, FailoverReason
│   ├── redact.py             # v6.0: Secret redaction (15+ patterns)
│   ├── file_safety.py        # v6.0: Protected paths, denied files
│   ├── context_references.py # v6.0: @file, @url references
│   ├── rate_limit_tracker.py # v6.0: x-ratelimit-* per model
│   ├── iteration_budget.py   # v6.0: Per-turn/conversation budget
│   ├── think_scrubber.py     # v6.0: Strip 6 thinking block types
│   ├── title_generator.py    # v6.0: DE/EN title generation
│   ├── message_sanitization.py # v6.0: 3-mode sanitization
│   ├── skill_bundles.py      # v6.0: 6 pre-configured bundles
│   ├── credential_pool.py    # v6.0: Key rotation, health scoring
│   ├── skill_hub.py          # v6.0: Dynamic skill marketplace
│   └── activity_feedback.py  # v6.0: German feedback messages
│
├── interfaces/
│   ├── cli.py                # Rich terminal CLI
│   └── telegram_bot.py       # Telegram bot
│
├── prompts/                  # Agent system prompts
│
├── skills/                   # 10+ skill modules
│
├── memory/                   # Persistent memory storage
│
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Skill Hub Categories

| Category | Skills | Description |
|----------|--------|-------------|
| 🔧 **coding** | `code_debug`, `code_review`, `test_gen`, `dependency_check` | Code analysis, testing, debugging |
| 🔬 **research** | `web_research`, `data_extract`, `doc_gen` | Information gathering & processing |
| 🚀 **devops** | `deploy_prep`, `dependency_check`, `security_scan` | Infrastructure & deployment |
| 🎨 **creative** | `doc_gen`, `data_extract`, `web_research` | Content & documentation |
| 📊 **analysis** | `data_extract`, `performance`, `code_review` | Data & performance analysis |

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push and open a Pull Request

**Extension Points:**

| What | Where | How |
|------|-------|-----|
| New Module | `core/` | Add file, register in `tools.py` |
| New Skill | `skills/` | Implement `execute(llm_client, tools, **kwargs)` |
| New Agent | `agents/` | Subclass `AgentBase` |
| New Feedback | `core/activity_feedback.py` | Add to `THINKING_MSGS`, `WORKING_MSGS`, or `PROGRESS_MSGS` |

---

## License

MIT License — see [LICENSE](LICENSE) for full text.

---

*Built with ❤️ by ***REMOVED*** · NEXUS v6.0 — Autonomous Multi-Agent Framework*