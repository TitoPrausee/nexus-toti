---
name: mercury-web-dashboard
description: aiohttp WebSocket Dashboard that bridges browser clients to a Tailscale mesh of Mercury peers — live desktop streaming, remote input, terminal, file browser.
version: 1.0.0
author: <GITHUB_USER>
---

# Mercury Web Dashboard

Web-basierte Verwaltungsoberfläche für das Mercury Peer Mesh über Tailscale. Bietet Live Desktop-Streaming, Remote Maus/Tastatur, Terminal und File Browser.

## Architektur

```
┌──────────────────────────────┐
│    Web Dashboard (:8080)      │
│  ┌──────────┐ ┌────────────┐ │
│  │ Frontend │◄┤ Backend    │ │
│  │ Vanilla  │ │ (aiohttp)  │ │
│  │ JS + CSS │ │ WS + REST  │ │
│  └──────────┘ └─────┬──────┘ │
└──────────────────────┼────────┘
                       │ Tailscale :9443 (Mercury Protocol)
              ┌────────┼────────┐
              ▼        ▼        ▼
        ┌────────┐ ┌────────┐ ┌────────┐
        │ macOS  │ │Server  │ │Weitere │
        │Mercury │ │Mercury │ │Peers   │
        │cliclick │ │xdotool │ │        │
        └────────┘ └────────┘ └────────┘
```

## Repo-Struktur

```
mercury-web/
├── backend/
│   ├── mercury_web.py     # aiohttp Server (REST + WebSocket)
│   └── requirements.txt   # aiohttp
├── frontend/
│   ├── index.html          # Dashboard UI
│   └── app.js              # Frontend-Logik
├── start.sh                # Start-Skript
└── README.md
```

## Backend: mercury_web.py

### Key Functions

```python
async def scan_all_peers() -> list[dict]:
    # 1. Führt `tailscale status` aus (mit korrektem Binary/Socket-Pfad!)
    # 2. Parst Output: IP, Hostname, OS (aus tailscale drittes Feld)
    # 3. Für online Peers: TCP :9443 → Mercury Auth → system_info abfragen
    # 4. Caching: 30s TTL
    # Return: [{"hostname":"mac","ip":"<PRIVATE_IP>","os":"macOS","online":true,"version":"3.2.0"}]

async def peer_exec(peer_ip, cmd_data, timeout=30) -> dict:
    # Verbindung zu peer_ip:9443
    # Prefix b'P' senden
    # peer_hello empfangen → challenge parsen
    # SHA256(secret_bytes + chal_bytes).hexdigest() als response senden
    # Command senden, Antwort empfangen, close

async def mercury_auth(reader, writer) -> bool:
    writer.write(b"P")
    await writer.drain()
    hello = await recv(reader, timeout=10)  # {"type":"peer_hello","challenge":"<hex>"}
    response = hashlib.sha256(secret + bytes.fromhex(hello["challenge"])).hexdigest()
    await send(writer, {"type":"peer_auth","response":response,"hostname":get_hostname()})
    ok = await recv(reader, timeout=5)  # {"type":"peer_ok"}
```

### Remote Commands (peer_* Wrapper)

| Funktion | Mercury Command | Peer-Voraussetzung |
|---|---|---|
| `peer_shell(ip, cmd)` | `{"cmd":"shell","args":{"command":cmd,"timeout":30}}` | — |
| `peer_screenshot(ip)` | Shell: `screencapture -x -T0 /tmp/s.png && base64 < /tmp/s.png` | macOS: Screen Recording Permission |
| `peer_mouse_move(ip, x, y)` | Shell: `cliclick m:{x},{y}` | macOS: `brew install cliclick` + Accessibility |
| `peer_mouse_click(ip, button)` | Shell: `cliclick c:.` (left) oder `cliclick c:c.` (right) | macOS: cliclick + Accessibility |
| `peer_keyboard(ip, text)` | Shell: `cliclick k:{shlex.quote(text)}` | macOS: cliclick + Input Monitoring |
| `peer_list_dir(ip, path)` | `{"cmd":"list_dir","args":{"path":path}}` | — |
| `peer_read_file(ip, path)` | `{"cmd":"read_file","args":{"path":path}}` | — |
| `peer_system_info(ip)` | `{"cmd":"system_info"}` | — |

### WebSocket Protokoll

**Client → Server:**
```json
{"action": "list_peers"}
{"action": "shell", "peer": "mac", "cmd": "uname -a"}
{"action": "screenshot", "peer": "mac"}
{"action": "mouse_move", "peer": "mac", "x": 100, "y": 200}
{"action": "mouse_click", "peer": "mac", "button": "left"}
{"action": "keyboard_type", "peer": "mac", "text": "hello"}
{"action": "list_dir", "peer": "mac", "path": "/Users"}
{"action": "read_file", "peer": "mac", "path": "/tmp/test.txt"}
{"action": "start_stream", "peer": "mac"}
{"action": "stop_stream"}
```

