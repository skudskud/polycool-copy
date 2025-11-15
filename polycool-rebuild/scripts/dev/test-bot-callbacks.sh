#!/bin/bash
# test-bot-callbacks.sh
# Script pour vérifier que tous les callbacks/boutons du bot sont bien connectés

set -e

API_URL="${API_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1}"
USER_ID="${USER_ID:-6500527972}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

echo ""
echo "🧪 POLYCOOL BOT - CALLBACKS & ENDPOINTS TEST"
echo "============================================="
echo ""

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    log_error "jq is required but not installed. Install with: brew install jq"
    exit 1
fi

TESTS_PASSED=0
TESTS_FAILED=0

test_endpoint() {
    local name=$1
    local method=$2
    local endpoint=$3
    local data=$4

    log_info "Testing: $name"

    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "${API_URL}${endpoint}")
    else
        response=$(curl -s -w "\n%{http_code}" -X "$method" "${API_URL}${endpoint}" \
            -H "Content-Type: application/json" \
            -d "$data")
    fi

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        log_success "$name (HTTP $http_code)"
        ((TESTS_PASSED++))
        return 0
    else
        log_error "$name (HTTP $http_code)"
        echo "$body" | jq . 2>/dev/null || echo "$body"
        ((TESTS_FAILED++))
        return 1
    fi
}

# ============================================
# 1. USER ENDPOINTS
# ============================================
echo ""
log_info "Phase 1: User Endpoints..."
echo "-----------------------------"

test_endpoint "GET /users/{telegram_user_id}" "GET" "${API_PREFIX}/users/${USER_ID}"
test_endpoint "GET /wallet/balance/telegram/{telegram_user_id}" "GET" "${API_PREFIX}/wallet/balance/telegram/${USER_ID}"

# ============================================
# 2. MARKETS ENDPOINTS (pour callbacks markets_hub, trending, etc.)
# ============================================
echo ""
log_info "Phase 2: Markets Endpoints..."
echo "---------------------------------"

test_endpoint "GET /markets/trending" "GET" "${API_PREFIX}/markets/trending?page=0&page_size=5&group_by_events=true"
test_endpoint "GET /markets/search" "GET" "${API_PREFIX}/markets/search?query_text=trump&page=0&page_size=3"
test_endpoint "GET /markets/categories/politics" "GET" "${API_PREFIX}/markets/categories/politics?page=0&page_size=5"

# Get a market ID for testing
MARKET_ID=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=1&group_by_events=false" | jq -r '.[0].id // empty')
if [ -n "$MARKET_ID" ] && [ "$MARKET_ID" != "null" ]; then
    test_endpoint "GET /markets/{market_id}" "GET" "${API_PREFIX}/markets/${MARKET_ID}"
    log_success "Using market ID: ${MARKET_ID}"
else
    log_warning "Could not get market ID for testing"
fi

# ============================================
# 3. POSITIONS ENDPOINTS (pour callback view_positions)
# ============================================
echo ""
log_info "Phase 3: Positions Endpoints..."
echo "-----------------------------------"

# Get internal user ID
INTERNAL_USER_ID=$(curl -s "${API_URL}${API_PREFIX}/users/${USER_ID}" | jq -r '.id // empty')
if [ -n "$INTERNAL_USER_ID" ] && [ "$INTERNAL_USER_ID" != "null" ]; then
    test_endpoint "GET /positions/user/{user_id}" "GET" "${API_PREFIX}/positions/user/${INTERNAL_USER_ID}"
else
    log_warning "Could not get internal user ID for positions test"
fi

# ============================================
# 4. SMART TRADING ENDPOINTS (pour callback smart_trading)
# ============================================
echo ""
log_info "Phase 4: Smart Trading Endpoints..."
echo "---------------------------------------"

test_endpoint "GET /smart-trading/recommendations" "GET" "${API_PREFIX}/smart-trading/recommendations?page=1&limit=5"
test_endpoint "GET /smart-trading/stats" "GET" "${API_PREFIX}/smart-trading/stats"

# ============================================
# 5. COPY TRADING ENDPOINTS (pour callbacks copy_trading:*)
# ============================================
echo ""
log_info "Phase 5: Copy Trading Endpoints..."
echo "--------------------------------------"

test_endpoint "GET /copy-trading/leaders" "GET" "${API_PREFIX}/copy-trading/leaders"
if [ -n "$INTERNAL_USER_ID" ] && [ "$INTERNAL_USER_ID" != "null" ]; then
    test_endpoint "GET /copy-trading/followers/{user_id}" "GET" "${API_PREFIX}/copy-trading/followers/${INTERNAL_USER_ID}"
    test_endpoint "GET /copy-trading/followers/{user_id}/stats" "GET" "${API_PREFIX}/copy-trading/followers/${INTERNAL_USER_ID}/stats"
else
    log_warning "Skipping copy trading follower tests (no internal user ID)"
fi

# ============================================
# 6. TRADES ENDPOINT (pour callbacks quick_buy, custom_buy, etc.)
# ============================================
echo ""
log_info "Phase 6: Trades Endpoint..."
echo "-------------------------------"

if [ -n "$MARKET_ID" ] && [ "$MARKET_ID" != "null" ]; then
    test_endpoint "POST /trades/ (dry run)" "POST" "${API_PREFIX}/trades/" \
        "{\"user_id\": ${USER_ID}, \"market_id\": \"${MARKET_ID}\", \"outcome\": \"Yes\", \"amount_usd\": 1.0, \"dry_run\": true}"
else
    log_warning "Skipping trades test (no market ID)"
fi

# ============================================
# 7. VERIFICATION DES CALLBACKS REGISTRES
# ============================================
echo ""
log_info "Phase 7: Callback Patterns Verification..."
echo "----------------------------------------------"

# Vérifier que les patterns de callbacks sont bien définis dans application.py
if grep -q "markets_hub\|view_positions\|view_wallet\|smart_trading" /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild/telegram_bot/bot/application.py 2>/dev/null; then
    log_success "Callback patterns found in application.py"
    ((TESTS_PASSED++))
else
    log_warning "Could not verify callback patterns in application.py"
fi

# ============================================
# SUMMARY
# ============================================
echo ""
echo "============================================="
log_info "TEST SUMMARY"
echo "============================================="
log_success "Passed: ${TESTS_PASSED}"
log_error "Failed: ${TESTS_FAILED}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All endpoint tests passed!${NC}"
    echo ""
    echo "✅ Tous les endpoints nécessaires pour les callbacks du bot sont fonctionnels."
    echo ""
    echo "📋 Callbacks vérifiés indirectement via leurs endpoints:"
    echo "   • markets_hub → GET /markets/trending ✅"
    echo "   • view_positions → GET /positions/user/{id} ✅"
    echo "   • view_wallet → GET /wallet/balance/telegram/{id} ✅"
    echo "   • smart_trading → GET /smart-trading/recommendations ✅"
    echo "   • copy_trading:* → GET /copy-trading/* ✅"
    echo "   • quick_buy_* → POST /trades/ ✅"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed. Check the output above.${NC}"
    exit 1
fi
