---
name: ollama-launch-setup
description: Set up Ollama with `ollama launch` integration — Claude Code, Codex, Hermes, etc. using Ollama cloud models.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Ollama, Claude-Code, Codex, cloud-models, setup]
    related_skills: [claude-code, codex, hermes-agent]
---

# Ollama Launch Setup — Claude Code + Cloud Models

`ollama launch` is an official Ollama feature that starts third-party coding agents (Claude Code, Codex, Hermes, etc.) backed by Ollama models.

## Supported Integrations

| Name | CLI | Notes |
|------|-----|-------|
| claude | Claude Code | `ollama launch claude --model <model>` |
| codex | Codex | OpenAI CLI agent |
| cline | Cline | VS Code extension |
| copilot | Copilot CLI | |
| droid | Droid | |
| hermes | Hermes Agent | Self-referential |
| kimi | Kimi Code CLI | |
| opencode | OpenCode | |
| openclaw | OpenClaw | Aliases: clawdbot, moltbot |
| pi | Pi | |
| vscode | VS Code | Alias: code |

## Installation Steps

### 1. Install Claude Code
```bash
sudo npm install -g @anthropic-ai/claude-code
claude --version  # verify
```

### 2. Install Ollama
```bash
# Linux — needs zstd first
sudo apt-get install -y zstd
curl -fsSL https://ollama.com/install.sh | sudo sh
ollama --version  # verify
```

### 3. Start Ollama server
```bash
# Run as background process (sudo needed on some systems)
sudo ollama serve  # background it
# Wait 2s, then verify:
ollama list
```

### 4. Pull model
```bash
ollama pull kimi-k2.6:cloud  # cloud model
# or local: ollama pull llama3.3
```

### 5. Launch integration
```bash
ollama launch claude --model kimi-k2.6:cloud -y
```

## Cloud Model Authentication

**Cloud models (e.g. `kimi-k2.6:cloud`, `glm-5.1:cloud`) require an Ollama account sign-in.**

### Browser Auth Flow
```bash
ollama login
```
Outputs a URL like `https://ollama.com/connect?name=<id>&key=<key>`. User must open this in a browser and sign in to their Ollama account. The container/session is then authenticated.

### Pitfall: Headless / Container Environments
- `ollama login` does NOT accept an API key as a CLI argument
- Piping an API key via stdin doesn't work either
- The auth is browser-based — you MUST complete the browser callback
- On a headless container: share the URL with the user so they can open it on their local machine's browser
- The connect URL ties the session by hostname ID, so as long as the browser completes the flow, the container becomes authenticated

### ⚠ Headless Auth Attempts That DON'T Work
- Writing API key to `~/.ollama/auth.json` manually — ignored by ollama
- `OLLAMA_API_KEY=<key> ollama run <model>` — still says "requires sign in"
- Piping key via stdin to `ollama login` — still opens browser flow
- `Authorization: Bearer <key>` or `X-API-Key` headers against `localhost:11434/api/chat` — 401 Unauthorized

**The ONLY way is the browser callback.** There is no headless auth method.

## Extra Launch Flags

| Flag | Purpose |
|------|---------|
| `--model <model>` | Specify which Ollama model to use |
| `-y` | Auto-yes to confirmation prompts |
| `--config` | Configure without launching |
| `-- [args]` | Pass extra args to the integration (e.g. `-- --dangerously-skip-permissions`) |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `zstd` missing during install | `sudo apt-get install -y zstd` |
| Ollama server not running | Start with `sudo ollama serve` in background |
| `requires sign in` error | Run `ollama login`, complete browser auth |
| No GPU detected (warning) | Safe to ignore for cloud models; local models will use CPU |
| `ollama launch` not found | Update Ollama: `curl -fsSL https://ollama.com/install.sh \\| sudo sh` |

## LiteLLM Proxy for Claude Code + Ollama Cloud

When `ollama launch` isn't available or you need more control (multiple models, fallback, custom routing), use LiteLLM as a proxy that translates Anthropic Messages API calls to Ollama Cloud's OpenAI-compatible endpoint.

### Architecture

