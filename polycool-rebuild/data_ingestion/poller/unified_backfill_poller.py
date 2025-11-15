"""
Unified Backfill Poller - Complete market coverage with ZERO ORPHANS guarantee
Strategy: /events first (complete metadata), then /markets (standalone), then orphan verification
"""
import asyncio
from time import time
from datetime import datetime, timezone
from typing import List, Dict, Set
from sqlalchemy import text
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller
from core.database.connection import get_db

logger = get_logger(__name__)


class UnifiedBackfillPoller(BaseGammaAPIPoller):
    """
    Unified Backfill Poller that GUARANTEES zero orphan markets
    Strategy:
    1. Fetch ALL active events via /events
    2. For each event, fetch /events/{id} for COMPLETE metadata and dates
    3. Extract ALL markets from events (with complete event metadata)
    4. Fetch standalone markets via /markets (excluding already found)
    5. VERIFICATION: Ensure NO ORPHANS (all markets have event_title)
    6. Enrich with tags and upsert

    Supports resume on non-empty tables and optimized parallel processing.
    """

    def __init__(self, resume_on_existing: bool = False, parallel_requests: int = 1, skip_tags: bool = False):
        super().__init__(poll_interval=0)  # One-shot only
        self.max_retries = 5  # More retries for comprehensive backfill
        self.resume_on_existing = resume_on_existing  # Allow running on non-empty tables
        self.parallel_requests = parallel_requests  # Concurrent API requests (now defaults to 1)
        self.skip_tags = skip_tags  # Skip tags enrichment for speed

    async def _ensure_table_empty(self) -> None:
        """Ensure markets table is empty before starting backfill"""
        try:
            async with get_db() as db:
                result = await db.execute(text("SELECT COUNT(*) FROM markets"))
                count = result.scalar()
                if count > 0:
                    raise RuntimeError(f"❌ Markets table is not empty ({count} records). "
                                     "Use resume_on_existing=True to allow running on non-empty tables, "
                                     "or truncate the table first.")
        except Exception as e:
            logger.error(f"Failed to check table status: {e}")
            raise RuntimeError("Cannot verify table status. Please ensure database connection works.")

    async def comprehensive_backfill(self) -> Dict:
        """
        Complete backfill with ZERO ORPHANS guarantee
        Returns stats about the backfill operation
        """
        print("🚀 ENTERING comprehensive_backfill() method")
        print("🚀 Starting UNIFIED COMPREHENSIVE backfill - ZERO ORPHANS strategy")
        logger.info("🚀 Starting UNIFIED COMPREHENSIVE backfill - ZERO ORPHANS strategy")
        logger.info("📊 Strategy: /events → /events/{id} → /markets (standalone) → Orphan Check")

        # Check if table is empty (unless resume is enabled)
        if not self.resume_on_existing:
            await self._ensure_table_empty()

        start_time = time()
        stats = {
            'total_markets': 0,
            'event_markets': 0,
            'standalone_markets': 0,
            'orphans_found': 0,
            'orphans_enriched': 0,
            'final_upserted': 0,
            'duration_seconds': 0
        }

        try:
            print("📦 Phase 1: Starting to fetch ALL active events and their markets...")
            # Phase 1: Fetch ALL markets from events (with complete metadata)
            logger.info("📦 Phase 1: Fetching ALL active events and their markets...")
            event_markets, event_market_ids = await self._backfill_via_events_complete()
            stats['event_markets'] = len(event_markets)
            print(f"✅ Phase 1 complete: {len(event_markets)} markets from events")
            logger.info(f"✅ Phase 1 complete: {len(event_markets)} markets from events")

            # Phase 2: Fetch standalone markets (not in events)
            print("📦 Phase 2: Starting to fetch standalone markets...")
            logger.info("📦 Phase 2: Fetching standalone markets...")
            standalone_markets = await self._backfill_standalone_markets(event_market_ids)
            stats['standalone_markets'] = len(standalone_markets)
            print(f"✅ Phase 2 complete: {len(standalone_markets)} standalone markets")
            logger.info(f"✅ Phase 2 complete: {len(standalone_markets)} standalone markets")

            # Phase 3: VERIFICATION - Check for orphans and enrich
            print("📦 Phase 3: Starting orphan verification and enrichment...")
            logger.info("📦 Phase 3: Orphan verification and enrichment...")
            all_markets = event_markets + standalone_markets
            orphans_stats = await self._verify_and_enrich_orphans(all_markets)
            stats.update(orphans_stats)
            print(f"✅ Phase 3 complete: {orphans_stats['orphans_found']} orphans found, {orphans_stats['orphans_enriched']} enriched")
            logger.info(f"✅ Phase 3 complete: {orphans_stats['orphans_found']} orphans found, {orphans_stats['orphans_enriched']} enriched")

            # Phase 4: Final enrichment and upsert
            if not self.skip_tags:
                print("📦 Phase 4: Starting final enrichment with tags and upsert...")
                logger.info("📦 Phase 4: Final enrichment with tags and upsert...")
                stats['final_upserted'] = await self._final_enrichment_and_upsert(all_markets)
                print("✅ Phase 4 complete!")
            else:
                print("📦 Phase 4: Skipping tags enrichment (--skip-tags enabled) - direct upsert...")
                logger.info("📦 Phase 4: Skipping tags enrichment (--skip-tags enabled) - direct upsert...")
                stats['final_upserted'] = await self._upsert_markets_batch_only(all_markets)
                print("✅ Phase 4 complete (no tags)!")

            stats['total_markets'] = len(all_markets)
            stats['duration_seconds'] = time() - start_time

            logger.info("🎉 UNIFIED COMPREHENSIVE backfill completed!")
            logger.info(f"📊 Results: {stats['total_markets']} total markets, {stats['final_upserted']} upserted, {stats['orphans_enriched']} orphans enriched")
            logger.info(f"⏱️ Duration: {stats['duration_seconds']:.2f}s")

            return stats

        except Exception as e:
            logger.error(f"❌ Unified backfill failed: {e}", exc_info=True)
            raise

    async def _backfill_via_events_complete(self) -> tuple[List[Dict], Set[str]]:
        """
        Phase 1: Fetch ALL active events, get complete details for each,
        extract all markets with COMPLETE event metadata and dates
        Returns: (markets_list, market_ids_set)
        """
        print("🔄 Starting _backfill_via_events_complete()...")
        all_markets = []
        event_market_ids: Set[str] = set()
        all_events = []  # Store all events in memory

        # Fetch ALL active events (paginate through all with safety limits)
        print("📥 Starting to fetch all active events...")
        logger.info("📥 Fetching all active events...")
        offset = 0
        limit = 500  # Increased batch size for better performance
        max_iterations = 50  # Reasonable limit for active events (50 * 200 = 10,000 events max)
        max_total_events = 5000  # Reasonable total limit
        iteration = 0

        while iteration < max_iterations and len(all_events) < max_total_events:
            print(f"📥 Fetching events batch {iteration + 1} (offset: {offset}, total so far: {len(all_events)})...")
            logger.info(f"📥 Fetching events batch {iteration + 1} (offset: {offset})...")

            batch = await self._fetch_api("/events", params={
                'closed': False,
                'offset': offset,
                'limit': limit,
                'order': 'volume',
                'ascending': False
            })

            if not batch or not isinstance(batch, list):
                logger.info("📥 API returned invalid response")
                break

            if not batch:  # Empty list
                logger.info("📥 Empty batch received - end of data")
                break

            batch_count = len(batch)

            # Check for duplicates (if we get the same events, we've reached the end)
            if all_events and batch_count > 0:
                last_event_id = all_events[-1].get('id')
                first_new_event_id = batch[0].get('id')
                if str(last_event_id) == str(first_new_event_id):
                    logger.info("📥 Detected duplicate events - reached end of data")
                    break

            all_events.extend(batch)
            logger.info(f"📥 Fetched {batch_count} events in this batch (total: {len(all_events)})")

            # If we got fewer than requested, we've reached the end
            if batch_count < limit:
                logger.info("📥 Reached end of events list (partial batch)")
                break

            # Safety check: if we've fetched a lot of events and they're all low volume,
            # we probably have enough data
            if len(all_events) >= 2000:
                logger.info("📥 Reached reasonable data limit (2000+ events)")
                break

            offset += limit
            iteration += 1
            await asyncio.sleep(1.0)  # Rate limiting

        if iteration >= max_iterations:
            logger.warning(f"⚠️ Reached iteration limit of {max_iterations}")
        if len(all_events) >= max_total_events:
            logger.warning(f"⚠️ Reached total events limit of {max_total_events}")

        logger.info(f"✅ Fetched {len(all_events)} total active events")

        # Process events sequentially to avoid rate limits
        event_batch_size = 50  # Larger batches for faster processing

        for i in range(0, len(all_events), event_batch_size):
            batch_events = all_events[i:i + event_batch_size]

            logger.info(f"📦 Processing events batch {i//event_batch_size + 1}/{len(all_events)//event_batch_size + 1} ({len(batch_events)} events) - SEQUENTIAL MODE")

            markets_from_batch = await self._process_event_batch_sequential(batch_events)

            for market in markets_from_batch:
                market_id = market.get('id')
                if market_id:
                    event_market_ids.add(str(market_id))
                all_markets.append(market)

            logger.info(f"📦 Events batch {i//event_batch_size + 1}: processed {len(batch_events)} events, extracted {len(markets_from_batch)} markets")
            await asyncio.sleep(0.3)  # Faster sleep between batches

        logger.info(f"✅ Extracted {len(all_markets)} markets from {len(all_events)} events")
        return all_markets, event_market_ids

    async def _process_event_batch_with_complete_metadata(self, events: List[Dict]) -> List[Dict]:
        """
        Process a batch of events: fetch /events/{id} for COMPLETE metadata and dates
        Returns markets with complete event metadata and proper dates
        """
        all_markets = []

        for event in events:
            event_id = str(event.get('id', ''))
            if not event_id:
                continue

            try:
                # 🔥 CRITICAL: Fetch full event details for COMPLETE metadata
                full_event = await self._fetch_api(f"/events/{event_id}")

                if not full_event:
                    logger.warning(f"Failed to fetch full details for event {event_id}")
                    full_event = event  # Fallback to list data

                # Extract COMPLETE dates from full event (priority: endDate > endsAt)
                event_end_date = full_event.get('endDate') or full_event.get('endsAt')
                event_start_date = full_event.get('startDate') or full_event.get('startsAt')

                # Get complete event metadata
                event_slug = full_event.get('slug', '')
                event_title = full_event.get('title', '')
                event_category = full_event.get('category', '')
                event_tags = full_event.get('tags', [])

                # Extract markets from this event
                markets_in_event = full_event.get('markets', [])

                if not markets_in_event:
                    continue

                # Process each market in this event
                for market in markets_in_event:
                    # Add COMPLETE event metadata (guarantees no orphans)
                    market['event_id'] = event_id
                    market['event_slug'] = event_slug
                    market['event_title'] = event_title  # 🔥 CRITICAL: Prevents orphans

                    # 🔥 CRITICAL: Use event dates (more reliable than market dates)
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

    async def _process_event_batch_sequential(self, events: List[Dict]) -> List[Dict]:
        """
        Process a batch of events sequentially to get complete metadata and dates
        Returns markets with complete event metadata and proper dates
        """
        all_markets = []

        for event in events:
            event_id = str(event.get('id', ''))
            if not event_id:
                continue

            try:
                # 🔥 CRITICAL: Fetch full event details for COMPLETE metadata
                full_event = await self._fetch_api(f"/events/{event_id}")

                if not full_event:
                    logger.warning(f"Failed to fetch full details for event {event_id}")
                    full_event = event  # Fallback to list data

                # Extract COMPLETE dates from full event (priority: endDate > endsAt)
                event_end_date = full_event.get('endDate') or full_event.get('endsAt')
                event_start_date = full_event.get('startDate') or full_event.get('startsAt')

                # Get complete event metadata
                event_slug = full_event.get('slug', '')
                event_title = full_event.get('title', '')
                event_category = full_event.get('category', '')
                event_tags = full_event.get('tags', [])

                # Extract markets from this event
                markets_in_event = full_event.get('markets', [])

                if not markets_in_event:
                    continue

                # Process each market in this event
                for market in markets_in_event:
                    # Add COMPLETE event metadata (guarantees no orphans)
                    market['event_id'] = event_id
                    market['event_slug'] = event_slug
                    market['event_title'] = event_title  # 🔥 CRITICAL: Prevents orphans

                    # 🔥 CRITICAL: Use event dates (more reliable than market dates)
                    if event_end_date:
                        market['endDate'] = event_end_date
                    if event_start_date:
                        market['startDate'] = event_start_date

                    # Add event category and tags
                    if event_category and not market.get('category'):
                        market['category'] = event_category
                    market['event_tags'] = event_tags

                    all_markets.append(market)

            except Exception as e:
                logger.warning(f"Error processing event {event_id}: {e}")
                continue

            # Sleep between individual events to avoid rate limits
            await asyncio.sleep(0.1)

        return all_markets

    async def _backfill_standalone_markets(self, event_market_ids: Set[str]) -> List[Dict]:
        """
        Phase 2: Fetch standalone markets (markets NOT in events)
        Ensures we catch any markets that aren't part of events
        """
        standalone_markets = []
        offset = 0
        limit = 1000  # Increased for better performance
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
                        # Market has events but wasn't in our event list - might be new event
                        # Include it but extract event metadata
                        await self._extract_event_metadata_from_market(market)
                        standalone_markets.append(market)

            logger.info(f"📦 Standalone batch {iteration + 1}: {len(batch)} markets checked, {len(standalone_markets)} total standalone")

            if len(batch) < limit:
                break

            offset += limit
            iteration += 1
            await asyncio.sleep(1.0)  # Rate limiting

        logger.info(f"✅ Found {len(standalone_markets)} standalone markets")
        return standalone_markets

    async def _extract_event_metadata_from_market(self, market: Dict) -> None:
        """
        Extract event metadata from the events field in a market
        Used as fallback when event data is already in market response
        """
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
                market['event_title'] = event.get('title')  # 🔥 CRITICAL: Prevents orphans

            # Use event dates if market doesn't have them
            if not market.get('endDate') and event.get('endDate'):
                market['endDate'] = event.get('endDate')
            if not market.get('startDate') and event.get('startDate'):
                market['startDate'] = event.get('startDate')

            # Add category from event if not present
            if not market.get('category') and event.get('category'):
                market['category'] = event.get('category')

            # Add event tags for enrichment
            market['event_tags'] = event.get('tags', [])

        logger.debug(f"Extracted event metadata for market {market.get('id')}")

    async def _verify_and_enrich_orphans(self, markets: List[Dict]) -> Dict:
        """
        Phase 3: CRITICAL VERIFICATION - Ensure NO ORPHANS
        Check all markets have event_title, if not: fetch from /events
        Returns stats about orphan detection and enrichment
        """
        stats = {'orphans_found': 0, 'orphans_enriched': 0}
        orphans = []

        # Find orphan markets (have event_id but no event_title)
        for market in markets:
            if market.get('event_id') and not market.get('event_title'):
                orphans.append(market)

        stats['orphans_found'] = len(orphans)

        if not orphans:
            logger.info("✅ No orphan markets found - perfect!")
            return stats

        logger.warning(f"🔍 Found {len(orphans)} orphan markets - enriching via /events calls...")

        # Enrich orphans sequentially to avoid rate limits
        enriched_count = 0
        for orphan in orphans:
            try:
                event_id = orphan['event_id']
                event_data = await self._fetch_api(f"/events/{event_id}")

                if event_data:
                    # Add missing metadata
                    orphan['event_title'] = event_data.get('title', 'Unknown Event')
                    orphan['event_slug'] = event_data.get('slug', '')
                    orphan['category'] = event_data.get('category', orphan.get('category'))

                    # Add dates if missing
                    if not orphan.get('endDate'):
                        orphan['endDate'] = event_data.get('endDate') or event_data.get('endsAt')
                    if not orphan.get('startDate'):
                        orphan['startDate'] = event_data.get('startDate') or event_data.get('startsAt')

                    enriched_count += 1
                    logger.debug(f"✅ Enriched orphan market {orphan.get('id')} with event '{orphan['event_title']}'")

                # Sleep between orphan enrichment calls
                await asyncio.sleep(0.2)

            except Exception as e:
                logger.warning(f"Failed to enrich orphan market {orphan.get('id')}: {e}")
                continue

        stats['orphans_enriched'] = enriched_count

        if enriched_count == len(orphans):
            logger.info("✅ All orphan markets successfully enriched!")
        else:
            logger.warning(f"⚠️ {len(orphans) - enriched_count} orphan markets could not be enriched")

        return stats

    async def _final_enrichment_and_upsert(self, markets: List[Dict]) -> int:
        """
        Phase 4: Final enrichment with tags and upsert to database
        """
        logger.info(f"🏷️ Fetching tags for {len(markets)} markets...")

        # Enrich with tags
        await self._enrich_markets_with_tags(markets)

        # Upsert in batches
        total_upserted = 0
        batch_size = 100  # Increased for better performance

        for i in range(0, len(markets), batch_size):
            batch = markets[i:i + batch_size]
            upserted = await self._upsert_markets(batch)
            total_upserted += upserted

            logger.info(f"📦 Upsert batch {i//batch_size + 1}: {upserted} markets upserted (total: {total_upserted})")
            await asyncio.sleep(1.0)  # Rate limiting

        logger.info(f"✅ Final upsert complete: {total_upserted} markets inserted/updated")
        return total_upserted

    async def _enrich_markets_with_tags(self, markets: List[Dict]) -> None:
        """Enrich markets with tags for better categorization - SEQUENTIAL & NON-BLOCKING"""
        logger.info(f"🏷️ Starting tags enrichment for {len(markets)} markets (non-blocking)...")

        tags_fetched = 0
        tags_failed = 0

        for i, market in enumerate(markets):
            market_id = market.get('id')
            if not market_id:
                continue

            try:
                # Fetch tags for this market - with timeout and error handling
                tags = await self._fetch_api(f"/markets/{market_id}/tags")

                if tags and isinstance(tags, list):
                    market['tags'] = tags
                    tags_fetched += 1
                else:
                    # No tags available, that's ok
                    market['tags'] = []
                    tags_failed += 1

            except Exception as e:
                # Tags are not critical - continue without them
                logger.debug(f"Failed to fetch tags for market {market_id}: {e}")
                market['tags'] = []  # Set empty tags
                tags_failed += 1
                continue

            # Log progress every 50 markets
            if i % 50 == 0:
                logger.info(f"🏷️ Processed {i}/{len(markets)} markets tags (fetched: {tags_fetched}, failed: {tags_failed})")

            # Sleep between tag requests to be very conservative
            await asyncio.sleep(1.0)

        logger.info(f"✅ Tags enrichment completed: {tags_fetched} successful, {tags_failed} failed (non-blocking)")

    async def _upsert_markets_batch_only(self, markets: List[Dict]) -> int:
        """
        Upsert markets in batches WITHOUT tags enrichment - ULTRA FAST MODE
        """
        logger.info(f"💾 Starting direct batch upsert for {len(markets)} markets (no tags)...")

        # Upsert in larger batches for speed
        total_upserted = 0
        batch_size = 200  # Larger batches for speed

        for i in range(0, len(markets), batch_size):
            batch = markets[i:i + batch_size]
            upserted = await self._upsert_markets(batch)
            total_upserted += upserted

            logger.info(f"📦 Upsert batch {i//batch_size + 1}: {upserted} markets upserted (total: {total_upserted})")
            # Minimal sleep between batches
            await asyncio.sleep(0.1)

        logger.info(f"✅ Direct batch upsert complete: {total_upserted} markets inserted/updated")
        return total_upserted
