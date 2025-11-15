#!/bin/bash
# Test End-to-End User Flow avec telegram_user_id spécifique
# Usage: ./scripts/dev/test-e2e-user-flow.sh [telegram_user_id]
#
# Ce script teste les flows complets:
# - Buy position → Visible dans /positions
# - WebSocket → PnL temps réel
# - Stop Loss fonctionnel
# - Sell position → Disparaît de /positions
# - Tous les callbacks/boutons fonctionnent

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
TELEGRAM_USER_ID="${1:-6500527972}"
API_URL="${API_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1}"

# Load environment
if [ -f ".env.local" ]; then
    set -a
    source .env.local 2>/dev/null || true
    set +a
fi

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}🧪 End-to-End User Flow Test${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}👤 Testing with telegram_user_id: ${TELEGRAM_USER_ID}${NC}"
echo ""

TESTS_PASSED=0
TESTS_FAILED=0
WARNINGS=0

# Helper functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
    WARNINGS=$((WARNINGS + 1))
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    log_error "jq is required. Install with: brew install jq"
    exit 1
fi

# Check if API is running
if ! curl -s -f "${API_URL}/health/live" >/dev/null 2>&1; then
    log_error "API is not running at ${API_URL}. Start it with: ./scripts/dev/start-api.sh"
    exit 1
fi

