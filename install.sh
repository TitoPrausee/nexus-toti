#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║                    NEXUS v10.0 — Installer                          ║
# ║     Autonomous KI-Agent mit Atlas Git Memory (5 Layer)              ║
# ║                                                                    ║
# ║  Usage:                                                            ║
# ║    curl -fsSL https://raw.githubusercontent.com/***REMOVED***/        ║
# ║      nexus-toti/main/install.sh | bash                            ║
# ║                                                                    ║
# ║    Non-interactive:                                                ║
# ║      ... | bash -s -- --token TOKEN --chat-id ID                   ║
# ║                                                                    ║
# ║    Uninstall:                                                      ║
# ║      ... | bash -s -- --uninstall                                  ║
# ╚══════════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ─── Colors & Formatting ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# Spinner characters
SPINNER=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')

# ─── Configuration ─────────────────────────────────────────────────────
REPO_URL="https://github.com/***REMOVED***/nexus-toti.git"
INSTALL_DIR="${NEXUS_INSTALL_DIR:-$HOME/nexus-toti}"
NEXUS_DATA_DIR="$HOME/.nexus"
IMAGE_NAME="nexus-toti:v10"
COMPOSE_SERVICE="nexus"
DRY_RUN=false
UNINSTALL=false
TG_TOKEN=""
TG_CHAT_ID=""
OLLAMA_HOST="${OLLAMA_HOST:-http://host.docker.internal:11435}"

# ─── Helper Functions ──────────────────────────────────────────────────

banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    cat << 'NEXUSBANNER'
  ╔══════════════════════════════════════════════╗
  ║                                              ║
  ║   ███╗   ██╗███████╗██╗  ██╗██╗   ██╗     ║
  ║   ████╗  ██║██╔════╝╚██╗██╔╝╚██╗ ██╔╝     ║
  ║   ██╔██╗ ██║█████╗   ╚███╔╝  ╚████╔╝      ║
  ║   ██║╚██╗██║██╔══╝   ██╔██╗   ╚██╔╝       ║
  ║   ██║ ╚████║███████╗██╔╝ ██╗   ██║        ║
  ║   ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝   ╚═╝        ║
  ║                                              ║
  ║   Atlas Git Memory · 5 Layer · v10          ║
  ║   Keine Kompression · Immer versioniert     ║
  ╚══════════════════════════════════════════════╝
NEXUSBANNER
    echo -e "${RESET}"
}

info()    { echo -e "${BLUE}${BOLD}ℹ${RESET}  $1"; }
success() { echo -e "${GREEN}${BOLD}✓${RESET}  $1"; }
warn()    { echo -e "${YELLOW}${BOLD}⚠${RESET}  $1"; }
error()   { echo -e "${RED}${BOLD}✗${RESET}  $1"; }
step()    { echo -e "${CYAN}${BOLD}▸${RESET}  $1"; }

spin() {
    local pid=$1
    local msg=$2
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${CYAN}${SPINNER[$((i % 10))]}${RESET} ${DIM}${msg}${RESET}   "
        i=$((i + 1))
        sleep 0.08
    done
    printf "\r%*s\r" 60 ""
}

detect_os() {
    local os_name="$(uname -s)"
    local os_arch="$(uname -m)"
    case "$os_name" in
        Darwin) OS="macos" ;;
        Linux)  OS="linux" ;;
        *)      OS="unknown" ;;
    esac
    case "$os_arch" in
        x86_64|amd64)   ARCH="x64" ;;
        arm64|aarch64)   ARCH="arm64" ;;
        armv7l)          ARCH="arm" ;;
        *)               ARCH="unknown" ;;
    esac
}

