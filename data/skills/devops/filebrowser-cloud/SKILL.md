---
name: filebrowser-cloud
description: Set up FileBrowser as a self-hosted cloud file manager on Tailscale with DOCX/PDF preview
version: 1.0
---

# FileBrowser Cloud Setup

Lightweight self-hosted cloud file manager with upload, download, rename, delete, and file preview. Runs as a single binary — no Docker needed.

## Quick Setup

### 1. Install FileBrowser binary
```bash
curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash
filebrowser version  # verify
```

### 2. Initialize config and database
```bash
mkdir -p /opt/data/cloud-data/filebrowser-db /opt/data/cloud-data/filebrowser
cd /opt/data/cloud-data

filebrowser config init -d filebrowser-db/filebrowser.db
filebrowser config set -d filebrowser-db/filebrowser.db \
  --root /opt/data/cloud-data/filebrowser \
  --address 0.0.0.0 \
  --port 8090 \
  --locale de
```

### 3. Create admin user
```bash
filebrowser users add <username> <password> -d filebrowser-db/filebrowser.db --perm.admin
```

### 4. Start FileBrowser
```bash
nohup filebrowser -d filebrowser-db/filebrowser.db \
  --root /opt/data/cloud-data/filebrowser \
  --address 0.0.0.0 --port 8090 \
  > /opt/data/cloud-data/filebrowser.log 2>&1 &
```

Access via Tailscale: `http://<tailscale-ip>:8090`

### 5. Persist across reboots
```bash
# Create startup script
cat > /opt/data/cloud-data/start-cloud.sh << 'EOF'
#!/bin/bash
DATABASE=/opt/data/cloud-data/filebrowser-db/filebrowser.db
ROOT=/opt/data/cloud-data/filebrowser
/usr/local/bin/filebrowser -d "$DATABASE" --root "$ROOT" --address 0.0.0.0 --port 8090
EOF
chmod +x /opt/data/cloud-data/start-cloud.sh

# If crontab available:
(crontab -l 2>/dev/null; echo "@reboot /opt/data/cloud-data/start-cloud.sh >> /opt/data/cloud-data/filebrowser.log 2>&1") | crontab -

# If no crontab (container environments), add to supervisor/systemd or
# use the Hermes startup hook in config.yaml
```

## DOCX Preview (LibreOffice Headless)

FileBrowser can preview PDFs natively. For DOCX preview, convert to PDF first:

### Install LibreOffice
```bash
sudo apt-get update && sudo apt-get install -y libreoffice-writer --no-install-recommends
```

### Bulk convert DOCX → PDF
```bash
find /path/to/files -name "*.docx" -print0 | while IFS= read -r -d '' f; do
    dir=$(dirname "$f")
    libreoffice --headless --convert-to pdf "$f" --outdir "$dir/" 2>/dev/null
done
```

### Auto-convert script
```bash
cat > /opt/data/cloud-data/convert-docx.sh << 'EOF'
#!/bin/bash
SRC="${1:-.}"
DST="${2:-$SRC}"
mkdir -p "$DST"
find "$SRC" -name "*.docx" -newer "$DST/.last-convert" -print0 2>/dev/null | while IFS= read -r -d '' f; do
    libreoffice --headless --convert-to pdf "$f" --outdir "$DST" 2>/dev/null
done
touch "$DST/.last-convert"
EOF
chmod +x /opt/data/cloud-data/convert-docx.sh
```

## Pitfalls

