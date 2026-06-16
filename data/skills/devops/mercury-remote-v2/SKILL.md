---
name: mercury-remote-v2
description: Mercury Remote v3.0 — Peer-to-Peer Mesh über Tailscale. Zero-Dependency, jeder Rechner ist Server + Client gleichzeitig. Kein zentraler Server nötig.
version: 3.3.0
author: <GITHUB_USER>
---

# Mercury Remote v3.0 — Tailscale Mesh (Peer-to-Peer)

**Architecture:** Peer-to-Peer Mesh. Jeder Rechner läuft `mercury serve` und ist gleichzeitig Server + Client.  
**Discovery:** Tailscale (`tailscale status`) → automatisch alle Peers finden. Kein zentraler Server, kein Port-Forwarding.  
**CLI:** `mercury` (interaktiv), `mercury connect <name>`, `mercury exec <name> <cmd>`, `mercury list`

## Files

| File | Purpose |
|------|---------|
| `mercury.py` | **Hauptprogramm** — Server, Client, CLI in einer Datei (Peer) |
| `server.py` | Legacy: Standalone-Server (Multi-Client-Architektur v2) |
| `client.py` | Legacy: Standalone-Client-Agent (v2) |
| `install.sh` | One-line installer |
| `launch.sh` / `launch.bat` | Start scripts |
| `client_config.json` | Legacy client config |
| `.secret` | Shared auth secret (in Repo-Root, legacy) |
| `~/.mercury/` | **v3 Config dir** — secret, history, peers.json |

## Protocol

**Byte-prefixed length-prefixed JSON over TCP, port 9443.**

```
Prefix (1 byte):  b'P' = Peer connection
Length (4 bytes): Big-endian uint32
Payload (N bytes): UTF-8 JSON
```

### Peer Auth Flow (bidirectional — each peer authenticates the other)

```
Peer A → Peer B: {"type":"peer_hello","challenge":"<hex>","hostname":"dev-server","version":"3.0.0"}
Peer B → Peer A: {"type":"peer_auth","response":"<sha256(secret+challenge)>","hostname":"laptop"}
Peer A → Peer B: {"type":"peer_ok"}
```

