#!/bin/bash
# Main test script for local production-like testing
# Usage: ./scripts/dev/test-local-prod-like.sh
#
# This script runs all verification and test scripts

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}🧪 Local Production-Like Testing Suite${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Function to run a test script
run_test() {
    local test_name=$1
    local test_script=$2

    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Running: ${test_name}${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    if [ -f "$test_script" ]; then
        if bash "$test_script"; then
            echo ""
            echo -e "${GREEN}✅ ${test_name} PASSED${NC}"
            PASSED_TESTS=$((PASSED_TESTS + 1))
            echo ""
            return 0
        else
            echo ""
            echo -e "${RED}❌ ${test_name} FAILED${NC}"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            echo ""
            # Don't fail the entire test suite for configuration warnings
            if [ "$test_name" = "Configuration Verification" ]; then
                echo -e "${YELLOW}⚠️  Configuration has warnings but continuing...${NC}"
                return 0
            fi
            return 1
        fi
    else
        echo -e "${YELLOW}⚠️  Test script not found: ${test_script}${NC}"
        echo ""
        return 1
    fi
}

# 1. Verify Configuration
run_test "Configuration Verification" "scripts/dev/verify-config.sh"

# 2. Verify Services (if running)
if [ -f "logs/api.pid" ] || [ -f "logs/bot.pid" ] || [ -f "logs/workers.pid" ]; then
    run_test "Services Verification" "scripts/dev/verify-services.sh"
else
    echo -e "${YELLOW}⚠️  Services not running, skipping services verification${NC}"
    echo -e "${YELLOW}   → Start services with: ./scripts/dev/start-all.sh${NC}"
    echo ""
fi

# 3. Verify Handlers SKIP_DB
run_test "Handlers SKIP_DB Verification" "scripts/dev/verify-handlers-skip-db.sh"

# 4. Test Bot-API Integration (if API is running)
if curl -s -f "http://localhost:8000/health/live" >/dev/null 2>&1; then
    run_test "Bot-API Integration" "scripts/dev/test-bot-api-integration.sh"
else
    echo -e "${YELLOW}⚠️  API not running, skipping bot-API integration test${NC}"
    echo -e "${YELLOW}   → Start API with: ./scripts/dev/start-api.sh${NC}"
    echo ""
fi

# 5. Test Cache Integration (if Redis is running)
if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    run_test "Cache Integration" "scripts/dev/test-cache-integration.sh"
else
    echo -e "${YELLOW}⚠️  Redis not running, skipping cache integration test${NC}"
    echo -e "${YELLOW}   → Start Redis with: docker compose -f docker-compose.local.yml up -d redis${NC}"
    echo ""
fi

# 6. Test Workers (if workers are running)
if [ -f "logs/workers.pid" ]; then
    run_test "Workers Functionality" "scripts/dev/test-workers.sh"
else
    echo -e "${YELLOW}⚠️  Workers not running, skipping workers test${NC}"
    echo -e "${YELLOW}   → Start workers with: ./scripts/dev/start-workers.sh${NC}"
    echo ""
fi

# 7. Test End-to-End Scenarios (if services are running)
if curl -s -f "http://localhost:8000/health/live" >/dev/null 2>&1; then
    run_test "End-to-End Scenarios" "scripts/dev/test-e2e-scenarios.sh"
else
    echo -e "${YELLOW}⚠️  Services not running, skipping end-to-end scenarios test${NC}"
    echo -e "${YELLOW}   → Start all services with: ./scripts/dev/start-all.sh${NC}"
    echo ""
fi

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📊 Test Suite Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Total Tests: ${BLUE}${TOTAL_TESTS}${NC}"
echo -e "Passed: ${GREEN}${PASSED_TESTS}${NC}"
echo -e "Failed: ${RED}${FAILED_TESTS}${NC}"
echo -e "Skipped: ${YELLOW}$((TOTAL_TESTS - PASSED_TESTS - FAILED_TESTS))${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    echo ""
    echo "💡 Next steps:"
    echo "   1. Start all services: ./scripts/dev/start-all.sh"
    echo "   2. Monitor logs: ./scripts/dev/monitor-all.sh"
    echo "   3. Test manually via Telegram bot"
    exit 0
else
    echo -e "${RED}❌ Some tests failed (${FAILED_TESTS})${NC}"
    echo ""
    echo "💡 To fix issues:"
    echo "   1. Review the failed tests above"
    echo "   2. Check logs: tail -f logs/*.log"
    echo "   3. Consult troubleshooting guide: docs/TROUBLESHOOTING.md"
    exit 1
fi