```
Claude Code → LiteLLM Proxy (:4000) → Ollama Cloud API (ollama.com/v1)
                 (model mapping)           (actual LLM inference)
```

Claude Code uses the Anthropic Messages API (`/v1/messages`). LiteLLM translates this to OpenAI chat/completions format and routes to Ollama Cloud.

### Setup

```bash
# 1. Create proxy venv
python3 -m venv /tmp/proxy-env
source /tmp/proxy-env/bin/activate
pip install 'litellm[proxy]'

# 2. Create config (/tmp/proxy-anthropic.yaml)
cat > /tmp/proxy-anthropic.yaml << 'EOF'
model_list:
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: openai/glm-5.1
      api_base: https://ollama.com/v1
      api_key: <OLLAMA_API_KEY>
      supports_function_calling: true

general_settings:
  drop_params: true
EOF

# 3. Start proxy
source /tmp/proxy-env/bin/activate && litellm --config /tmp/proxy-anthropic.yaml --port 4000

# 4. Configure Claude Code
# Edit ~/.claude/settings.json:
{
  "env": {
    "ANTHROPIC_API_KEY": "anything",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"
  },
  "model": "claude-sonnet-4-6"
}

# 5. Run Claude Code
ANTHROPIC_API_KEY=anything ANTHROPIC_BASE_URL=http://127.0.0.1:4000 claude -p "your task" --max-turns 10
```

### Troubleshooting Claude Code + LiteLLM Proxy

| Problem | Cause | Solution |
|---------|-------|----------|
| "Invalid model name passed in model=kimi-k2.6" | `~/.claude/settings.json` has stale `"model": "kimi-k2.6"` with direct Ollama Cloud URL | Overwrite settings.json to use `"model": "claude-sonnet-4-6"` + `"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"`. Remove `apiBaseUrl` and `apiProvider` fields. |
| Empty text in responses (thinking but no text) | Reasoning models (kimi-k2.6) put answer in `thinking` field, `text` is empty | Use non-reasoning model: `glm-5.1` or `deepseek-v3.2`. They produce proper `text` content. |
| 400 error from proxy after config change | LiteLLM caches model routing in RAM | Kill and restart the proxy process: `pkill -9 -f litellm; sleep 2; litellm --config ...` |
| `apiBaseUrl` in settings.json overrides proxy | Claude Code uses direct URL when `apiBaseUrl` is set | Remove `apiBaseUrl` and `apiProvider` from `~/.claude/settings.json`, use `ANTHROPIC_BASE_URL` env var instead |
| `drop_params: true` missing | Ollama Cloud doesn't support all Anthropic params (e.g. `top_k`) | Add `drop_params: true` to `general_settings` in proxy config |
| `supports_function_calling: true` missing | Tool calls won't work | Add `supports_function_calling: true` to litellm_params |

### Model Selection for Coding Tasks

| Model | Strengths | Weaknesses | Recommended |
|-------|-----------|------------|-------------|
| `glm-5.1` | Stable, no reasoning mode, proper text output, tool calling | Moderate coding ability | ✅ Best for automated Claude Code sessions |
| `deepseek-v3.2` | Strong coder, tool calling | Sometimes verbose | ✅ Good alternative |
| `kimi-k2.6` | Strong reasoning | Empty `text` field (answer in `thinking`), Claude Code can't parse | ❌ Broken with Messages API proxy |
| `kimi-k2:1t` | Strong coder | Reasoning mode issues | ⚠️ Unreliable |

### Key Insight: Claude Code Settings Priority

Claude Code merges settings from:
1. CLI flags (`--model`, `--output-format`)
2. Local `.claude/settings.local.json` (per-project, gitignored)
3. Project `.claude/settings.json` (shared)
4. `~/.claude/settings.json` (global)
5. Environment variables (`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`)

**Critical**: If `apiProvider` and `apiBaseUrl` are set in `~/.claude/settings.json`, Claude Code sends requests DIRECTLY to that URL, bypassing `ANTHROPIC_BASE_URL`. Always remove `apiProvider`/`apiBaseUrl` from settings.json when using the proxy approach.