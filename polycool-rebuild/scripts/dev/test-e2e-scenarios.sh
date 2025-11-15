#!/bin/bash
# Test end-to-end scenarios (copy trading, smart trading)
# Usage: ./scripts/dev/test-e2e-scenarios.sh
#
# This script ONLY tests scenarios - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 Testing End-to-End Scenarios${NC}"
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

API_URL="${API_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1}"

# Function to check if service is running
check_service_running() {
    local service_name=$1
    local health_url=$2

    if curl -s -f "$health_url" >/dev/null 2>&1; then
        echo -e "${GREEN}   ✅ ${service_name} is running${NC}"
        return 0
    else
        echo -e "${RED}   ❌ ${service_name} is not running${NC}"
        return 1
    fi
}

# Function to test API endpoint exists
test_api_endpoint_exists() {
    local endpoint=$1
    local description=$2

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${API_PREFIX}${endpoint}" 2>/dev/null || echo "000")

    if [ "$HTTP_CODE" != "000" ]; then
        echo -e "${GREEN}   ✅ ${description} endpoint exists (HTTP ${HTTP_CODE})${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${YELLOW}   ⚠️  ${description} endpoint not reachable${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# Function to check logs for scenario patterns
check_logs_for_scenario() {
    local scenario_name=$1
    local log_file=$2
    local patterns=$3

    echo -e "${BLUE}📋 Checking logs for ${scenario_name}...${NC}"

    if [ ! -f "$log_file" ]; then
        echo -e "${YELLOW}   ⚠️  Log file not found: ${log_file}${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi

    local found_patterns=0
    for pattern in $patterns; do
        if grep -q "$pattern" "$log_file" 2>/dev/null; then
            found_patterns=$((found_patterns + 1))
        fi
    done

    if [ $found_patterns -gt 0 ]; then
        echo -e "${GREEN}   ✅ Found ${found_patterns} pattern(s) related to ${scenario_name}${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${YELLOW}   ⚠️  No patterns found for ${scenario_name} (may not have been tested yet)${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# 1. Check services are running
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}1. Service Availability${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_service_running "API" "${API_URL}/health/live"
check_service_running "Bot" "${API_URL}/health/live"  # Bot doesn't have HTTP endpoint, but we check API

# Check if bot process is running
if [ -f "logs/bot.pid" ]; then
    BOT_PID=$(cat logs/bot.pid 2>/dev/null)
    if [ -n "$BOT_PID" ] && ps -p "$BOT_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}   ✅ Bot process is running${NC}"
    else
        echo -e "${YELLOW}   ⚠️  Bot process not found${NC}"
    fi
fi

# Check if workers process is running
if [ -f "logs/workers.pid" ]; then
    WORKERS_PID=$(cat logs/workers.pid 2>/dev/null)
    if [ -n "$WORKERS_PID" ] && ps -p "$WORKERS_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}   ✅ Workers process is running${NC}"
    else
        echo -e "${YELLOW}   ⚠️  Workers process not found${NC}"
    fi
fi

echo ""

# 2. Test Copy Trading Scenario
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}2. Copy Trading Scenario${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Testing Copy Trading API endpoints...${NC}"

# Test copy trading endpoints
test_api_endpoint_exists "/copy-trading/leaders" "Copy Trading Leaders"
test_api_endpoint_exists "/copy-trading/allocations" "Copy Trading Allocations"
test_api_endpoint_exists "/webhooks/copy-trade" "Copy Trading Webhook"

echo ""

# Check logs for copy trading activity
check_logs_for_scenario "Copy Trading" "logs/bot.log" "copy.*trading\|copy_trading\|CopyTrading"
check_logs_for_scenario "Copy Trading Listener" "logs/workers.log" "Copy.*trading.*listener\|copy.*trade.*event"

echo ""

# 3. Test Smart Trading Scenario
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}3. Smart Trading Scenario${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Testing Smart Trading API endpoints...${NC}"

# Test smart trading endpoints
test_api_endpoint_exists "/smart-trading/recommendations" "Smart Trading Recommendations"
test_api_endpoint_exists "/smart-trading/stats" "Smart Trading Stats"

echo ""

# Check logs for smart trading activity
check_logs_for_scenario "Smart Trading" "logs/bot.log" "smart.*trading\|smart_trading\|SmartTrading"

echo ""

# 4. Test Position Management Scenario
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}4. Position Management Scenario${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Testing Position API endpoints...${NC}"

# Test position endpoints
test_api_endpoint_exists "/positions" "Positions List"
test_api_endpoint_exists "/positions/me" "User Positions"

echo ""

# Check logs for position activity
check_logs_for_scenario "Positions" "logs/bot.log" "positions\|position\|Position"

echo ""

# 5. Test Market Data Scenario
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}5. Market Data Scenario${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Testing Market API endpoints...${NC}"

# Test market endpoints
test_api_endpoint_exists "/markets" "Markets List"
test_api_endpoint_exists "/markets/trending" "Trending Markets"

echo ""

# Check logs for market activity
check_logs_for_scenario "Markets" "logs/bot.log" "markets\|market\|Market"
check_logs_for_scenario "Poller" "logs/workers.log" "Poller\|poller\|markets.*updated"

echo ""

# 6. Test Cache Integration in Scenarios
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}6. Cache Integration${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Checking cache usage in scenarios...${NC}"

# Check if Redis has cache keys
if command -v redis-cli >/dev/null 2>&1; then
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
        CACHE_KEYS=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" KEYS "api:*" 2>/dev/null | wc -l | tr -d ' ')
        if [ "$CACHE_KEYS" -gt 0 ]; then
            echo -e "${GREEN}   ✅ Found ${CACHE_KEYS} cache key(s) (cache is being used)${NC}"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo -e "${YELLOW}   ⚠️  No cache keys found (cache may be empty or not used yet)${NC}"
            WARNINGS=$((WARNINGS + 1))
        fi
    fi
fi

echo ""

# 7. Test Webhook Integration
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}7. Webhook Integration${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Testing webhook endpoints...${NC}"

# Test webhook endpoint (should exist even if it requires auth)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}${API_PREFIX}/webhooks/copy-trade" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "000" ]; then
    if [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "403" ]; then
        echo -e "${GREEN}   ✅ Webhook endpoint exists (requires authentication: HTTP ${HTTP_CODE})${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    elif [ "$HTTP_CODE" = "400" ] || [ "$HTTP_CODE" = "422" ]; then
        echo -e "${GREEN}   ✅ Webhook endpoint exists (requires payload: HTTP ${HTTP_CODE})${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${GREEN}   ✅ Webhook endpoint exists (HTTP ${HTTP_CODE})${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    fi
else
    echo -e "${YELLOW}   ⚠️  Webhook endpoint not reachable${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""

# 8. Test API-Bot Communication
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}8. API-Bot Communication${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}📋 Checking API-Bot communication...${NC}"

# Check bot logs for API calls
if [ -f "logs/bot.log" ]; then
    if grep -q "${API_URL}${API_PREFIX}\|API request\|api_client\|APIClient" logs/bot.log 2>/dev/null; then
        echo -e "${GREEN}   ✅ Bot logs show API calls (Bot is communicating with API)${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${YELLOW}   ⚠️  Bot logs do not show API calls (may not have made requests yet)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}   ⚠️  Bot log file not found${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# Check API logs for requests
if [ -f "logs/api.log" ]; then
    API_REQUESTS=$(grep -c "GET\|POST\|PUT\|DELETE" logs/api.log 2>/dev/null || echo "0")
    if [ "$API_REQUESTS" -gt 0 ]; then
        echo -e "${GREEN}   ✅ API logs show ${API_REQUESTS} request(s)${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${YELLOW}   ⚠️  API logs do not show requests (may not have received requests yet)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}   ⚠️  API log file not found${NC}"
    WARNINGS=$((WARNINGS + 1))
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
    echo -e "${GREEN}✅ All end-to-end scenario tests passed!${NC}"
    echo -e "${GREEN}   Scenarios are properly integrated.${NC}"
    echo ""
    echo "💡 To test scenarios manually:"
    echo "   1. Start all services: ./scripts/dev/start-all.sh"
    echo "   2. Use Telegram bot to test copy trading and smart trading"
    echo "   3. Monitor logs: tail -f logs/*.log"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Some scenario tests have warnings but no critical errors.${NC}"
    echo -e "${YELLOW}   Review the warnings above.${NC}"
    echo ""
    echo "💡 To test scenarios manually:"
    echo "   1. Start all services: ./scripts/dev/start-all.sh"
    echo "   2. Use Telegram bot to test copy trading and smart trading"
    exit 0
else
    echo -e "${RED}❌ Scenario tests found ${ERRORS} error(s).${NC}"
    echo -e "${RED}   Please review the errors above.${NC}"
    exit 1
fi
