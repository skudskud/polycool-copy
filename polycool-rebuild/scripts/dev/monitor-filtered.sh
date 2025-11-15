#!/bin/bash
# Monitor all services logs with poller filtering
# Usage: ./scripts/dev/monitor-filtered.sh
#
# This script filters out verbose poller logs while keeping important messages

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}📊 Monitoring All Services (Filtered)${NC}"
echo -e "${YELLOW}⚠️  Poller logs filtered - showing only errors, warnings, and key events${NC}"
echo ""

# Create logs directory if it doesn't exist
mkdir -p logs

# Function to filter poller logs
# Keep: errors, warnings, and important info (✅, 🚀, 🛑, ❌)
# Filter out: verbose info logs (📦, 📊, 📥, etc.)
filter_poller_logs() {
    grep -v --line-buffered \
        -e "Events poll cycle completed" \
        -e "Fetched.*events" \
        -e "Fetched.*markets" \
        -e "Price poll cycle completed" \
        -e "Resolutions poll cycle completed" \
        -e "Standalone poll cycle completed" \
        -e "UPSERT:" \
        -e "Processing events batch" \
        -e "Fetching events batch" \
        -e "Fetching all active events" \
        -e "Extracted.*markets from.*events" \
        -e "Created.*parent events" \
        -e "Found.*markets" \
        -e "Fetched.*markets from" \
        -e "Price poller:" \
        -e "📦\|📊\|📥\|📁\|🏷️" \
    | grep --line-buffered \
        -e "ERROR\|WARNING\|CRITICAL" \
        -e "✅\|🚀\|🛑\|❌\|⚠️" \
        -e "Error\|Failed\|Exception\|Traceback" \
        -e "started\|stopped\|connected\|disconnected" \
        -e "API\|Bot\|Workers\|Streamer\|WebSocket" \
        -e "position\|trade\|market.*created\|market.*updated" \
        -e "PnL\|price.*update\|stop.*loss\|take.*profit" \
        -e "copy.*trading\|smart.*trading" \
        || true
}

# Function to show service status
show_service_status() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Service Status${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Check API
    API_URL="${API_URL:-http://localhost:8000}"
    if curl -s -f "${API_URL}/health/live" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ API Service: Running${NC}"
    else
        echo -e "${RED}❌ API Service: Not running${NC}"
    fi

    # Check Bot process
    if [ -f "logs/bot.pid" ]; then
        BOT_PID=$(cat logs/bot.pid 2>/dev/null)
        if [ -n "$BOT_PID" ] && ps -p "$BOT_PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Bot Service: Running (PID: ${BOT_PID})${NC}"
        else
            echo -e "${RED}❌ Bot Service: Not running${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Bot Service: PID file not found${NC}"
    fi

    # Check Workers process
    if [ -f "logs/workers.pid" ]; then
        WORKERS_PID=$(cat logs/workers.pid 2>/dev/null)
        if [ -n "$WORKERS_PID" ] && ps -p "$WORKERS_PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Workers Service: Running (PID: ${WORKERS_PID})${NC}"
        else
            echo -e "${RED}❌ Workers Service: Not running${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Workers Service: PID file not found${NC}"
    fi

    # Check Redis
    if command -v redis-cli >/dev/null 2>&1; then
        if redis-cli ping >/dev/null 2>&1; then
            echo -e "${GREEN}✅ Redis: Running${NC}"
        else
            echo -e "${RED}❌ Redis: Not running${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Redis: redis-cli not found${NC}"
    fi

    echo ""
}

# Function to monitor with tmux (filtered)
monitor_with_tmux_filtered() {
    local session_name="polycool-monitor-filtered"

    # Kill existing session if it exists
    tmux kill-session -t "$session_name" 2>/dev/null || true

    # Create new session with API log (filtered)
    tmux new-session -d -s "$session_name" -n "api" \
        "tail -f logs/api.log 2>/dev/null | grep --line-buffered -v 'GET /health' || echo 'API log not found'"

    # Create windows for other logs (filtered)
    tmux new-window -t "$session_name" -n "bot" \
        "tail -f logs/bot.log 2>/dev/null || echo 'Bot log not found'"

    tmux new-window -t "$session_name" -n "workers" \
        "tail -f logs/workers.log 2>/dev/null | filter_poller_logs || echo 'Workers log not found'"

    # Create a combined view window (all filtered)
    tmux new-window -t "$session_name" -n "all" "
        (
            echo '=== API Log (filtered) ===' &&
            tail -f logs/api.log 2>/dev/null | grep --line-buffered -v 'GET /health' &
            echo '=== Bot Log ===' &&
            tail -f logs/bot.log 2>/dev/null &
            echo '=== Workers Log (filtered) ===' &&
            tail -f logs/workers.log 2>/dev/null | filter_poller_logs &
            wait
        ) 2>/dev/null || echo 'Logs not found'
    "

    echo ""
    echo -e "${GREEN}✅ Monitoring session created: ${session_name}${NC}"
    echo ""
    echo "📊 Commands:"
    echo "   • Attach to session: ${BLUE}tmux attach -t ${session_name}${NC}"
    echo "   • List windows: ${BLUE}tmux list-windows -t ${session_name}${NC}"
    echo "   • Switch windows: ${BLUE}Ctrl+B + 0-3${NC}"
    echo "   • Detach: ${BLUE}Ctrl+B + D${NC}"
    echo "   • Kill session: ${BLUE}tmux kill-session -t ${session_name}${NC}"
    echo ""
    echo -e "${CYAN}💡 Tip: Poller logs are filtered. To see all logs, use: ${BLUE}./scripts/dev/monitor-all.sh${NC}"
    echo ""

    # Ask if user wants to attach
    read -p "Attach to monitoring session now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        tmux attach -t "$session_name"
    fi
}

# Function to monitor without tmux (filtered)
monitor_without_tmux_filtered() {
    echo -e "${BLUE}📋 Monitoring logs (Ctrl+C to stop)${NC}"
    echo -e "${YELLOW}⚠️  Poller logs filtered - showing only important messages${NC}"
    echo ""

    # Check if log files exist
    if [ ! -f "logs/api.log" ] && [ ! -f "logs/bot.log" ] && [ ! -f "logs/workers.log" ]; then
        echo -e "${RED}❌ No log files found${NC}"
        echo "   → Start services first: ./scripts/dev/start-all.sh"
        exit 1
    fi

    # Use tail -f with filtering
    (
        if [ -f "logs/api.log" ]; then
            echo -e "${CYAN}=== API Log (filtered) ===${NC}"
            tail -f logs/api.log 2>/dev/null | grep --line-buffered -v 'GET /health' &
        fi

        if [ -f "logs/bot.log" ]; then
            echo -e "${CYAN}=== Bot Log ===${NC}"
            tail -f logs/bot.log 2>/dev/null &
        fi

        if [ -f "logs/workers.log" ]; then
            echo -e "${CYAN}=== Workers Log (filtered) ===${NC}"
            tail -f logs/workers.log 2>/dev/null | filter_poller_logs &
        fi

        wait
    ) 2>/dev/null
}

# Check if tmux is available
if command -v tmux >/dev/null 2>&1; then
    USE_TMUX=true
else
    USE_TMUX=false
fi

# Show service status
show_service_status

# Start monitoring
if [ "$USE_TMUX" = true ]; then
    monitor_with_tmux_filtered
else
    monitor_without_tmux_filtered
fi
