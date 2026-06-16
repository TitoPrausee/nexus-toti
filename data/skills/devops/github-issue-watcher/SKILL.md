---
name: github-issue-watcher
description: Automatischer GitHub Issue Watcher — checkt alle N Minuten auf neue Issues, assigned sie an den Owner, kommentiert und queued sie zur Verarbeitung via Cron.
version: 1.0.0
author: Hermes Agent
---

# GitHub Issue Watcher — Auto-Assign & Process

## Überblick
Ein Cron-betriebenes System das regelmäßig (z.B. alle 30min) GitHub-Repos auf neue Issues scannt, sie automatisch assigned, einen Acknowledgement-Kommentar hinterlässt und eine Workqueue für die Verarbeitung anlegt.

## Wann verwenden
- User will dass externe Contributors automatisch betreut werden
- Neue Issues sollen sofort assigned + kommentiert werden
- Issues sollen automatisch in Bearbeitung gehen (nicht nur manuell)
- User arbeitet mit mehreren Repos und will keinen Issue verpassen

## Setup

### 1. Watcher-Skript
`/opt/data/home/scripts/issue_watcher.py`:

```python
#!/usr/bin/env python3
"""Issue Watcher — check for new unassigned issues, assign + queue"""
import json, subprocess, sys

TOKEN = subprocess.run(
    "grep '^export GITHUB_TOKEN=' ~/.hermes/.env | head -1 | cut -d= -f2 | tr -d '\"'",
    shell=True, capture_output=True, text=True
).stdout.strip()

REPOS = ["Owner/repo1", "Owner/repo2"]

def api(method, path, data=None):
    cmd = ["curl", "-s", "-X", method,
           "-H", f"Authorization: token {TOKEN}",
           "-H", "Accept: application/vnd.github+json",
           f"https://api.github.com{path}"]
    if data: cmd += ["-d", json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout)

def get_last_checked(repo):
    p = f"/tmp/issue_watch_{repo.replace('/', '_')}.txt"
    try:
        with open(p) as f: return int(f.read().strip())
    except: return 0

def set_last_checked(repo, n):
    p = f"/tmp/issue_watch_{repo.replace('/', '_')}.txt"
    with open(p, "w") as f: f.write(str(n))

found = []
for repo in REPOS:
    last = get_last_checked(repo)
    issues = api("GET", f"/repos/{repo}/issues?state=open&sort=created&direction=desc&per_page=10")
    
    latest = last
    for issue in issues:
        if "pull_request" in issue: continue
        if issue["number"] > latest: latest = issue["number"]
        if issue["number"] > last:
            found.append((repo, issue))
    
    if latest > last: set_last_checked(repo, latest)

for repo, issue in found:
    num = issue["number"]
    # Assign
    api("POST", f"/repos/{repo}/issues/{num}/assignees",
        {"assignees": ["OwnerName"]})
    # Comment
    api("POST", f"/repos/{repo}/issues/{num}/comments", {
        "body": "🤖 **Auto-Watcher**: Issue #N detected + assigned!\n\nProcessing...\n---\n*Automated response*"
    })
    # Queue for processing
    with open(f"/tmp/issue_work_{repo.replace('/', '_')}_{num}.json", "w") as f:
        json.dump({"repo": repo, "number": num, "title": issue["title"],
                   "body": issue.get("body",""), "labels": [l["name"] for l in issue["labels"]],
                   "status": "pending"}, f)
    print(f"✅ #{num}: {issue['title']}")
```

### 2. Cron-Job für den Watcher
```python
cronjob(
    action="create",
    name="issue-watcher",
    skills=["github-issues", "github-auth"],
    prompt="Run: python3 /opt/data/home/scripts/issue_watcher.py\n\nRead output. If NEW issues found, process each: read the work file, implement the feature/fix, commit with '(Closes #N)', tag and release if significant, delete work file after.",
    schedule="every 30m",
    repeat=-1
)
```

### 3. Cron-Job für den Dashboard (optional kombiniert)
```python
cronjob(
    action="create",
    name="project-dashboard",
    prompt="Run: python3 /opt/data/home/scripts/dashboard.py\n\nDeliver result to user.",
    schedule="10m",
    repeat=-1
)
```

## Workflow
```
GitHub Issue created → Watcher Cron (30min)
  → Detect new issue (number > last_checked)
  → Assign to owner
  → Comment "Processing..."
  → Save to /tmp/issue_work_*.json
  → Next Cron tick reads work file
  → Implements feature / fixes bug
  → Commit "(Closes #N)" → Auto-close
  → Tag + Release if significant
  → Delete work file
```

