#!/bin/bash
# Script pour voir les logs (si redirigés vers un fichier)

cd "$(dirname "$0")"

LOG_FILE="${1:-logs/polycool.log}"

if [ ! -f "$LOG_FILE" ]; then
    echo "⚠️  Fichier de log non trouvé: $LOG_FILE"
    echo ""
    echo "💡 Les logs s'affichent directement dans le terminal où le bot tourne."
    echo "   Pas besoin de script séparé pour voir les logs."
    echo ""
    echo "📝 Pour rediriger les logs vers un fichier:"
    echo "   python3 telegram_bot/main.py > bot.log 2>&1"
    exit 1
fi

echo "📊 Affichage des logs depuis: $LOG_FILE"
echo "🛑 Ctrl+C pour arrêter"
echo ""

tail -f "$LOG_FILE"
