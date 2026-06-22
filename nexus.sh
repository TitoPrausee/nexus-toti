#!/bin/bash
# Nexus Agent — Management Script
# Basiert auf Hermes-Agent, mit Atlas Memory System
set -e

NEXUS_DIR="$HOME/.nexus"
COMPOSE_FILE="$(cd "$(dirname "$0")" && pwd)/docker-compose.yml"
CONTAINER_NAME="nexus"
PORT=8690

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[Nexus]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }

check_docker() { docker info >/dev/null 2>&1 || { err "Docker läuft nicht."; exit 1; }; }
is_running() { docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; }

case "${1:-help}" in
    start)
        check_docker
        if is_running; then info "Nexus läuft bereits (Port $PORT)"; exit 0; fi
        info "Starte Nexus (Port $PORT)..."
        docker compose -f "$COMPOSE_FILE" up -d && sleep 3
        is_running && ok "Nexus läuft auf Port $PORT" || { err "Fehler"; exit 1; }
        ;;
    stop)   check_docker; docker compose -f "$COMPOSE_FILE" down; ok "Nexus gestoppt" ;;
    restart) $0 stop; sleep 2; $0 start ;;
    status)
        check_docker
        if is_running; then
            ok "Nexus läuft (Port $PORT)"
            docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
            [ -d "$NEXUS_DIR/memory/git/.git" ] && {
                C=$(cd "$NEXUS_DIR/memory/git" && git log --oneline 2>/dev/null | wc -l)
                F=$(find "$NEXUS_DIR/memory/git" -name "*.md" -not -path "*.git/*" | wc -l)
                ok "Atlas Memory: $C Commits, $F Dateien"
            }
        else warn "Nexus läuft nicht"; fi
        ;;
    logs)   check_docker; docker logs -f --tail "${2:-50}" "$CONTAINER_NAME" ;;
    chat)
        check_docker
        if ! is_running; then err "Nexus läuft nicht"; exit 1; fi
        if [ -n "$2" ]; then
            docker exec -i "$CONTAINER_NAME" ollama launch claude -p "$2" --model glm-5.2:cloud --dangerously-skip-permissions
        else
            docker exec -it "$CONTAINER_NAME" ollama launch claude --model glm-5.2:cloud --dangerously-skip-permissions
        fi
        ;;
    memory)
        case "${2:-status}" in
            status)
                if [ -d "$NEXUS_DIR/memory/git/.git" ]; then
                    cd "$NEXUS_DIR/memory/git"
                    echo "=== Atlas Memory ==="
                    echo "Commits: $(git log --oneline | wc -l)"
                    echo "Letzter: $(git log -1 --format='%h %ai %s')"
                    echo "Dateien: $(find . -name '*.md' -not -path './.git/*' | wc -l)"
                else err "Nicht initialisiert"; fi
                ;;
            search) cd "$NEXUS_DIR/memory/git" && git grep -n "$3" -- "*.md" || echo "Keine Treffer" ;;
            log) cd "$NEXUS_DIR/memory/git" && git log --oneline -"${3:-20}" ;;
        esac
        ;;
    doctor)
        echo "=== Container ==="; is_running && ok "Läuft" || warn "Läuft nicht"
        echo "=== Memory ==="; [ -d "$NEXUS_DIR/memory/git/.git" ] && ok "Git-Repo" || warn "Kein Git"
        echo "=== Ollama ==="; curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && ok "OK" || err "Nicht erreichbar"
        ;;
    help|*)
        echo "Nexus Agent — Management Script"
        echo "Verwendung: $0 start|stop|restart|status|logs|chat|memory|doctor"
        ;;
esac
