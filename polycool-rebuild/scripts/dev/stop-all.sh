#!/bin/bash
# Stop all services (API, Bot, Workers)
# Usage: ./scripts/dev/stop-all.sh

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}🛑 Stopping all Polycool services...${NC}"
echo ""

# Stop tmux session if it exists
if tmux has-session -t polycool-local 2>/dev/null; then
    echo -e "${YELLOW}📦 Stopping tmux session 'polycool-local'...${NC}"
    tmux kill-session -t polycool-local 2>/dev/null || true
    echo -e "${GREEN}✅ Tmux session stopped${NC}"
fi

# Stop background processes
for service in api bot workers; do
    pid_file="logs/${service}.pid"
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}🛑 Stopping ${service} (PID: ${pid})...${NC}"
            kill "$pid" 2>/dev/null || true
            sleep 1
            # Force kill if still running
            if ps -p "$pid" > /dev/null 2>&1; then
                kill -9 "$pid" 2>/dev/null || true
            fi
            rm -f "$pid_file"
            echo -e "${GREEN}✅ ${service} stopped${NC}"
        else
            rm -f "$pid_file"
        fi
    fi
done

# Kill any remaining Python processes running our scripts
echo -e "${YELLOW}🧹 Cleaning up remaining processes...${NC}"
pkill -f "python.*api_only.py" 2>/dev/null || true
pkill -f "python.*bot_only.py" 2>/dev/null || true
pkill -f "python.*workers.py" 2>/dev/null || true

# Wait a bit for processes to terminate
sleep 2

echo ""
echo -e "${GREEN}✅ All services stopped${NC}"
