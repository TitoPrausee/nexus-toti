---
name: mcp-ecosystem
description: MCP (Model Context Protocol) ecosystem overview — key concepts, cool servers, setup for Hermes Agent, and security best practices. Reference for adding MCP capabilities.
version: 1.0.0
author: Toti
license: MIT
metadata:
  hermes:
    tags: [MCP, Tools, Integrations, Ecosystem]
    related_skills: [native-mcp]
---

# MCP Ecosystem Overview

## What is MCP?

Model Context Protocol (MCP) is an **open protocol by Anthropic** that standardizes how AI models interact with external tools and data sources. Think of it as "USB for AI" — one standard connector for any capability.

**Key concepts:**
- **Tools**: Functions an AI can call (like API endpoints)
- **Resources**: Data sources the AI can read (files, databases, APIs)
- **Prompts**: Template messages the AI can use
- **Sampling**: Server-initiated LLM requests (agent-in-the-loop workflows)

**Transport types:**
- **stdio**: Server runs as subprocess (npx/uvx), communicates via stdin/stdout
- **HTTP/StreamableHTTP**: Remote server, communicates via HTTP

**SDK availability**: TypeScript, Python, Go, Rust, Java, Kotlin, C#, PHP, Ruby, Swift, Elixir — 11+ official SDKs.

## Hermes Agent MCP Setup

Hermes has a **built-in MCP client** (see `native-mcp` skill). Configuration in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  memory:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-memory"]
  
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  
  git:
    command: "uvx"
    args: ["mcp-server-git", "--repository", "/path/to/repo"]
  
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_..."
```

**Prerequisites:**
- `pip install mcp` — Python MCP SDK (✅ installed v1.27.1)
- `node` + `npx` — For TypeScript-based servers (✅ node v20.19.2, npx 9.2.0)
- `uvx` — For Python-based servers (✅ available)

**Security**: Hermes filters environment variables — only safe baseline (PATH, HOME, USER, etc.) is passed to MCP subprocesses unless explicitly configured via `env`. Credentials in error messages are auto-redacted.

**Tool naming**: `mcp_{server}_{tool}` — e.g., `mcp_memory_add`, `mcp_filesystem_read_file`

## Coolest MCP Servers (Curated for Tito's Stack)

### 🧠 Knowledge & Memory
| Server | Description | Install |
|--------|-------------|---------|
| **server-memory** (Official) | Persistent knowledge graph for agents | `npx -y @modelcontextprotocol/server-memory` |
| **Cortex** (`gzoo/cortex`) | Local-first KG, watches project files, extracts entities, web dashboard | `npx -y cortex` |
| **Forage** (`isaac-levine/forage`) | Self-improving tool discovery — searches registries, installs servers, persists tool knowledge | `npx -y forage` |

### 🏠 Smart Home & OS
| Server | Description | Install |
|--------|-------------|---------|
| **Terminator** (`mediar-ai/terminator`) | Desktop GUI automation via accessibility APIs (no vision model!) | `npx -y @anthropic-ai/terminator-mcp-agent` |
| **iTerm MCP** | Terminal command execution + screenshots | `npx -y iterm-mcp` |

### 🗄️ Database & Data
| Server | Description | Install |
|--------|-------------|---------|
| **server-postgres** (Official) | Read-only Postgres access with schema inspection | `npx -y @modelcontextprotocol/server-postgres` |
| **server-sqlite** (Official) | SQLite with BI capabilities | `npx -y @modelcontextprotocol/server-sqlite` |
| **MindsDB** | 200+ data sources as single MCP server, ML in SQL | `pip install mindsdb` |
| **AnyQuery** | Query 40+ apps via SQL (local-first, privacy-focused) | Download from github.com/julien040/anyquery |

### 🔍 Search & Research
| Server | Description | Install |
|--------|-------------|---------|
| **server-fetch** (Official) | Web content fetching, converts for LLM consumption | `npx -y @modelcontextprotocol/server-fetch` |
| **A2A Search** | Search 4800+ MCP servers, agents, CLI tools | `npx -y a2asearch-mcp` |

### 🛠️ DevOps & Infra
| Server | Description | Install |
|--------|-------------|---------|
| **server-git** (Official) | Git repo operations (read, search, manipulate) | `uvx mcp-server-git` |
| **server-github** (Official) | GitHub API — PRs, issues, file ops | `npx -y @modelcontextprotocol/server-github` |
| **server-filesystem** (Official) | Secure file operations with access controls | `npx -y @modelcontextprotocol/server-filesystem /path` |
| **Portainer MCP** | Container management via MCP | `npx -y portainer-mcp` |
| **LocalStack MCP** | Local AWS environment management | `npx -y localstack-mcp-server` |

### 🤖 Multi-Agent & Orchestration
| Server | Description | Install |
|--------|-------------|---------|
| **Bernstein** | Multi-agent orchestrator for 37 CLI coding agents, git worktree isolation, HMAC audit | `pip install bernstein` |
| **Roundtable** | Zero-config multi-AI: Codex, Claude Code, Cursor auto-discovery | `npx -y roundtable` |
| **Owlex** | Multi-agent deliberation: Claude Code, Codex, Gemini, OpenCode parallel | `npx -y owlex` |

### 💰 Finance & Trading
| Server | Description | Install |
|--------|-------------|---------|
| **awesome-crypto-mcp-servers** | Curated list of crypto/DeFi MCP servers | See github.com/badkk/awesome-crypto-mcp-servers |

### 🔐 Security
| Server | Description | Install |
|--------|-------------|---------|
| **MCPWatch** | Security scanner for MCP server vulnerabilities | `pip install mcp-watch` |
| **ToolHive** | Containerized MCP server management, isolation, security | See github.com/StacklokLabs/toolhive |

## MCP Ecosystem Stats (as of 2026)

- **Official SDKs**: 11+ languages (TypeScript, Python, Go, Rust, Java, Kotlin, C#, PHP, Ruby, Swift, Elixir)
- **Registry**: registry.modelcontextprotocol.io (official), glama.ai/mcp/servers (community)
- **Server count**: 5000+ community servers listed across registries
- **Major adopters**: Anthropic (Claude), OpenAI, Google, Microsoft, Cursor, Windsurf, Zed
- **Key registries**: Smithery.ai, MCPServers.com, MCPHub.com, OpenTools.com, mcp.run, PulseMCP.com

## Adding MCP Servers to Hermes

1. Choose server from the lists above
2. Add to `~/.hermes/config.yaml` under `mcp_servers`
3. Restart Hermes Agent
4. Tools appear as `mcp_{server}_{tool}` in all conversations

Example — adding memory + git:
```yaml
mcp_servers:
  memory:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-memory"]
  git:
    command: "uvx"
    args: ["mcp-server-git", "--repository", "/opt/data/repos"]
```

## Pitfalls

- **Node.js required** for npx-based servers — make sure node is installed
- **uvx required** for Python-based servers — make sure uv is installed  
- **Environment filtering**: Hermes only passes safe baseline env vars. API keys must be explicitly set in `env` config
- **No hot-reload**: Adding/removing servers requires restart
- **Sampling risk**: Servers can request LLM completions via `sampling/createMessage`. Disable for untrusted servers with `sampling: { enabled: false }`
- **Timeouts**: Default 120s per tool call, 60s for connection. Increase for slow servers