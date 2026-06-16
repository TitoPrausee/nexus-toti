---
name: mercury-remote-agent
description: Bau eines Zero-Dependency Remote-Access Tools (Server + Client) mit reinem Python asyncio. Ermöglicht Mercury (dem Dev-Server) vollen Shell-/File-/Minecraft-Log-Zugriff auf entfernte Rechner via TCP.
version: 1.0.0
author: Mercury
diagram: |
  graph LR
      Local((Local Agent)) --> SSH["SSH / TCP API"]
      SSH --> Remote["Remote Mercury Server"]
      Remote --> Response((Response))
      style Local fill:#1a1a2e,stroke:#e94560,color:#fff
      style SSH fill:#16213e,stroke:#fbbf24,color:#fff
      style Remote fill:#16213e,stroke:#0f3460,color:#fff
      style Response fill:#1a1a2e,stroke:#e94560,color:#fff
---

# Mercury Remote Agent — Zero-Dependency Remote Access

## Architektur

```
Target PC                    Dev-Server (Mercury)
┌──────────────┐    TCP     ┌──────────────────────┐
│ client.py    │◄─────────►│ server.py             │
│ (ausführen)  │   Port     │ (listening)           │
│              │   9443     │                       │
│ - Shell      │            │ - mercury_cli.py      │
│ - File I/O   │            │ - Hermes integriert   │
│ - Minecraft  │            │                       │
└──────────────┘            └──────────────────────┘
```

## Custom Binary Protocol (Zero Dependencies)

Python-Standardbibliothek reicht (`asyncio`, `json`, `struct`, `hashlib`, `base64`):

### Nachrichtenformat
```
[4 Bytes Länge (Big-Endian)] [JSON Payload (UTF-8)]
```

### Encoding/Decoding
```python
import struct, json

def encode_msg(data: dict) -> bytes:
    payload = json.dumps(data).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload

async def recv_msg(reader, timeout=30):
    raw_len = await asyncio.wait_for(reader.readexactly(4), timeout)
    msg_len = struct.unpack("!I", raw_len)[0]
    if msg_len > 10 * 1024 * 1024:  # 10MB Safety Limit
        raise ValueError("Message too large")
    payload = await reader.readexactly(msg_len)
    return json.loads(payload.decode("utf-8"))
```

**CRITICAL:** 10MB-Limit verhindert Memory-Exhaustion. Ohne externe Libs gibt's keinen Streaming-Parser — JSON muss komplett in Memory passen.

## Challenge-Response Authentication

```python
# Server generiert:
challenge = os.urandom(16)  # 16 random bytes
expected = hashlib.sha256(secret + challenge).hexdigest()
# Sendet: {"type": "auth_challenge", "challenge": challenge.hex()}

# Client antwortet:
response = hashlib.sha256(secret + challenge).hexdigest()
# Sendet: {"type": "auth_response", "response": response, "client_name": "..."}

# Server prüft: response == expected → authenticated
```

**Shared Secret** wird in `.secret`-Datei gespeichert (32 Bytes = 64 Hex-Zeichen). Bei erstem Serverstart generiert.

## Kommandosystem (Dispatcher Pattern)

```python
COMMAND_HANDLERS = {
    "shell": handle_shell,        # subprocess.run
    "read_file": handle_read_file,  # base64-encoded
    "write_file": handle_write_file,
    "list_dir": handle_list_dir,
    "find_minecraft": handle_find_minecraft,
    "system_info": handle_system_info,
    "ping": handle_ping,
}

async def handle_message(msg: dict, writer) -> dict:
    cmd = msg.get("cmd", "")
    args = msg.get("args", {})
    handler = COMMAND_HANDLERS.get(cmd)
    if handler:
        result = await handler(**args)
        result["type"] = f"{cmd}_result"
        return result
    return {"ok": False, "error": f"Unknown: {cmd}"}
```

Jeder Handler bekommt `**args` aus dem JSON. Ergebnis wird automatisch via `send_msg()` zurückgeschickt.

## File Transfer

Dateien werden als **base64** im JSON transportiert:

```python
async def read_file(path: str) -> dict:
    data = Path(path).read_bytes()
    return {
        "ok": True,
        "size": len(data),
        "data_b64": base64.b64encode(data).decode(),
    }

async def write_file(path: str, data_b64: str) -> dict:
    data = base64.b64decode(data_b64)
    Path(path).write_bytes(data)
    return {"ok": True, "bytes": len(data)}
```

**Praktische Limits:** ~7.5MB Nutzdaten pro Transfer (10MB JSON-Limit / 1.33 base64-Faktor).

## Minecraft Crash-Report Auto-Detection

