#!/bin/bash
# View logs from all services
# Usage: ./scripts/dev/view-logs.sh [service] [--follow]

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SERVICE="${1:-all}"
FOLLOW="${2:-}"

# Create logs directory if it doesn't exist
mkdir -p logs

view_logs() {
    local service=$1
    local log_file="logs/${service}.log"

    if [ ! -f "$log_file" ]; then
        echo -e "${YELLOW}⚠️  Log file not found: ${log_file}${NC}"
        return 1
    fi

    echo -e "${BLUE}📋 Viewing logs for ${service}...${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [ "$FOLLOW" = "--follow" ] || [ "$FOLLOW" = "-f" ]; then
        tail -f "$log_file"
    else
        tail -n 100 "$log_file"
    fi
}

case "$SERVICE" in
    api)
        view_logs "api"
        ;;
    bot)
        view_logs "bot"
        ;;
    workers)
        view_logs "workers"
        ;;
    all)
        echo -e "${BLUE}📋 Viewing logs for all services...${NC}"
        echo ""

        if [ "$FOLLOW" = "--follow" ] || [ "$FOLLOW" = "-f" ]; then
            # Use multitail if available, otherwise tail -f for each
            if command -v multitail >/dev/null 2>&1; then
                multitail -s 2 logs/api.log logs/bot.log logs/workers.log
            else
                echo -e "${YELLOW}⚠️  multitail not found. Showing last 50 lines of each service:${NC}"
                echo ""
                echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
                echo -e "${BLUE}API Logs:${NC}"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                tail -n 50 logs/api.log 2>/dev/null || echo "No API logs"
                echo ""
                echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
                echo -e "${BLUE}Bot Logs:${NC}"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                tail -n 50 logs/bot.log 2>/dev/null || echo "No Bot logs"
                echo ""
                echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
                echo -e "${BLUE}Workers Logs:${NC}"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                tail -n 50 logs/workers.log 2>/dev/null || echo "No Workers logs"
            fi
        else
            echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${BLUE}API Logs (last 50 lines):${NC}"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            tail -n 50 logs/api.log 2>/dev/null || echo "No API logs"
            echo ""
            echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${BLUE}Bot Logs (last 50 lines):${NC}"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            tail -n 50 logs/bot.log 2>/dev/null || echo "No Bot logs"
            echo ""
            echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${BLUE}Workers Logs (last 50 lines):${NC}"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            tail -n 50 logs/workers.log 2>/dev/null || echo "No Workers logs"
        fi
        ;;
    *)
        echo "Usage: $0 [api|bot|workers|all] [--follow|-f]"
        echo ""
        echo "Examples:"
        echo "  $0 all              # Show last 50 lines of all services"
        echo "  $0 api --follow     # Follow API logs"
        echo "  $0 bot              # Show last 100 lines of bot logs"
        exit 1
        ;;
esac
