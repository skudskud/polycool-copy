#!/bin/bash

# Subsquid Silo Tests - Test Runner Script
# Vérifie les dépendances et lance la suite de tests

set -e  # Exit on error

echo "================================================================================"
echo "🧪 SUBSQUID SILO TESTS - Integration Test Suite"
echo "================================================================================"

# Couleurs pour output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Changement de répertoire
cd "$(dirname "$0")"
PROJECT_ROOT="/Users/ulyssepiediscalzi/Documents/polycool_last2/py-clob-client-with-bots/apps/subsquid-silo-tests"
cd "$PROJECT_ROOT"

echo -e "\n📁 Working directory: $PWD"

# Vérifier Redis
echo -e "\n🔍 Checking Redis..."
if redis-cli -h localhost -p 6379 -n 1 ping > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Redis OK${NC} (localhost:6379)"
else
    echo -e "${RED}❌ Redis non disponible sur localhost:6379${NC}"
    echo "   Please start Redis: brew services start redis (macOS)"
    echo "   Or: docker run -d -p 6379:6379 redis:latest"
    exit 1
fi

# Vérifier PostgreSQL (via DATABASE_URL dans .env)
echo -e "\n🔍 Checking PostgreSQL..."
if [ -f .env ]; then
    source .env
    if [ -n "$DATABASE_URL" ]; then
        if psql "$DATABASE_URL" -c "SELECT 1" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ PostgreSQL OK${NC}"
        else
            echo -e "${YELLOW}⚠️  PostgreSQL connexion failed${NC}"
            echo "   DATABASE_URL: ${DATABASE_URL:0:40}..."
            echo "   Tests may fail if database is not accessible"
        fi
    else
        echo -e "${YELLOW}⚠️  DATABASE_URL not set in .env${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  .env file not found${NC}"
    echo "   Using default test database"
fi

# Vérifier Python dependencies
echo -e "\n🔍 Checking Python dependencies..."
if python3 -c "import pytest, asyncio, httpx, websockets, redis, fastapi" 2>/dev/null; then
    echo -e "${GREEN}✅ Python dependencies OK${NC}"
else
    echo -e "${RED}❌ Missing Python dependencies${NC}"
    echo "   Installing from requirements.txt..."
    pip3 install -r requirements.txt
fi

# Configuration des tests
echo -e "\n⚙️  Test Configuration:"
echo "   EXPERIMENTAL_SUBSQUID=true"
echo "   REDIS_URL=redis://localhost:6379/1"
echo "   POLL_MS=5000 (fast mode for tests)"
echo "   WS_MAX_SUBSCRIPTIONS=5 (limited for tests)"

# Lancer les tests
echo -e "\n" + "="*80
echo "🚀 RUNNING TESTS"
echo "="*80

# Options pytest:
# -v: verbose
# -s: show print statements
# --tb=short: short traceback
# --durations=10: show 10 slowest tests
# --cov=src: code coverage for src/
# --cov-report=term-missing: show missing lines
# --maxfail=3: stop after 3 failures
# -W ignore::DeprecationWarning: ignore deprecation warnings

pytest tests/ \
    -v \
    -s \
    --tb=short \
    --durations=10 \
    --cov=src \
    --cov-report=term-missing \
    --cov-report=html \
    --maxfail=3 \
    -W ignore::DeprecationWarning

TEST_EXIT_CODE=$?

echo -e "\n================================================================================"
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ TOUS LES TESTS SONT PASSÉS${NC}"
else
    echo -e "${RED}❌ CERTAINS TESTS ONT ÉCHOUÉ${NC}"
fi
echo "================================================================================"

# Afficher rapport de couverture
if [ -d htmlcov ]; then
    echo -e "\n📊 Code coverage report generated: htmlcov/index.html"
    echo "   Open with: open htmlcov/index.html"
fi

# Stats finales
echo -e "\n📈 Test Summary:"
echo "   Check output above for detailed results"
echo "   Exit code: $TEST_EXIT_CODE"

exit $TEST_EXIT_CODE