- **⚠️ FileBrowser v2.63+ BROKEN on mobile Safari (iPhone)** — The SPA uses Vite/rolldown ES modules that cause an infinite loading spinner on iOS Safari. **Fix: Use v2.31.0** which works on all browsers:
  ```bash
  # Download v2.31.0 (Safari-stable, JWT auth fixed)
  wget -q https://github.com/filebrowser/filebrowser/releases/download/v2.31.0/linux-arm64-filebrowser.tar.gz -O /tmp/fb.tar.gz
  cd /tmp && tar xzf fb.tar.gz filebrowser
  # Kill existing process first, then replace binary
  kill $(pgrep filebrowser) 2>/dev/null; sleep 1
  sudo cp -f /tmp/filebrowser /usr/local/bin/filebrowser
  sudo chmod +x /usr/local/bin/filebrowser
  # Re-init DB when upgrading/downgrading (DBs are version-incompatible)
  rm /opt/data/cloud-data/filebrowser-db/filebrowser.db
  filebrowser config init -d /opt/data/cloud-data/filebrowser-db/filebrowser.db
  filebrowser config set -d /opt/data/cloud-data/filebrowser-db/filebrowser.db --root /opt/data/cloud-data/filebrowser --address 127.0.0.1 --port 8091
  filebrowser users add tito <password> --perm.admin --scope / -d /opt/data/cloud-data/filebrowser-db/filebrowser.db
  ```
