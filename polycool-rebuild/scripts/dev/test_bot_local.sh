#!/bin/bash
# Test suite pour le bot Telegram en local
# Usage: bash scripts/dev/test_bot_local.sh

set -e

cd "$(dirname "$0")/../.."

echo "🧪 Test Suite - Bot Telegram Local"
echo "===================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Phase 1: Vérification Pré-Démarrage
echo "📋 Phase 1: Vérification Pré-Démarrage"
echo "----------------------------------------"

# Check Python
echo -n "1. Python version... "
python_version=$(python3 --version 2>&1 | awk '{print $2}')
if [[ $(echo "$python_version 3.9" | awk '{print ($1 >= $2)}') == 1 ]]; then
    echo -e "${GREEN}✅${NC} Python $python_version"
else
    echo -e "${YELLOW}⚠️${NC}  Python $python_version (3.9+ recommandé)"
fi

# Check .env
echo -n "2. Fichier .env... "
if [[ -f ".env" ]]; then
    echo -e "${GREEN}✅${NC} Existe"

    # Check required vars
    missing_vars=()
    if ! grep -q "BOT_TOKEN" .env 2>/dev/null; then missing_vars+=("BOT_TOKEN"); fi
    if ! grep -q "DATABASE_URL" .env 2>/dev/null; then missing_vars+=("DATABASE_URL"); fi
    if ! grep -q "ENCRYPTION_KEY" .env 2>/dev/null; then missing_vars+=("ENCRYPTION_KEY"); fi

    if [[ ${#missing_vars[@]} -eq 0 ]]; then
        echo -e "   ${GREEN}✅${NC} Variables requises présentes"
    else
        echo -e "   ${RED}❌${NC} Variables manquantes: ${missing_vars[*]}"
    fi
else
    echo -e "${RED}❌${NC} Non trouvé (copier depuis env.template)"
fi

# Check dependencies
echo -n "3. Dépendances... "
if python3 -c "import fastapi, telegram, sqlalchemy, websockets, redis, cryptography" 2>/dev/null; then
    echo -e "${GREEN}✅${NC} Installées"
else
    echo -e "${YELLOW}⚠️${NC}  Certaines manquantes (pip install -r requirements.txt)"
fi

# Test imports
echo -n "4. Imports... "
if python3 scripts/dev/test_imports.py >/dev/null 2>&1; then
    echo -e "${GREEN}✅${NC} OK"
else
    echo -e "${RED}❌${NC} Erreurs détectées"
    echo "   Lancer: python3 scripts/dev/test_imports.py"
fi

echo ""

# Phase 2: Tests Unitaires
echo "📋 Phase 2: Tests Unitaires"
echo "----------------------------------------"

if python3 scripts/dev/quick_test.py >/dev/null 2>&1; then
    echo -e "${GREEN}✅${NC} Tests rapides passent"
else
    echo -e "${RED}❌${NC} Tests rapides échouent"
    python3 scripts/dev/quick_test.py
fi

echo ""

# Phase 3: Instructions Démarrage
echo "📋 Phase 3: Instructions pour Tester le Bot"
echo "----------------------------------------"
echo ""
echo "1. Démarrer le bot:"
echo "   ${YELLOW}python3 main.py${NC}"
echo "   OU"
echo "   ${YELLOW}uvicorn telegram_bot.main:app --reload --port 8000${NC}"
echo ""
echo "2. Vérifier les logs au démarrage:"
echo "   - ✅ 'Telegram bot initialized successfully'"
echo "   - ✅ 'Starting Telegram bot...'"
echo "   - ⚠️  Si erreur: vérifier imports dans telegram_bot/main.py"
echo ""
echo "3. Tester dans Telegram:"
echo "   - Envoyer ${YELLOW}/start${NC} → Devrait créer user + wallets"
echo "   - Envoyer ${YELLOW}/wallet${NC} → Devrait afficher wallets"
echo "   - Envoyer ${YELLOW}/markets${NC} → 'To be implemented'"
echo ""
echo "4. Vérifier en DB:"
echo "   - User créé avec stage='onboarding'"
echo "   - Wallets générés (Polygon + Solana)"
echo "   - Clés privées encryptées"
echo ""
echo "5. Tester callbacks:"
echo "   - Cliquer sur boutons → Rien ne se passe (normal, pas implémentés)"
echo ""

# Phase 4: Checklist
echo "📋 Phase 4: Checklist de Vérification"
echo "----------------------------------------"
echo ""
echo "Avant de démarrer:"
echo "  [ ] .env configuré avec BOT_TOKEN, DATABASE_URL, ENCRYPTION_KEY"
echo "  [ ] STREAMER_ENABLED=false (ou corriger imports)"
echo "  [ ] INDEXER_ENABLED=false (pas encore implémenté)"
echo "  [ ] Database accessible"
echo "  [ ] Redis accessible (ou désactiver cache)"
echo ""
echo "Pendant les tests:"
echo "  [ ] Bot démarre sans erreur"
echo "  [ ] /start crée user en DB"
echo "  [ ] /wallet affiche adresses"
echo "  [ ] Callbacks ne causent pas d'erreurs"
echo ""

echo -e "${GREEN}✅${NC} Test suite terminée!"
echo ""
echo "Pour plus de détails, voir: docs/STATUS_RECAP.md"
