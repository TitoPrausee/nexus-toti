---
name: agent-architecture-integration
description: Progressive integration of Hermes-style agent architecture into existing projects. 8-layer reference model for building autonomous AI agent systems.
tags: [agent, architecture, integration, hermes, coding-agent]
---

# Agent Architecture Integration (Hermes-style)

When integrating a Hermes-inspired agent architecture into an existing codebase, follow this 8-layer reference model. **Never rewrite everything at once** — understand first, then extend incrementally.

## The 8 Layers

### 1. Entry Points
Multiple entry points feeding into a single core agent loop:
- **CLI** (interactive terminal)
- **Gateway** (long-running process for messaging platforms like Telegram)
- **Batch runner** (non-interactive, trajectory/task generation)
- **API server** (optional, programmatic access)

Each entry point must be **thin** — platform-specific logic stays in the entry point, not in the agent core.

### 2. Core Agent Loop (AIAgent)
Single central orchestration class shared by all entry points:
- Prompt assembly (system prompt from: personality/SOUL file, memory, skills, context files)
- Provider resolution (model + provider config → API credentials + API mode)
- Tool dispatch (call right tool, handle errors, loop until final response)
- Context compression (summarize middle turns when context window fills up)
- Session persistence (save conversation after each turn)
- Must be **stateless between instantiations** — all state from session store.

### 3. Memory System
Persistent cross-session memory:
- MEMORY.md or flat file / DB table, read at session start
- Agent can write mid-session when it learns something worth keeping
- Full-text search across past sessions (SQLite FTS5 or equivalent)
- User modeling: preferences, recurring patterns, project context

### 4. Skills System
Procedural memory as reusable skill documents:
- When agent solves non-trivial problem → write skill document describing approach
- Skills loaded into system prompt when relevant (keyword match or explicit invocation)
- Portable files (Markdown) in dedicated skills directory
- Agent can create, update, and search skills autonomously

### 5. Tool System
Central tool registry:
- Each tool self-registers at import time
- Tools grouped into **toolsets** (terminal, file, web, code execution, delegation)
- Registry handles: schema generation, dispatch, availability checking, error wrapping
- Terminal execution must support: local shell, Docker (at minimum)

### 6. Session Storage
SQLite-based persistence:
- Every turn saved: role, content, timestamp, session ID
- Sessions have lineage (compressed session knows parent)
- Full-text search across all sessions
- Per-platform / per-context session isolation

### 7. Messaging Gateway (optional but recommended)
Long-running gateway process:
- Connects to ≥1 messaging platform (Telegram recommended first)
- Routes messages to agent loop
- User authorization (allowlist or pairing code)
- Delivers responses through platform adapter
- Per-user session state

### 8. Plugin System
Loose coupling for optional subsystems:
- Memory provider: pluggable (default = flat file + SQLite, replaceable)
- Context engine: pluggable (default = lossy summarization)
- Tools & hooks registered by plugins without modifying core files

## Integration Order (lowest disruption → highest value)

1. **Memory system** first — highest impact, lowest coupling
2. **Skills system** second
3. **Session storage** third (if not already present)
4. **Tool registry** cleanup fourth
5. **Gateway** last — most isolated, easiest to add without touching core

## Rules
- Read and understand existing codebase completely before any changes
- Identify which layers already exist (even partially) vs. missing
- Never delete or break existing functionality — extend it
- After each layer, summarize what was built and what is still missing
- If unsure how something fits, ask before implementing