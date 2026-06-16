---
name: claude-code-cron-orchestrator
description: Run Claude Code autonomously via cron — spawn background agents, auto-commit uncommitted changes after build, auto-tag and release on GitHub. Full dev cycle automation without human intervention.
version: 1.0.0
author: Mercury
license: MIT
metadata:
  hermes:
    tags: [cron, claude-code, ollama, automation, orchestration, minecraft-fabric]
    related_skills: [claude-code, mercury-heartbeat, github-pr-workflow]
---

# Claude Code Cron Orchestrator

Run Claude Code via `ollama launch` in **background cron jobs** — autonomous dev cycle without human intervention. Agents code, build, commit, tag, and release entirely on their own.

## Why This Exists

Using `ollama launch claude` for automation has several pitfalls discovered through trial and error:
- `--dangerously-skip-permissions` must go AFTER `--` separator (ollama flags before, Claude Code flags after)
- Cron tasks have no TTY — stdin piping is the only way to pass tasks
- Uncommitted changes from a failed/partial agent run block the next agent
- The `-p` (print) flag doesn't exist on newer ollama versions — pipe tasks via stdin instead

## Architecture Pattern

```
cron (every 10m)
  └─ orchestrator.sh
       ├─ 1. Lock (flock) — no parallel runs
       ├─ 2. Check running agents — max N parallel
       ├─ 3. Uncommitted changes? → Build → Auto-commit + push DIRECTLY (NO ready-flag)
       ├─ 4. Free slots? → Filter out issues that already have git tags → start agent for next open issue
       └─ 5. Agent does: code → build → git add+commit+push (agents are trusted to commit)
```

## Key Lessons Learned (Hard-Won)

1. **🚨 Ready-Flag pattern is unreliable.** The orchestrator wrote ready-flags to `$READY_FLAG` path, but the Mercury commit watcher looked at a different path. Ready-flags piling up, never consumed, infinite loop. **Fix:** Orchestrator commits+pushes directly after successful build. No ready-flag.

2. **🚨 "Agents never commit" causes infinite uncommitted-changes loops.** When agents are told NOT to commit, every agent run leaves uncommitted changes. The next orchestrator cycle finds them, builds (which may change gradle.properties), commits a generic "fix: uncommitted changes" message — losing connection to the original issue. **Fix:** Agents DO commit after successful build (`git add -A && git commit -m "feat: implement Issue #N ... [skip ci]" && git push`).

3. **🚨 Open-but-implemented issues spawn infinitely.** If an issue is OPEN on GitHub but already has a git tag (was implemented/released but never closed), the orchestrator spawns a new agent every cycle — wasting resources. **Fix:** Check `git tag -l "v*$(printf '%02d' $ISSUE_NUM)"` before spawning, skip if tag exists.

4. **🚨 `gh` CLI not in cron PATH.** Inside the orchestator script, `gh` must be called with explicit full path or PATH must include `/opt/data/home/bin`. Without this, `gh issue list` silently returns empty. **Fix:** Always set `PATH="/opt/data/home/bin:$PATH"` or use `/opt/data/home/bin/gh` explicitly in scripts.

## Prerequisites

- `ollama` CLI installed (`/usr/local/bin/ollama`)
- Claude Code installed and accessible (via PATH or configured in ollama)
- `gh` CLI installed and authenticated with GitHub
- `flock` (util-linux) for locking

## Critical Syntax: The `--` Separator

This is the most important and most error-prone detail.

```bash
# ✅ CORRECT — ollama flags BEFORE --, Claude Code flags AFTER --
echo 'task' | ollama launch claude --model deepseek-v4-flash:cloud -y -- --dangerously-skip-permissions

# ❌ WRONG — --dangerously-skip-permissions is passed to ollama, not Claude Code
echo 'task' | ollama launch claude --dangerously-skip-permissions -y
```

| Part | What it does |
|------|-------------|
| `ollama launch claude` | Launch Claude Code via ollama integration |
| `-y` | Ollama flag: auto-confirm launch prompts |
| `--model <model>:cloud` | Ollama flag: which cloud model to use |
| `--` | **Separator** — everything after is for Claude Code, not ollama |
| `--dangerously-skip-permissions` | Claude Code flag: auto-approve ALL tool use |

Without `--`, `--dangerously-skip-permissions` is treated as an **ollama** flag and fails with `Error: unknown flag`.

## The Full Orchestrator Script

### Shell Script Template

