---
name: autonomous-heartbeat
description: 4-phase autonomous agent heartbeat — WATCH → WORK → LEARN → DREAM cycle for self-improving, self-monitoring agents
tags: [autonomous, agent, cronjob, heartbeat, self-improving, monitoring]
diagram: |
  graph LR
      Pulse((Pulse)) --> HealthCheck["Health Check"]
      HealthCheck --> Action["Execute Tasks"]
      Action --> Sleep["Sleep — Wait Next Cycle"]
      Sleep --> Pulse
      style Pulse fill:#1a1a2e,stroke:#e94560,color:#fff
      style HealthCheck fill:#16213e,stroke:#22d3ee,color:#fff
      style Action fill:#16213e,stroke:#34d399,color:#fff
      style Sleep fill:#1a1a2e,stroke:#a78bfa,color:#fff
---

# Autonomous Heartbeat — 4-Phase Cycle

A self-improving agent doesn't just execute tasks — it monitors its environment, learns between cycles, and ideates about the future.

## The 4 Phases

### Phase 0: WATCH (Health Check)
**Always run first — health before new work.** Check that everything is still running:

1. `git pull` — repo in sync
2. Run full test suite — all tests must pass. If any fail, investigate and fix BEFORE moving on.
3. Check running processes: Docker containers, background services, LiteLLM/API proxies
4. Health-check critical services: `curl` health endpoints (e.g., `http://127.0.0.1:4000/health`)
5. Check disk space (`df -h`) — warn if >90%
6. Check for crash logs: recent `.log` files, `journalctl` errors
7. If background agents were spawned in previous cycles, check their output/status
8. Append health report to a watchdog log with timestamp and per-check status

**Critical issues (broken tests, down services, full disk) → FIX first before continuing.**
**Non-critical issues → report but continue to WORK.**

### Phase 1: WORK (Execution)
- Pick next item from backlog/issues
- Implement, test, commit, push
- Update persistent context (AGENT_CONTEXT.md or equivalent)

### Phase 2: LEARN (Training)
Scan upcoming work and identify technologies/patterns you could train on NOW to be faster later:

- Look at the next 2-3 items in the backlog
- For each, identify 1-2 patterns or APIs you haven't used yet
- Build a tiny prototype (10-30 lines) that exercises the pattern
- Save what you learned as notes

**Training examples:**
- Next is Telegram Gateway → build a tiny Bun HTTP server receiving webhooks
- Next is Session Storage → prototype FTS5 full-text search queries
- Next is Plugin System → try dynamic import() patterns
- Next uses OAuth → prototype the auth flow with a mock server

### Phase 3: DREAM (Ideation + Presentation)
Look at the full project landscape and:

1. **Gaps** — things not covered by any issue but that would make the system better
2. **Risks** — what could break when features are combined?
3. **Shortcuts** — what existing tools/skills/libraries could accelerate upcoming work?
4. **Ideas** — generate 2-3 concrete ideas with a one-paragraph pitch each
5. Append to a dreams log with timestamp
6. **Presentation** — After every WORK phase that produced a commit:
   - Create a presentation slide deck (.pptx) or infographic summarizing what was built
   - Use `powerpoint` skill for slide decks (architecture, progress, demos)
   - Use `baoyu-infographic` skill for visual summaries (architecture diagrams, feature overviews)
   - Save to `/tmp/toti-training/presentations/` with date prefix (e.g., `2026-05-04-tool-registry.pptx`)
   - Presentation should cover: What was built, How it works, Architecture/flow, What's next
   - This creates a living documentation trail that makes progress visible

## Cronjob Setup

Use Hermes cronjob tool with a prompt that encodes all 3 phases:

```
schedule: every 6h
repeat: 8  (or appropriate count)
deliver: local  (no user interruption needed)
```

Key rules for the prompt:
- Always `git pull` before starting
- Always commit + push work results
- Never break existing tests
- If stuck >10 min, skip and move to next phase
- Write code/docs in English, user-facing messages in user's language
- Training output goes to a dedicated directory (e.g., `/tmp/<project>-training/`)
- Dream output goes to a dated log (e.g., `dreams.md`)

## Why This Works

1. **WATCH phase** catches degradation early — broken tests, crashed services, full disks — before they compound
2. **LEARN phase** prevents the agent from being overwhelmed by unfamiliar tech when it finally hits that issue — it's already seen the patterns
2. **DREAM phase** catches gaps early, before they become blockers
3. The cycle structure means each wakeup has clear priorities, not just "work on something"
4. The dreams log becomes a backlog of ideas the user can triage

