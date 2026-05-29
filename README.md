# NEXUS — Toti Agent System v3.0

> Autonomous multi-agent framework powered by Ollama Cloud · Per-agent model routing · Error Learning · 22 Tools · 10 Skills · Telegram Interface

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Ollama](https://img.shields.io/badge/Ollama-Cloud%20%7C%20Local-green.svg)](https://ollama.ai)

---

## Table of Contents

- [What is NEXUS?](#what-is-nexus)
- [Architecture](#architecture)
  - [System Overview](#system-overview)
  - [Agent Team](#agent-team)
  - [Agent Routing](#agent-routing)
  - [LLM Backend Stack](#llm-backend-stack)
  - [Memory System](#memory-system)
  - [Delegation Engine](#delegation-engine)
  - [Error Learning](#error-learning)
  - [Smart Scheduler](#smart-scheduler)
  - [Safety Guards](#safety-guards)
  - [Request Flow](#request-flow)
  - [Class Structure](#class-structure)
- [Tool Registry](#tool-registry)
- [Skill System](#skill-system)
- [Installation](#installation)
  - [Local Setup](#local-setup)
  - [Docker Setup](#docker-setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [Commands](#commands)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## What is NEXUS?

NEXUS is an autonomous multi-agent system built around **Toti** — a primary agent that thinks, delegates, learns, and acts without waiting for approval. Unlike typical chatbot wrappers, NEXUS is built for developers: it runs shell commands, writes and executes code, manages Docker containers, queries databases, and coordinates specialized sub-agents to tackle complex multi-step tasks.

**Key characteristics:**

- **Autonomous by default** — Toti acts, then reports. No confirmation loops for routine operations.
- **Per-agent model routing** — Each sub-agent runs on the best-fit LLM for its specialty.
- **Error learning** — NEXUS remembers every failure, classifies it, and avoids repeating mistakes.
- **Three interfaces** — Interactive CLI, single-task CLI, and a Telegram bot.
- **Multi-backend LLM** — Ollama Cloud, local Ollama, or z-ai CLI — auto-detected with auto-fallback.

---

## Architecture

### System Overview

```mermaid
graph TB
    subgraph Interfaces
        CLI[CLI Interface]
        TG[Telegram Bot]
        TASK[Single Task --task]
    end

    subgraph Primary["Primary Agent"]
        TOTI["🤖 TOTI / NEXUS-0<br/>kimi-k2.6:cloud"]
    end

    subgraph SubAgents["Sub-Agent Team"]
        SCOUT["🔍 SCOUT<br/>glm-5.1:cloud<br/>Research"]
        FORGE["⚒️ FORGE<br/>qwen3-coder-next:cloud<br/>Coding"]
        LENS["🔬 LENS<br/>kimi-k2.6:cloud<br/>Analysis"]
        HERALD["📢 HERALD<br/>minimax-m2.7:cloud<br/>Output"]
        GHOST["👻 GHOST<br/>deepseek-v4-flash:cloud<br/>Background"]
    end

    subgraph Core["Core Subsystems"]
        MEM["Memory<br/>L1 / L2 / L3"]
        TOOLS["Tools<br/>22 built-in"]
        SKILLS["Skills<br/>10 modules"]
        GUARDS["Safety Guards<br/>Loop · Steps · Budget"]
        SCHED["Smart Scheduler<br/>4 Trigger Types"]
        ERR["Error Learning<br/>Record · Warn · Fix"]
    end

    subgraph LLM["LLM Backend"]
        CLOUD["Ollama Cloud API<br/>api.ollama.ai"]
        LOCAL["Local Ollama<br/>localhost:11434"]
        ZAI["z-ai CLI<br/>GLM Fallback"]
    end

    CLI --> TOTI
    TG --> TOTI
    TASK --> TOTI

    TOTI --> SCOUT
    TOTI --> FORGE
    TOTI --> LENS
    TOTI --> HERALD
    TOTI --> GHOST

    TOTI --> MEM
    TOTI --> TOOLS
    TOTI --> SKILLS
    TOTI --> GUARDS
    TOTI --> SCHED
    TOTI --> ERR

    SCOUT --> CLOUD
    FORGE --> CLOUD
    LENS --> CLOUD
    HERALD --> CLOUD
    GHOST --> CLOUD
    TOTI --> CLOUD

    CLOUD -.->|fallback| LOCAL
    LOCAL -.->|fallback| ZAI
```

---

### Agent Team

NEXUS uses a team of 6 specialized agents, each running on the LLM best suited for its role.

| Agent | Model | Specialty | Temp | Max Tokens |
|-------|-------|-----------|------|------------|
| **NEXUS-0 / Toti** | `kimi-k2.6:cloud` | Orchestration, decision-making, general tasks | 0.7 | 4096 |
| **SCOUT** | `glm-5.1:cloud` | Web research, data extraction, fact-finding | 0.5 | 8192 |
| **FORGE** | `qwen3-coder-next:cloud` | Code generation, debugging, testing, deployment | 0.3 | 8192 |
| **LENS** | `kimi-k2.6:cloud` | Code review, security analysis, performance profiling | 0.4 | 4096 |
| **HERALD** | `minimax-m2.7:cloud` | Documentation, formatting, structured output | 0.6 | 4096 |
| **GHOST** | `deepseek-v4-flash:cloud` | Background monitoring, state persistence, scheduling | 0.3 | 2048 |

---

### Agent Routing

Every incoming message passes through a three-layer routing decision before reaching an agent.

```mermaid
flowchart TD
    IN([User Input]) --> CMD{Starts with /command?}

    CMD -->|Yes| HANDLE[_handle_command]
    HANDLE --> OUT1([Return formatted response])

    CMD -->|No| CONV{Is conversational?\n≤3 words · greeting · identity}

    CONV -->|Yes| QUICK[quick_response\nshort prompt + history]
    QUICK --> LLM1[llm.chat NEXUS-0]
    LLM1 --> LOG1[Update _conversation\nsession_log]
    LOG1 --> OUT2([Return response])

    CONV -->|No| COMPLEX{Assess complexity}

    COMPLEX -->|simple| QUICK
    COMPLEX -->|moderate| EXEC[toti.execute\nfull context · NEXUS-0 model]
    EXEC --> BUILD[_build_messages\nsystem prompt · state · memory\nerror warnings · tools · skills]
    BUILD --> LLM2[llm.chat NEXUS-0]
    LLM2 --> TOOLS_PROC[_process_tool_calls\n_process_skill_calls]
    TOOLS_PROC --> ERR_LOG[error_learning.auto_record]
    ERR_LOG --> OUT3([Return processed result])

    COMPLEX -->|complex| DAG[_delegate_complex\nDAG decomposition]
    DAG --> DECOMP[delegation.decompose_task\nLLM generates subtask DAG]
    DECOMP --> PLAN[delegation.execute_plan]
    PLAN --> PARALLEL["Parallel execution:\nSCOUT · FORGE · LENS · HERALD"]
    PARALLEL --> MERGE[merge_results]
    MERGE --> OUT4([Return final response])

    style IN fill:#4a9eff,color:#fff
    style OUT1 fill:#2ecc71,color:#fff
    style OUT2 fill:#2ecc71,color:#fff
    style OUT3 fill:#2ecc71,color:#fff
    style OUT4 fill:#2ecc71,color:#fff
    style DAG fill:#e67e22,color:#fff
    style EXEC fill:#9b59b6,color:#fff
```

---

### LLM Backend Stack

NEXUS auto-detects the available backend at startup and falls back gracefully.

```mermaid
flowchart LR
    subgraph Detection["Startup Detection"]
        A{OLLAMA_API_KEY\nset?}
        B{localhost:11434\nreachable?}
        C{z-ai binary\nin PATH?}
    end

    subgraph Backends
        CLOUD["☁️ Ollama Cloud API\nhttps://api.ollama.ai\nPer-agent model routing"]
        LOCAL["🖥️ Local Ollama\nlocalhost:11434\nSingle model for all agents"]
        ZAI["⚡ z-ai CLI\nGLM-4-Plus / GLM-4-Flash\nLegacy fallback"]
        NONE["❌ No backend\nError: configure at least one"]
    end

    A -->|Yes| CLOUD
    A -->|No| B
    B -->|Yes| LOCAL
    B -->|No| C
    C -->|Yes| ZAI
    C -->|No| NONE

    CLOUD -.->|model fails| LOCAL
    LOCAL -.->|unreachable| ZAI

    style CLOUD fill:#27ae60,color:#fff
    style LOCAL fill:#2980b9,color:#fff
    style ZAI fill:#8e44ad,color:#fff
    style NONE fill:#c0392b,color:#fff
```

---

### Memory System

```mermaid
classDiagram
    class MemorySystem {
        +session_id: str
        -_l1: dict
        -_l1_history: list
        -_rolling_summary: str
        +session_write(key, value)
        +session_read(key) Any
        +session_log(role, content, agent)
        +session_get_history(last_n) list
        +session_save()
        +session_load(session_id) bool
        +session_clear()
        +skill_write(name, pattern, description)
        +skill_read(name) dict
        +skill_list() list
        +longterm_write(key, value)
        +longterm_read(key) Any
        +longterm_list() list
        +build_context(query) str
        -_compress_rolling_summary()
    }

    class L1SessionMemory {
        <<volatile · in-RAM>>
        Conversation history
        Key-value session data
        Rolling summary
        Cleared on reset
    }

    class L2SkillMemory {
        <<persistent · file-based>>
        Solution patterns
        memory/skills/*.json
        Survives restarts
    }

    class L3LongTermMemory {
        <<persistent · file-based>>
        Facts and preferences
        GEPA analysis results
        memory/longterm/*.json
        Survives restarts
    }

    MemorySystem "1" --> "1" L1SessionMemory
    MemorySystem "1" --> "1" L2SkillMemory
    MemorySystem "1" --> "1" L3LongTermMemory
```

---

### Delegation Engine

```mermaid
sequenceDiagram
    participant T as Toti
    participant D as DelegationEngine
    participant LLM as LLM (NEXUS-0)
    participant S as SCOUT
    participant F as FORGE
    participant L as LENS

    T->>D: decompose_task(complex_task, context)
    D->>LLM: "Break this into subtasks as DAG JSON"
    LLM-->>D: DAG JSON [{id, agent, task, depends_on}]

    D->>D: execute_plan(dag)
    note over D: Resolve dependency order

    par Independent subtasks run in parallel
        D->>S: execute(subtask_A)
        S-->>D: result_A
    and
        D->>F: execute(subtask_B)
        F-->>D: result_B
    end

    note over D: subtask_C depends on subtask_B
    D->>L: execute(subtask_C, context=result_B)
    L-->>D: result_C

    D->>D: merge_results(result_A, result_B, result_C)
    D-->>T: final_result
```

---

### Error Learning

```mermaid
stateDiagram-v2
    [*] --> Monitoring : Agent starts

    Monitoring --> Recording : Tool call / LLM call / Agent step fails

    Recording --> Classifying : Error detected
    Classifying --> Stored : Classify into error class\nTOOL_ERROR · AGENT_ERROR\nPARSE_ERROR · LOOP_ERROR\nTIMEOUT_ERROR · LLM_ERROR\nVALIDATION_ERROR · PERMISSION_ERROR

    Stored --> Monitoring : Continue

    Monitoring --> Checking : Before each new action
    Checking --> Warning : Similar past error found\nsimilarity > 0.3
    Warning --> Injecting : Inject warning into system prompt\n"⚠ TOOL_ERROR: use absolute paths"
    Injecting --> Monitoring : Agent adjusts approach

    Monitoring --> Consolidating : Every 600s (GEPA trigger)
    Consolidating --> Pruning : Merge duplicate errors
    Pruning --> Promoting : Remove errors older than 7 days
    Promoting --> Monitoring : Promote fixed errors as SOLUTION hints

    Monitoring --> [*] : Session ends
```

---

### Smart Scheduler

```mermaid
graph LR
    subgraph Triggers["4 Trigger Types"]
        IT[INTERVAL_TRIGGER\nFixed interval\nskips if nothing changed]
        CT[CHANGE_TRIGGER\nFile/dir changes\nwatches paths]
        IDT[IDLE_TRIGGER\nSystem idle\nfor N seconds]
        TT[THRESHOLD_TRIGGER\nMetric crosses\na threshold]
    end

    subgraph DefaultTasks["Default Scheduled Tasks"]
        SP[state_persist\nINTERVAL · 60s]
        MC[memory_compress\nINTERVAL · 300s]
        EC[error_consolidate\nINTERVAL · 600s]
        LC[log_cleanup\nCHANGE · data/state/]
    end

    IT --> SP
    IT --> MC
    IT --> EC
    CT --> LC

    subgraph Runtime["Runtime via scheduler_tool"]
        ADD[Add task]
        LIST[List tasks]
        REMOVE[Remove task]
    end

    TT -.->|example| Runtime
    IDT -.->|example| Runtime
```

---

### Safety Guards

```mermaid
flowchart TD
    IN([Incoming Task]) --> STEPS{Steps ≤ max_steps?\ndefault: 10}

    STEPS -->|No| ABORT1[Abort task\nRecord in Error Learning]
    STEPS -->|Yes| BUDGET{Budget used\n≤ 90%?}

    BUDGET -->|No| WARN[Emit budget warning\nContinue with caution]
    BUDGET -->|Yes| LOOP{Loop detected?\nHash last N outputs\nHash last N actions}

    WARN --> LOOP

    LOOP -->|Yes| ABORT2[Abort task\nRecord LOOP_ERROR\nSuggest different approach]
    LOOP -->|No| ALLOW([Task allowed\nProceed])

    style ABORT1 fill:#c0392b,color:#fff
    style ABORT2 fill:#c0392b,color:#fff
    style ALLOW fill:#27ae60,color:#fff
    style WARN fill:#e67e22,color:#fff
```

---

### Request Flow

```mermaid
sequenceDiagram
    actor User
    participant IF as Interface\n(CLI / Telegram)
    participant T as Toti
    participant G as Guards
    participant EL as ErrorLearning
    participant LLM as LLMClient
    participant TOOL as ToolRegistry
    participant D as Delegation

    User->>IF: Send message
    IF->>T: process(user_input)

    alt /command
        T-->>IF: _handle_command() → formatted string
    else conversational or short
        T->>LLM: chat(short_prompt + history, NEXUS-0)
        LLM-->>T: response
        T->>T: update _conversation[]
        T-->>IF: response
    else moderate complexity
        T->>G: pre_check(task)
        G-->>T: allowed / blocked
        T->>EL: check_before_action(task)
        EL-->>T: warnings (injected into prompt)
        T->>LLM: chat(full_context, NEXUS-0)
        LLM-->>T: response with TOOL:/SKILL: calls
        T->>TOOL: _process_tool_calls()
        TOOL-->>T: tool results
        T->>EL: auto_record(result)
        T-->>IF: processed result
    else complex
        T->>D: decompose_task(task)
        D->>LLM: generate DAG JSON
        LLM-->>D: subtask DAG
        D->>D: execute_plan() — parallel where possible
        D-->>T: merged results
        T-->>IF: final response
    end

    IF-->>User: Display response
```

---

### Class Structure

```mermaid
classDiagram
    class AgentBase {
        +AGENT_ID: str
        +AGENT_NAME: str
        +SYSTEM_PROMPT_FILE: str
        #llm: LLMClient
        #memory: MemorySystem
        #tools: ToolRegistry
        #guards: NexusGuards
        #state: StateManager
        #error_learning: ErrorLearningSystem
        #_conversation: list[Message]
        +execute(task, context, level) dict
        +quick_response(message) str
        +reset_conversation()
        #_build_messages(user_input, context) list
        #_process_tool_calls(content) str
        #_process_skill_calls(content, task) str
        #_load_prompt() str
    }

    class TotiAgent {
        +AGENT_ID = "NEXUS-0"
        -delegation: DelegationEngine
        +process(user_input) str
        +register_agent(id, agent)
        -_is_conversational(task) bool
        -_assess_complexity(task) str
        -_delegate_complex(task) str
        -_handle_command(command) str
        -_gepa_evolve(task) str
    }

    class ScoutAgent {
        +AGENT_ID = "SCOUT"
    }

    class ForgeAgent {
        +AGENT_ID = "FORGE"
    }

    class LensAgent {
        +AGENT_ID = "LENS"
    }

    class HeraldAgent {
        +AGENT_ID = "HERALD"
    }

    class GhostAgent {
        +AGENT_ID = "GHOST"
        +scheduler: SmartScheduler
    }

    class LLMClient {
        -_active_backend: str
        -_agent_models: dict
        -_cloud_available: bool
        -_local_available: bool
        -_zai_available: bool
        +chat(messages, agent_id) LLMResponse
        +quick_response(message, agent_id) str
        +run_health_check() dict
        +get_model_for_agent(agent_id) str
        +get_health_status() dict
    }

    class DelegationEngine {
        -_agents: dict
        +register_agent(id, agent)
        +decompose_task(task, context) list
        +execute_plan(dag) dict
        -merge_results(results) dict
    }

    class ErrorLearningSystem {
        +record_error(class, context, action, message, agent)
        +check_before_action(action) list
        +auto_record_from_result(result, action, agent)
        +consolidate()
        +get_error_stats() dict
        +build_error_context(task) str
    }

    class NexusGuards {
        +max_steps: int
        +budget_limit_pct: float
        +pre_check(task) GuardResult
        +check_loop(output) bool
        +reset()
        +get_status() dict
    }

    class SmartScheduler {
        +add_task(task_id, trigger, ...)
        +remove_task(task_id)
        +get_status() dict
        +start()
        +stop()
    }

    AgentBase <|-- TotiAgent
    AgentBase <|-- ScoutAgent
    AgentBase <|-- ForgeAgent
    AgentBase <|-- LensAgent
    AgentBase <|-- HeraldAgent
    AgentBase <|-- GhostAgent

    TotiAgent --> DelegationEngine
    DelegationEngine --> ScoutAgent
    DelegationEngine --> ForgeAgent
    DelegationEngine --> LensAgent
    DelegationEngine --> HeraldAgent
    DelegationEngine --> GhostAgent

    AgentBase --> LLMClient
    AgentBase --> MemorySystem
    AgentBase --> NexusGuards
    AgentBase --> ErrorLearningSystem
    GhostAgent --> SmartScheduler
```

---

## Tool Registry

22 built-in tools dispatched via `TOOL:name(params)` syntax in LLM output.

<details>
<summary><strong>Base Tools — 6 (click to expand)</strong></summary>

| Tool | Parameters | Description |
|------|-----------|-------------|
| `terminal` | `cmd` | Execute shell commands |
| `read_file` | `path` | Read file contents |
| `write_file` | `path, content` | Write file contents |
| `web_search` | `query, num` | Web search (requires backend support) |
| `list_dir` | `path` | List directory contents |
| `code_exec` | `code` | Execute Python code |

</details>

<details>
<summary><strong>Developer Tools — 10 (click to expand)</strong></summary>

| Tool | Parameters | Description |
|------|-----------|-------------|
| `git` | `action, args` | Git: status, log, diff, commit, push, pull, branch, merge, tag, blame |
| `docker` | `action, args` | Docker: ps, images, run, stop, build, logs, compose, inspect, exec, pull, stats |
| `pkg_install` | `manager, package, dev` | Install packages via pip, npm, or apt |
| `http_request` | `method, url, headers, body` | HTTP GET/POST/PUT/DELETE/PATCH |
| `file_search` | `pattern, path, type` | Find files by name or grep for content |
| `process_manager` | `action, pid, name` | List, find, kill processes; show top |
| `env_check` | — | Check OS, Python, Node, Git, Docker, disk, memory |
| `port_check` | `port, host` | Check if a port is open |
| `json_yaml` | `action, data, query` | Parse, convert, query, validate JSON/YAML |
| `file_ops` | `action, src, dst` | tree, copy, move, delete, diff, tail, head, mkdir, chmod |

</details>

<details>
<summary><strong>Advanced Tools — 6 (click to expand)</strong></summary>

| Tool | Parameters | Description |
|------|-----------|-------------|
| `db_query` | `action, db_path, query, db_type` | SQLite / PostgreSQL / MySQL: query, tables, schema, insert |
| `api_test` | `action, url, method, headers, body, expected_status` | Test API endpoints, validate OpenAPI/Swagger specs |
| `code_lint` | `action, path, linter, fix` | Lint (flake8/pylint/eslint), format (black/prettier), type-check (mypy) |
| `archive_ops` | `action, src, dst, format` | Create/extract tar.gz, zip, gzip archives |
| `csv_ops` | `action, path, data, delimiter, query, output` | Read, write, filter, sort, convert CSV; compute statistics |
| `scheduler_tool` | `action, task_id, trigger, interval_seconds, command` | Manage Smart Scheduler tasks at runtime |

</details>

---

## Skill System

Skills are specialized Python modules in `skills/` implementing multi-step workflows. Agents invoke them via `SKILL:name(params)` syntax.

| Skill | Description |
|-------|-------------|
| `web_research` | Deep web research with source triangulation and confidence scoring |
| `code_debug` | Root-cause error analysis: read error → identify cause → fix → validate |
| `code_review` | Structured code review with quality verdict and improvement suggestions |
| `security_scan` | Scan code and dependencies for known vulnerabilities |
| `data_extract` | Extract and process data from CSV, JSON, APIs, web pages, or databases |
| `test_gen` | Automatically generate unit tests for Python/JS code |
| `doc_gen` | Generate README, API docs, or CHANGELOG from code |
| `deploy_prep` | Validate and prepare deployments for Docker, Kubernetes, or VPS |
| `dependency_check` | Check dependencies for updates, conflicts, and security issues |
| `performance` | Profile and optimize code performance |

---

## Installation

### Local Setup

**Requirements:** Python 3.10+, [Ollama](https://ollama.ai) installed

```bash
# Clone
git clone https://github.com/TitoPrausee/nexus-toti.git
cd nexus-toti

# Install dependencies
pip install rich pyyaml
pip install python-telegram-bot  # optional, for Telegram bot

# Pull a local model (if not using Ollama Cloud)
ollama pull qwen2.5:3b        # ~2 GB RAM — recommended for local use
ollama pull llama3.2:latest   # ~4 GB RAM

# Configure (optional — works out of the box with local Ollama)
cp .env.example .env

# Run
python nexus.py
```

**Using Ollama Cloud:**

```bash
# Option A: environment variable
export OLLAMA_API_KEY=your-key-here
python nexus.py

# Option B: interactive setup wizard
python nexus.py --setup

# Option C: edit config.yaml directly
# ollama.api_key: "your-key-here"
```

### Docker Setup

```bash
cp .env.example .env  # edit as needed

# Interactive CLI
docker compose run --rm nexus

# Telegram bot (runs as daemon)
docker compose --profile telegram up nexus-telegram -d

# Single task
docker compose run --rm nexus --task "List all Python files in /app"
```

| Variable | Description | Default |
|----------|-------------|---------|
| `OLLAMA_HOST` | Ollama server URL | `http://host.docker.internal:11434` |
| `OLLAMA_API_KEY` | Ollama Cloud API key | — |
| `NEXUS_MODEL_FAST` | Override fast model | `qwen2.5:3b` |
| `NEXUS_MODEL_STANDARD` | Override standard model | `qwen2.5:3b` |
| `NEXUS_TG_TOKEN` | Telegram bot token | — |

---

## Configuration

All configuration lives in `config.yaml`.

<details>
<summary><strong>Ollama / Model config (click to expand)</strong></summary>

```yaml
ollama:
  base_url: "https://api.ollama.ai"
  local_url: "http://localhost:11434"
  api_key: ""                # or OLLAMA_API_KEY env var
  mode: "cloud"              # "cloud" | "local" | "hybrid"

  agent_models:
    NEXUS-0:
      model: "kimi-k2.6:cloud"
      temperature: 0.7
      max_tokens: 4096
    FORGE:
      model: "qwen3-coder-next:cloud"
      temperature: 0.3
      max_tokens: 8192
```

</details>

<details>
<summary><strong>Guards config (click to expand)</strong></summary>

```yaml
guards:
  max_steps: 10
  budget_limit_pct: 90.0
  loop_detection_window: 3
  action_loop_window: 5
```

</details>

<details>
<summary><strong>Scheduler config (click to expand)</strong></summary>

```yaml
scheduler:
  enabled: true
  default_tasks:
    state_persist:
      trigger: INTERVAL_TRIGGER
      interval_seconds: 60
    log_cleanup:
      trigger: CHANGE_TRIGGER
      watch: "data/state/"
```

</details>

<details>
<summary><strong>Telegram config (click to expand)</strong></summary>

```yaml
telegram:
  enabled: false
  token: ""                  # or NEXUS_TG_TOKEN env var
  authorized_users: []       # empty = all users; [12345678] = restrict
```

</details>

---

## Usage

```bash
python nexus.py                          # Interactive CLI
python nexus.py --task "..."             # Single task and exit
python nexus.py --telegram               # Start Telegram bot
python nexus.py --health                 # LLM health check
python nexus.py --models                 # Show model routing table
python nexus.py --setup                  # Ollama Cloud setup wizard
python nexus.py --session ID             # Resume previous session
```

---

## Commands

Available in both CLI and Telegram:

| Command | Description |
|---------|-------------|
| `/status` | System status: guards, budget, LLM calls, agents, scheduler |
| `/health` | Run LLM health check for all configured models |
| `/memory` | Memory overview: L1 session history, L2 skills, L3 long-term |
| `/state` | Raw state JSON |
| `/errors` | Error Learning stats: known errors, recent failures, avoidance count |
| `/tools` | All 22 tools listed by category |
| `/skills` | All 10 skills with descriptions |
| `/reset` | Clear session memory and state |
| `/evolve` | GEPA self-improvement: analyze session, generate improvement proposals |
| `/help` | Show all commands |

---

## Project Structure

```
nexus-toti/
│
├── nexus.py                  # Entry point — arg parsing, mode selection
├── config.yaml               # All configuration
├── requirements.txt          # Python dependencies
├── setup.sh                  # Interactive setup script
├── ollama_setup.py           # Ollama Cloud setup wizard
│
├── agents/
│   ├── toti.py               # Primary agent — routing, delegation, commands
│   ├── scout.py              # Research agent
│   ├── forge.py              # Code / dev agent
│   ├── lens.py               # Analysis / review agent
│   ├── herald.py             # Output / docs agent
│   ├── ghost.py              # Background / monitoring agent
│   └── orchestrator.py       # DAG orchestration helper
│
├── core/
│   ├── agent_base.py         # Base class all agents inherit from
│   ├── llm_client.py         # Multi-backend LLM client
│   ├── memory.py             # 3-level memory (L1 session / L2 skills / L3 longterm)
│   ├── tools.py              # Tool registry and dispatch (22 tools)
│   ├── delegation.py         # DAG task decomposition and parallel execution
│   ├── error_learning.py     # Error record · warn · consolidate
│   ├── guards.py             # Loop detection · max steps · budget tracking
│   ├── scheduler.py          # Smart scheduler (4 trigger types)
│   └── state.py              # Persistent state management
│
├── interfaces/
│   ├── cli.py                # Interactive Rich terminal CLI
│   └── telegram_bot.py       # Telegram bot with per-user sessions
│
├── prompts/                  # System prompts per agent
│   ├── toti.txt
│   ├── scout.txt
│   ├── forge.txt
│   ├── lens.txt
│   ├── herald.txt
│   └── ghost.txt
│
├── skills/                   # 10 skill modules
│   └── *.py
│
├── memory/skills/            # Persistent skill patterns (JSON)
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit: `git commit -m "Add your feature"`
4. Push: `git push origin feature/your-feature`
5. Open a Pull Request

**Extension points:**

| What | Where | How |
|------|-------|-----|
| New Tool | `core/tools.py` | Add handler, register in `_register_defaults()` |
| New Skill | `skills/your_skill.py` | Implement `execute(llm_client, tools, **kwargs)` |
| New Agent | `agents/your_agent.py` | Subclass `AgentBase`, set `AGENT_ID` + `SYSTEM_PROMPT_FILE` |
| New Trigger | `core/scheduler.py` | Extend `ScheduledTask` with new trigger logic |

---

## License

MIT License — see [LICENSE](LICENSE) for full text.
