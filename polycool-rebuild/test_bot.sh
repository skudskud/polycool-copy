#!/bin/bash
# Script rapide pour tester le bot

cd "$(dirname "$0")"

echo "🚀 Démarrage du bot Telegram..."
echo ""
echo "📊 Les logs s'affichent ci-dessous"
echo "💡 Teste avec /start dans Telegram"
echo "🛑 Ctrl+C pour arrêter"
echo ""

# Charger les variables d'environnement
if [ -f ".env.local" ]; then
    set -a
    source .env.local 2>/dev/null || true
    set +a
fi

# Lancer le bot
python3 telegram_bot/main.py
