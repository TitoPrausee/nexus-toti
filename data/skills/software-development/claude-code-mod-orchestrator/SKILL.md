---
name: claude-code-mod-orchestrator
description: Automated Minecraft Mod development pipeline — scans open GitHub issues, dispatches Claude Code agents (Ollama Cloud), builds, and signals Mercury to commit. Agents NEVER commit/push themselves.
version: 2.0.0
author: Hermes Agent
tags: [minecraft, fabric, automation, claude-code, ollama, orchestration, cron, git-identity]
related_skills: [minecraft-mod-project-workflow, subagent-driven-development, github-issues, github-pr-workflow]
---

# Claude Code Mod Orchestrator

Automated Minecraft mod development pipeline. Scans open GitHub issues → dispatches Claude Code agents → builds → signals Mercury to commit & push.

## 🛑 CRITICAL — Agents NEVER Commit/Push

**This is the single most important rule.** Claude Code agents will use their own identity (e.g. "Henry (OpenClaw Agent)", "Claude", "Mercury") for commits unless explicitly prevented.

**Rule:** Agents implement + build ONLY. Mercury (the orchestrator, as <GITHUB_USER>) commits and pushes.

- ✅ Code implementieren
- ✅ `JAVA_HOME=... ./gradlew build`
- 🚫 KEIN `git add`, `git commit`, `git push`, `git tag`
- 🚫 KEIN `gh release create`
- Nach Build fertig — Änderungen liegen uncommitted da
- Orchestrator legt Ready-Flag ab → Mercury committed + pusht

## Architecture

```
Cron (60 min — reduced for token economy)
  └── orchestrator.sh
        ├── 1. Check running agents (max 3 concurrent)
        ├── 2. Check uncommitted changes → build → write ready_to_commit.json
        ├── 3. Fetch next open issues
        └── 4. Launch Claude Code agent per issue (implement+build only)
```

## Token Economy — Sparmodus

When tokens are limiting (e.g. weekly limit almost reached):

| Service | Normal | Sparmodus | Savings |
|---------|--------|-----------|---------|
| claude-orchestrator | alle 10 Min | stündlich | -83% |
| workers-collective-dev | alle 60 Min | alle 4h | -75% |
| fitspar-coach-dev | alle 60 Min | ⏸️ pausiert | -100% |
| fitspar-retro-ui-dev | alle 60 Min | ⏸️ pausiert | -100% |
| project-dashboard | alle 10 Min | stündlich | -83% |
| issue-watcher | alle 30 Min | stündlich | -50% |

**Priority order:** Workers Collective > Issue Watcher > Dashboard > Heartbeat > Coach/Retro

## Prerequisites

- GitHub repo with issues + milestones created
- `gh` CLI authenticated (`/opt/data/home/bin/gh`)
- `ollama` installed and configured for Cloud
- `OLLAMA_HOST=http://host.docker.internal:11434` for containerized setups
- `JAVA_HOME` pointing to JDK 21
- `TZ='Europe/Berlin'` if timezone needs fixing
- **Default branch must be `master`** (change from `main` via GitHub API PATCH)

## The Orchestrator Script

Save as `/opt/data/home/.mercury/claude_orchestrator.sh`:

```bash
#!/bin/bash
set -euo pipefail

REPO_DIR="/opt/data/home/workers-collective"
BRANCH="master"  # NOT main!
OLLAMA_BIN="/usr/local/bin/ollama"
MODEL="deepseek-v4-flash:cloud"
JAVA_HOME="/opt/data/home/.local/java/jdk-21.0.11+10"
PATH="/opt/data/home/bin:/opt/data/home/.local/bin:/usr/local/bin:/usr/bin:/bin"
LOG_FILE="/opt/data/home/.mercury/orchestrator.log"
READY_FLAG="/opt/data/home/.mercury/ready_to_commit.json"
MAX_AGENTS=3
LOCK_FILE="/tmp/claude_orchestrator.lock"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
export OLLAMA_HOST=http://host.docker.internal:11434
export TZ='Europe/Berlin'

exec 200>"$LOCK_FILE"
flock -n 200 || { echo "[$TIMESTAMP] ⏳ Läuft bereits"; exit 0; }
trap 'rm -f "$LOCK_FILE"' EXIT

cd "$REPO_DIR"

# === Check uncommitted changes — BUILD ONLY, NO COMMIT ===
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    CHANGED=$(git diff --name-only)
    if JAVA_HOME="$JAVA_HOME" ./gradlew build 2>&1 | tail -5 >> "$LOG_FILE"; then
        cat > "$READY_FLAG" << EOF
{
  "repo": "workers-collective",
  "branch": "$BRANCH",
  "timestamp": "$TIMESTAMP",
  "changes": $(echo "$CHANGED" | python3 -c "import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))"),
  "status": "ready"
}
EOF
    fi
fi

# === Free slots → issue agents ===
AVAILABLE=$((MAX_AGENTS - $(pgrep -f "ollama launch claude" 2>/dev/null | grep -c . || true)))
for i in $(seq 1 "$AVAILABLE"); do
    IDX=$((i - 1))
    ISSUE_NUM=$(export PATH="/opt/data/home/bin:$PATH" && gh issue list --state open --limit 10 --json number,title 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d[$IDX]['number'] if len(d)>$IDX else '')" 2>/dev/null || echo "")
    [ -z "$ISSUE_NUM" ] && break
    
    cd "$REPO_DIR"
    echo "Implementiere Issue #$ISSUE_NUM.

REGELN:
- ✏️ NUR IMPLEMENTIEREN und BAUEN
- 🚫 NIEMALS committen, pushen, taggen oder releasen!
- Mercury committed+pusht selbst

SCHRITTE:
1. Code implementieren
2. JAVA_HOME=$JAVA_HOME ./gradlew build
3. FERTIG — keine git add/commit/push/tag/release" | \
    $OLLAMA_BIN launch claude --model "$MODEL" -y -- --dangerously-skip-permissions > /dev/null 2>&1 &
    sleep 10
done
```

## ⚠️ Critical: Cron Conflicts

The orchestrator runs on cron. When you manually commit and push to the repo, the cron may have already pushed different commits. This causes a **diverged history**:

**Symptoms:** `git push` says "everything up-to-date" but remote has different commits.

**Solution:**
1. Pause offending cron: `cronjob action=pause job_id=xxx`
2. Fetch remote: `git fetch origin`
3. Cherry-pick your commits onto remote HEAD: `git cherry-pick YOUR_COMMIT_HASH`
4. Force push: `git push --force origin master`
5. Resume cron: `cronjob action=resume job_id=xxx`

**Prevention:** Always pause the claude-orchestrator cron before making manual changes to the repo.

## Claude Code Launch Syntax

**CRITICAL — the `--` separator is mandatory:**

```bash
# CORRECT: ollama flags BEFORE --, Claude Code flags AFTER
echo 'task' | ollama launch claude --model deepseek-v4-flash:cloud -y -- --dangerously-skip-permissions

# WRONG (will pass flags to ollama, not Claude):
echo 'task' | ollama launch claude --model deepseek-v4-flash:cloud --dangerously-skip-permissions -y
```

## Default Branch: master (not main)

Workers Collective uses `master` as the default branch. `main` was renamed by:
1. Create `master` from `main`: `git checkout -b master`
2. Push: `git push -u origin master`
3. Change default via API: `PATCH /repos/... {"default_branch":"master"}`
4. Delete local + remote main: `git branch -d main && git push origin --delete main`

All scripts, crons, and skills must reference `master`, not `main`.

## Pitfalls

| Problem | Solution |
|---------|----------|
| Agents commit under own name | In prompt: "NIEMALS committen — nur implementieren + bauen" |
| Agent uses "Henry"/"Claude" as author | Agents implement only — Mercury commits |
| Cron overwrites manual commits | Pause cron → cherry-pick → force push → resume |
| Default branch is `main` | Rename to `master` via git + API |
| ollama flags ignored | `--` separator: `-y -- --dangerously-skip-permissions` |
| ScreenHandlerType compile error | MC 1.21: `new ScreenHandlerType<>(factory, FeatureSet.empty())` |
| Token limit almost reached | Scale down cron frequencies, pause non-critical services |
| gh not found in cron | Add `/opt/data/home/bin` to PATH explicitly |
