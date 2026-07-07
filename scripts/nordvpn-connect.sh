#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║           NordVPN Connect — Linux VPN via Docker                   ║
# ║                                                                    ║
# ║  Nutzt bubuntux/nordvpn Docker-Image für eine sichere              ║
# ║  VPN-Verbindung mit NordVPN Access Token.                          ║
# ║                                                                    ║
# ║  Usage:                                                            ║
# ║    ./nordvpn-connect.sh --token TOKEN [OPTIONEN]                   ║
# ║                                                                    ║
# ║  Beispiele:                                                        ║
# ║    ./nordvpn-connect.sh --token TOKEN                              ║
# ║    ./nordvpn-connect.sh --token TOKEN --country Germany            ║
# ║    ./nordvpn-connect.sh --token TOKEN --country Netherlands        ║
# ║    ./nordvpn-connect.sh --token TOKEN --country Italy --kill       ║
# ║    ./nordvpn-connect.sh --disconnect                               ║
# ║    ./nordvpn-connect.sh --status                                  ║
# ╚══════════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ─── Konfiguration ────────────────────────────────────────────────────
IMAGE="bubuntux/nordvpn:latest"
CONTAINER_NAME="nordvpn-gateway"
NETWORK="192.168.148.0/24"
TZ="${TZ:-Europe/Berlin}"

# Farben
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

info()    { echo -e "${BLUE}${BOLD}ℹ${RESET}  $1"; }
success() { echo -e "${GREEN}${BOLD}✓${RESET}  $1"; }
warn()    { echo -e "${YELLOW}${BOLD}⚠${RESET}  $1"; }
error()   { echo -e "${RED}${BOLD}✗${RESET}  $1"; }
step()    { echo -e "${CYAN}${BOLD}▸${RESET}  $1"; }

# ─── Argumente parsen ─────────────────────────────────────────────────
TOKEN=""
COUNTRY="Germany"
TECHNOLOGY="NordLynx"
KILL_SWITCH=false
DISCONNECT=false
SHOW_STATUS=false

usage() {
    echo "NordVPN Connect — Linux VPN via Docker"
    echo ""
    echo "Usage: $0 [OPTIONEN]"
    echo ""
    echo "Optionen:"
    echo "  --token TOKEN       NordVPN Access Token (Pflicht)"
    echo "  --country LAND      Server-Land (default: Germany)"
    echo "  --technology TECH   NordLynx oder OpenVPN (default: NordLynx)"
    echo "  --kill              Kill-Switch aktivieren"
    echo "  --disconnect        VPN trennen und Container stoppen"
    echo "  --status            VPN-Status anzeigen"
    echo "  --help              Diese Hilfe"
    echo ""
    echo "Beispiele:"
    echo "  $0 --token TOKEN"
    echo "  $0 --token TOKEN --country Netherlands --kill"
    echo "  $0 --disconnect"
    echo "  $0 --status"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token|-t)       TOKEN="$2"; shift 2 ;;
        --country|-c)     COUNTRY="$2"; shift 2 ;;
        --technology)     TECHNOLOGY="$2"; shift 2 ;;
        --kill)           KILL_SWITCH=true; shift ;;
        --disconnect|-d)  DISCONNECT=true; shift ;;
        --status|-s)      SHOW_STATUS=true; shift ;;
        --help|-h)        usage ;;
        *) error "Unbekannte Option: $1"; usage ;;
    esac
done

# ─── Prüfungen ────────────────────────────────────────────────────────

check_docker() {
    if ! docker info >/dev/null 2>&1; then
        error "Docker läuft nicht. Bitte Docker installieren und starten."
        echo ""
        echo -e "  ${BOLD}Installation:${RESET}"
        echo -e "  ${CYAN}curl -fsSL https://get.docker.com | sh${RESET}"
        exit 1
    fi
}

check_token() {
    if [ -z "$TOKEN" ]; then
        # Prüfe ob Token in Umgebungsvariable
        TOKEN="${NORDVPN_TOKEN:-}"
    fi
    if [ -z "$TOKEN" ] && [ "$DISCONNECT" = false ] && [ "$SHOW_STATUS" = false ]; then
        error "Kein NordVPN Access Token angegeben."
        echo ""
        echo -e "  ${BOLD}Token besorgen:${RESET}"
        echo -e "  1. Bei NordVPN einloggen: ${CYAN}https://my.nordaccount.com${RESET}"
        echo -e "  2. Service-Credentials → Access Token kopieren"
        echo -e "  3. Oder als Umgebungsvariable setzen:"
        echo -e "     ${DIM}export NORDVPN_TOKEN=dein_token${RESET}"
        echo -e "     ${DIM}$0 --country Germany${RESET}"
        exit 1
    fi
}

# ─── Aktionen ─────────────────────────────────────────────────────────

