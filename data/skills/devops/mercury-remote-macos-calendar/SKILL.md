---
name: mercury-remote-macos-calendar
description: Read macOS Calendar events via Mercury Remote (TCP :9443) using icalBuddy/AppleScript
version: 1.0.0
author: Mercury
tags: [macos, calendar, mercury, remote, icalbuddy, applescript]
---

# macOS Calendar via Mercury Remote

Access Calendar.app events on a remote Mac over the Mercury Remote TCP mesh (`:9443`).

## Prerequisites

- Mercury Remote peer running on target Mac
- Shared secret in `~/.mercury/secret`
- Mac reachable via Tailscale IP
- **macOS 14+**: AppleScript Calendar access (no TCC permission needed for osascript)
- **macOS 14+**: icalBuddy needs Terminal Calendar permission (System Settings → Privacy → Calendar)

## Key Findings (macOS 26 specific)

- `~/Library/Calendars/Calendar.sqlitedb` is **0 bytes** on macOS 26 — Apple uses EventKit framework, not direct SQLite
- AppleScript access works without extra permissions on modern macOS via `osascript`
- icalBuddy requires **Calendar TCC permission** for Terminal (`/usr/bin/osascript` inherits it)
- Old `.calendar/Events/` directories no longer exist

## Connection Setup

```python
import asyncio, hashlib, json, struct, os

def pack(d: dict) -> bytes:
    p = json.dumps(d, ensure_ascii=False).encode()
    return struct.pack("!I", len(p)) + p

async def mercury_connect(mac_ip: str, secret_path: str = "~/.mercury/secret"):
    secret = bytes.fromhex(open(os.path.expanduser(secret_path)).read().strip())
    r, w = await asyncio.wait_for(
        asyncio.open_connection(mac_ip, 9443), 5
    )
    # Prefix byte
    w.write(b"P")
    await w.drain()
    
    # Read peer_hello
    raw = await asyncio.wait_for(r.readexactly(4), 5)
    msg = json.loads(await r.readexactly(struct.unpack("!I", raw)[0]))
    
    # Auth challenge-response
    chal = bytes.fromhex(msg["challenge"])
    auth = pack({
        "type": "peer_auth",
        "response": hashlib.sha256(secret + chal).hexdigest(),
        "hostname": "mercury-dash"
    })
    w.write(auth)
    await w.drain()
    
    raw = await asyncio.wait_for(r.readexactly(4), 5)
    auth_resp = json.loads(await r.readexactly(struct.unpack("!I", raw)[0]))
    
    if auth_resp.get("type") != "peer_ok":
        raise PermissionError("Mercury auth failed")
    
    return r, w

async def run_cmd(r, w, cmd: str, timeout: int = 15) -> dict:
    """Execute a shell command on the remote Mac and return the result."""
    w.write(pack({"cmd": "shell", "args": {"command": cmd, "timeout": timeout}}))
    await w.drain()
    raw = await asyncio.wait_for(r.readexactly(4), timeout + 5)
    return json.loads(await r.readexactly(struct.unpack("!I", raw)[0]))
```

## Step 1: Verify Calendar access via AppleScript

Before trying icalBuddy, verify that Calendar.app is accessible:

```bash
osascript -e 'tell application "Calendar" to get name of every calendar'
```

Expected output: `Arbeit, Privat, Kalender, Geburtstage, ...`

If this fails with "not authorized" → **Calendar TCC permission missing** for Terminal.app

## Step 2: Install icalBuddy (if missing)

```bash
brew install ical-buddy
```

⚠️ After install, the first run will trigger a macOS permission dialog on the Mac.
If icalBuddy returns "No calendars." even though AppleScript can see calendars,
the issue is likely an **incorrect flag** — see Pitfalls below.

## Step 3: Fetch events

### Today's events
```bash
icalBuddy -n -b "" -iep datetime,title,calendar eventsToday
```

### Date range (this week)
```bash
icalBuddy -n -b "" -iep datetime,title,calendar \
  eventsFrom:"2026-05-20" to:"2026-05-24"
```

