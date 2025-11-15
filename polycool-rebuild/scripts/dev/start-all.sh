#!/bin/bash
# Start all services (API, Bot, Workers) for local testing
# Usage: ./scripts/dev/start-all.sh

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🚀 Starting all Polycool services for local testing${NC}"
echo ""

# Check if tmux is available
if command -v tmux >/dev/null 2>&1; then
    USE_TMUX=true
    echo -e "${GREEN}✅ tmux detected - will use separate panes${NC}"
else
    USE_TMUX=false
    echo -e "${YELLOW}⚠️  tmux not found - will start services in background${NC}"
fi

# Create logs directory
mkdir -p logs

# Check if Redis is running
if ! redis-cli ping >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Redis is not running. Starting Redis...${NC}"
    if command -v docker >/dev/null 2>&1; then
        # Try docker-compose.local.yml first, then docker-compose.yml
        if [ -f "docker-compose.local.yml" ]; then
            docker compose -f docker-compose.local.yml up -d redis 2>/dev/null || \
            docker compose up -d redis 2>/dev/null || \
            echo -e "${RED}❌ Failed to start Redis${NC}"
        else
            docker compose up -d redis 2>/dev/null || \
            echo -e "${RED}❌ Failed to start Redis${NC}"
        fi
        sleep 2
    else
        echo -e "${RED}❌ Redis is not running and Docker is not available${NC}"
        exit 1
    fi
fi

# Function to start service in tmux pane
start_service_tmux() {
    local service_name=$1
    local script_path=$2

    if tmux has-session -t polycool-local 2>/dev/null; then
        tmux new-window -t polycool-local -n "$service_name" "bash $script_path"
    else
        tmux new-session -d -s polycool-local -n "$service_name" "bash $script_path"
    fi
}

# Function to start service in background
start_service_bg() {
    local service_name=$1
    local script_path=$2
    local log_file="logs/${service_name}.log"

    echo -e "${BLUE}📦 Starting ${service_name} in background...${NC}"
    nohup bash "$script_path" > "$log_file" 2>&1 &
    echo $! > "logs/${service_name}.pid"
    echo -e "${GREEN}✅ ${service_name} started (PID: $(cat logs/${service_name}.pid))${NC}"
}

# Start services
if [ "$USE_TMUX" = true ]; then
    echo -e "${BLUE}📦 Starting services in tmux session 'polycool-local'...${NC}"

    # Start API
    start_service_tmux "api" "scripts/dev/start-api.sh"
    sleep 3

    # Start Bot
    start_service_tmux "bot" "scripts/dev/start-bot.sh"
    sleep 2

    # Start Workers
    start_service_tmux "workers" "scripts/dev/start-workers.sh"

    echo ""
    echo -e "${GREEN}✅ All services started in tmux session 'polycool-local'${NC}"
    echo ""
    echo "📊 Commands:"
    echo "   • Attach to session: ${BLUE}tmux attach -t polycool-local${NC}"
    echo "   • List windows: ${BLUE}tmux list-windows -t polycool-local${NC}"
    echo "   • Switch windows: ${BLUE}Ctrl+B + 0-2${NC}"
    echo "   • Detach: ${BLUE}Ctrl+B + D${NC}"
    echo "   • Kill session: ${BLUE}tmux kill-session -t polycool-local${NC}"
    echo ""
    echo "🌐 Services:"
    echo "   • API: http://localhost:8000"
    echo "   • Health: http://localhost:8000/health/live"
    echo "   • Docs: http://localhost:8000/docs"
    echo ""
    echo "📋 Logs (Filtered - no poller spam):"
    echo "   • Filtered monitoring: ${BLUE}./scripts/dev/monitor-filtered.sh${NC}"
    echo "   • Summary view: ${BLUE}./scripts/dev/monitor-summary.sh${NC}"
    echo ""

    # Attach to session
    read -p "Attach to tmux session now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        tmux attach -t polycool-local
    fi
else
    echo -e "${BLUE}📦 Starting services in background...${NC}"

    # Start API
    start_service_bg "api" "scripts/dev/start-api.sh"
    sleep 5

    # Wait for API to be ready
    echo -e "${YELLOW}⏳ Waiting for API to be ready...${NC}"
    for i in {1..30}; do
        if curl -s -f http://localhost:8000/health/live >/dev/null 2>&1; then
            echo -e "${GREEN}✅ API is ready${NC}"
            break
        fi
        sleep 1
    done

    # Start Bot
    start_service_bg "bot" "scripts/dev/start-bot.sh"
    sleep 2

    # Start Workers
    start_service_bg "workers" "scripts/dev/start-workers.sh"

    echo ""
    echo -e "${GREEN}✅ All services started in background${NC}"
    echo ""
    echo "📊 Services:"
    echo "   • API: http://localhost:8000"
    echo "   • Health: http://localhost:8000/health/live"
    echo "   • Docs: http://localhost:8000/docs"
    echo ""
    echo "📋 Logs (Filtered - no poller spam):"
    echo "   • Filtered monitoring: ${BLUE}./scripts/dev/monitor-filtered.sh${NC}"
    echo "   • Summary view: ${BLUE}./scripts/dev/monitor-summary.sh${NC}"
    echo "   • All logs (verbose): ${BLUE}./scripts/dev/monitor-all.sh${NC}"
    echo ""
    echo "   • Individual logs:"
    echo "     - API: ${BLUE}tail -f logs/api.log${NC}"
    echo "     - Bot: ${BLUE}tail -f logs/bot.log${NC}"
    echo "     - Workers: ${BLUE}tail -f logs/workers.log${NC}"
    echo ""
    echo "🛑 To stop all services: ${BLUE}./scripts/dev/stop-all.sh${NC}"
fi
