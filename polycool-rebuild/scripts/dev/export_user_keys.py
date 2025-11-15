#!/usr/bin/env python3
"""
Script pour exporter les clés privées des utilisateurs depuis la base de données.
Utile pour la sauvegarde de sécurité des wallets.

Usage: python3 scripts/dev/export_user_keys.py [telegram_user_id]
"""

import asyncio
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database.connection import get_db
from core.services.encryption.encryption_service import EncryptionService
from sqlalchemy import text


async def export_user_keys(telegram_user_id: int = None):
    """Exporte les clés privées d'un utilisateur spécifique ou du premier utilisateur trouvé."""
    try:
        encryption_service = EncryptionService()

        async with get_db() as db:
            # Construire la requête
            if telegram_user_id:
                result = await db.execute(
                    text('SELECT telegram_user_id, username, polygon_address, polygon_private_key, solana_address, solana_private_key, created_at FROM users WHERE telegram_user_id = :user_id'),
                    {'user_id': telegram_user_id}
                )
            else:
                result = await db.execute(
                    text('SELECT telegram_user_id, username, polygon_address, polygon_private_key, solana_address, solana_private_key, created_at FROM users LIMIT 1')
                )

            user_data = result.fetchone()

            if not user_data:
                suffix = f" avec l'ID {telegram_user_id}" if telegram_user_id else ""
                print(f'❌ Aucun utilisateur trouvé{suffix}')
                return

            # Décrypter les clés privées
            polygon_key = encryption_service.decrypt_private_key(user_data.polygon_private_key)
            solana_key = encryption_service.decrypt_private_key(user_data.solana_private_key)

            # Préparer les données à exporter
            export_data = {
                'export_timestamp': datetime.utcnow().isoformat(),
                'telegram_user_id': user_data.telegram_user_id,
                'username': user_data.username,
                'created_at': user_data.created_at.isoformat() if user_data.created_at else None,
                'wallets': {
                    'polygon': {
                        'address': user_data.polygon_address,
                        'private_key': polygon_key,
                        'blockchain': 'Polygon (MATIC)',
                        'network': 'Mainnet'
                    },
                    'solana': {
                        'address': user_data.solana_address,
                        'private_key': solana_key,
                        'blockchain': 'Solana',
                        'network': 'Mainnet'
                    }
                },
                'security_notes': [
                    'Ces clés privées permettent l\'accès complet à vos fonds',
                    'Stockez-les dans un endroit sécurisé (coffre-fort numérique)',
                    'Ne partagez jamais ces clés avec qui que ce soit',
                    'Utilisez des mots de passe forts pour protéger ce fichier',
                    'Gardez plusieurs copies de sauvegarde'
                ]
            }

            # Créer le nom du fichier
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f'user_wallets_backup_{user_data.telegram_user_id}_{timestamp}.json'

            # Sauvegarder dans un fichier JSON
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            print(f'✅ Clés privées sauvegardées dans: {filename}')
            print()
            print('🔐 RÉSUMÉ DE SÉCURITÉ:')
            print(f'👤 Utilisateur: {user_data.username or "N/A"} (ID: {user_data.telegram_user_id})')
            print(f'🔷 Polygon: {user_data.polygon_address[:10]}...')
            print(f'🔶 Solana: {user_data.solana_address[:10]}...')
            print()
            print('⚠️  CONSERVATION:')
            print('- Stockez ce fichier dans un endroit sûr')
            print('- Utilisez un mot de passe fort')
            print('- Ne le partagez avec personne')
            print('- Gardez une copie de sauvegarde')
            print('- Le fichier est automatiquement exclu de git')

    except Exception as e:
        print(f'❌ Erreur: {e}')
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description='Exporter les clés privées des utilisateurs')
    parser.add_argument('telegram_user_id', nargs='?', type=int, help='ID Telegram de l\'utilisateur (optionnel)')

    args = parser.parse_args()
    asyncio.run(export_user_keys(args.telegram_user_id))


if __name__ == '__main__':
    main()
