---
name: ollama-model-benchmark
description: Benchmark Ollama Cloud models for coding subagent delegation — test speed, quality, reasoning overhead, and delegation compatibility
tags: [ollama, benchmark, delegation, models, subagents]
---

# Ollama Model Benchmark Workflow

When new models are available on Ollama Cloud, benchmark them systematically before assigning to agent roles.

## Ollama Cloud Setup

- Base URL: `http://host.docker.internal:11434/v1`
- Auth: `Bearer ollama`
- List models: `curl http://host.docker.internal:11434/v1/models -H "Authorization: Bearer ollama"`

## Benchmark Phases

### Phase 1: Direct API Speed Test

```bash
time curl -s --max-time 45 http://host.docker.internal:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ollama" \
  -d '{"model":"MODEL:cloud","messages":[{"role":"user","content":"What is 2+2? Answer with just the number."}],"max_tokens":20}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);c=d['choices'][0]['message'];print('REASONING:',bool(c.get('reasoning','')));print('CONTENT:',c['content'][:100] if c.get('content') else 'EMPTY');print('TOKENS:',d.get('usage',{}))"
```

### Phase 2: Coding Quality Test

```bash
curl -s --max-time 60 ... \
  -d '{"model":"MODEL:cloud","messages":[{"role":"user","content":"Write a Python function merge_sorted_arrays(a, b) that merges two sorted lists. Type hints + docstring only."}],"max_tokens":300}'
```

### Phase 3: Reasoning Test

```
"A bat and ball cost $1.10 total. The bat costs $1.00 more than the ball. How much does the ball cost? Think step by step."
```
Correct answer: $0.05

### Phase 4: German Test

```
"Schreibe genau 2 Sätze über die Friedrich-Schiller-Universität Jena. Sachlich."
```

### Phase 5: Delegation Test

Use `delegate_task` with a coding task:
- Simple function + tests (quick benchmark)
- Class with methods (medium complexity)
- ALWAYS verify: code written, tests pass, API calls made

## Key Findings (Current Models)

| Model | Speed | Reasoning | Coding | German | Delegation | Best For |
|-------|-------|-----------|--------|--------|------------|----------|
| qwen3-coder-next:cloud | 1-4s | No (faster) | Clean, typed | OK | ✅ Fast (3 calls, 24s) | **Coding subagents** |
| deepseek-v4-flash:cloud | 3-30s | Yes (eats tokens) | Good (EN only) | ❌ EMPTY | ✅ Works (3 calls, 21s) | Complex analysis |
| kimi-k2.6:cloud | 13s+ | Yes (eats tokens) | Content often empty | Untested | ❌ BROKEN (0 calls, timeout) | Direct API only |
| glm-5.1:cloud | 13s | Yes (eats tokens) | Content often empty | OK | ⚠️ Slow, works | Main conversation |

## Critical Pitfalls

1. **Reasoning models eat max_tokens**: Models with `reasoning` field (deepseek, kimi, glm) consume tokens for chain-of-thought BEFORE the visible content. If `max_tokens` is too low (e.g., 300), the content field comes back EMPTY because all tokens went to reasoning. Fix: set `max_tokens` to 600+ for reasoning models.

2. **German doesn't work for all models**: deepseek-v4-flash:cloud returns EMPTY for German prompts. Use ENGLISH prompts for coding subagents regardless of user language.

3. **kimi-k2.6:cloud delegation is broken**: Direct API calls work, but `delegate_task` times out with 0 API calls. Cause unclear. Do NOT use for delegation.

4. **Delegation config is in `/opt/data/config.yaml`** under `delegation:` key — model, provider, base_url, api_key, max_concurrent_children.

## Configuring Best Model for Delegation

```yaml
delegation:
  model: qwen3-coder-next:cloud
  provider: custom
  base_url: http://host.docker.internal:11434/v1
  api_key: ollama
  inherit_mcp_toolsets: true
  max_concurrent_children: 2
  max_iterations: 50
  reasoning_effort: low
```

## Role Assignment Strategy

- **Coding subagents** → `qwen3-coder-next:cloud` (fast, no token waste, clean output)
- **Analysis/reasoning subagents** → `deepseek-v4-flash:cloud` with EN prompts + max_tokens 800+
- **Main conversation** → `glm-5.1:cloud` (current model, stays as is)
- **Direct API-only analysis** → `kimi-k2.6:cloud` (never use for delegation)