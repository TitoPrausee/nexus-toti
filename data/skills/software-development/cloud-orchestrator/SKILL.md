---
name: cloud-orchestrator
description: >
  Multi-agent system on Ollama Cloud. Use when the user requests a complex task
  with 3+ phases, spans multiple domains, or benefits from adversarial review.
  Routes each subtask to the best-fit Ollama Cloud model and coordinates via a
  shared scratchpad.
version: 1.0.0
---

# Cloud Orchestrator — Multi-Agent System on Ollama Cloud

## When to Use

Activate when **any** of these are true:
- Task has 3+ distinct phases (analysis → design → execution → review)
- Task spans multiple domains (research + code + writing)
- User explicitly asks for "a team", "multiple agents", "Multi-Agent", "Agentensystem"
- Task is large enough that one model call loses context/quality
- Task benefits from adversarial review (critique, QA, fact-checking)

Do **NOT** activate for:
- Simple Q&A, single-shot lookups, or trivial tasks
- Tasks that already have a dedicated skill (defer to that skill)
- Tasks where the user wants to drive every step manually

## Quick Reference — Model Routing Table

| Role / Task Type              | Primary Model                     | Fallback                   |
|-------------------------------|-----------------------------------|----------------------------|
| Orchestrator / Planning       | `glm-5.1:cloud`                   | `deepseek-v4-pro:cloud`    |
| Deep reasoning / Analysis     | `deepseek-v4-pro:cloud`           | `kimi-k2.6:cloud`          |
| Long-context (>200K tokens)   | `deepseek-v4-flash:cloud`         | `deepseek-v4-pro:cloud`    |
| Coding (agentic, multi-file)  | `qwen3-coder-next:cloud`          | `devstral-2:123b-cloud`    |
| Coding (small/fast)           | `devstral-small-2:24b-cloud`      | `qwen3-coder-next:cloud`   |
| Vision / Multimodal           | `kimi-k2.6:cloud`                 | `gemma4:31b-cloud`         |
| Audio understanding           | `gemma4:31b-cloud`                | —                          |
| Creative writing / Roleplay   | `kimi-k2.6:cloud`                 | `qwen3.5:122b-cloud`       |
| Research / Long synthesis     | `minimax-m2.7:cloud`              | `glm-5:cloud`              |
| Critique / QA review          | `nemotron-3-super:120b-cloud`     | `glm-5.1:cloud`            |
| Fast utility / triage         | `nemotron-3-nano:30b-cloud`       | `qwen3.5:9b-cloud`         |
| General-purpose worker        | `qwen3.5:27b-cloud`               | `gemma4:26b-cloud`         |

## Procedure

### Phase 1 — Decompose

Do NOT execute the task yourself. Write a decomposition plan with:

1. **Task summary** (1–2 sentences in the user's language)
2. **Sub-agent roster** (min 2, max 6). For each agent:
   - Role name (e.g. Researcher, Architect, Implementer, Critic)
   - Assigned Ollama Cloud model from routing table
   - Single concrete deliverable
   - Inputs needed from prior agents
3. **Execution order** — pipeline, fan-out/fan-in, debate, or hybrid
4. **Termination criteria** — what does "done" look like?

Show plan to user before spawning. Skip confirmation only if user said "just go" or `auto_confirm: true`.

### Phase 2 — Spawn Sub-Agents

For each sub-agent, use `delegate_task` with this structure:

```python
goal: "[ROLE] You are the <Role>. [GOAL] <single deliverable>"
context: "Relevant prior outputs from scratchpad."
toolsets: ["terminal", "file"]
```

Set the ACP command to run the Ollama Cloud model:

```python
acp_command: "ollama"
acp_args: ["run", "<model>:cloud"]
```

Each sub-agent writes its output. The orchestrator appends it to the scratchpad.

### Phase 3 — Inter-Agent Communication

Sub-agents do NOT call each other directly. All communication flows through the orchestrator via the scratchpad format:

```markdown
## [run-id] <timestamp>
### Agent: <Role> | Model: <model>:cloud
### Status: complete | blocked | needs_input
### Output:
<deliverable>
### Hand-off to: <next role>
```

If an agent returns `NEED_CLARIFICATION`, the orchestrator decides:
- Can another agent answer this? → route the question
- Is it a user-only decision? → ask user, then resume
- Is it ambiguous? → make a reasonable assumption, log it, continue

### Phase 4 — Critique Loop (mandatory for non-trivial tasks)

After implementers finish, **always** spawn a Critic using `nemotron-3-super:120b-cloud`. The Critic produces:

```markdown
## Critique
### Strengths: ...
### Issues (severity: blocker | major | minor):
- [blocker] ...
- [major] ...
### Recommended fixes: ...
### Verdict: ship | revise | redo
```

- **revise** → route issues back to the relevant agent for one (1) fix pass
- **redo** → escalate to user before re-running
- **ship** → proceed to synthesis

### Phase 5 — Synthesize and Deliver

Write the final answer including:
- The deliverable itself
- "How this was built" — each agent + model used
- Any assumptions made on the user's behalf

## Orchestration Patterns

| Pattern        | Description                                    | Use Case                        |
|----------------|------------------------------------------------|---------------------------------|
| **Pipeline**   | A → B → C → D, sequential                      | Linear workflows                |
| **Fan-out/in** | Split across N parallel, then merge            | Independent subtasks            |
| **Debate**     | Two sides argue, judge decides                | Architecture/library choices    |
| **Hierarchical**| Managers spawn sub-teams                      | >6 agents (rarely needed)       |

## Pitfalls

- ❌ Do not do the work yourself. Delegate.
- ❌ Cloud model auth fails → surface to user immediately, don't retry
- ❌ Never paste entire scratchpad into every agent. Pass only relevant context.
- ❌ Cap critique at 1 revise pass. Ship with known issues documented.
- ❌ Language drift: if user wrote in German, every prompt must say "Antworte auf Deutsch."
- ❌ Tag drift: ollama cloud model tags change. Verify with `ollama list` if tags fail.

## Verification Checklist

Before declaring done, verify:
1. ✅ Every agent produced a deliverable (or skipped with reason)
2. ✅ Critic verdict is `ship` or `revise` (not `redo`)
3. ✅ Final output addresses the original request
4. ✅ All scratchpad entries saved to `runs/<run-id>/`
5. ✅ Created files exist and are non-empty

## Configuration

Optional overrides in `~/.hermes/config.yaml`:

```yaml
skills:
  cloud-orchestrator:
    default_critic_model: nemotron-3-super:120b-cloud
    max_agents_per_run: 6
    auto_confirm_plan: false
    scratchpad_dir: ~/.hermes/skills/cloud-orchestrator/runs
    revise_passes: 1
```

## Example

**User:** *"Bau mir eine Landing Page für mein Stanced Fiction Projekt — modern, animiert, Volvo-Vibes."*

```markdown
Task: Animated landing page for Stanced Fiction (automotive AI Instagram brand).

Roster:
1. Creative Director  → kimi-k2.6:cloud        → Mood, color palette, copy
2. Architect          → glm-5.1:cloud           → Structure, tech stack
3. Developer          → qwen3-coder-next:cloud   → HTML/CSS/JS file
4. Critic             → nemotron-3-super:120b-cloud → Review

Order: Pipeline (1 → 2 → 3 → 4)
Done: HTML renders, verdict is "ship"
```

## References
- [Ollama Cloud Models](https://ollama.com/search?c=cloud)
- [Ollama Cloud Docs](https://docs.ollama.com/cloud)
