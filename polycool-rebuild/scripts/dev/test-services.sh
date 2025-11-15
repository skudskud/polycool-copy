#!/bin/bash
# Test all services health and connectivity
# Usage: ./scripts/dev/test-services.sh

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔍 Testing Polycool services...${NC}"
echo ""

# Test results
TESTS_PASSED=0
TESTS_FAILED=0

# Function to test service
test_service() {
    local name=$1
    local test_cmd=$2

    echo -n "Testing ${name}... "
    if eval "$test_cmd" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ PASS${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Test Redis
test_service "Redis" "redis-cli ping"

# Test API Health
test_service "API Health" "curl -s -f http://localhost:8000/health/live"

# Test API Ready
test_service "API Ready" "curl -s -f http://localhost:8000/health/ready"

# Test API Root
test_service "API Root" "curl -s -f http://localhost:8000/"

# Test Database connection (if DATABASE_URL is set)
if [ -n "$DATABASE_URL" ]; then
    echo -n "Testing Database connection... "
    # Try to connect using psql if available
    if command -v psql >/dev/null 2>&1; then
        if psql "$DATABASE_URL" -c "SELECT 1;" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ PASS${NC}"
            ((TESTS_PASSED++))
        else
            echo -e "${RED}❌ FAIL${NC}"
            ((TESTS_FAILED++))
        fi
    else
        echo -e "${YELLOW}⚠️  SKIP (psql not available)${NC}"
    fi
fi

# Test Bot process
echo -n "Testing Bot process... "
if pgrep -f "python.*bot_only.py" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}❌ FAIL (Bot not running)${NC}"
    ((TESTS_FAILED++))
fi

# Test Workers process
echo -n "Testing Workers process... "
if pgrep -f "python.*workers.py" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}❌ FAIL (Workers not running)${NC}"
    ((TESTS_FAILED++))
fi

# Test API process
echo -n "Testing API process... "
if pgrep -f "python.*api_only.py" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}❌ FAIL (API not running)${NC}"
    ((TESTS_FAILED++))
fi

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}📊 Test Summary${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ Passed: ${TESTS_PASSED}${NC}"
echo -e "${RED}❌ Failed: ${TESTS_FAILED}${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed. Check the logs for details.${NC}"
    exit 1
fi