## Priority Hierarchy

**Agent infrastructure is always Rank 1.** The heartbeat exists to prove and improve the agent system itself. Any project work (even user requests) is secondary to ensuring the agent delegation pipeline works correctly. If an agent fails, diagnosing and fixing the agent infrastructure takes precedence over the project task.

In practice:
- If a delegated agent times out or produces errors → fix the delegation workflow first
- If tests break → fix before new features
- If services are down → restore before anything else
- Project code is the test field for agent quality, not the goal itself

## RAM & Resource Management (CRITICAL)

**This section was added after a 15GB RAM spike killed the Docker container and caused 10 days of downtime.**

### Hard Limits
- Docker containers have hard memory limits. An OOM kill kills everything — no graceful degradation.
- Always know your container's memory limit (`cat /sys/fs/cgroup/memory.max`). Never exceed 75% of it.
- Example: 8GB limit → safety threshold is 5-6GB used. Above that, STOP all work and run cleanup.

### RAM Budget for Heartbeat Cycles
A heartbeat cycle must stay within a memory budget:

| Component | Typical RAM | Mitigation |
|---|---|---|
| Hermes gateway | ~350MB | Fixed, unavoidable |
| `bun install` / `bun test` | ~200-400MB | Transient, free after exit |
| Git clone/pull | ~50-100MB | Transient |
| Browser sessions | **500MB-2GB each** | **NEVER use browser in heartbeat** |
| Subagents (Codex, Claude Code) | ~200-500MB each | Limit concurrent agents |
| Python deps / pip cache | ~100-300MB | Clean caches regularly |

### Mandatory RAM Checks
1. **Before each phase**: Run `free -h` and check `used` memory
2. **If >75% of limit used**: ABORT the cycle. Do cleanup instead:
   - `ps aux --sort=-%mem | head -10` — identify top consumers
   - Kill zombie/defunct processes: `ps aux | grep -E 'Z|defunct'`
   - Clean caches: `rm -rf ~/.cache/pip ~/.cache/bun ~/.cache/npm /tmp/__pycache__`
   - Clean `/tmp/` lock files and stale data
3. **After each phase**: Re-check RAM. If it spiked, note which phase caused it.

