#!/bin/bash
# Mercury Archive Builder — speichert alle Agenten-Versionen in OrbStack Volume
# Archiviert: Mercury v1, Mercury v2, Hermes, Nova, Atlas
# Nutzung: sudo ./archive_mercury.sh

set -e

VOLUME="mercury-archive"
MOUNT="/mnt/archive"
DATE=$(date +%Y-%m-%d)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[ARCHIV]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }

# Prüfe ob Volume existiert
if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    err "Volume $VOLUME existiert nicht. Bitte zuerst: docker volume create $VOLUME"
    exit 1
fi

info "Starte Mercury-Archivierung in Volume '$VOLUME'..."
echo ""

# Temporären Container starten
CONTAINER_ID=$(docker run -d --rm \
    -v ${VOLUME}:/archive \
    alpine:latest \
    sleep 3600 2>&1)
ok "Temporärer Container gestartet: ${CONTAINER_ID:0:12}"

cleanup() {
    docker kill "$CONTAINER_ID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Verzeichnisstruktur anlegen
docker exec "$CONTAINER_ID" mkdir -p /archive/mercury-v1/{config,memory,skills,sessions,projects,home}
docker exec "$CONTAINER_ID" mkdir -p /archive/mercury-v2/{config,memory,skills,sessions,projects,home}
docker exec "$CONTAINER_ID" mkdir -p /archive/hermes/{config,memory,skills,sessions,projects}
docker exec "$CONTAINER_ID" mkdir -p /archive/nova/{config,memory,skills,sessions,projects}
docker exec "$CONTAINER_ID" mkdir -p /archive/atlas/{config,memory,skills}
docker exec "$CONTAINER_ID" mkdir -p /archive/docs

# ─── Mercury v1 ─────────────────────────────────────────────

info "Archiviere Mercury v1..."

# Config
[ -f ~/.mercury/config.yaml ] && \
    docker cp ~/.mercury/config.yaml "$CONTAINER_ID":/archive/mercury-v1/config/ 2>/dev/null && \
    ok "  config.yaml" || warn "  config.yaml fehlt"

[ -f ~/.mercury/SOUL.md ] && \
    docker cp ~/.mercury/SOUL.md "$CONTAINER_ID":/archive/mercury-v1/config/ 2>/dev/null && \
    ok "  SOUL.md" || warn "  SOUL.md fehlt"

[ -f ~/.mercury/USER.md ] && \
    docker cp ~/.mercury/USER.md "$CONTAINER_ID":/archive/mercury-v1/config/ 2>/dev/null && \
    ok "  USER.md" || warn "  USER.md fehlt"

[ -f ~/.mercury/MEMORY.md ] && \
    docker cp ~/.mercury/MEMORY.md "$CONTAINER_ID":/archive/mercury-v1/config/ 2>/dev/null && \
    ok "  MEMORY.md" || warn "  MEMORY.md fehlt"

# Memory
[ -d ~/.mercury/memories ] && \
    docker cp ~/.mercury/memories "$CONTAINER_ID":/archive/mercury-v1/memory/ 2>/dev/null && \
    ok "  memories/" || warn "  memories/ fehlt"

# Skills (ohne .git)
[ -d ~/.mercury/skills ] && \
    docker cp ~/.mercury/skills "$CONTAINER_ID":/archive/mercury-v1/skills/ 2>/dev/null && \
    ok "  skills/" || warn "  skills/ fehlt"

# Sessions (nicht-komprimierte)
[ -d ~/.mercury/sessions ] && \
    docker cp ~/.mercury/sessions "$CONTAINER_ID":/archive/mercury-v1/sessions/ 2>/dev/null && \
    ok "  sessions/" || warn "  sessions/ fehlt"

# Projekte
[ -d ~/.mercury/projects ] && \
    docker cp ~/.mercury/projects "$CONTAINER_ID":/archive/mercury-v1/projects/ 2>/dev/null && \
    ok "  projects/" || warn "  projects/ fehlt"

# Home (nur Configs + Scripts, keine Downloads/Cache)
[ -d ~/.mercury/home ] && \
    docker exec "$CONTAINER_ID" mkdir -p /archive/mercury-v1/home && \
    for dir in bin scripts .gitconfig .bashrc .ssh config; do
        [ -e ~/.mercury/home/$dir ] && \
            docker cp ~/.mercury/home/$dir "$CONTAINER_ID":/archive/mercury-v1/home/ 2>/dev/null && \
            ok "  home/$dir" || true
    done

# Mercury-Remote
[ -d ~/.mercury/home/mercury-remote ] && \
    docker cp ~/.mercury/home/mercury-remote "$CONTAINER_ID":/archive/mercury-v1/ 2>/dev/null && \
    ok "  mercury-remote/" || warn "  mercury-remote/ fehlt"

# ─── Mercury v2 ─────────────────────────────────────────────

info "Archiviere Mercury v2..."

[ -f ~/.mercury-v2/config.yaml ] && \
    docker cp ~/.mercury-v2/config.yaml "$CONTAINER_ID":/archive/mercury-v2/config/ 2>/dev/null && \
    ok "  config.yaml" || warn "  config.yaml fehlt"

[ -f ~/.mercury-v2/SOUL.md ] && \
    docker cp ~/.mercury-v2/SOUL.md "$CONTAINER_ID":/archive/mercury-v2/config/ 2>/dev/null && \
    ok "  SOUL.md" || warn "  SOUL.md fehlt"

[ -f ~/.mercury-v2/USER.md ] && \
    docker cp ~/.mercury-v2/USER.md "$CONTAINER_ID":/archive/mercury-v2/config/ 2>/dev/null && \
    ok "  USER.md" || warn "  USER.md fehlt"

[ -f ~/.mercury-v2/MEMORY.md ] && \
    docker cp ~/.mercury-v2/MEMORY.md "$CONTAINER_ID":/archive/mercury-v2/config/ 2>/dev/null && \
    ok "  MEMORY.md" || warn "  MEMORY.md fehlt"

[ -d ~/.mercury-v2/memories ] && \
    docker cp ~/.mercury-v2/memories "$CONTAINER_ID":/archive/mercury-v2/memory/ 2>/dev/null && \
    ok "  memories/" || warn "  memories/ fehlt"

[ -d ~/.mercury-v2/skills ] && \
    docker cp ~/.mercury-v2/skills "$CONTAINER_ID":/archive/mercury-v2/skills/ 2>/dev/null && \
    ok "  skills/" || warn "  skills/ fehlt"

[ -d ~/.mercury-v2/sessions ] && \
    docker cp ~/.mercury-v2/sessions "$CONTAINER_ID":/archive/mercury-v2/sessions/ 2>/dev/null && \
    ok "  sessions/" || warn "  sessions/ fehlt"

[ -d ~/.mercury-v2/projects ] && \
    docker cp ~/.mercury-v2/projects "$CONTAINER_ID":/archive/mercury-v2/projects/ 2>/dev/null && \
    ok "  projects/" || warn "  projects/ fehlt"

# ─── Hermes ─────────────────────────────────────────────────

info "Archiviere Hermes..."

[ -f ~/.hermes/config.yaml ] && \
    docker cp ~/.hermes/config.yaml "$CONTAINER_ID":/archive/hermes/config/ 2>/dev/null && \
    ok "  config.yaml" || warn "  config.yaml fehlt"

[ -f ~/.hermes/SOUL.md ] && \
    docker cp ~/.hermes/SOUL.md "$CONTAINER_ID":/archive/hermes/config/ 2>/dev/null && \
    ok "  SOUL.md" || warn "  SOUL.md fehlt"

[ -f ~/.hermes/USER.md ] && \
    docker cp ~/.hermes/USER.md "$CONTAINER_ID":/archive/hermes/config/ 2>/dev/null && \
    ok "  USER.md" || warn "  USER.md fehlt"

[ -f ~/.hermes/MEMORY.md ] && \
    docker cp ~/.hermes/MEMORY.md "$CONTAINER_ID":/archive/hermes/config/ 2>/dev/null && \
    ok "  MEMORY.md" || warn "  MEMORY.md fehlt"

[ -f ~/.hermes/.env ] && \
    docker cp ~/.hermes/.env "$CONTAINER_ID":/archive/hermes/config/ 2>/dev/null && \
    ok "  .env" || warn "  .env fehlt"

[ -d ~/.hermes/memories ] && \
    docker cp ~/.hermes/memories "$CONTAINER_ID":/archive/hermes/memory/ 2>/dev/null && \
    ok "  memories/" || warn "  memories/ fehlt"

[ -d ~/.hermes/skills ] && \
    docker cp ~/.hermes/skills "$CONTAINER_ID":/archive/hermes/skills/ 2>/dev/null && \
    ok "  skills/" || warn "  skills/ fehlt"

[ -d ~/.hermes/sessions ] && \
    docker cp ~/.hermes/sessions "$CONTAINER_ID":/archive/hermes/sessions/ 2>/dev/null && \
    ok "  sessions/" || warn "  sessions/ fehlt"

[ -d ~/.hermes/.tools ] && \
    docker cp ~/.hermes/.tools "$CONTAINER_ID":/archive/hermes/ 2>/dev/null && \
    ok "  .tools/" || warn "  .tools/ fehlt"

# ─── Nova ───────────────────────────────────────────────────

info "Archiviere Nova..."

[ -f ~/.nova/config.yaml ] && \
    docker cp ~/.nova/config.yaml "$CONTAINER_ID":/archive/nova/config/ 2>/dev/null && \
    ok "  config.yaml" || warn "  config.yaml fehlt"

[ -f ~/.nova/SOUL.md ] && \
    docker cp ~/.nova/SOUL.md "$CONTAINER_ID":/archive/nova/config/ 2>/dev/null && \
    ok "  SOUL.md" || warn "  SOUL.md fehlt"

[ -f ~/.nova/USER.md ] && \
    docker cp ~/.nova/USER.md "$CONTAINER_ID":/archive/nova/config/ 2>/dev/null && \
    ok "  USER.md" || warn "  USER.md fehlt"

[ -f ~/.nova/MEMORY.md ] && \
    docker cp ~/.nova/MEMORY.md "$CONTAINER_ID":/archive/nova/config/ 2>/dev/null && \
    ok "  MEMORY.md" || warn "  MEMORY.md fehlt"

[ -d ~/.nova/memories ] && \
    docker cp ~/.nova/memories "$CONTAINER_ID":/archive/nova/memory/ 2>/dev/null && \
    ok "  memories/" || warn "  memories/ fehlt"

[ -d ~/.nova/skills ] && \
    docker cp ~/.nova/skills "$CONTAINER_ID":/archive/nova/skills/ 2>/dev/null && \
    ok "  skills/" || warn "  skills/ fehlt"

[ -d ~/.nova/sessions ] && \
    docker cp ~/.nova/sessions "$CONTAINER_ID":/archive/nova/sessions/ 2>/dev/null && \
    ok "  sessions/" || warn "  sessions/ fehlt"

[ -d ~/.nova/projects ] && \
    docker cp ~/.nova/projects "$CONTAINER_ID":/archive/nova/projects/ 2>/dev/null && \
    ok "  projects/" || warn "  projects/ fehlt"

# ─── Atlas ──────────────────────────────────────────────────

info "Archiviere Atlas..."

[ -f ~/.atlas/config.yaml ] && \
    docker cp ~/.atlas/config.yaml "$CONTAINER_ID":/archive/atlas/config/ 2>/dev/null && \
    ok "  config.yaml" || warn "  config.yaml fehlt"

[ -f ~/.atlas/SOUL.md ] && \
    docker cp ~/.atlas/SOUL.md "$CONTAINER_ID":/archive/atlas/config/ 2>/dev/null && \
    ok "  SOUL.md" || warn "  SOUL.md fehlt"

[ -f ~/.atlas/USER.md ] && \
    docker cp ~/.atlas/USER.md "$CONTAINER_ID":/archive/atlas/config/ 2>/dev/null && \
    ok "  USER.md" || warn "  USER.md fehlt"

# Git-Memory (komplett mit .git)
[ -d ~/.atlas/memory ] && \
    docker cp ~/.atlas/memory "$CONTAINER_ID":/archive/atlas/memory/ 2>/dev/null && \
    ok "  memory/ (mit Git-History)" || warn "  memory/ fehlt"

# Skills
[ -d ~/.atlas/skills ] && \
    docker cp ~/.atlas/skills "$CONTAINER_ID":/archive/atlas/skills/ 2>/dev/null && \
    ok "  skills/" || warn "  skills/ fehlt"

# Scripts
for script in git_memory.py hot_memory.py session_manager.py context_loader.py memory_orchestrator.py migrate.py consolidate_skills.py; do
    [ -f ~/.atlas/$script ] && \
        docker cp ~/.atlas/$script "$CONTAINER_ID":/archive/atlas/ 2>/dev/null && \
        ok "  $script" || true
done

# ─── Dokumentation ──────────────────────────────────────────

info "Erstelle README..."

docker exec "$CONTAINER_ID" sh -c "cat > /archive/docs/README.md << 'EOF'
# Mercury Agenten-Archiv

> Erstellt am: $DATE
> Volume: mercury-archive
> Enthält: Mercury v1, Mercury v2, Hermes, Nova, Atlas

## Struktur

\`\`\`
/archive/
├── mercury-v1/          # Original Mercury (91GB, gestoppt)
│   ├── config/          # config.yaml, SOUL.md, USER.md, MEMORY.md
│   ├── memory/          # memories/
│   ├── skills/          # skills/
│   ├── sessions/        # sessions/
│   ├── projects/        # projects/
│   ├── home/            # .gitconfig, .bashrc, .ssh, scripts
│   └── mercury-remote/  # P2P Mesh Terminal
│
├── mercury-v2/          # Aktuelles Mercury (893MB, Port 8650)
│   ├── config/
│   ├── memory/
│   ├── skills/
│   ├── sessions/
│   └── projects/
│
├── hermes/              # Hermes/Toti (9.2GB, Port 8642)
│   ├── config/
│   ├── memory/
│   ├── skills/
│   ├── sessions/
│   └── .tools/
│
├── nova/                # Nova (1.5GB, Port 8660)
│   ├── config/
│   ├── memory/
│   ├── skills/
│   ├── sessions/
│   └── projects/
│
├── atlas/               # Atlas (42MB, Port 8670)
│   ├── config/
│   ├── memory/          # Git-basiert, versioniert
│   ├── skills/          # Konsolidiert aus allen Agenten
│   └── *.py             # Memory Engine Scripts
│
└── docs/
    └── README.md        # Diese Datei
\`\`\`

## Wiederherstellung

Um einen Agenten wiederherzustellen:
\`\`\`bash
# Container starten mit Volume
docker run -it --rm -v mercury-archive:/archive alpine:latest

# Daten kopieren
cp -r /archive/mercury-v1/config/* ~/.mercury/
\`\`\`

## Versionen

| Agent | Modell | Port | Status |
|-------|--------|------|--------|
| Mercury v1 | glm-5.1:cloud | 9443 | ❌ Gestoppt |
| Mercury v2 | glm-5.1:cloud | 8650 | ✅ Aktiv |
| Hermes/Toti | qwen3.5:cloud | 8642 | ✅ Aktiv |
| Nova | gemini-3-flash-preview:cloud | 8660 | ✅ Aktiv |
| Atlas | glm-5.2:cloud | 8670 | ✅ Aktiv |
EOF
" && ok "  README.md"

# ─── Zusammenfassung ────────────────────────────────────────

echo ""
info "Berechne Archiv-Größe..."
docker exec "$CONTAINER_ID" du -sh /archive 2>/dev/null

echo ""
info "Erstelle Archiv-Liste..."
docker exec "$CONTAINER_ID" find /archive -type f -not -path '*/\.*' | wc -l | xargs -I{} echo "  {} Dateien archiviert"

echo ""
ok "Archivierung abgeschlossen!"
info "Volume: $VOLUME"
info "Mountpoint: /var/lib/docker/volumes/$VOLUME/_data"
echo ""
info "Zum Durchsuchen:"
echo "  docker run -it --rm -v $VOLUME:/archive alpine:latest ls -la /archive"