```bash
#!/bin/bash
# Claude Code Multi-Agent Orchestrator
set -euo pipefail

# === Config ===
REPO_DIR="/path/to/repo"
OLLAMA_BIN="/usr/local/bin/ollama"
MODEL="deepseek-v4-flash:cloud"  # Use :cloud suffix for Ollama Cloud models
JAVA_HOME="/path/to/java"        # Set if project needs specific JDK
LOG_FILE="/tmp/orchestrator.log"
MAX_AGENTS=3
LOCK_FILE="/tmp/orchestrator.lock"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Must be set for container environments
export OLLAMA_HOST=http://host.docker.internal:11434
export TZ='Europe/Berlin'

# === Lock ===
exec 200>"$LOCK_FILE"
flock -n 200 || { echo "[$TIMESTAMP] ⏳ Läuft bereits"; exit 0; }
trap 'rm -f "$LOCK_FILE"' EXIT

echo "[$TIMESTAMP] 🚀 Orchestrator gestartet" | tee -a "$LOG_FILE"

# === Count running agents ===
AGENT_COUNT=$(pgrep -f "ollama launch claude" 2>/dev/null | grep -c . || true)
echo "[$TIMESTAMP] 🤖 $AGENT_COUNT/$MAX_AGENTS aktiv" | tee -a "$LOG_FILE"

cd "$REPO_DIR"

### Auto-commit uncommitted changes (build first!) ===
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "[$TIMESTAMP] 📦 Uncommitted Changes" | tee -a "$LOG_FILE"
    
    if JAVA_HOME="$JAVA_HOME" ./gradlew build 2>&1 | tail -5 >> "$LOG_FILE"; then
        # ✅ DIRECT COMMIT — no ready-flag, no waiting for Mercury.
        # The orchestrator commits+pushes immediately after successful build.
        # This prevents uncommitted-changes loops that plagued the ready-flag approach.
        # Use `git add -A` (NOT `git add .`) to catch ALL changes including new untracked files.
        git add -A
        git commit -m "fix: uncommitted changes from failed agent [skip ci]"
        git push origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE"
        echo "[$TIMESTAMP] ✅ Committed & gepusht" | tee -a "$LOG_FILE"
        rm -f "$READY_FLAG" 2>/dev/null || true  # Clean up stale ready-flag
    else
        echo "[$TIMESTAMP] ❌ Build fehlgeschlagen — uncommitted changes bleiben liegen" | tee -a "$LOG_FILE"
    fi
fi

# === Start agents for open issues — skip already-released ones ===
AVAILABLE=$((MAX_AGENTS - AGENT_COUNT))
[ "$AVAILABLE" -le 0 ] && exit 0

for i in $(seq 1 "$AVAILABLE"); do
    IDX=$((i - 1))
    ISSUE_NUM=$(/opt/data/home/bin/gh issue list --state open --limit 10 --json number,title 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$IDX]['number'] if len(d)>$IDX else '')" 2>/dev/null || echo "")
    ISSUE_TITLE=$(/opt/data/home/bin/gh issue list --state open --limit 10 --json number,title 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$IDX]['title'] if len(d)>$IDX else '')" 2>/dev/null || echo "")
    
    [ -z "$ISSUE_NUM" ] && break
    
    # 🚨 Skip if issue already has a matching tag (prevents infinite re-spawn)
    TAG_PATTERN=$(printf "v*%02d" "$ISSUE_NUM")
    if git tag -l "$TAG_PATTERN" | grep -q . 2>/dev/null; then
        echo "[$TIMESTAMP] ⏭️  Issue #$ISSUE_NUM already tagged — skipping" | tee -a "$LOG_FILE"
        continue
    fi
    
    echo "[$TIMESTAMP] 🎯 Issue #$ISSUE_NUM → Agent" | tee -a "$LOG_FILE"
    
    # Pipe task to Claude Code in background
    echo "Implementiere Issue #$ISSUE_NUM - $ISSUE_TITLE in $REPO_DIR.
    
    REGELN:
    - ✅ CODE SCHREIBEN, BAUEN, COMMITTEN und PUSHEN
    - Nach erfolgreichem Build: git add -A && git commit && git push
    
    ARBEITSSCHRITTE:
    1. Code schreiben: Implementiere die Anforderungen laut Issue.
    2. Bauen: JAVA_HOME=$JAVA_HOME ./gradlew build
    3. Bei Erfolg: git add -A && git commit -m 'feat: implement Issue #$ISSUE_NUM - $ISSUE_TITLE [skip ci]' && git push origin $BRANCH
    4. Bei Fehler: Änderungen liegen uncommitted — Orchestrator kümmert sich darum" | \
    $OLLAMA_BIN launch claude --model "$MODEL" -y -- --dangerously-skip-permissions > /dev/null 2>&1 &
    
    sleep 10
done
done
```

### Cron Setup

```bash
# Every 10 minutes
*/10 * * * * bash /path/to/orchestrator.sh

# Or use Hermes cron
cronjob(action="create", schedule="every 10m", name="claude-orchestrator", prompt="Run: bash /path/to/orchestrator.sh")
```

## Fabric Mod Release Best Practices

When Claude Code creates GitHub releases for Fabric mods:

