#!/bin/bash
# Script de test sans reloader automatique

cd "$(dirname "$0")"

echo "🚀 Démarrage du bot SANS reloader automatique..."
echo ""
echo "📊 Les logs s'affichent ci-dessous"
echo "💡 Teste avec /start dans Telegram"
echo "🛑 Ctrl+C pour arrêter"
echo ""

# Charger les variables d'environnement
if [ -f ".env.local" ]; then
    export $(grep -v '^#' .env.local | grep -v '^$' | xargs 2>/dev/null)
fi

# Lancer le bot SANS reloader
python3 -c "
import uvicorn
from telegram_bot.main import app
uvicorn.run(app, host='0.0.0.0', port=8000, reload=False, log_level='info')
"
