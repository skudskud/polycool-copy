#!/bin/bash
# Start Bot service for local testing
# Usage: ./scripts/dev/start-bot.sh

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🤖 Starting Polycool Bot service (local testing)${NC}"
echo ""

# Check if API is running
API_URL="${API_URL:-http://localhost:8000}"
echo -e "${YELLOW}🔍 Checking if API service is available at ${API_URL}...${NC}"

if ! curl -s -f "${API_URL}/health/live" >/dev/null 2>&1; then
    echo -e "${RED}❌ API service is not available at ${API_URL}${NC}"
    echo "   Please start the API service first: ./scripts/dev/start-api.sh"
    exit 1
fi

echo -e "${GREEN}✅ API service is healthy${NC}"

# Check if Redis is running
if ! redis-cli ping >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Redis is not running. Starting Redis...${NC}"
    if command -v docker >/dev/null 2>&1; then
        # Try docker-compose.local.yml first, then docker-compose.yml
        if [ -f "docker-compose.local.yml" ]; then
            docker compose -f docker-compose.local.yml up -d redis 2>/dev/null || \
            docker compose up -d redis 2>/dev/null || \
            echo -e "${RED}❌ Failed to start Redis. Please start it manually.${NC}"
        else
            docker compose up -d redis 2>/dev/null || \
            echo -e "${RED}❌ Failed to start Redis. Please start it manually.${NC}"
        fi
        sleep 2
    else
        echo -e "${RED}❌ Redis is not running and Docker is not available.${NC}"
        exit 1
    fi
fi

# Create logs directory
mkdir -p logs

# Set environment variables for Bot service
export SKIP_DB=true
export STREAMER_ENABLED=false
export TPSL_MONITORING_ENABLED=false
export POLLER_ENABLED=false
export API_URL="${API_URL:-http://localhost:8000}"
export API_PREFIX=/api/v1
export ENVIRONMENT=local
export DEBUG=true
export LOG_LEVEL=INFO

# Load REDIS_URL from environment or use local
if [ -z "$REDIS_URL" ]; then
    export REDIS_URL="redis://localhost:6379"
fi

# Load other required variables from .env.local if it exists
if [ -f ".env.local" ]; then
    echo -e "${GREEN}📋 Loading variables from .env.local${NC}"
    set -a
    source .env.local
    set +a
fi

# Override with Bot-specific settings
export SKIP_DB=true
export STREAMER_ENABLED=false
export TPSL_MONITORING_ENABLED=false
export POLLER_ENABLED=false
export API_URL=http://localhost:8000
export API_PREFIX=/api/v1

# Check required variables
# Support both TELEGRAM_BOT_TOKEN and BOT_TOKEN for compatibility
if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ -z "$BOT_TOKEN" ]; then
    echo -e "${RED}❌ TELEGRAM_BOT_TOKEN or BOT_TOKEN is not set${NC}"
    echo "   Please set it in .env.local or export it"
    exit 1
fi

# Normalize: Use BOT_TOKEN if TELEGRAM_BOT_TOKEN is not set, and vice versa
# settings.py uses TELEGRAM_BOT_TOKEN env var
if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ -n "$BOT_TOKEN" ]; then
    export TELEGRAM_BOT_TOKEN="$BOT_TOKEN"
fi
if [ -z "$BOT_TOKEN" ] && [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    export BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
fi

if [ -z "$ENCRYPTION_KEY" ]; then
    echo -e "${RED}❌ ENCRYPTION_KEY is not set${NC}"
    echo "   Please set it in .env.local or export it"
    exit 1
fi

echo -e "${GREEN}✅ Configuration loaded${NC}"
echo ""
echo "📊 Service: Bot"
echo "🔗 API: ${API_URL}"
echo "🤖 Bot: Telegram polling"
echo ""
echo -e "${GREEN}🚀 Starting Bot service...${NC}"
echo ""

# Start Bot service
python bot_only.py 2>&1 | tee logs/bot.log
