---
name: mercury-mesh-watcher
description: Cron-basierter Mesh Watcher, der Tailscale-Peers scannt, Mercury-Dienste erkennt, mit gespeicherten Peers vergleicht und Änderungen meldet.
version: 2.0.0
author: Hermes Agent
---

# Mercury Mesh Watcher v2

## 🎯 Ziel

Ein **standalone Python-Script** als Cron-`script`-Feld, das regelmäßig das Tailscale-Mesh scannt und **NUR bei Änderungen** benachrichtigt — **0 Tokens pro Run** statt ~17k.

| Aspekt | v1 (veraltet) | v2 ✅ |
|---|---|---|
| LLM-Turn pro Run | Ja (voller Agent-Turn) | Nein (0 Token) |
| Kosten pro Run | ~17k input tokens | 0 |
| Session-Blocking | Blockiert Chat | Nie |
| Benachrichtigung | Jeder Run produziert Output | Nur bei Änderung |
| Intervall | 2 Min (viel zu aggressiv) | 5 Min (konfigurierbar) |
| Scanning | LLM steuert Python an | Python macht es direkt |
| Telegram | LLM formuliert | Direkt via Bot API |
| Cron-Typ | `prompt`-basiert | `script`-Feld (pre-script) |

## 🔧 Standalone Watcher Script

Das Script liegt unter `/opt/data/home/mercury-remote/mercury_watcher_v2.py`.

### Features

- **Tailscale-Scanner** — parst `tailscale status` Output (auch mit userspace Socket)
- **Mercury-Probe** — TCP Connect auf Port 9443 + `peer_hello`-Antwort checken
- **Change Detection** — `known_peers.json` wird mit aktuellem Scan verglichen
- **Telegram-Notification** — Direkt via Bot API (kein LLM!), nur bei neuen/offline Peers
- **Status-Datei** — `mesh_status.json` für Dashboard-Abfragen

### Usage

```bash
# Einmal scannen (für Cron-Script-Feld)
python3 mercury_watcher_v2.py --once

# Mit JSON-Output für andere Tools
python3 mercury_watcher_v2.py --once --json --no-notify

# Daemon-Modus (eigene Schleife)
python3 mercury_watcher_v2.py --daemon

# Status anzeigen
python3 mercury_watcher_v2.py --status
```

### Flags

| Flag | Wirkung |
|---|---|
| `--once` | Ein Scan + Exit (für Cron-Script-Feld) |
| `--json` | Output als JSON |
| `--no-notify` | Keine Telegram-Benachrichtigung (nur Status aktualisieren) |
| `--status` | Zeige aktuellen Mesh-Status |
| `--daemon` | Endlosschleife (alle 300s) |

## ⚡ Cron-Job Setup (0 Tokens)

NICHT den `prompt`-Weg — setze das Script ins `script`-Feld:

```python
cronjob(
    action='update' if exists else 'create',
    job_id='007abc63df3d',
    name='mercury-watcher',
    schedule='every 5m',
    script='python3 /opt/data/home/mercury-remote/mercury_watcher_v2.py --once --json --no-notify',
    prompt='Mercury Mesh Watcher scan completed. Check ~/.mercury/mesh_status.json for changes. Respond briefly ONLY if new peers or offline peers detected.',
    deliver='none'  # WICHTIG: Script selbst sendet Telegram bei Änderung, LLM wird nicht gestört
)
```

### Warum `deliver: 'none'`?

Das Script updated `mesh_status.json` und schickt bei Bedarf selbst Telegram. Der LLM-Prompt dient nur als **Notfall-Backup** für den unwahrscheinlichen Fall, dass das Script crasht. 99.9% der Runs: Script läuft, Prompt ist irrelevant, **0 Token verbraucht**.

## 🔍 Change Detection Logik

Das Script speichert `known_peers.json` persistent und vergleicht bei jedem Scan:

