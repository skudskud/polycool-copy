#!/bin/bash
# Diagnostic script for bot issues
# Usage: ./scripts/dev/diagnose-bot.sh

set +e  # Don't exit on errors, we want to show all diagnostics

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}🔍 Bot Diagnostic Tool${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Load environment
if [ -f ".env.local" ]; then
    set -a
    source .env.local 2>/dev/null || true
    set +a
fi

ISSUES=0

# 1. Check if bot process is running
echo -e "${BLUE}1. Checking bot process...${NC}"
BOT_PID=$(ps aux | grep -E "python.*bot_only|bot_only.py" | grep -v grep | awk '{print $2}' | head -1)
if [ -n "$BOT_PID" ]; then
    echo -e "${GREEN}✅ Bot process found (PID: $BOT_PID)${NC}"
else
    echo -e "${RED}❌ Bot process not running${NC}"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# 2. Check bot token
echo -e "${BLUE}2. Checking bot token...${NC}"
TOKEN="${TELEGRAM_BOT_TOKEN:-$BOT_TOKEN}"
if [ -n "$TOKEN" ]; then
    TOKEN_PREFIX="${TOKEN:0:10}..."
    echo -e "${GREEN}✅ Bot token found: ${TOKEN_PREFIX}${NC}"

    # Test token validity
    echo -e "${YELLOW}   Testing token validity...${NC}"
    RESPONSE=$(curl -s --max-time 5 "https://api.telegram.org/bot${TOKEN}/getMe" 2>/dev/null || echo "ERROR")
    if echo "$RESPONSE" | grep -q '"ok":true'; then
        BOT_USERNAME=$(echo "$RESPONSE" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)
        echo -e "${GREEN}   ✅ Token is valid (Bot: @${BOT_USERNAME})${NC}"
    else
        echo -e "${RED}   ❌ Token is invalid or bot API is unreachable${NC}"
        echo -e "${RED}   Response: ${RESPONSE}${NC}"
        ISSUES=$((ISSUES + 1))
    fi
else
    echo -e "${RED}❌ Bot token not found in environment${NC}"
    echo -e "${YELLOW}   Check .env.local for TELEGRAM_BOT_TOKEN or BOT_TOKEN${NC}"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# 3. Check API service
echo -e "${BLUE}3. Checking API service...${NC}"
API_URL="${API_URL:-http://localhost:8000}"
if curl -s -f --max-time 3 "${API_URL}/health/live" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ API service is healthy (${API_URL})${NC}"
else
    echo -e "${RED}❌ API service is not available (${API_URL})${NC}"
    echo -e "${YELLOW}   Start it with: ./scripts/dev/start-api.sh${NC}"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# 4. Check Redis
echo -e "${BLUE}4. Checking Redis...${NC}"
if redis-cli ping >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Redis is running${NC}"
else
    echo -e "${RED}❌ Redis is not running${NC}"
    echo -e "${YELLOW}   Start it with: docker-compose -f docker-compose.local.yml up -d redis${NC}"
    ISSUES=$((ISSUES + 1))
fi
echo ""

# 5. Check bot logs for errors
echo -e "${BLUE}5. Checking bot logs...${NC}"
if [ -f "logs/bot.log" ]; then
    # Check for "polling started" message
    if grep -q "polling started\|Telegram bot polling started\|✅ Telegram bot running" logs/bot.log 2>/dev/null; then
        echo -e "${GREEN}✅ Bot polling started successfully${NC}"
    else
        echo -e "${YELLOW}⚠️  Bot polling not confirmed in logs${NC}"
    fi

    # Check for errors
    RECENT_ERRORS=$(grep -i "error\|exception\|failed\|❌" logs/bot.log 2>/dev/null | tail -5)
    if [ -n "$RECENT_ERRORS" ]; then
        echo -e "${RED}❌ Recent errors found:${NC}"
        echo "$RECENT_ERRORS" | sed 's/^/   /'
        ISSUES=$((ISSUES + 1))
    else
        echo -e "${GREEN}✅ No recent errors found${NC}"
    fi

    # Show last few log lines
    echo -e "${CYAN}   Last 3 log lines:${NC}"
    tail -3 logs/bot.log 2>/dev/null | sed 's/^/   /' || echo "   (no logs)"
else
    echo -e "${YELLOW}⚠️  Bot log file not found (logs/bot.log)${NC}"
    echo -e "${YELLOW}   Bot may not have started yet${NC}"
fi
echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📋 Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
    echo ""
    echo -e "${YELLOW}If bot still doesn't respond:${NC}"
    echo "   1. Check logs: ${CYAN}tail -f logs/bot.log${NC}"
    echo "   2. Verify you're messaging the correct bot (@${BOT_USERNAME:-unknown})"
    echo "   3. Try sending /start to the bot"
else
    echo -e "${RED}❌ Found $ISSUES issue(s)${NC}"
    echo ""
    echo -e "${YELLOW}Quick fixes:${NC}"

    if [ -z "$BOT_PID" ]; then
        echo "   • Start bot: ${CYAN}./scripts/dev/start-bot.sh${NC}"
    fi

    if ! curl -s -f --max-time 3 "${API_URL:-http://localhost:8000}/health/live" >/dev/null 2>&1; then
        echo "   • Start API: ${CYAN}./scripts/dev/start-api.sh${NC}"
    fi

    if ! redis-cli ping >/dev/null 2>&1; then
        echo "   • Start Redis: ${CYAN}docker-compose -f docker-compose.local.yml up -d redis${NC}"
    fi

    echo ""
    echo -e "${YELLOW}Or restart everything:${NC}"
    echo "   ${CYAN}./scripts/dev/stop-all.sh && ./scripts/dev/start-all.sh${NC}"
fi

echo ""