### Key flags
| Flag | Meaning | Correct Usage |
|------|---------|--------------|
| `-n` | No color codes | Always use |
| `-nc` | No calendar colors | Optional |
| `-b ""` | No bullets | Clean output |
| `-ic` | Include calendars | **OMIT** for all calendars (don't use `-ic ""`) |
| `-ec` | Exclude calendars | **OMIT** for all calendars |
| `-iep` | Include event properties | `datetime,title,calendar` |
| `-po` | Property order | `datetime,title,calendar` |
| `-ps` | Property separator | `"   ❯   "` |

### CRITICAL PITFALL — Empty flag strings

Do NOT use `-ic ""` or `-ec ""` — icalBuddy interprets empty quotes as "no calendars" and returns `error: No calendars.` Just omit these flags entirely (include all calendars).

### CRITICAL PITFALL — AppleScript record construction

Do NOT try to build records/dicts inside repeat loops like this:
```applescript
set end of todayEvents to {title:summary of e, start:start date of e}
```
This causes `"end" found (-2741)` syntax error. Use string concatenation instead:
```applescript
set out to out & summary of e & " | " & (start date of e as string)
```

### Deleting events via AppleScript

```applescript
tell application "Calendar"
    repeat with c in calendars
        set calName to title of c
        if calName is "Privat" then
            set todays to (events of c whose start date is greater than or equal to (current date) and start date is less than or equal to (current date + 2 * days))
            repeat with e in todays
                if summary of e contains "VR Bank" then
                    delete e
                    return "DELETED: " & summary of e
                end if
            end repeat
        end if
    end repeat
end tell
```

## Step 4: Fallback — AppleScript

If icalBuddy fails or permissions aren't granted, use AppleScript directly:

```applescript
set out to ""
tell application "Calendar"
    repeat with c in calendars
        set calName to title of c
        try
            set todays to (events of c whose start date is greater than or equal to (current date) and start date is less than or equal to (current date + 1 * days))
            repeat with e in todays
                set startStr to (start date of e as string)
                set endStr to (end date of e as string)
                set out to out & "[" & calName & "] " & summary of e & return & "     " & startStr & " - " & endStr & return
            end repeat
        end try
    end repeat
end tell
return out
```

⚠️ **AppleScript Array Record Pitfall**: Do NOT try to build records/dicts inside repeat loops with `set end of todayEvents to {title:summary of e, ...}` — this causes `"end" found (-2741)` syntax errors. Use string concatenation instead.

## Step 5: Format Output

Parse icalBuddy output with Python for grouping by day, adding emoji, etc.:

```python
lines = stdout.strip().split("\n")
for line in lines:
    if not line.strip():
        continue
    # Parse: "datetime   ❯   title (calendar)"
    parts = line.split("   ❯   ")
    if len(parts) >= 2:
        datetime_str = parts[0].strip()
        title_cal = parts[1].strip()
        # Extract calendar name from parentheses
        if "(" in title_cal:
            title = title_cal[:title_cal.rindex("(")].strip()
            cal = title_cal[title_cal.rindex("(")+1:title_cal.rindex(")")]
        else:
            title = title_cal
            cal = "?"
        print(f"  {datetime_str} → {title} [{cal}]")
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `error: No calendars.` | Wrong icalBuddy flags | Omit `-ic`/`-ec` flags |
| AppleScript returns empty | No events today | Check date range |
| `sqlite3` finds 0-byte DB | macOS 26+ uses EventKit | Don't use sqlite3 — use AppleScript |
| Permission dialog on Mac | First icalBuddy run | User must accept in System Settings |
| `icalBuddy: command not found` | Not installed | `brew install ical-buddy` |
| Timeout on AppleScript | Calendar has many calendars | Filter to specific calendars |

## Full Example: This Week

```python
today = datetime.now()
days_until_sunday = 6 - today.weekday()
end_of_week = today + timedelta(days=days_until_sunday)

r, w = await mercury_connect("<PRIVATE_IP>")
result = await run_cmd(r, w,
    f'icalBuddy -n -b "" -iep datetime,title,calendar '
    f'eventsFrom:"{today:%Y-%m-%d}" to:"{end_of_week:%Y-%m-%d}"'
)
# result["stdout"] contains the events
w.close()
```