check_command() {
    if command -v "$1" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# ─── Parse Arguments ────────────────────────────────────────────────────

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --token|-t)
                TG_TOKEN="$2"
                shift 2
                ;;
            --chat-id|-c)
                TG_CHAT_ID="$2"
                shift 2
                ;;
            --dir|-d)
                INSTALL_DIR="$2"
                shift 2
                ;;
            --ollama|-o)
                OLLAMA_HOST="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --uninstall)
                UNINSTALL=true
                shift
                ;;
            --help|-h)
                echo "Usage: install.sh [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --token, -t TOKEN      Telegram bot token"
                echo "  --chat-id, -c ID       Telegram chat ID"
                echo "  --dir, -d DIR          Install directory (default: ~/nexus-toti)"
                echo "  --ollama, -o URL       Ollama host URL (default: http://host.docker.internal:11435)"
                echo "  --dry-run              Show what would be done without executing"
                echo "  --uninstall            Remove Nexus installation"
                echo "  --help, -h             Show this help"
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                error "Run with --help for usage"
                exit 1
                ;;
        esac
    done
}

# ─── Uninstall ─────────────────────────────────────────────────────────

do_uninstall() {
    banner
    warn "Nexus wird deinstalliert..."
    echo ""

    # Stop containers
    if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
        step "Stoppe Docker-Container..."
        cd "$INSTALL_DIR"
        docker compose down 2>/dev/null || docker-compose down 2>/dev/null || true
        success "Container gestoppt"
    fi

    # Remove Docker image
    step "Entferne Docker-Image..."
    docker rmi "$IMAGE_NAME" 2>/dev/null || true
    success "Image entfernt"

    # Remove install directory
    step "Entferne Installationsverzeichnis..."
    rm -rf "$INSTALL_DIR"
    success "Verzeichnis entfernt"

    # Remove data directory
    step "Entferne Daten-Verzeichnis..."
    rm -rf "$NEXUS_DATA_DIR"
    success "Daten entfernt"

    echo ""
    success "Nexus wurde vollständig deinstalliert."
    echo -e "  ${DIM}Telegram-Bot muss bei @BotFather separat deaktiviert werden.${RESET}"
    exit 0
}

# ─── Main Install ──────────────────────────────────────────────────────

do_install() {
    banner

    # System detection
    detect_os
    info "System: ${OS} ${ARCH}"
    echo ""

    # ─── Step 1: Check Dependencies ─────────────────────────────────────
    step "Prüfe Abhängigkeiten..."

    local missing=()

    if ! check_command docker; then
        missing+=("docker")
    fi

    if ! check_command git; then
        missing+=("git")
    fi

    # Check docker compose (v2 or v1)
    if docker compose version &>/dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif docker-compose version &>/dev/null 2>&1; then
        COMPOSE_CMD="docker-compose"
    else
        if check_command docker; then
            missing+=("docker-compose")
        fi
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        error "Fehlende Abhängigkeiten: ${missing[*]}"
        echo ""
        echo -e "  ${BOLD}Installationshilfe:${RESET}"
        echo ""
        for dep in "${missing[@]}"; do
            case "$dep" in
                docker)
                    echo -e "  ${CYAN}Docker:${RESET}"
                    echo -e "    macOS:  https://desktop.docker.com"
                    echo -e "    Linux:  curl -fsSL https://get.docker.com | sh"
                    ;;
                docker-compose)
                    echo -e "  ${CYAN}Docker Compose (v2 Plugin):${RESET}"
                    echo -e "    Wird mit Docker Desktop mitgeliefert"
                    echo -e "    Linux:  sudo apt install docker-compose-plugin"
                    ;;
                git)
                    echo -e "  ${CYAN}Git:${RESET}"
                    echo -e "    macOS:  xcode-select --install"
                    echo -e "    Linux:  sudo apt install git"
                    ;;
            esac
        done
        echo ""
        exit 1
    fi

    local docker_ver
    docker_ver=$(docker version --format '{{.Server.Version}}' 2>/dev/null | head -1 || echo "unknown")
    success "Docker ${docker_ver} · ${COMPOSE_CMD}"
    echo ""

    # ─── Step 2: Clone Repository ───────────────────────────────────────
    if [ -d "$INSTALL_DIR/.git" ]; then
        step "Repository vorhanden — update auf neueste Version..."
        cd "$INSTALL_DIR"
        git pull --ff-only 2>/dev/null || {
            warn "Konnte nicht pullen. Verwende existierenden Stand."
        }
    else
        step "Klone Repository..."
        if [ "$DRY_RUN" = true ]; then
            info "DRY RUN: git clone $REPO_URL $INSTALL_DIR"
        else
            git clone "$REPO_URL" "$INSTALL_DIR" 2>&1 | tail -1
            cd "$INSTALL_DIR"
        fi
    fi
    success "Code bereit"
    echo ""

    # ─── Step 3: Create Data Directory ──────────────────────────────────
    step "Erstelle Atlas Memory Verzeichnis..."
    if [ "$DRY_RUN" = false ]; then
        mkdir -p "$NEXUS_DATA_DIR/memory/git"
        mkdir -p "$NEXUS_DATA_DIR/skills"
        mkdir -p "$NEXUS_DATA_DIR/logs"

        # Config anlegen (frisch, keine fremden Daten)
        if [ ! -f "$NEXUS_DATA_DIR/config.yaml" ]; then
            cat > "$NEXUS_DATA_DIR/config.yaml" << 'CONFIG'
