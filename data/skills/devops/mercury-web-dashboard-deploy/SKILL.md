---
name: mercury-web-dashboard-deploy
description: Deploy and maintain the Mercury Web Dashboard — aiohttp server, Tailscale mesh connectivity, peer discovery fixes, port management, and auto-health-cron.
version: 1.0.0
author: Mercury Agent
license: MIT
---

# Mercury Web Dashboard Deploy & Maintain

The Mercury Web Dashboard (`github.com/<GITHUB_USER>/mercury-web`, private) runs an aiohttp server on port 8080 with WebSocket bridge to Mercury peers.

## Deployment

```bash
cd /tmp/mercury-web
python3 backend/mercury_web.py &
```

The server binds to `0.0.0.0:8080` and serves:
- `GET /` → Frontend (dark theme dashboard)
- `GET /api/peers` → JSON peer list
- `GET /ws` → WebSocket for live communication
- `/static/` → Frontend assets

## Common Issues & Fixes

### Port 8080 already in use

```bash
# Find the PID blocking port 8080
cat /proc/net/tcp | grep ':1F90 ' | head -1
# The last column before the 0 at end is the inode number
# Find PID: ls -la /proc/[pid]/fd/ | grep socket:[inode]

# Quick kill:
fuser -k 8080/tcp 2>/dev/null  # or
kill -9 PID

# Then restart
cd /tmp/mercury-web && python3 backend/mercury_web.py &
```

### Dashboard stops randomly

The background process may exit silently. Set up a cron health check:
- Schedule: `*/3 * * * *`
- Check: look for `:1F90` in `/proc/net/tcp`
- If missing: restart the server

### Peer Discovery returns empty array

Possible causes:
1. Tailscale not running → restart: see tailscale-docker-setup skill
2. Tailscale binary not found at `tailscale` → check `~/.local/bin/tailscale`
3. Userspace networking socket at `/tmp/tailscale.sock` → use `--socket` flag

Fix in `backend/mercury_web.py`:
```python
ts_bin = "tailscale"
home_ts = os.path.expanduser("~/.local/bin/tailscale")
if os.path.isfile(home_ts):
    ts_bin = home_ts
ts_socket = "/tmp/tailscale.sock"
proc = await asyncio.create_subprocess_exec(
    ts_bin, "--socket", ts_socket, "status", ...
)
```

### _fetch_system_info fails for some peers

Bug pattern in early versions: if `system_info` returns unexpected field names (e.g., `"system"` instead of `"os"`), the peer was silently dropped from the list.

Fix: always append the peer to the enriched list, even if `_fetch_system_info` returns None:
```python
if peer["online"]:
    info = await _fetch_system_info(peer["ip"])
    if info and isinstance(info, dict):
        peer["version"] = info.get("version", "unknown")
        peer["os"] = info.get("system", info.get("os", "unknown"))
    enriched.append(peer)  # ALWAYS append
else:
    enriched.append(peer)
```

Also handle `asyncio.IncompleteReadError` in `_fetch_system_info` — the Mercury peer may disconnect mid-response if the command is slow or unsupported.

### Screenshot streaming doesn't work

If the stream starts but no images arrive:
1. Check the peer is actually online (Mercury protocol)
2. The screenshot command on Mac uses `screencapture` + base64 — verify `screencapture` exists
3. Base64 transfer over TCP may be slow for large images (3-5MB)
4. Try a single screenshot first: `{"cmd":"shell","args":{"command":"screencapture -x -T0 /tmp/s.png && base64 < /tmp/s.png","timeout":15}}`

## Tailscale Connectivity

The dashboard relies on `tailscale status` for peer discovery. In userspace-networking mode:

```bash
# Start tailscaled
~/.local/bin/tailscaled --state=/tmp/tailscale.state --socket=/tmp/tailscale.sock --tun=userspace-networking &

# Connect
~/.local/bin/tailscale --socket /tmp/tailscale.sock up --reset --accept-routes --ssh
```

Verify with: `~/.local/bin/tailscale --socket /tmp/tailscale.sock status`

## Auto-Health Cron

Setup a cron job that checks port 8080 every 3 minutes and restarts if down:

```
Schedule: */3 * * * *
Prompt: Check /proc/net/tcp for :1F90. If port free, restart server and notify.
```

If the server process keeps dying (exit code 1) while port stays bound, the old process is stuck in a half-dead state — use `fuser -k 8080/tcp` before restarting.
