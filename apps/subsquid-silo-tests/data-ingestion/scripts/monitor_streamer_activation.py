#!/usr/bin/env python3
"""
Script de monitoring rapide pour l'activation du streamer
Vérifie que le streamer fonctionne et mesure les performances
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid
from src.db.client import get_db_client, close_db_client


async def main():
    """Vérification rapide de l'activation du streamer"""
    try:
        print("\n" + "="*60)
        print("🚀 MONITORING ACTIVATION STREAMER")
        print("="*60)

        # Validation feature flag
        validate_experimental_subsquid()
        print("✅ Feature flag validé")

        # Connexion DB
        db = await get_db_client()
        print("✅ Connexion DB OK")

        # Test 1: Vérifier données WS
        print("\n🔍 TEST 1: Données WebSocket")
        print("-"*40)

        ws_data = await db.get_markets_ws(limit=5)
        if ws_data:
            print(f"✅ {len(ws_data)} marchés trouvés dans WS")
            for market in ws_data[:3]:
                mid = market.get('last_mid', 0)
                print(f"   - {market['market_id'][:20]}...: ${mid:.4f}")
        else:
            print("❌ Aucune donnée WS trouvée")
            print("   → Le streamer n'est peut-être pas encore actif")
            return

        # Test 2: Fraîcheur des données
        print("\n📈 TEST 2: Fraîcheur des données")
        print("-"*40)

        freshness = await db.calculate_freshness_ws()
        if freshness:
            p95 = freshness.get('p95_freshness_seconds', 0)
            print(".2f"
            if p95 < 10:
                print("✅ EXCELLENT: Données temps réel !")
            elif p95 < 60:
                print("✅ BON: Données fraîches")
            else:
                print("⚠️ MOYEN: Données un peu vieilles")
        else:
            print("❌ Impossible de calculer la fraîcheur")

        # Test 3: Comparaison avec poller
        print("\n⚖️ TEST 3: Comparaison Poller vs Streamer")
        print("-"*40)

        poll_freshness = await db.calculate_freshness_poll()
        ws_freshness = await db.calculate_freshness_ws()

        if poll_freshness and ws_freshness:
            poll_p95 = poll_freshness.get('p95_freshness_seconds', 0)
            ws_p95 = ws_freshness.get('p95_freshness_seconds', 0)

            ratio = poll_p95 / ws_p95 if ws_p95 > 0 else 999
            print(".2f"            print(".2f"            print(".1f"
            if ratio > 5:
                print("🎯 EXCELLENT: Streamer ×6+ plus rapide !")
            elif ratio > 2:
                print("✅ BON: Streamer ×2+ plus rapide")
            else:
                print("⚠️ MOYEN: Amélioration limitée")

        # Résumé
        print("\n" + "="*60)
        print("📋 RÉSUMÉ ACTIVATION")
        print("="*60)

        if ws_data and ws_freshness:
            p95 = ws_freshness.get('p95_freshness_seconds', 0)
            if p95 < 10:
                print("🎉 SUCCÈS TOTAL: Streamer actif avec données temps réel!")
                print("   → Bot devrait maintenant être ultra-rapide")
            else:
                print("⚠️ PARTIEL: Streamer actif mais données pas ultra-fraîches")
        else:
            print("❌ ÉCHEC: Streamer pas encore actif")
            print("   → Vérifier les logs Railway")

        print("\n💡 PROCHAINES ÉTAPES:")
        print("   1. Tester les commands /markets, buy/sell")
        print("   2. Créer un TP/SL test pour vérifier la précision")
        print("   3. Monitor les performances 1h")

        print("\n" + "="*60 + "\n")

    except Exception as e:
        print(f"❌ ERREUR: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        await close_db_client()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Monitoring interrompu")
        sys.exit(0)