### Anti-Patterns That Cause OOM
- **Browser usage in crons** — headless Chromium eats 500MB-2GB per session. NEVER use `browser_navigate` or `browser_click` in heartbeat cycles.
- **Consecutivebun install without cleaning** — node_modules caches accumulate
- **Multiple subagents spawning simultaneously** — each adds ~200-500MB
- **Large git repos left in /tmp/** — clean up old clones
- **Accumulated watchdog/training logs** — prune files older than 7 days

### System Cleanup Cron
Set up a separate daily cleanup cron (e.g., `0 3 * * *`) that:
- Removes `/tmp/` files older than 2 days (excluding active project dirs)
- Clears Python caches (`__pycache__`, `.pyc`)
- Removes stale lock files (`uv-setuptools-*.lock`)
- Clears pip/bun/npm caches if disk or RAM is tight
- Kills zombie processes

## Pitfalls

- WATCH phase must run FIRST — never skip health checks for new work
- Don't let LEARN phase spiral — cap at 1-2 prototypes per cycle
- Don't let DREAM phase become noise — only generate ideas with concrete actionability
- The cronjob prompt must be self-contained (no chat context carries over)
- Test counts must be checked during WATCH — if tests drop, fix before WORK
- Training prototypes are throwaway — don't let them pollute the main codebase
- Watchdog reports accumulate — clean old ones periodically or they fill disk
- **Don't hand-code project work yourself when the task is testing agent delegation** — delegate to agents and validate their output instead
- **CRITICAL: Never use browser tools in heartbeat cronjobs** — Chromium is the #1 RAM killer in automated cycles
- **CRITICAL: Always check RAM before AND after each phase** — an OOM kill wipes all progress and causes days of downtime
- **CRITICAL: Know your Docker memory limit** — hard OOM kills are unrecoverable; stay under 75%
- **CRITICAL: config.yaml base_url inside Docker** — `127.0.0.1:PORT` does NOT work inside a Docker container (points to container loopback, not host). Use `host.docker.internal` for URLs that need to reach the host machine.
- **CRITICAL: Subagent model choice** — Use `deepseek-v4-flash:cloud` for coding subagents. It's the most reliable cloud model for delegation. `qwen3-coder-next:cloud` works for direct API calls but times out in delegation. `kimi-k2.6:cloud` ALWAYS times out with 0 API calls in delegation — NEVER use it. Local models no longer exist — all models are cloud-only (glm-5.1:cloud, glm-5:cloud, kimi-k2.6:cloud, kimi-k2.5:cloud, deepseek-v4-flash:cloud).
- **CRITICAL: Coding prompts must be in ENGLISH** — deepseek-v4-flash returns EMPTY for German prompts. Always write subagent coding prompts in English.
- **CRITICAL: Set max_tokens ≥ 600** for reasoning models in delegation, otherwise reasoning eats all tokens
- **CRITICAL: max_concurrent_children MUST be 1** — parallel delegation causes child agents to time out with 0 API calls. Always run subagents sequentially.
- **CRITICAL: lofty crate v0.19** — only has features: default, id3v2_compression_support. No format-specific features exist (no mp3, flac, vorbis, opus, mp4, ape, wma, picture).
- **CRITICAL: Git push in cron DOES work now** — git-credentials has been populated with GitLab PAT. Sentinel branches and backups can push to GitLab.
- **CRITICAL: Docker networking** — Inside a Docker container, `127.0.0.1` points to the container itself, NOT the host. Use `host.docker.internal` to reach host services (Ollama, LiteLLM proxy, etc.). NEVER change base_url to `127.0.0.1:PORT` inside a container — it will break model connectivity.
- **CRITICAL: Cronjob repeat count** — Default `repeat` for cronjobs may be low (e.g. 2/12 = stops after 2 runs). Always set `repeat` to a high number (365+) or `forever` for long-running autonomous jobs.
- **CRITICAL: Tauri 2 compilation on Linux ARM64** — requires system packages: `sudo apt install pkg-config libgtk-3-dev libglib2.0-dev libcairo2-dev libpango1.0-dev libgdk-pixbuf-xlib-2.0-dev libatk1.0-dev libjavascriptcoregtk-4.1-dev libsoup-3.0-dev libwebkit2gtk-4.1-dev libasound2-dev`. Install BEFORE attempting cargo check/build.
- **CRITICAL: Never code yourself when the task is delegation testing** — If the agent infrastructure fails, diagnose and fix the infrastructure, don't fall back to manual coding. The user's explicit rule: "never do it yourself, fix the agents instead."

## Minimal Docker Environment Pitfalls (CRITICAL)

Some Docker environments have extremely limited shell tooling — no `git`, `cat`, `find`, `sort`, `tail`, `python3`, `npm` in PATH. Workarounds:

- **Git**: Usually at `/usr/bin/git` even if not in PATH. Use Python `subprocess` module to call it.
- **Bun**: At `/opt/data/home/.bun/bin/bun`. Always `export PATH="$PATH:/opt/data/home/.bun/bin"` first.
- **File I/O — NEVER use hermes `write_file` tool in heartbeat cycles**: It can silently zero out files (zero-byte content) while reporting errors. Use `patch()` tool or Python `open()` / `write()` instead.
- **File reads — prefer Python `open()`**: The hermes `read_file` tool sometimes returns empty content for non-empty files. Verify with Python if results seem wrong.
- **File search**: `search_files` requires `rg` or `find` which may not be installed. Use Python `os.walk()` + `open()` as fallback.
- **Process monitoring**: `free` may not be in PATH. Use `subprocess.run(["free", "-h"], capture_output=True)` or read `/proc/meminfo` directly.
- **GitLab auth**: Use `git -c http.extraHeader="PRIVATE-TOKEN: <PAT>"` for clone/pull/push operations.
- **Zombie processes**: In Docker, many zombie processes (git, esbuild, sh) accumulate as children of PID 1. They can't be reaped. Monitor with `ps aux | grep Z` but don't waste time — they use negligible RAM.

### Safe File Editing in Heartbeat Cycles

| Method | Risk | Recommendation |
|---|---|---|
| `patch()` tool | Low — targeted find/replace | ✅ Preferred for small changes |
| Python `open()` + write | Low — explicit | ✅ Preferred for new files, full rewrites |
| `write_file` tool | **HIGH — can zero files** | ❌ NEVER use in automated cycles |
| `read_file` tool | Medium — may return empty | ⚠️ Verify with Python if suspicious |