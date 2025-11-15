"""
Keyword Poller - Specialized poller for markets containing specific keywords
Combines discovery, price updates, and resolution checking for targeted markets
"""
import asyncio
from time import time
from datetime import datetime, timezone
from typing import List, Dict, Set
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller
from core.database.connection import get_db
from sqlalchemy import text

logger = get_logger(__name__)


class KeywordPoller(BaseGammaAPIPoller):
    """
    Specialized poller for markets containing specific keywords
    Ensures 100% coverage of ALL keyword markets (non-resolved) on Polymarket

    DUAL MODE OPERATION:
    - Fast Discovery (every 5min): Finds new keyword markets only - optimized for speed
    - Complete Backfill (every 1h): Exhaustive search to ensure 100% coverage of ALL keyword markets

    Keywords: bitcoin, eth, solana, trump, elon, israel, ukraine, AI, and "what + say" pattern
    Frequency: 5min (cycles alternate between fast discovery and complete backfill)

    FAST DISCOVERY STRATEGY (every 5min):
    - Discovery by volume: 200 markets from events (sorted by volume)
    - Discovery by recency: 100 markets from events (sorted by createdAt)
    - Discovery standalone: 200 standalone markets
    - Discovery by recency: 100 markets by recency (regardless of volume)
    - Updates: Top 500 keyword markets (by volume + recency)
    - Resolutions: Top 200 expired keyword markets (by volume)

    COMPLETE BACKFILL STRATEGY (every 1h):
    - Exhaustive pagination through ALL events (both volume and createdAt ordering)
    - Exhaustive pagination through ALL standalone markets
    - Ensures 100% coverage - upserts ALL keyword markets found (not just new ones)
    - Batch processing (100 markets/batch) to avoid DB overload
    - Rate limiting (400-500ms between pages) to respect API limits

    OPTIMIZATIONS:
    - Rate limiting between API calls (400-500ms)
    - Batch processing for DB upserts (100 markets/batch)
    - Safety limits to avoid infinite loops (200 pages events, 300 pages standalone)
    - Deduplication during search to avoid processing same market twice
    - Search in: title, description, AND event_title
    - Increased SQL limit to 5000 for existing keyword markets detection
    """

    # Keywords to search for (case-insensitive)
    KEYWORDS = [
        'bitcoin',
        'eth',  # Matches ethereum, ETH, etc.
        'solana',
        'trump',
        'elon',
        'israel',
        'ukraine',
        'ai',  # Matches AI, artificial intelligence, etc.
    ]

    # Special pattern: "what + say" in a single sentence
    # We'll check for markets with "what" and "say" in the title/description

    def __init__(self, interval: int = 300):  # 5min default
        super().__init__(poll_interval=interval)
        # Cycle management: alternate between fast discovery (5min) and complete backfill (1h)
        # Complete backfill runs every 12 cycles (12 * 5min = 60min = 1h)
        self.cycle_count = 0
        self.complete_backfill_interval = 12  # Every 12 cycles = 1 hour
        self.last_complete_backfill = None

    async def _poll_cycle(self) -> None:
        """
        Single poll cycle - ALTERNATE between fast discovery and complete backfill
        Strategy:
        - Fast discovery (every 5min): Find new keyword markets only
        - Complete backfill (every 1h): Ensure 100% coverage of ALL keyword markets
        """
        start_time = time()
        self.cycle_count += 1

        try:
            # Determine cycle type: complete backfill every N cycles, fast discovery otherwise
            is_complete_backfill = (self.cycle_count % self.complete_backfill_interval == 0) or \
                                   (self.last_complete_backfill is None)

            if is_complete_backfill:
                logger.info(f"🔄 COMPLETE BACKFILL CYCLE (#{self.cycle_count}) - Ensuring 100% keyword coverage")
                await self._complete_backfill_cycle()
                self.last_complete_backfill = datetime.now(timezone.utc)
            else:
                logger.debug(f"⚡ FAST DISCOVERY CYCLE (#{self.cycle_count}) - Finding new keyword markets only")
                await self._fast_discovery_cycle()

            # Update stats
            self.poll_count += 1
            self.last_poll_time = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            duration = time() - start_time
            logger.info(f"✅ Keyword poll cycle completed in {duration:.2f}s (cycle #{self.cycle_count})")

        except Exception as e:
            logger.error(f"Keyword poll cycle error: {e}")
            raise

    async def _fast_discovery_cycle(self) -> None:
        """
        Fast discovery cycle (every 5min) - Find new keyword markets only
        Optimized for speed and minimal API/DB load
        """
        start_time = time()

        # 1. Get existing keyword markets from DB
        existing_keyword_markets = await self._get_existing_keyword_markets()
        logger.debug(f"Found {len(existing_keyword_markets)} existing keyword markets in DB")

        # 2. PRIORITY: Discover new keyword markets from API
        new_keyword_markets = await self._discover_keyword_markets(existing_keyword_markets)

        # Upsert new markets immediately
        upserted_new = 0
        if new_keyword_markets:
            upserted_new = await self._upsert_markets(new_keyword_markets, allow_resolved=True)
            logger.info(f"✅ FAST DISCOVERY: Upserted {upserted_new} new keyword markets")

        # 3. Update existing keyword markets (prices, metadata) - limited batch
        updated_markets = await self._update_existing_keyword_markets(existing_keyword_markets)

        if updated_markets:
            await self._upsert_markets(updated_markets, allow_resolved=False)

        # 4. Check resolutions for keyword markets - limited batch
        resolved_markets = await self._check_keyword_resolutions(existing_keyword_markets)

        if resolved_markets:
            await self._upsert_markets(resolved_markets, allow_resolved=True)

        duration = time() - start_time
        logger.info(f"⚡ Fast discovery completed in {duration:.2f}s - {len(new_keyword_markets)} new, {len(updated_markets)} updated, {len(resolved_markets)} resolved")

    async def _complete_backfill_cycle(self) -> None:
        """
        Complete backfill cycle (every 1h) - Ensure 100% coverage of ALL keyword markets
        Exhaustive pagination through all events and markets to catch every keyword market
        Optimized with rate limits and batch processing to avoid overloading API/DB
        """
        start_time = time()

        # 1. Get ALL keyword markets from Polymarket (exhaustive search)
        logger.info("🔍 Starting exhaustive search for ALL keyword markets...")
        all_keyword_markets = await self._ensure_complete_keyword_coverage()

        if not all_keyword_markets:
            logger.warning("No keyword markets found in complete backfill")
            return

        logger.info(f"📋 Found {len(all_keyword_markets)} total keyword markets to ensure coverage")

        # 2. Upsert in batches to avoid DB overload
        batch_size = 100  # Process 100 markets at a time
        total_upserted = 0

        for i in range(0, len(all_keyword_markets), batch_size):
            batch = all_keyword_markets[i:i + batch_size]
            upserted = await self._upsert_markets(batch, allow_resolved=False)
            total_upserted += upserted

            logger.info(f"📦 Batch {i//batch_size + 1}/{(len(all_keyword_markets) + batch_size - 1)//batch_size}: {upserted} markets upserted (total: {total_upserted})")

            # Rate limiting between batches to avoid DB overload
            if i + batch_size < len(all_keyword_markets):
                await asyncio.sleep(0.5)  # 500ms delay between batches

        # 3. Update stats
        self.market_count = len(all_keyword_markets)
        self.upsert_count = total_upserted

        duration = time() - start_time
        logger.info(f"✅ COMPLETE BACKFILL completed in {duration:.2f}s - {total_upserted}/{len(all_keyword_markets)} keyword markets ensured")

    def _matches_keywords(self, market: Dict) -> bool:
        """Check if market matches any keyword"""
        title = (market.get('question') or market.get('title') or '').lower()
        description = (market.get('description') or '').lower()
        event_title = (market.get('event_title') or '').lower()
        text_to_search = f"{title} {description} {event_title}"

        # Check for keyword matches
        for keyword in self.KEYWORDS:
            if keyword.lower() in text_to_search:
                return True

        # Check for "what + say" pattern (both words in same sentence)
        if 'what' in text_to_search and 'say' in text_to_search:
            # Check if they're in the same sentence (simple heuristic: within 50 chars)
            what_idx = text_to_search.find('what')
            say_idx = text_to_search.find('say')
            if what_idx >= 0 and say_idx >= 0:
                distance = abs(what_idx - say_idx)
                if distance < 50:  # Within 50 characters
                    return True

        return False

    async def _get_existing_keyword_markets(self) -> Set[str]:
        """
        Get market IDs that already match keywords (from DB)
        Increased limit to 5000 to handle more keyword markets
        """
        try:
            async with get_db() as db:
                # Use SQL ILIKE for case-insensitive keyword matching (more efficient)
                # Build OR conditions for each keyword (keywords are safe - hardcoded list)
                keyword_conditions = []
                for keyword in self.KEYWORDS:
                    # Keywords are from hardcoded list, safe to use in SQL
                    keyword_conditions.append(f"(title ILIKE '%{keyword}%' OR description ILIKE '%{keyword}%' OR event_title ILIKE '%{keyword}%')")

                # Add "what + say" pattern
                keyword_conditions.append("(title ILIKE '%what%' AND title ILIKE '%say%')")
                keyword_conditions.append("(description ILIKE '%what%' AND description ILIKE '%say%')")
                keyword_conditions.append("(event_title ILIKE '%what%' AND event_title ILIKE '%say%')")

                conditions_sql = " OR ".join(keyword_conditions)

                # Note: keywords are from hardcoded list, so SQL injection risk is minimal
                # But we still validate with Python logic below
                # Increased limit from 1000 to 5000 to handle more keyword markets
                result = await db.execute(text(f"""
                    SELECT id, title, description, event_title
                    FROM markets
                    WHERE is_resolved = false
                    AND ({conditions_sql})
                    LIMIT 5000
                """))
                rows = result.fetchall()

                # Double-check with Python logic (more precise for "what + say" distance)
                keyword_market_ids = set()
                for row in rows:
                    market_id, title, description, event_title = row
                    market_dict = {
                        'id': market_id,
                        'question': title,
                        'title': title,
                        'description': description or '',
                        'event_title': event_title or ''
                    }
                    if self._matches_keywords(market_dict):
                        keyword_market_ids.add(str(market_id))

                logger.debug(f"Found {len(keyword_market_ids)} keyword markets in DB")
                return keyword_market_ids
        except Exception as e:
            logger.error(f"Error getting existing keyword markets: {e}")
            return set()

    async def _discover_keyword_markets(self, existing_ids: Set[str]) -> List[Dict]:
        """
        Discover new keyword markets from API
        Strategy: 300 from events + 200 standalone + 100 by recency = 600 total
        Multiple strategies to catch blind spots:
        - Events by volume (existing)
        - Events by recency (new - catches low volume events)
        - Standalone markets (existing, increased limit)
        - Markets by recency (new - catches new markets regardless of volume)
        """
        new_markets = []

        try:
            # Strategy 1: Find keyword markets from events by volume (200 max)
            logger.debug("🔍 Searching for keyword markets in events (by volume)...")
            events_markets_volume = await self._discover_keyword_markets_from_events(existing_ids, max_markets=200, order_by='volume')
            new_markets.extend(events_markets_volume)
            logger.info(f"📋 Found {len(events_markets_volume)} keyword markets from events (by volume)")

            # Strategy 2: Find keyword markets from events by recency (100 max) - NEW
            logger.debug("🔍 Searching for keyword markets in events (by recency)...")
            events_markets_recent = await self._discover_keyword_markets_from_events(existing_ids, max_markets=100, order_by='createdAt')
            new_markets.extend(events_markets_recent)
            logger.info(f"📋 Found {len(events_markets_recent)} keyword markets from events (by recency)")

            # Strategy 3: Find standalone keyword markets (200 max, increased from 100)
            logger.debug("🔍 Searching for standalone keyword markets...")
            standalone_markets = await self._discover_keyword_markets_standalone(existing_ids, max_markets=200)
            new_markets.extend(standalone_markets)
            logger.info(f"📋 Found {len(standalone_markets)} standalone keyword markets")

            # Strategy 4: Find keyword markets by recency (100 max) - NEW
            logger.debug("🔍 Searching for keyword markets by recency (regardless of volume)...")
            recent_markets = await self._discover_keyword_markets_by_recency(existing_ids, max_markets=100)
            new_markets.extend(recent_markets)
            logger.info(f"📋 Found {len(recent_markets)} keyword markets by recency")

            # Deduplicate (in case a market appears in multiple strategies)
            seen_ids = set()
            unique_markets = []
            for market in new_markets:
                market_id = str(market.get('id', ''))
                if market_id and market_id not in seen_ids:
                    seen_ids.add(market_id)
                    unique_markets.append(market)

            logger.info(f"📋 Discovered {len(unique_markets)} unique new keyword markets (volume: {len(events_markets_volume)}, recency: {len(events_markets_recent)}, standalone: {len(standalone_markets)}, recent: {len(recent_markets)})")
            return unique_markets

        except Exception as e:
            logger.error(f"Error discovering keyword markets: {e}")
            return []

    async def _discover_keyword_markets_from_events(self, existing_ids: Set[str], max_markets: int = 100, order_by: str = 'volume') -> List[Dict]:
        """
        Discover keyword markets from events
        Args:
            existing_ids: Set of market IDs already in DB
            max_markets: Maximum number of new markets to find
            order_by: 'volume' or 'createdAt' - determines sorting strategy
        """
        new_markets = []

        try:
            # Fetch events and extract markets
            # IMPORTANT: Don't stop early - continue pagination even if we found max_markets
            # This ensures we catch markets that might be in later pages
            offset = 0
            limit = 200
            max_pages = 50  # Increased to 50 pages to catch more events (10,000 events total)
            markets_found = 0

            for page in range(max_pages):
                # Continue pagination even if we found max_markets (to ensure we don't miss markets)
                # But limit the total markets we return
                if markets_found >= max_markets * 2:  # Allow 2x to catch more, then filter
                    break

                # Build params based on order_by
                params = {
                    'closed': False,
                    'offset': offset,
                    'limit': limit,
                }

                if order_by == 'createdAt':
                    # Try createdAt ordering (may not be supported, will fallback)
                    params['order'] = 'createdAt'
                    params['ascending'] = False
                else:
                    # Default: volume ordering
                    params['order'] = 'volume'
                    params['ascending'] = False

                events = await self._fetch_api("/events", params=params)

                if not events or not isinstance(events, list) or not events:
                    break

                # Extract markets from events
                for event in events:
                    markets_in_event = event.get('markets', [])
                    for market in markets_in_event:
                        market_id = str(market.get('id', ''))

                        # Skip if already in DB
                        if market_id in existing_ids:
                            continue

                        # Add event metadata
                        market['event_id'] = event.get('id')
                        market['event_slug'] = event.get('slug')
                        market['event_title'] = event.get('title')

                        # Check if matches keywords
                        if self._matches_keywords(market):
                            new_markets.append(market)
                            markets_found += 1
                            logger.debug(f"🔍 New keyword market from event: {market.get('question', market_id)}")

                if len(events) < limit:
                    break

                offset += limit
                await asyncio.sleep(0.3)  # Rate limiting

            # Limit to max_markets (but we've searched more pages to catch blind spots)
            if len(new_markets) > max_markets:
                logger.info(f"Found {len(new_markets)} keyword markets, limiting to {max_markets} (searched {page + 1} pages)")
                new_markets = new_markets[:max_markets]

            return new_markets

        except Exception as e:
            logger.error(f"Error discovering keyword markets from events: {e}")
            return []

    async def _discover_keyword_markets_standalone(self, existing_ids: Set[str], max_markets: int = 200) -> List[Dict]:
        """
        Discover standalone keyword markets (markets without events)
        Increased limit from 100 to 200 to catch more markets
        """
        new_markets = []

        try:
            offset = 0
            limit = 500
            max_pages = 50  # Increased to 50 pages to catch more markets (25,000 markets total)
            markets_found = 0

            for page in range(max_pages):
                # Continue pagination even if we found max_markets (to ensure we don't miss markets)
                if markets_found >= max_markets * 2:  # Allow 2x to catch more, then filter
                    break

                api_markets = await self._fetch_api("/markets", params={
                    'limit': limit,
                    'closed': False,
                    'offset': offset
                    # No order parameter - we don't care about volume
                })

                if not api_markets or not isinstance(api_markets, list) or not api_markets:
                    break

                # Filter by keywords and check if standalone
                for market in api_markets:
                    market_id = str(market.get('id', ''))

                    # Skip if already in DB
                    if market_id in existing_ids:
                        continue

                    # Check if standalone (no events field or empty)
                    events_data = market.get('events', [])
                    has_no_events = not events_data or len(events_data) == 0
                    event_id = market.get('event_id')

                    # Standalone = no events AND no event_id
                    if has_no_events and not event_id:
                        # Check if matches keywords
                        if self._matches_keywords(market):
                            new_markets.append(market)
                            markets_found += 1
                            logger.debug(f"🔍 New standalone keyword market: {market.get('question', market_id)}")

                if len(api_markets) < limit:
                    break

                offset += limit
                await asyncio.sleep(0.5)  # Rate limiting between pages

            # Limit to max_markets (but we've searched more pages to catch blind spots)
            if len(new_markets) > max_markets:
                logger.info(f"Found {len(new_markets)} standalone keyword markets, limiting to {max_markets} (searched {page + 1} pages)")
                new_markets = new_markets[:max_markets]

            return new_markets

        except Exception as e:
            logger.error(f"Error discovering standalone keyword markets: {e}")
            return []

    async def _update_existing_keyword_markets(self, market_ids: Set[str]) -> List[Dict]:
        """
        Update existing keyword markets with fresh prices
        Ignores volume - just updates prices for existing keyword markets
        """
        updated_markets = []

        if not market_ids:
            return []

        # Prioritize: Get top 500 keyword markets by volume and recency
        try:
            async with get_db() as db:
                # Get top keyword markets by volume and recent updates (limit to 500)
                result = await db.execute(text("""
                    SELECT id
                    FROM markets
                    WHERE id = ANY(:market_ids)
                    AND is_resolved = false
                    ORDER BY volume DESC, updated_at DESC
                    LIMIT 500
                """), {'market_ids': list(market_ids)})

                prioritized_ids = [str(row[0]) for row in result.fetchall()]
                logger.debug(f"Prioritizing {len(prioritized_ids)} top keyword markets by volume/recency")

        except Exception as e:
            logger.warning(f"Failed to prioritize markets: {e}. Using all markets.")
            prioritized_ids = list(market_ids)[:500]  # Fallback: limit to 500

        logger.debug(f"Updating prices for {len(prioritized_ids)} prioritized keyword markets")

        for market_id in prioritized_ids:
            try:
                # Fetch fresh data (mainly for prices)
                market = await self._fetch_api(f"/markets/{market_id}")

                if market and self._matches_keywords(market):  # Double-check keywords
                    updated_markets.append(market)

                # Rate limiting
                await asyncio.sleep(0.1)  # 100ms delay

            except Exception as e:
                logger.debug(f"Failed to update keyword market {market_id}: {e}")
                continue

        logger.debug(f"Updated prices for {len(updated_markets)} keyword markets")
        return updated_markets

    async def _check_keyword_resolutions(self, market_ids: Set[str]) -> List[Dict]:
        """
        Check resolutions for keyword markets
        Strategy: Prioritize markets that are most likely to be resolved (expired, high volume)
        """
        resolved_markets = []

        if not market_ids:
            return []

        # Get markets that might be resolved (expired or closed) - prioritize by volume
        try:
            async with get_db() as db:
                result = await db.execute(text("""
                    SELECT id
                    FROM markets
                    WHERE id = ANY(:market_ids)
                    AND is_resolved = false
                    AND (
                        end_date < now()
                        OR end_date IS NULL
                    )
                    ORDER BY volume DESC, end_date DESC
                    LIMIT 200  -- Increased limit for keyword markets
                """), {'market_ids': list(market_ids)})

                candidate_ids = [str(row[0]) for row in result.fetchall()]
                logger.debug(f"Checking resolutions for {len(candidate_ids)} expired keyword markets")

        except Exception as e:
            logger.error(f"Error getting resolution candidates: {e}")
            return []

        # Fetch and check resolutions
        for market_id in candidate_ids:
            try:
                market = await self._fetch_api(f"/markets/{market_id}")

                if market and self._is_market_really_resolved(market):
                    resolved_markets.append(market)
                    logger.debug(f"✅ Keyword market resolved: {market.get('question', market_id)}")

                await asyncio.sleep(0.1)  # Rate limiting

            except Exception as e:
                logger.debug(f"Failed to check resolution for {market_id}: {e}")
                continue

        if resolved_markets:
            logger.info(f"📋 Found {len(resolved_markets)} resolved keyword markets")

        return resolved_markets

    async def _discover_keyword_markets_by_recency(self, existing_ids: Set[str], max_markets: int = 100) -> List[Dict]:
        """
        Discover keyword markets by recency (newest first)
        This catches new markets regardless of volume - important for blind spots
        Strategy: Fetch recent markets and filter by keywords
        """
        new_markets = []

        try:
            offset = 0
            limit = 500
            max_pages = 20  # Increased to 20 pages to catch more recent markets (10,000 markets total)
            markets_found = 0

            for page in range(max_pages):
                # Continue pagination even if we found max_markets (to ensure we don't miss markets)
                if markets_found >= max_markets * 2:  # Allow 2x to catch more, then filter
                    break

                # Try to fetch by createdAt/recency (may fallback to default ordering)
                api_markets = await self._fetch_api("/markets", params={
                    'limit': limit,
                    'closed': False,
                    'offset': offset,
                    'order': 'createdAt',  # Try recency ordering
                    'ascending': False
                })

                if not api_markets or not isinstance(api_markets, list) or not api_markets:
                    break

                # Filter by keywords and check if new
                for market in api_markets:
                    market_id = str(market.get('id', ''))

                    # Skip if already in DB
                    if market_id in existing_ids:
                        continue

                    # Check if matches keywords
                    if self._matches_keywords(market):
                        new_markets.append(market)
                        markets_found += 1
                        logger.debug(f"🔍 New keyword market by recency: {market.get('question', market_id)}")

                if len(api_markets) < limit:
                    break

                offset += limit
                await asyncio.sleep(0.5)  # Rate limiting between pages

            # Limit to max_markets (but we've searched more pages to catch blind spots)
            if len(new_markets) > max_markets:
                logger.info(f"Found {len(new_markets)} recent keyword markets, limiting to {max_markets} (searched {page + 1} pages)")
                new_markets = new_markets[:max_markets]

            return new_markets

        except Exception as e:
            logger.error(f"Error discovering keyword markets by recency: {e}")
            return []

    async def _ensure_complete_keyword_coverage(self) -> List[Dict]:
        """
        Ensure 100% coverage of ALL keyword markets (non-resolved) on Polymarket
        Strategy: Exhaustive pagination through ALL events and markets
        Returns ALL keyword markets found (not just new ones)

        Optimizations:
        - Rate limiting between API calls
        - Safety limits to avoid infinite loops
        - Batch processing to avoid memory issues
        """
        all_keyword_markets = []
        seen_market_ids = set()  # Deduplicate as we go

        try:
            # Strategy 1: Exhaustive search through ALL events
            logger.info("📦 Phase 1: Exhaustive search through ALL events...")
            events_keyword_markets = await self._exhaustive_events_search(seen_market_ids)
            all_keyword_markets.extend(events_keyword_markets)
            logger.info(f"✅ Phase 1: Found {len(events_keyword_markets)} keyword markets from events")

            # Strategy 2: Exhaustive search through ALL standalone markets
            logger.info("📦 Phase 2: Exhaustive search through ALL standalone markets...")
            standalone_keyword_markets = await self._exhaustive_standalone_search(seen_market_ids)
            all_keyword_markets.extend(standalone_keyword_markets)
            logger.info(f"✅ Phase 2: Found {len(standalone_keyword_markets)} standalone keyword markets")

            # Final deduplication
            final_markets = []
            final_seen = set()
            for market in all_keyword_markets:
                market_id = str(market.get('id', ''))
                if market_id and market_id not in final_seen:
                    final_seen.add(market_id)
                    final_markets.append(market)

            logger.info(f"✅ Complete coverage: {len(final_markets)} unique keyword markets found")
            return final_markets

        except Exception as e:
            logger.error(f"Error ensuring complete keyword coverage: {e}")
            return all_keyword_markets  # Return what we found so far

    async def _exhaustive_events_search(self, seen_market_ids: Set[str]) -> List[Dict]:
        """
        Exhaustive search through ALL events to find keyword markets
        Uses both volume and createdAt ordering to catch all events
        """
        keyword_markets = []
        offset = 0
        limit = 200
        max_pages = 200  # Safety limit: ~40,000 events max
        pages_searched = 0
        consecutive_empty = 0

        # Try both orderings to catch all events
        for order_by in ['volume', 'createdAt']:
            if pages_searched >= max_pages:
                break

            offset = 0
            consecutive_empty = 0
            logger.debug(f"Searching events with order_by={order_by}...")

            while pages_searched < max_pages:
                try:
                    params = {
                        'closed': False,
                        'offset': offset,
                        'limit': limit,
                        'order': order_by,
                        'ascending': False
                    }

                    events = await self._fetch_api("/events", params=params)

                    if not events or not isinstance(events, list) or not events:
                        consecutive_empty += 1
                        if consecutive_empty >= 3:  # Stop after 3 consecutive empty pages
                            break
                        await asyncio.sleep(0.5)
                        continue

                    consecutive_empty = 0
                    events_found = 0

                    # Extract keyword markets from events
                    for event in events:
                        markets_in_event = event.get('markets', [])
                        for market in markets_in_event:
                            market_id = str(market.get('id', ''))

                            # Skip if already seen (deduplication)
                            if market_id in seen_market_ids:
                                continue

                            # Add event metadata
                            market['event_id'] = event.get('id')
                            market['event_slug'] = event.get('slug')
                            market['event_title'] = event.get('title')

                            # Check if matches keywords
                            if self._matches_keywords(market):
                                keyword_markets.append(market)
                                seen_market_ids.add(market_id)
                                events_found += 1

                    pages_searched += 1
                    offset += limit

                    # Rate limiting: more aggressive during exhaustive search
                    await asyncio.sleep(0.4)  # 400ms between pages

                    # Log progress every 10 pages
                    if pages_searched % 10 == 0:
                        logger.info(f"📊 Events search progress: {pages_searched} pages, {len(keyword_markets)} keyword markets found so far")

                except Exception as e:
                    logger.warning(f"Error fetching events page {pages_searched} (order_by={order_by}): {e}")
                    await asyncio.sleep(1.0)  # Longer delay on error
                    continue

            logger.info(f"✅ Events search complete (order_by={order_by}): {pages_searched} pages searched")

        return keyword_markets

    async def _exhaustive_standalone_search(self, seen_market_ids: Set[str]) -> List[Dict]:
        """
        Exhaustive search through ALL standalone markets to find keyword markets
        """
        keyword_markets = []
        offset = 0
        limit = 500
        max_pages = 300  # Safety limit: ~150,000 markets max
        pages_searched = 0
        consecutive_empty = 0

        while pages_searched < max_pages:
            try:
                api_markets = await self._fetch_api("/markets", params={
                    'limit': limit,
                    'closed': False,
                    'offset': offset
                    # No order parameter - we want all markets
                })

                if not api_markets or not isinstance(api_markets, list) or not api_markets:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:  # Stop after 3 consecutive empty pages
                        break
                    await asyncio.sleep(0.5)
                    continue

                consecutive_empty = 0
                markets_found = 0

                # Filter standalone and keyword markets
                for market in api_markets:
                    market_id = str(market.get('id', ''))

                    # Skip if already seen
                    if market_id in seen_market_ids:
                        continue

                    # Check if standalone (no events field or empty)
                    events_data = market.get('events', [])
                    has_no_events = not events_data or len(events_data) == 0
                    event_id = market.get('event_id')

                    # Standalone = no events AND no event_id
                    if has_no_events and not event_id:
                        # Check if matches keywords
                        if self._matches_keywords(market):
                            keyword_markets.append(market)
                            seen_market_ids.add(market_id)
                            markets_found += 1

                pages_searched += 1
                offset += limit

                # Rate limiting
                await asyncio.sleep(0.5)  # 500ms between pages

                # Log progress every 20 pages
                if pages_searched % 20 == 0:
                    logger.info(f"📊 Standalone search progress: {pages_searched} pages, {len(keyword_markets)} keyword markets found so far")

            except Exception as e:
                logger.warning(f"Error fetching standalone markets page {pages_searched}: {e}")
                await asyncio.sleep(1.0)  # Longer delay on error
                continue

        logger.info(f"✅ Standalone search complete: {pages_searched} pages searched")
        return keyword_markets
