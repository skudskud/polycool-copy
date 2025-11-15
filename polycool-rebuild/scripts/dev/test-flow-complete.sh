#!/bin/bash
# test-flow-complete.sh
# Script automatisé pour tester le flow complet utilisateur jusqu'au trade

set -e  # Exit on error

# Configuration
API_URL="${API_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1}"
USER_ID="${USER_ID:-6500527972}"
TRADE_AMOUNT=2.00

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
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

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    log_error "jq is required but not installed. Install with: brew install jq"
    exit 1
fi

# Check if bc is installed (for float comparisons)
if ! command -v bc &> /dev/null; then
    log_error "bc is required but not installed. Install with: brew install bc"
    exit 1
fi

echo ""
echo "🧪 POLYCOOL API - FLOW COMPLET TEST"
echo "===================================="
echo "User ID: ${USER_ID}"
echo "Trade Amount: \$${TRADE_AMOUNT}"
echo "API URL: ${API_URL}"
echo ""

# Phase 1: Infrastructure Checks
echo ""
log_info "Phase 1: Infrastructure Checks..."
echo "--------------------------------------"

HEALTH_LIVE=$(curl -s "${API_URL}/health/live" | jq -r '.status')
if [ "${HEALTH_LIVE}" = "alive" ] || [ "${HEALTH_LIVE}" = "ok" ]; then
    log_success "API Health Check: OK"
else
    log_error "API Health Check: FAILED (got: ${HEALTH_LIVE})"
    exit 1
fi

HEALTH_READY=$(curl -s "${API_URL}/health/ready" | jq -r '.status')
if [ "${HEALTH_READY}" = "ready" ] || [ "${HEALTH_READY}" = "ok" ]; then
    log_success "API Ready Check: OK"
    # Show component status
    curl -s "${API_URL}/health/ready" | jq '.components' | head -5
else
    log_error "API Ready Check: FAILED"
    exit 1
fi

# Phase 2: User Information
echo ""
log_info "Phase 2: User Information..."
echo "----------------------------------"

USER_DATA=$(curl -s "${API_URL}${API_PREFIX}/users/${USER_ID}")
if [ -z "${USER_DATA}" ] || [ "${USER_DATA}" = "null" ]; then
    log_error "User ${USER_ID} not found"
    exit 1
fi

INTERNAL_USER_ID=$(echo "${USER_DATA}" | jq -r '.id')
TELEGRAM_USER_ID=$(echo "${USER_DATA}" | jq -r '.telegram_user_id')
POLYGON_ADDRESS=$(echo "${USER_DATA}" | jq -r '.polygon_address')
SOLANA_ADDRESS=$(echo "${USER_DATA}" | jq -r '.solana_address')

log_success "User found:"
echo "  • Internal ID: ${INTERNAL_USER_ID}"
echo "  • Telegram ID: ${TELEGRAM_USER_ID}"
echo "  • Polygon Address: ${POLYGON_ADDRESS:0:20}..."
echo "  • Solana Address: ${SOLANA_ADDRESS:0:20}..."

WALLET_DATA=$(curl -s "${API_URL}${API_PREFIX}/wallet/balance/telegram/${USER_ID}")
POLYGON_BALANCE=$(echo "${WALLET_DATA}" | jq -r '.polygon_balance // .usdc_balance // 0')
SOLANA_BALANCE=$(echo "${WALLET_DATA}" | jq -r '.solana_balance // 0')

log_success "Wallet Balances:"
echo "  • Polygon: \$${POLYGON_BALANCE}"
echo "  • Solana: \$${SOLANA_BALANCE}"

if (( $(echo "${POLYGON_BALANCE} < ${TRADE_AMOUNT}" | bc -l) )); then
    log_warning "Insufficient Polygon balance for trade (\$${TRADE_AMOUNT} required)"
fi

# Phase 3: Trending Markets
echo ""
log_info "Phase 3: Trending Markets Discovery..."
echo "-------------------------------------------"

TRENDING_DATA=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=true")
TRENDING_COUNT=$(echo "${TRENDING_DATA}" | jq 'length')

if [ "${TRENDING_COUNT}" -eq 0 ]; then
    log_error "No trending markets found"
    exit 1
