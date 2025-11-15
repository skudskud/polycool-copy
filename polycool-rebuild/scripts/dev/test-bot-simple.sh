#!/bin/bash
# Test simple du bot en local comme en production
# Usage: ./scripts/dev/test-bot-simple.sh
#
# Ce script démarre l'API et le bot avec la même config qu'en production

set -e

cd "$(dirname "$0")/../.."

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}🤖 Test Bot Local (comme en production)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Load .env.local
if [ -f ".env.local" ]; then
    set -a
    source .env.local 2>/dev/null || true
    set +a
fi

# 1. Vérifier Redis
echo -e "${BLUE}1. Vérification Redis...${NC}"
if ! redis-cli ping >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Redis n'est pas démarré. Démarrage...${NC}"
    if command -v docker >/dev/null 2>&1; then
        if [ -f "docker-compose.local.yml" ]; then
            docker compose -f docker-compose.local.yml up -d redis 2>/dev/null || true
        else
            docker compose up -d redis 2>/dev/null || true
        fi
        sleep 2
    else
        echo -e "${RED}❌ Redis n'est pas disponible. Installe Redis ou Docker.${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✅ Redis OK${NC}"
echo ""

# 2. Arrêter/Redémarrer API (pour avoir les derniers changements)
echo -e "${BLUE}2. Redémarrage API...${NC}"
API_URL="${API_URL:-http://localhost:8000}"

# Arrêter l'API si elle est déjà en cours d'exécution
API_PIDS=$(ps aux | grep -E "uvicorn|api_only|start-api" | grep -v grep | awk '{print $2}' || true)
if [ -n "$API_PIDS" ]; then
    echo -e "${YELLOW}⚠️  Arrêt de l'API existante...${NC}"
    echo "$API_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
    echo -e "${GREEN}✅ API arrêtée${NC}"
fi

# Démarrer l'API
echo -e "${YELLOW}⚠️  Démarrage de l'API en arrière-plan...${NC}"
    # Variables d'environnement pour l'API (comme dans start-api.sh)
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

    # Database URL (utilise celle du script start-api.sh)
    if [ -z "$DATABASE_URL" ]; then
        export DATABASE_URL="postgresql://postgres.xxzdlbwfyetaxcmodiec:ClDSK0N5IedorZes@aws-1-eu-north-1.pooler.supabase.com:5432/postgres"
    fi

    # Redis URL
    if [ -z "$REDIS_URL" ]; then
        export REDIS_URL="redis://localhost:6379"
    fi

    python api_only.py > logs/api.log 2>&1 &
    API_PID=$!
    echo "   API démarrée (PID: $API_PID)"

    # Attendre que l'API soit prête (max 30 secondes)
    echo -e "${YELLOW}   Attente de l'API...${NC}"
    for i in {1..30}; do
        if curl -s -f "${API_URL}/health/live" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ API prête${NC}"
            break
        fi
        sleep 1
        if [ $i -eq 30 ]; then
            echo -e "${RED}❌ L'API n'a pas démarré après 30 secondes${NC}"
            echo "   Vérifie les logs: tail -f logs/api.log"
            exit 1
        fi
    done
echo ""

# 3. Démarrer Workers Service (pour WebSocket subscriptions via Redis)
echo -e "${BLUE}3. Démarrage Workers Service...${NC}"

# Arrêter les anciens workers si existants
WORKERS_PIDS=$(ps aux | grep -E "workers\.py|python.*workers" | grep -v grep | awk '{print $2}' || true)
if [ -n "$WORKERS_PIDS" ]; then
    echo -e "${YELLOW}⚠️  Arrêt des anciens workers...${NC}"
    echo "$WORKERS_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Configuration pour workers (avec streamer activé)
export SKIP_DB=true
export STREAMER_ENABLED=true
export TPSL_MONITORING_ENABLED=false
export POLLER_ENABLED=false

# Redis local
if [ -z "$REDIS_URL" ]; then
    export REDIS_URL="redis://localhost:6379"
fi

# Démarrer workers en arrière-plan
echo -e "${YELLOW}⚠️  Démarrage des workers en arrière-plan...${NC}"
python workers.py > logs/workers.log 2>&1 &
WORKERS_PID=$!
echo "   Workers démarrés (PID: $WORKERS_PID)"
sleep 3  # Attendre que les workers démarrent
echo -e "${GREEN}✅ Workers Service démarré${NC}"
echo "   • Streamer activé (pour WebSocket)"
echo "   • Listener Redis Pub/Sub activé"
echo "   • Logs: tail -f logs/workers.log"
echo ""

# 4. Configuration du bot (comme en production - SANS streamer pour tester Redis)
echo -e "${BLUE}4. Configuration du bot...${NC}"

# Variables comme en production (MAIS sans streamer pour tester Redis Pub/Sub)
export SKIP_DB=true
export STREAMER_ENABLED=false  # Désactivé pour forcer l'utilisation de Redis Pub/Sub
export TPSL_MONITORING_ENABLED=false
export POLLER_ENABLED=false
export API_URL="${API_URL:-http://localhost:8000}"
export API_PREFIX=/api/v1
export ENVIRONMENT=local

