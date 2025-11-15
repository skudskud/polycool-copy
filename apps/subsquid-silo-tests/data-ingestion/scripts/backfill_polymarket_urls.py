"""
One-time script to backfill polymarket_url for existing markets

Generates URLs from slug and events data:
- Event markets: https://polymarket.com/event/{event_slug}
- Standalone markets: https://polymarket.com/market/{market_slug}

Usage:
    python scripts/backfill_polymarket_urls.py
"""

import asyncio
import logging
import sys
import os
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db.client import get_db_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def backfill_polymarket_urls():
    """
    Generate polymarket_url for all markets
    Priority: event_slug > market_slug
    """
    db = await get_db_client()

    try:
        async with db.pool.acquire() as conn:
            # Get all markets without URL
            logger.info("📊 Fetching markets without polymarket_url...")
            markets = await conn.fetch("""
                SELECT market_id, slug, events
                FROM subsquid_markets_poll
                WHERE polymarket_url IS NULL OR polymarket_url = ''
                ORDER BY volume DESC
            """)

            logger.info(f"📊 Found {len(markets)} markets without URLs")

            updated_count = 0
            event_url_count = 0
            market_url_count = 0
            no_slug_count = 0

            # Process in batches
            batch_size = 100
            for i in range(0, len(markets), batch_size):
                batch = markets[i:i + batch_size]

                for market in batch:
                    market_id = market['market_id']
                    slug = market['slug']
                    events = market['events']

                    url = ""

                    try:
                        # Priority 1: Event URL
                        if events:
                            # Parse events if it's a string
                            if isinstance(events, str):
                                try:
                                    events = json.loads(events)
                                except:
                                    events = []

                            # Extract event_slug
                            if isinstance(events, list) and len(events) > 0:
                                event_data = events[0]
                                if isinstance(event_data, dict):
                                    event_slug = event_data.get('event_slug')
                                    if event_slug:
                                        url = f"https://polymarket.com/event/{event_slug}"
                                        event_url_count += 1

                        # Priority 2: Market URL (if no event)
                        if not url and slug:
                            url = f"https://polymarket.com/market/{slug}"
                            market_url_count += 1

                        # Update if URL was generated
                        if url:
                            await conn.execute("""
                                UPDATE subsquid_markets_poll
                                SET polymarket_url = $1
                                WHERE market_id = $2
                            """, url, market_id)

                            updated_count += 1
                        else:
                            no_slug_count += 1
                            logger.debug(f"⚠️ Market {market_id}: No slug available")

                    except Exception as e:
                        logger.error(f"❌ Error processing market {market_id}: {e}")
                        continue

                # Progress log
                if (i + batch_size) % 1000 == 0:
                    logger.info(f"✅ Processed {i + batch_size}/{len(markets)} markets...")

            logger.info(f"✅ SUMMARY:")
            logger.info(f"  - Total updated: {updated_count}")
            logger.info(f"  - Event URLs: {event_url_count}")
            logger.info(f"  - Market URLs: {market_url_count}")
            logger.info(f"  - No slug available: {no_slug_count}")

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)


async def validate_urls():
    """
    Validate URLs were generated correctly
    """
    db = await get_db_client()

    async with db.pool.acquire() as conn:
        # Count URL coverage
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE polymarket_url IS NOT NULL AND polymarket_url != '') as has_url,
                COUNT(*) FILTER (WHERE polymarket_url IS NULL OR polymarket_url = '') as missing_url,
                COUNT(*) FILTER (WHERE polymarket_url LIKE 'https://polymarket.com/event/%') as event_urls,
                COUNT(*) FILTER (WHERE polymarket_url LIKE 'https://polymarket.com/market/%') as market_urls
            FROM subsquid_markets_poll
            WHERE status = 'ACTIVE'
        """)

        logger.info(f"📊 URL Coverage Stats (ACTIVE markets):")
        logger.info(f"  - Total: {stats['total']}")
        logger.info(f"  - Has URL: {stats['has_url']} ({stats['has_url']/stats['total']*100:.1f}%)")
        logger.info(f"  - Missing URL: {stats['missing_url']}")
        logger.info(f"  - Event URLs: {stats['event_urls']}")
        logger.info(f"  - Market URLs: {stats['market_urls']}")

        # Show sample URLs
        samples = await conn.fetch("""
            SELECT market_id, title, polymarket_url
            FROM subsquid_markets_poll
            WHERE polymarket_url IS NOT NULL AND polymarket_url != ''
            ORDER BY volume DESC
            LIMIT 5
        """)

        logger.info(f"\n📋 Sample URLs (top 5 by volume):")
        for sample in samples:
            logger.info(f"  - {sample['title'][:60]}...")
            logger.info(f"    {sample['polymarket_url']}")


async def main():
    """Main entry point"""
    logger.info("🚀 Starting polymarket_url backfill...")

    # Backfill URLs
    await backfill_polymarket_urls()

    # Validate results
    logger.info("\n📊 Validating results...")
    await validate_urls()

    logger.info("\n✅ Polymarket URL backfill complete!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Script interrupted")
        sys.exit(0)
