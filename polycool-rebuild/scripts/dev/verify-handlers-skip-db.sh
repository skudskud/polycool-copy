#!/bin/bash
# Verify that all handlers respect SKIP_DB (no direct DB access without check)
# Usage: ./scripts/dev/verify-handlers-skip-db.sh
#
# This script ONLY verifies handlers - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔍 Verifying Handlers Respect SKIP_DB${NC}"
echo ""

ERRORS=0
WARNINGS=0
HANDLERS_CHECKED=0
HANDLERS_OK=0
HANDLERS_ISSUES=0

# Function to check a handler file
check_handler_file() {
    local handler_file=$1
    local handler_name=$2

    HANDLERS_CHECKED=$((HANDLERS_CHECKED + 1))

    if [ ! -f "$handler_file" ]; then
        return 0  # File doesn't exist, skip
    fi

    # Check for direct DB access patterns
    local has_db_access=false
    local has_skip_db_check=false
    local has_apiclient=false
    local issues=()

    # Patterns that indicate DB access
    if grep -q "get_db()\|from core.database\|async_session_factory\|SessionLocal\|db.execute\|db.query" "$handler_file" 2>/dev/null; then
        has_db_access=true
    fi

    # Patterns that indicate SKIP_DB check
    if grep -q "SKIP_DB\|skip_db\|os.getenv.*SKIP_DB\|if.*not.*SKIP_DB\|if.*SKIP_DB" "$handler_file" 2>/dev/null; then
        has_skip_db_check=true
    fi

    # Patterns that indicate APIClient usage
    if grep -q "from core.services.api_client\|import.*APIClient\|get_api_client\|api_client\." "$handler_file" 2>/dev/null; then
        has_apiclient=true
    fi

    # Analyze the handler
    if [ "$has_db_access" = true ]; then
        if [ "$has_skip_db_check" = true ]; then
            # DB access is protected by SKIP_DB check - OK
            echo -e "${GREEN}   ✅ ${handler_name}${NC}"
            echo -e "${GREEN}      → Has DB access but protected by SKIP_DB check${NC}"
            HANDLERS_OK=$((HANDLERS_OK + 1))
        else
            # DB access without SKIP_DB check - ISSUE
            echo -e "${RED}   ❌ ${handler_name}${NC}"
            echo -e "${RED}      → Has direct DB access without SKIP_DB check${NC}"
            issues+=("Direct DB access without SKIP_DB check")
            HANDLERS_ISSUES=$((HANDLERS_ISSUES + 1))
            ERRORS=$((ERRORS + 1))
        fi
    elif [ "$has_apiclient" = true ]; then
        # Uses APIClient - OK
        echo -e "${GREEN}   ✅ ${handler_name}${NC}"
        echo -e "${GREEN}      → Uses APIClient (no direct DB access)${NC}"
        HANDLERS_OK=$((HANDLERS_OK + 1))
    else
        # No DB access, no APIClient - might be placeholder or simple handler
        if grep -q "To be implemented\|PLACEHOLDER\|placeholder\|pass\|return" "$handler_file" 2>/dev/null; then
            echo -e "${YELLOW}   ⚠️  ${handler_name}${NC}"
            echo -e "${YELLOW}      → Placeholder handler (not implemented)${NC}"
            WARNINGS=$((WARNINGS + 1))
        else
            echo -e "${GREEN}   ✅ ${handler_name}${NC}"
            echo -e "${GREEN}      → No DB access (simple handler)${NC}"
            HANDLERS_OK=$((HANDLERS_OK + 1))
        fi
    fi

    # Show issues if any
    if [ ${#issues[@]} -gt 0 ]; then
        for issue in "${issues[@]}"; do
            echo -e "${RED}      → Issue: ${issue}${NC}"
        done
    fi
}

# Find all handler files
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Scanning Handler Files${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Main handlers
echo -e "${BLUE}📋 Main Handlers${NC}"
check_handler_file "telegram_bot/bot/handlers/start_handler.py" "Start Handler"
check_handler_file "telegram_bot/bot/handlers/wallet_handler.py" "Wallet Handler"
check_handler_file "telegram_bot/bot/handlers/positions_handler.py" "Positions Handler"
check_handler_file "telegram_bot/bot/handlers/markets_handler.py" "Markets Handler"
check_handler_file "telegram_bot/bot/handlers/referral_handler.py" "Referral Handler"
check_handler_file "telegram_bot/bot/handlers/admin_handler.py" "Admin Handler"
echo ""

# Positions sub-handlers
echo -e "${BLUE}📋 Positions Sub-Handlers${NC}"
check_handler_file "telegram_bot/bot/handlers/positions/refresh_handler.py" "Positions Refresh Handler"
check_handler_file "telegram_bot/bot/handlers/positions/sell_handler.py" "Positions Sell Handler"
check_handler_file "telegram_bot/bot/handlers/positions/tpsl_handler.py" "Positions TP/SL Handler"
echo ""

# Markets sub-handlers
echo -e "${BLUE}📋 Markets Sub-Handlers${NC}"
check_handler_file "telegram_bot/bot/handlers/markets/categories.py" "Markets Categories Handler"
check_handler_file "telegram_bot/bot/handlers/markets/search.py" "Markets Search Handler"
check_handler_file "telegram_bot/bot/handlers/markets/trading.py" "Markets Trading Handler"
echo ""

# Smart Trading handlers
echo -e "${BLUE}📋 Smart Trading Handlers${NC}"
check_handler_file "telegram_bot/handlers/smart_trading/view_handler.py" "Smart Trading View Handler"
check_handler_file "telegram_bot/handlers/smart_trading/callbacks.py" "Smart Trading Callbacks Handler"
echo ""

# Copy Trading handlers
echo -e "${BLUE}📋 Copy Trading Handlers${NC}"
check_handler_file "telegram_bot/handlers/copy_trading/budget_flow.py" "Copy Trading Budget Flow Handler"
check_handler_file "telegram_bot/handlers/copy_trading/helpers.py" "Copy Trading Helpers"
check_handler_file "telegram_bot/handlers/copy_trading/main.py" "Copy Trading Main Handler"
echo ""

# Wallet handlers
echo -e "${BLUE}📋 Wallet Handlers${NC}"
check_handler_file "telegram_bot/handlers/wallet/view.py" "Wallet View Handler"
echo ""

# Check for any handlers with unprotected DB access
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Detailed Analysis${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Find handlers with get_db() calls
echo -e "${BLUE}📋 Handlers with get_db() calls${NC}"
HANDLER_FILES=$(find telegram_bot/bot/handlers telegram_bot/handlers -name "*.py" -type f 2>/dev/null | grep -v __pycache__ || true)

UNPROTECTED_DB_ACCESS=0
for handler_file in $HANDLER_FILES; do
    if [ -f "$handler_file" ] && grep -q "get_db()" "$handler_file" 2>/dev/null; then
        # Check if it's protected
        if ! grep -A 10 -B 10 "get_db()" "$handler_file" 2>/dev/null | grep -q "SKIP_DB\|skip_db\|if.*not.*SKIP_DB\|if.*SKIP_DB"; then
            echo -e "${RED}   ❌ ${handler_file}${NC}"
            echo -e "${RED}      → Unprotected get_db() call${NC}"
            UNPROTECTED_DB_ACCESS=$((UNPROTECTED_DB_ACCESS + 1))
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

if [ $UNPROTECTED_DB_ACCESS -eq 0 ]; then
    echo -e "${GREEN}   ✅ No unprotected get_db() calls found${NC}"
else
    echo -e "${RED}   ❌ Found ${UNPROTECTED_DB_ACCESS} handler(s) with unprotected DB access${NC}"
fi
echo ""

# Check for direct database imports
echo -e "${BLUE}📋 Handlers with direct database imports${NC}"
DIRECT_DB_IMPORTS=0
for handler_file in $HANDLER_FILES; do
    if [ -f "$handler_file" ]; then
        if grep -q "from core.database.connection import\|from core.database import\|import.*get_db" "$handler_file" 2>/dev/null; then
            # Check if it's protected
            if ! grep -q "SKIP_DB\|skip_db" "$handler_file" 2>/dev/null; then
                echo -e "${YELLOW}   ⚠️  ${handler_file}${NC}"
                echo -e "${YELLOW}      → Direct database import without SKIP_DB check${NC}"
                DIRECT_DB_IMPORTS=$((DIRECT_DB_IMPORTS + 1))
                WARNINGS=$((WARNINGS + 1))
            fi
        fi
    fi
done

if [ $DIRECT_DB_IMPORTS -eq 0 ]; then
    echo -e "${GREEN}   ✅ No unprotected database imports found${NC}"
else
    echo -e "${YELLOW}   ⚠️  Found ${DIRECT_DB_IMPORTS} handler(s) with direct database imports${NC}"
fi
echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📊 Verification Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "Handlers Checked: ${BLUE}${HANDLERS_CHECKED}${NC}"
echo -e "Handlers OK: ${GREEN}${HANDLERS_OK}${NC}"
echo -e "Handlers with Issues: ${RED}${HANDLERS_ISSUES}${NC}"
echo -e "Warnings: ${YELLOW}${WARNINGS}${NC}"
echo -e "Errors: ${RED}${ERRORS}${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $HANDLERS_ISSUES -eq 0 ]; then
    echo -e "${GREEN}✅ All handlers respect SKIP_DB!${NC}"
    echo -e "${GREEN}   No unprotected direct DB access found.${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Some handlers have warnings but no critical errors.${NC}"
    echo -e "${YELLOW}   Review the warnings above.${NC}"
    exit 0
else
    echo -e "${RED}❌ Verification found ${ERRORS} error(s).${NC}"
    echo -e "${RED}   Some handlers have unprotected DB access.${NC}"
    echo -e "${RED}   These handlers should use APIClient when SKIP_DB=true.${NC}"
    exit 1
fi