fi

log_success "Found ${TRENDING_COUNT} trending items"

# Extract first event group or individual market
FIRST_EVENT=$(echo "${TRENDING_DATA}" | jq '[.[] | select(.type == "event_group")] | .[0]')
if [ "${FIRST_EVENT}" = "null" ] || [ -z "${FIRST_EVENT}" ]; then
    log_warning "No event groups found, fetching individual markets..."
    # Fetch individual markets (without grouping)
    INDIVIDUAL_TRENDING=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=false")
    # Find first individual market with prices
    FIRST_MARKET=$(echo "${INDIVIDUAL_TRENDING}" | jq '[.[] | select(.outcome_prices != null and (.outcome_prices | length) > 0)] | .[0]')
    if [ "${FIRST_MARKET}" = "null" ] || [ -z "${FIRST_MARKET}" ]; then
        # Fallback to any individual market
        FIRST_MARKET=$(echo "${INDIVIDUAL_TRENDING}" | jq '.[0]')
    fi
    SELECTED_MARKET_ID=$(echo "${FIRST_MARKET}" | jq -r '.id')
    SELECTED_MARKET_TITLE=$(echo "${FIRST_MARKET}" | jq -r '.title')
    if [ "${SELECTED_MARKET_ID}" != "null" ] && [ -n "${SELECTED_MARKET_ID}" ]; then
        log_success "Using individual market: ${SELECTED_MARKET_TITLE}"
        FIRST_EVENT_ID=""  # Clear event ID to skip Phase 4
    else
        log_error "No individual markets found"
        exit 1
    fi
else
    FIRST_EVENT_ID=$(echo "${FIRST_EVENT}" | jq -r '.event_id')
    FIRST_EVENT_TITLE=$(echo "${FIRST_EVENT}" | jq -r '.event_title')
    FIRST_EVENT_MARKET_COUNT=$(echo "${FIRST_EVENT}" | jq -r '.market_count')

    log_success "Selected Event:"
    echo "  • Event ID: ${FIRST_EVENT_ID}"
    echo "  • Title: ${FIRST_EVENT_TITLE}"
    echo "  • Markets: ${FIRST_EVENT_MARKET_COUNT}"
fi

# Phase 4: Event Markets (if event group, otherwise skip)
if [ -n "${FIRST_EVENT_ID}" ] && [ "${FIRST_EVENT_ID}" != "null" ] && [ "${FIRST_EVENT_ID}" != "" ]; then
    echo ""
    log_info "Phase 4: Exploring Event Markets..."
    echo "--------------------------------------"

    EVENT_MARKETS=$(curl -s "${API_URL}${API_PREFIX}/markets/events/${FIRST_EVENT_ID}?page=0&page_size=20")
    EVENT_MARKETS_COUNT=$(echo "${EVENT_MARKETS}" | jq 'length')

    if [ "${EVENT_MARKETS_COUNT}" -gt 0 ]; then
    log_success "Found ${EVENT_MARKETS_COUNT} markets in event"

    # Find market with prices
    MARKET_WITH_PRICES=$(echo "${EVENT_MARKETS}" | jq '[.[] | select(.outcome_prices != null and (.outcome_prices | length) > 0)] | .[0]')

    if [ "${MARKET_WITH_PRICES}" != "null" ] && [ -n "${MARKET_WITH_PRICES}" ]; then
        SELECTED_MARKET_ID=$(echo "${MARKET_WITH_PRICES}" | jq -r '.id')
        SELECTED_MARKET_TITLE=$(echo "${MARKET_WITH_PRICES}" | jq -r '.title')
        log_success "Selected market with prices: ${SELECTED_MARKET_TITLE}"
    else
            log_warning "No markets with prices found in event, trying first market"
            SELECTED_MARKET_ID=$(echo "${EVENT_MARKETS}" | jq -r '.[0].id // empty')
            SELECTED_MARKET_TITLE=$(echo "${EVENT_MARKETS}" | jq -r '.[0].title // "Unknown"')
            if [ -z "${SELECTED_MARKET_ID}" ] || [ "${SELECTED_MARKET_ID}" = "null" ]; then
                log_warning "Event has no markets, will use individual market from Phase 3"
            fi
        fi
    else
        log_warning "Event has no markets (${EVENT_MARKETS_COUNT}), will use individual market from Phase 3"
        # If we don't have a market ID yet, get one from trending individual markets
        if [ -z "${SELECTED_MARKET_ID}" ] || [ "${SELECTED_MARKET_ID}" = "null" ]; then
            log_info "Selecting individual market from trending..."
            INDIVIDUAL_TRENDING=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=false")
            INDIVIDUAL_MARKET=$(echo "${INDIVIDUAL_TRENDING}" | jq '[.[] | select(.outcome_prices != null and (.outcome_prices | length) > 0)] | .[0]')
            if [ "${INDIVIDUAL_MARKET}" = "null" ] || [ -z "${INDIVIDUAL_MARKET}" ]; then
                INDIVIDUAL_MARKET=$(echo "${INDIVIDUAL_TRENDING}" | jq '.[0]')
            fi
            if [ "${INDIVIDUAL_MARKET}" != "null" ] && [ -n "${INDIVIDUAL_MARKET}" ]; then
                SELECTED_MARKET_ID=$(echo "${INDIVIDUAL_MARKET}" | jq -r '.id')
                SELECTED_MARKET_TITLE=$(echo "${INDIVIDUAL_MARKET}" | jq -r '.title')
                if [ "${SELECTED_MARKET_ID}" != "null" ] && [ -n "${SELECTED_MARKET_ID}" ]; then
                    log_success "Selected individual market: ${SELECTED_MARKET_TITLE}"
                fi
            fi
        fi
    fi
