#!/usr/bin/env python3
"""
Show examples of parent events with child markets and standalone markets
"""
import asyncio
import os
from sqlalchemy import text
from core.database.connection import get_db

# Force local database
os.environ['DATABASE_URL'] = 'postgresql://postgres:postgres2025@localhost:5432/polycool_dev'

async def show_examples():
    async with get_db() as db:
        print('🎯 EXEMPLE 1: Événement parent avec 3 sous-marchés')
        print('=' * 60)

        # Trouver un événement avec plusieurs marchés
        result = await db.execute(text('''
            SELECT event_id, event_slug, event_title, COUNT(*) as market_count
            FROM markets
            WHERE event_id IS NOT NULL
            GROUP BY event_id, event_slug, event_title
            HAVING COUNT(*) >= 3
            ORDER BY market_count DESC
            LIMIT 5
        '''))

        events = result.fetchall()
        if events:
            # Prendre le premier événement avec le plus de marchés
            event = events[0]
            print(f'📊 Événement: {event[2]}')
            print(f'   Event ID: {event[0]}')
            print(f'   Event Slug: {event[1]}')
            print(f'   Nombre de marchés: {event[3]}')
            print(f'   URL: https://polymarket.com/event/{event[1]}')
            print()

            # Montrer 3 marchés de cet événement
            result = await db.execute(text('SELECT id, title, outcomes, outcome_prices, volume, is_resolved FROM markets WHERE event_id = :event_id ORDER BY volume DESC LIMIT 3'), {'event_id': event[0]})

            markets = result.fetchall()
            for i, market in enumerate(markets, 1):
                print(f'   📈 Marché {i}:')
                print(f'      ID: {market[0]}')
                print(f'      Titre: {market[1][:80]}...')
                print(f'      Outcomes: {market[2]}')
                print(f'      Prix: {market[3]}')
                print(f'      Volume: {market[4]}')
                print(f'      Résolu: {market[5]}')
                print()

        print()
        print('🎯 EXEMPLE 2: 3 marchés standalone (comme Zuckerberg)')
        print('=' * 60)

        # Trouver des marchés standalone (pas d'event_id ou event_id null)
        result = await db.execute(text('SELECT id, title, outcomes, outcome_prices, volume, is_resolved, event_id, polymarket_url FROM markets WHERE event_id IS NULL OR is_event_market = false ORDER BY volume DESC LIMIT 3'))

        standalone_markets = result.fetchall()
        for i, market in enumerate(standalone_markets, 1):
            print(f'   📈 Marché standalone {i}:')
            print(f'      ID: {market[0]}')
            print(f'      Titre: {market[1][:80]}...')
            print(f'      Outcomes: {market[2]}')
            print(f'      Prix: {market[3]}')
            print(f'      Volume: {market[4]}')
            print(f'      Résolu: {market[5]}')
            print(f'      Event ID: {market[6]}')
            if market[7]:
                print(f'      URL: {market[7]}')
            print()

        print()
        print('🎯 EXEMPLE 3: Marché Zuckerberg (spécifique)')
        print('=' * 60)

        # Montrer spécifiquement le marché Zuckerberg
        result = await db.execute(text('SELECT * FROM markets WHERE id = \'519276\''))
        zuckerberg = result.fetchone()
        if zuckerberg:
            print('   📈 Zuckerberg Divorce Market:')
            print(f'      ID: {zuckerberg.id}')
            print(f'      Titre: {zuckerberg.title}')
            print(f'      Description: {zuckerberg.description[:100] if zuckerberg.description else "None"}...')
            print(f'      Is Event Market: {zuckerberg.is_event_market}')
            print(f'      Parent Event ID: {zuckerberg.parent_event_id}')
            print(f'      Event Slug: {zuckerberg.event_slug}')
            print(f'      URL: {zuckerberg.polymarket_url}')
            print(f'      Outcomes: {zuckerberg.outcomes}')
            print(f'      Outcome Prices: {zuckerberg.outcome_prices}')
            print(f'      Volume: {zuckerberg.volume}')
            print(f'      Is Resolved: {zuckerberg.is_resolved}')

if __name__ == "__main__":
    asyncio.run(show_examples())
