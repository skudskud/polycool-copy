#!/bin/bash
# Test workers functionality (poller, websocket, copy trading listener, TP/SL monitor)
# Usage: ./scripts/dev/test-workers.sh
#
# This script ONLY tests workers - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 Testing Workers Functionality${NC}"
echo ""

ERRORS=0
WARNINGS=0
TESTS_PASSED=0
TESTS_FAILED=0

# Load environment
if [ -f ".env.local" ]; then
    set -a
    source .env.local 2>/dev/null || true
    set +a
elif [ -f ".env" ]; then
    set -a
    source .env 2>/dev/null || true
    set +a
fi

# Function to check worker in logs
check_worker_in_logs() {
    local worker_name=$1
    local log_file=$2
    local success_pattern=$3
    local error_pattern=${4:-"error\|failed\|exception"}

    echo -e "${BLUE}📋 Checking ${worker_name}...${NC}"

    if [ ! -f "$log_file" ]; then
        echo -e "${YELLOW}   ⚠️  Log file not found: ${log_file}${NC}"
        echo -e "${YELLOW}      → Workers service may not be running${NC}"
        echo -e "${YELLOW}      → Start with: ./scripts/dev/start-workers.sh${NC}"
        WARNINGS=$((WARNINGS + 1))
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi

    # Check for success pattern
    if grep -q "$success_pattern" "$log_file" 2>/dev/null; then
        echo -e "${GREEN}   ✅ ${worker_name} started successfully${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Check for errors
        if grep -i "$error_pattern" "$log_file" 2>/dev/null | grep -v "INFO\|DEBUG" | head -5; then
            echo -e "${YELLOW}   ⚠️  ${worker_name} has some errors in logs (check above)${NC}"
            WARNINGS=$((WARNINGS + 1))
        fi

        return 0
    else
        echo -e "${YELLOW}   ⚠️  ${worker_name} success pattern not found in logs${NC}"
        WARNINGS=$((WARNINGS + 1))
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Function to check if worker process is running
check_worker_process() {
    local worker_name=$1
    local pid_file="logs/workers.pid"

    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${GREEN}   ✅ Workers process is running (PID: ${PID})${NC}"
            TESTS_PASSED=$((TESTS_PASSED + 1))
            return 0
        else
            echo -e "${YELLOW}   ⚠️  Workers PID file exists but process is not running${NC}"
            WARNINGS=$((WARNINGS + 1))
            return 1
        fi
    else
        echo -e "${YELLOW}   ⚠️  Workers PID file not found (may not be started via start-all.sh)${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# Function to check Redis PubSub
check_redis_pubsub() {
    echo -e "${BLUE}📋 Checking Redis PubSub...${NC}"

    if ! command -v redis-cli >/dev/null 2>&1; then
        echo -e "${YELLOW}   ⚠️  redis-cli not found, skipping PubSub check${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi

    REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
    REDIS_HOST="${REDIS_URL#*://}"
    REDIS_HOST="${REDIS_HOST%%:*}"
    REDIS_PORT="${REDIS_URL#*:}"
    REDIS_PORT="${REDIS_PORT#*:}"
    REDIS_PORT="${REDIS_PORT%%/*}"

    if [ -z "$REDIS_PORT" ] || [ "$REDIS_PORT" = "$REDIS_HOST" ]; then
        REDIS_PORT=6379
    fi

    if redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" ping >/dev/null 2>&1; then
        echo -e "${GREEN}   ✅ Redis is accessible for PubSub${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Check PubSub channels (if any)
        PUBSUB_CHANNELS=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" PUBSUB CHANNELS 2>/dev/null || echo "")
        if [ -n "$PUBSUB_CHANNELS" ]; then
            echo -e "${GREEN}   ✅ Active PubSub channels found${NC}"
            echo "$PUBSUB_CHANNELS" | while read -r channel; do
                if [ -n "$channel" ]; then
                    echo -e "${BLUE}      → Channel: ${channel}${NC}"
                fi
            done
        else
            echo -e "${YELLOW}   ⚠️  No active PubSub channels (may be normal if no events)${NC}"
        fi

        return 0
    else
        echo -e "${RED}   ❌ Redis is not accessible${NC}"
        ERRORS=$((ERRORS + 1))
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# 1. Check workers process
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}1. Workers Process${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_worker_process
echo ""

# 2. Check Poller
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}2. Poller Service${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_worker_in_logs "Poller" "logs/workers.log" "Poller services launched\|poller.*started\|DiscoveryPoller\|EventsPoller\|PricePoller"
echo ""

# 3. Check WebSocket Streamer
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}3. WebSocket Streamer${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_worker_in_logs "Streamer" "logs/workers.log" "Streamer service launched\|StreamerService\|WebSocket.*connected\|websocket.*connected"
echo ""

# 4. Check Copy Trading Listener
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}4. Copy Trading Listener${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_worker_in_logs "Copy Trading Listener" "logs/workers.log" "Copy trading listener started\|CopyTradingListener\|copy.*trading.*listener"
echo ""

# 5. Check TP/SL Monitor
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}5. TP/SL Monitor${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_worker_in_logs "TP/SL Monitor" "logs/workers.log" "TP/SL monitor launched\|TPSLMonitor\|tpsl.*monitor"
echo ""

# 6. Check Watched Addresses Sync
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}6. Watched Addresses Sync${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_worker_in_logs "Watched Addresses Sync" "logs/workers.log" "watched.*addresses\|WatchedAddressesManager\|cache refreshed"
echo ""

# 7. Check Redis PubSub
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}7. Redis PubSub${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_redis_pubsub
echo ""

# 8. Check database connectivity (workers need DB access)
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}8. Database Connectivity (for Workers)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ -n "$DATABASE_URL" ]; then
    echo -e "${BLUE}📋 Testing database connection...${NC}"

    if python3 -c "
import os
import sys
os.environ['DATABASE_URL'] = '${DATABASE_URL}'
try:
    from sqlalchemy import create_engine, text
    url = os.environ['DATABASE_URL']
    if not url.startswith('postgresql+'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
        url = url.replace('postgres://', 'postgresql+psycopg://', 1)
    engine = create_engine(url, connect_args={'connect_timeout': 5})
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        result.fetchone()
    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
" 2>/dev/null | grep -q "SUCCESS"; then
        echo -e "${GREEN}   ✅ Database is accessible${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${YELLOW}   ⚠️  Could not connect to database${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}   ⚠️  DATABASE_URL not set${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 9. Check worker configuration
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}9. Worker Configuration${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Checking worker configuration...${NC}"

# Check SKIP_DB (should be false for workers)
if [ "${SKIP_DB:-false}" = "false" ]; then
    echo -e "${GREEN}   ✅ SKIP_DB=false (workers have DB access)${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}   ❌ SKIP_DB=true (workers need DB access)${NC}"
    ERRORS=$((ERRORS + 1))
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

# Check feature flags
if [ "${STREAMER_ENABLED:-true}" = "true" ]; then
    echo -e "${GREEN}   ✅ STREAMER_ENABLED=true${NC}"
else
    echo -e "${YELLOW}   ⚠️  STREAMER_ENABLED=false (streamer disabled)${NC}"
fi

if [ "${POLLER_ENABLED:-true}" = "true" ]; then
    echo -e "${GREEN}   ✅ POLLER_ENABLED=true${NC}"
else
    echo -e "${YELLOW}   ⚠️  POLLER_ENABLED=false (poller disabled)${NC}"
fi

if [ "${TPSL_MONITORING_ENABLED:-true}" = "true" ]; then
    echo -e "${GREEN}   ✅ TPSL_MONITORING_ENABLED=true${NC}"
else
    echo -e "${YELLOW}   ⚠️  TPSL_MONITORING_ENABLED=false (TP/SL monitor disabled)${NC}"
fi

echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📊 Test Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "Tests Passed: ${GREEN}${TESTS_PASSED}${NC}"
echo -e "Tests Failed: ${RED}${TESTS_FAILED}${NC}"
echo -e "Warnings: ${YELLOW}${WARNINGS}${NC}"
echo -e "Errors: ${RED}${ERRORS}${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All worker tests passed!${NC}"
    echo -e "${GREEN}   All workers are running correctly.${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Some worker tests have warnings but no critical errors.${NC}"
    echo -e "${YELLOW}   Review the warnings above.${NC}"
    echo ""
    echo "💡 To start workers:"
    echo "   ./scripts/dev/start-workers.sh"
    exit 0
else
    echo -e "${RED}❌ Worker tests found ${ERRORS} error(s).${NC}"
    echo -e "${RED}   Please review the errors above.${NC}"
    echo ""
    echo "💡 To start workers:"
    echo "   ./scripts/dev/start-workers.sh"
    exit 1
fi