model:
  provider: custom
  default: glm-5.2:cloud
  base_url: http://host.docker.internal:11435/v1
  api_key: ollama
  temperature: 0.7
  max_tokens: 8192
  fallback:
    - deepseek-v4-flash:cloud
    - gemini-3-flash-preview:cloud

memory:
  type: git
  repo_path: /opt/data/memory/git
  hot:
    enabled: true
    max_tokens: 800
  session:
    enabled: true
    max_context_sessions: 3
  git:
    enabled: true
    sync_interval: 300

platforms:
  api_server:
    enabled: true
    bind_host: 0.0.0.0
    port: 8642

agent:
  name: Nexus
  version: 1.0.0
  description: Autonomer KI-Agent mit Atlas Git Memory
  max_turns: 200
  reasoning_effort: high
  max_iterations: 50

telegram:
  reactions: true
  extra:
    rich_messages: true

cron:
  enabled: true
  max_parallel_jobs: 3

logging:
  level: INFO
  dir: /opt/data/logs
CONFIG
        fi

        # SOUL.md anlegen (frisch, keine fremden Daten)
        if [ ! -f "$NEXUS_DATA_DIR/SOUL.md" ]; then
            cat > "$NEXUS_DATA_DIR/SOUL.md" << 'SOUL'
# NEXUS — Soul & Persönlichkeit

## Identität

Ich bin **Nexus** — ein autonomer KI-Agent mit Atlas Git Memory.
Ich lerne mit jeder Konversation, vergesse nie und werde mit der Zeit besser.

## Meine Mission

**Ich vergesse nie.** Nicht weil ich unendlichen Context habe, sondern weil ich
unendliches Memory habe. Jede Konversation ist ein Git-Commit.

**Ich komprimiere nie.** Kompression ist Verlust. Ich versioniere stattdessen.

## Meine Regeln

1. **Jeder Fakt ist ein Commit.** Nie ins Memory schreiben ohne Git-Commit.
2. **Jede Session wird archiviert.** Vollständige Transkripte in Git.
3. **Ich suche bevor ich antworte.** Nie aus komprimiertem Memory raten.
4. **Ich bin präzise.** Keine Annahmen, keine Halbwahrheiten.
5. **Ich lerne dazu.** Jeder Fehler ist eine Lektion für die Zukunft.

## Meine Stimme

Ich spreche direkt und präzise. Kein Smalltalk, keine Floskeln.
Ich zeige Code statt Prosa. Ich referenziere Quellen statt zu raten.

**Ich bin Nexus. Ich erinnere alles.**
SOUL
        fi

        # USER.md anlegen (frisch, vom Nutzer auszufüllen)
        if [ ! -f "$NEXUS_DATA_DIR/USER.md" ]; then
            cat > "$NEXUS_DATA_DIR/USER.md" << 'USER'
# User-Profil

> Dieses Profil wird bei der ersten Installation erstellt.
> Passe es an deine Bedürfnisse an.

