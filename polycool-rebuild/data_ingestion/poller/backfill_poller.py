"""
Backfill Poller - Comprehensive market coverage with NO ORPHANS
Strategy: /events first (to catch all event markets), then /markets (for standalone markets)
Ensures complete end_date and full table population
"""
import asyncio
from time import time
from datetime import datetime, timezone
from typing import List, Dict, Set
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller

logger = get_logger(__name__)


class BackfillPoller(BaseGammaAPIPoller):
    """
    Comprehensive backfill poller that ensures NO ORPHAN MARKETS
    Strategy:
    1. Fetch ALL events via /events endpoint
    2. For each event, fetch full details via /events/{id} to get COMPLETE endDate/startDate
    3. Extract all markets from events (guarantees no orphans)
    4. Fetch standalone markets via /markets (markets not in events)
    5. Enrich all markets with tags and upsert
    """

    def __init__(self):
        super().__init__(poll_interval=0)  # Not used for one-shot
        self.max_retries = 5  # More retries for rate limiting

    async def backfill_all_active_markets(self) -> int:
        """
        Comprehensive backfill: events first, then standalone markets
        Ensures NO ORPHAN MARKETS and COMPLETE end_date for all markets
        """
        logger.info("🚀 Starting COMPREHENSIVE backfill - NO ORPHANS strategy")
        logger.info("📊 Strategy: /events → /events/{id} → /markets (standalone)")
        start_time = time()
        total_upserted = 0

        try:
            # Step 1: Fetch ALL events and their markets (with complete dates)
            logger.info("📦 Step 1: Fetching ALL active events...")
            markets_from_events, event_market_ids = await self._backfill_via_events()
            logger.info(f"✅ Step 1 complete: {len(markets_from_events)} markets from events")

            # Step 2: Fetch standalone markets (not in events)
            logger.info("📦 Step 2: Fetching standalone markets...")
            standalone_markets = await self._backfill_standalone_markets(event_market_ids)
            logger.info(f"✅ Step 2 complete: {len(standalone_markets)} standalone markets")

            # Step 3: Combine and upsert all markets
            all_markets = markets_from_events + standalone_markets
            logger.info(f"📦 Step 3: Upserting {len(all_markets)} total markets...")

            # Process in batches
            batch_size = 50
            for i in range(0, len(all_markets), batch_size):
                batch = all_markets[i:i + batch_size]

                # Enrich with tags
                await self._enrich_markets_with_tags(batch)

                # Upsert
                upserted = await self._upsert_markets(batch)
                total_upserted += upserted

                logger.info(f"📦 Batch {i//batch_size + 1}: {upserted} markets upserted (total: {total_upserted})")
                await asyncio.sleep(1.0)  # Rate limiting

            duration = time() - start_time
            logger.info(f"🎉 COMPREHENSIVE backfill completed in {duration:.2f}s")
            logger.info(f"📊 Total: {total_upserted} markets upserted ({len(markets_from_events)} from events, {len(standalone_markets)} standalone)")
            return total_upserted

        except Exception as e:
            logger.error(f"❌ Backfill failed: {e}", exc_info=True)
            raise

    async def _backfill_via_events(self) -> tuple[List[Dict], Set[str]]:
        """
        Fetch ALL active events, get full details for each, extract all markets
        Returns: (list of markets, set of market IDs found in events)
        """
        all_markets = []
        event_market_ids: Set[str] = set()
        all_events = []

        # Fetch ALL active events (paginate through all)
        logger.info("📥 Fetching all active events...")
        offset = 0
        limit = 200  # Smaller batches to avoid rate limiting

        while True:
            batch = await self._fetch_api("/events", params={
                'closed': False,
                'offset': offset,
                'limit': limit,
                'order': 'volume',
                'ascending': False
            })

            if not batch or not isinstance(batch, list) or not batch:
                break

            all_events.extend(batch)
            logger.info(f"📥 Fetched {len(all_events)} events so far...")

            if len(batch) < limit:
                break

            offset += limit
            await asyncio.sleep(1.0)  # Rate limiting

        logger.info(f"✅ Fetched {len(all_events)} total active events")

        # Process events in batches to get full details
        event_batch_size = 50
        for i in range(0, len(all_events), event_batch_size):
            event_batch = all_events[i:i + event_batch_size]
            markets_from_batch = await self._process_event_batch_with_full_details(event_batch)

            for market in markets_from_batch:
                market_id = market.get('id')
                if market_id:
                    event_market_ids.add(str(market_id))
                all_markets.append(market)

            logger.info(f"📦 Processed {min(i + event_batch_size, len(all_events))}/{len(all_events)} events ({len(markets_from_batch)} markets)")

            # Rate limiting between batches
            await asyncio.sleep(2.0)

        logger.info(f"✅ Extracted {len(all_markets)} markets from {len(all_events)} events")
        return all_markets, event_market_ids

    async def _process_event_batch_with_full_details(self, events: List[Dict]) -> List[Dict]:
        """
        Process a batch of events: fetch full details via /events/{id} to get COMPLETE dates
        Returns markets with complete event metadata and dates
        """
        all_markets = []

        for event in events:
            event_id = str(event.get('id', ''))
            if not event_id:
                continue

            try:
                # 🔥 CRITICAL: Fetch full event details to get COMPLETE endDate/startDate
                # The /events list endpoint doesn't always include dates
                full_event = await self._fetch_api(f"/events/{event_id}")

                if not full_event:
                    logger.warning(f"Failed to fetch full details for event {event_id}")
                    # Fallback: use data from list endpoint
                    full_event = event

                # Extract markets from this event
                markets_in_event = full_event.get('markets', [])

                if not markets_in_event:
                    continue

                # Get COMPLETE dates from full event (priority: endDate > endsAt)
                event_end_date = full_event.get('endDate') or full_event.get('endsAt')
                event_start_date = full_event.get('startDate') or full_event.get('startsAt')

                # Get other event metadata
                event_slug = full_event.get('slug', '')
                event_title = full_event.get('title', '')
                event_category = full_event.get('category', '')
                event_tags = full_event.get('tags', [])

                # Process each market in this event
                for market in markets_in_event:
                    # Add COMPLETE event metadata
                    market['event_id'] = event_id
                    market['event_slug'] = event_slug
                    market['event_title'] = event_title

                    # 🔥 CRITICAL: Use event dates (more reliable than market dates)
                    # Event dates take priority - they're the source of truth
                    if event_end_date:
                        market['endDate'] = event_end_date
                    if event_start_date:
                        market['startDate'] = event_start_date

                    # Add event category and tags
                    if event_category and not market.get('category'):
                        market['category'] = event_category
                    market['event_tags'] = event_tags

                    all_markets.append(market)

                # Rate limiting between events
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"Error processing event {event_id}: {e}")
                continue

        return all_markets

    async def _backfill_standalone_markets(self, event_market_ids: Set[str]) -> List[Dict]:
        """
        Fetch standalone markets (markets NOT in events) via /markets endpoint
        This ensures we catch any markets that aren't part of events
        """
        standalone_markets = []
        offset = 0
        limit = 500
        max_iterations = 50  # Safety limit

        iteration = 0
        while iteration < max_iterations:
            batch = await self._fetch_api("/markets", params={
                'closed': False,
                'limit': limit,
                'offset': offset,
                'order': 'volumeNum',
                'ascending': False
            })

            if not batch or not isinstance(batch, list) or not batch:
                break

            # Filter out markets that are already in events
            for market in batch:
                market_id = str(market.get('id', ''))
                if market_id and market_id not in event_market_ids:
                    # Check if market has events field - if empty, it's truly standalone
                    events_data = market.get('events', [])
                    if not events_data or len(events_data) == 0:
                        standalone_markets.append(market)
                    else:
                        # Market has events but wasn't in our event list - might be a new event
                        # Include it but extract event metadata
                        await self._extract_event_metadata_from_markets([market])
                        standalone_markets.append(market)

            logger.info(f"📦 Standalone batch: {len(batch)} markets checked, {len(standalone_markets)} total standalone")

            if len(batch) < limit:
                break

            offset += limit
            iteration += 1
            await asyncio.sleep(1.0)  # Rate limiting

        logger.info(f"✅ Found {len(standalone_markets)} standalone markets")
        return standalone_markets

    async def _extract_event_metadata_from_markets(self, markets: List[Dict]) -> None:
        """
        Extract event metadata from the events field in markets
        Used as fallback when event data is already in market response
        """
        for market in markets:
            events_data = market.get('events', [])

            if events_data and len(events_data) > 0:
                # Extract metadata from the first event
                event = events_data[0]

                # Add event metadata to market (only if not already set)
                if not market.get('event_id'):
                    market['event_id'] = event.get('id')
                if not market.get('event_slug'):
                    market['event_slug'] = event.get('slug')
                if not market.get('event_title'):
                    market['event_title'] = event.get('title')

                # Use event dates if market doesn't have them (but event dates take priority)
                if not market.get('endDate') and event.get('endDate'):
                    market['endDate'] = event.get('endDate')
                if not market.get('startDate') and event.get('startDate'):
                    market['startDate'] = event.get('startDate')

                # Add category from event if not present
                if not market.get('category') and event.get('category'):
                    market['category'] = event.get('category')

                # Add event tags for enrichment
                market['event_tags'] = event.get('tags', [])

        logger.debug(f"Extracted event metadata for {len(markets)} markets")

    async def _enrich_markets_with_tags(self, markets: List[Dict]) -> None:
        """Enrich markets with tags to get categories"""
        logger.info(f"🏷️ Fetching tags for {len(markets)} markets...")

        for i, market in enumerate(markets):
            market_id = market.get('id')
            if not market_id:
                continue

            try:
                # Fetch tags for this market
                tags = await self._fetch_api(f"/markets/{market_id}/tags")

                if tags and isinstance(tags, list):
                    # Add tags to market for category extraction
                    market['tags'] = tags

                    # Log progress every 50 markets
                    if i % 50 == 0:
                        logger.info(f"🏷️ Processed {i}/{len(markets)} markets tags")

            except Exception as e:
                logger.debug(f"Failed to fetch tags for market {market_id}: {e}")

            # Delay to avoid rate limiting
            await asyncio.sleep(0.3)  # 300ms delay = ~3 req/s max

        logger.info("✅ Tags enrichment completed")