After auth, any peer can send commands (it's symmetrical):
```
Peer A → Peer B: {"cmd":"shell","args":{"command":"ls -la","timeout":30}}
Peer B → Peer A: {"ok":true,"stdout":"...","stderr":"...","exit_code":0,"type":"cmd_result"}
```

### Peer Commands

| Command | What it does |
|---------|-------------|
| `shell` / `sh` | Execute shell command on peer |
| `read_file` | Read file, base64-encoded |
| `write_file` | Write file from base64 data |
| `list_dir` | Directory listing |
| `find_minecraft` | Find .minecraft, crash reports, latest.log |
| `system_info` | OS, hostname, python, cwd |
| `ping` | Heartbeat/pong |

## Mercury CLI Modes

```
mercury                   Interactive mode — shows peer list, user selects
mercury serve             Start peer server (background)
mercury peer              Dual-mode: server + keepalive (for background peers)
mercury list / ls / scan  Discover and list all peers
mercury connect <name>    Connect to peer + open interactive terminal
mercury exec <name> <cmd> Execute one command, print output, exit
```

### Interactive Terminal Commands (after connecting)

```
help / h / ?              This help
exit / quit / disconnect  Disconnect from peer
! / sh / shell <cmd>      Run shell command on peer
cat <path>                View file on peer
ls [path]                 List directory on peer
get <remote> [local]      Copy file from peer
put <local> <remote>      Copy file to peer
mc [path]                 Scan Minecraft crash-reports
info                      System information
```

## macOS Permissions for Full Remote Control

For Mercury to control the Mac completely (mouse, keyboard, apps, screenshots), **Terminal** needs 7 permissions in **System Settings → Privacy & Security**:

| # | Permission | What Mercury can do |
|---|---|---|
| 🖥 | **Screen Recording** (`Privacy_ScreenCapture`) | Take screenshots |
| 🖱 | **Accessibility** (`Privacy_Accessibility`) | Move mouse, click, control windows |
| 📁 | **Full Disk Access** (`Privacy_AllFiles`) | Read/write any file |
| ⌨️ | **Input Monitoring** (`Privacy_ListenEvent`) | Simulate keyboard input |
| 🤖 | **Automation** (`Privacy_Automation`) | Control Safari, Finder, other apps |
| 🗂 | **Files & Folders** (`Privacy_FilesAndFolders`) | Desktop, Downloads, Documents access |
| 🔧 | **Developer Tools** (`Privacy_DeveloperTools`) | AppleScript & system commands |

**One-time setup:** Open all permission panes at once:
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture" &
sleep 0.5
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" &
sleep 0.5
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" &
sleep 0.5
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent" &
sleep 0.5
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation" &
sleep 0.5
open "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders" &
sleep 0.5
open "x-apple.systempreferences:com.apple.preference.security?Privacy_DeveloperTools"
```

For each pane: click `+` → select **Terminal** → check the box → enter password/Touch ID.

**Important:** After granting permissions, **restart Mercury** (`mercury peer`) for them to take effect.

## Mercury Mesh Watcher — Cron Job für Peer-Überwachung

Ein cron job, der regelmäßig das Tailscale-Mesh scannt, Mercury Peers identifiziert und neue Peers meldet.

### Workflow (vollständig autonom)

1. **Lese `~/.mercury/known_peers.json`** — Liste bereits bekannter Mercury Peers
2. **Scanne via `discover_peers()`** — ruft `tailscale status` auf (oder Cache-Fallback)
3. **Filtere echte Mercury Peers** — `discover_peers()` gibt ALLE Tailscale-Nodes zurück, nicht nur Mercury. Nur Nodes auf Port 9443 sind Mercury Peers. Proben:
   - TCP connect auf `ip:9443` mit Timeout (10s)
   - SSL wrap (Mercury nutzt rohen TCP, aber manche Peers antworten auf TLS)
   - HTTP GET `/version` oder `/info` für Versionsinfo
4. **Vergleiche** mit `known_peers.json` — wenn ein neuer Hostname/neue IP auftaucht, benachrichtigen
5. **Speichere** aktualisierte `known_peers.json`

### ⚠️ Wichtige technische Fallstricke

- **`read_file()` liefert Zeilennummern** — `read_file()` gibt `1|{...}` zurück (mit Zeilennummer-Präfix), das `json.loads()` mit "Extra data" fehlschlagen lässt. Verwende stattdessen `terminal("cat ~/.mercury/known_peers.json")` um rohes JSON zu bekommen, oder parsiere die Zeilennummern raus.
- **`discover_peers()` != Mercury Peers** — Die Funktion listet *alle* Tailscale-Nodes + Cache. Ein Node, der nicht auf Port 9443 antwortet, ist kein Mercury Peer. apple-tv, iphone-15-pro etc. tauchen regelmäßig auf, sind aber normale Tailscale-Geräte.
- **`tailscaled` läuft nicht immer** — In cron-Kontexten oder Docker kann `tailscale --socket /tmp/tailscale.sock status` fehlschlagen. `discover_peers()` fällt dann auf den PEER_CACHE zurück, der veraltete Daten haben kann.
- **SSL vs Raw TCP** — Mercury benutzt rohen TCP (kein TLS). Ein `SSL: UNEXPECTED_EOF_WHILE_READING` beim Connect auf 9443 deutet darauf hin, dass der Node antwortet aber das Mercury-Protokoll nicht spricht (kein gültiger TLS-Handshake). Timeout auf 9443 = Mercury läuft nicht.

### Beispiel: Neuen Peer erkennen und melden

```python
from hermes_tools import terminal  # für cat, nicht read_file
import json

raw = terminal("cat ~/.mercury/known_peers.json")
known = json.loads(raw["output"])

# discover_peers() aus mercury.py liefert alle Tailscale-Nodes
# Nur solche mit offenem Port 9443 sind Mercury Peers
```

### known_peers.json Schema

```json
{
  "dev-server": {
    "first_seen": "2026-05-20T08:47:20.612782",
    "hostname": "dev-server",
    "version": "3.2.0",
    "ip": "<PRIVATE_IP>"
  }
}
```

## Auto-Discovery (Tailscale)

```python
def discover_peers() -> list[dict]:
    # 1. Try tailscale status — always use --socket for container environments
    ts_bin = shutil.which("tailscale") or os.path.expanduser("~/.local/bin/tailscale")
    if not os.path.isfile(ts_bin):
        ts_bin = "tailscale"
    result = subprocess.run([ts_bin, "--socket", "/tmp/tailscale.sock", "status"], ...)
    # Parse: "<PRIVATE_IP>  dev-server          linux/     active; ..."
    # Extract IP, hostname (strip .tailscale.ts.net suffix)
    
    # 2. Fallback: PEER_CACHE (~/.mercury/peers.json)
    #    Saves known peers so they appear even without tailscale
    
    # 3. Manual: user provides hostname/IP
```

### Tailscale in containerisierten Umgebungen (wichtig!)

Wenn Tailscale auf einem Server in einem Container/einer VM läuft (z.B. LinuxKit, Docker), gilt:

**1. TUN-Device fehlt → Userspace-Networking erzwingen:**
```bash
# ❌ Default mode scheitert mit: /dev/net/tun does not exist
# ✅ Userspace-Networking:
tailscaled --state=/tmp/tailscale.state --socket=/tmp/tailscale.sock --tun=userspace-networking
```

**2. Custom Socket + Binary Pfad:**
```bash
# Tailscale Binary liegt oft in ~/.local/bin/tailscale, nicht in $PATH
~/.local/bin/tailscale --socket /tmp/tailscale.sock status
~/.local/bin/tailscale --socket /tmp/tailscale.sock up --reset --accept-routes --ssh
```

**3. State File:**
```bash
# State in /tmp/ damit er Container-Neustarts überlebt (falls /tmp persistent)
tailscaled --state=/tmp/tailscale.state --socket=/tmp/tailscale.sock --tun=userspace-networking
```

**4. Dashboard-Backend muss wissen wo Tailscale ist:**
```python
# Nicht hardcoded "tailscale" — finde binary:
ts_bin = "tailscale"
home_ts = os.path.expanduser("~/.local/bin/tailscale")
if os.path.isfile(home_ts):
    ts_bin = home_ts
# Benutze custom socket
ts_socket = "/tmp/tailscale.sock"
proc = await asyncio.create_subprocess_exec(ts_bin, "--socket", ts_socket, "status", ...)
```

**5. `tailscale up` mit --reset:**
Wenn beim ersten `tailscale up` ein Fehler kommt dass nicht-default-flags erwähnt werden müssen, IMMER `--reset` verwenden:
```bash
# ❌ Error: changing settings via 'tailscale up' requires mentioning all non-default flags
tailscale up --accept-routes

# ✅ Use --reset to start fresh
tailscale up --reset --accept-routes --ssh
```

Returns: `[{"name":"dev-server","ip":"<PRIVATE_IP>","source":"tailscale","port":9443}]`

## Auto-Update (in mercury.py eingebaut)

```python
# Beim Start von `mercury peer`:
check_update()  # git pull im REPO_DIR
asyncio.create_task(auto_update_loop())  # alle 3600s wiederholen

# Manuell: mercury update / mercury upgrade
# Nach Update: os.execv() neustartet den Peer automatisch
# Manuell: mercury restart

# REPO_DIR = Path(__file__).parent.resolve()
# Prüft auf .git/ → wenn nicht da, silent skip
```

### ⚠️ Wichtiger Bug: Symlink vs Wrapper-Script

`mercury` darf **KEIN Symlink** auf `mercury.py` sein — dann kann Python das Repo-Verzeichnis nicht finden (`Path(__file__).parent` zeigt auf `/usr/local/bin/`, nicht auf `~/mercury-remote/`). Das bricht **Auto-Update** (`check_update()` findet kein `.git/`) und **REPO_DIR** für den Peer-Modus.

Stattdessen ein **Wrapper-Script** in `/usr/local/bin/`:

```bash
sudo tee /usr/local/bin/mercury << 'EOF'
#!/usr/bin/env bash
exec python3 "$HOME/mercury-remote/mercury.py" "$@"
EOF
sudo chmod +x /usr/local/bin/mercury
```

**⚠️ `git checkout -- .` (oder `git pull` bei merge conflicts) löscht den Symlink** — das Wrapper-Script bleibt erhalten. Nach Repo-Updates auf dem Mac muss `mercury peer` neu gestartet werden (Ctrl+C + erneut starten), damit die neue Version geladen wird.

### Auto-Update in mercury.py (v3.2+)

```python
# REPO_DIR muss auf das Git-Repo zeigen — deshalb ist ein Wrapper-Script statt Symlink kritisch!
REPO_DIR = Path(__file__).parent.resolve()

def check_update(silent=False):
    """git pull — updated Mercury auf die neueste Version."""
    git_dir = REPO_DIR / ".git"
    if not git_dir.exists():
        return False  # silent skip wenn kein Git (kein Symlink-Problem)
    result = subprocess.run(["git", "pull"], capture_output=True, text=True, timeout=30, cwd=str(REPO_DIR))
    return "Already up to date" not in result.stdout

# Beim Start von `mercury peer`:
check_update()
asyncio.create_task(auto_update_loop())  # alle 3600s wiederholen

# Manuell: mercury update / mercury upgrade → git pull + os.execv() restart
# Manuell: mercury restart → os.execv() ohne pull
```

### macOS: Symlink nach git checkout wiederherstellen

Nach `git checkout -- .` oder `git pull` der den Symlink löscht:
```bash
sudo rm -f /usr/local/bin/mercury
sudo tee /usr/local/bin/mercury << 'EOF'
#!/usr/bin/env bash
exec python3 "$HOME/mercury-remote/mercury.py" "$@"
EOF
sudo chmod +x /usr/local/bin/mercury
chmod +x ~/mercury-remote/mercury.py
```

Dann `mercury peer` starten.

### Auto-Update Fehlersuche

Wenn `check_update()` meldet "⚠️ Kein Git-Repo — Auto-Update nicht möglich", liegt das meistens am Symlink-Problem (s.o.) — `__file__` ist `/usr/local/bin/mercury` → `.git/` nicht gefunden. Fix: Wrapper-Script statt Symlink.

## Screenshot aus Remote-Mac in Telegram delivery

Um einen Screenshot vom Mac ins Telegram zu senden:

1. Auf dem Mac: `screencapture -x /tmp/shot.png` → `base64` → stdout
2. Auf dem Server: base64 decoden → als PNG speichern
3. **Wichtig: `MEDIA:` Annotation muss in der Assistant-Antwort stehen, NICHT in `execute_code` output oder `send_message`.**

```python
# execute_code → speichert die Datei
img_data = base64.b64decode(out)
with open('/path/to/output/screenshot.png', 'wb') as f:
    f.write(img_data)
print(f"MEDIA:/path/to/output/screenshot.png")  # ← Das allein reicht NICHT!
```

Stattdessen nach dem execute_code in der **direkten Antwort** des Assistant:
```
Hier ist der Screenshot:

MEDIA:/path/to/output/screenshot.png
```

**Alternative:** Die Datei in `~/./cron/output/` speichern (wird automatisch von cron delivery erfasst) oder `send_message` mit dem MEDIA-Pfad. In der Praxis: einfach `MEDIA:` in die letzte Nachricht des Assistant schreiben.

**Edge Cases:**
- `screencapture -x` braucht **Screen Recording** Permission auf macOS
- Große Screenshots (Retina 5K) können mehrere MB sein → ggf. verkleinern vor base64
- `mktemp` ist macOS-spezifisch — funktioniert aber auf Macs 🍎

## Remote-Commands (Chat → Mac)

Du kannst von hier (Dev-Server) Shell-Befehle auf dem Mac ausführen. Das Protokoll:

1. TCP verbinden (<PRIVATE_IP>:9443)
2. Prefix `b'P'` senden
3. `peer_hello` empfangen → `challenge` als `bytes.fromhex()` parsen
4. Auth: `hashlib.sha256(SECRET_BYTES + CHALLENGE_BYTES).hexdigest()` — **beide als bytes!**
5. Auth-JSON-Feld heisst **"response"**, nicht "hash"!
6. Befehl senden: `{"cmd":"shell","args":{"command":"...","timeout":30}}`
7. Antwort: `{"ok":true,"stdout":"...","stderr":"...","exit_code":0,"type":"cmd_result"}`

### Praktische Remote-Befehle für macOS

| Was | Befehl |
|-----|--------|
| App löschen | `osascript -e 'tell app "Finder" to delete POSIX file "/Applications/Name.app"'` |
| App beenden | `pkill -f "AppName"` |
| Safari öffnen | `open -a /Applications/Safari.app https://google.com` |
| Safari Tabs sehen | `osascript -e 'tell app "Safari" to get name of every tab of front window'` |
| App suchen | `mdfind "kMDItemKind == \"Application\"" \| grep -i name` |
| System-Info | `sw_vers` (macOS), `uname -a` (Kernel) |
| Kalender (heute) | `icalBuddy -n -nc eventsToday` (vorher: `brew install ical-buddy`) |

### system_info response — field names (wichtig!)

Der mercury.py Handler (Zeile 220) sendet `system_info` als **flaches Dict mit diesen Feldern**:

```python
# Antwort von {"cmd": "system_info"}:
{
    "ok": True,
    "hostname": "FSU-QV7T75JMGV",
    "platform": "darwin",          # sys.platform
    "python": "3.13.3 ...",
    "machine": "arm64",            # platform.machine()
    "system": "Darwin",            # platform.system() — NICHT "os"!
    "release": "26.0",             # platform.release()
    "type": "cmd_result"
}
```

**⚠️ Feldname ist `"system"`, nicht `"os"`!**  
Wenn du ein Dashboard baust, das die OS-Information parst:
```python
# ✅ RICHTIG
os_name = info.get("system", "unknown")  # "Darwin", "Linux", "Windows"
# ❌ FALSCH — existiert nicht
os_name = info.get("os", "unknown")
```

### Kalender-Zugriff auf macOS 26+ via Mercury Remote

macOS 26 hat die Calendar.sqlitedb durch EventKit ersetzt — die alte DB ist 0 Bytes groß.
Der Zugriff funktioniert NICHT via sqlite3, sondern nur über EventKit-Tools.

**Setup (einmalig auf dem Mac):**
```bash
# 1. icalBuddy installieren
brew install ical-buddy

# 2. Kalender-Berechtigung für Terminal erteilen
#    Systemeinstellungen → Datenschutz & Sicherheit → Kalender
#    → Terminal hinzufügen ✅

# 3. Nach Berechtigung: Mercury Peer neustarten!
mercury restart
```

**Verfügbare Kommandos (nach Setup):**
```bash
# Heutige Termine
icalBuddy -n -nc -b "" -ic "" -iep datetime,title,calendar -ps " | " -po datetime,title,calendar eventsToday

# Termine mit Details
icalBuddy -n -nc -ic "" -iep datetime,title,calendar,location -ps " | " eventsToday

# Alle Kalender auflisten
icalBuddy -n calendars
```

**Fallstricke:**
- `icalBuddy` ohne Berechtigung gibt `"error: No calendars."` — das bedeutet: Terminal hat keine Kalender-Freigabe in System Settings
- Auch nach Berechtigung: `mercury peer` NEU starten (Ctrl+C → neu starten), sonst bleiben die Rechte unsichtbar
- Auf macOS 26+ funktioniert die `Calendar.sqlitedb` **nicht mehr** — immer 0 Bytes

### macOS 26: Calendar Privacy Permission per Remote öffnen

```bash
# Kalender-Privacy-Einstellung auf dem Mac öffnen (per Mercury Remote):
open "x-apple.systempreferences:com.apple.preference.security?Privacy_LinkedIn"
```

## Mercury Watcher (`mercury-watcher.py`)

```bash
python3 mercury-watcher.py --once      # Einmal scannen
python3 mercury-watcher.py              # Loop (alle 30s)
python3 mercury-watcher.py --exec "hostname" "uname -a"  # Remote-Befehl
```

## Auth: Byte vs String Encoding

**⚠️ Beim händischen Test mit `execute_code` zwei häufige Bugs:**

1. **Prefix** — `mercury.py` erwartet `b'P'`, nicht `b'M'`
2. **Auth Field Name** — Der Server prüft `msg.get("response")`, also **"response"** senden, nicht "hash"
3. **SHA256 Input** — `hashlib.sha256(SECRET_BYTES + CHALLENGE_BYTES)` — beide Werte als **bytes**, nicht hex strings!

```python
# ✅ So authentifiziert man sich korrekt zu einem Peer:
secret_bytes = bytes.fromhex(SECRET_HEX)  # ~/.mercury/secret als bytes
chal_bytes = bytes.fromhex(msg["challenge"])
expected = hashlib.sha256(secret_bytes + chal_bytes).hexdigest()
auth = {"type": "peer_auth", "response": expected, "hostname": "dev-server"}
```

## macOS grep Kompatibilität

Niemals `grep -P` in Bash-Skripten verwenden — macOS BSD grep hat kein `-P`.

```bash
# ❌ macOS: grep: invalid option -- P
ver=$(python3 --version | grep -oP '\d+\.\d+')

# ✅ Cross-platform mit awk
ver=$(python3 --version 2>&1)
major=$(echo "$ver" | awk -F'[ .]' '{print $2}')
minor=$(echo "$ver" | awk -F'[ .]' '{print $3}')
```

## Tailscale Dateiname (wichtig!)

**KEIN `linux` im Dateinamen** — auch für Linux arm64:

```bash
# ✅ RICHTIG
https://pkgs.tailscale.com/stable/tailscale_1.98.2_arm64.tgz
# ❌ FALSCH (404)
https://pkgs.tailscale.com/stable/tailscale_1.98.2_linux_arm64.tgz
```

## Device Auth Installer (private Repos)

Das Repo ist private. Der Installer wird als **public Gist** gehostet:

```bash
curl -sL https://gist.githubusercontent.com/<GITHUB_USER>/82e33d7c2aa5826aa486f93b2f06edc6/raw/install-mercury.sh | bash
```

Ablauf: Python check → gh install (falls nötig) → `gh auth login --web` (Safari öffnet sich) → `gh repo clone` (private Repos erlaubt, weil gh logged in ist).

## Key Design Decisions

| Decision | v2.0 (old) | v3.0 (current) |
|----------|-----------|-----------------|
| **Architecture** | Central server → clients | Peer-to-peer mesh |
| **Discovery** | Manual config | Tailscale status + cache |
| **Server needed?** | Yes | No — every machine is a peer |
| **Port** | 9443 | 9443 (same) |
| **Python file** | server.py + client.py + mercury.py | **mercury.py** (all-in-one) |
| **Config** | client_config.json | `~/.mercury/` directory |
| **Prefix byte** | `C` (client), `M` (commander) | `P` (peer) |

## Installation

### On every machine in the mesh:

```bash
# 1. Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# 2. Mercury
curl -sL https://raw.githubusercontent.com/<GITHUB_USER>/mercury-remote/main/install.sh | bash
mercury peer   # Start peer mode (server + client)
```

### On one machine (the one you're sitting at):

```bash
mercury          # Interactive — shows all peers
# or
mercury connect dev-server   # Direct connect
```

## Pitfalls

- **`StreamWriter` vs `StreamReader`** — When you open a connection with `asyncio.open_connection()`, you get `(reader, writer)`. To receive data, use `reader` (not `writer`). The `recv()` function must accept the reader:
  ```python
  # CORRECT
  async def recv(r: asyncio.StreamReader, timeout=30) -> dict | None:
      raw = await asyncio.wait_for(r.readexactly(4), timeout)
      ...

  # WRONG — writer has no readexactly!
  async def recv(w: asyncio.StreamWriter, timeout=30):
      raw = await asyncio.wait_for(w.readexactly(4), timeout)  # AttributeError!
  ```
- **`server.sockets[0]` subscript** — `asyncio.start_server().sockets` returns a list of `TransportSocket` objects, which are NOT subscriptable like tuples. Use `server.sockets[0].getsockname()` instead of `server.sockets[0][0]`.
- **`platform` module name collision** — If you use `import platform` in a module that also uses the `platform` variable, Python's stdlib `platform` module gets shadowed. Use `import platform as platform_mod` for the stdlib module.
- **F-string escaped quotes** — Some Python versions (3.13+) have stricter f-string parsing. NEVER use escaped quotes inside nested f-strings:
  ```python
  # ❌ WRONG — SyntaxError in Python 3.13
  print(f"  {col(C.CYAN, p[\"name\"])}")
  
  # ✅ CORRECT — intermediate variable
  pname = p.get("name", "?")
  print(f"  {col(C.CYAN, pname)}")
  ```
- **Auto-discovery without Tailscale** — If Tailscale is not installed, only cached peers appear. The cache fills when peers are found via Tailscale or manually connected.
- **Secret mismatch** — Every peer must share the same `~/.mercury/secret`. By default, each fresh install generates its own. You must copy the secret from one machine to others, or the `install.sh` does it automatically if `--secret` is provided.
- **Firewall rules** — Port 9443 must be open locally. Tailscale handles NAT traversal, but the local firewall must allow inbound on 9443.
- **Interactive mode blocking** — The interactive mode uses `input()` which blocks the event loop. The background reader can't process messages during `input()`. This is mitigated by the 5-second client list broadcast and the fact that peer commands are request-response (blocking is fine).