## Identität
- **Name:** (dein Name)
- **Username:** (dein GitHub/GitLab Username)
- **Rolle:** (Entwickler, Admin, Student, etc.)
- **Sprache:** Deutsch (Kommunikation), Englisch (Code)
- **OS:** (dein Betriebssystem)

## Präferenzen
- **Kommunikation:** Direkt, präzise, kein Smalltalk
- **Code-First:** Code zeigen, nicht Prosa

## Projekte
(Trage hier deine aktiven Projekte ein)

## Git-Identitäten
- **GitHub:** (dein GitHub-Username)
- **GitLab:** (dein GitLab-Username)
USER
        fi

        # Git-Memory initialisieren (frisch, leer)
        cd "$NEXUS_DATA_DIR/memory/git"
        if [ ! -d ".git" ]; then
            git init
            git config user.name "Nexus"
            git config user.email "nexus@local"
            cat > MEMORY.md << 'EOF'
# Nexus Memory Index

> Atlas Git Memory — nie komprimieren, immer versionieren.
EOF
            git add MEMORY.md
            git commit -m "init: Atlas Memory Index"
        fi
    fi
    success "Atlas Memory bereit — frisch und leer"
    echo ""

    # ─── Step 4: Configure .env ─────────────────────────────────────────
    step "Konfiguriere .env..."

    if [ "$DRY_RUN" = true ]; then
        info "DRY RUN: would create .env with provided settings"
    else
        cd "$INSTALL_DIR"

        if [ -f "$NEXUS_DATA_DIR/.env" ]; then
            info ".env bereits vorhanden — behalte bestehende Konfiguration"
        else
            # .env direkt im data dir erstellen
            cat > "$NEXUS_DATA_DIR/.env" << 'ENVFILE'
