#!/usr/bin/env python3
"""
Script to count standalone markets in Polymarket API
Compares markets from /events vs /markets to find standalone markets
"""
import asyncio
import httpx
from infrastructure.config.settings import settings
from infrastructure.logging.logger import setup_logging, get_logger

setup_logging(__name__)
logger = get_logger(__name__)


async def count_standalone_markets():
    """Count standalone markets (markets not in events)"""
    api_url = settings.polymarket.gamma_api_base
    client = httpx.AsyncClient(timeout=30.0)

    try:
        # Step 1: Get all market IDs from events
        logger.info("📦 Step 1: Fetching all events and their markets...")
        event_market_ids = set()
        all_events = []

        offset = 0
        limit = 200

        while True:
            response = await client.get(
                f"{api_url}/events",
                params={
                    'closed': False,
                    'offset': offset,
                    'limit': limit,
                    'order': 'volume',
                    'ascending': False
                }
            )
            response.raise_for_status()
            batch = response.json()

            if not batch or not isinstance(batch, list) or not batch:
                break

            all_events.extend(batch)

            # Extract market IDs from events
            for event in batch:
                markets = event.get('markets', [])
                for market in markets:
                    market_id = market.get('id')
                    if market_id:
                        event_market_ids.add(str(market_id))

            logger.info(f"📦 Processed {len(all_events)} events, found {len(event_market_ids)} markets in events")

            if len(batch) < limit:
                break

            offset += limit
            await asyncio.sleep(0.5)  # Rate limiting

        logger.info(f"✅ Step 1 complete: {len(all_events)} events, {len(event_market_ids)} markets in events")

        # Step 2: Get all markets from /markets endpoint
        logger.info("📦 Step 2: Fetching all markets from /markets endpoint...")
        all_market_ids = set()
        standalone_market_ids = set()
        total_markets_fetched = 0

        offset = 0
        limit = 500
        max_iterations = 200  # Safety limit

        iteration = 0
        while iteration < max_iterations:
            response = await client.get(
                f"{api_url}/markets",
                params={
                    'closed': False,
                    'offset': offset,
                    'limit': limit,
                    'order': 'volumeNum',
                    'ascending': False
                }
            )
            response.raise_for_status()
            batch = response.json()

            if not batch or not isinstance(batch, list) or not batch:
                break

            for market in batch:
                market_id = str(market.get('id', ''))
                if market_id:
                    all_market_ids.add(market_id)
                    total_markets_fetched += 1

                    # Check if standalone
                    events_data = market.get('events', [])
                    is_in_events = market_id in event_market_ids
                    has_no_events = not events_data or len(events_data) == 0

                    # Standalone = not in our events list AND (no events field OR empty events)
                    # OR not in events list (might be in an event we didn't fetch)
                    if not is_in_events:
                        if has_no_events:
                            # Definitely standalone
                            standalone_market_ids.add(market_id)
                        else:
                            # Has events but not in our list - might be standalone or new event
                            # Check if event_id is None or empty
                            event_id = market.get('event_id')
                            if not event_id:
                                standalone_market_ids.add(market_id)

            logger.info(f"📦 Batch {iteration + 1}: {len(batch)} markets, {len(standalone_market_ids)} standalone so far")

            if len(batch) < limit:
                break

            offset += limit
            iteration += 1
            await asyncio.sleep(0.5)  # Rate limiting

        logger.info(f"✅ Step 2 complete: {total_markets_fetched} total markets fetched")

        # Step 3: Summary
        logger.info("\n" + "="*60)
        logger.info("📊 SUMMARY")
        logger.info("="*60)
        logger.info(f"Total events: {len(all_events)}")
        logger.info(f"Markets in events: {len(event_market_ids)}")
        logger.info(f"Total markets fetched: {total_markets_fetched}")
        logger.info(f"Standalone markets: {len(standalone_market_ids)}")
        logger.info(f"Percentage standalone: {len(standalone_market_ids) / total_markets_fetched * 100:.2f}%")
        logger.info("="*60)

        # Show some examples
        if standalone_market_ids:
            logger.info("\n📋 Sample standalone market IDs (first 10):")
            for i, market_id in enumerate(list(standalone_market_ids)[:10]):
                logger.info(f"  {i+1}. {market_id}")

        return {
            'total_events': len(all_events),
            'markets_in_events': len(event_market_ids),
            'total_markets': total_markets_fetched,
            'standalone_markets': len(standalone_market_ids),
            'percentage_standalone': len(standalone_market_ids) / total_markets_fetched * 100 if total_markets_fetched > 0 else 0
        }

    except Exception as e:
        logger.error(f"❌ Error counting standalone markets: {e}", exc_info=True)
        raise
    finally:
        await client.aclose()


async def main():
    """Main function"""
    logger.info("🚀 Starting standalone markets count...")
    try:
        results = await count_standalone_markets()
        logger.info("✅ Count completed successfully")
        return results
    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