do_connect() {
    step "Starte NordVPN Verbindung..."
    echo ""

    # Prüfe ob bereits ein Container läuft
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        warn "VPN-Container läuft bereits. Trenne zuerst mit --disconnect."
        exit 1
    fi

    # Prüfe ob alter Container existiert (gestoppt)
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        info "Entferne alten Container..."
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1
    fi

    # Docker-Image pullen (falls nicht vorhanden)
    if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
        step "Pulle Docker-Image ($IMAGE)..."
        docker pull "$IMAGE" 2>&1 | tail -1
    fi

    # Container starten
    step "Starte VPN-Container (${COUNTRY}, ${TECHNOLOGY})..."

    local cmd="docker run -d \
        --name $CONTAINER_NAME \
        --restart unless-stopped \
        --cap-add NET_ADMIN \
        --cap-add SYS_MODULE \
        --cap-add NET_RAW \
        --sysctl net.ipv4.conf.all.rp_filter=2 \
        --sysctl net.ipv6.conf.all.disable_ipv6=1 \
        -e NETWORK=\"$NETWORK\" \
        -e TZ=\"$TZ\" \
        -e TOKEN=\"$TOKEN\" \
        -e CONNECT=\"$COUNTRY\" \
        -e TECHNOLOGY=\"$TECHNOLOGY\""

    if [ "$KILL_SWITCH" = true ]; then
        cmd="$cmd -e KILL_SWITCH=on"
        info "Kill-Switch aktiviert"
    fi

    cmd="$cmd $IMAGE"

    eval "$cmd" >/dev/null 2>&1

    # Warten auf Verbindung
    info "Warte auf VPN-Verbindung..."
    local retries=0
    local max_retries=30
    while [ $retries -lt $max_retries ]; do
        local status
        status=$(docker exec "$CONTAINER_NAME" python3 -c "
import urllib.request
try:
    resp = urllib.request.urlopen('https://ipapi.co/json/', timeout=10)
    import json
    data = json.loads(resp.read())
    print(data.get('country_name', 'waiting'))
except:
    print('waiting')
" 2>/dev/null)

        if [ "$status" != "waiting" ] && [ -n "$status" ]; then
            local ip
            ip=$(docker exec "$CONTAINER_NAME" python3 -c "
import urllib.request
try:
    ip = urllib.request.urlopen('https://ifconfig.me', timeout=10).read().decode().strip()
    print(ip)
except:
    print('unknown')
" 2>/dev/null)
            echo ""
            success "VPN verbunden!"
            echo -e "  Land:    ${BOLD}${status}${RESET}"
            echo -e "  IP:      ${BOLD}${ip}${RESET}"
            echo -e "  Technik: ${BOLD}${TECHNOLOGY}${RESET}"
            echo ""
            info "Container läuft als: ${CONTAINER_NAME}"
            info "Zum Trennen: $0 --disconnect"
            return 0
        fi

        printf "\r  ${CYAN}⏳${RESET} Warte... (%d/%d)   " $((retries + 1)) $max_retries
        retries=$((retries + 1))
        sleep 2
    done

    echo ""
    warn "VPN-Verbindung konnte nicht bestätigt werden."
    warn "Prüfe mit: docker logs $CONTAINER_NAME"
}

do_disconnect() {
    step "Trenne VPN-Verbindung..."

    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        docker stop "$CONTAINER_NAME" >/dev/null 2>&1
        docker rm "$CONTAINER_NAME" >/dev/null 2>&1
        success "VPN getrennt und Container entfernt."
    else
        if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
            docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1
            success "Alter Container entfernt."
        else
            warn "Kein aktiver VPN-Container gefunden."
        fi
    fi
}

do_status() {
    step "VPN-Status..."

    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo ""
        echo -e "  ${GREEN}✓${RESET} Container: ${BOLD}${CONTAINER_NAME}${RESET} (läuft)"

        # IP und Land abfragen
        local ip country
        ip=$(docker exec "$CONTAINER_NAME" python3 -c "
import urllib.request
try:
    ip = urllib.request.urlopen('https://ifconfig.me', timeout=10).read().decode().strip()
    print(ip)
except:
    print('unbekannt')
" 2>/dev/null)
        country=$(docker exec "$CONTAINER_NAME" python3 -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen('https://ipapi.co/json/', timeout=10)
    data = json.loads(resp.read())
    print(data.get('country_name', 'unbekannt'))
except:
    print('unbekannt')
" 2>/dev/null)

        echo -e "  🌍 IP:      ${BOLD}${ip}${RESET}"
        echo -e "  🏳️  Land:    ${BOLD}${country}${RESET}"

        # Verbindungsdetails aus Container-Env
        local conn tech
        conn=$(docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{.}}{{"\n"}}{{end}}' 2>/dev/null | grep "^CONNECT=" | cut -d= -f2 || echo "unbekannt")
        tech=$(docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{.}}{{"\n"}}{{end}}' 2>/dev/null | grep "^TECHNOLOGY=" | cut -d= -f2 || echo "unbekannt")

        echo -e "  🔗 Server:  ${BOLD}${conn}${RESET}"
        echo -e "  ⚙️  Technik: ${BOLD}${tech}${RESET}"
        echo ""
        info "Zum Trennen: $0 --disconnect"
    else
        warn "Kein aktiver VPN-Container."
        echo ""
        echo -e "  Verbinden mit: ${BOLD}$0 --token TOKEN${RESET}"
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────

check_docker

if [ "$DISCONNECT" = true ]; then
    do_disconnect
    exit 0
fi

if [ "$SHOW_STATUS" = true ]; then
    do_status
    exit 0
fi

check_token
do_connect
