#!/bin/bash

# Simple local testing script for telegram bot
# Usage: ./test_all_services_local.sh [start|stop|status]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$SCRIPT_DIR"
PID_FILE="$BOT_DIR/bot.pid"
LOG_FILE="$BOT_DIR/logs/bot.log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
}

warn() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

check_python() {
    if ! command -v python3 &> /dev/null; then
        error "Python3 not found"
        exit 1
    fi
}

check_requirements() {
    if [ ! -f "$BOT_DIR/requirements.txt" ]; then
        error "requirements.txt not found in $BOT_DIR"
        exit 1
    fi
}

start_bot() {
    info "Starting Telegram Bot..."

    # Create logs directory
    mkdir -p "$BOT_DIR/logs"

    # Check if already running
    if [ -f "$PID_FILE" ]; then
        if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            warn "Bot already running (PID: $(cat "$PID_FILE"))"
            return 0
        else
            rm -f "$PID_FILE"
        fi
    fi

    # Start bot
    cd "$BOT_DIR"
    nohup python3 main.py > "$LOG_FILE" 2>&1 &
    BOT_PID=$!
    echo $BOT_PID > "$PID_FILE"

    log "Bot started with PID: $BOT_PID"
    log "Logs: $LOG_FILE"

    # Wait a moment and check if it's still running
    sleep 2
    if kill -0 $BOT_PID 2>/dev/null; then
        log "✅ Bot is running"
    else
        error "❌ Bot failed to start - check logs"
        exit 1
    fi
}

stop_bot() {
    info "Stopping Telegram Bot..."

    if [ -f "$PID_FILE" ]; then
        BOT_PID=$(cat "$PID_FILE")
        if kill -0 $BOT_PID 2>/dev/null; then
            kill $BOT_PID
            log "Sent stop signal to bot (PID: $BOT_PID)"
            sleep 2

            # Force kill if still running
            if kill -0 $BOT_PID 2>/dev/null; then
                kill -9 $BOT_PID 2>/dev/null || true
                warn "Force killed bot"
            fi
        else
            warn "Bot process not found"
        fi
        rm -f "$PID_FILE"
    else
        warn "No PID file found - bot not running"
    fi

    # Clean up any remaining processes
    pkill -f "python3 main.py" 2>/dev/null || true

    log "✅ Bot stopped"
}

show_status() {
    echo "=== Bot Status ==="

    if [ -f "$PID_FILE" ]; then
        BOT_PID=$(cat "$PID_FILE")
        if kill -0 $BOT_PID 2>/dev/null; then
            echo "✅ Bot RUNNING (PID: $BOT_PID)"
        else
            echo "❌ Bot STOPPED (stale PID file)"
            rm -f "$PID_FILE"
        fi
    else
        echo "❌ Bot STOPPED"
    fi

    if [ -f "$LOG_FILE" ]; then
        echo "📄 Logs: $LOG_FILE"
        echo "📊 Last 3 lines:"
        tail -3 "$LOG_FILE" 2>/dev/null || echo "   (empty log)"
    fi
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo "=== Bot Logs ($LOG_FILE) ==="
        tail -f "$LOG_FILE"
    else
        error "Log file not found: $LOG_FILE"
    fi
}

# Main logic
case "${1:-status}" in
    start)
        check_python
        check_requirements
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        stop_bot
        sleep 2
        start_bot
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the bot"
        echo "  stop    - Stop the bot"
        echo "  restart - Restart the bot"
        echo "  status  - Show bot status"
        echo "  logs    - Show live logs"
        exit 1
        ;;
esac
