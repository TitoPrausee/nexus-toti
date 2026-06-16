---
name: macos-calendar-via-mercury
description: Read, create, and manage macOS Calendar events from a remote server via Mercury Remote (Tailscale TCP :9443 Shell). Handles macOS 26+ permission quirks and sqlite3 / icalBuddy approaches.
version: 1.0.0
author: Mercury Agent
license: MIT
---

# macOS Calendar via Mercury Remote

Read macOS Calendar events by executing commands on the Mac peer through Mercury Remote. Requires:
- Mercury peer running on the Mac (`mercury peer`)
- Tailscale connectivity between server and Mac
- macOS Calendar permission granted to Terminal

## First-Time Setup

### Step 1: Install icalBuddy on Mac

```bash
# Via Mercury Remote shell
# Connect to Mac peer and run:
brew install ical-buddy
```

**Verification:**
```bash
icalBuddy eventsToday
```
Expected: `error: No calendars.` — this means icalBuddy is installed but Calendar permission is missing.

### Step 2: Grant Calendar Permission to Terminal

macOS blocks Calendar access for Terminal by default. The user must:

1. Open **System Settings → Privacy & Security → Calendar**
2. Click `+` and add **Terminal**
3. Check the checkbox ✅ next to Terminal

You can open the settings pane remotely via:
```bash
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_LinkedIn'
```

### Step 3: Verify Access

```bash
icalBuddy -n -nc -b "" -ic "" -iep datetime,title,calendar -ps " | " -po datetime,title,calendar eventsToday
```

Expected: Formatted list of today's events.

## Usage

### Read Today's Events

```bash
icalBuddy -n -nc -b "" -ic "" -iep datetime,title,calendar -ps " | " -po datetime,title,calendar eventsToday
```

### Read Events for a Specific Date Range

```bash
icalBuddy eventsFrom:"2026-05-20" to:"2026-05-22"
```

### List All Calendars

```bash
icalBuddy list calendars
```

### Create an Event

```bash
icalBuddy add "Meeting Title" --calendar "CalendarName" --datetime "2026-05-20 15:00" --duration 60
```

## Technical Details

### macOS 26+ Calendar Storage

On macOS 26, the old `~/Library/Calendars/Calendar.sqlitedb` is **0 bytes** (empty placeholder). Apple uses EventKit framework internally. Direct sqlite3 access to calendar data is NOT possible on modern macOS.

**Working approaches:**
1. **icalBuddy** (recommended) — CLI wrapper around EventKit, needs Calendar permission
2. **AppleScript** — `tell application "Calendar" to ...` — needs Calendar + Automation permission
3. **EventKit via Swift/ObjC** — custom binary, overkill

### Permission Requirements

| Tool | macOS Permission Needed |
|---|---|
| icalBuddy | Calendar (System Settings → Privacy → Calendar → Terminal) |
| AppleScript Calendar | Calendar + Automation |
| sqlite3 Calendar.sqlitedb | NOT useful — DB is empty on macOS 26+ |

### Mercury Remote Execution Pattern

All commands are sent via Mercury protocol's `shell` command:

```python
import asyncio, json, struct, hashlib

async def run_on_mac(command: str, timeout=15) -> dict:
    secret = bytes.fromhex(open(os.path.expanduser("~/.mercury/secret")).read().strip())
    
    r, w = await asyncio.wait_for(asyncio.open_connection("<PRIVATE_IP>", 9443), 5)
    w.write(b"P")
    await w.drain()
    
    raw = await asyncio.wait_for(r.readexactly(4), 5)
    msg = json.loads(await r.readexactly(struct.unpack("!I", raw)[0]))
    
    chal = bytes.fromhex(msg["challenge"])
    p = json.dumps({"type": "peer_auth", "response": hashlib.sha256(secret + chal).hexdigest(), "hostname": "dash"}).encode()
    w.write(struct.pack("!I", len(p)) + p)
    await w.drain()
    
    raw = await asyncio.wait_for(r.readexactly(4), 5)
    auth = json.loads(await r.readexactly(struct.unpack("!I", raw)[0]))
    if auth.get("type") != "peer_ok":
        w.close()
        return {"error": "auth failed"}
    
    c = json.dumps({"cmd": "shell", "args": {"command": command, "timeout": timeout}}).encode()
    w.write(struct.pack("!I", len(c)) + c)
    await w.drain()
    
    raw = await asyncio.wait_for(r.readexactly(4), timeout + 5)
    result = json.loads(await r.readexactly(struct.unpack("!I", raw)[0]))
    w.close()
    return result
```

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `error: No calendars.` | Permission missing | Grant Calendar access to Terminal |
| `icalBuddy: command not found` | Not installed | `brew install ical-buddy` |
| Timeout on AppleScript command | Calendar GUI opens and blocks | Use icalBuddy instead |
| `Calendar.sqlitedb` is 0 bytes | macOS 26+ — normal | DB is virtual via EventKit, use icalBuddy |
| sqlite3: `no such table` | Wrong DB, macOS 26 | Use icalBuddy, don't bother with sqlite3 |

## Pitfalls

1. **AppleScript triggers GUI** — `tell application "Calendar"` will OPEN the Calendar.app GUI on the Mac and show a permission dialog. Use icalBuddy instead which doesn't open the GUI.
2. **Permission persists after first grant** — Once the user clicks ✅ for Terminal's Calendar access, it works until revoked.
3. **Multiple concurrent Mercury commands** — Each command opens a new TCP connection to :9443. The Mac peer handles one at a time via its event loop.
4. **No way to grant permission remotely** — The user MUST interact with the macOS popup/System Settings. You can only open the settings pane remotely.
