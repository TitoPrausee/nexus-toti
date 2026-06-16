#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║                    NEXUS v9 — Installer                            ║
# ║     Autonomous KI-Agent mit Seele und 156 Skills                  ║
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
IMAGE_NAME="nexus-toti:v9"
COMPOSE_SERVICE="nexus-telegram"
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
  ║     ███╗   ██╗███████╗██╗  ██╗██╗   ██╗    ║
  ║     ████╗  ██║██╔════╝██║  ██║╚██╗ ██╔╝    ║
  ║     ██╔██╗ ██║█████╗  ███████║ ╚████╔╝     ║
  ║     ██║╚██╗██║██╔══╝  ██╔══██║  ╚██╔╝      ║
  ║     ██║ ╚████║███████╗██║  ██║   ██║       ║
  ║     ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝   ╚═╝       ║
  ║                                              ║
  ║   Autonomous KI-Agent · 156 Skills · v9     ║
  ║   Seele · 6-Agenten-Team · DSGVO            ║
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

version_check() {
    # Returns 0 if $1 >= $2 (semantic version, major.minor)
    local v1_major v1_minor v2_major v2_minor
    v1_major=$(echo "$1" | cut -d. -f1)
    v1_minor=$(echo "$1" | cut -d. -f2)
    v2_major=$(echo "$2" | cut -d. -f1)
    v2_minor=$(echo "$2" | cut -d. -f2)
    [ "$v1_major" -gt "$v2_major" ] && return 0
    [ "$v1_major" -eq "$v2_major" ] && [ "$v1_minor" -ge "$v2_minor" ] && return 0
    return 1
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

    # Remove Docker volumes
    step "Entferne Docker-Volumes..."
    docker volume rm nexus_data nexus_soul 2>/dev/null || true
    success "Volumes entfernt"

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
        # docker exists but compose doesn't
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

    # ─── Step 3: Configure .env ─────────────────────────────────────────
    step "Konfiguriere .env..."

    if [ "$DRY_RUN" = true ]; then
        info "DRY RUN: would create .env with provided settings"
    else
        cd "$INSTALL_DIR"

        if [ -f .env ]; then
            info ".env bereits vorhanden — behalte bestehende Konfiguration"
        else
            cp .env.example .env

            # Interactive or non-interactive token setup
            if [ -n "$TG_TOKEN" ]; then
                sed -i.bak "s|^NEXUS_TG_TOKEN=.*|NEXUS_TG_TOKEN=${TG_TOKEN}|" .env
                rm -f .env.bak
            else
                echo ""
                echo -e "  ${BOLD}${CYAN}Telegram Bot Token${RESET}"
                echo -e "  ${DIM}Erstelle einen Bot unter @BotFather auf Telegram${RESET}"
                echo -n "  Token: "
                read -r token_input
                if [ -n "$token_input" ]; then
                    sed -i.bak "s|^NEXUS_TG_TOKEN=.*|NEXUS_TG_TOKEN=${token_input}|" .env
                    rm -f .env.bak
                fi
            fi

            if [ -n "$TG_CHAT_ID" ]; then
                sed -i.bak "s|^NEXUS_TG_USERS=.*|NEXUS_TG_USERS=${TG_CHAT_ID}|" .env
                rm -f .env.bak
            else
                echo ""
                echo -e "  ${BOLD}${CYAN}Telegram Chat ID${RESET}"
                echo -e "  ${DIM}Deine Telegram-User-ID (oder leer für alle)${RESET}"
                echo -n "  Chat ID: "
                read -r chat_input
                if [ -n "$chat_input" ]; then
                    sed -i.bak "s|^NEXUS_TG_USERS=.*|NEXUS_TG_USERS=${chat_input}|" .env
                    rm -f .env.bak
                fi
            fi

            # Set Ollama host
            sed -i.bak "s|^OLLAMA_HOST=.*|OLLAMA_HOST=${OLLAMA_HOST}|" .env
            rm -f .env.bak
        fi
    fi
    success "Konfiguration bereit"
    echo ""

    # ─── Step 4: Build Docker Image ──────────────────────────────────────
    step "Baue Docker-Image..."
    echo -e "  ${DIM}Dies kann einige Minuten dauern (erster Build)...${RESET}"

    if [ "$DRY_RUN" = true ]; then
        info "DRY RUN: ${COMPOSE_CMD} build nexus-telegram"
    else
        cd "$INSTALL_DIR"
        if ${COMPOSE_CMD} build nexus-telegram 2>&1 | tail -5; then
            success "Image gebaut: ${IMAGE_NAME}"
        else
            error "Build fehlgeschlagen!"
            echo -e "  ${DIM}Prüfe Docker-Logs mit: docker compose logs${RESET}"
            exit 1
        fi
    fi
    echo ""

    # ─── Step 5: Start Container ────────────────────────────────────────
    step "Starte Nexus..."
    if [ "$DRY_RUN" = true ]; then
        info "DRY RUN: ${COMPOSE_CMD} up -d nexus-telegram"
    else
        cd "$INSTALL_DIR"
        ${COMPOSE_CMD} up -d nexus-telegram 2>&1 | tail -3
    fi
    success "Container gestartet"
    echo ""

    # ─── Step 6: Health Check ────────────────────────────────────────────
    step "Health-Check..."
    if [ "$DRY_RUN" = false ]; then
        local retries=0
        local max_retries=15
        while [ $retries -lt $max_retries ]; do
            if docker ps --filter "name=nexus-toti-telegram" --filter "health=healthy" --format "{{.Names}}" | grep -q "nexus"; then
                break
            fi
            printf "\r  ${CYAN}${SPINNER[$((retries % 10))]}${RESET} Warte auf Health-Check... (%d/%d)   " $((retries + 1)) $max_retries
            retries=$((retries + 1))
            sleep 2
        done
        printf "\r%*s\r" 60 ""

        if [ $retries -eq $max_retries ]; then
            warn "Health-Check Timeout — Container läuft aber evtl. noch beim Starten"
            echo -e "  ${DIM}Prüfe mit: docker logs nexus-toti-telegram${RESET}"
        else
            success "Container ist gesund (healthy)"
        fi
    fi
    echo ""

    # ─── Summary ────────────────────────────────────────────────────────
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║           NEXUS v9 — Installation fertig!        ║${RESET}"
    echo -e "${BOLD}${CYAN}╠══════════════════════════════════════════════════╣${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Installiert in:  ${BOLD}${INSTALL_DIR}${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Docker-Image:   ${BOLD}${IMAGE_NAME}${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Container:       ${BOLD}nexus-toti-telegram${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Skills:          ${BOLD}156${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}  ${GREEN}✓${RESET}  Lizenz:          ${BOLD}GNU GPLv3${RESET}    "
    echo -e "${BOLD}${CYAN}║${RESET}                                                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}Logs:       docker logs -f nexus-toti-telegram${RESET}  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}Stoppen:    docker compose stop${RESET}                  ${BOLD}${CYAN}║${RESET}"
    echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}Neustarten: docker compose restart${RESET}              ${BOLD}${CYAN}║${RESET}"
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