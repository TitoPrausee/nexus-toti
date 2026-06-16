---
name: mac-daily-maintenance
description: Tägliche Mac-Reinigung und Ressourcen-Überwachung via Mercury Remote. Prüft RAM, Swap, Disk und räumt Caches/Logs auf. Kann als Cron-Job laufen.
version: 2.1.0
author: Mercury
license: MIT
---

# Mac Daily Maintenance

## Überblick
Tägliche Routine für den Mac über Mercury Remote:
1. **Ressourcen-Check** — RAM, Swap, Disk, DisplayLink-Prozesse
2. **Aufräumen** — Caches, Logs, Tempfiles (sicher, kein Docker)
3. **Dashboard-Update** — Status speichern
4. **Bericht** — Zusammenfassung via Telegram

## Voraussetzungen
- Mercury Remote Verbindung zum Mac (<PRIVATE_IP>:9443)
- Secret in `~/.mercury/secret`
- `icalBuddy` optional installiert
- Dashboard `get_mac_health.py` in `~/.mercury/`

## 🔴 CRITICAL: Shell Quoting durch Mercury Remote

**Problem:** Komplexe Shell-Kommandos mit Pipes (`|`), Quotes (`'"`), `awk` und Variablen durch Mercury Remote JSON zu senden (= in `{"cmd":"shell","args":{"command": "..."}}` verpacken) führt zu unendlichem Escape-Desaster.

**Lösung:** NIEMALS komplexe Shell-Befehle inline senden. Stattdessen:
1. Ein **Python-Skript auf dem DEV-SERVER** schreiben (`~/.mercury/get_mac_health.py`)
2. Dieses Skript verbindet sich via Mercury zum Mac, auth't, sendet **einfache Einzelbefehle**
3. Dashboard ruft das Skript per `create_subprocess_exec` auf → sauber, kein Quote-Hell

```python
# ✅ RICHTIG: Externes Skript + create_subprocess_exec
script_path = Path.home() / ".mercury" / "get_mac_health.py"
proc = await asyncio.create_subprocess_exec(
    sys.executable, str(script_path),
    stdout=asyncio.subprocess.PIPE,
)
stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
data = json.loads(stdout.decode().strip())
```

```python
# ❌ FALSCH: Inline Shell durch Mercury Remote (explodiert bei Quotes)
cmd = "df -h ... | awk '{print $3}'  # <- Quotes in JSON escaped = disaster
```

### Das get_mac_health.py Pattern

Das Skript auf dem Dev-Server führt **einfache Einzelbefehle** pro Feld aus:

```python
# send_cmd() wrapper kapselt Mercury Protocol + Timeout
async def send_cmd(r, w, command, timeout=10):
    p = json.dumps({"cmd":"shell","args":{"command":command,"timeout":timeout}}).encode()
    w.write(struct.pack("!I", len(p)) + p)
    await w.drain()
    raw = await asyncio.wait_for(r.readexactly(4), timeout + 5)
    return json.loads(await r.readexactly(struct.unpack("!I", raw)[0]))

# Einfache Einzelbefehle — KEINE Pipes, KEINE doppelten Quotes
res = await send_cmd(r, w, "df -h /System/Volumes/Data 2>&1 | tail -1 | awk '{print $3,$4,$2}'", 5)
out = (res.get("stdout","") or "").strip().split()
if len(out) >= 3:
    data["disk_used"] = out[0]
```

**Faustregel:** Wenn der Shell-Befehl mehr als ein `|` oder geschachtelte Quotes hat → in ein externes Skript auslagern.

## Ablauf

### 1. Verbinden & Auth
```python
secret = bytes.fromhex(open(os.path.expanduser("~/.mercury/secret")).read().strip())
r, w = await asyncio.wait_for(asyncio.open_connection("<PRIVATE_IP>", 9443), 5)
w.write(b"P")
# auth handshake ...
```

### 2. Health-Check (als Einzelbefehle)
- `df -h /System/Volumes/Data | tail -1 | awk '{print $3,$4,$2}'` — Disk: used, free, total
- `sysctl vm.swapusage` — Swap: **Achtung deutsches Locale** → Komma als Dezimaltrenner: `7168,00M`
- `ps aux | grep -i DisplayLinkUserAgent | grep -v grep | awk '{print $3,$4}'` — DisplayLink CPU+Mem
- `uptime | sed 's/.*up //' | sed 's/,.*//'` — Uptime im Klartext

### 3. Swap Parsing (deutsches Locale!)
`sysctl vm.swapusage` liefert: `total = 7168,00M  used = 6655,06M  free = 512,94M`

