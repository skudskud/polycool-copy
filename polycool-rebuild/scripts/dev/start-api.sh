#!/bin/bash
# Start API service for local testing
# Usage: ./scripts/dev/start-api.sh

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🚀 Starting Polycool API service (local testing)${NC}"
echo ""

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
        echo "   Please start Redis manually: redis-server"
        exit 1
    fi
fi

# Create logs directory
mkdir -p logs

# Set environment variables for API service
export SKIP_DB=false
export STREAMER_ENABLED=false
export TPSL_MONITORING_ENABLED=false
export POLLER_ENABLED=false
export PORT=8000
export API_URL=http://localhost:8000
export API_PREFIX=/api/v1
export ENVIRONMENT=local
export DEBUG=true
export LOG_LEVEL=INFO

# Load DATABASE_URL from environment or use Supabase production pooler
if [ -z "$DATABASE_URL" ]; then
    export DATABASE_URL="postgresql://postgres.xxzdlbwfyetaxcmodiec:ClDSK0N5IedorZes@aws-1-eu-north-1.pooler.supabase.com:5432/postgres"
    echo -e "${YELLOW}⚠️  Using Supabase production database (from default)${NC}"
fi

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

# Override with API-specific settings
export SKIP_DB=false
export STREAMER_ENABLED=false
export TPSL_MONITORING_ENABLED=false
export POLLER_ENABLED=false
export PORT=8000
export API_URL=http://localhost:8000
export API_PREFIX=/api/v1

# Check required variables
if [ -z "$ENCRYPTION_KEY" ]; then
    echo -e "${RED}❌ ENCRYPTION_KEY is not set${NC}"
    echo "   Please set it in .env.local or export it"
    exit 1
fi

echo -e "${GREEN}✅ Configuration loaded${NC}"
echo ""
echo "📊 Service: API"
echo "🌐 URL: http://localhost:8000"
echo "🏥 Health: http://localhost:8000/health/live"
echo "📚 Docs: http://localhost:8000/docs"
echo ""
echo -e "${GREEN}🚀 Starting API service...${NC}"
echo ""

# Start API service
python api_only.py 2>&1 | tee logs/api.log