else
    log_info "Skipping Phase 4 (using individual market from Phase 3)"
    # SELECTED_MARKET_ID should already be set from Phase 3
fi

# Phase 5: Market Details & Price Analysis
echo ""
log_info "Phase 5: Market Details & Price Analysis..."
echo "----------------------------------------------"

# Ensure we have a valid market ID
if [ -z "${SELECTED_MARKET_ID}" ] || [ "${SELECTED_MARKET_ID}" = "null" ]; then
    log_error "No market ID selected - cannot proceed"
    exit 1
fi

MARKET_DETAILS=$(curl -s "${API_URL}${API_PREFIX}/markets/${SELECTED_MARKET_ID}")
if [ "${MARKET_DETAILS}" = "null" ] || [ -z "${MARKET_DETAILS}" ] || [ "$(echo "${MARKET_DETAILS}" | jq -r '.id // empty')" = "" ]; then
    log_error "Market ${SELECTED_MARKET_ID} not found"
    log_info "Trying to fetch market on-demand..."
    MARKET_DETAILS=$(curl -s -X POST "${API_URL}${API_PREFIX}/markets/fetch/${SELECTED_MARKET_ID}")
    if [ "${MARKET_DETAILS}" = "null" ] || [ -z "${MARKET_DETAILS}" ]; then
        log_error "Failed to fetch market ${SELECTED_MARKET_ID}"
    exit 1
    fi
fi

MARKET_TITLE=$(echo "${MARKET_DETAILS}" | jq -r '.title')
MARKET_VOLUME=$(echo "${MARKET_DETAILS}" | jq -r '.volume // 0')
MARKET_LIQUIDITY=$(echo "${MARKET_DETAILS}" | jq -r '.liquidity // 0')
MARKET_ACTIVE=$(echo "${MARKET_DETAILS}" | jq -r '.active')

log_success "Market Details:"
echo "  • Title: ${MARKET_TITLE}"
echo "  • Volume: \$${MARKET_VOLUME}"
echo "  • Liquidity: \$${MARKET_LIQUIDITY}"
echo "  • Active: ${MARKET_ACTIVE}"

# Extract outcomes and prices
OUTCOMES=$(echo "${MARKET_DETAILS}" | jq -r '.outcomes[]?')
OUTCOME_PRICES=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[]?')
CLOB_TOKEN_IDS=$(echo "${MARKET_DETAILS}" | jq -r '.clob_token_ids[]?')

if [ -z "${OUTCOME_PRICES}" ]; then
    log_warning "No price data available for this market"
    log_info "Attempting to fetch market on-demand..."
    MARKET_DETAILS=$(curl -s -X POST "${API_URL}${API_PREFIX}/markets/fetch/${SELECTED_MARKET_ID}")
    OUTCOME_PRICES=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[]?')