Mit Regex parsen, nicht mit Split:
```python
import re
sw_m = re.search(r'used\s*=\s*(\S+)', out)
if sw_m: data["swap_used"] = sw_m.group(1)  # "6655,06M"
```

Für Health-Scoring in MB umrechnen:
```python
su = "6655,06M"
su_clean = su.replace(",",".").replace("G","*1024").replace("M","")
su_num = float(su_clean.split("*")[0]) if "*" not in su_clean else float(su_clean.split("*")[0]) * 1024
```

### 4. Cleaning (nur wenn Disk < 30 GB frei)
```bash
rm -rf ~/Library/Caches/* 2>/dev/null
rm -f ~/Library/Logs/desktop_organizer*.log 2>/dev/null
rm -rf ~/Library/Logs/CCleaner/ 2>/dev/null
rm -rf ~/.npm/_cacache/* 2>/dev/null
# Python cache files
find ~ -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
# Brew cleanup
brew cleanup 2>&1 | tail -2
# Old downloads
find ~/Downloads -type f -mtime +30 -delete 2>/dev/null
```

**⚠️ NIEMALS anfassen:**
- Docker-Container, Images, Volumes (`/var/lib/docker/`, `~/.docker/`)
- `node_modules/` Verzeichnisse
- `Library/Containers/` (App-Sandboxes)
- `.git/` Verzeichnisse

**Weitere sichere Cleanups:**
```bash
# Homebrew cache
rm -rf $(brew --cache)/* 2>/dev/null
# cloudflared Logs
find ~/.cloudflared -name "*.log" -delete 2>/dev/null
# Browser Caches
rm -rf ~/Library/Caches/com.google.Chrome/*
rm -rf ~/Library/Caches/org.mozilla.firefox/*
rm -rf ~/Library/Caches/com.apple.Safari/*
# Gem cleanup
gem cleanup 2>&1 | tail -3
# Trash
rm -rf ~/.Trash/* 2>/dev/null
```

### 5. Dashboard-Update
```bash
# Status in /tmp/mac_status.json (wird vom dashboard /api/mac-health gelesen)
python3 ~/.mercury/get_mac_health.py > /tmp/mac_status.json
```

### 6. Ergebnis senden
```python
bericht = f"""🧹 MAC MAINTENANCE
📅 {datum}

💿 Disk: {disk_free} frei von {disk_total} ({warn_disk})
💾 Swap: {swap_used}/{swap_total} ({swap_pct:.0f}%) ({warn_swap})
⏱️  Uptime: {uptime} ({warn_uptime})
🖥️  DisplayLink: {'✅ läuft' if displaylink else '❌ abgestürzt'}

🧹 Aufräumen: {'✅ erledigt' if cleaned else '⏭️ nicht nötig'}
Frei gemacht: ~{freed_gb} GB

⚠️ Warnungen:
{'- Disk < 15 GB 🔴' if disk_gb < 15 else '- Disk < 30 GB 🟡' if disk_gb < 30 else '- Disk OK 🟢'}
{'- Swap > 80% 🔴' if swap_pct > 80 else '- Swap > 50% 🟡' if swap_pct > 50 else '- Swap OK 🟢'}
{'- Uptime > 14d 🔴' if uptime_days > 14 else '- Uptime > 7d 🟡' if uptime_days > 7 else '- Uptime OK 🟢'}

💡 Empfehlung{'EN: Neustart!' if uptime_days > 14 else ': keine'}
"""
```

## DisplayLink Behandlung

### Status prüfen
```bash
ps aux | grep -i DisplayLinkUserAgent | grep -v grep | head -1
```
Ausgabe: `tito1   1524   0,0  0,0 ... /Applications/DisplayLink Manager.app/Contents/MacOS/DisplayLinkUserAgent`
→ `$3` = CPU%, `$4` = MEM%

### Neustart (wenn abgestürzt)
```bash
# Kill
killall DisplayLinkUserAgent 2>/dev/null
sleep 2
# Relaunch
open -a "DisplayLink Manager" 2>/dev/null
```

**Pitfall:** `killall DisplayLinkManager` findet nichts — der korrekte Prozessname ist `DisplayLinkUserAgent`. `launchctl bootout` scheitert ohne Root. `open -a` als Fallback funktioniert zuverlässig.

## DisplayLink Crash Diagnose

Wenn DisplayLink wiederholt abstürzt, ist die **wahrscheinlichste Ursache Swap-Überlastung + voller Massenspeicher**:

```
💿 Disk: 12 GB frei (98%)  →  macOS kann keinen Swap mehr schreiben
💾 Swap: 6/7 GB belegt (86%)
⏱️  Uptime: 16 Tage
```

