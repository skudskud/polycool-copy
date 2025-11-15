#!/bin/bash
# Script de démarrage rapide pour le bot en local
# Usage: ./start_local.sh

set -e

cd "$(dirname "$0")"

echo "🚀 Démarrage du bot Polycool en local..."
echo ""

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Fonction pour tuer les processus utilisant un port spécifique
kill_port_processes() {
    local port=$1
    local pids=$(lsof -ti:$port 2>/dev/null)
    if [ ! -z "$pids" ]; then
        echo -e "${YELLOW}⚠️  Port $port occupé par les processus: $pids${NC}"
        echo -e "${YELLOW}🔫 Terminaison des processus...${NC}"
        kill -9 $pids 2>/dev/null || true
        sleep 2
        echo -e "${GREEN}✅ Port $port libéré${NC}"
    else
        echo -e "${GREEN}✅ Port $port disponible${NC}"
    fi
}

# Nettoyer les ports utilisés
echo "🧹 Nettoyage des ports utilisés..."
kill_port_processes 8000
kill_port_processes 8443
echo ""

# 1. Vérifier que .env existe
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ Fichier .env non trouvé!${NC}"
    echo "   Création depuis template..."
    cp env.template .env
    echo -e "${YELLOW}⚠️  Veuillez configurer .env avec tes credentials avant de continuer${NC}"
    exit 1
fi

# 2. Vérifier les services Docker
echo "📋 Vérification des services Docker..."
if ! docker compose ps postgres | grep -q "running\|healthy"; then
    echo -e "${YELLOW}⚠️  PostgreSQL n'est pas démarré. Démarrage...${NC}"
    docker compose up -d postgres
    sleep 5
fi

if ! docker compose ps redis | grep -q "running\|healthy"; then
    echo -e "${YELLOW}⚠️  Redis n'est pas démarré. Démarrage...${NC}"
    docker compose up -d redis
    sleep 3
fi

echo -e "${GREEN}✅ Services Docker OK${NC}"

# 3. Vérifier les variables d'environnement critiques
echo ""
echo "📋 Vérification des variables d'environnement..."

missing_vars=()
# Priorité à .env.local pour le développement local
if ! grep -q "^TELEGRAM_BOT_TOKEN=" .env.local 2>/dev/null || grep -q "^TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here" .env.local 2>/dev/null; then
    missing_vars+=("TELEGRAM_BOT_TOKEN")
fi
if ! grep -q "^DATABASE_URL=" .env.local 2>/dev/null; then
    missing_vars+=("DATABASE_URL")
fi
if ! grep -q "^ENCRYPTION_KEY=" .env.local 2>/dev/null; then
    missing_vars+=("ENCRYPTION_KEY")
fi

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ Variables manquantes ou non configurées: ${missing_vars[*]}${NC}"
    echo "   Veuillez configurer ces variables dans .env.local"
    exit 1
fi

# Vérifier que ENCRYPTION_KEY fait 32 caractères (depuis .env.local)
encryption_key=$(grep "^ENCRYPTION_KEY=" .env.local | cut -d'=' -f2 | tr -d '"' | tr -d "'")
if [ ${#encryption_key} -ne 32 ]; then
    echo -e "${RED}❌ ENCRYPTION_KEY doit faire exactement 32 caractères (actuellement: ${#encryption_key})${NC}"
    echo "   Générer une nouvelle clé:"
    echo "   python3 -c \"import secrets; print(secrets.token_urlsafe(32)[:32])\""
    exit 1
fi

echo -e "${GREEN}✅ Variables d'environnement OK${NC}"

# 4. Vérifier les imports
echo ""
echo "📋 Vérification des imports Python..."
if python3 scripts/dev/test_imports.py >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Imports OK${NC}"
else
    echo -e "${YELLOW}⚠️  Certains imports échouent. Installation des dépendances...${NC}"
    pip install -e ".[dev]" || pip install -r requirements.txt
    if ! python3 scripts/dev/test_imports.py >/dev/null 2>&1; then
        echo -e "${RED}❌ Erreurs d'imports persistantes${NC}"
        python3 scripts/dev/test_imports.py
        exit 1
    fi
fi

# 5. Démarrer le bot
echo ""
echo -e "${GREEN}🚀 Démarrage du bot...${NC}"
echo ""
echo "📊 Endpoints disponibles:"
echo "   • API: http://localhost:8000"
echo "   • Health: http://localhost:8000/health"
echo "   • Docs: http://localhost:8000/docs"
echo ""
echo "💡 Pour tester dans Telegram:"
echo "   1. Cherche ton bot dans Telegram"
echo "   2. Envoie /start"
echo "   3. Envoie /wallet"
echo ""
echo "🛑 Pour arrêter: Ctrl+C"
echo ""

# Démarrer le bot
# Exporter les variables d'environnement pour le processus enfant (priorité à .env.local)
if [ -f ".env.local" ]; then
    echo "📋 Chargement des variables depuis .env.local"
    set -a  # Export automatiquement toutes les variables définies
    source .env.local
    set +a
else
    echo "⚠️ .env.local non trouvé, utilisation de .env"
    set -a  # Export automatiquement toutes les variables définies
    source .env
    set +a
fi
python3 telegram_bot/main.py
