#!/bin/bash
# Test bot-API integration to verify handlers use APIClient
# Usage: ./scripts/dev/test-bot-api-integration.sh
#
# This script ONLY tests integration - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 Testing Bot-API Integration${NC}"
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

# Function to test API endpoint
test_api_endpoint() {
    local endpoint=$1
    local method=${2:-GET}
    local expected_status=${3:-200}
    local description=$4

    echo -e "${BLUE}📋 Testing: ${description}${NC}"

    if [ "$method" = "GET" ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${API_PREFIX}${endpoint}" 2>/dev/null || echo "000")
    else
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${API_URL}${API_PREFIX}${endpoint}" 2>/dev/null || echo "000")
    fi

    if [ "$HTTP_CODE" = "$expected_status" ] || [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}   ✅ ${endpoint} returned ${HTTP_CODE}${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        if [ "$HTTP_CODE" = "000" ]; then
            echo -e "${YELLOW}   ⚠️  ${endpoint} is not reachable (API may not be running)${NC}"
        else
            echo -e "${YELLOW}   ⚠️  ${endpoint} returned ${HTTP_CODE} (expected ${expected_status})${NC}"
        fi
        TESTS_FAILED=$((TESTS_FAILED + 1))
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# Function to check if handler uses APIClient
check_handler_uses_apiclient() {
    local handler_file=$1
    local handler_name=$2

    if [ ! -f "$handler_file" ]; then
        echo -e "${YELLOW}   ⚠️  Handler file not found: ${handler_file}${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi

    # Check for APIClient import/usage
    if grep -q "from core.services.api_client\|import.*APIClient\|get_api_client" "$handler_file"; then
        echo -e "${GREEN}   ✅ ${handler_name} uses APIClient${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        # Check if it's a placeholder handler
        if grep -q "To be implemented\|PLACEHOLDER\|placeholder" "$handler_file"; then
            echo -e "${YELLOW}   ⚠️  ${handler_name} is a placeholder (not implemented yet)${NC}"
            WARNINGS=$((WARNINGS + 1))
            return 1
        else
            echo -e "${RED}   ❌ ${handler_name} does NOT use APIClient${NC}"
            TESTS_FAILED=$((TESTS_FAILED + 1))
            ERRORS=$((ERRORS + 1))
            return 1
        fi
    fi
}

# Function to check logs for API calls
check_logs_for_api_calls() {
    local log_file=$1
    local service_name=$2

    if [ ! -f "$log_file" ]; then
        echo -e "${YELLOW}   ⚠️  Log file not found: ${log_file} (service may not be running)${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi

    # Check for API calls in logs
    if grep -q "${API_URL}${API_PREFIX}\|API request\|api_client\|APIClient" "$log_file" 2>/dev/null; then
        echo -e "${GREEN}   ✅ ${service_name} logs show API calls${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${YELLOW}   ⚠️  ${service_name} logs do not show API calls (may not have made requests yet)${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi
}

# 1. Check API is running
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}1. Checking API Service${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if curl -s -f "${API_URL}/health/live" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ API is running at ${API_URL}${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${RED}❌ API is not running at ${API_URL}${NC}"
    echo -e "${YELLOW}   → Start API with: ./scripts/dev/start-api.sh${NC}"
    ERRORS=$((ERRORS + 1))
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
echo ""

# 2. Test API endpoints
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}2. Testing API Endpoints${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Health endpoint
test_api_endpoint "/health/live" "GET" "200" "Health check endpoint"

# Root endpoint
test_api_endpoint "/" "GET" "200" "Root endpoint"

# API endpoints (these may require authentication, so 401/404 is acceptable)
test_api_endpoint "/users/me" "GET" "200|401|404" "Users endpoint"
test_api_endpoint "/positions" "GET" "200|401|404" "Positions endpoint"
test_api_endpoint "/markets" "GET" "200|401|404" "Markets endpoint"

echo ""

# 3. Check handlers use APIClient
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}3. Verifying Handlers Use APIClient${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Start handler
check_handler_uses_apiclient "telegram_bot/bot/handlers/start_handler.py" "Start Handler"

# Wallet handler
check_handler_uses_apiclient "telegram_bot/bot/handlers/wallet_handler.py" "Wallet Handler"
check_handler_uses_apiclient "telegram_bot/handlers/wallet/view.py" "Wallet View Handler"

# Positions handler
check_handler_uses_apiclient "telegram_bot/bot/handlers/positions_handler.py" "Positions Handler"
check_handler_uses_apiclient "telegram_bot/bot/handlers/positions/refresh_handler.py" "Positions Refresh Handler"
check_handler_uses_apiclient "telegram_bot/bot/handlers/positions/sell_handler.py" "Positions Sell Handler"
check_handler_uses_apiclient "telegram_bot/bot/handlers/positions/tpsl_handler.py" "Positions TP/SL Handler"

# Markets handler
check_handler_uses_apiclient "telegram_bot/bot/handlers/markets_handler.py" "Markets Handler"
check_handler_uses_apiclient "telegram_bot/bot/handlers/markets/categories.py" "Markets Categories Handler"
check_handler_uses_apiclient "telegram_bot/bot/handlers/markets/search.py" "Markets Search Handler"
check_handler_uses_apiclient "telegram_bot/bot/handlers/markets/trading.py" "Markets Trading Handler"

# Smart trading handler
check_handler_uses_apiclient "telegram_bot/handlers/smart_trading/view_handler.py" "Smart Trading View Handler"
check_handler_uses_apiclient "telegram_bot/handlers/smart_trading/callbacks.py" "Smart Trading Callbacks Handler"

# Copy trading handlers
check_handler_uses_apiclient "telegram_bot/handlers/copy_trading/budget_flow.py" "Copy Trading Budget Flow Handler"
check_handler_uses_apiclient "telegram_bot/handlers/copy_trading/helpers.py" "Copy Trading Helpers"

# Referral handler
check_handler_uses_apiclient "telegram_bot/bot/handlers/referral_handler.py" "Referral Handler"

echo ""

# 4. Check logs for API calls
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}4. Checking Logs for API Calls${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_logs_for_api_calls "logs/bot.log" "Bot Service"
check_logs_for_api_calls "logs/api.log" "API Service"

echo ""

# 5. Check for direct DB access in handlers (should not exist when SKIP_DB=true)
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}5. Checking for Direct DB Access in Handlers${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Find handlers that might have direct DB access (without SKIP_DB check)
HANDLER_FILES=$(find telegram_bot/bot/handlers telegram_bot/handlers -name "*.py" -type f 2>/dev/null | grep -v __pycache__ || true)

DB_ACCESS_FOUND=0
for handler_file in $HANDLER_FILES; do
    if [ -f "$handler_file" ]; then
        # Check for get_db() calls that are not protected by SKIP_DB check
        if grep -q "get_db()" "$handler_file" 2>/dev/null; then
            # Check if it's protected by SKIP_DB check
            if ! grep -A 5 -B 5 "get_db()" "$handler_file" 2>/dev/null | grep -q "SKIP_DB\|skip_db\|if.*not.*SKIP_DB"; then
                echo -e "${YELLOW}   ⚠️  ${handler_file} has direct DB access without SKIP_DB check${NC}"
                DB_ACCESS_FOUND=$((DB_ACCESS_FOUND + 1))
                WARNINGS=$((WARNINGS + 1))
            fi
        fi
    fi
done

if [ $DB_ACCESS_FOUND -eq 0 ]; then
    echo -e "${GREEN}✅ No unprotected direct DB access found in handlers${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo -e "${YELLOW}⚠️  Found ${DB_ACCESS_FOUND} handler(s) with potential direct DB access${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
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
    echo -e "${GREEN}✅ All integration tests passed!${NC}"
    echo -e "${GREEN}   Bot handlers are properly integrated with API service.${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Some tests failed but no critical errors.${NC}"
    echo -e "${YELLOW}   Review the warnings above.${NC}"
    exit 0
else
    echo -e "${RED}❌ Integration tests found ${ERRORS} error(s).${NC}"
    echo -e "${RED}   Please review the errors above.${NC}"
    exit 1
fi
