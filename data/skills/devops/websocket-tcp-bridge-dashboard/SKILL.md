---
name: websocket-tcp-bridge-dashboard
description: "Build a web dashboard that bridges WebSocket clients to an existing TCP protocol server via aiohttp. Pattern: Web UI to WebSocket to Python Bridge to TCP Protocol to Remote Services."
version: 1.0.0
author: "Mercury (extracted from mercury-web build)"
tags:
  - web-dashboard
  - aiohttp
  - websocket
  - tcp-bridge
  - remote-control
---

# WebSocket-to-TCP Bridge Dashboard Pattern

Build a web UI that controls remote machines or services speaking a custom TCP protocol.

## Architecture

```
Browser (JS)  <--WebSocket-->  aiohttp Server (Python Bridge)  <--TCP :9443-->  TCP Service (Mercury)
Single-Page App                JSON msgs                                      Custom Protocol
```

## When to Use

- You already have a TCP-based remote-control protocol (custom, binary, or text)
- You want a web UI for it without modifying the protocol server
- Multiple remote peers need a dashboard
- You need live streaming (screenshots, data) from remote hosts

## Key Components

### 1. Backend Structure (aiohttp)

```python
# mercury_web.py — single file, ~400-500 lines
import asyncio, aiohttp, json, struct, hashlib, os, subprocess, base64
from aiohttp import web, WSMsgType
from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# --- Protocol Encoding (custom TCP protocol) ---
def enc(data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload

async def send(w, data: dict):
    w.write(enc(data))
    await w.drain()

async def recv(r, timeout=30) -> dict | None:
    try:
        raw = await asyncio.wait_for(r.readexactly(4), timeout)
        length = struct.unpack("!I", raw)[0]
        payload = await asyncio.wait_for(r.readexactly(length), timeout)
        return json.loads(payload)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
        return None
```

### 2. Peer Discovery (finding TCP services)

For Tailscale-based discovery:
```python
async def scan_all_peers() -> list[dict]:
    """Scan for peers via Tailscale + enrich with system_info."""
    # Find tailscale binary — might be in ~/.local/bin/
    ts_bin = "tailscale"
    home_ts = os.path.expanduser("~/.local/bin/tailscale")
    if os.path.isfile(home_ts):
        ts_bin = home_ts
    
    proc = await asyncio.create_subprocess_exec(
        ts_bin, "status",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
```

Always use `--socket` flag if Tailscale runs in userspace-networking mode:
```python
proc = await asyncio.create_subprocess_exec(
    ts_bin, "--socket", "/tmp/tailscale.sock", "status", ...
)
```

### 3. TCP Command Execution (Bridge Core)

```python
async def peer_exec(peer_ip: str, port: int, cmd_data: dict, timeout=30) -> dict | None:
    """Connect to peer, authenticate, send command, return response."""
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection(peer_ip, port), 5)
        
        # 1. Protocol handshake (protocol-specific)
        w.write(b"P")  # prefix byte
        await w.drain()
        
        # 2. Auth challenge-response
        hello = await recv(r, timeout=10)
        secret = load_secret()
        challenge_bytes = bytes.fromhex(hello["challenge"])
        response = hashlib.sha256(secret + challenge_bytes).hexdigest()
        await send(w, {"type": "peer_auth", "response": response, "hostname": socket.gethostname()})
        
        auth = await recv(r, 5)
        if not auth or auth.get("type") != "peer_ok":
            w.close(); return None
        
        # 3. Send command, get response
        await send(w, cmd_data)
        result = await recv(r, timeout)
        w.close()
        return result
    except Exception:
        return None
```

### 4. WebSocket Handler

```python
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    stream_task = None
    
    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            data = json.loads(msg.data)
            action = data.get("action")
            
            if action == "list_peers":
                peers = await scan_all_peers()
                await ws.send_json({"type": "peers", "data": peers})
            
            elif action == "shell":
                result = await peer_shell(data["peer"], data["cmd"])
                await ws.send_json({"type": "result", "action": "shell", "data": result})
            
            elif action == "start_stream":
                stream_task = asyncio.create_task(
                    screenshot_stream(ws, data["peer"]))
            
            elif action == "stop_stream":
                if stream_task:
                    stream_task.cancel()
                    stream_task = None
    
    if stream_task:
        stream_task.cancel()
    return ws
```