# Vérifier BOT_TOKEN
if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ -z "$BOT_TOKEN" ]; then
    echo -e "${RED}❌ TELEGRAM_BOT_TOKEN ou BOT_TOKEN n'est pas défini${NC}"
    echo "   Ajoute-le dans .env.local"
    exit 1
fi

# Normaliser les tokens
if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ -n "$BOT_TOKEN" ]; then
    export TELEGRAM_BOT_TOKEN="$BOT_TOKEN"
fi
if [ -z "$BOT_TOKEN" ] && [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    export BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
fi

echo -e "${GREEN}✅ Configuration OK${NC}"
echo "   • SKIP_DB=true (comme en prod)"
echo "   • STREAMER_ENABLED=false (bot utilise Redis Pub/Sub)"
echo "   • API_URL=${API_URL}"
echo "   • Bot Token: ${TELEGRAM_BOT_TOKEN:0:10}...${TELEGRAM_BOT_TOKEN: -4}"
echo ""

# 5. Arrêter les anciennes instances du bot
echo -e "${BLUE}5. Vérification des anciennes instances...${NC}"
BOT_PIDS=$(ps aux | grep -E "bot_only|python.*bot_only" | grep -v grep | awk '{print $2}' || true)
if [ -n "$BOT_PIDS" ]; then
    echo -e "${YELLOW}⚠️  Anciennes instances trouvées. Arrêt...${NC}"
    echo "$BOT_PIDS" | xargs kill -9 2>/dev/null || true
    sleep 2
    echo -e "${GREEN}✅ Anciennes instances arrêtées${NC}"
else
    echo -e "${GREEN}✅ Aucune ancienne instance${NC}"
fi
echo ""

# 6. Créer le dossier logs
mkdir -p logs

# 7. Démarrer le bot
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🚀 Démarrage du bot...${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}💡 Architecture de test:${NC}"
echo -e "${YELLOW}   • API (port 8000) - sans streamer${NC}"
echo -e "${YELLOW}   • Workers - avec streamer + listener Redis${NC}"
echo -e "${YELLOW}   • Bot - sans streamer (utilise Redis Pub/Sub)${NC}"
echo ""
echo -e "${YELLOW}💡 Le bot va démarrer et afficher les logs ci-dessous${NC}"
echo -e "${YELLOW}💡 Envoie /start au bot Telegram pour tester${NC}"
echo -e "${YELLOW}💡 Après un trade, vérifie les logs:${NC}"
echo -e "${YELLOW}   • API: tail -f logs/api.log | grep websocket${NC}"
echo -e "${YELLOW}   • Workers: tail -f logs/workers.log | grep -i 'redis\|subscribe'${NC}"
echo -e "${YELLOW}💡 Ctrl+C pour arrêter${NC}"
echo ""

# Fonction de nettoyage pour arrêter tous les processus
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Arrêt des services...${NC}"

    # Arrêter le bot
    if [ -n "$BOT_PID" ]; then
        kill $BOT_PID 2>/dev/null || true
    fi

    # Arrêter les workers
    if [ -n "$WORKERS_PID" ]; then
        kill $WORKERS_PID 2>/dev/null || true
    fi

    # Arrêter l'API
    if [ -n "$API_PID" ]; then
        kill $API_PID 2>/dev/null || true
    fi

    # Nettoyer les processus restants
    pkill -f "bot_only.py" 2>/dev/null || true
    pkill -f "workers.py" 2>/dev/null || true
    pkill -f "api_only.py" 2>/dev/null || true

    echo -e "${GREEN}✅ Services arrêtés${NC}"
    exit 0
}

# Capturer Ctrl+C et appeler cleanup
trap cleanup SIGINT SIGTERM

# Démarrer le bot avec logs visibles
# IMPORTANT: Exporter explicitement TELEGRAM_BOT_TOKEN pour forcer son utilisation
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$BOT_TOKEN}"

# Démarrer le bot en arrière-plan et capturer son PID
# Utiliser PYTHONUNBUFFERED pour éviter les problèmes de buffering
PYTHONUNBUFFERED=1 python bot_only.py > logs/bot.log 2>&1 &
BOT_PID=$!
echo "   Bot démarré (PID: $BOT_PID)"
echo "   Logs: tail -f logs/bot.log"

# Attendre que le bot se termine (ou Ctrl+C)
echo ""
echo -e "${GREEN}✅ Tous les services sont démarrés${NC}"
echo -e "${YELLOW}💡 Surveille les logs dans des terminaux séparés:${NC}"
echo -e "${YELLOW}   • tail -f logs/api.log${NC}"
echo -e "${YELLOW}   • tail -f logs/workers.log${NC}"
echo -e "${YELLOW}   • tail -f logs/bot.log${NC}"
echo ""
echo -e "${YELLOW}💡 Appuie sur Ctrl+C pour arrêter tous les services${NC}"
echo ""

# Attendre que le bot se termine
wait $BOT_PID
