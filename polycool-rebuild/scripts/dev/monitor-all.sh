#!/bin/bash
# Monitor all services logs in parallel
# Usage: ./scripts/dev/monitor-all.sh
#
# This script ONLY monitors logs - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}📊 Monitoring All Services${NC}"
echo ""

# Check if tmux is available (best option)
if command -v tmux >/dev/null 2>&1; then
    echo -e "${GREEN}✅ tmux detected - will use separate panes${NC}"
    USE_TMUX=true
else
    USE_TMUX=false
    echo -e "${YELLOW}⚠️  tmux not found - will use simple tail${NC}"
fi

# Create logs directory if it doesn't exist
mkdir -p logs

# Function to monitor with tmux
monitor_with_tmux() {
    local session_name="polycool-monitor"

    # Kill existing session if it exists
    tmux kill-session -t "$session_name" 2>/dev/null || true

    # Create new session with API log
    tmux new-session -d -s "$session_name" -n "api" "tail -f logs/api.log 2>/dev/null || echo 'API log not found'"

    # Create windows for other logs
    tmux new-window -t "$session_name" -n "bot" "tail -f logs/bot.log 2>/dev/null || echo 'Bot log not found'"
    tmux new-window -t "$session_name" -n "workers" "tail -f logs/workers.log 2>/dev/null || echo 'Workers log not found'"

    # Create a combined view window
    tmux new-window -t "$session_name" -n "all" "
        echo '=== API Log ===' && tail -f logs/api.log 2>/dev/null &
        echo '=== Bot Log ===' && tail -f logs/bot.log 2>/dev/null &
        echo '=== Workers Log ===' && tail -f logs/workers.log 2>/dev/null &
        wait
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

    # Ask if user wants to attach
    read -p "Attach to monitoring session now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        tmux attach -t "$session_name"
    fi
}

# Function to monitor without tmux (simple tail)
monitor_without_tmux() {
    echo -e "${BLUE}📋 Monitoring logs (Ctrl+C to stop)${NC}"
    echo ""
    echo -e "${YELLOW}Note: Logs will be interleaved. For better separation, use tmux.${NC}"
    echo ""

    # Use tail -f on all log files
    if [ -f "logs/api.log" ] && [ -f "logs/bot.log" ] && [ -f "logs/workers.log" ]; then
        tail -f logs/api.log logs/bot.log logs/workers.log 2>/dev/null
    elif [ -f "logs/api.log" ]; then
        tail -f logs/api.log 2>/dev/null
    elif [ -f "logs/bot.log" ]; then
        tail -f logs/bot.log 2>/dev/null
    elif [ -f "logs/workers.log" ]; then
        tail -f logs/workers.log 2>/dev/null
    else
        echo -e "${RED}❌ No log files found${NC}"
        echo "   → Start services first: ./scripts/dev/start-all.sh"
        exit 1
    fi
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

# Function to show log file sizes
show_log_sizes() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Log File Sizes${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    for log_file in logs/api.log logs/bot.log logs/workers.log; do
        if [ -f "$log_file" ]; then
            SIZE=$(du -h "$log_file" | cut -f1)
            LINES=$(wc -l < "$log_file" 2>/dev/null || echo "0")
            echo -e "${BLUE}   ${log_file}:${NC} ${SIZE} (${LINES} lines)"
        else
            echo -e "${YELLOW}   ${log_file}: Not found${NC}"
        fi
    done
    echo ""
}

# Show service status
show_service_status

# Show log sizes
show_log_sizes

# Start monitoring
if [ "$USE_TMUX" = true ]; then
    monitor_with_tmux
else
    monitor_without_tmux
fi
