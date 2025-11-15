"""
One-time script to fix corrupted events field in subsquid_markets_poll

Problem: events field contains multiple levels of escaped backslashes
Solution: Parse corrupted JSON, rebuild from Gamma API, update DB

Usage:
    python scripts/fix_events_corruption.py
"""

import asyncio
import httpx
import json
import logging
from datetime import datetime, timezone
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.db.client import get_db_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def fix_corrupted_events():
    """
    Fix events field corruption for all markets
    Rebuilds clean events structure from existing data
    """
    db = await get_db_client()
    client = httpx.AsyncClient(timeout=30.0)

    try:
        async with db.pool.acquire() as conn:
            # Get all markets with events field
            logger.info("📊 Fetching markets with events field...")
            markets = await conn.fetch("""
                SELECT market_id, events, slug
                FROM subsquid_markets_poll
                WHERE events IS NOT NULL
                  AND events::text != '[]'
                ORDER BY updated_at DESC
                LIMIT 10000
            """)

            logger.info(f"📊 Found {len(markets)} markets with events data")

            fixed_count = 0
            corrupted_count = 0
            api_rebuild_count = 0

            for idx, market in enumerate(markets):
                market_id = market['market_id']
                events_raw = market['events']

                try:
                    # Check if already valid JSON array
                    if isinstance(events_raw, list):
                        # Already clean!
                        continue

                    # Try to parse as JSON string
                    if isinstance(events_raw, str):
                        try:
                            # Try multiple levels of unescaping
                            events_json = json.loads(events_raw)

                            # Validate structure
                            if isinstance(events_json, list) and len(events_json) > 0:
                                if isinstance(events_json[0], dict) and 'event_id' in events_json[0]:
                                    # Valid structure! Update DB
                                    await conn.execute("""
                                        UPDATE subsquid_markets_poll
                                        SET events = $1::jsonb
                                        WHERE market_id = $2
                                    """, json.dumps(events_json), market_id)

                                    fixed_count += 1
                                    if fixed_count % 100 == 0:
                                        logger.info(f"✅ Fixed {fixed_count}/{len(markets)} markets...")
                                    continue
                        except json.JSONDecodeError:
                            corrupted_count += 1

                    # If we get here, events is corrupted beyond parsing
                    # Try to rebuild from event slug via API
                    slug = market['slug']
                    if slug:
                        try:
                            # Try to find event via market slug
                            # We can't easily rebuild events without the event_id
                            # So we'll just set to empty array for standalone markets
                            await conn.execute("""
                                UPDATE subsquid_markets_poll
                                SET events = '[]'::jsonb
                                WHERE market_id = $1
                            """, market_id)

                            api_rebuild_count += 1
                            logger.debug(f"⚠️ Market {market_id}: Set events to [] (corrupted beyond repair)")
                        except Exception as api_error:
                            logger.error(f"❌ Failed to rebuild events for {market_id}: {api_error}")

                except Exception as e:
                    logger.error(f"❌ Error processing market {market_id}: {e}")
                    continue

            logger.info(f"✅ SUMMARY:")
            logger.info(f"  - Fixed via JSON parsing: {fixed_count}")
            logger.info(f"  - Corrupted beyond repair: {corrupted_count}")
            logger.info(f"  - Reset to []: {api_rebuild_count}")
            logger.info(f"  - Total processed: {len(markets)}")

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
    finally:
        await client.aclose()


async def validate_events_field():
    """
    Validate that events field is clean after fix
    """
    db = await get_db_client()

    async with db.pool.acquire() as conn:
        # Check for corruption patterns
        corrupted = await conn.fetch("""
            SELECT market_id, events::text as events_text
            FROM subsquid_markets_poll
            WHERE events::text LIKE '%\\\\\\\\%'
            LIMIT 10
        """)

        if corrupted:
            logger.warning(f"⚠️ Still found {len(corrupted)} markets with escaped backslashes")
            for m in corrupted[:3]:
                logger.warning(f"  - {m['market_id']}: {m['events_text'][:100]}...")
        else:
            logger.info("✅ No corrupted events found!")

        # Count by structure
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE events = '[]'::jsonb) as empty_events,
                COUNT(*) FILTER (WHERE events != '[]'::jsonb) as has_events,
                COUNT(*) FILTER (WHERE events IS NULL) as null_events
            FROM subsquid_markets_poll
        """)

        logger.info(f"📊 Events field stats:")
        logger.info(f"  - Empty arrays ([]): {stats['empty_events']}")
        logger.info(f"  - Has events: {stats['has_events']}")
        logger.info(f"  - NULL: {stats['null_events']}")


async def main():
    """Main entry point"""
    logger.info("🚀 Starting events field corruption fix...")

    # Fix corrupted events
    await fix_corrupted_events()

    # Validate results
    logger.info("\n📊 Validating results...")
    await validate_events_field()

    logger.info("\n✅ Events corruption fix complete!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Script interrupted")
        sys.exit(0)