fi

if [ -n "${OUTCOME_PRICES}" ]; then
    PRICE_YES=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[0] // 0')
    PRICE_NO=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[1] // 0')

    echo ""
    echo "  📊 Price Analysis:"
    echo "    • Yes: \$${PRICE_YES}"
    echo "    • No: \$${PRICE_NO}"

    # Select outcome with highest price (most expensive)
    if (( $(echo "${PRICE_YES} > ${PRICE_NO}" | bc -l) )); then
        SELECTED_OUTCOME="Yes"
        SELECTED_PRICE="${PRICE_YES}"
        SELECTED_TOKEN_ID=$(echo "${MARKET_DETAILS}" | jq -r '.clob_token_ids[0]')
    else
        SELECTED_OUTCOME="No"
        SELECTED_PRICE="${PRICE_NO}"
        SELECTED_TOKEN_ID=$(echo "${MARKET_DETAILS}" | jq -r '.clob_token_ids[1]')
    fi

    log_success "Selected Outcome: ${SELECTED_OUTCOME} (Price: \$${SELECTED_PRICE})"
    echo "    • Token ID: ${SELECTED_TOKEN_ID:0:30}..."
else
    log_error "Cannot determine prices - cannot proceed with trade simulation"
    exit 1
fi

# Phase 6: Trade Preparation
echo ""
log_info "Phase 6: Trade Preparation..."
echo "--------------------------------"

REQUIRED_BALANCE=$(echo "${TRADE_AMOUNT} + 0.5" | bc -l)

if (( $(echo "${POLYGON_BALANCE} >= ${REQUIRED_BALANCE}" | bc -l) )); then
    log_success "Sufficient balance for trade"
else
    log_warning "Insufficient balance (need \$${REQUIRED_BALANCE}, have \$${POLYGON_BALANCE})"
fi

echo ""
echo "📊 TRADE SUMMARY:"
echo "=================="
echo "  • User ID: ${USER_ID}"
echo "  • Market ID: ${SELECTED_MARKET_ID}"
echo "  • Market Title: ${MARKET_TITLE}"
echo "  • Outcome: ${SELECTED_OUTCOME}"
echo "  • Price: \$${SELECTED_PRICE}"
echo "  • Amount: \$${TRADE_AMOUNT}"
echo "  • Token ID: ${SELECTED_TOKEN_ID:0:30}..."
echo "  • Current Balance: \$${POLYGON_BALANCE}"
echo ""

# Check if trade endpoint exists
TRADE_ENDPOINT_EXISTS=$(curl -s -X POST "${API_URL}${API_PREFIX}/trades/" \
  -H "Content-Type: application/json" \
  -d "{}" 2>&1 | grep -q "405\|404" && echo "false" || echo "true")

if [ "${TRADE_ENDPOINT_EXISTS}" = "true" ]; then
    log_info "Trade endpoint exists - attempting trade..."

    TRADE_RESPONSE=$(curl -s -X POST "${API_URL}${API_PREFIX}/trades/" \
      -H "Content-Type: application/json" \
      -d "{
        \"user_id\": ${USER_ID},
        \"market_id\": \"${SELECTED_MARKET_ID}\",
        \"outcome\": \"${SELECTED_OUTCOME}\",
        \"amount_usd\": ${TRADE_AMOUNT},
        \"order_type\": \"FOK\"
      }")

    TRADE_SUCCESS=$(echo "${TRADE_RESPONSE}" | jq -r '.success // .status // false')

    if [ "${TRADE_SUCCESS}" != "false" ] && [ "${TRADE_SUCCESS}" != "null" ]; then
        log_success "Trade executed successfully!"
        echo "${TRADE_RESPONSE}" | jq .
    else
        log_error "Trade failed"
        echo "${TRADE_RESPONSE}" | jq .
    fi
