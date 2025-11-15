#!/usr/bin/env python3
"""
Populate a specific market with complete data from Polymarket API
"""
import asyncio
import json
import os
from typing import Dict
import httpx
from sqlalchemy import text
from core.database.connection import get_db
from infrastructure.config.settings import settings

# Force local database
os.environ['DATABASE_URL'] = 'postgresql://postgres:postgres2025@localhost:5432/polycool_dev'

async def fetch_market_from_event_slug(event_slug: str, market_id: str) -> Dict:
    """Fetch complete market data from event slug"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{settings.polymarket.gamma_api_base}/events/slug/{event_slug}"
        print(f"📡 Fetching event: {url}")

        response = await client.get(url)
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            return None

        event_data = response.json()
        markets = event_data.get('markets', [])

        # Find our specific market
        for market in markets:
            if str(market.get('id')) == str(market_id):
                # Enrich with event data
                enriched_market = market.copy()
                enriched_market.update({
                    'event_id': str(event_data.get('id')),
                    'event_slug': event_slug,
                    'event_title': event_data.get('title'),
                    'is_event_market': True,
                    'parent_event_id': str(event_data.get('id')),
                    'polymarket_url': f"https://polymarket.com/event/{event_slug}"
                })
                return enriched_market

        print(f"❌ Market {market_id} not found in event {event_slug}")
        return None

async def upsert_market(market: Dict) -> bool:
    """Upsert market to database"""
    async with get_db() as db:
        try:
            # Prepare data for insertion
            outcomes = market.get('outcomes', [])
            outcome_prices = market.get('outcomePrices', [])

            # Safely handle data types
            volume = market.get('volume', 0)
            if isinstance(volume, str):
                try:
                    volume = float(volume)
                except:
                    volume = 0

            last_trade_price = market.get('lastTradePrice')
            if isinstance(last_trade_price, str):
                try:
                    last_trade_price = float(last_trade_price)
                except:
                    last_trade_price = None

            await db.execute(text("""
                INSERT INTO markets (
                    id, source, title, description, category,
                    outcomes, outcome_prices, events,
                    is_event_market, parent_event_id,
                    volume, last_trade_price, clob_token_ids,
                    is_resolved, resolved_outcome,
                    event_id, event_slug, event_title, polymarket_url,
                    updated_at
                ) VALUES (
                    :id, 'poll', :title, :description, :category,
                    :outcomes, :outcome_prices, :events,
                    :is_event_market, :parent_event_id,
                    :volume, :last_trade_price, :clob_token_ids,
                    :is_resolved, :resolved_outcome,
                    :event_id, :event_slug, :event_title, :polymarket_url,
                    now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    outcomes = EXCLUDED.outcomes,
                    outcome_prices = EXCLUDED.outcome_prices,
                    volume = EXCLUDED.volume,
                    last_trade_price = EXCLUDED.last_trade_price,
                    is_resolved = EXCLUDED.is_resolved,
                    resolved_outcome = EXCLUDED.resolved_outcome,
                    event_id = EXCLUDED.event_id,
                    event_slug = EXCLUDED.event_slug,
                    event_title = EXCLUDED.event_title,
                    polymarket_url = EXCLUDED.polymarket_url,
                    updated_at = now()
            """), {
                'id': str(market.get('id')),
                'title': market.get('question', ''),
                'description': market.get('description'),
                'category': market.get('category'),
                'outcomes': outcomes,
                'outcome_prices': outcome_prices,
                'events': market.get('events'),
                'is_event_market': market.get('is_event_market', False),
                'parent_event_id': market.get('parent_event_id'),
                'volume': volume,
                'last_trade_price': last_trade_price,
                'clob_token_ids': json.dumps(market.get('clobTokenIds', [])),
                'is_resolved': market.get('resolvedBy') is not None,
                'resolved_outcome': None,  # Simplified for now
                'event_id': market.get('event_id'),
                'event_slug': market.get('event_slug'),
                'event_title': market.get('event_title'),
                'polymarket_url': market.get('polymarket_url')
            })

            print(f"✅ Successfully upserted market {market.get('id')}")
            return True

        except Exception as e:
            print(f"❌ Failed to upsert market {market.get('id')}: {e}")
            return False

async def populate_zuckerberg_market():
    """Populate the specific Zuckerberg market with complete data"""
    print("🎯 Populating Zuckerberg market with complete data...")

    market_id = '519276'
    event_slug = 'zuckerberg-divorce-in-2025'

    # Fetch complete data
    market_data = await fetch_market_from_event_slug(event_slug, market_id)

    if not market_data:
        print("❌ Could not fetch market data")
        return

    print("📊 Market data retrieved:")
    print(f"   Title: {market_data.get('question')}")
    print(f"   Description: {market_data.get('description')[:100] if market_data.get('description') else 'None'}...")
    print(f"   Category: {market_data.get('category')}")
    print(f"   Condition ID: {market_data.get('conditionId')}")
    print(f"   Start Date: {market_data.get('startDate')}")
    print(f"   End Date: {market_data.get('endDate')}")

    # Upsert to database
    success = await upsert_market(market_data)

    if success:
        print("🎉 Zuckerberg market successfully populated with complete data!")
    else:
        print("❌ Failed to populate Zuckerberg market")

async def main():
    await populate_zuckerberg_market()

if __name__ == "__main__":
    asyncio.run(main())