### 5. Screenshot Streaming

```python
async def screenshot_stream(ws, peer_ip, interval=2):
    """Send screenshots every N seconds over WebSocket."""
    while True:
        try:
            img_b64 = await peer_shell(peer_ip, 
                "screencapture -x -T0 /tmp/ms.png && base64 < /tmp/ms.png")
            if img_b64 and img_b64.get("stdout"):
                await ws.send_json({
                    "type": "screenshot",
                    "data_b64": img_b64["stdout"].strip(),
                    "size": len(base64.b64decode(img_b64["stdout"].strip()))
                })
        except (asyncio.CancelledError, ConnectionError):
            break
        except Exception as e:
            await ws.send_json({"type": "stream_error", "error": str(e)})
        await asyncio.sleep(interval)
```

### 6. Frontend (Vanilla JS)

Single `index.html` + `app.js` — no framework needed.

**WebSocket with auto-reconnect:**
```javascript
function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { 
        document.getElementById('ws-status').classList.add('connected');
        sendWS({ action: 'list_peers' });
    };
    ws.onclose = () => {
        document.getElementById('ws-status').classList.remove('connected');
        setTimeout(connectWS, 2000);
    };
    ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
}
```

**Screenshot display on Canvas:**
```javascript
function handleMessage(msg) {
    if (msg.type === 'screenshot') {
        const img = new Image();
        img.onload = () => {
            const canvas = document.getElementById('desktop-canvas');
            canvas.width = img.width;
            canvas.height = img.height;
            canvas.getContext('2d').drawImage(img, 0, 0);
        };
        img.src = `data:image/png;base64,${msg.data_b64}`;
    }
}
```

**Mouse click on Canvas to remote click:**
```javascript
canvas.addEventListener('click', (e) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);
    ws.send(JSON.stringify({
        action: 'mouse_click',
        peer: selectedPeer,
        x: x, y: y
    }));
});
```

### 7. Execution Strategy (Agent Teams)

Use **parallel subagents** for backend + frontend:
- Backend subagent: writes `backend/mercury_web.py` — single-file aiohttp server
- Frontend subagent: writes `frontend/index.html` + `frontend/app.js` — single-page app

The backend subagent typically finishes first (pure Python, no UI logic). The frontend is larger and may time out — but the files are usually committed even on timeout. Always check `git log` before assuming failure.

## Pitfalls

1. **Tailscale binary location** — Not always in PATH. Check `~/.local/bin/tailscale` and use `--socket /tmp/tailscale.sock` for userspace-networking mode.

2. **Auth protocol** — The challenge-response hash must use **bytes**, not hex strings:
   ```python
   # CORRECT
   response = hashlib.sha256(secret_bytes + challenge_bytes).hexdigest()
   # WRONG — hash of hex strings, not bytes
   response = hashlib.sha256(f"{secret_hex}{challenge_hex}".encode()).hexdigest()
   ```

3. **Screenshot on macOS** — `screencapture -x -T0` for silent capture, pipe to `base64` for transmission. Requires Screen Recording permission.

4. **WebSocket port mismatch** — Always use relative URLs (`ws://${location.host}/ws`) so it works behind reverse proxies.

5. **Subprocess in async** — Use `asyncio.create_subprocess_exec` instead of `subprocess.run` in async context to avoid blocking the event loop.

## Verification

After deployment:
```bash
# Server running?
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/  # should be 200
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/peers

# Frontend serves HTML?
curl -s http://localhost:8080/ | head -5

# WebSocket works?
python3 -c "
import asyncio, aiohttp
async def test():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect('http://localhost:8080/ws') as ws:
            await ws.send_json({'action':'list_peers'})
            resp = await ws.receive()
            print('WS OK:', resp.data[:200])
asyncio.run(test())"
```
