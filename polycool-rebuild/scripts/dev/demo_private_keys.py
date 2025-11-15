#!/usr/bin/env python3
"""
Démonstration de la fonctionnalité d'affichage des clés privées avec auto-destruction
"""

import asyncio
import sys
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from telegram_bot.handlers.wallet.view import (
    handle_show_polygon_key_callback,
    handle_show_solana_key_callback
)
from unittest.mock import AsyncMock, MagicMock


async def demo_private_keys():
    """Démontre la fonctionnalité d'affichage des clés privées"""
    print("🔐 DÉMONSTRATION - Clés Privées avec Auto-Destruction")
    print("=" * 60)

    # Créer un mock update/callback pour Polygon
    print("\n🔷 Test affichage clé Polygon:")

    update = MagicMock()
    query = MagicMock()
    query.from_user.id = 6500527972
    query.answer = AsyncMock()
    query.message.reply_text = AsyncMock()
    query.message.reply_text.return_value = MagicMock(message_id=123)

    update.callback_query = query
    context = MagicMock()

    try:
        await handle_show_polygon_key_callback(update, context)
        print("✅ Callback Polygon traité avec succès")
        print("📱 Un message avec la clé privée aurait dû être envoyé")
        print("⏰ Ce message s'autodétruira après 10 secondes")
        print("🔘 Un bouton '❌ Hide Key' permet de le cacher manuellement")
    except Exception as e:
        print(f"❌ Erreur: {e}")

    # Créer un mock update/callback pour Solana
    print("\n🔶 Test affichage clé Solana:")

    query2 = MagicMock()
    query2.from_user.id = 6500527972
    query2.answer = AsyncMock()
    query2.message.reply_text = AsyncMock()
    query2.message.reply_text.return_value = MagicMock(message_id=124)

    update2 = MagicMock()
    update2.callback_query = query2
    context2 = MagicMock()

    try:
        await handle_show_solana_key_callback(update2, context2)
        print("✅ Callback Solana traité avec succès")
        print("📱 Un message avec la clé privée aurait dû être envoyé")
        print("⏰ Ce message s'autodétruira après 10 secondes")
        print("🔘 Un bouton '❌ Hide Key' permet de le cacher manuellement")
    except Exception as e:
        print(f"❌ Erreur: {e}")

    print("\n" + "=" * 60)
    print("🎯 COMMENT UTILISER DANS LE BOT:")
    print("1. Envoyer /wallet au bot")
    print("2. Cliquer sur '🔑 Show Polygon Key' ou '🔑 Show Solana Key'")
    print("3. La clé apparaît dans un message séparé")
    print("4. Après 10 secondes, le message disparaît automatiquement")
    print("5. Ou cliquer sur '❌ Hide Key' pour le cacher immédiatement")
    print("\n⚠️  SÉCURITÉ:")
    print("- Les clés sont déchiffrées uniquement à la demande")
    print("- Elles sont affichées dans un message séparé (pas dans l'historique)")
    print("- Auto-destruction empêche les captures accidentelles")
    print("- Accès loggé pour audit de sécurité")


if __name__ == '__main__':
    asyncio.run(demo_private_keys())