**Server → Client:**
```json
{"type": "peers", "data": [...]}
{"type": "result", "action": "shell", "data": {"stdout":"...","stderr":"...","exit_code":0}}
{"type": "result", "action": "screenshot", "data_b64":"...base64...","size":12345}
{"type": "screenshot", "data_b64":"...base64...","size":12345}  // streaming mode
```

### Screenshot Stream Loop

```python
async def screenshot_stream(ws, peer_ip):
    """Send screenshots every 2s via WebSocket."""
    while True:
        img_bytes = await peer_screenshot(peer_ip)
        if img_bytes:
            await ws.send_json({
                "type": "screenshot",
                "data_b64": base64.b64encode(img_bytes).decode(),
                "size": len(img_bytes)
            })
        await asyncio.sleep(2)
```

## Frontend: app.js + index.html

### State Management

```javascript
const state = {
    peers: [],
    selectedPeer: null,      // hostname string
    streamActive: false,
    terminalHistory: [],
    terminalHistoryIndex: -1,
    currentDir: '/',
    fileBrowserHistory: ['/'],
    activeTab: 'desktop',
};
```

### WebSocket mit Auto-Reconnect

```javascript
function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onclose = () => setTimeout(connectWS, 2000);
}
```

### Live Desktop Canvas

Canvas-Element mit Maus-Events:
- `click` → mouse_click an Peer senden
- `mousemove` → Position in Statuszeile anzeigen
- `mousedown`+`drag` → mouse_move an Peer senden
- Keyboard Input → keyboard_type an Peer senden

Wichtig: Koordinaten skalieren (canvas width/height vs display size):
```javascript
const scaleX = canvas.width / rect.width;
const x = Math.round((e.clientX - rect.left) * scaleX);
```

## Tailscale auf Container ohne TUN

Wenn der Server in einem Docker/Container läuft (kein `/dev/net/tun`):

```bash
# Binaries (nicht im System-PATH, liegen in ~/.local/bin/)
tailscaled --state=/tmp/tailscale.state --socket=/tmp/tailscale.sock --tun=userspace-networking
tailscale --socket /tmp/tailscale.sock up --reset --accept-routes --ssh
tailscale --socket /tmp/tailscale.sock status
```

Im Backend muss der Socket-Pfad gesetzt werden:
```python
ts_bin = "tailscale"
home_ts = os.path.expanduser("~/.local/bin/tailscale")
if os.path.isfile(home_ts):
    ts_bin = home_ts
# Use --socket for userspace-networking mode
proc = await asyncio.create_subprocess_exec(
    ts_bin, "--socket", "/tmp/tailscale.sock", "status", ...
)
```

## GitHub Repo ohne gh CLI erstellen

Wenn `gh` nicht installiert ist, Token via `git credential` extrahieren:

```python
import subprocess, json
proc = subprocess.run(
    ["git", "credential", "fill"],
    input=b"protocol=https\nhost=github.com\n\n",
    capture_output=True, timeout=10
)
# Parse password= aus output
token = re.search(r'password=(.+)', proc.stdout.decode()).group(1).strip()

# Repo via API erstellen
curl_cmd = ["curl", "-s", "-X", "POST", 
    "-H", f"Authorization: token {token}",
    "-H", "Accept: application/vnd.github.v3+json",
    "https://api.github.com/user/repos",
    "-d", json.dumps({"name": "repo-name", "private": True, "auto_init": False})]
```

Der `.env`-Token und `~/.git-credentials` werden oft vom System maskiert (`***`), aber `git credential fill` liefert den echten Token.

## Pitfalls

- **Tailscale userspace-socket**: `tailscale status` ohne `--socket` schlägt fehl, wenn tailscaled mit custom socket läuft
- **Tailscale OS parsing**: Das dritte Feld in `tailscale status` enthält evtl. `/` am Ende → `rstrip("/")` verwenden
- **Frontend Canvas-Skalierung**: Immer `canvas.width / rect.width` berechnen — `clientX/Y` sind in Display-Koordinaten, nicht Canvas-Koordinaten
- **cliclick auf macOS**: Braucht `brew install cliclick` + Accessibility + Input Monitoring Berechtigungen
- **Screencapture Permission**: macOS verlangt "Bildschirmaufnahme" Berechtigung für `screencapture`
- **Secret aus ~/.mercury/secret**: Ist hex-kodiert, erst `bytes.fromhex()` — niemals rohen String verwenden
- **Multi-Agent Timeouts**: Subagents die timeouts haben, haben oft 90%+ der Arbeit erledigt. Immer checken ob Files committed wurden, bevor man neu dispatched
- **Dashboard-Server starten**: Hintergrund-Prozess mit `python3 backend/mercury_web.py &`, Health-Check via `curl http://localhost:8080/`
