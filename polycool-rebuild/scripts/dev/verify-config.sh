#!/bin/bash
# Verify configuration for local multi-service testing (production-like)
# Usage: ./scripts/dev/verify-config.sh
#
# This script ONLY verifies configuration - it does NOT modify anything

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔍 Verifying configuration for local multi-service testing${NC}"
echo ""

ERRORS=0
WARNINGS=0

# Function to check if a variable is set
check_var() {
    local var_name=$1
    local var_value=$2
    local required=${3:-true}

    if [ -z "$var_value" ]; then
        if [ "$required" = "true" ]; then
            echo -e "${RED}❌ ${var_name} is not set${NC}"
            ERRORS=$((ERRORS + 1))
        else
            echo -e "${YELLOW}⚠️  ${var_name} is not set (optional)${NC}"
            WARNINGS=$((WARNINGS + 1))
        fi
        return 1
    else
        echo -e "${GREEN}✅ ${var_name} is set${NC}"
        return 0
    fi
}

# Function to check if a file exists
check_file() {
    local file_path=$1
    local required=${2:-true}

    if [ ! -f "$file_path" ]; then
        if [ "$required" = "true" ]; then
            echo -e "${RED}❌ File not found: ${file_path}${NC}"
            ERRORS=$((ERRORS + 1))
            return 1
        else
            echo -e "${YELLOW}⚠️  File not found: ${file_path} (optional)${NC}"
            WARNINGS=$((WARNINGS + 1))
            return 1
        fi
    else
        echo -e "${GREEN}✅ File exists: ${file_path}${NC}"
        return 0
    fi
}

# 1. Check environment files
echo -e "${BLUE}📋 Checking environment files...${NC}"
check_file ".env.local" false
check_file ".env" false

# Load .env.local if it exists
if [ -f ".env.local" ]; then
    echo -e "${GREEN}📋 Loading variables from .env.local${NC}"
    set -a
    source .env.local
    set +a
elif [ -f ".env" ]; then
    echo -e "${YELLOW}📋 Loading variables from .env (fallback)${NC}"
    set -a
    source .env
    set +a
else
    echo -e "${RED}❌ No .env.local or .env file found${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# 2. Check critical variables
echo -e "${BLUE}📋 Checking critical environment variables...${NC}"

# Database
check_var "DATABASE_URL" "$DATABASE_URL" true
if [ -n "$DATABASE_URL" ]; then
    # Check if it's Supabase URL
    if echo "$DATABASE_URL" | grep -q "supabase.com\|pooler.supabase.com"; then
        echo -e "${GREEN}   → Using Supabase database${NC}"
    else
        echo -e "${YELLOW}   → Not a Supabase URL (might be local PostgreSQL)${NC}"
    fi
fi

# Redis
REDIS_URL_VALUE="${REDIS_URL:-redis://localhost:6379}"
check_var "REDIS_URL" "$REDIS_URL" false
if [ -z "$REDIS_URL" ]; then
    echo -e "${YELLOW}   → REDIS_URL not set, will use default: redis://localhost:6379${NC}"
fi

# Telegram Bot Token (support both names)
BOT_TOKEN_VALUE="${TELEGRAM_BOT_TOKEN:-$BOT_TOKEN}"
if [ -z "$BOT_TOKEN_VALUE" ]; then
    echo -e "${RED}❌ TELEGRAM_BOT_TOKEN or BOT_TOKEN is not set${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅ Telegram bot token is set${NC}"
fi