## Wichtige Details

### Issue-Check-Logik
- Speichert `last_checked` Issue-Nummer pro Repo in `/tmp/issue_watch_*.txt`
- Neue Issues = Nummer > last_checked
- Filtert PRs raus (`"pull_request" in issue`)
- Holt nur die 10 neuesten Issues (`per_page=10`)

### Commit Convention
Immer `(Closes #N)` in der Commit-Message:
```bash
git commit -m "feat: implement feature (Closes #5)"
```
GitHub schließt das Issue automatisch beim Push.

### Token-Sicherheit
```python
TOKEN = subprocess.run(
    "grep '^export GITHUB_TOKEN=' ~/.hermes/.env | head -1 | cut -d= -f2 | tr -d '\"'",
    shell=True, capture_output=True, text=True
).stdout.strip()
```
- `head -1` = nur erste Zeile falls Duplikate
- `tr -d '"'` = Quotes entfernen
- Niemals Token in Logs/Outputs

## Processing Strategy — Queue Execution

When the watcher finds NEW issues and work files exist in `/tmp/issue_work_*`, they must be implemented. This is the most critical and time-consuming phase.

### Strategy: Delegate by Repo, Limit Batch Size

**DO NOT** delegate all issues in one go — subagents consistently time out (>300s) on batches of 4+ issues.

**DO** delegate by individual repo with max 2-3 issues per delegation:

```python
# Better: split into smaller delegations per repo
# For fitspar-retro-ui (simple JS/TS changes):
delegate_task(
    goal="Implement issues for fitspar-retro-ui: #3, #4",
    # ... 2-3 issues max per delegation
)

# For workers-collective (complex Java mod):
delegate_task(
    goal="Implement single issue #2 for workers-collective",
    # ... or implement directly for complex domains
)
```

### When Subagents Time Out — Fallback Strategy

If a subagent times out (common with batched work at 300s limit):

1. **Check what got committed**: The subagent may have made progress before timing out — always check `git log --oneline -10` and `git status --short`.
2. **Re-read modified files**: Subagent modifications may not be visible in your cached reads — re-read files flagged as modified by sibling warnings before editing.
3. **Pick up where it left off**: Uncommitted changes can be committed, then continue with remaining work directly.
4. **Direct implementation**: For remaining issues, implement directly rather than re-delegating — this avoids repeated timeout cycles.

### Issue Implementation Order (per repo)

For a React library (fitspar-retro-ui pattern):
1. Code quality fixes (#5) — quick wins, fix before migration
2. TypeScript conversion (#4) — needed before tests
3. Tests (#3) — depends on TS being done
4. Storybook (#6) — can parallel with release
5. Release (#7) — depends on everything being done

For a Minecraft Fabric mod (workers-collective pattern):
- Each issue is substantial (blocks, entities, mixins, recipes, lang, models)
- **Implement 1 issue per delegation max**
- Or implement directly — the complex Java + JSON model + recipe structure is slower for subagents

### What to Check After Each Issue

After committing each issue, verify:
```bash
# 1. Delete the tracking file
rm /tmp/issue_work_Owner_Repo_N.json

# 2. Verify remaining queue
ls /tmp/issue_work_*.json 2>/dev/null || echo "All done"
```

## Pitfalls
- Cron-Jobs dürfen keine neuen Cron-Jobs spawnen (Safety-Rule)
- `/tmp/` ist flüchtig — nach Reboot sind last_checked-Dateien weg (ist okay, scannt halt nochmal)
- Bei vielen neuen Issues auf einmal: `per_page` erhöhen oder mehrfach laufen lassen
- **Subagent delegation timeout**: Subagents with 300s timeout can't complete batches of 4+ issues. Limit delegations to 2-3 issues max. After timeout, check git log for partial progress rather than re-delegating.
- **Sibling file conflicts**: When subagents run in parallel and both modify the same repo, file read/write conflicts can occur. Use sequential (not parallel) delegations for the same repo.
- GitHub API Rate Limit: 5000 req/h — watch script + dashboard zusammen unter 100 req/Lauf
- PRs werden von GitHub als Issues in der API gelistet — IMMER filtern
- **Build verification is critical** — after TypeScript conversion, always run `npm run build` (or `./gradlew build`) to catch import/type errors before committing
