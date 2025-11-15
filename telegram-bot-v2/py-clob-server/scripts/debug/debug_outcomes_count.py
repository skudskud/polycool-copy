#!/usr/bin/env python3
"""
Débugger pourquoi 9 outcomes affichés au lieu de 64 dans /markets
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import asyncio
from market_database import MarketDatabase
from core.services.market_grouping_service import MarketGroupingService

async def debug():
    print("="*80)
    print("DEBUG: Pourquoi 9 outcomes affichés au lieu de 64 ?")
    print("="*80)

    market_db = MarketDatabase()
    grouping_service = MarketGroupingService()

    # Simuler _get_filtered_markets
    print("\n1️⃣ Get all active markets...")
    all_markets = market_db.get_high_volume_markets(limit=500)
    print(f"   ✅ {len(all_markets)} markets total")

    # Compter marchés Poker
    poker_markets = [m for m in all_markets if m.get('event_id') == '35532']
    print(f"   🎰 Poker markets: {len(poker_markets)}")

    # Créer la liste combinée
    print("\n2️⃣ Create combined list (with grouping)...")
    combined_list = grouping_service.create_combined_list(all_markets)
    print(f"   ✅ {len(combined_list)} items in combined list")

    # Trouver le groupe Poker
    poker_group = None
    for item in combined_list:
        if item.get('event_id') == '35532':
            poker_group = item
            break

    if poker_group:
        print(f"\n3️⃣ Poker group trouvé:")
        print(f"   Event ID: {poker_group.get('event_id')}")
        print(f"   Event Title: {poker_group.get('event_title')}")
        print(f"   Type: {poker_group.get('type')}")

        # Vérifier outcomes
        outcomes = poker_group.get('outcomes', [])
        print(f"   📊 Outcomes in group: {len(outcomes)}")

        # Vérifier market_ids
        market_ids = poker_group.get('market_ids', [])
        print(f"   📊 Market IDs in group: {len(market_ids)}")

        # Vérifier markets
        markets = poker_group.get('markets', [])
        print(f"   📊 Markets in group: {len(markets)}")

        if len(outcomes) != len(poker_markets):
            print(f"\n   ❌ PROBLÈME: {len(outcomes)} outcomes vs {len(poker_markets)} markets!")
            print(f"      Cause probable: calculate_group_stats() reçoit seulement {len(markets)} markets")
            print(f"      au lieu des {len(poker_markets)} disponibles")
        else:
            print(f"\n   ✅ OK: {len(outcomes)} outcomes = {len(poker_markets)} markets")

        # Afficher quelques outcomes
        print(f"\n   📋 Premiers outcomes:")
        for i, outcome in enumerate(outcomes[:5], 1):
            print(f"      {i}. {outcome.get('title', 'N/A')[:60]}")
            print(f"         Price: {outcome.get('price')}, Vol: ${outcome.get('volume', 0):,.0f}")
    else:
        print(f"\n❌ Groupe Poker NON TROUVÉ dans combined_list")

    print("\n" + "="*80)

asyncio.run(debug())