# Encryption Key
check_var "ENCRYPTION_KEY" "$ENCRYPTION_KEY" true
if [ -n "$ENCRYPTION_KEY" ]; then
    KEY_LENGTH=${#ENCRYPTION_KEY}
    if [ "$KEY_LENGTH" -ne 32 ]; then
        echo -e "${RED}❌ ENCRYPTION_KEY must be exactly 32 characters (currently: ${KEY_LENGTH})${NC}"
        ERRORS=$((ERRORS + 1))
    else
        echo -e "${GREEN}   → ENCRYPTION_KEY length is correct (32 characters)${NC}"
    fi
fi

# API URL (should be localhost for local testing)
API_URL_VALUE="${API_URL:-http://localhost:8000}"
check_var "API_URL" "$API_URL" false
if [ -n "$API_URL" ]; then
    if echo "$API_URL" | grep -q "localhost\|127.0.0.1"; then
        echo -e "${GREEN}   → API_URL is configured for local testing${NC}"
    else
        echo -e "${YELLOW}   → API_URL points to non-local address: ${API_URL}${NC}"
        echo -e "${YELLOW}   → For local testing, should be: http://localhost:8000${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}   → API_URL not set, will use default: http://localhost:8000${NC}"
fi

# CLOB API credentials (optional but recommended)
check_var "CLOB_API_KEY" "$CLOB_API_KEY" false
check_var "CLOB_API_SECRET" "$CLOB_API_SECRET" false
check_var "CLOB_API_PASSPHRASE" "$CLOB_API_PASSPHRASE" false

# Optional variables
check_var "POLYGON_RPC_URL" "$POLYGON_RPC_URL" false
check_var "SOLANA_RPC_URL" "$SOLANA_RPC_URL" false
check_var "OPENAI_API_KEY" "$OPENAI_API_KEY" false

echo ""

# 3. Check Redis connectivity
echo -e "${BLUE}📋 Checking Redis connectivity...${NC}"
if command -v redis-cli >/dev/null 2>&1; then
    REDIS_HOST="${REDIS_URL_VALUE#*://}"
    REDIS_HOST="${REDIS_HOST%%:*}"
    REDIS_PORT="${REDIS_URL_VALUE#*:}"
    REDIS_PORT="${REDIS_PORT#*:}"
    REDIS_PORT="${REDIS_PORT%%/*}"

    if [ -z "$REDIS_PORT" ] || [ "$REDIS_PORT" = "$REDIS_HOST" ]; then
        REDIS_PORT=6379
    fi

    if redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" ping >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Redis is accessible at ${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}${NC}"
    else
        echo -e "${YELLOW}⚠️  Redis is not accessible at ${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}${NC}"
        echo -e "${YELLOW}   → You may need to start Redis: docker compose -f docker-compose.local.yml up -d redis${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  redis-cli not found, skipping Redis connectivity check${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""

# 4. Check Docker (for Redis)
echo -e "${BLUE}📋 Checking Docker availability...${NC}"
if command -v docker >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Docker is available${NC}"
    if docker ps >/dev/null 2>&1; then
        echo -e "${GREEN}   → Docker daemon is running${NC}"

        # Check if Redis container is running
        if docker ps --format '{{.Names}}' | grep -q "polycool-redis\|redis"; then
            echo -e "${GREEN}   → Redis container appears to be running${NC}"
        else
            echo -e "${YELLOW}   → Redis container not found (will be started automatically)${NC}"
        fi
    else
        echo -e "${YELLOW}   → Docker daemon is not running${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  Docker not found (Redis will need to be started manually)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""

# 5. Check Python and dependencies
echo -e "${BLUE}📋 Checking Python environment...${NC}"
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    echo -e "${GREEN}✅ Python3 is available (${PYTHON_VERSION})${NC}"

    # Check if we can import key modules (read-only check)
    if python3 -c "import sys; sys.path.insert(0, '.'); from infrastructure.config.settings import settings" 2>/dev/null; then
        echo -e "${GREEN}   → Core modules can be imported${NC}"
    else
        echo -e "${YELLOW}   → Some modules may not be importable (run: pip install -e .)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${RED}❌ Python3 not found${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# 6. Check Supabase database connectivity (read-only test)
echo -e "${BLUE}📋 Checking Supabase database connectivity...${NC}"
if [ -n "$DATABASE_URL" ] && echo "$DATABASE_URL" | grep -q "supabase.com\|pooler.supabase.com"; then
    # Try a simple connection test (read-only)
    if python3 -c "
import os
import sys
os.environ['DATABASE_URL'] = '${DATABASE_URL}'
try:
    from sqlalchemy import create_engine, text
    from urllib.parse import urlparse
    url = os.environ['DATABASE_URL']
    # Add psycopg driver if needed
    if not url.startswith('postgresql+'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
        url = url.replace('postgres://', 'postgresql+psycopg://', 1)
    engine = create_engine(url, connect_args={'connect_timeout': 5})
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        result.fetchone()
    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
" 2>/dev/null | grep -q "SUCCESS"; then
        echo -e "${GREEN}✅ Supabase database is accessible${NC}"
    else
        echo -e "${YELLOW}⚠️  Could not connect to Supabase database${NC}"
        echo -e "${YELLOW}   → This might be normal if credentials are incorrect or network is down${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  DATABASE_URL does not point to Supabase (skipping connectivity test)${NC}"
fi

echo ""

# 7. Check required scripts exist
echo -e "${BLUE}📋 Checking required scripts...${NC}"
check_file "scripts/dev/start-api.sh" true
check_file "scripts/dev/start-bot.sh" true
check_file "scripts/dev/start-workers.sh" true
check_file "scripts/dev/start-all.sh" true
check_file "api_only.py" true
check_file "bot_only.py" true
check_file "workers.py" true

echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📊 Verification Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $ERRORS -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}✅ All checks passed! Configuration is ready for local testing.${NC}"
    else
        echo -e "${YELLOW}⚠️  Configuration has ${WARNINGS} warning(s) but no errors.${NC}"
        echo -e "${YELLOW}   You can proceed, but some features may not work correctly.${NC}"
    fi
    echo ""
    echo -e "${GREEN}✅ Configuration Verification PASSED${NC}"
    exit 0
else
    echo -e "${RED}❌ Configuration has ${ERRORS} error(s) and ${WARNINGS} warning(s).${NC}"
    echo -e "${RED}   Please fix the errors before proceeding.${NC}"
    exit 1
fi
