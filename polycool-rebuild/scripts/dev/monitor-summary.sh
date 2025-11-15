#!/bin/bash
# Show a summary of recent logs instead of streaming
# Usage: ./scripts/dev/monitor-summary.sh [refresh_interval]
#
# This script shows a summary of recent important logs instead of streaming everything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

REFRESH_INTERVAL="${1:-5}"

echo -e "${BLUE}📊 Service Logs Summary${NC}"
echo -e "${YELLOW}⚠️  Refreshing every ${REFRESH_INTERVAL} seconds (Ctrl+C to stop)${NC}"
echo ""

# Function to show summary
show_summary() {
    clear
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}📊 Service Logs Summary - $(date '+%H:%M:%S')${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # API Log Summary
    if [ -f "logs/api.log" ]; then
        echo -e "${CYAN}=== API (last 5 lines, errors/warnings only) ===${NC}"
        tail -n 100 logs/api.log | grep -E "ERROR|WARNING|CRITICAL|Exception|Failed" | tail -n 5 || echo "  No errors/warnings"
        echo ""
    fi

    # Bot Log Summary
    if [ -f "logs/bot.log" ]; then
        echo -e "${CYAN}=== Bot (last 5 lines, errors/warnings only) ===${NC}"
        tail -n 100 logs/bot.log | grep -E "ERROR|WARNING|CRITICAL|Exception|Failed|✅|❌|⚠️" | tail -n 5 || echo "  No errors/warnings"
        echo ""
    fi

    # Workers Log Summary (filtered)
    if [ -f "logs/workers.log" ]; then
        echo -e "${CYAN}=== Workers (last 5 important lines) ===${NC}"
        tail -n 200 logs/workers.log | grep -v \
            -e "Events poll cycle completed" \
            -e "Fetched.*events" \
            -e "Fetched.*markets" \
            -e "Price poll cycle completed" \
            -e "UPSERT:" \
            -e "📦\|📊\|📥\|📁\|🏷️" \
        | grep -E "ERROR|WARNING|CRITICAL|Exception|Failed|✅|🚀|🛑|❌|⚠️|started|stopped|connected|disconnected|Streamer|WebSocket|position|trade|PnL|stop.*loss|take.*profit" \
        | tail -n 5 || echo "  No important messages"
        echo ""
    fi

    # Service Status
    echo -e "${CYAN}=== Service Status ===${NC}"

    # API
    API_URL="${API_URL:-http://localhost:8000}"
    if curl -s -f "${API_URL}/health/live" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ API: Running${NC}"
    else
        echo -e "${RED}❌ API: Not running${NC}"
    fi

    # Bot
    if [ -f "logs/bot.pid" ]; then
        BOT_PID=$(cat logs/bot.pid 2>/dev/null)
        if [ -n "$BOT_PID" ] && ps -p "$BOT_PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Bot: Running (PID: ${BOT_PID})${NC}"
        else
            echo -e "${RED}❌ Bot: Not running${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Bot: PID file not found${NC}"
    fi

    # Workers
    if [ -f "logs/workers.pid" ]; then
        WORKERS_PID=$(cat logs/workers.pid 2>/dev/null)
        if [ -n "$WORKERS_PID" ] && ps -p "$WORKERS_PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Workers: Running (PID: ${WORKERS_PID})${NC}"
        else
            echo -e "${RED}❌ Workers: Not running${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Workers: PID file not found${NC}"
    fi

    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}Refreshing in ${REFRESH_INTERVAL} seconds... (Ctrl+C to stop)${NC}"
}

# Main loop
while true; do
    show_summary
    sleep "$REFRESH_INTERVAL"
done
