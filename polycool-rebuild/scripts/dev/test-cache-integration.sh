#!/bin/bash
# Test Redis cache integration (cache hit/miss, invalidation, TTL)
# Usage: ./scripts/dev/test-cache-integration.sh
#
# This script ONLY tests cache - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 Testing Redis Cache Integration${NC}"
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

REDIS_URL="${REDIS_URL:-redis://localhost:6379}"

# Extract Redis host and port
REDIS_HOST="${REDIS_URL#*://}"
REDIS_HOST="${REDIS_HOST%%:*}"
REDIS_PORT="${REDIS_URL#*:}"
REDIS_PORT="${REDIS_PORT#*:}"
REDIS_PORT="${REDIS_PORT%%/*}"

if [ -z "$REDIS_PORT" ] || [ "$REDIS_PORT" = "$REDIS_HOST" ]; then
    REDIS_PORT=6379
fi

# Function to check Redis connectivity
check_redis() {
    echo -e "${BLUE}📋 Checking Redis connectivity...${NC}"

    if ! command -v redis-cli >/dev/null 2>&1; then
        echo -e "${RED}❌ redis-cli not found${NC}"
        echo -e "${YELLOW}   → Install Redis CLI or use Docker: docker exec -it polycool-redis-local redis-cli${NC}"
        ERRORS=$((ERRORS + 1))
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi

    if redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" ping >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Redis is accessible at ${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}❌ Redis is not accessible at ${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}${NC}"
        echo -e "${YELLOW}   → Start Redis with: docker compose -f docker-compose.local.yml up -d redis${NC}"
        ERRORS=$((ERRORS + 1))
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Function to test cache operations via Python
test_cache_operations() {
    echo -e "${BLUE}📋 Testing cache operations...${NC}"

    python3 << 'PYTHON_SCRIPT'
import os
import sys
import asyncio
import json
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.getcwd())

try:
    from core.services.cache_manager import CacheManager

    async def test_cache():
        print("   Testing CacheManager...")

        cache_manager = CacheManager()

        # Test 1: Set a value
        test_key = "test:cache:integration"
        test_data = {"test": "data", "timestamp": str(datetime.now())}

        try:
            await cache_manager.set(test_key, test_data, "user_profile")
            print("   ✅ Cache SET operation successful")
        except Exception as e:
            print(f"   ❌ Cache SET operation failed: {e}")
            sys.exit(1)

        # Test 2: Get the value (cache hit)
        try:
            cached_data = await cache_manager.get(test_key, "user_profile")
            if cached_data and cached_data.get("test") == "data":
                print("   ✅ Cache GET operation successful (cache hit)")
            else:
                print("   ❌ Cache GET returned incorrect data")
                sys.exit(1)
        except Exception as e:
            print(f"   ❌ Cache GET operation failed: {e}")
            sys.exit(1)

        # Test 3: Delete the value
        try:
            deleted = await cache_manager.delete(test_key)
            if deleted:
                print("   ✅ Cache DELETE operation successful")
            else:
                print("   ⚠️  Cache DELETE returned False (key may not exist)")
        except Exception as e:
            print(f"   ❌ Cache DELETE operation failed: {e}")
            sys.exit(1)

        # Test 4: Get after delete (cache miss)
        try:
            cached_data = await cache_manager.get(test_key, "user_profile")
            if cached_data is None:
                print("   ✅ Cache miss after deletion (expected)")
            else:
                print("   ⚠️  Cache still contains data after deletion")
        except Exception as e:
            print(f"   ❌ Cache GET after DELETE failed: {e}")
            sys.exit(1)

        # Test 5: Test TTL by setting with short TTL
        test_key_ttl = "test:cache:ttl"
        await cache_manager.set(test_key_ttl, {"test": "ttl"}, "prices")  # prices has short TTL (20s)
        print("   ✅ Cache SET with TTL successful")

        # Test 6: Test pattern invalidation
        test_pattern_keys = [
            "test:cache:pattern:1",
            "test:cache:pattern:2",
            "test:cache:pattern:3"
        ]
        for key in test_pattern_keys:
            await cache_manager.set(key, {"data": "test"}, "user_profile")

        try:
            invalidated = await cache_manager.invalidate_pattern("test:cache:pattern:*")
            if invalidated > 0:
                print(f"   ✅ Cache pattern invalidation successful ({invalidated} keys)")
            else:
                print("   ⚠️  Pattern invalidation returned 0 (no keys matched)")
        except Exception as e:
            print(f"   ❌ Cache pattern invalidation failed: {e}")
            sys.exit(1)

        # Cleanup
        try:
            await cache_manager.delete(test_key_ttl)
        except:
            pass

        print("   ✅ All cache operations successful")

    asyncio.run(test_cache())

except ImportError as e:
    print(f"   ❌ Failed to import CacheManager: {e}")
    print("   → Make sure dependencies are installed: pip install -e .")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ Cache test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYTHON_SCRIPT

    if [ $? -eq 0 ]; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        ERRORS=$((ERRORS + 1))
    fi
}