1. **Only upload the main JAR** — not the `-sources.jar`:
   ```bash
   MAIN_JAR=$(ls build/libs/*.jar | grep -v sources | head -1)
   gh release create "$TAG" --title "..." "$MAIN_JAR"
   ```

2. **The "Source code (zip)" on GitHub** are automatically generated by GitHub for every tag. They are NOT the mod — players should never download them. The JAR under "Assets" is the real mod.

3. **Release notes should clarify:**
   ```markdown
   ## 🎮 Installation (1 Minute)

   ### 1️⃣ Fabric installieren
   → https://fabricmc.net/use/ (Version 1.21)

   ### 2️⃣ Fabric API hinzufügen
   → https://modrinth.com/mod/fabric-api — in den `mods/`-Ordner legen

   ### 3️⃣ Workers' Collective installieren
   - **⬇️ JAR unten runterladen**
   - In den `mods/`-Ordner kopieren:
     - **Windows:** `%appdata%/.minecraft/mods/`
     - **macOS:** `~/Library/Application Support/minecraft/mods/`
     - **Linux:** `~/.minecraft/mods/`
   - Minecraft starten (Fabric-Profil) → **Fertig! 🚀**

   ---

   ## ✨ Was ist neu
   ```

4. **Tag naming convention:** `v<major>.<minor>.<patch>` — e.g. `v0.5.09`.

## Background Process Management

When running agents in the background from cron:

```bash
# Start agent in background (disowned)
echo 'task' | ollama launch claude -y -- --dangerously-skip-permissions > /dev/null 2>&1 &

# Track via Hermes terminal
terminal(
  command="echo 'task' | ollama launch claude -y -- --dangerously-skip-permissions 2>&1",
  background=true,
  notify_on_complete=true,
  timeout=300
)

# Check running agents later
pgrep -f "ollama launch claude"

# Kill stuck agents
pkill -f "ollama launch claude"
```

The `> /dev/null 2>&1 &` pattern disowns the process from the shell so it survives the cron job exiting. For Hermes' terminal tool, use `background=true`.

## Known Pitfalls

1. **`-p` / `--print` flag doesn't exist in ollama 0.23+** — Use stdin piping instead: `echo 'task' | ollama launch claude ...`
2. **Cron has a minimal PATH** — Always set `PATH` explicitly including `/opt/data/home/bin` and where `gh` / `claude` / `ollama` live. Inside the orchestrator script, call `gh` as `/opt/data/home/bin/gh` rather than relying on PATH.
3. **🚨 [CRITICAL] Ready-Flag pattern is BROKEN** — The two-component design (orchestrator writes ready-flag → separate cron reads it) is fragile. Paths get out of sync, flags pile up, no one consumes them. **Use DIRECT commit instead: `git add -A && git commit && git push` after successful build.**
4. **🚨 [CRITICAL] "Agents never commit" causes infinite loops** — If agents are told not to commit, every agent run leaves uncommitted changes, the next cycle finds them, builds (possibly bumping version), and commits a generic message. **Fix: Agents commit after build success.**
5. **🚨 [CRITICAL] Open-but-implemented issues spawn infinitely** — The orchestrator checks `gh issue list --state open` but does NOT check if that issue already has a release/tag. An issue that was completed (tagged & released) but never closed will re-spawn on every cycle. **Fix:** Check `git tag -l "v*$(printf '%02d' $ISSUE_NUM)"` before spawning.
6. **🚨 pgrep race condition on agent counting** — The `AGENT_COUNT` runs BEFORE new agents actually spawn (takes 5-15s). **Fix:** Count before AND after spawning, or use a state file, or add a cooldown check.
12. **🚨 `git diff` returns empty for recently-committed changes** — After agents push, `git diff --name-only HEAD` shows nothing. Use `git diff HEAD~1 --name-only` or `git diff --cached --name-only`.

13. **🚨 [CRITICAL] `git diff-index --quiet HEAD` ignores staged changes!** — `git diff-index --quiet HEAD` compares the worktree (unstaged) against the index, so `git add -A` (stage) + NO commit is NOT detected. An agent that runs `git add -A` but then crashes before committing leaves staged changes invisible to the orchestrator. **Fix:** Use `git status --porcelain` which detects BOTH staged (`M `) and unstaged (` M`) changes:
    ```bash
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        CHANGED=$(git status --short)
        ...
        git add -A && git commit && git push
    fi
    ```
8. **🚨 CHANGELOG merge conflicts** — When both agents and orchestrator touch CHANGELOG.md. **Fix:** Single owner for CHANGELOG — either agents always write it, or orchestrator is the sole writer.
9. **Build before commit** — Never auto-commit if the build fails. Failed commits pollute git history.
10. **Always use `flock`** — Without a lockfile, overlapping cron runs start multiple orchestrator instances.
11. **OLLAMA_HOST in containers** — Inside Docker, always set `export OLLAMA_HOST=http://host.docker.internal:11434` because ollama daemon runs on the host.