```python
async def find_minecraft(path: str = "") -> dict:
    # Auto-detect paths
    candidates = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        candidates.append(Path(appdata) / ".minecraft")
    candidates.append(Path.home() / ".minecraft")
    
    # Crash reports (neueste 5)
    crash_dir = mc_dir / "crash-reports"
    crashes = sorted(crash_dir.glob("*.txt"), 
                     key=lambda f: f.stat().st_mtime, reverse=True)[:5]
    
    # Latest log (letzte 300 Zeilen)
    log_file = mc_dir / "logs/latest.log"
    result["latest_log"] = log_file.read_text(errors="replace").splitlines()[-300:]
```

- **`client_config.json`** — Konfiguration (Server-IP, Secret, Client-Name)

## Key Lessons for this Task

These are the critical findings from building Mercury v3.0→v3.2:

### Device Auth Installer for Private Repos

To distribute a CLI tool from a **private** GitHub repo with zero-config installation:

1. Host the **installer script as a public Gist** (raw download works without auth)
2. Installer checks for `gh` CLI, installs it if missing (brew/tarball)
3. `gh auth login --web` triggers the **GitHub Device Flow** — browser opens, user clicks Authorize
4. After auth: `gh repo clone` works on private repos automatically
5. **Never use `grep -P`** in bash scripts targeting macOS — use `awk` instead

### Tailscale Userspace Mode (container/Docker)

```bash
# --tun=userspace-networking on tailscaled, NOT on tailscale up!
tailscaled --tun=userspace-networking --socket=/tmp/tailscale.sock --state=/tmp/tailscale.state &

# Client always uses --socket=/tmp/tailscale.sock
tailscale --socket=/tmp/tailscale.sock status
tailscale --socket=/tmp/tailscale.sock up --ssh
```

### Cross-platform Shell Scripting

macOS uses BSD tools which differ from GNU:
- `grep -P` → `awk` for regex extraction
- `sed -i` → `sed -i ''` on macOS
- `readlink -f` → not available
- `realpath` → not available

### Peer-to-Peer Auth Protocol Gotchas

The three most common auth failures:
1. Wrong prefix byte (`b'M'` vs `b'P'`)
2. Wrong JSON field name (`"hash"` vs `"response"`)
3. String vs bytes in SHA256 (`sha256(secret_str + chal_str)` vs `sha256(secret_bytes + chal_bytes)`)


1. **Pip kann fehlen!** — Auf manchen Systemen gibt's `pip` nicht. Immer zuerst prüfen:
   ```bash
   python3 -m pip install websockets 2>/dev/null || {
       # Fallback: asyncio + struct (Pure Python)
   }
   ```
   Der hier dokumentierte Ansatz **braucht kein pip** — alles ist Standardbibliothek.

2. **`asyncio.start_server()` vs `websockets`** — Für einfache TCP-Kommunikation reicht `asyncio.start_server()` völlig. WebSocket ist nur nötig wenn Browser-Kommunikation oder Firewall-Probleme via HTTP-Upgrade.

3. **`ensurepip` kann auch fehlen** — Selbst `python3 -m ensurepip` gibt's nicht auf minimal-Installationen. Deshalb Zero-Dependency-Ansatz.

4. **Windows cmd.exe vs bash** — Bei `subprocess.run()` auf Windows:
   ```python
   if sys.platform == "win32":
       subprocess.run(["cmd.exe", "/c", command], ...)
   else:
       subprocess.run(command, shell=True, ...)
   ```

5. **File System Boundaries** — Docker/mounted Volumes können `git init` blockieren. Lösung: In `~/` (Home) statt `/opt/data/` arbeiten.

6. **Timeout beim `readexactly()`** — Immer `asyncio.wait_for()` um `reader.readexactly()` wrappen, sonst hängt der Client bei verlorenen Verbindungen ewig.

## Deployment

```bash
# 1. Server starten (Dev-Server)
cd ~/mercury-remote
python3 server.py &

# 2. client_config.json auf Target kopieren + editieren
#    secret_hex aus ~/mercury-remote/.secret kopieren
#    server_host auf Dev-Server-IP setzen

# 3. Client starten (Target-PC)
python3 client.py

# 4. Über Mercury CLI interagieren
python3 mercury_cli.py
# shell dir C:\Users
# find_minecraft
# read_file C:\Users\...\.minecraft\crash-reports\crash-xxx.txt
```

## Files im Repo

- `server.py` — Server (Dev-Seite), asyncio TCP-Server
- `client.py` — Client (Target), verbindet sich + verarbeitet Commands
- `mercury_cli.py` — Interaktive Shell für Mercury
- `launch.bat` — Windows-USB-Stick-Launcher
- `launch.sh` — Linux/macOS-Launcher
- `client_config.json` — Konfiguration (Server-IP, Secret, Client-Name)