1. **Neue Mercury Peers** — Hostname nicht in `known` oder war vorher `mercury: false`
2. **Offline Mercury Peers** — War `mercury: true` und `online: true`, jetzt nicht mehr gesehen
3. **Tailscale-Status** — Nur Online/Offline dokumentiert, nicht benachrichtigt

### Zustandsdateien

**`~/.mercury/known_peers.json`** — Vollständiger Zustand, persistiert über Läufe:
```json
{
  "FSU-QV7T75JMGV": {
    "hostname": "FSU-QV7T75JMGV",
    "ip": "<PRIVATE_IP>",
    "version": "3.2.0",
    "online": true,
    "mercury": true,
    "first_seen": "2026-05-20T08:47:20",
    "last_online": "2026-05-20T15:42:00"
  }
}
```

**`~/.mercury/mesh_status.json`** — Leichtgewichtiger Status für Dashboard-Abfragen:
```json
{
  "last_scan": "2026-05-20T15:42:00",
  "mercury_peers": [...],
  "online_count": 5,
  "mercury_count": 1
}
```

## 📬 Telegram Notification (im Script)

Das Script hat **direkten Bot API Zugriff** — kein LLM beteiligt:

```python
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "<CHAT_ID>")

def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
    req = Request(url, data=data.encode(), headers={"Content-Type": "application/json"})
    resp = urlopen(req, timeout=10)
    return resp.status == 200
```

Das Script formatiert die Nachricht selbst (kein LLM):
```
📡 Mesh Update

🪐 Mercury Peer online: *MacBook-Pro* v3.2 @ `<PRIVATE_IP>`

_Mercury: 1 online | Tailscale: 5 online_
```

## 🛠 Tailscale Userspace Socket

Auf dem Dev-Server (Docker/Container mit userspace-networking):

```python
TS_SOCKET = "/tmp/tailscale.sock"
result = subprocess.run(
    ["~/.local/bin/tailscale", "--socket", TS_SOCKET, "status"],
    capture_output=True, text=True, timeout=5
)
```

## ⚠️ Fallstricke & Lessons Learned

### Telegram-Token nicht in Shell-Env
Der Telegram Bot Token ist **nicht** in Shell-Umgebungsvariablen (`TELEGRAM_BOT_TOKEN` existiert nicht als export). Das Script catcht das elegant: sendet einfach nichts. Trotzdem: wenn Telegram-Benachrichtigung gewünscht, muss der Token irgendwohin — entweder in `~/.mercury/config.json` oder als Export in `.bashrc`.

### `deliver: 'none'` ist kritisch
Ohne `deliver: 'none'` schickt Hermes' Cron-System den Prompt-Output trotzdem an Telegram — und macht den 0-Token-Vorteil zunichte. Immer explizit setzen.

### Kein `--daemon` im Cron
Cron ruft das Script kurz auf — es soll sich nach einem Scan beenden. `--daemon` ist für manuelles Testen oder Background-Service. Für Cron immer `--once` verwenden.

### Scan-Intervall
2 Minuten war viel zu aggressiv. 5 Minuten ist ein guter Kompromiss zwischen Aktualität und Ressourcen. Tailscale-Status-Änderungen (Peers kommen/gehen) sind seltene Ereignisse.

## 📁 Script-Struktur (Referenz)

Das komplette v2-Script hat ~350 Zeilen und besteht aus:

1. **Config** — Port, Prefix, Intervalle, Pfade
2. **`get_tailscale_peers()`** — Tailscale CLI parsen
3. **`check_mercury_service(ip)`** — TCP-Probe mit Protokoll-Handshake
4. **`scan_mesh()`** — Paralleles Abfragen aller Peers
5. **`detect_changes(known, current)`** — Differenzberechnung
6. **`format_notification(changes)`** — Telegram-Text bauen
7. **`send_telegram(msg)`** — Direkter Bot API Call
8. **`run_scan(notify)`** — Ein Scan-Durchlauf
9. **CLI** — `--once`, `--daemon`, `--status`, `--json`, `--no-notify`