**Diagnose-Schritte:**
1. `df -h /System/Volumes/Data` → Ist Disk < 15 GB frei? → 🔴
2. `sysctl vm.swapusage` → Ist Swap > 80%? → 🔴
3. Ist Uptime > 7 Tage? → Swap sammelt sich an
4. **Treffer wenn:** Disk < 15 GB **UND** Swap > 80% **UND** Uptime > 7 Tage

**Lösung:** Disk freiräumen (Ziel 30+ GB) + Neustart (leert Swap komplett)

## Multi-Pass Cleanup Strategie

Aufräumen nicht auf einmal, sondern in **Phasen mit Zwischenkontrolle**:

### Pass 1 — Caches + Logs (schnell, ~1-2 GB)
```bash
rm -rf ~/Library/Caches/* 2>/dev/null
rm -f ~/Library/Logs/desktop_organizer*.log
rm -rf ~/Library/Logs/CCleaner/
```

### Pass 2 — Brew + Python + System (mittel, ~2-5 GB)
```bash
brew cleanup && brew autoremove
find ~ -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
gem cleanup 2>&1 | tail -3
rm -rf $(brew --cache)/*
```

### Pass 3 — Browser Caches + Downloads (groß, ~3-8 GB)
```bash
rm -rf ~/Library/Caches/com.google.Chrome/*
rm -rf ~/Library/Caches/org.mozilla.firefox/*
rm -rf ~/Library/Caches/com.apple.Safari/*
find ~/Downloads -type f -mtime +30 -delete 2>/dev/null
rm -rf ~/.Trash/*
```

**Nach jeder Phase** `df -h` checken → wenn Ziel (30+ GB frei) erreicht, abbrechen.

## macOS 26 Besonderheiten
- **Calendar.sqlitedb ist 0 Bytes** — Apple speichert Kalender via EventKit, nicht mehr in SQLite
- AppleScript für Kalender funktioniert, braucht aber **Automation-Berechtigung** in Datenschutz
- Terminal muss in **Systemeinstellungen → Datenschutz → Kalender** freigegeben werden
- `icalBuddy` installieren via `brew install ical-buddy`
- TCC-Datenbank liegt in `~/Library/Application Support/com.apple.TCC/TCC.db`

## Dashboard Integration

### API Endpoint (`/api/mac-health`)
```python
# In mercury_web.py:
import sys
from pathlib import Path

async def handle_mac_health(request):
    script_path = Path.home() / ".mercury" / "get_mac_health.py"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(script_path),
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
    data = json.loads(stdout.decode().strip())
    # Health scoring...
    return web.json_response(data)
```

**Wichtig:** `sys` muss oben im File importiert sein, nicht nur in der Funktion.

### Frontend Widget (pollt alle 30s)
```javascript
async function updateMacHealth() {
    const resp = await fetch('/api/mac-health');
    const data = await resp.json();
    // Update DOM elements...
    // Color-code: stat-critical (🔴), stat-warn (🟡), stat-ok (🟢)
}
setInterval(updateMacHealth, 30000);
```

### JSON Response Format
```json
{
    "mac_reachable": true,
    "disk_used": "397Gi",
    "disk_free": "22Gi",
    "disk_total": "460Gi",
    "swap_total": "7168,00M",
    "swap_used": "6655,06M",
    "swap_free": "512,94M",
    "displaylink_running": true,
    "displaylink_cpu": "1,7",
    "displaylink_mem": "0,5",
    "uptime": "16 days",
    "warnings": ["🟡", "🔴"]
}
```

## Cron-Integration
```bash
# Täglich 03:00 UTC
0 3 * * *  cd /tmp/mercury-web && python3 backend/mercury_web.py
```
Cron-Job lädt den Skill `mac-daily-maintenance`, führt Health-Check + Cleaning durch, sendet Bericht via Telegram.

## Fehlerbehandlung
- Bei Verbindungsfehler: 3x wiederholen mit 5s Pause
- Bei Timeout: Teilbericht senden ("Teilweise fehlgeschlagen")
- Bei Auth-Fehler: Report "🔴 Mac nicht erreichbar (Auth)"
- Bei leerem Output aus get_mac_health.py: HTTP 503 + "no output"

## 🔴 Knowledge Base = Mercury-Vault

Das **"Gemeinsame Wissen im Tailscale"** wird aktuell noch gar nicht als "Knowledge Base" betrieben — es gibt kein separates Repo, keine Datenbank, keinen Service dafür.

**Aktueller Stand:** Eine `mercury-knowledge` wurde im vorherigen Session-Durchlauf geplant und Subagenten gestartet, aber die Ergebnisse gingen durch Context-Compaction verloren. Das Repo wurde (noch) nicht auf GitHub erstellt oder die Commits nie gepusht.