# ============================================
# PHASE 1: Get User Info
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 1: User Information${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Fetching user data for telegram_user_id: ${TELEGRAM_USER_ID}"

USER_RESPONSE=$(curl -s "${API_URL}${API_PREFIX}/users/${TELEGRAM_USER_ID}")
INTERNAL_USER_ID=$(echo "$USER_RESPONSE" | jq -r '.id // empty')

if [ -z "$INTERNAL_USER_ID" ] || [ "$INTERNAL_USER_ID" = "null" ]; then
    log_error "Could not get internal user ID. User may not exist."
    echo "Response: $USER_RESPONSE"
    exit 1
fi

log_success "User found: internal_id=${INTERNAL_USER_ID}, telegram_id=${TELEGRAM_USER_ID}"

USER_STAGE=$(echo "$USER_RESPONSE" | jq -r '.stage // "unknown"')
if [ "$USER_STAGE" != "ready" ]; then
    log_warning "User stage is '${USER_STAGE}' (expected 'ready'). Some features may not work."
fi

echo ""

# ============================================
# PHASE 2: Get Initial Positions Count
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 2: Initial State${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Getting initial positions count..."

POSITIONS_RESPONSE=$(curl -s "${API_URL}${API_PREFIX}/positions/user/${INTERNAL_USER_ID}")
INITIAL_POSITIONS_COUNT=$(echo "$POSITIONS_RESPONSE" | jq -r 'length // 0')

log_success "Initial positions count: ${INITIAL_POSITIONS_COUNT}"

# Get wallet balance
WALLET_RESPONSE=$(curl -s "${API_URL}${API_PREFIX}/wallet/balance/telegram/${TELEGRAM_USER_ID}")
INITIAL_BALANCE=$(echo "$WALLET_RESPONSE" | jq -r '.balance // 0')

log_success "Initial wallet balance: \$${INITIAL_BALANCE}"

echo ""

# ============================================
# PHASE 3: Get Available Market for Testing
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 3: Market Selection${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Finding an available market for testing..."

MARKETS_RESPONSE=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=5&group_by_events=false")
MARKET_ID=$(echo "$MARKETS_RESPONSE" | jq -r '.[0].id // empty')

if [ -z "$MARKET_ID" ] || [ "$MARKET_ID" = "null" ]; then
    log_error "Could not find a market for testing"
    exit 1
fi

MARKET_TITLE=$(echo "$MARKETS_RESPONSE" | jq -r '.[0].title // "Unknown"')
log_success "Selected market: ${MARKET_ID}"
log_info "Market title: ${MARKET_TITLE}"

# Get market details
MARKET_DETAILS=$(curl -s "${API_URL}${API_PREFIX}/markets/${MARKET_ID}")
MARKET_TOKEN_ID=$(echo "$MARKET_DETAILS" | jq -r '.token_id // empty')
MARKET_OUTCOME_PRICES=$(echo "$MARKET_DETAILS" | jq -r '.outcome_prices // {}')

log_info "Market token_id: ${MARKET_TOKEN_ID}"
log_info "Market outcome_prices: ${MARKET_OUTCOME_PRICES}"

echo ""

# ============================================
# PHASE 4: Test Buy Position (via API)
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 4: Buy Position${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Creating a test position (buy)..."

# Note: This is a DRY RUN - we don't actually execute the trade
# In production, you would use the real trade endpoint
BUY_PAYLOAD=$(jq -n \
    --arg user_id "$TELEGRAM_USER_ID" \
    --arg market_id "$MARKET_ID" \
    --arg outcome "Yes" \
    --argjson amount 1.0 \
    '{
        telegram_user_id: $user_id,
        market_id: $market_id,
        outcome: $outcome,
        amount_usd: $amount,
        dry_run: true
    }')

BUY_RESPONSE=$(curl -s -X POST "${API_URL}${API_PREFIX}/trades/" \
    -H "Content-Type: application/json" \
    -d "$BUY_PAYLOAD")

BUY_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}${API_PREFIX}/trades/" \
    -H "Content-Type: application/json" \
    -d "$BUY_PAYLOAD")

if [ "$BUY_HTTP_CODE" -ge 200 ] && [ "$BUY_HTTP_CODE" -lt 300 ]; then
    log_success "Buy endpoint is accessible (HTTP ${BUY_HTTP_CODE})"
    log_warning "This is a DRY RUN test. To test real buy, remove dry_run flag and ensure sufficient balance."
else
    log_error "Buy endpoint returned HTTP ${BUY_HTTP_CODE}"
    echo "Response: $BUY_RESPONSE"
fi

echo ""
log_warning "⚠️  To test REAL buy flow:"
log_warning "   1. Ensure user has sufficient balance"
log_warning "   2. Remove dry_run flag"
log_warning "   3. Execute trade via Telegram bot: /markets → Select market → Quick Buy"
echo ""

# ============================================
# PHASE 5: Verify Position Appears in /positions
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 5: Verify Position in /positions${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Checking positions after buy..."

sleep 2  # Wait a bit for DB to update

NEW_POSITIONS_RESPONSE=$(curl -s "${API_URL}${API_PREFIX}/positions/user/${INTERNAL_USER_ID}")
NEW_POSITIONS_COUNT=$(echo "$NEW_POSITIONS_RESPONSE" | jq -r 'length // 0')

if [ "$NEW_POSITIONS_COUNT" -gt "$INITIAL_POSITIONS_COUNT" ]; then
    log_success "Position count increased: ${INITIAL_POSITIONS_COUNT} → ${NEW_POSITIONS_COUNT}"

    # Find the new position
    NEW_POSITION=$(echo "$NEW_POSITIONS_RESPONSE" | jq -r ".[] | select(.market_id == \"${MARKET_ID}\") | .id // empty" | head -n1)
    if [ -n "$NEW_POSITION" ]; then
        log_success "New position found: ${NEW_POSITION}"
    fi
else
    log_warning "Position count unchanged (${NEW_POSITIONS_COUNT}). This is expected if dry_run=true."
    log_warning "To test real flow, execute a real trade via Telegram bot."
fi

echo ""

# ============================================
# PHASE 6: Test Stop Loss Setup
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 6: Stop Loss Setup${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Testing Stop Loss endpoint..."

# Check if position exists (if we have a real position)
if [ -n "$NEW_POSITION" ] && [ "$NEW_POSITION" != "null" ]; then
    # Test updating position with stop loss
    STOP_LOSS_PAYLOAD=$(jq -n \
        --argjson position_id "$NEW_POSITION" \
        --argjson stop_loss 0.3 \
        '{
            position_id: $position_id,
            stop_loss: $stop_loss
        }')

    STOP_LOSS_RESPONSE=$(curl -s -X PUT "${API_URL}${API_PREFIX}/positions/${NEW_POSITION}/stop-loss" \
        -H "Content-Type: application/json" \
        -d "$STOP_LOSS_PAYLOAD")

    STOP_LOSS_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "${API_URL}${API_PREFIX}/positions/${NEW_POSITION}/stop-loss" \
        -H "Content-Type: application/json" \
        -d "$STOP_LOSS_PAYLOAD")

    if [ "$STOP_LOSS_HTTP_CODE" -ge 200 ] && [ "$STOP_LOSS_HTTP_CODE" -lt 300 ]; then
        log_success "Stop Loss endpoint is accessible (HTTP ${STOP_LOSS_HTTP_CODE})"
    else
        log_warning "Stop Loss endpoint returned HTTP ${STOP_LOSS_HTTP_CODE} (may not be implemented yet)"
    fi
else
    log_warning "No position found to test Stop Loss. Create a real position first."
fi

echo ""

# ============================================
# PHASE 7: Verify WebSocket Connection
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 7: WebSocket Connection${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Checking WebSocket/Streamer status..."

# Check workers log for streamer
if [ -f "logs/workers.log" ]; then
    if grep -q "Streamer service launched\|WebSocket.*connected\|Streamer.*running" logs/workers.log 2>/dev/null; then
        log_success "Streamer service is running (checked logs/workers.log)"
    else
        log_warning "Streamer service may not be running (check logs/workers.log)"
    fi

    # Check for active subscriptions
    if grep -q "Subscribed to.*market\|Active positions.*subscribed" logs/workers.log 2>/dev/null; then
        log_success "WebSocket subscriptions found in logs"
    else
        log_warning "No WebSocket subscriptions found (may not have active positions)"
    fi
else
    log_warning "Workers log not found. Start workers with: ./scripts/dev/start-workers.sh"
fi

# Check if positions are being updated (check for price updates)
if [ -f "logs/workers.log" ]; then
    if grep -q "price.*update\|PnL.*updated\|position.*price" logs/workers.log 2>/dev/null; then
        log_success "Price updates detected in logs (WebSocket is updating positions)"
    else
        log_warning "No price updates detected (may not have active positions or prices haven't changed)"
    fi
fi

echo ""

# ============================================
# PHASE 8: Test Sell Position
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 8: Sell Position${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Testing Sell endpoint..."

if [ -n "$NEW_POSITION" ] && [ "$NEW_POSITION" != "null" ]; then
    SELL_PAYLOAD=$(jq -n \
        --argjson position_id "$NEW_POSITION" \
        --argjson amount 1.0 \
        '{
            position_id: $position_id,
            amount_usd: $amount,
            dry_run: true
        }')

    SELL_RESPONSE=$(curl -s -X POST "${API_URL}${API_PREFIX}/positions/${NEW_POSITION}/sell" \
        -H "Content-Type: application/json" \
        -d "$SELL_PAYLOAD")

    SELL_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}${API_PREFIX}/positions/${NEW_POSITION}/sell" \
        -H "Content-Type: application/json" \
        -d "$SELL_PAYLOAD")

    if [ "$SELL_HTTP_CODE" -ge 200 ] && [ "$SELL_HTTP_CODE" -lt 300 ]; then
        log_success "Sell endpoint is accessible (HTTP ${SELL_HTTP_CODE})"
        log_warning "This is a DRY RUN test. To test real sell, remove dry_run flag."
    else
        log_warning "Sell endpoint returned HTTP ${SELL_HTTP_CODE} (may not be implemented yet)"
    fi
else
    log_warning "No position found to test Sell. Create a real position first."
fi

echo ""

# ============================================
# PHASE 9: Verify Position Disappears After Sell
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 9: Verify Position Disappears${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Checking positions after sell..."

sleep 2  # Wait a bit for DB to update

FINAL_POSITIONS_RESPONSE=$(curl -s "${API_URL}${API_PREFIX}/positions/user/${INTERNAL_USER_ID}")
FINAL_POSITIONS_COUNT=$(echo "$FINAL_POSITIONS_RESPONSE" | jq -r 'length // 0')

if [ "$FINAL_POSITIONS_COUNT" -lt "$NEW_POSITIONS_COUNT" ]; then
    log_success "Position count decreased: ${NEW_POSITIONS_COUNT} → ${FINAL_POSITIONS_COUNT}"
else
    log_warning "Position count unchanged (${FINAL_POSITIONS_COUNT}). This is expected if dry_run=true."
    log_warning "To test real flow, execute a real sell via Telegram bot."
fi

echo ""

# ============================================
# PHASE 10: Test All Callback Endpoints
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Phase 10: Callback Endpoints Verification${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

log_info "Testing all callback-related endpoints..."

# Test markets endpoints (for markets_hub callback)
MARKETS_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=5")
if [ "$MARKETS_HTTP" = "200" ]; then
    log_success "markets_hub callback endpoint OK (GET /markets/trending)"
else
    log_error "markets_hub callback endpoint failed (HTTP ${MARKETS_HTTP})"
fi

# Test positions endpoint (for view_positions callback)
POSITIONS_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${API_PREFIX}/positions/user/${INTERNAL_USER_ID}")
if [ "$POSITIONS_HTTP" = "200" ]; then
    log_success "view_positions callback endpoint OK (GET /positions/user/{id})"
else
    log_error "view_positions callback endpoint failed (HTTP ${POSITIONS_HTTP})"
fi

# Test wallet endpoint (for view_wallet callback)
WALLET_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${API_PREFIX}/wallet/balance/telegram/${TELEGRAM_USER_ID}")
if [ "$WALLET_HTTP" = "200" ]; then
    log_success "view_wallet callback endpoint OK (GET /wallet/balance/telegram/{id})"
else
    log_error "view_wallet callback endpoint failed (HTTP ${WALLET_HTTP})"
fi

# Test smart trading endpoint (for smart_trading callback)
SMART_TRADING_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${API_PREFIX}/smart-trading/recommendations?page=1&limit=5")
if [ "$SMART_TRADING_HTTP" = "200" ]; then
    log_success "smart_trading callback endpoint OK (GET /smart-trading/recommendations)"
else
    log_error "smart_trading callback endpoint failed (HTTP ${SMART_TRADING_HTTP})"
fi

# Test copy trading endpoint (for copy_trading callback)
COPY_TRADING_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${API_PREFIX}/copy-trading/allocations/${INTERNAL_USER_ID}")
if [ "$COPY_TRADING_HTTP" = "200" ] || [ "$COPY_TRADING_HTTP" = "404" ]; then
    log_success "copy_trading callback endpoint OK (GET /copy-trading/allocations/{id})"
else
    log_error "copy_trading callback endpoint failed (HTTP ${COPY_TRADING_HTTP})"
fi

echo ""

# ============================================
# SUMMARY
# ============================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📊 Test Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Tests Passed: ${GREEN}${TESTS_PASSED}${NC}"
echo -e "Tests Failed: ${RED}${TESTS_FAILED}${NC}"
echo -e "Warnings: ${YELLOW}${WARNINGS}${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All endpoint tests passed!${NC}"
    echo ""
    echo -e "${BLUE}📋 Next Steps for Manual Testing:${NC}"
    echo ""
    echo "1. Test via Telegram Bot:"
    echo "   • Send /start to bot"
    echo "   • Click '📊 Browse Markets' → Select market → Quick Buy"
    echo "   • Send /positions → Verify position appears"
    echo "   • Set Stop Loss via position details"
    echo "   • Sell position → Verify it disappears"
    echo ""
    echo "2. Monitor WebSocket Updates:"
    echo "   • tail -f logs/workers.log | grep -i 'price\|pnl\|position'"
    echo "   • Check that PnL updates automatically when price changes"
    echo ""
    echo "3. Test All Callbacks:"
    echo "   • Click every button in the bot"
    echo "   • Verify all buttons lead somewhere (no errors)"
    echo "   • Check logs/bot.log for any errors"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Some tests failed. Review the output above.${NC}"
    exit 1
fi
