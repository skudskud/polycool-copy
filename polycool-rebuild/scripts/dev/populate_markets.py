#!/usr/bin/env python3
"""
Populate markets table with Polymarket data - Progressive approach
Fills markets in batches to avoid API rate limits and timeouts
"""
import asyncio
import json
import os
from typing import List, Dict
import httpx
from sqlalchemy import text
from core.database.connection import get_db
from infrastructure.config.settings import settings

# Force local database
os.environ['DATABASE_URL'] = 'postgresql://postgres:postgres2025@localhost:5432/polycool_dev'

class MarketPopulator:
    """Progressive market populator"""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.base_url = settings.polymarket.gamma_api_base
        self.batch_size = 50  # Markets per batch
        self.max_events = 500  # Events to process

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def get_current_count(self) -> int:
        """Get current markets count"""
        async with get_db() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM markets"))
            return result.fetchone()[0]

    async def fetch_events_batch(self, offset: int = 0, limit: int = 100) -> List[Dict]:
        """Fetch events from Gamma API"""
        url = f"{self.base_url}/events?limit={limit}&offset={offset}&order=id&ascending=false"
        print(f"📡 Fetching events: {url}")

        response = await self.client.get(url)
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            return []

        return response.json()

    def extract_markets_from_events(self, events: List[Dict]) -> List[Dict]:
        """Extract and enrich markets from events"""
        all_markets = []

        for event in events:
            event_id = event.get('id')
            event_slug = event.get('slug')
            event_title = event.get('title')

            markets = event.get('markets', [])
            for market in markets:
                # Enrich with event data
                enriched_market = market.copy()
                enriched_market.update({
                    'event_id': str(event_id),
                    'event_slug': event_slug,
                    'event_title': event_title,
                    'is_event_market': True,
                    'parent_event_id': str(event_id),
                    'polymarket_url': f"https://polymarket.com/event/{event_slug}"
                })
                all_markets.append(enriched_market)

        print(f"📦 Extracted {len(all_markets)} markets from {len(events)} events")
        return all_markets

    async def upsert_markets_batch(self, markets: List[Dict]) -> int:
        """Upsert markets batch to database"""
        if not markets:
            return 0

        upserted = 0
        async with get_db() as db:
            for market in markets:
                try:
                    # Prepare data for insertion
                    outcomes = market.get('outcomes', [])
                    outcome_prices = market.get('outcomePrices', [])

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
                        'volume': market.get('volume', 0),
                        'last_trade_price': market.get('lastTradePrice'),
                        'clob_token_ids': json.dumps(market.get('clobTokenIds', [])),
                        'is_resolved': market.get('resolvedBy') is not None,
                        'resolved_outcome': market.get('resolvedBy', {}).get('outcome') if market.get('resolvedBy') else None,
                        'event_id': market.get('event_id'),
                        'event_slug': market.get('event_slug'),
                        'event_title': market.get('event_title'),
                        'polymarket_url': market.get('polymarket_url')
                    })
                    upserted += 1

                except Exception as e:
                    print(f"⚠️ Failed to upsert market {market.get('id')}: {e}")

        return upserted

    async def populate_batch(self, batch_num: int) -> bool:
        """Populate one batch of markets"""
        offset = batch_num * self.batch_size
        limit = min(self.batch_size, self.max_events - offset)

        if limit <= 0:
            return False

        print(f"\n🔄 Batch {batch_num + 1}: Processing events {offset}-{offset + limit - 1}")

        # Fetch events
        events = await self.fetch_events_batch(offset, limit)
        if not events:
            print("❌ No more events to process")
            return False

        # Extract markets
        markets = self.extract_markets_from_events(events)
        if not markets:
            print("⚠️ No markets extracted from this batch")
            return True  # Continue to next batch

        # Split markets into smaller chunks for upsert
        chunk_size = 10
        total_upserted = 0

        for i in range(0, len(markets), chunk_size):
            chunk = markets[i:i + chunk_size]
            upserted = await self.upsert_markets_batch(chunk)
            total_upserted += upserted
            print(f"  ✅ Upserted chunk {i//chunk_size + 1}: {upserted} markets")

        print(f"📊 Batch {batch_num + 1} complete: {total_upserted} markets upserted")
        return True

    async def populate_all(self):
        """Populate all markets progressively"""
        print("🚀 Starting progressive market population...")
        print(f"📊 Batch size: {self.batch_size} markets per batch")

        initial_count = await self.get_current_count()
        print(f"📈 Initial markets count: {initial_count}")

        batch_num = 0
        while batch_num < 20:  # Max 20 batches
            success = await self.populate_batch(batch_num)
            if not success:
                break

            batch_num += 1

            # Progress check
            current_count = await self.get_current_count()
            print(f"📈 Current total: {current_count} markets")

        final_count = await self.get_current_count()
        added = final_count - initial_count
        print(f"\n🎉 Population complete!")
        print(f"📊 Added {added} markets (Total: {final_count})")

async def main():
    """Main population script"""
    async with MarketPopulator() as populator:
        await populator.populate_all()

if __name__ == "__main__":
    asyncio.run(main())
