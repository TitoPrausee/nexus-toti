---
name: mercury-heartbeat
description: Run the 4-phase Mercury Heartbeat cycle — WATCH → WORK → LEARN → DREAM — for autonomous self-improvement and project maintenance.
---

# Mercury Heartbeat Cycle

Self-running 4-phase cycle for autonomous project maintenance. Designed to run at intervals (cron) or on-demand.

## Trigger

- User says "run heartbeat" or "start cycle"
- Cron job triggers `python3 ~/heartbeat/scripts/run_cycle.py`
- Manually: `cd ~/heartbeat && python3 scripts/run_cycle.py`

## Structure

```
~/heartbeat/
├── scripts/
│   ├── 01_watch.py       # Phase 1: git, tests, services, RAM
│   ├── 02_work.py        # Phase 2: pick + implement top backlog task
│   ├── 03_learn.py       # Phase 3: analyze next tasks, micro-prototypes
│   ├── 04_dream.py       # Phase 4: gaps/risks/ideas → dreams.md
│   └── run_cycle.py      # Orchestrator — runs all 4 in sequence
├── backlog.md             # Priority queue [P0]-[P3]
├── dreams.md              # Generated ideas, gaps, risks
├── config.yaml            # Thresholds, paths
└── .mercury/              # Phase results, learn notes, reports
```

## Phase Details

### WATCH (never skip)
1. Check RAM — abort if >75%
2. Check git status — log dirty files
3. Run tests — fail cycle if tests break
4. Check essential services (python, git)

### WORK
1. Parse backlog.md — find highest-priority unchecked task
2. Auto-detect if task is already done (script exists)
3. Execute task or prompt user for guidance
4. Mark task done in backlog.md
5. Limit: 1 task per cycle, 10min max per task

**💡 Key pattern: task auto-detection by file existence**
The WORK phase uses keyword matching to map task descriptions to script files (e.g., `"watch"` → `01_watch.py`). If the file exists, the task is automatically marked done. This avoids re-implementing already-finished work. Add new keyword→file mappings in the `script_keywords` dict as the backlog grows.

**💡 Iterative fix pattern (discovered during first run)**
When the initial cycle ran, WORK's keyword matching was too strict — `"all 4 heartbeat phases"` didn't match individual sub-tasks like `"Script: WATCH phase..."`. Fix: added granular keyword→filename mapping. Then the cron task wasn't handled — fix: added a `"cron"`/`"automated run"` handler. Then the Telegram notification task wasn't handled — fix: added `"telegram"`/`"notification"`/`"delivery"` handler that creates `scripts/deliver_report.py`. Then the metrics task (`"Track cycle duration, tasks completed, RAM trend"`) wasn't handled — fix: added a `"metrics"`/`"track cycle"`/`"duration"`/`"ram trend"`/`"tasks completed"` handler that writes to `.mercury/metrics_history.json`. Later, that metrics handler was **moved from `02_work.py` to `run_cycle.py`** to fix the silent metrics gap on idle cycles (see pitfall below). Then the DREAM phase was appending the same static content every cycle, bloating `dreams.md` to 268K — fix: added MD5 fingerprint-based dedup in `04_dream.py` (see dreams.md bloat pitfall below). Expect to add more handlers as new task types appear in the backlog.

**🐛 Known bug fixed: dream_ideas field type**
The initial metrics handler used `len(metrics.get("dream", {}).get("ideas", []))` but the DREAM phase stores `ideas` as an integer count (3), not a list. Fixed by using `metrics.get("dream", {}).get("ideas", 0)` directly.

When adding a new WORK handler, insert it as an `elif` branch in `02_work.py` before the `else:` fallback. Pattern:
1. Match on keywords in `desc.lower()`
2. Do the work (create files, run commands)
3. Set `implemented = True`
4. Set `result = {"task": desc, "custom_key": True}`

### LEARN
1. Look at next 2-3 pending backlog tasks
2. Check for unfamiliar patterns (cron, notifications, metrics, skills, git ops)
3. Build 1-2 micro-prototypes in `.mercury/learn/`
4. Save learn notes with timestamp

### DREAM
1. Load results from WATCH/WORK/LEARN phases
2. Identify gaps, risks, and shortcuts
3. Generate 2-3 actionable ideas
4. Append analysis to `dreams.md`

## Rules (enforced by run_cycle.py)
- Never skip WATCH
- Never break tests
- If RAM >75% → abort and cleanup
- No browser tools
- Max 2 concurrent subagents
- If stuck >10min → skip task

## Pitfalls

