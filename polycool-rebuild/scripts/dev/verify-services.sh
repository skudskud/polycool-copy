#!/bin/bash
# Verify that all services are running and healthy
# Usage: ./scripts/dev/verify-services.sh
#
# This script ONLY verifies services - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔍 Verifying Polycool services status${NC}"
echo ""

ERRORS=0
WARNINGS=0

# Function to check service health
check_service_health() {
    local service_name=$1
    local health_url=$2
    local expected_status=${3:-200}

    echo -e "${BLUE}📋 Checking ${service_name}...${NC}"

    if curl -s -f -o /dev/null -w "%{http_code}" "$health_url" | grep -q "^${expected_status}$"; then
        echo -e "${GREEN}✅ ${service_name} is healthy (${health_url})${NC}"
        return 0
    else
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$health_url" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "000" ]; then
            echo -e "${RED}❌ ${service_name} is not reachable (${health_url})${NC}"
        else
            echo -e "${YELLOW}⚠️  ${service_name} returned HTTP ${HTTP_CODE} (expected ${expected_status})${NC}"
        fi
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

# Function to check if a process is running
check_process() {
    local service_name=$1
    local pid_file="logs/${service_name}.pid"

    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ ${service_name} process is running (PID: ${PID})${NC}"
            return 0
        else
            echo -e "${YELLOW}⚠️  ${service_name} PID file exists but process is not running${NC}"
            WARNINGS=$((WARNINGS + 1))
            return 1
        fi
    else
        echo -e "${YELLOW}⚠️  ${service_name} PID file not found (may not be started via start-all.sh)${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# Function to check Redis connectivity
check_redis() {
    echo -e "${BLUE}📋 Checking Redis...${NC}"

    if command -v redis-cli >/dev/null 2>&1; then
        if redis-cli ping >/dev/null 2>&1; then
            echo -e "${GREEN}✅ Redis is accessible${NC}"

            # Check Redis info
            REDIS_INFO=$(redis-cli info server 2>/dev/null | grep "redis_version" | cut -d: -f2 | tr -d '\r\n' || echo "unknown")
            echo -e "${GREEN}   → Redis version: ${REDIS_INFO}${NC}"
            return 0
        else
            echo -e "${RED}❌ Redis is not accessible${NC}"
            ERRORS=$((ERRORS + 1))
            return 1
        fi
    else
        echo -e "${YELLOW}⚠️  redis-cli not found, skipping Redis check${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# Function to check database connectivity (read-only)
check_database() {
    echo -e "${BLUE}📋 Checking database connectivity...${NC}"

    # Load environment if available
    if [ -f ".env.local" ]; then
        set -a
        source .env.local 2>/dev/null || true
        set +a
    elif [ -f ".env" ]; then
        set -a
        source .env 2>/dev/null || true
        set +a
    fi

    if [ -z "$DATABASE_URL" ]; then
        echo -e "${YELLOW}⚠️  DATABASE_URL not set, skipping database check${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi

    # Try a simple read-only query
    if python3 -c "
import os
import sys
os.environ['DATABASE_URL'] = '${DATABASE_URL}'
try:
    from sqlalchemy import create_engine, text
    from urllib.parse import urlparse
    url = os.environ['DATABASE_URL']
    # Add psycopg driver if needed
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
        echo -e "${GREEN}✅ Database is accessible${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  Could not connect to database (may be normal if credentials are incorrect)${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# 1. Check Redis
check_redis
echo ""

# 2. Check Database (read-only)
check_database
echo ""

# 3. Check API Service
echo -e "${BLUE}📋 Checking API Service...${NC}"
API_URL="${API_URL:-http://localhost:8000}"

if check_service_health "API Service" "${API_URL}/health/live" 200; then
    # Try to get API info
    API_INFO=$(curl -s "${API_URL}/" 2>/dev/null || echo "{}")
    if echo "$API_INFO" | grep -q "status"; then
        echo -e "${GREEN}   → API root endpoint is responding${NC}"
    fi
else
    echo -e "${YELLOW}   → API may not be started yet${NC}"
    echo -e "${YELLOW}   → Start it with: ./scripts/dev/start-api.sh${NC}"
fi

# Check API process
check_process "api"
echo ""

# 4. Check Bot Service
echo -e "${BLUE}📋 Checking Bot Service...${NC}"
check_process "bot"

# Check if bot can reach API (indirect check via logs)
if [ -f "logs/bot.log" ]; then
    if grep -q "API service is healthy" logs/bot.log 2>/dev/null; then
        echo -e "${GREEN}   → Bot detected API service as healthy${NC}"
    elif grep -q "API service health check failed" logs/bot.log 2>/dev/null; then
        echo -e "${YELLOW}   → Bot had issues connecting to API (check logs)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
fi
echo ""

# 5. Check Workers Service
echo -e "${BLUE}📋 Checking Workers Service...${NC}"
check_process "workers"

# Check if workers started successfully (indirect check via logs)
if [ -f "logs/workers.log" ]; then
    if grep -q "Worker services running" logs/workers.log 2>/dev/null; then
        echo -e "${GREEN}   → Workers service started successfully${NC}"

        # Check which workers are enabled
        if grep -q "Streamer service launched" logs/workers.log 2>/dev/null; then
            echo -e "${GREEN}     → Streamer is running${NC}"
        fi
        if grep -q "TP/SL monitor launched" logs/workers.log 2>/dev/null; then
            echo -e "${GREEN}     → TP/SL monitor is running${NC}"
        fi
        if grep -q "Copy trading listener started" logs/workers.log 2>/dev/null; then
            echo -e "${GREEN}     → Copy trading listener is running${NC}"
        fi
        if grep -q "Poller services launched" logs/workers.log 2>/dev/null; then
            echo -e "${GREEN}     → Poller is running${NC}"
        fi
    fi
fi
echo ""

# 6. Check service dependencies
echo -e "${BLUE}📋 Checking service dependencies...${NC}"

# Check if API is accessible from bot's perspective
if check_service_health "API (from Bot perspective)" "${API_URL}/health/live" 200 >/dev/null 2>&1; then
    echo -e "${GREEN}✅ API is accessible (Bot can connect)${NC}"
else
    echo -e "${YELLOW}⚠️  API may not be accessible (Bot may have issues)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# Check Redis PubSub (if workers are running)
if [ -f "logs/workers.log" ] && grep -q "Redis PubSub connected" logs/workers.log 2>/dev/null; then
    echo -e "${GREEN}✅ Redis PubSub is connected (Workers)${NC}"
fi

echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📊 Service Verification Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ All services are running and healthy!${NC}"
    echo ""
    echo "🌐 Service URLs:"
    echo "   • API: ${API_URL}"
    echo "   • Health: ${API_URL}/health/live"
    echo "   • Docs: ${API_URL}/docs"
    echo ""
    echo "📋 Logs:"
    echo "   • API: tail -f logs/api.log"
    echo "   • Bot: tail -f logs/bot.log"
    echo "   • Workers: tail -f logs/workers.log"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Services have ${WARNINGS} warning(s) but no critical errors.${NC}"
    echo -e "${YELLOW}   Some services may not be fully operational.${NC}"
    exit 0
else
    echo -e "${RED}❌ Service verification found ${ERRORS} error(s) and ${WARNINGS} warning(s).${NC}"
    echo -e "${RED}   Please check the errors above and ensure all services are started.${NC}"
    echo ""
    echo "💡 To start all services:"
    echo "   ./scripts/dev/start-all.sh"
    exit 1
fi
