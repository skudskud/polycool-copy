#!/usr/bin/env python3
"""
Script: Fix Empty Events
Fetches markets with empty/null events from DB, enriches them via Gamma API, and updates.
Runs locally - connects to Supabase directly.
"""

import asyncio
import sys
import httpx
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid
from src.db.client import get_db_client, close_db_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EventsFixer:
    """Fixes markets with empty/null events"""

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.fixed_count = 0
        self.failed_count = 0

    async def start(self):
        """Start fixing events"""
        self.client = httpx.AsyncClient(timeout=30.0)
        try:
            await self.fix_empty_events()
        finally:
            await self.stop()

    async def stop(self):
        """Stop service"""
        if self.client:
            await self.client.aclose()
        logger.info("✅ Fixer stopped")

    async def fix_empty_events(self):
        """Fetch and fix markets with empty events"""
        db = await get_db_client()

        try:
            logger.info("📊 Fetching markets with empty/null events...")

            # Get all markets with empty events
            import asyncpg
            query = """
            SELECT market_id, title FROM subsquid_markets_poll
            WHERE events IS NULL OR (jsonb_typeof(events) = 'array' AND jsonb_array_length(events) = 0)
            ORDER BY volume DESC
            """

            async with db.pool.acquire() as conn:
                rows = await conn.fetch(query)

            if not rows:
                logger.warning("⚠️ No markets with empty events found")
                return

            logger.info(f"📋 Found {len(rows)} markets with empty events")

            fixed_batch = []

            for i, row in enumerate(rows, 1):
                market_id = row['market_id']
                title = row['title']

                # Fetch from Gamma API
                events = await self._fetch_market_events(market_id)

                if events is not None:
                    fixed_batch.append({
                        'market_id': market_id,
                        'events': events
                    })
                    self.fixed_count += 1
                    logger.debug(f"✅ Fetched events for {market_id}")
                else:
                    self.failed_count += 1
                    logger.debug(f"❌ No events for {market_id}")

                # Batch update every 50 markets
                if len(fixed_batch) >= 50 or i == len(rows):
                    await self._batch_update_events(db, fixed_batch)
                    fixed_batch = []

                if i % 100 == 0:
                    logger.info(f"⏳ Processed {i}/{len(rows)} markets...")

                await asyncio.sleep(0.02)  # Rate limiting

            # Summary
            logger.info("\n" + "=" * 80)
            logger.info(f"✅ EVENTS FIXING COMPLETE")
            logger.info(f"   Fixed:   {self.fixed_count}")
            logger.info(f"   Failed:  {self.failed_count}")
            logger.info("=" * 80 + "\n")

        finally:
            await close_db_client()

    async def _fetch_market_events(self, market_id: str) -> Optional[List[Dict[str, Any]]]:
        """Fetch market events from Gamma API"""
        if not self.client or not market_id:
            return None

        url = f"{settings.GAMMA_API_URL}/{market_id}"

        try:
            response = await self.client.get(url, timeout=10.0)
            if response.status_code == 200:
                market = response.json()
                events = market.get("events", [])

                if events:
                    # Parse events
                    parsed_events = []
                    for event in events:
                        parsed_events.append({
                            "event_id": event.get("id"),
                            "event_slug": event.get("slug"),
                            "event_title": event.get("title"),
                            "event_category": event.get("category"),
                            "event_volume": round(float(event.get("volume", 0)), 4) if event.get("volume") else 0.0,
                        })
                    return parsed_events
        except asyncio.TimeoutError:
            logger.debug(f"⏱️ Timeout fetching {market_id}")
        except Exception as e:
            logger.debug(f"❌ Error fetching {market_id}: {e}")

        return None

    async def _batch_update_events(self, db, markets: List[Dict[str, Any]]) -> int:
        """Batch update events in DB"""
        if not markets:
            return 0

        updated = 0

        query = """
        UPDATE subsquid_markets_poll
        SET events = $1, updated_at = NOW()
        WHERE market_id = $2
        """

        try:
            async with db.pool.acquire() as conn:
                for market in markets:
                    events_json = json.dumps(market['events'])
                    await conn.execute(query, events_json, market['market_id'])
                    updated += 1

            logger.info(f"✅ Updated {updated} markets in DB")
            return updated
        except Exception as e:
            logger.error(f"❌ Batch update failed: {e}")
            return 0


async def main():
    """Main entry point"""
    try:
        print("\n" + "=" * 80)
        print("🚀 EVENTS FIXER SERVICE")
        print("Fixing markets with empty/null events...")
        print("=" * 80 + "\n")

        # Validate feature flag
        validate_experimental_subsquid()

        # Start fixer
        fixer = EventsFixer()
        await fixer.start()

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Interrupted")
        sys.exit(0)