- **⚠️ FileBrowser v2.27 JWT auth bug** — v2.27 returns a JWT token from `/api/login` but ALL subsequent API calls return 401 Unauthorized regardless of header format (`Authorization: Bearer` or `X-Auth`). This makes the FileBrowser web UI completely unusable after login. **Fix: Upgrade to v2.31.0** which fixes JWT validation.
- **XLSX needs libreoffice-calc** not just `-writer`. Install: `sudo apt-get install -y libreoffice-calc --no-install-recommends`. Without calc, `--convert-to pdf` on XLSX fails with "source file could not be loaded".
- **Pandoc MD→PDF needs LaTeX** for German text. Install texlive or fall back to `libreoffice --headless --convert-to pdf` for MD files.
- **Docker socket not available** in Hermes container environment. Use binary install instead of Docker Compose.
- **No crontab** in some containers. Use startup scripts or supervisor configs.
- **LibreOffice javaldx warning** is harmless — PDF conversion still works.
- **Port 8090** must be free. Check with `ss -tlnp | grep 8090`.
- **ARM64/aarch64**: FileBrowser get.sh auto-detects architecture. LibreOffice also available for aarch64.
- **FileBrowser config flags** vary by version. `--perm.move` doesn't exist in v2.63 — use `--perm.admin` for full access.
- **DOCX/XLSX preview is IMPOSSIBLE in FileBrowser** — it only renders PDF, images, audio, video. Don't try to make DOCX preview work; instead put only PDFs at the top level of each directory and move source files to `quellformat/` subfolder. This is the only reliable solution.
- **⚠️ Multi-Port auf iPhone geht NICHT** — iPhone Safari over Tailscale kann nicht zuverlässig 3 separate Ports (8090/8091/8092) erreichen. Manche Ports laden endlos, andere zeigen "Connection refused". **Lösung**: Alle Services auf EINEM Port (8090) via Flask-Proxy laufen lassen. FileBrowser intern auf Port 8095, Flask proxyt `/files/` dorthin.
- **Flask-Proxy für FileBrowser** — FileBrowser braucht WebSocket-Upgrade für Echtzeit-Updates. Flask muss den `Upgrade`-Header weiterleiten. Ohne Proxy-Unterstützung funktioniert FileBrowser im Browser (Dateien bleiben scheinbar hängen, Upload-Progress fehlt).
- **Tailscale**: Service must listen on `0.0.0.0` (not just localhost) to be reachable via Tailscale IP.
- **DB incompatibility**: v2.63 DB cannot be used with v2.27. Must re-init DB when downgrading.
- **Password reset via CLI times out if FileBrowser is running** — `filebrowser users update <user> --password <new> -d <db>` returns "timeout" when the FileBrowser process is already using the DB. **Fix: Kill the running process first** (`kill <pid>`), then run the CLI command, then restart FileBrowser. If the password still doesn't work after reset, the DB may be corrupted — reinitialize with `rm <db> && filebrowser config init -d <db>` and recreate the user.
- **FileBrowser v2.27 JWT auth bug** — v2.27 returns a valid JWT from `/api/login` but all subsequent authenticated requests return 401. Neither `Authorization: Bearer` nor `X-Auth` headers work. This is a v2.27-specific bug. **Fix: Upgrade to v2.31.0** and reinitialize the database (DBs are version-incompatible).
- **Upgrade process v2.27 → v2.31.0**: (1) Kill all filebrowser processes (`kill $(pgrep filebrowser)`), (2) `sudo cp -f /tmp/filebrowser /usr/local/bin/filebrowser` (the running binary can't be overwritten — must kill first), (3) `rm` old DB and reinit (`filebrowser config init`, `filebrowser config set`, `filebrowser users add`), (4) restart filebrowser on internal port. The `--perm.admin` flag grants all permissions. DBs are version-incompatible — always reinit when upgrading.
- **X-Auth header, not Authorization: Bearer** — v2.31.0 uses `X-Auth: <token>` for authenticated API requests, NOT `Authorization: Bearer <token>`. When proxying through Flask, forward the `X-Auth` header. Login returns a plain JWT string (no JSON wrapper) which must be used as the `X-Auth` header value in subsequent requests. Verified with: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8091/api/resources/ -H "X-Auth: $TOKEN"` → 200 (while `Authorization: Bearer` → 401).
  ```python
  for header in ["Authorization", "X-Auth", "Content-Type", "Cookie", "Accept", "Origin", "Referer"]:
      if header in self.headers:
          req.add_header(header, self.headers[header])
  ```
- **SQLite3 not installed by default** — `apt-get install sqlite3` needed if you want to inspect the DB directly. Requires `sudo` in Hermes container.

## Directory Structure Pattern (quellformat/)

FileBrowser cannot preview DOCX/XLSX/MD files — it shows "Für diese Datei ist keine Vorschau verfügbar". The cleanest solution is a **two-tier directory structure** where only PDFs appear at the top level, and source files live in a `quellformat/` subdirectory:

```
TitoCloud/
├── README.pdf                    ← Vorschau (clickable)
├── fsu-connect-docs/
│   ├── 04_analysen/
│   │   ├── bewertung-entscheidung.pdf   ← Previewable
│   │   ├── cms-systemvergleich.pdf      ← Previewable
│   │   └── quellformat/                 ← Download-only originals
│   │       ├── bewertung-entscheidung.docx
│   │       ├── bewertung-entscheidung.md
│   │       └── cms-systemvergleich.docx
│   └── uploads/
└── uploads/                      ← User uploads
```

**Why this works**: Users see only PDFs at the top level — every file they click opens in the browser. Source files (DOCX, XLSX, MD) are one click away in `quellformat/` for downloading/editing. No confusion about "preview not available".

**Bulk restructuring command**:
```bash
cd /opt/data/cloud-data/filebrowser/fsu-connect-docs
for dir in $(find . -mindepth 1 -maxdepth 1 -type d); do
    mkdir -p "$dir/quellformat"
    # Move non-PDF source files to quellformat (keep PDFs and subdirs at top)
    find "$dir" -maxdepth 1 -type f \( -name "*.docx" -o -name "*.xlsx" -o -name "*.md" -o -name "*.xls" \) \
        -exec mv {} "$dir/quellformat/" \;
done
```

## Video Streaming (`/video/`)

Flask app at `/opt/data/cloud-data/web/titocloud.py` serves HLS video streaming on the same port (8090).

- Upload videos (MP4/MKV/MOV/WebM) via drag & drop or file picker
- Videos auto-convert to HLS via ffmpeg for adaptive streaming
- iPhone Safari compatible (native HLS support)
- Video storage: `/opt/data/cloud-data/videos/uploads/`
- HLS segments: `/opt/data/cloud-data/videos/hls/`
- HTML5 player with fullscreen overlay

### ffmpeg HLS conversion
```bash
ffmpeg -y -i input.mp4 \
  -c:v libx264 -c:a aac \
  -hls_time 10 -hls_list_size 0 \
  -f hls output/stream.m3u8
```

## Aufgabenverwaltung (`/tasks/`)

Same Flask app, task management with Arbeit/Privat tabs on the same port (8090).

- Data stored in `/opt/data/cloud-data/tasks.json`
- Priorities: low, medium, high, urgent (color-coded)
- Due dates with overdue/today badges
- Tags for categorization (e.g. "fsu", "homelab")
- Daily Telegram reminder at 08:00 via cronjob `aufgaben-reminder`
- API: GET/POST/PATCH/DELETE `/api/tasks`

### Pre-seeded tasks
- Arbeit: 5 FSU Connect tasks (BITV 2.0, FSU CI, Zugänge, Jour fixe, Meilisearch)
- Privat: 3 tasks (Mac Mini, Tailscale docs, iSH SSH)

## TitoCloud Stack Overview — All-in-One auf Port 8090

**WICHTIG**: Alle Services laufen auf **einem Port** (8090) über einen Flask-Proxy. iPhone Safari konnte mehrere Ports nicht erreichen — daher Konsolidierung.

| Path | Service | Tech | Purpose |
|------|---------|------|---------|
| `/` | Portal | Flask + HTML | Startseite mit Navigation |
| `/files/` | FileBrowser | Binary v2.27 (proxy) | Files, PDF preview, upload/download |
| `/video/` | Video | Flask + ffmpeg | Video upload, HLS streaming |
| `/tasks/` | Aufgaben | Flask + JSON | Task management, Arbeit/Privat |
| `/api/tasks` | Task API | Flask JSON | CRUD API für Aufgaben |

Start all: `/opt/data/cloud-data/start-cloud.sh`
Convert DOCX→PDF: `/opt/data/cloud-data/convert-all.sh`

### Warum All-in-One statt separate Ports?

iPhone Safari/Tailscale hatte Probleme, mehrere Ports gleichzeitig zu erreichen. 8090/8091/8092 waren nicht alle erreichbar — Lösung: Flask-Proxy auf 8090, der FileBrowser auf internem Port 8095 weiterleitet und Video/Tasks direkt bedient.

### Flask Proxy Architektur

```
iPhone → Tailscale:8090 → Flask (titocloud.py)
                                ├── /         → portal.html
                                ├── /files/*  → Proxy zu FileBrowser (localhost:8091)
                                ├── /video/   → video.html
                                ├── /tasks/   → tasks.html
                                └── /api/*    → JSON API (tasks.json) + proxy to FileBrowser
```

- FileBrowser läuft intern auf Port 8091 (nicht direkt erreichbar)
- Flask proxy leitet `/files/` und `/api/*` Requests an FileBrowser weiter
- **WICHTIG**: FileBrowser nutzt `X-Auth` Header (nicht `Authorization: Bearer`) für JWT-Tokens. Der Flask-Proxy MUSS `X-Auth` weiterleiten:
  ```python
  # In _proxy_fb() — forward all relevant headers including X-Auth:
  for header in ["Authorization", "X-Auth", "Content-Type", "Cookie", "Accept", "Origin", "Referer"]:
      if header in self.headers:
          req.add_header(header, self.headers[header])
  ```
  Ohne `X-Auth`-Weiterleitung gibt FileBrowser nach dem Login 401 Unauthorized zurück — die eingeloggte Session ist unbrauchbar.

## Current Deployment

- **Single URL**: `http://<PRIVATE_IP>:8090` — alle Services hinter einem Port
- FileBrowser data: `/opt/data/cloud-data/filebrowser/`
- FileBrowser DB: `/opt/data/cloud-data/filebrowser-db/filebrowser.db`
- Binary: `/usr/local/bin/filebrowser` — **v2.31.0** (upgraded from v2.27 which had JWT auth bug, v2.63+ broken on Safari)
- LibreOffice: `/usr/bin/libreoffice` (v25.2, writer + calc)
- Video data: `/opt/data/cloud-data/videos/`
- Tasks data: `/opt/data/cloud-data/tasks.json`
- Flask app: `/opt/data/cloud-data/web/titocloud.py`
- Portal/Video/Tasks UI: `/opt/data/cloud-data/web/portal.html`, `video.html`, `tasks.html`
- Login: `tito` / `prause2026fsu`
- Cronjob `aufgaben-reminder`: täglich 08:00 Telegram