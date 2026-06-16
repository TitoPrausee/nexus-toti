---
name: claude-code-ollama-cloud
description: Set up and use Claude Code CLI with Ollama Cloud models (ARM64 Docker). Covers installation, auth, Docker networking, and print-mode task delegation.
version: 1.0.0
author: Hermes Agent
---

# Claude Code + Ollama Cloud (ARM64 Docker)

Use Claude Code (Anthropic's CLI coding agent) with Ollama Cloud models for autonomous coding tasks. Runs inside the Hermes Docker container on ARM64.

## Architecture

```
Container (ARM64 Hermes)
  ├── /usr/local/bin/ollama v0.23.0 — pre-installed
  ├── ~/.local/bin/claude — npm-installed Claude Code CLI
  └── Ollama Cloud API ← connects to host daemon → Host running ollama serve
```

**Key fact:** The Ollama daemon runs on the **Docker host**, NOT inside the container. Connect via `OLLAMA_HOST=http://host.docker.internal:11434`.

## Installation (first time only)

Claude Code must be installed globally via npm:

```bash
npm install -g @anthropic-ai/claude-code --prefix=/opt/data/home/.local
```

This creates: `~/.local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`
With symlink: `~/.local/bin/claude → ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`

## Path Setup

`ollama launch claude` needs `claude` in PATH. The global npm prefix must be in PATH:

```bash
export PATH="/opt/data/home/.local/bin:$PATH"
```

Without this, ollama errors: `Error: claude is not installed`.

## Start Claude Code with Cloud Model

### One-shot task (print mode) — PREFERRED

Pipe the task directly via stdin:

```bash
export PATH="/opt/data/home/.local/bin:$PATH"
export OLLAMA_HOST=http://host.docker.internal:11434

echo '<TASK DESCRIPTION>' | ollama launch claude --model glm-5.1:cloud
```

The task description should include:
- Exact file paths and project structure
- Build commands with JAVA_HOME/explicit paths
- Git commit, tag, push, and release instructions
- Verification steps

### Available Cloud Models

| Model | Purpose |
|-------|---------|
| `glm-5.1:cloud` | Default coding, fast |
| `glm-5.1:cloud` | Strong reasoning, complex tasks |
| `kimi-k2.6:cloud` | Delegation, multi-task |

### Modelliste abrufen

```bash
OLLAMA_HOST=http://host.docker.internal:11434 ollama list
```

Oder per API:

```bash
curl -s https://ollama.com/v1/models \
  -H "Authorization: Bearer $OLLAMA_API_KEY" | python3 -c "import json,sys;[print(m['id']) for m in json.load(sys.stdin).get('data',[])]"
```

## Print Mode Details

Claude Code launched via `ollama launch` runs in interactive mode by default. To make it non-interactive (print mode for automation):

```bash
echo 'task' | ollama launch claude --model glm-5.1:cloud 2>&1
```

If no stdin is detected after 3 seconds, it warns: `Warning: no stdin data received in 3s`.

## Task Delegation Pattern (Continuous Dev)

For autonomous issue implementation, craft a prompt like:

```bash
echo 'Implementiere Issue #N - TITLE für das Repo unter /opt/data/home/PROJECT/.

1. Lies das Issue auf GitHub: gh issue view <GITHUB_USER>/REPO N
2. Implementiere das Feature gemäß Issue-Body
3. Wichtige Pfade/Konstanten:
   - JAVA_HOME=/opt/data/home/.local/java/jdk-21.0.11+10
   - Build: cd /opt/data/home/PROJECT && ./gradlew build
   - Bei Fehlern: Identifier.of() statt asIdentifier(), fehlende Imports ergänzen
4. Git: git add -A && git commit -m "feat: Issue #N - TITLE (Closes #N)"
5. Version bump in gradle.properties
6. git tag -a vX.Y.Z && git push origin main --tags
7. gh release create vX.Y.Z build/libs/*.jar --title "vX.Y.Z" --notes "Issue N: TITLE"' | OLLAMA_HOST=http://host.docker.internal:11434 ollama launch claude --model glm-5.1:cloud
```

## What NOT To Do

- ❌ No `ollama pull <model>` — cloud models only, never downloaded locally
- ❌ No `localhost` or `127.0.0.1` as OLLAMA_HOST — use `host.docker.internal:11434`
- ❌ No binary downloads from GitHub — ollama is pre-installed at `/usr/local/bin/ollama`
- ❌ No `sudo` or systemd service management
- ❌ No `zstd` / tar extraction for ollama — it's already there
- ❌ No attempting to install ollama from script — it's already installed on host

## Pitfalls & Gotchas

1. **`-p` flag doesn't work with `ollama launch`** — the `-p` flag is for `claude` CLI directly. With `ollama launch`, pipe via stdin instead.
2. **Symlink must be in PATH** — ollama finds `claude` via PATH lookup. If claude is in `~/.local/bin`, that must be in PATH before calling `ollama launch`.
3. **Background processes use `terminal(background=true, notify_on_complete=true)`** — then poll with `process(action="poll")`.
4. **Ollama daemon on host** — the container doesn't run ollama serve. All model execution happens on the host, proxied through `host.docker.internal:11434`.
5. **API Key** — stored in memory (user profile). Set `OLLAMA_API_KEY` env var for direct API access without the local daemon.