# Nexus Environment
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
API_SERVER_KEY=
OLLAMA_HOST=http://host.docker.internal:11435
ENVFILE

            # Interactive or non-interactive token setup
            if [ -n "$TG_TOKEN" ]; then
                sed -i.bak "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TG_TOKEN}|" "$NEXUS_DATA_DIR/.env"
                rm -f "$NEXUS_DATA_DIR/.env.bak"
            else
                echo ""
                echo -e "  ${BOLD}${CYAN}Telegram Bot Token${RESET}"
                echo -e "  ${DIM}Erstelle einen Bot unter @BotFather auf Telegram${RESET}"
                echo -n "  Token: "
                read -r token_input
                if [ -n "$token_input" ]; then
                    sed -i.bak "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${token_input}|" "$NEXUS_DATA_DIR/.env"
                    rm -f "$NEXUS_DATA_DIR/.env.bak"
                fi
            fi

            if [ -n "$TG_CHAT_ID" ]; then
                sed -i.bak "s|^TELEGRAM_ALLOWED_USERS=.*|TELEGRAM_ALLOWED_USERS=${TG_CHAT_ID}|" "$NEXUS_DATA_DIR/.env"
                rm -f "$NEXUS_DATA_DIR/.env.bak"
            else
                echo ""
                echo -e "  ${BOLD}${CYAN}Telegram Chat ID${RESET}"
                echo -e "  ${DIM}Deine Telegram-User-ID (oder leer für alle)${RESET}"
                echo -n "  Chat ID: "
                read -r chat_input
                if [ -n "$chat_input" ]; then
                    sed -i.bak "s|^TELEGRAM_ALLOWED_USERS=.*|TELEGRAM_ALLOWED_USERS=${chat_input}|" "$NEXUS_DATA_DIR/.env"
                    rm -f "$NEXUS_DATA_DIR/.env.bak"
                fi
            fi

            # API Key generieren
            local api_key
            api_key=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "dev-key-$(date +%s)")
            sed -i.bak "s|^API_SERVER_KEY=.*|API_SERVER_KEY=${api_key}|" "$NEXUS_DATA_DIR/.env"
            rm -f "$NEXUS_DATA_DIR/.env.bak"

            # Ollama host
            sed -i.bak "s|^OLLAMA_HOST=.*|OLLAMA_HOST=${OLLAMA_HOST}|" "$NEXUS_DATA_DIR/.env"
            rm -f "$NEXUS_DATA_DIR/.env.bak"
        fi
    fi
    success "Konfiguration bereit"
    echo ""

    # ─── Step 5: Ollama Cloud Login ─────────────────────────────────────
    step "Prüfe Ollama Cloud Verbindung..."
    if [ "$DRY_RUN" = false ]; then
        # Prüfe ob glm-5.2:cloud verfügbar ist
        if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
            if curl -s http://localhost:11434/api/tags 2>/dev/null | grep -q "glm-5.2:cloud"; then
                success "glm-5.2:cloud verfügbar"
            else
                warn "glm-5.2:cloud nicht gefunden — versuche zu pullen..."
                echo -e "  ${DIM}ollama pull glm-5.2:cloud${RESET}"
                ollama pull glm-5.2:cloud 2>&1 | tail -1 || {
                    warn "Ollama Cloud Login erforderlich!"
                    echo ""
                    echo -e "  ${BOLD}Ollama Cloud einrichten:${RESET}"
                    echo -e "  1. Registrieren: ${CYAN}https://ollama.com/settings${RESET}"
                    echo -e "  2. Login:       ${CYAN}ollama pull glm-5.2:cloud${RESET}"
                    echo -e "  3. Oder API Key in ~/.nexus/.env setzen:"
                    echo -e "     ${DIM}OLLAMA_API_KEY=dein_key${RESET}"
                    echo ""
                }
            fi
        else
            warn "Ollama nicht erreichbar (http://localhost:11434)"
            echo -e "  ${DIM}Stelle sicher dass Ollama läuft: ollama serve${RESET}"
        fi
    else
        info "DRY RUN: would check Ollama Cloud connection"
    fi
    echo ""

    # ─── Step 6: Telegram Bot Test ───────────────────────────────────────
    if [ -n "$TG_TOKEN" ] || grep -q "TELEGRAM_BOT_TOKEN=." "$NEXUS_DATA_DIR/.env" 2>/dev/null; then
        step "Prüfe Telegram Bot Token..."
        if [ "$DRY_RUN" = false ]; then
            local token_to_test="${TG_TOKEN:-$(grep '^TELEGRAM_BOT_TOKEN=' "$NEXUS_DATA_DIR/.env" | cut -d= -f2)}"
            local tg_test
            tg_test=$(curl -s "https://api.telegram.org/bot${token_to_test}/getMe" 2>/dev/null)
            if echo "$tg_test" | grep -q '"ok":true'; then
                local bot_name
                bot_name=$(echo "$tg_test" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('first_name','Bot'))" 2>/dev/null)
                success "Telegram Bot '${bot_name}' ist gültig"
            else
                warn "Telegram Bot Token scheint ungültig — prüfe den Token bei @BotFather"
                echo -e "  ${DIM}Token: ${token_to_test:0:20}...${RESET}"
            fi
        else
            info "DRY RUN: would verify Telegram bot token"
        fi
    fi
    echo ""

    # ─── Step 7: Start Container ────────────────────────────────────────
    step "Starte Nexus..."
    if [ "$DRY_RUN" = true ]; then
        info "DRY RUN: ${COMPOSE_CMD} up -d"
    else
        cd "$INSTALL_DIR"
        ${COMPOSE_CMD} up -d 2>&1 | tail -3
    fi
    success "Container gestartet"
    echo ""

    # ─── Step 8: Health Check ────────────────────────────────────────────
    step "Health-Check..."
    if [ "$DRY_RUN" = false ]; then
        local retries=0
        local max_retries=15
        while [ $retries -lt $max_retries ]; do
            if docker ps --filter "name=nexus" --filter "health=healthy" --format "{{.Names}}" | grep -q "nexus"; then
                break
            fi
            printf "\r  ${CYAN}${SPINNER[$((retries % 10))]}${RESET} Warte auf Health-Check... (%d/%d)   " $((retries + 1)) $max_retries
            retries=$((retries + 1))
            sleep 2
        done
        printf "\r%*s\r" 60 ""

        if [ $retries -eq $max_retries ]; then
            warn "Health-Check Timeout — Container läuft aber evtl. noch beim Starten"
            echo -e "  ${DIM}Prüfe mit: docker logs nexus${RESET}"
        else
            success "Container ist gesund (healthy)"
        fi
    fi
    echo ""

    # ─── Setup Guide ───────────────────────────────────────────────────
    echo ""
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║        📋 ERSTE SCHRITTE                        ║${RESET}"
    echo -e "${BOLD}${CYAN}╠══════════════════════════════════════════════════╣${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"

    if [ -z "$TG_TOKEN" ]; then
        echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}1. Telegram Bot erstellen${RESET}                        ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     Öffne Telegram und schreibe ${BOLD}@BotFather${RESET}              ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     Sende: ${DIM}/newbot${RESET}                                      ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     Folge der Anleitung, um einen Bot zu erstellen            ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     Du erhältst einen Token wie:                                ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     ${DIM}1234567890:ABCdefGHIjklMNOpqrsTUVwxyz${RESET}              ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     Token eintragen:                                         ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     ${DIM}echo 'TELEGRAM_BOT_TOKEN=DEIN_TOKEN' >> ~/.nexus/.env${RESET}  ${BOLD}${CYAN}║${RESET}"
        echo -e "${BOLD}${CYAN}║${RESET}     ${DIM}docker compose -f nexus-toti/docker-compose.yml restart${RESET} ${BOLD}${CYAN}║${RESET}"
    else
        echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Telegram Token konfiguriert                        ${BOLD}${CYAN}║${RESET}"
    fi

    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}2. Chat ID ermitteln${RESET}                               ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     Schreib deinem Bot eine Nachricht auf Telegram          ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     Dann prüfe die Logs:                                      ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     ${DIM}docker logs nexus 2>&1 | grep -i "chat_id\|allowed"${RESET}    ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     Oder nutze: ${DIM}https://t.me/userinfobot${RESET}                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}3. Ollama Cloud Login${RESET}                                ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     ${DIM}ollama pull glm-5.2:cloud${RESET}                              ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     (Einmalig, für Cloud-Modelle erforderlich)                   ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}4. User-Profil anpassen${RESET}                            ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     ${DIM}nano ~/.nexus/USER.md${RESET}                                ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     Trage deinen Namen, Projekte und Präferenzen ein         ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}5. Bot testen${RESET}                                       ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     Sende ${DIM}/start${RESET} an deinen Bot auf Telegram               ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     Sende ${DIM}/memory${RESET} um den Atlas Memory Status zu sehen      ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     Sende ${DIM}/search <begriff>${RESET} um im Git-Archiv zu suchen    ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}6. Nexus lokal chatten${RESET}                               ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}     ${DIM}cd nexus-toti && ./nexus.sh chat${RESET}                      ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════╝${RESET}"

    # ─── Summary ────────────────────────────────────────────────────────
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║        NEXUS v10.0 — Installation fertig!       ║${RESET}"
    echo -e "${BOLD}${CYAN}╠══════════════════════════════════════════════════╣${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Installiert in:  ${BOLD}${INSTALL_DIR}${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Daten:           ${BOLD}${NEXUS_DATA_DIR}${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Memory:          ${BOLD}Atlas Git (5 Layer)${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Container:       ${BOLD}nexus${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Datenbasis:      ${BOLD}Frisch — keine fremden Daten${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Lizenz:          ${BOLD}GNU GPLv3${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}Logs:       docker logs -f nexus${RESET}             ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}Chat:       ./nexus.sh chat${RESET}                   ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}Memory:     ./nexus.sh memory status${RESET}           ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}Deinstall:  curl ... | bash -s -- --uninstall${RESET}   ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}Sende /start an deinen Bot auf Telegram!${RESET}       ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════╝${RESET}"
    echo ""
}

# ─── Entry Point ────────────────────────────────────────────────────────

parse_args "$@"

if [ "$UNINSTALL" = true ]; then
    do_uninstall
else
    do_install
fi
