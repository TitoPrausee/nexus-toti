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
  - [Core Subsystems](#core-subsystems)
  - [LLM Backend Stack](#llm-backend-stack)
  - [Memory System](#memory-system)
  - [Tool Registry](#tool-registry)
  - [Skill System](#skill-system)
  - [Error Learning](#error-learning)
  - [Smart Scheduler](#smart-scheduler)
  - [Safety Guards](#safety-guards)
  - [Request Flow](#request-flow)
- [Installation](#installation)
  - [Local Setup](#local-setup)
  - [Docker Setup](#docker-setup)
- [Configuration](#configuration)
- [Usage](#usage)
  - [CLI Mode](#cli-mode)
  - [Telegram Bot](#telegram-bot)
  - [Single Task](#single-task)
- [Commands](#commands)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## What is NEXUS?

NEXUS is an autonomous multi-agent system built around **Toti** — a primary agent that thinks, delegates, learns, and acts without waiting for approval. Unlike typical chatbot wrappers, NEXUS is built for developers: it runs shell commands, writes and executes code, manages Docker containers, queries databases, and coordinates specialized sub-agents to tackle complex multi-step tasks.

**Key characteristics:**

- **Autonomous by default** — Toti acts, then reports. No confirmation loops for routine operations.
- **Per-agent model routing** — Each sub-agent runs on the best-fit LLM for its specialty (coding, research, analysis, etc.)
- **Error learning** — NEXUS remembers every failure, classifies it, and avoids repeating the same mistake in future sessions.
- **Three interfaces** — Interactive CLI, single-task CLI, and a Telegram bot.
- **Multi-backend LLM** — Ollama Cloud, local Ollama, or z-ai CLI — auto-detected and auto-fallback.

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         NEXUS v3.0                              │
│                                                                 │
│   ┌──────────┐   ┌──────────┐   ┌──────────────────────────┐   │
│   │   CLI    │   │ Telegram │   │     Single Task (--task)  │   │
│   │Interface │   │   Bot    │   │                          │   │
│   └────┬─────┘   └────┬─────┘   └────────────┬─────────────┘   │
│        └──────────────┴──────────────────────┘                 │
│                              │                                  │
│                     ┌────────▼────────┐                         │
│                     │   TOTI (Primary  │                         │
│                     │     Agent)       │                         │
│                     │   NEXUS-0 Model  │                         │
│                     └────────┬────────┘                         │
│                              │                                  │
│          ┌───────────────────┼───────────────────┐              │
│          │                   │                   │              │
│   ┌──────▼──────┐   ┌────────▼──────┐   ┌───────▼──────┐       │
│   │    SCOUT    │   │     FORGE     │   │     LENS     │       │
│   │  glm-5.1   │   │ qwen3-coder  │   │  kimi-k2.6  │       │
│   │ (Research) │   │   (Coding)   │   │  (Analysis) │       │
│   └─────────────┘   └──────────────┘   └──────────────┘       │
│                                                                 │
│          ┌──────────────────────────────────┐                   │
│          │                                  │                   │
│   ┌──────▼──────┐                  ┌────────▼──────┐            │
│   │   HERALD    │                  │     GHOST     │            │
│   │minimax-m2.7 │                  │deepseek-flash │            │
│   │  (Output)  │                  │ (Background)  │            │
│   └─────────────┘                  └───────────────┘            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Core Subsystems                       │   │
│  │  Memory │ Tools (22) │ Skills (10) │ Guards │ Scheduler  │   │
│  │         │            │             │        │ ErrorLearn │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

### Agent Team

NEXUS uses a team of 6 specialized agents. Each agent runs on a different LLM optimized for its task type.

| Agent | Model | Specialty | Temp | Max Tokens |
|-------|-------|-----------|------|------------|
| **NEXUS-0 / Toti** | `kimi-k2.6:cloud` | Orchestration, decision-making, general tasks | 0.7 | 4096 |
| **SCOUT** | `glm-5.1:cloud` | Web research, data extraction, fact-finding | 0.5 | 8192 |
| **FORGE** | `qwen3-coder-next:cloud` | Code generation, debugging, testing, deployment | 0.3 | 8192 |
| **LENS** | `kimi-k2.6:cloud` | Code review, security analysis, performance profiling | 0.4 | 4096 |
| **HERALD** | `minimax-m2.7:cloud` | Documentation, formatting, structured output | 0.6 | 4096 |
| **GHOST** | `deepseek-v4-flash:cloud` | Background monitoring, state persistence, scheduling | 0.3 | 2048 |

<details>
<summary><strong>Agent Routing Logic (click to expand)</strong></summary>

When Toti receives a message, it runs through three layers of routing:

```
Input
  │
  ├─ Is it a /command?  ──────────────────────────────► handle_command()
  │
  ├─ Is it conversational? (≤3 words, greeting, identity question)
  │    └─ YES ─────────────────────────────────────────► quick_response()
  │                                                       (short prompt + history)
  │
  └─ Assess complexity:
       │
       ├─ simple  ──────────────────────────────────────► quick_response()
       │
       ├─ moderate  ────────────────────────────────────► toti.execute()
       │                                                   (full context, NEXUS-0 model)
       │
       └─ complex  ────────────────────────────────────► delegation.decompose_task()
                                                           ├─ SCOUT  (research subtasks)
                                                           ├─ FORGE  (code subtasks)
                                                           ├─ LENS   (review subtasks)
                                                           ├─ HERALD (output subtasks)
                                                           └─ GHOST  (background subtasks)
```

Complexity is assessed by counting task indicators (keywords like "build", "debug", "deploy", "and then") and word count. Tasks with ≥3 indicators or >40 words trigger full DAG delegation.

</details>

---

### Core Subsystems

<details>
<summary><strong>Delegation Engine (click to expand)</strong></summary>

The `DelegationEngine` in `core/delegation.py` handles complex multi-step task decomposition:

1. **Task Decomposition** — Uses the LLM to break a complex task into a Directed Acyclic Graph (DAG) of subtasks.
2. **Dependency Resolution** — Subtasks with dependencies wait for their prerequisites to complete.
3. **Parallel Execution** — Independent subtasks run in parallel where possible.
4. **Result Aggregation** — Results from all subtasks are merged into a final response.

```
complex task
     │
     ▼
decompose_task()  ──► LLM generates DAG JSON
     │
     ▼
execute_plan()
     ├─ subtask A (SCOUT)  ─────────────────────────────────► result_A
     ├─ subtask B (FORGE)  ─────────────────────────────────► result_B
     └─ subtask C (LENS, depends on B) ── waits for B ──────► result_C
                                                                   │
                                                                   ▼
                                                           merge_results()
```

</details>

<details>
<summary><strong>Memory System — 3 Levels (click to expand)</strong></summary>

`core/memory.py` implements a 3-level hierarchical memory:

```
L1 — Session Memory (volatile, in-RAM)
     • Conversation history for current session
     • Key-value store for session-scoped data
     • Rolling summary (auto-compressed every 10 entries)
     • Cleared on /reset or new session

L2 — Skill Memory (persistent, file-based)
     • Solution patterns that worked in past sessions
     • Stored as JSON in memory/skills/
     • Example: "how to fix this type of import error"
     • Survives restarts

L3 — Long-Term Memory (persistent, file-based)
     • Facts, preferences, project context
     • GEPA self-improvement analysis results
     • Stored as JSON in memory/longterm/
     • Survives restarts
```

The `build_context()` method merges all three levels into a single context string that gets injected into the system prompt for every LLM call.

</details>

---

### LLM Backend Stack

NEXUS supports three backends, tried in priority order:

```
┌──────────────────────────────────────────────────────┐
│                  Backend Priority                    │
│                                                      │
│  1. Ollama Cloud API  (if OLLAMA_API_KEY is set)     │
│     └─ Endpoint: https://api.ollama.ai               │
│     └─ Per-agent model routing (see Agent Team)      │
│                                                      │
│  2. Local Ollama  (if localhost:11434 responds)       │
│     └─ Endpoint: http://localhost:11434              │
│     └─ Falls back to llama3.2:latest or configured   │
│                                                      │
│  3. z-ai CLI  (if `z-ai` binary found in PATH)       │
│     └─ ZhipuAI GLM-4-Plus / GLM-4-Flash              │
│     └─ Legacy fallback only                          │
└──────────────────────────────────────────────────────┘
```

The active backend is auto-detected at startup. You can force a specific backend in `config.yaml`:

```yaml
ollama:
  mode: "cloud"    # "cloud" | "local" | "hybrid"
```

---

### Tool Registry

22 built-in tools, dispatched via `TOOL:name(params)` syntax in LLM output.

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

### Skill System

Skills are specialized Python modules in `skills/` that implement multi-step workflows. Agents call them via `SKILL:name(params)` syntax.

| Skill | Description |
|-------|-------------|
| `web_research` | Deep web research with source triangulation and confidence scoring |
| `code_debug` | Root-cause error analysis: read error → identify cause → fix → validate |
| `code_review` | Structured code review with quality verdict and improvement suggestions |
| `security_scan` | Scan code and dependencies for vulnerabilities |
| `data_extract` | Extract and process data from CSV, JSON, APIs, web pages, or databases |
| `test_gen` | Automatically generate unit tests for Python/JS code |
| `doc_gen` | Generate README, API docs, or CHANGELOG from code |
| `deploy_prep` | Validate and prepare deployments for Docker, Kubernetes, or VPS |
| `dependency_check` | Check dependencies for updates, conflicts, and security issues |
| `performance` | Profile and optimize code performance |

---

### Error Learning

`core/error_learning.py` is NEXUS's self-improvement loop. It runs entirely locally (no LLM calls) and operates in three phases:

```
Phase 1 — Record
  Every tool call, agent step, and LLM response is monitored.
  Failures are classified into error classes:
    TOOL_ERROR, AGENT_ERROR, PARSE_ERROR, LOOP_ERROR,
    TIMEOUT_ERROR, LLM_ERROR, VALIDATION_ERROR,
    PERMISSION_ERROR, DEPENDENCY_ERROR

Phase 2 — Warn
  Before each action, the error database is checked for similar past failures.
  Warnings are injected into the system prompt:
    "⚠ TOOL_ERROR: read_file on /tmp/ failed before — use absolute paths"

Phase 3 — Consolidate (GEPA trigger, every 10 min)
  Old duplicate errors are merged.
  Errors older than 7 days are pruned.
  Successful fixes are promoted as SOLUTION hints.
```

<details>
<summary><strong>Error record format (click to expand)</strong></summary>

```json
{
  "error_class": "TOOL_ERROR",
  "context": "reading config from relative path",
  "action": "TOOL:read_file(path=config.yaml)",
  "error_message": "FileNotFoundError: config.yaml",
  "agent": "FORGE",
  "tool": "read_file",
  "hint": "Use absolute paths — relative paths fail depending on working directory",
  "solution": "Use os.path.abspath() or Path(__file__).parent / 'config.yaml'",
  "solved": true,
  "occurrences": 3,
  "timestamp": 1700000000
}
```

</details>

---

### Smart Scheduler

`core/scheduler.py` replaces dumb time-based crons with 4 intelligent trigger types:

| Trigger | Fires when... | Use case |
|---------|---------------|----------|
| `INTERVAL_TRIGGER` | Fixed interval, but skips if nothing changed | State persistence every 60s |
| `CHANGE_TRIGGER` | A watched file/directory changes | Log cleanup when state/ changes |
| `IDLE_TRIGGER` | System has been idle for N seconds | Memory compression during idle |
| `THRESHOLD_TRIGGER` | A metric crosses a threshold | Alert when budget > 90% |

Default scheduled tasks (configured in `config.yaml`):

```
state_persist     — INTERVAL_TRIGGER, every 60s
memory_compress   — INTERVAL_TRIGGER, every 300s
error_consolidate — INTERVAL_TRIGGER, every 600s
log_cleanup       — CHANGE_TRIGGER, watches data/state/
```

---

### Safety Guards

`core/guards.py` runs locally (zero LLM cost) and enforces three limits:

```
Max Steps Guard       — Stops a task after N steps (default: 10)
                        Prevents infinite loops in agentic chains

Budget Guard          — Tracks estimated token usage per session
                        Warns when budget_used_pct > 90%

Loop Detection Guard  — Hashes recent outputs and actions
                        Triggers if the same pattern repeats within
                        a window of 3 outputs or 5 actions
```

When a guard triggers, the task is aborted and the error is recorded in Error Learning.

---

### Request Flow

Complete flow from user input to final response:

```
User Input
    │
    ▼
telegram_bot.handle_message()  OR  cli.run()
    │
    ▼
toti.process(user_input)
    │
    ├── /command ──────────────────────────────► toti._handle_command()
    │                                                      │
    │                                                      ▼
    │                                              Return formatted string
    │
    ├── conversational / short ─────────────────► toti.quick_response()
    │                                                      │
    │                                            [short system prompt]
    │                                            [last 20 conversation turns]
    │                                            [current message]
    │                                                      │
    │                                                      ▼
    │                                            llm.chat(agent_id="NEXUS-0")
    │                                                      │
    │                                            update _conversation[]
    │                                            session_log("user", "assistant")
    │                                                      │
    │                                                      ▼
    │                                              Return response
    │
    ├── moderate complexity ─────────────────────► toti.execute(task)
    │                                                      │
    │                                         guards.pre_check() ──► abort if blocked
    │                                         error_learning.check_before_action()
    │                                         _build_messages()
    │                                           └─ full system prompt
    │                                           └─ state JSON
    │                                           └─ memory context (L1+L2+L3)
    │                                           └─ error warnings
    │                                           └─ tool list (22 tools)
    │                                           └─ skill list (10 skills)
    │                                           └─ conversation history
    │                                                      │
    │                                         llm.chat(agent_id="NEXUS-0")
    │                                         _process_tool_calls()  ──► execute tools
    │                                         _process_skill_calls() ──► execute skills
    │                                         error_learning.auto_record()
    │                                                      │
    │                                                      ▼
    │                                              Return processed result
    │
    └── complex ─────────────────────────────────► toti._delegate_complex(task)
                                                           │
                                               delegation.decompose_task()
                                                 └─ LLM generates DAG JSON
                                                           │
                                               delegation.execute_plan()
                                                 ├─ SCOUT.execute(subtask)
                                                 ├─ FORGE.execute(subtask)
                                                 ├─ LENS.execute(subtask)
                                                 └─ HERALD.execute(subtask)
                                                           │
                                               merge_results()
                                                           │
                                                           ▼
                                                   Return final response
```

---

## Installation

### Local Setup

**Requirements:** Python 3.10+, [Ollama](https://ollama.ai) installed

```bash
# 1. Clone the repo
git clone https://github.com/TitoPrausee/nexus-toti.git
cd nexus-toti

# 2. Install Python dependencies
pip install rich pyyaml

# Optional: Telegram bot support
pip install python-telegram-bot

# 3. Pull a local model (if not using Ollama Cloud)
ollama pull qwen2.5:3b        # lightweight, ~2GB RAM
# or
ollama pull llama3.2:latest   # ~4GB RAM

# 4. Configure (optional — works out of the box with local Ollama)
cp .env.example .env
# Edit .env to set OLLAMA_API_KEY if using Ollama Cloud

# 5. Run
python nexus.py
```

**Using Ollama Cloud (for per-agent model routing):**

```bash
# Option A: via environment variable
export OLLAMA_API_KEY=your-key-here
python nexus.py

# Option B: interactive setup wizard
python nexus.py --setup

# Option C: directly in config.yaml
# Edit config.yaml → ollama.api_key
```

---

### Docker Setup

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env

# 2. Build and run (interactive CLI)
docker compose run --rm nexus

# 3. Telegram bot mode
docker compose --profile telegram up nexus-telegram -d

# 4. Single task
docker compose run --rm nexus --task "Write a Python script that lists all files in /tmp"
```

**Environment variables for Docker:**

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
  api_key: ""                # or set OLLAMA_API_KEY env var
  mode: "cloud"              # "cloud" | "local" | "hybrid"

  agent_models:
    NEXUS-0:
      model: "kimi-k2.6:cloud"
      temperature: 0.7
      max_tokens: 4096
    FORGE:
      model: "qwen3-coder-next:cloud"
      temperature: 0.3       # lower = more deterministic for code
      max_tokens: 8192
    # ... see config.yaml for all agents
```

</details>

<details>
<summary><strong>Guards config (click to expand)</strong></summary>

```yaml
guards:
  max_steps: 10              # Max steps per task before abort
  budget_limit_pct: 90.0     # Warn when this % of estimated budget is used
  loop_detection_window: 3   # Hash last N outputs for loop detection
  action_loop_window: 5      # Hash last N actions for loop detection
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
    memory_compress:
      trigger: INTERVAL_TRIGGER
      interval_seconds: 300
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
  token: ""                  # or set NEXUS_TG_TOKEN env var
  authorized_users: []       # empty = all users allowed
                             # [12345678, 87654321] = restrict to these IDs
```

</details>

---

## Usage

### CLI Mode

```bash
python nexus.py
```

Interactive REPL with Toti. Type any task or use `/commands`.

```
Toti > What files are in the current directory?
Toti > Write a FastAPI endpoint that returns system info
Toti > Debug this error: ModuleNotFoundError: No module named 'requests'
Toti > Review my code in src/main.py for security issues
```

### Telegram Bot

```bash
# Set token
export NEXUS_TG_TOKEN=your-bot-token

# Start bot
python nexus.py --telegram

# Or with Docker
docker compose --profile telegram up nexus-telegram -d
```

Each Telegram user gets their own isolated session with persistent memory.

### Single Task

```bash
# Run a single task and exit
python nexus.py --task "Create a requirements.txt from imports in src/"

# Show model routing table
python nexus.py --models

# Run health check
python nexus.py --health

# Setup Ollama Cloud
python nexus.py --setup --api-key YOUR_KEY

# Resume a previous session
python nexus.py --session session_1700000000
```

---

## Commands

Available in CLI and Telegram:

| Command | Description |
|---------|-------------|
| `/status` | System status: guards, budget, LLM stats, agent count, scheduler |
| `/health` | Run LLM health check for all models |
| `/memory` | Show memory overview: L1 session, L2 skills, L3 long-term |
| `/state` | Show raw state JSON |
| `/errors` | Error Learning statistics and recent failures |
| `/tools` | List all 22 available tools by category |
| `/skills` | List all 10 available skills |
| `/reset` | Clear session memory and state |
| `/evolve` | Run GEPA self-improvement analysis on the current session |
| `/help` | Show all commands |

---

## Project Structure

```
nexus-toti/
│
├── nexus.py                  # Entry point — CLI arg parsing, mode selection
├── config.yaml               # All configuration (models, guards, scheduler, etc.)
├── requirements.txt          # Python dependencies
├── setup.sh                  # Interactive setup script
├── ollama_setup.py           # Ollama Cloud setup wizard
│
├── agents/                   # Agent implementations
│   ├── toti.py               # Primary agent — routing, delegation, commands
│   ├── scout.py              # Research agent
│   ├── forge.py              # Code/dev agent
│   ├── lens.py               # Analysis/review agent
│   ├── herald.py             # Output/docs agent
│   ├── ghost.py              # Background/monitoring agent
│   └── orchestrator.py       # DAG orchestration helper
│
├── core/                     # Core subsystems
│   ├── agent_base.py         # Base class all agents inherit from
│   ├── llm_client.py         # Multi-backend LLM client (Cloud/Local/z-ai)
│   ├── memory.py             # 3-level memory system (L1/L2/L3)
│   ├── tools.py              # Tool registry and dispatch (22 tools)
│   ├── delegation.py         # DAG task decomposition and execution
│   ├── error_learning.py     # Error classification, warning, consolidation
│   ├── guards.py             # Loop detection, max steps, budget tracking
│   ├── scheduler.py          # Smart scheduler (4 trigger types)
│   └── state.py              # Persistent state management
│
├── interfaces/               # User-facing interfaces
│   ├── cli.py                # Interactive Rich terminal CLI
│   └── telegram_bot.py       # Telegram bot (per-user sessions)
│
├── prompts/                  # System prompts for each agent
│   ├── toti.txt              # Toti's full persona and capability prompt
│   ├── scout.txt             # SCOUT research prompt
│   ├── forge.txt             # FORGE coding prompt
│   ├── lens.txt              # LENS analysis prompt
│   ├── herald.txt            # HERALD output prompt
│   └── ghost.txt             # GHOST background prompt
│
├── skills/                   # Skill modules (10 skills)
│   ├── web_research.py
│   ├── code_debug.py
│   ├── code_review.py
│   ├── security_scan.py
│   ├── data_extract.py
│   ├── test_gen.py
│   ├── doc_gen.py
│   ├── deploy_prep.py
│   ├── dependency_check.py
│   └── performance.py
│
├── memory/
│   └── skills/               # Persistent skill patterns (JSON)
│
├── data/                     # Runtime data (gitignored)
│   └── state/                # Per-session state files
│
├── Dockerfile                # Container build
├── docker-compose.yml        # CLI + Telegram service definitions
└── .env.example              # Environment variable template
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

**Extending NEXUS:**

- **New Tool** — Add a handler in `core/tools.py` and register it in `_register_defaults()`
- **New Skill** — Create `skills/your_skill.py` with an `execute(llm_client, tools, **kwargs)` function
- **New Agent** — Subclass `AgentBase`, set `AGENT_ID`, `SYSTEM_PROMPT_FILE`, and register in `nexus.py`
- **New Trigger Type** — Extend `core/scheduler.py` with a new `ScheduledTask` subclass

---

## License

MIT License — see [LICENSE](LICENSE) for full text.