### 🚨 Uncommitted `.mercury/` artifact pile-up (critical!)
The `.mercury/` directory accumulates `report_*.md` and `learn/*.md` files **every cycle** — one per phase per run. Within days, this generates **80-100 untracked files** that:
- Break the "zero uncommitted changes" health check rule
- Make `git status` useless for spotting actual code changes
- Bloat the repository with disposable runtime artifacts

**Fix:** Create a `.gitignore` in `~/heartbeat/`:
```gitignore
# Runtime artifacts — regenerated every heartbeat cycle
.mercury/report_*.md
.mercury/learn/*.md

# Keep tracked files
!.mercury/metrics_history.json
!.mercury/last_*.json
```

**Prevention (new project setup):** Always create `.gitignore` before the first commit. The heartbeat scripts create artifacts every cycle — if you don't exclude them upfront, they'll pile up as untracked garbage.

### ✅ Silent metrics gap on idle cycles (RESOLVED — fix applied 2026-05-10)
**Problem:** Metrics collection lived in `02_work.py` as a WORK handler — it only fired when there was a pending backlog task. On idle cycles, **no metrics were recorded**, creating dark periods with no RAM trend, cycle frequency, or health correlation data.

**Fix applied:** Moved metrics collection to `run_cycle.py` as an unconditional post-phase step (inserted just before the `build_health_report()` call). Every cycle now records:
```python
metrics_entry = {
    "timestamp": datetime.datetime.now().isoformat(),
    "ram_pct": cycle_metrics.get("watch", {}).get("ram_pct", None),
    "git_dirty": cycle_metrics.get("watch", {}).get("git_dirty", None),
    "cycle_duration_s": round(total_time, 1),
    "watch_status": cycle_metrics.get("watch", {}).get("status", None),
    "work_status": cycle_metrics.get("work", {}).get("status", None),
    "learn_status": cycle_metrics.get("learn", {}).get("status", None),
    "dream_status": cycle_metrics.get("dream", {}).get("status", None),
    "dream_ideas": cycle_metrics.get("dream", {}).get("ideas", 0),
}
```

The duplicate handler in `02_work.py` was also removed to avoid double-recording. The code reads phase result JSONs from `.mercury/last_*.json` (same files the health report uses) and appends to `metrics_history.json`. No schema migration needed — old entries with `work_task` field coexist with new entries that have `cycle_duration_s`.

### 🚨 dreams.md bloat from static DREAM phase (CRITICAL — fixed 2026-05-10)
**Problem:** The DREAM phase appended the exact same static gaps/risks/ideas (`analyze_gaps`, `identify_risks`, `find_shortcuts`, `generate_ideas` all returned hardcoded data) every cycle. Within days, `dreams.md` grew to **268K and 2,910 lines** of pure duplication.

**Fix applied to `scripts/04_dream.py` (3 changes):**
1. **Added `get_cycle_fingerprint()`** — computes an MD5 hash of all gap/risk/shortcut/idea text. Added `import hashlib`.
2. **Added `get_last_n_fingerprints(n)`** — scans `dreams.md` for HTML comments `<!-- FP:... -->` left after each cycle, returns the last N.
3. **Modified `append_to_dreams()`** — checks the fingerprint against the last 10 cycles before appending. If a match is found, prints "Skipping append — identical analysis already recorded" and returns `None`.
4. **Fixed result print in `main()`** — shows "Appended to ..." or "(skipped)" based on return value.

Each dream cycle now embeds `<!-- FP:{hash} -->` after the timestamp header for efficient future dedup.

**After fix:** Compacted dreams.md from 2,910 lines / 268K back to 50 lines / 4K (header + first cycle + latest cycle with FP tag). Subsequent identical cycles are silently skipped.

### 🚨 No remote configured
The heartbeat repo (`~/heartbeat`) typically has no git remote, so committed changes are local-only. If the user expects pushes to GitHub/Modrinth, configure the remote on setup. Health checks that auto-commit will succeed but cannot push — this is normal for a local-only Mercury instance.

## Cron Setup

```python
# Automate via Hermes cronjob tool:
cronjob(
    action='create',
    name='mercury-heartbeat',
    schedule='0 * * * *',  # every hour
    prompt='Run the full Mercury Heartbeat cycle (WATCH → WORK → LEARN → DREAM) on ~/heartbeat',
    skills=['mercury-heartbeat'],
    deliver='origin'
)
```

## Health Report Format

```
⚡ Mercury Heartbeat Report
📅 2026-05-04 16:30:32

✅ WATCH — 0.0s
✅ WORK — 0.0s
✅ LEARN — 0.0s
✅ DREAM — 0.0s

📊 Summary:
  watch: PASS
  work: COMPLETED
  learn: DONE
  dream: DONE

⏱️ Total cycle time: 0.0s
```