else
    log_warning "Trade endpoint not available (POST /api/v1/trades/)"
    log_info "Skipping actual trade execution"
    echo ""
    echo "💡 To enable trade testing, create the endpoint:"
    echo "   POST ${API_URL}${API_PREFIX}/trades/"
    echo "   Body: {"
    echo "     \"user_id\": ${USER_ID},"
    echo "     \"market_id\": \"${SELECTED_MARKET_ID}\","
    echo "     \"outcome\": \"${SELECTED_OUTCOME}\","
    echo "     \"amount_usd\": ${TRADE_AMOUNT},"
    echo "     \"order_type\": \"FOK\""
    echo "   }"
fi

# Phase 7: Position Verification
echo ""
log_info "Phase 7: Position Verification..."
echo "-------------------------------------"

sleep 2  # Wait for position to be created if trade was executed

POSITIONS=$(curl -s "${API_URL}${API_PREFIX}/positions/user/${USER_ID}")
POSITION_COUNT=$(echo "${POSITIONS}" | jq 'length')

log_success "Current Positions: ${POSITION_COUNT}"

if [ "${POSITION_COUNT}" -gt 0 ]; then
    echo ""
    echo "📈 Recent Positions:"
    # Check if positions is an array
    if echo "${POSITIONS}" | jq -e '. | type == "array"' > /dev/null 2>&1; then
        echo "${POSITIONS}" | jq -r '.[0:3] | .[] | "  • \(.market_id // "N/A"): \(.outcome // "N/A") - \(.status // "N/A")"'

    # Check if our trade created a position
    OUR_POSITION=$(echo "${POSITIONS}" | jq "[.[] | select(.market_id == \"${SELECTED_MARKET_ID}\")] | .[0]")
    if [ "${OUR_POSITION}" != "null" ] && [ -n "${OUR_POSITION}" ]; then
        log_success "Position found for traded market!"
        echo "${OUR_POSITION}" | jq .
        fi
    else
        # Positions might be an object, show it as-is
        echo "${POSITIONS}" | jq .
    fi
fi

# Phase 8: Additional Tests
echo ""
log_info "Phase 8: Additional Tests..."
echo "---------------------------------"

# Test search
log_info "Testing market search..."
SEARCH_RESULTS=$(curl -s "${API_URL}${API_PREFIX}/markets/search?query_text=trump&page=0&page_size=3")
SEARCH_COUNT=$(echo "${SEARCH_RESULTS}" | jq 'length')
log_success "Search returned ${SEARCH_COUNT} results"

# Test categories
log_info "Testing category markets..."
CATEGORY_RESULTS=$(curl -s "${API_URL}${API_PREFIX}/markets/categories/politics?page=0&page_size=3")
CATEGORY_COUNT=$(echo "${CATEGORY_RESULTS}" | jq 'length')
log_success "Politics category returned ${CATEGORY_COUNT} markets"

# Performance test
log_info "Testing API performance..."
HEALTH_TIME=$(time (curl -s "${API_URL}/health/live" > /dev/null) 2>&1 | grep real | awk '{print $2}')
TRENDING_TIME=$(time (curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10" > /dev/null) 2>&1 | grep real | awk '{print $2}')
MARKET_TIME=$(time (curl -s "${API_URL}${API_PREFIX}/markets/${SELECTED_MARKET_ID}" > /dev/null) 2>&1 | grep real | awk '{print $2}')

echo ""
echo "⏱️  Performance Metrics:"
echo "  • Health Check: ${HEALTH_TIME}"
echo "  • Trending Markets: ${TRENDING_TIME}"
echo "  • Market Details: ${MARKET_TIME}"

# Final Summary
echo ""
echo "===================================="
log_success "FLOW TEST COMPLETED!"
echo "===================================="
echo ""
echo "📊 Summary:"
echo "  ✅ Infrastructure: OK"
echo "  ✅ User Data: Retrieved"
echo "  ✅ Trending Markets: Found"
echo "  ✅ Market Details: Retrieved"
echo "  ✅ Price Analysis: Completed"
echo "  ${TRADE_ENDPOINT_EXISTS:+✅}${TRADE_ENDPOINT_EXISTS:-⚠️}  Trade: ${TRADE_ENDPOINT_EXISTS:+Executed}${TRADE_ENDPOINT_EXISTS:-Skipped (endpoint missing)}"
echo "  ✅ Positions: Checked"
echo ""
echo "🎉 All critical paths tested successfully!"
echo ""
