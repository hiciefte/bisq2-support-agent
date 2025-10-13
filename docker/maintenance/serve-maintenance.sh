#!/bin/bash
#
# Serve Maintenance Page
# This script serves the static maintenance page on port 80 during deployments
# when all Docker containers are down
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAINTENANCE_HTML="$SCRIPT_DIR/maintenance.html"
PID_FILE="/tmp/maintenance-server.pid"
PORT="${MAINTENANCE_PORT:-80}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

start_maintenance() {
    if [ -f "$PID_FILE" ]; then
        log "Maintenance server already running (PID: $(cat "$PID_FILE"))"
        return 0
    fi

    log "Starting maintenance page server on port $PORT..."

    # Check if port is available
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        log "WARNING: Port $PORT is already in use. Maintenance page may not be accessible."
        log "Stopping existing service on port $PORT..."
        # Try to stop whatever is on that port
        lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
        sleep 2
    fi

    # Create temporary directory with just the maintenance.html file
    TEMP_DIR=$(mktemp -d)
    cp "$MAINTENANCE_HTML" "$TEMP_DIR/index.html"

    # Start Python HTTP server in background
    cd "$TEMP_DIR"
    nohup python3 -m http.server $PORT > /tmp/maintenance-server.log 2>&1 &
    SERVER_PID=$!
    echo $SERVER_PID > "$PID_FILE"

    log "Maintenance server started (PID: $SERVER_PID)"
    log "Accessible at: http://localhost:$PORT"
    log "Log file: /tmp/maintenance-server.log"
}

stop_maintenance() {
    if [ ! -f "$PID_FILE" ]; then
        log "Maintenance server is not running"
        return 0
    fi

    PID=$(cat "$PID_FILE")
    log "Stopping maintenance server (PID: $PID)..."

    if kill -0 $PID 2>/dev/null; then
        kill $PID
        sleep 1

        # Force kill if still running
        if kill -0 $PID 2>/dev/null; then
            log "Force killing maintenance server..."
            kill -9 $PID
        fi
    fi

    rm -f "$PID_FILE"
    log "Maintenance server stopped"
}

status_maintenance() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 $PID 2>/dev/null; then
            log "Maintenance server is running (PID: $PID)"
            return 0
        else
            log "Maintenance server PID file exists but process is not running"
            rm -f "$PID_FILE"
            return 1
        fi
    else
        log "Maintenance server is not running"
        return 1
    fi
}

case "${1:-}" in
    start)
        start_maintenance
        ;;
    stop)
        stop_maintenance
        ;;
    status)
        status_maintenance
        ;;
    restart)
        stop_maintenance
        sleep 1
        start_maintenance
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart}"
        echo ""
        echo "This script manages a simple HTTP server that serves the maintenance page"
        echo "on port $PORT during Docker container deployments."
        echo ""
        echo "Examples:"
        echo "  $0 start   - Start serving maintenance page"
        echo "  $0 stop    - Stop serving maintenance page"
        echo "  $0 status  - Check if maintenance server is running"
        exit 1
        ;;
esac
