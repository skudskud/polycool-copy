#!/usr/bin/env python3
"""
Bulk Re-verification Script for Stale CLOSED Markets

Purpose:
- One-time fix to re-verify the 10,833+ markets marked CLOSED with future end_dates
- Fetches fresh status from Gamma API and updates DB
- Complements PASS 2.75 in poller.py for immediate correction

Usage:
    python scripts/reverify_closed_markets.py [--limit LIMIT] [--dry-run]

Options:
    --limit LIMIT    Maximum number of markets to re-verify (default: all)
    --dry-run        Show what would be updated without making changes
    --batch-size N   Number of markets per batch (default: 50)

Example:
    # Dry run to see what would be updated
    python scripts/reverify_closed_markets.py --dry-run --limit 100

    # Re-verify all stale CLOSED markets
    python scripts/reverify_closed_markets.py

    # Re-verify first 1000 markets only
    python scripts/reverify_closed_markets.py --limit 1000
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any
import httpx

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.client import get_db_client
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def fetch_market_from_api(client: httpx.AsyncClient, market_id: str) -> Dict[str, Any]:
    """Fetch market data from Gamma API"""
    url = f"https://gamma-api.polymarket.com/markets/{market_id}"
    try:
        response = await client.get(url, timeout=10.0)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            logger.warning(f"⚠️ Rate limited - waiting 2s")
            await asyncio.sleep(2.0)
            return None
        else:
            logger.debug(f"⚠️ API returned {response.status_code} for market {market_id}")
            return None
    except Exception as e:
        logger.debug(f"⚠️ Error fetching market {market_id}: {e}")
        return None


async def reverify_batch(
    client: httpx.AsyncClient,
    markets: List[Dict],
    dry_run: bool = False
) -> tuple[int, int, int]:
    """
    Re-verify a batch of markets

    Returns:
        (reopened_count, still_closed_count, errors_count)
    """
    reopened_count = 0
    still_closed_count = 0
    errors_count = 0

    updates_to_apply = []

    for market_row in markets:
        market_id = market_row['market_id']
        old_status = market_row['status']

        # Fetch fresh data from API
        market_data = await fetch_market_from_api(client, market_id)

        if not market_data:
            errors_count += 1
            continue

        # Check new status from API
        is_closed = market_data.get('closed', False)
        new_status = 'CLOSED' if is_closed else 'ACTIVE'

        if new_status == 'ACTIVE' and old_status == 'CLOSED':
            reopened_count += 1
            logger.info(f"✅ Market {market_id} REOPENED: '{market_data.get('question', '')[:60]}...'")
            updates_to_apply.append({
                'market_id': market_id,
                'status': new_status,
                'accepting_orders': market_data.get('acceptingOrders', False),
                'tradeable': market_data.get('active', False),
            })
        elif new_status == 'CLOSED':
            still_closed_count += 1
            logger.debug(f"📊 Market {market_id} still CLOSED (verified)")

        # Rate limiting - 5 requests per second
        await asyncio.sleep(0.2)

    # Apply updates to DB
    if updates_to_apply and not dry_run:
        db = await get_db_client()
        async with db.pool.acquire() as conn:
            for update in updates_to_apply:
                await conn.execute("""
                    UPDATE subsquid_markets_poll
                    SET status = $1,
                        accepting_orders = $2,
                        tradeable = $3,
                        updated_at = $4
                    WHERE market_id = $5
                """,
                    update['status'],
                    update['accepting_orders'],
                    update['tradeable'],
                    datetime.now(timezone.utc),
                    update['market_id']
                )
        logger.info(f"💾 Updated {len(updates_to_apply)} markets in database")
    elif dry_run and updates_to_apply:
        logger.info(f"🔍 [DRY RUN] Would update {len(updates_to_apply)} markets")

    return reopened_count, still_closed_count, errors_count


async def main():
    parser = argparse.ArgumentParser(description='Re-verify stale CLOSED markets from Gamma API')
    parser.add_argument('--limit', type=int, default=None, help='Maximum markets to process')
    parser.add_argument('--dry-run', action='store_true', help='Show updates without applying them')
    parser.add_argument('--batch-size', type=int, default=50, help='Markets per batch')
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("🔄 BULK RE-VERIFICATION: Stale CLOSED Markets")
    logger.info("=" * 80)
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be made")

    # Get database connection
    db = await get_db_client()

    # Query stale CLOSED markets
    async with db.pool.acquire() as conn:
        query = """
            SELECT market_id, status, title, end_date, updated_at
            FROM subsquid_markets_poll
            WHERE status = 'CLOSED'
            AND end_date > NOW()
            AND updated_at < NOW() - INTERVAL '7 days'
            ORDER BY end_date ASC
        """

        if args.limit:
            query += f" LIMIT {args.limit}"

        rows = await conn.fetch(query)

    total_markets = len(rows)
    logger.info(f"📊 Found {total_markets} stale CLOSED markets to re-verify")

    if total_markets == 0:
        logger.info("✅ No markets to process")
        return

    # Process in batches
    total_reopened = 0
    total_still_closed = 0
    total_errors = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, total_markets, args.batch_size):
            batch = rows[i:i + args.batch_size]
            batch_num = i // args.batch_size + 1
            total_batches = (total_markets + args.batch_size - 1) // args.batch_size

            logger.info(f"📦 Processing batch {batch_num}/{total_batches} ({len(batch)} markets)...")

            reopened, still_closed, errors = await reverify_batch(client, batch, args.dry_run)

            total_reopened += reopened
            total_still_closed += still_closed
            total_errors += errors

            # Progress summary
            logger.info(f"✅ Batch {batch_num} complete: {reopened} reopened, {still_closed} still closed, {errors} errors")

            # Rate limiting between batches
            if i + args.batch_size < total_markets:
                await asyncio.sleep(1.0)

    # Final summary
    logger.info("=" * 80)
    logger.info("📊 FINAL SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total markets processed: {total_markets}")
    logger.info(f"✅ Markets REOPENED (CLOSED → ACTIVE): {total_reopened}")
    logger.info(f"📊 Markets still CLOSED (verified): {total_still_closed}")
    logger.info(f"❌ Errors: {total_errors}")

    if args.dry_run:
        logger.info("")
        logger.info("🔍 This was a DRY RUN - no changes were made")
        logger.info("Run without --dry-run to apply updates")
    else:
        logger.info("")
        logger.info("✅ Database updated successfully!")
        logger.info("💡 PASS 2.75 in poller.py will continue to maintain these updates")

    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⏹️ Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