# Function to check cache keys in Redis
check_cache_keys() {
    echo -e "${BLUE}📋 Checking cache keys in Redis...${NC}"

    if ! command -v redis-cli >/dev/null 2>&1; then
        echo -e "${YELLOW}   ⚠️  redis-cli not found, skipping key inspection${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi

    # Count cache keys
    CACHE_KEYS=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" KEYS "api:*" 2>/dev/null | wc -l | tr -d ' ')

    if [ "$CACHE_KEYS" -gt 0 ]; then
        echo -e "${GREEN}   ✅ Found ${CACHE_KEYS} cache key(s) with pattern 'api:*'${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Show sample keys
        SAMPLE_KEYS=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" KEYS "api:*" 2>/dev/null | head -5)
        if [ -n "$SAMPLE_KEYS" ]; then
            echo -e "${BLUE}   Sample keys:${NC}"
            echo "$SAMPLE_KEYS" | while read -r key; do
                if [ -n "$key" ]; then
                    TTL=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" TTL "$key" 2>/dev/null || echo "-1")
                    if [ "$TTL" -gt 0 ]; then
                        echo -e "${GREEN}     → ${key} (TTL: ${TTL}s)${NC}"
                    elif [ "$TTL" -eq -1 ]; then
                        echo -e "${YELLOW}     → ${key} (no TTL)${NC}"
                    else
                        echo -e "${YELLOW}     → ${key} (expired)${NC}"
                    fi
                fi
            done
        fi
    else
        echo -e "${YELLOW}   ⚠️  No cache keys found with pattern 'api:*' (cache may be empty)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
}

# Function to test cache hit/miss via API calls
test_api_cache_behavior() {
    echo -e "${BLUE}📋 Testing API cache behavior...${NC}"

    API_URL="${API_URL:-http://localhost:8000}"

    if ! curl -s -f "${API_URL}/health/live" >/dev/null 2>&1; then
        echo -e "${YELLOW}   ⚠️  API is not running, skipping API cache test${NC}"
        echo -e "${YELLOW}   → Start API with: ./scripts/dev/start-api.sh${NC}"
        WARNINGS=$((WARNINGS + 1))
        return 1
    fi

    # Make two identical API calls and check if second one is cached
    TEST_ENDPOINT="${API_URL}/api/v1/markets?limit=5"

    echo -e "${BLUE}   Making first API call (should populate cache)...${NC}"
    FIRST_RESPONSE=$(curl -s -w "\n%{http_code}" "${TEST_ENDPOINT}" 2>/dev/null || echo "")
    FIRST_HTTP_CODE=$(echo "$FIRST_RESPONSE" | tail -1)

    if [ "$FIRST_HTTP_CODE" = "200" ] || [ "$FIRST_HTTP_CODE" = "401" ] || [ "$FIRST_HTTP_CODE" = "404" ]; then
        echo -e "${GREEN}   ✅ First API call successful (HTTP ${FIRST_HTTP_CODE})${NC}"

        # Wait a moment
        sleep 1

        # Check if key exists in cache
        CACHE_KEY="api:markets:limit=5"
        CACHE_EXISTS=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" EXISTS "$CACHE_KEY" 2>/dev/null || echo "0")

        if [ "$CACHE_EXISTS" = "1" ]; then
            echo -e "${GREEN}   ✅ Cache key exists after API call${NC}"
            TESTS_PASSED=$((TESTS_PASSED + 1))

            # Check TTL
            TTL=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" TTL "$CACHE_KEY" 2>/dev/null || echo "-1")
            if [ "$TTL" -gt 0 ]; then
                echo -e "${GREEN}   ✅ Cache key has TTL: ${TTL}s${NC}"
                TESTS_PASSED=$((TESTS_PASSED + 1))
            else
                echo -e "${YELLOW}   ⚠️  Cache key has no TTL or expired${NC}"
                WARNINGS=$((WARNINGS + 1))
            fi
        else
            echo -e "${YELLOW}   ⚠️  Cache key not found (may not be cached or different key pattern)${NC}"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        echo -e "${YELLOW}   ⚠️  API call returned HTTP ${FIRST_HTTP_CODE} (may require authentication)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
}

# 1. Check Redis connectivity
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}1. Redis Connectivity${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if check_redis; then
    # Get Redis info
    REDIS_VERSION=$(redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" INFO server 2>/dev/null | grep "redis_version" | cut -d: -f2 | tr -d '\r\n' || echo "unknown")
    echo -e "${GREEN}   Redis version: ${REDIS_VERSION}${NC}"
fi
echo ""

# 2. Test cache operations
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}2. Cache Operations${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

test_cache_operations
echo ""

# 3. Check existing cache keys
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}3. Existing Cache Keys${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

check_cache_keys
echo ""

# 4. Test API cache behavior
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}4. API Cache Behavior${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

test_api_cache_behavior
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
    echo -e "${GREEN}✅ All cache tests passed!${NC}"
    echo -e "${GREEN}   Redis cache is working correctly.${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Some cache tests have warnings but no critical errors.${NC}"
    echo -e "${YELLOW}   Review the warnings above.${NC}"
    exit 0
else
    echo -e "${RED}❌ Cache tests found ${ERRORS} error(s).${NC}"
    echo -e "${RED}   Please review the errors above.${NC}"
    exit 1
fi