**Lösung:** Wenn der User fragt: "Wie steht es um die Knowledge Base?" → ehrlich sagen: **"Es gibt sie (noch) nicht"** und anbieten, sie jetzt aufzusetzen.

**Empfohlener Ansatz (für späteren Bau):**
- Backend: FastAPI + SQLite (einfach, kein externes DBMS) auf Dev-Server :9444
- Optional: Vektorsuche via sqlite-vss oder MiniLM for semantic retrieval
- Frontend: Als neues Tab im bestehenden Dashboard
- Zugriff: Tailscale-only (<PRIVATE_IP>:9444)
- Datenmodell: `(id, title, content, tags, source, created_at, updated_at, embedding)`

## Tailscale Crash Recovery (Dev Server)

Der `tailscaled`-Daemon kann sich **sauber herunterfahren** (`control: client.Shutdown`) ohne ersichtlichen Grund — kein Crash, kein OOM, keine Fehlermeldung. Zurück bleibt ein **Zombie-Prozess** (Status `Z`).

**Erkennung:**
```bash
ps aux | grep tailscale | grep -v grep
# → hermes  66296  0.0  0.0  0  0 ?  Z  May08  0:00 [tailscale] <defunct>
ls -la /tmp/tailscale.sock
# → No such file or directory
```

**Wichtig:** Der Zombie `[tailscale] <defunct>` ist der **Client**, nicht der Daemon (`tailscaled`). Der Daemon-Prozess ist bereits tot. Es reicht, den Daemon neu zu starten — der Zombie räumt sich von selbst weg.

**Recovery:**
```python
# 1. Daemon starten (background=true!)
terminal(
    command="~/.local/bin/tailscaled --state=/tmp/tailscale.state "
            "--socket=/tmp/tailscale.sock --tun=userspace-networking",
    background=True
)

# 2. Warten auf Verbindung (poll bis health ok)
process(action="poll", session_id="proc_xxx")
# → Suche nach: "health(warnable=not-in-map-poll): ok"

# 3. Status prüfen
terminal(command="~/.local/bin/tailscale --socket=/tmp/tailscale.sock status")
```

**Pitfall:** Der alte `tailscaled`-State (`/tmp/tailscale.state`) hat den Auth-Key **nicht** gespeichert → der Neustart erfolgt ohne expliziten Key, aber Tailscale merkt sich die Machine-Autorisierung (`machineAuthorized=true` → kein re-Login nötig). Funktioniert auch ohne `--authkey`-Flag.

## Tailscale Peers (Stand Mai 2026)

Aktuelle aktive Peers im Netz (tito1708@):
| Peer | IP | OS | Status |
|---|---|---|---|
| **Dieser Server** | `<PRIVATE_IP>` | Linux | ✅ Online |
| **Mac** (<HOSTNAME>) | `<PRIVATE_IP>` | macOS | ✅ Online |
| **Anderer Mac** (fsu-c02fgd2tmd6m) | `<PRIVATE_IP>` | macOS | ❌ Offline (seit 18h) |
| **iPhone 15 Pro** | `<PRIVATE_IP>` | iOS | ✅ Online |
| **Apple TV** | `<PRIVATE_IP>` | tvOS | ✅ Online |
| **Andere** | diverse | diverse | Alle offline (2d-491d) |

Dashboard/Mercury Remote: nur über die **aktiven Peers** (`<PRIVATE_IP>` Mac, `<PRIVATE_IP>` Server).

## Common Pitfalls

1. **🚫 Shell Quotes in JSON** — NIEMALS komplexe Shell-Befehle mit `'"` durch Mercury Remote jagen. Immer externes Python-Skript.
2. **🚫 `sys` nicht importiert** — Dashboard `handle_mac_health` braucht `import sys` oben im File
3. **🚫 Deutsches Locale** — Swap-Werte haben `,` als Dezimaltrenner: `7168,00M`. Immer mit Regex + `replace(",",".")` parsen.
4. **🚫 Docker anfassen** — NIEMALS Docker-Container/Images löschen
5. **🚫 Calendar.sqlitedb** — ist auf macOS 26+ 0 Bytes, AppleScript/icalBuddy nutzen
6. **🚫 `killall DisplayLinkManager`** — Falscher Name. Korrekt: `DisplayLinkUserAgent`
7. **🚫 Process läuft länger als Cron-Timeout** — Einzelne Shell-Befehle timeouten nach 8s
8. **🚫 `port = 8080` ist belegt** — Vor Dashboard-Start immer `fuser -k 8080/tcp`
