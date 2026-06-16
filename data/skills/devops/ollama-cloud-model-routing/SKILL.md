---
name: ollama-cloud-model-routing
description: >
  Benchmark and route Ollama Cloud models for agent delegation. Tests each model's
  speed, coding quality, reasoning, language support, and delegation reliability.
  Assigns models to agent roles based on strengths. Activate when adding a new
  Ollama Cloud model, tuning delegation config, or setting up agent teams.
version: 1.0.0
prerequisites:
  commands: [curl, jq, python3]
diagram: |
  graph LR
      Input((Request)) --> Router["Model Router"]
      Router --> Coding["Coding — qwen3-coder"]
      Router --> Reasoning["Reasoning — deepseek-v4"]
      Router --> Chat["Chat — glm-5.1"]
      Coding --> Result((Result))
      Reasoning --> Result
      Chat --> Result
      style Input fill:#1a1a2e,stroke:#e94560,color:#fff
      style Router fill:#16213e,stroke:#fbbf24,color:#fff
      style Coding fill:#16213e,stroke:#34d399,color:#fff
      style Reasoning fill:#16213e,stroke:#a78bfa,color:#fff
      style Chat fill:#16213e,stroke:#22d3ee,color:#fff
      style Result fill:#1a1a2e,stroke:#e94560,color:#fff
---

# Ollama Cloud Model Routing

## When to Use

- User mentions a new Ollama Cloud model to test
- Setting up delegate_task or cron delegation config
- Agent teams need model assignments based on strength
- Debugging slow/failed delegations

## Quick Benchmark

Test any model with this 3-step suite. Run all via `curl` to the Ollama Cloud proxy:

```bash
PROXY="http://host.docker.internal:11434/v1"
AUTH="Authorization: Bearer ollama"
MODEL="MODEL_NAME_HERE"
```

### Test 1: Speed & Responsiveness
```bash
time curl -s --max-time 45 "$PROXY/chat/completions" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d '{"model":"'"$MODEL"'","messages":[{"role":"user","content":"What is 2+2? Answer with just the number."}],"max_tokens":20}' | \
  python3 -c "import sys,json;d=json.load(sys.stdin);print(d['choices'][0]['message']['content'][:50])"
```
**Pass**: <5s response. **Warn**: 5-15s. **Fail**: >15s or timeout.

### Test 2: Coding (English required)
```bash
time curl -s --max-time 60 "$PROXY/chat/completions" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d '{"model":"'"$MODEL"'","messages":[{"role":"user","content":"Write a Python function merge_sorted_arrays(a: list[int], b: list[int]) -> list[int] that merges two sorted lists. Type hints + docstring only. No explanation."}],"max_tokens":600}' | \
  python3 -c "import sys,json;d=json.load(sys.stdin);c=d['choices'][0]['message'];print('REASONING:',bool(c.get('reasoning','')));print('CONTENT:',c['content'][:500] if c['content'] else 'EMPTY')"
```
**Key checks**: Does it produce actual code? Is reasoning token eating the output? Set max_tokens=600+ for reasoning models.

### Test 3: Delegation (most critical)
```bash
# Use delegate_task with the model and a simple coding task
# delegate_task(goal="Write a Python function count_words(s) -> dict. Type hints. Save to /tmp/test_MODEL.py. Run: python3 -m pytest /tmp/test_MODEL.py -v", toolsets=["terminal","file"])
```
**Pass**: Completes in <60s with working code. **Fail**: Timeout or 0 API calls.

## Known Model Profiles (as of May 2026)

| Model | Speed | Coding | Reasoning | German | Delegation | Best Role |
|-------|-------|--------|-----------|--------|------------|-----------|
| qwen3-coder-next:cloud | 1-4s | Clean, typed | No flag | OK | ✅ 20-60s, 3-13 calls | **Coding subagent** |
| deepseek-v4-flash:cloud | 3-30s | Good (EN only) | YES (eats tokens) | EMPTY | ✅ 21s (needs high max_tokens) | Complex reasoning tasks |
| kimi-k2.6:cloud | 13s+ | Content often empty | YES | Untested | ❌ **BROKEN** — 0 API calls, 5min timeout | Direct API only |
| glm-5.1:cloud | 13s | Content often empty | YES | Works (main model) | ⚠️ Slow, works sometimes | Main conversation |

## Critical Findings

### 1. Reasoning Token Problem
Models with chain-of-thought reasoning (DeepSeek, Kimi, GLM) emit a hidden `reasoning` field that **counts against max_tokens**. With max_tokens=200, most tokens go to reasoning and content is EMPTY.

**Fix**: Always set max_tokens=600+ for reasoning models. For delegation, use the `reasoning_effort: low` config option.

### 2. Language Asymmetry
Some models (deepseek-v4-flash) produce EMPTY output for German prompts but work fine in English. **Always use English for coding agent prompts**, even if the user communicates in German.

### 3. Delegation vs Direct API
A model that works via direct `curl` may completely fail in `delegate_task`. Kimi-k2.6 responds to direct API calls but produces 0 API calls when used as a delegation model — the subagent process never starts.

**Diagnosis**: Check the delegation result's `api_calls` field. If 0, the model is incompatible with the delegation transport regardless of direct API working.

### 4. Speed vs Quality Tradeoff
For simple coding subagents, fast models (qwen3-coder-next at 1-4s) outperform reasoning models because:
- Less token waste → more actual output
- Faster iteration cycles
- Fewer timeout risks in delegation

Reserve reasoning models for tasks that genuinely need chain-of-thought (architecture decisions, debugging, analysis).

## Model Assignment Rules

```
Coding subagents (delegate_task)     → qwen3-coder-next:cloud
Text/German content generation       → glm-5.1:cloud (main model)  
Complex reasoning / debugging        → deepseek-v4-flash:cloud (EN + max_tokens 800+)
Analysis / summarization             → glm-5.1:cloud direct (skip delegation)
Main conversation                    → glm-5.1:cloud (current default)
```

## Config

Update `/opt/data/config.yaml` delegation section:

```yaml
delegation:
  model: qwen3-coder-next:cloud    # best for coding subagents
  provider: custom
  base_url: http://host.docker.internal:11434/v1
  api_key: ollama
  inherit_mcp_toolsets: true
  max_concurrent_children: 2        # RAM protection
  max_iterations: 50
  reasoning_effort: low              # prevent reasoning token waste
```

## Pitfalls

- **Never assume direct API success = delegation success** — always test both
- **German prompts can produce EMPTY output** on some models — use English for code
- **Reasoning models need 600+ max_tokens** or content is empty
- **kimi-k2.6:cloud delegation is BROKEN** — don't use it for delegate_task until confirmed fixed
- **Ollama Cloud models not in `/v1/models` list** still work if you know the exact name (cloud-routed)
- **Monitor RAM** — each concurrent delegation adds 200-500MB; max 2 concurrent
- **Cloud model rate limits** — aggressive dispatch (every 2h) can eat weekly quotas; start at 6h