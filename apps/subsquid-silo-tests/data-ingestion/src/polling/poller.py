"""
Gamma API Poller Service (Hybrid)
Fetches market data from both /events (grouped) and /markets (standalone) endpoints.
Updates subsquid_markets_poll with complete market data including events.
"""

import logging
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Set
from time import time
import json
from dateutil import parser as date_parser

from ..config import settings, validate_experimental_subsquid, TABLES
from ..db.client import get_db_client
# from .market_categorizer import MarketCategorizerService  # DISABLED: Causing TIER 0 to never execute

logger = logging.getLogger(__name__)


class PollerService:
    """Gamma API polling service - Hybrid approach"""

    def __init__(self):
        self.enabled = settings.POLLER_ENABLED
        self.client: Optional[httpx.AsyncClient] = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.backoff_seconds = 1.0
        self.max_backoff = settings.POLL_RATE_LIMIT_BACKOFF_MAX
        self.poll_count = 0
        self.market_count = 0
        self.upsert_count = 0
        self.last_poll_time = None
        self.last_sync = datetime.now(timezone.utc) - timedelta(hours=24)  # Track last sync

        # 🔥 EVENTS PRESERVATION MONITORING
        self.events_preserved_pass2 = 0

        # 🤖 AI CATEGORIZER - DISABLED (causing TIER 0 to never execute)
        # self.categorizer = MarketCategorizerService()
        # self.categorized_count = 0
        # self.max_categorizations_per_cycle = 50

    async def start(self):
        """Start the polling service"""
        if not self.enabled:
            logger.warning("⚠️ Poller service disabled (POLLER_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info("✅ Poller service starting...")

        self.client = httpx.AsyncClient(timeout=30.0)

        # Load last_sync from DB
        db = await get_db_client()
        self.last_sync = await db.get_poller_last_sync()
        logger.info(f"✅ Loaded last_sync from DB: {self.last_sync.isoformat()}")

        try:
            while True:
                await self.poll_cycle()
                await asyncio.sleep(settings.POLL_MS / 1000.0)
        except KeyboardInterrupt:
            logger.info("⏹️ Poller interrupted")
        except Exception as e:
            logger.error(f"❌ Poller fatal error: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the polling service"""
        if self.client:
            await self.client.aclose()
        logger.info("✅ Poller stopped")

    async def poll_cycle(self):
        """Single polling cycle using hybrid approach"""
        try:
            start_time = time()
            self.poll_count += 1

            total_upserted = 0
            seen_market_ids: Set[str] = set()

            # PASS 1: Grouped markets from /events - FULL COVERAGE MODE
            events_markets = await self._fetch_and_parse_events()
            if events_markets:
                logger.debug(f"📊 [PASS 1] Processing {len(events_markets)} markets from events...")

                # Process in chunks to avoid DB timeouts with full coverage
                chunk_size = 500
                for i in range(0, len(events_markets), chunk_size):
                    chunk = events_markets[i:i + chunk_size]
                    chunk = await self._enrich_markets_with_tokens(chunk)
                    db = await get_db_client()
                    upserted = await db.upsert_markets_poll(chunk)
                    total_upserted += upserted
                    await asyncio.sleep(0.1)  # Rate limiting between chunks

                for m in events_markets:
                    seen_market_ids.add(m.get("market_id"))

            # 🔥 DEBUG: Check if we reach PASS 2
            logger.info(f"🔥 [DEBUG] PASS 1 complete! About to start PASS 2...")

            # PASS 2: Update existing markets from /markets (includes PENDING and PROPOSED)
            # NEW LOGIC: Continue fetching markets until resolution_status = 'RESOLVED'
            # This ensures PROPOSED markets get updated until they become RESOLVED
            db = await get_db_client()
            existing_ids = await db.get_existing_market_ids(
                active_only=True,  # Parameter kept for backward compatibility
                include_recently_closed=True  # Parameter kept for backward compatibility
            )

            # 🚨🚨🚨 DEBUG: Confirm PASS 2 is executing
            logger.info(f"🚨🚨🚨 [PASS 2 DEBUG] Starting PASS 2 with {len(existing_ids)} existing markets, {len(seen_market_ids)} seen in PASS 1")

            standalone_markets = await self._fetch_and_update_existing_markets(existing_ids, seen_market_ids)
            if standalone_markets:
                # Enrich with tokens from Polymarket API
                standalone_markets = await self._enrich_markets_with_tokens(standalone_markets)
                upserted = await db.upsert_markets_poll(standalone_markets)
                total_upserted += upserted

            # PASS 3: CRITICAL - Lifecycle management (close expired/resolved markets)
            # Without this, your DB would fill with stale CLOSED markets!
            closed_updated = await self._update_closed_markets()
            total_upserted += closed_updated

            # 🚨 PASS 4: NEW - Re-evaluate PROPOSED markets for resolution
            # BUG FIX: 6,883 markets stuck in PROPOSED with extreme prices!
            # These were marked PROPOSED hours ago but may now have resolvable outcomes
            logger.debug(f"🔄 [PASS 4] Re-evaluating stuck PROPOSED markets...")
            proposed_upgraded = await self._upgrade_proposed_to_resolved()
            total_upserted += proposed_upgraded

            # Update last_sync in DB
            new_last_sync = datetime.now(timezone.utc)
            await db.update_poller_last_sync(new_last_sync)
            self.last_sync = new_last_sync

            # Summary - Log every 10 cycles only (reduced from every cycle)
            elapsed = time() - start_time
            if self.poll_count % 10 == 0:
                logger.info(f"✅ [CYCLE #{self.poll_count}] Total upserted: {total_upserted} in {elapsed:.2f}s")
                # 🔥 EVENTS PRESERVATION SUMMARY - CRITICAL FOR MONITORING FIX EFFECTIVENESS
                logger.info(f"🛡️ [EVENTS PRESERVATION] PASS 2: {self.events_preserved_pass2} markets preserved")
            else:
                logger.debug(f"✅ [CYCLE #{self.poll_count}] Total upserted: {total_upserted} in {elapsed:.2f}s")

            # Reset counters for next cycle
            self.events_preserved_pass2 = 0
            # self.categorized_count = 0  # DISABLED: AI categorization

            # PHASE 6: COMPREHENSIVE HEALTH MONITORING - coverage and freshness stats (reduced frequency to avoid Railway log limits)
            if self.poll_count % 60 == 0:  # Every 60 cycles (60 minutes) - REDUCED from 20 to avoid log spam
                try:
                    async with db.pool.acquire() as conn:
                        # Get comprehensive market coverage stats
                        stats = await conn.fetchrow("""
                            SELECT
                                COUNT(*) as total_active,
                                COUNT(*) FILTER (WHERE updated_at > NOW() - INTERVAL '5 minutes') as fresh_5min,
                                COUNT(*) FILTER (WHERE updated_at > NOW() - INTERVAL '1 hour') as fresh_1h,
                                COUNT(*) FILTER (WHERE updated_at > NOW() - INTERVAL '6 hours') as fresh_6h,
                                COUNT(*) FILTER (WHERE updated_at <= NOW() - INTERVAL '24 hours') as stale_24h,
                                COUNT(*) FILTER (WHERE array_length(outcome_prices, 1) IS NULL OR array_length(outcome_prices, 1) = 0) as missing_prices,
                                ROUND(AVG(EXTRACT(EPOCH FROM (NOW() - updated_at))/3600), 1) as avg_staleness_hours,
                                MIN(updated_at) as oldest_update,
                                MAX(updated_at) as newest_update
                            FROM subsquid_markets_poll
                            WHERE status = 'ACTIVE'
                        """)

                        # Calculate coverage percentages
                        total = stats['total_active'] or 0
                        fresh_5min_pct = (stats['fresh_5min'] or 0) / total * 100 if total > 0 else 0
                        fresh_1h_pct = (stats['fresh_1h'] or 0) / total * 100 if total > 0 else 0
                        fresh_6h_pct = (stats['fresh_6h'] or 0) / total * 100 if total > 0 else 0

                        logger.info(f"📊 [COVERAGE] Total: {total} active markets")
                        logger.info(f"🕐 [FRESHNESS] <5min: {stats['fresh_5min']} ({fresh_5min_pct:.1f}%) | <1h: {stats['fresh_1h']} ({fresh_1h_pct:.1f}%) | <6h: {stats['fresh_6h']} ({fresh_6h_pct:.1f}%)")
                        logger.info(f"⚠️ [STALENESS] >24h: {stats['stale_24h']} | Missing prices: {stats['missing_prices']} | Avg staleness: {stats['avg_staleness_hours']}h")
                        logger.info(f"📅 [RANGE] Oldest: {stats['oldest_update']} | Newest: {stats['newest_update']}")

                        # Alert if coverage is poor
                        if fresh_1h_pct < 50:
                            logger.warning(f"⚠️ LOW COVERAGE: Only {fresh_1h_pct:.1f}% of markets updated in last hour!")
                        if stats['missing_prices'] > 0:
                            logger.warning(f"⚠️ MISSING DATA: {stats['missing_prices']} markets without prices!")

                except Exception as health_error:
                    logger.warning(f"⚠️ Health check failed: {health_error}")

        except Exception as e:
            self.consecutive_errors += 1
            logger.error(f"❌ Poll cycle error: {e}")
            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.error(f"❌ Max consecutive errors ({self.max_consecutive_errors}) reached, stopping")
                raise

    async def _fetch_and_parse_events(self) -> List[Dict[str, Any]]:
        """Fetch grouped markets from /events endpoint - PRIORITIZE NEWEST MARKETS"""
        all_markets = []
        offset = 0
        limit = 200
        events_fetched = 0
        total_event_count = 0
        filtered_out = 0

        logger.debug(f"📊 [PASS 1] Fetching from /events (last_sync: {self.last_sync.isoformat()})...")

        # CRITICAL: Fetch enough pages to cover all high-volume events
        # With order=volume, top events will be in first pages
        max_pages = 200  # Enough to cover all active events with volume
        pages_fetched = 0

        while pages_fetched < max_pages:
            events = await self._fetch_events(offset, limit)
            if not events:
                break

            events_fetched += len(events)
            pages_fetched += 1

            # Extract markets from events
            for event in events:
                markets = event.get("markets", [])
                total_event_count += len(markets)

                for market in markets:
                    # Filter 1: Check if market is valid
                    if not self._is_market_valid(market):
                        filtered_out += 1
                        continue

                    # CRITICAL FIX: Remove 24-hour filter that was blocking high-volume markets!
                    # The filter was running BEFORE sorting, so top markets were excluded
                    # Now we add ALL valid markets, sort by volume, then take top 3000
                    # This ensures high-volume markets ALWAYS get updated regardless of age

                    enriched = await self._enrich_market_from_event(market, event)
                    all_markets.append(enriched)

            # Stop if we got fewer than limit (end of pagination)
            if len(events) < limit:
                break

            offset += limit
            await asyncio.sleep(0.05)  # Rate limiting

        # PHASE 3: CRITICAL FIX - Sort by VOLUME (not updated_at) to prioritize high-value markets
        # High-volume markets = high user interest = must have fresh prices!
        # Secondary sort by updated_at ensures recent trades within same volume tier
        all_markets.sort(
            key=lambda m: (
                float(m.get('volume', 0)),  # Primary: Volume (user interest indicator)
                m.get('updated_at', datetime.min.replace(tzinfo=timezone.utc))  # Secondary: Recency
            ),
            reverse=True
        )

        # Log top 5 markets for visibility
        if all_markets:
            top_5_summary = [f"{m.get('title', '')[:40]}... (${float(m.get('volume', 0))/1e6:.1f}M)" for m in all_markets[:5]]
            logger.debug(f"📊 [PASS 1] Top 5 markets by volume: {top_5_summary}")

        # PHASE 4: FULL COVERAGE - Remove artificial limit, process ALL discovered markets
        # Goal: 100% coverage of all active markets for complete bot functionality
        # Note: Markets are still sorted by volume for processing priority in enrichment
        logger.debug(f"📊 [PASS 1] Processing ALL {len(all_markets)} discovered markets (100% coverage)")

        logger.debug(f"✅ [PASS 1] {events_fetched} events → {len(all_markets)} markets (filtered: {filtered_out})")
        return all_markets

    async def _fetch_and_update_existing_markets(self, existing_ids: Set[str], exclude_ids: Set[str]) -> List[Dict[str, Any]]:
        """Multi-tier polling with user positions and urgent expiry prioritization

        TIER 0: USER_POSITIONS - Ultra-prioritaire (<3min resolution detection)
        - Markets with active user positions (watched_markets.active_positions > 0)
        - ALL polled every cycle (no rotation)
        - Endpoint: /markets bulk (full metadata needed for resolution status)

        TIER 1: URGENT_EXPIRY - Priorité haute (<5min resolution detection)
        - Markets expiring within 2 hours (end_date < NOW() + 2h)
        - ALL polled every cycle (no rotation)
        - Endpoint: /markets bulk (full metadata needed for resolution status)

        TIER 2-4: Volume-based distribution
        - HIGH (>100K): 700/min (12/cycle) - 97% of trading volume
        - MEDIUM (10K-100K): 180/min (3/cycle) - 2.6% of volume
        - SMALL (1K-10K): 20/min (1 every 3 cycles) - 0.4% of volume

        CRITICAL: Preserves events and category from DB to prevent data loss
        """
        all_markets = []
        db = await get_db_client()

        # ============================================================
        # TIER 0: USER_POSITIONS (Ultra-prioritaire - Fast resolution)
        # ============================================================
        user_position_ids = await db.get_user_position_market_ids()

        # 🚨🚨🚨 DEBUG LOG - ALWAYS VISIBLE
        logger.info(f"🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned {len(user_position_ids)} markets: {user_position_ids}")

        # CRITICAL: Always poll USER_POSITIONS, even if already in PASS 1
        # These markets need MAXIMUM freshness for <3min resolution detection
        # Don't exclude them - they should be polled in BOTH PASS 1 and TIER 0
        # This ensures they get updated every cycle regardless of PASS 1 coverage
        # user_position_ids = [mid for mid in user_position_ids if mid not in exclude_ids]  # REMOVED

        if user_position_ids:
            logger.info(f"🎯 [TIER 0: USER_POSITIONS] Polling {len(user_position_ids)} markets with active positions")

            # Fetch via /markets bulk (need full metadata for resolution status)
            markets = await self._fetch_markets_bulk(user_position_ids)

            if markets:
                # Enrich with tokens
                markets = await self._enrich_markets_with_tokens(markets)

                # Parse and preserve data
                tier0_markets = []
                for market in markets:
                    enriched = await self._parse_standalone_market(market)
                    tier0_markets.append(enriched)
                    all_markets.append(enriched)

                # 🔥 CRITICAL: Upsert TIER 0 markets IMMEDIATELY for fast resolution detection
                if tier0_markets:
                    upserted = await db.upsert_markets_poll(tier0_markets)
                    logger.info(f"✅ [TIER 0] Upserted {upserted} user position markets for fast resolution detection")

                # CRITICAL: Don't add USER_POSITIONS to exclude_ids
                # They should still be processable in other tiers if needed
                # But they'll be prioritized in TIER 0 for maximum freshness
                # for market_id in user_position_ids:
                #     exclude_ids.add(market_id)  # REMOVED

            await asyncio.sleep(0.1)  # Rate limiting

        # ============================================================
        # TIER 1: URGENT_EXPIRY (end_date < 2h) - Fast resolution prep
        # ============================================================
        urgent_ids = await db.get_markets_by_expiry_tier(hours=2, limit=50)

        # Exclude already processed markets
        urgent_ids = [mid for mid in urgent_ids if mid not in exclude_ids]

        if urgent_ids:
            logger.info(f"⏰ [TIER 1: URGENT_EXPIRY] Polling {len(urgent_ids)} markets expiring within 2h")

            # Fetch via /markets bulk (need full metadata for resolution status)
            markets = await self._fetch_markets_bulk(urgent_ids)

            if markets:
                # Enrich with tokens
                markets = await self._enrich_markets_with_tokens(markets)

                # Parse and preserve data
                for market in markets:
                    enriched = await self._parse_standalone_market(market)
                    all_markets.append(enriched)

                logger.info(f"✅ [TIER 1] Updated {len(markets)} urgent expiry markets")

                # Add to exclude_ids to avoid re-processing in other tiers
                for market_id in urgent_ids:
                    exclude_ids.add(market_id)

            await asyncio.sleep(0.1)  # Rate limiting

        # ============================================================
        # TIER 2+: Volume-based distribution (optimized)
        # ============================================================
        # Tier allocation per cycle (60 seconds)
        tiers = [
            {'name': 'HIGH', 'min_vol': 100000, 'max_vol': None, 'count': 12},  # 700/min ≈ 12/cycle
            {'name': 'MEDIUM', 'min_vol': 10000, 'max_vol': 100000, 'count': 3},  # 180/min ≈ 3/cycle
            {'name': 'SMALL', 'min_vol': 1000, 'max_vol': 10000, 'count': 1}  # 20/min ≈ 0.3/cycle
        ]

        logger.debug(f"📊 [PASS 2] Volume-based distribution (cycle #{self.poll_count}): targeting 16 markets")

        # Load preservation data ONCE for all tiers
        # NEW LOGIC: Include all non-RESOLVED markets for preservation
        # This ensures we preserve events/category for PENDING and PROPOSED markets
        events_by_market = {}
        try:
            db = await get_db_client()
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT market_id, events, category
                    FROM subsquid_markets_poll
                    WHERE (resolution_status != 'RESOLVED' OR resolution_status IS NULL)
                    AND market_id = ANY($1)
                """, list(existing_ids))

                for row in rows:
                    events_by_market[row['market_id']] = {
                        'events': row['events'],
                        'category': row['category']
                    }

            logger.debug(f"🛡️ [PASS 2] Loaded {len(events_by_market)} records for preservation")
        except Exception as e:
            logger.error(f"❌ [PASS 2] Failed to load preservation data: {e}")

        # Process each tier
        for tier in tiers:
            # Skip SMALL tier on non-multiple-of-3 cycles
            if tier['name'] == 'SMALL' and self.poll_count % 3 != 0:
                continue

            # Get market IDs for this tier
            # NEW LOGIC: Includes all non-RESOLVED markets (PENDING and PROPOSED)
            # This ensures markets continue to be fetched until resolution_status = 'RESOLVED'
            tier_ids = await db.get_markets_by_volume_tier(
                min_volume=tier['min_vol'],
                max_volume=tier['max_vol'],
                limit=tier['count'] * 100,  # Buffer for rotation
                include_recently_closed=True  # Parameter kept for backward compatibility
            )

            # Exclude already processed markets
            tier_ids = [mid for mid in tier_ids if mid not in exclude_ids]

            if not tier_ids:
                logger.debug(f"📄 [PASS 2] {tier['name']}: No markets to update")
                continue

            # Rotate through tier markets
            rotation_offset = (self.poll_count % len(tier_ids)) if tier_ids else 0
            selected_ids = tier_ids[rotation_offset:rotation_offset + tier['count']]

            if not selected_ids:
                continue

            # Fetch from Gamma API using bulk
            markets = await self._fetch_markets_bulk(selected_ids)

            if not markets:
                logger.debug(f"📄 [PASS 2] {tier['name']}: No markets returned from API")
                continue

            # Enrich and preserve data
            for market in markets:
                market_id = market.get('id') or market.get('market_id')
                enriched = await self._parse_standalone_market(market)

                # 🔥 CRITICAL: Preserve events and category from DB
                if market_id in events_by_market:
                    preserved = events_by_market[market_id]

                    # Preserve events (only if non-empty)
                    if preserved['events'] and len(preserved['events']) > 0:
                        enriched['events'] = preserved['events']
                        self.events_preserved_pass2 += 1

                    # Preserve category (only if new category is empty/missing)
                    if preserved['category'] and not enriched.get('category'):
                        enriched['category'] = preserved['category']

                all_markets.append(enriched)

            logger.debug(f"📄 [PASS 2] {tier['name']}: Updated {len(markets)}/{tier['count']} markets (target)")
            await asyncio.sleep(0.05)  # Rate limiting between tiers

        logger.debug(f"✅ [PASS 2] Total updated: {len(all_markets)} markets via volume distribution")
        logger.debug(f"🛡️ [PASS 2] Events preserved: {self.events_preserved_pass2} markets")

        return all_markets

    async def _update_closed_markets(self) -> int:
        """Update status of recently closed markets AND mark expired markets as CLOSED"""
        offset = 0
        limit = 200
        max_pages = 50
        updated_count = 0
        pages_fetched = 0
        expired_marked_closed = 0
        now = datetime.now(timezone.utc)

        logger.debug(f"📊 [PASS 3] Fetching closed markets and checking expired ones...")

        # FIRST: Mark expired ACTIVE markets as CLOSED in database
        db = await get_db_client()
        expired_count = await self._mark_expired_markets_as_closed(db)
        expired_marked_closed += expired_count
        logger.debug(f"✅ [PASS 3] Marked {expired_count} expired markets as CLOSED")

        # SECOND: Fetch recently closed markets from Gamma API
        for page in range(max_pages):
            markets = await self._fetch_markets(offset, closed_only=True)
            if not markets:
                break

            pages_fetched += 1

            # Filter to recently updated (last 24 hours)
            recently_closed = []
            for m in markets:
                try:
                    updated_at_str = m.get("updatedAtMs") or m.get("updatedAt")
                    if updated_at_str:
                        updated_at = datetime.fromtimestamp(int(updated_at_str)/1000, tz=timezone.utc)
                        if (now - updated_at).days < 1:
                            enriched = self._parse_standalone_market(m)
                            recently_closed.append(enriched)
                except:
                    pass

            if recently_closed:
                # OPT 5 FIX: Bypass filter for CLOSED markets (lifecycle management)
                # These markets MUST be upserted to update ACTIVE → CLOSED status
                count = await db.upsert_markets_poll(recently_closed, skip_filter=True)
                updated_count += count

            if len(markets) < limit:
                break

            offset += limit
            await asyncio.sleep(0.05)

        total_updated = updated_count + expired_marked_closed
        logger.debug(f"✅ [PASS 3] Updated {total_updated} markets ({expired_marked_closed} expired marked CLOSED, {updated_count} from API, pages: {pages_fetched})")
        return total_updated

    async def _mark_expired_markets_as_closed(self, db) -> int:
        """Mark ACTIVE markets that have expired as CLOSED (handles both end_date and closed field)"""
        async with db.pool.acquire() as conn:
            try:
                now = datetime.now(timezone.utc)

                # CRITICAL FIX: Remove 1-hour grace period to mark expired markets immediately
                # This ensures markets are marked CLOSED right after expiration for faster resolution detection
                # Previously: expired_cutoff = now - timedelta(hours=1)
                # Now: Mark markets expired as soon as end_date < now
                expired_cutoff = now

                # FIX 1: Mark markets with past end_date as CLOSED and PROPOSED
                # PROPOSED means market is closed but outcome not yet determined
                update_query = """
                    UPDATE subsquid_markets_poll
                    SET status = 'CLOSED',
                        resolution_status = CASE
                            WHEN resolution_status = 'PENDING' THEN 'PROPOSED'
                            ELSE resolution_status
                        END,
                        accepting_orders = false,
                        tradeable = false,
                        updated_at = $1
                    WHERE status = 'ACTIVE'
                      AND end_date IS NOT NULL
                      AND end_date < $2
                """

                # Execute update (removed 30-day restriction)
                update_result = await conn.execute(update_query, now, expired_cutoff)

                # Get count from result (PostgreSQL returns affected row count)
                if update_result and update_result.startswith('UPDATE'):
                    expired_count = int(update_result.split()[1])
                else:
                    expired_count = 0

                if expired_count > 0:
                    logger.debug(f"🔒 [EXPIRED-DATE] Marked {expired_count} past-date markets as CLOSED")

                # FIX 2: Mark old stale ACTIVE markets (not updated in 3+ days) as CLOSED
                # These are likely closed but we haven't polled them recently (avg staleness is 4+ days)
                # Conservative threshold: 3 days (72 hours) - if not polled in 3 days, likely closed
                stale_cutoff = now - timedelta(days=3)
                stale_query = """
                    UPDATE subsquid_markets_poll
                    SET status = 'CLOSED',
                        accepting_orders = false,
                        tradeable = false,
                        updated_at = $1
                    WHERE status = 'ACTIVE'
                      AND updated_at < $2
                """

                stale_result = await conn.execute(stale_query, now, stale_cutoff)

                if stale_result and stale_result.startswith('UPDATE'):
                    stale_count = int(stale_result.split()[1])
                else:
                    stale_count = 0

                if stale_count > 0:
                    logger.debug(f"🔒 [EXPIRED-STALE] Marked {stale_count} stale (3+ days old) markets as CLOSED")

                total_closed = expired_count + stale_count
                return total_closed

            except Exception as e:
                logger.error(f"❌ Error marking expired markets as closed: {e}")
                return 0

    async def _fetch_events(self, offset: int, limit: int) -> List[Dict[str, Any]]:
        """Fetch events from /events endpoint"""
        if not self.client:
            return []

        # CRITICAL FIX: Order by volume to get high-value events first (Super Bowl, F1, etc.)
        # order=id would require 4,400 pages to reach Super Bowl (ID 23656 vs latest 903799)
        url = f"{settings.GAMMA_API_URL.replace('/markets', '')}/events?limit={limit}&offset={offset}&closed=false&order=volume&ascending=false"

        try:
            response = await self.client.get(url, timeout=30.0)
            if response.status_code == 200:
                events = response.json()
                return events if isinstance(events, list) else events.get("data", [])
            elif response.status_code == 429:
                logger.warning(f"⚠️ Rate limited (429)")
                await asyncio.sleep(2)
                return []
        except Exception as e:
            logger.debug(f"⚠️ Error fetching events: {e}")

        return []

    async def _upgrade_proposed_to_resolved(self) -> int:
        """
        🚨 CRITICAL FIX: Re-evaluate markets that may now be resolvable.

        Problem: Thousands of markets stuck in PENDING/PROPOSED status with extreme prices
        because poller doesn't re-evaluate them after initial assignment.

        Solution:
        1. Upgrade PENDING markets with end_date past to PROPOSED (if >1h expired)
        2. Upgrade PROPOSED/PENDING markets with extreme prices to RESOLVED
        """
        db = await get_db_client()
        upgraded_count = 0

        try:
            # STEP 1: Fix PENDING markets that should be PROPOSED (end_date passed >1h)
            pending_to_proposed = await db.pool.execute("""
                UPDATE subsquid_markets_poll
                SET resolution_status = 'PROPOSED',
                    status = 'CLOSED',
                    updated_at = NOW()
                WHERE resolution_status = 'PENDING'
                  AND end_date < NOW() - interval '1 hour'
                  AND status = 'CLOSED'
            """)

            if pending_to_proposed and pending_to_proposed.startswith('UPDATE'):
                pending_count = int(pending_to_proposed.split()[1])
                if pending_count > 0:
                    # Only log if significant number to avoid log spam
                    if pending_count >= 50:
                        logger.info(f"✅ [PASS 4] Upgraded {pending_count} PENDING→PROPOSED (expired >1h)")
                    else:
                        logger.debug(f"✅ [PASS 4] Upgraded {pending_count} PENDING→PROPOSED (expired >1h)")
                    upgraded_count += pending_count

            # STEP 2: Fetch PROPOSED markets with USER_POSITIONS prioritization
            # Priority:
            # 1. Markets with user positions (from watched_markets) - CRITICAL for <3min detection
            # 2. Recently expired markets (end_date < 24h ago)
            # 3. Other PROPOSED markets
            # Increased limit to 1000 per cycle for better coverage
            proposed_markets = await db.pool.fetch("""
                SELECT
                    sp.market_id,
                    sp.title,
                    sp.outcome_prices,
                    sp.end_date,
                    sp.resolution_status,
                    CASE
                        WHEN wm.market_id IS NOT NULL THEN 0  -- Highest priority: user positions
                        WHEN sp.end_date > NOW() - INTERVAL '24 hours' THEN 1  -- High priority: recently expired
                        ELSE 2  -- Normal priority
                    END as priority
                FROM subsquid_markets_poll sp
                LEFT JOIN watched_markets wm ON sp.condition_id = wm.market_id AND wm.active_positions > 0
                WHERE sp.resolution_status = 'PROPOSED'
                  AND sp.winning_outcome IS NULL
                  AND sp.end_date < NOW() - interval '1 hour'
                  AND sp.outcome_prices IS NOT NULL
                  AND array_length(sp.outcome_prices, 1) = 2
                ORDER BY priority ASC, sp.end_date DESC
                LIMIT 1000
            """)

            if not proposed_markets:
                logger.debug(f"✅ [PASS 4] No PROPOSED markets to check")
            else:
                logger.info(f"🔍 [PASS 4] Checking {len(proposed_markets)} PROPOSED markets with fresh API data")

            # STEP 2.1: Fetch fresh market data from API
            market_ids = [m['market_id'] for m in proposed_markets]
            fresh_markets_data = {}

            if market_ids:
                try:
                    # Use bulk API to fetch fresh data for all PROPOSED markets
                    fresh_markets = await self._fetch_markets_bulk(market_ids)

                    # Build a map for quick lookup
                    for market_data in fresh_markets:
                        market_id = market_data.get('id') or market_data.get('market_id')
                        if market_id:
                            fresh_markets_data[market_id] = market_data

                    logger.debug(f"✅ [PASS 4] Fetched {len(fresh_markets_data)} fresh market data from API")
                except Exception as e:
                    logger.warning(f"⚠️ [PASS 4] Error fetching fresh market data: {e}")
                    # Fallback: use DB prices if API fetch fails
                    fresh_markets_data = {}

            # STEP 2.2: Check each PROPOSED market with fresh API data
            resolved_count = 0
            for market in proposed_markets:
                try:
                    market_id = market['market_id']

                    # Use fresh API data if available, otherwise fallback to DB data
                    if market_id in fresh_markets_data:
                        # Use fresh API data (most reliable - has outcome field + fresh prices)
                        market_dict = fresh_markets_data[market_id]
                    else:
                        # Fallback: use DB data (may be stale but better than nothing)
                        market_dict = {
                            "outcomePrices": market['outcome_prices'],
                            "outcome_prices": market['outcome_prices'],
                            "id": market_id,
                            "question": market['title']
                        }

                    # Extract winning outcome (checks API outcome field first, then prices)
                    outcome = PollerService._extract_winning_outcome(market_dict)

                    if outcome is not None:
                        # Extract fresh outcome_prices and volume from API data
                        outcome_prices = None
                        volume = None
                        volume_24hr = None

                        if market_id in fresh_markets_data:
                            api_market = fresh_markets_data[market_id]

                            # Parse outcomePrices (can be string or list)
                            prices = api_market.get("outcomePrices", [])
                            if isinstance(prices, str):
                                try:
                                    prices = json.loads(prices)
                                except json.JSONDecodeError:
                                    prices = []

                            if prices and len(prices) >= 2:
                                try:
                                    # Convert to float array (round to 4 decimals)
                                    outcome_prices = [
                                        round(float(prices[0]), 4),
                                        round(float(prices[1]), 4)
                                    ]
                                except (ValueError, TypeError):
                                    pass

                            # Extract volume fields
                            volume = PollerService._cap_numeric(api_market.get("volume", 0))
                            volume_24hr = PollerService._cap_numeric(api_market.get("volume24hr", 0))

                        # Build UPDATE query with fresh data
                        if outcome_prices is not None:
                            # Include outcome_prices and volume in UPDATE
                            await db.pool.execute("""
                                UPDATE subsquid_markets_poll
                                SET resolution_status = 'RESOLVED',
                                    winning_outcome = $1,
                                    outcome_prices = $2,
                                    volume = $3,
                                    volume_24hr = $4,
                                    resolution_date = NOW(),
                                    status = 'CLOSED',
                                    updated_at = NOW()
                                WHERE market_id = $5
                            """, outcome, outcome_prices, volume, volume_24hr, market_id)
                        else:
                            # Fallback: Update without prices/volume (use existing DB values)
                            await db.pool.execute("""
                                UPDATE subsquid_markets_poll
                                SET resolution_status = 'RESOLVED',
                                    winning_outcome = $1,
                                    resolution_date = NOW(),
                                    status = 'CLOSED',
                                    updated_at = NOW()
                                WHERE market_id = $2
                            """, outcome, market_id)

                        resolved_count += 1
                        # Reduced logging frequency to avoid Railway log limits
                        if resolved_count % 100 == 0:
                            logger.debug(f"✅ [PASS 4] Upgraded {resolved_count} →RESOLVED")

                except Exception as e:
                    logger.debug(f"⚠️ [PASS 4] Error upgrading {market['market_id']}: {e}")

            if resolved_count > 0:
                # Only log if significant number to avoid log spam
                if resolved_count >= 10:
                    logger.info(f"✅ [PASS 4] TOTAL UPGRADED TO RESOLVED: {resolved_count} markets")
                else:
                    logger.debug(f"✅ [PASS 4] TOTAL UPGRADED TO RESOLVED: {resolved_count} markets")
                upgraded_count += resolved_count

        except Exception as e:
            logger.warning(f"⚠️ [PASS 4] Error in _upgrade_proposed_to_resolved: {e}")

        return upgraded_count

    async def _fetch_markets(self, offset: int, closed_only: bool = False) -> List[Dict[str, Any]]:
        """Fetch markets from /markets endpoint"""
        if not self.client:
            return []

        if not closed_only:
            url = f"{settings.GAMMA_API_URL}?limit={settings.POLL_LIMIT}&offset={offset}&closed=false&order=id&ascending=false"
        else:
            url = f"{settings.GAMMA_API_URL}?limit={settings.POLL_LIMIT}&offset={offset}&closed=true&order=id&ascending=false"

        try:
            response = await self.client.get(url, timeout=30.0)
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, list) else data.get("data", [])
            elif response.status_code == 429:
                logger.warning(f"⚠️ Rate limited (429)")
                await asyncio.sleep(2)
                return []
        except Exception as e:
            logger.debug(f"⚠️ Error fetching markets: {e}")

        return []

    async def _fetch_markets_bulk(self, market_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch specific markets by IDs using bulk API

        Args:
            market_ids: List of market IDs to fetch

        Returns:
            List of market dicts from Gamma API
        """
        if not self.client or not market_ids:
            return []

        all_markets = []

        # Batch into chunks of 100 IDs
        for i in range(0, len(market_ids), 100):
            chunk_ids = market_ids[i:i + 100]
            ids_param = ','.join(chunk_ids)

            url = f"{settings.GAMMA_API_URL}?id={ids_param}&limit=500"

            try:
                response = await self.client.get(url, timeout=30.0)
                if response.status_code == 200:
                    data = response.json()
                    markets = data if isinstance(data, list) else data.get("data", [])
                    all_markets.extend(markets)
                elif response.status_code == 429:
                    logger.warning(f"⚠️ Rate limited (429)")
                    await asyncio.sleep(2)
            except Exception as e:
                logger.debug(f"⚠️ Error fetching bulk markets: {e}")

            await asyncio.sleep(0.05)  # Rate limiting between chunks

        return all_markets

    async def _fetch_prices_bulk_endpoint(self, token_ids: List[str]) -> Dict[str, Dict[str, float]]:
        """Fetch prices using /prices bulk endpoint (10x faster than /markets)

        Endpoint: GET https://clob.polymarket.com/prices?tokenIds=X,Y,Z
        Response: {"token1": {"BUY": "0.8", "SELL": "0.81"}, ...}

        Args:
            token_ids: List of token IDs to fetch prices for

        Returns:
            Dict mapping token_id to {"BUY": price, "SELL": price}
        """
        if not self.client or not token_ids:
            return {}

        all_prices = {}

        # Batch 100 tokens per request (API limit)
        for i in range(0, len(token_ids), 100):
            chunk = token_ids[i:i + 100]
            ids_param = ','.join(chunk)

            url = f"https://clob.polymarket.com/prices?tokenIds={ids_param}"

            try:
                response = await self.client.get(url, timeout=10.0)
                if response.status_code == 200:
                    prices = response.json()
                    all_prices.update(prices)
                elif response.status_code == 429:
                    logger.warning(f"⚠️ Rate limited on /prices endpoint (429)")
                    await asyncio.sleep(2)
            except Exception as e:
                logger.debug(f"⚠️ Error fetching bulk prices: {e}")

            await asyncio.sleep(0.05)  # Rate limiting between chunks

        logger.debug(f"📊 Fetched prices for {len(all_prices)}/{len(token_ids)} tokens via /prices bulk")
        return all_prices

    async def _enrich_markets_with_tokens(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich markets with tokens from Polymarket API
        OPTIMIZED: Pre-load clob_token_ids from DB to avoid redundant API calls
        """
        try:
            # Collect all market IDs
            market_ids = []
            for market in markets:
                market_id = market.get("market_id")
                if market_id:
                    market_ids.append(market_id)

            if not market_ids:
                return markets

            # 🔥 OPTIMIZATION: Pre-load clob_token_ids from DB
            # This avoids refetching tokens for markets that already have them!
            db = await get_db_client()
            db_tokens = {}
            try:
                async with db.pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT market_id, clob_token_ids, tokens
                        FROM subsquid_markets_poll
                        WHERE market_id = ANY($1)
                          AND clob_token_ids IS NOT NULL
                          AND clob_token_ids != '[]'
                    """, market_ids)

                    for row in rows:
                        db_tokens[row['market_id']] = {
                            'clob_token_ids': row['clob_token_ids'],
                            'tokens': row['tokens']
                        }

                    logger.debug(f"🔥 [ENRICH] Pre-loaded {len(db_tokens)}/{len(market_ids)} markets with existing tokens from DB")
            except Exception as e:
                logger.warning(f"⚠️ [ENRICH] Failed to pre-load from DB: {e}")

            # Merge DB data into markets BEFORE API calls
            markets_needing_api = []
            for market in markets:
                market_id = market.get("market_id")
                if not market_id:
                    continue

                # Check if we have this in DB
                if market_id in db_tokens:
                    market["clob_token_ids"] = db_tokens[market_id]['clob_token_ids']
                    market["tokens"] = db_tokens[market_id]['tokens']
                    logger.debug(f"✅ [ENRICH] Market {market_id}: Using cached tokens from DB")
                else:
                    markets_needing_api.append(market_id)

            # Only fetch from API for markets NOT in DB
            if not markets_needing_api:
                logger.info(f"✅ [ENRICH] All {len(markets)} markets already have tokens in DB - skipping API calls!")
                return markets

            total_markets = len(markets)
            logger.info(f"🔍 [ENRICH] Need to fetch tokens for {len(markets_needing_api)}/{total_markets} markets from API")

            # Replace market_ids with only those needing API calls
            market_ids = markets_needing_api

            # Fetch tokens from Polymarket API individually to avoid 422 errors
            # Even with batch_size=20, we still get 422 errors - switching to individual requests
            batch_size = 1
            all_polymarket_data = {}

            for i in range(0, len(market_ids), batch_size):
                batch = market_ids[i:i + batch_size]
                # Minimal progress logging - only every 10 batches
                batch_num = i//batch_size + 1
                total_batches = (len(market_ids) + batch_size - 1)//batch_size
                if batch_num % 10 == 1 and batch_num > 1:  # Only log every 10th batch, skip first
                    logger.debug(f"🔍 [ENRICH] Batch {batch_num}/{total_batches}")

                try:
                    # Fetch from Polymarket API - individual requests to avoid 422
                    if len(batch) == 1:
                        # Single market request
                        url = f"https://gamma-api.polymarket.com/markets/{batch[0]}"
                        params = {}
                    else:
                        # Batch request (fallback, but unlikely with batch_size=1)
                        url = "https://gamma-api.polymarket.com/markets"
                        params = {
                            "id": ",".join(batch),
                            # Removed "network": "base" as it might cause 422 errors
                        }

                    response = await self.client.get(url, params=params, timeout=30)
                    if response.status_code == 200:
                        data = response.json()

                        # Handle different response formats from Polymarket API
                        if len(batch) == 1:
                            # Single market request: direct object response
                            polymarket_markets = [data] if data and isinstance(data, dict) else []
                        elif isinstance(data, list):
                            # Multiple markets response: direct list
                            polymarket_markets = data
                        elif isinstance(data, dict) and "markets" in data:
                            # Structured response: {"markets": [...]}
                            polymarket_markets = data["markets"]
                        else:
                            # Fallback
                            polymarket_markets = [data] if data else []

                        for pm_market in polymarket_markets:
                            if isinstance(pm_market, dict):
                                market_id = pm_market.get("id")
                                if market_id:
                                    all_polymarket_data[market_id] = pm_market

                    # Only log API errors, not successes (too noisy)
                    if response.status_code != 200:
                        logger.warning(f"⚠️ [ENRICH] Polymarket API returned {response.status_code}")

                except Exception as e:
                    logger.error(f"❌ [ENRICH] Error fetching batch: {e}")

                # Rate limiting
                await asyncio.sleep(0.1)

            # Enrich markets with Polymarket data
            enriched_count = 0
            for market in markets:
                market_id = market.get("market_id")
                if not market_id:
                    continue

                # Get existing clob_token_ids from Gamma API
                existing_clob_ids = market.get("clob_token_ids", [])
                existing_tokens = market.get("tokens", [])

                # Check if we already have good data from Gamma
                has_clob_ids = existing_clob_ids and len(existing_clob_ids) > 0
                has_tokens = existing_tokens and len(existing_tokens) > 0

                if has_clob_ids and has_tokens:
                    logger.debug(f"✅ [ENRICH] Market {market_id}: Already has both clob_token_ids and tokens from Gamma")
                    continue

                # Try to enrich from Polymarket
                pm_market = all_polymarket_data.get(market_id)
                if not pm_market:
                    logger.debug(f"⚠️ [ENRICH] Market {market_id}: Not found in Polymarket data")
                    continue

                # Extract tokens from Polymarket
                pm_tokens = pm_market.get("tokens", [])
                pm_clob_ids = pm_market.get("clob_token_ids", [])

                # Parse clob_token_ids if it's a string
                if isinstance(pm_clob_ids, str):
                    try:
                        pm_clob_ids = json.loads(pm_clob_ids)
                    except:
                        pm_clob_ids = []

                # Only update if we don't have the data or if Polymarket has better data
                updated = False

                # Update clob_token_ids if missing or empty
                if not has_clob_ids and pm_clob_ids:
                    market["clob_token_ids"] = [str(tid) for tid in pm_clob_ids if tid]
                    updated = True

                # Update tokens if missing or empty
                if not has_tokens and pm_tokens:
                    market["tokens"] = pm_tokens
                    updated = True

                if updated:
                    enriched_count += 1

            if enriched_count > 0:
                logger.debug(f"✅ [ENRICH] Enriched {enriched_count}/{len(markets)} markets")

        except Exception as e:
            logger.error(f"❌ Error enriching markets with tokens: {e}", exc_info=True)
            # Don't break the flow, just log the error

        return markets

        try:
            polymarket_url = f"{settings.POLYMARKET_API_URL}?closed=false&archived=false&active=true&limit=1000"
            response = await self.client.get(polymarket_url, timeout=30.0)

            if response.status_code != 200:
                logger.warning(f"⚠️ Failed to fetch tokens from Polymarket API: {response.status_code}")
                for market in markets:
                    market.setdefault("tokens", [])
                    market.setdefault("clob_token_ids", [])
                return markets

            data = response.json()
            polymarket_markets = data.get("data", []) if isinstance(data, dict) else data

            # Build lookup maps so we can match regardless of identifier differences
            tokens_by_id: Dict[str, List[Dict[str, Any]]] = {}
            tokens_by_slug: Dict[str, List[Dict[str, Any]]] = {}
            tokens_by_question: Dict[str, List[Dict[str, Any]]] = {}
            tokens_by_condition: Dict[str, List[Dict[str, Any]]] = {}
            tokens_by_question_id: Dict[str, List[Dict[str, Any]]] = {}
            token_ids_by_id: Dict[str, List[str]] = {}
            token_ids_by_slug: Dict[str, List[str]] = {}
            token_ids_by_question: Dict[str, List[str]] = {}
            token_ids_by_condition: Dict[str, List[str]] = {}
            token_ids_by_question_id: Dict[str, List[str]] = {}

            for pm_market in polymarket_markets:
                market_id = pm_market.get("id") or pm_market.get("market_id")
                slug = pm_market.get("slug") or pm_market.get("market_slug")
                question = pm_market.get("question")
                condition_id = pm_market.get("condition_id") or pm_market.get("conditionId")
                question_id = pm_market.get("question_id") or pm_market.get("questionId")
                outcomes = pm_market.get("outcomes") or []

                tokens_raw = pm_market.get("tokens")
                clob_ids_raw = pm_market.get("clobTokenIds") or pm_market.get("clob_token_ids")

                normalized_tokens: List[Dict[str, Any]] = []
                normalized_token_ids: List[str] = []

                if isinstance(tokens_raw, list) and tokens_raw:
                    for token in tokens_raw:
                        if isinstance(token, dict):
                            token_id = (
                                token.get("token_id")
                                or token.get("tokenId")
                                or token.get("tokenID")
                                or token.get("id")
                            )
                            if token_id:
                                normalized_token_ids.append(str(token_id))
                            normalized_tokens.append(token)
                        elif token:
                            normalized_token_ids.append(str(token))
                            normalized_tokens.append({"token_id": str(token), "outcome": None})

                if not normalized_tokens and clob_ids_raw:
                    try:
                        iterable_ids = clob_ids_raw if isinstance(clob_ids_raw, list) else json.loads(clob_ids_raw)
                    except Exception:
                        iterable_ids = []

                    for idx, token_id in enumerate(iterable_ids):
                        token_id_str = str(token_id)
                        normalized_token_ids.append(token_id_str)
                        outcome = outcomes[idx] if isinstance(outcomes, list) and idx < len(outcomes) else None
                        normalized_tokens.append({"token_id": token_id_str, "outcome": outcome})

                if not normalized_token_ids:
                    continue

                if market_id:
                    key = str(market_id)
                    tokens_by_id[key] = normalized_tokens
                    token_ids_by_id[key] = normalized_token_ids
                if slug:
                    key = str(slug)
                    tokens_by_slug[key] = normalized_tokens
                    token_ids_by_slug[key] = normalized_token_ids
                if question:
                    key = str(question)
                    tokens_by_question[key] = normalized_tokens
                    token_ids_by_question[key] = normalized_token_ids
                if condition_id:
                    key = str(condition_id)
                    tokens_by_condition[key] = normalized_tokens
                    token_ids_by_condition[key] = normalized_token_ids
                if question_id:
                    key = str(question_id)
                    tokens_by_question_id[key] = normalized_tokens
                    token_ids_by_question_id[key] = normalized_token_ids

            for market in markets:
                matched_tokens: Optional[List[Dict[str, Any]]] = None
                matched_token_ids: Optional[List[str]] = None

                market_id = market.get("market_id")
                if market_id:
                    matched_tokens = tokens_by_id.get(str(market_id))
                    matched_token_ids = token_ids_by_id.get(str(market_id))

                if not matched_tokens and market.get("condition_id"):
                    cond_key = str(market["condition_id"])
                    matched_tokens = tokens_by_condition.get(cond_key)
                    matched_token_ids = token_ids_by_condition.get(cond_key)

                if not matched_tokens and market.get("slug"):
                    slug_key = str(market["slug"])
                    matched_tokens = tokens_by_slug.get(slug_key)
                    matched_token_ids = token_ids_by_slug.get(slug_key)

                if not matched_tokens:
                    question_key = market.get("title") or market.get("question")
                    if question_key:
                        q_key = str(question_key)
                        matched_tokens = tokens_by_question.get(q_key)
                        matched_token_ids = token_ids_by_question.get(q_key)

                if not matched_tokens and market.get("question_id"):
                    qid_key = str(market["question_id"])
                    matched_tokens = tokens_by_question_id.get(qid_key)
                    matched_token_ids = token_ids_by_question_id.get(qid_key)

                if matched_tokens or matched_token_ids:
                    tokens_payload: List[Dict[str, Any]] = matched_tokens if matched_tokens is not None else []
                    token_ids: List[str] = matched_token_ids if matched_token_ids is not None else []

                    # 🔍 DEBUG: Log enrichment details
                    logger.debug(f"🔍 [ENRICH_DEBUG] Market {market.get('market_id')}: matched_tokens={len(tokens_payload)}, matched_token_ids={len(token_ids)}")

                    if not tokens_payload and token_ids:
                        tokens_payload = [{"token_id": tid, "outcome": None} for tid in token_ids]
                        logger.debug(f"🔍 [ENRICH_DEBUG] Market {market.get('market_id')}: Created tokens_payload from token_ids")

                    market["tokens"] = tokens_payload

                    if not token_ids and matched_tokens:
                        for token in matched_tokens:
                            if isinstance(token, dict):
                                token_id = (
                                    token.get("token_id")
                                    or token.get("tokenId")
                                    or token.get("tokenID")
                                    or token.get("id")
                                )
                                if token_id:
                                    token_ids.append(str(token_id))
                            elif token:
                                token_ids.append(str(token))
                        logger.debug(f"🔍 [ENRICH_DEBUG] Market {market.get('market_id')}: Created token_ids from matched_tokens")

                    market["clob_token_ids"] = token_ids
                    logger.info(
                        f"✅ [ENRICH_DEBUG] Enriched market {market.get('market_id')} with {len(market.get('clob_token_ids', []))} CLOB tokens and {len(market.get('tokens', []))} tokens"
                    )
                else:
                    market.setdefault("tokens", [])
                    market["clob_token_ids"] = []
                    logger.debug(
                        f"⚠️ No tokens found for market {market.get('market_id')}: "
                        f"{(market.get('title') or '')[:50]}..."
                    )

        except Exception as e:
            logger.error(f"❌ Error enriching markets with tokens: {e}", exc_info=True)
            for market in markets:
                market.setdefault("tokens", [])
                market["clob_token_ids"] = []

        return markets

    @staticmethod
    def _cap_numeric(value: float, max_value: float = 99999999.9999) -> float:
        """Cap numeric value to prevent overflow in NUMERIC(12,4) columns"""
        if value is None:
            return 0.0
        try:
            capped = min(float(value), max_value)
            return round(capped, 4)
        except:
            return 0.0

    @staticmethod
    def _is_market_valid(market: Dict[str, Any]) -> bool:
        """Filter out invalid markets:
        - Only check if outcome prices exist (removed date and price range filters)
        """
        try:
            # Check outcome prices validity - just check they exist
            outcome_prices = market.get("outcomePrices", [])
            if isinstance(outcome_prices, str):
                import json
                try:
                    outcome_prices = json.loads(outcome_prices)
                except:
                    outcome_prices = []

            # Only filter if no prices at all
            if not outcome_prices or len(outcome_prices) == 0:
                return False

            return True
        except:
            return True

    def _detect_market_resolution(self, market_data: Dict, end_date: Optional[datetime]) -> tuple[str, str, Optional[int]]:
        """
        Détecte statut + résolution pour redeem automatique

        Returns:
            (status, resolution_status, winning_outcome)

        Catégorie 1 - ACTIVE en pause:
          Bitcoin Up/Down avant expiration → ("ACTIVE", "PENDING", None)

        Catégorie 2 - Expiré récemment:
          Bitcoin Up/Down après expiration → ("CLOSED", "PROPOSED", 1) puis ("CLOSED", "RESOLVED", 1)

        Catégorie 3 - Fermé prématurément:
          Lewis Hamilton éliminé → ("CLOSED", "RESOLVED", 0)
        """
        now = datetime.now(timezone.utc)
        api_closed = market_data.get("closed", False)

        # Catégorie 2: Market expiré
        if end_date and end_date < now:
            grace_period = now - timedelta(hours=1)

            if end_date < grace_period:
                # Expiré >1h, outcome devrait être dispo
                outcome = self._extract_winning_outcome(market_data)
                if outcome is not None:
                    return "CLOSED", "RESOLVED", outcome
                else:
                    return "CLOSED", "PROPOSED", None
            else:
                # Vient d'expirer (<1h), attente outcome
                return "CLOSED", "PROPOSED", None

        # Catégorie 3: Fermé prématurément (end_date future)
        if (end_date is None or end_date > now) and api_closed:
            outcome = self._extract_winning_outcome(market_data)
            if outcome is not None:
                return "CLOSED", "RESOLVED", outcome
            else:
                return "CLOSED", "PROPOSED", None

        # Catégorie 1: ACTIVE (ignore tradeable=false)
        if (end_date is None or end_date > now) and not api_closed:
            return "ACTIVE", "PENDING", None

        return "CLOSED", "PENDING", None

    @staticmethod
    def _extract_winning_outcome(market_data: Dict) -> Optional[int]:
        """
        Extrait outcome gagnant depuis API Gamma

        PRIORITÉ: Utiliser les données de l'API en premier, puis les prix comme fallback

        Méthodes (par ordre de priorité):
        1. Champ "outcome" de l'API: "Yes" → 1, "No" → 0 (SOURCE DE VÉRITÉ)
        2. umaResolutionStatuses de l'API: "resolved" + prix extrêmes → gagnant (SOURCE DE VÉRITÉ)
        3. Prix finaux: [>=0.99, <=0.01] → 1, [<=0.01, >=0.99] → 0 (fallback)
        """
        import json

        # 🔥 PRIORITÉ 1: Champ explicite "outcome" de l'API (source de vérité)
        # L'API Gamma retourne ce champ quand le marché est résolu
        outcome_str = market_data.get("outcome")
        if outcome_str:
            outcome_str_lower = str(outcome_str).lower().strip()
            if outcome_str_lower in ["yes", "1", "true"]:
                # Reduced logging frequency to avoid Railway log limits
                logger.debug(f"✅ [OUTCOME] API field 'outcome' = '{outcome_str}' → YES (1)")
                return 1
            elif outcome_str_lower in ["no", "0", "false"]:
                # Reduced logging frequency to avoid Railway log limits
                logger.debug(f"✅ [OUTCOME] API field 'outcome' = '{outcome_str}' → NO (0)")
                return 0
            else:
                logger.warning(f"⚠️ [OUTCOME] Unknown outcome value from API: '{outcome_str}'")

        # 🔥 PRIORITÉ 2: umaResolutionStatuses de l'API
        # Si le marché est marqué "resolved" par UMA ET a des prix extrêmes, on peut déterminer le gagnant
        uma_status = market_data.get("umaResolutionStatuses") or market_data.get("umaResolutionStatus")
        if uma_status:
            uma_status_lower = str(uma_status).lower().strip()
            # Removed verbose logging to reduce Railway log limits

            # Si le statut indique que c'est résolu, on peut utiliser les prix pour déterminer le gagnant
            if uma_status_lower in ["resolved", "yes", "no"]:
                # Extraire les prix pour déterminer le gagnant
                prices = market_data.get("outcomePrices") or market_data.get("outcome_prices") or []

                # Parse if it's a JSON string
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except json.JSONDecodeError:
                        prices = []

                if len(prices) == 2:
                    try:
                        yes_price, no_price = float(prices[0]), float(prices[1])

                        # Si le statut UMA dit "resolved" ET prix extrêmes, on peut déterminer
                        if yes_price >= 0.99 and no_price <= 0.01:
                            # Reduced logging frequency to avoid Railway log limits
                            logger.debug(f"✅ [OUTCOME] umaResolutionStatuses='{uma_status}' + YES price={yes_price} → YES (1)")
                            return 1
                        elif no_price >= 0.99 and yes_price <= 0.01:
                            # Reduced logging frequency to avoid Railway log limits
                            logger.debug(f"✅ [OUTCOME] umaResolutionStatuses='{uma_status}' + NO price={no_price} → NO (0)")
                            return 0
                        else:
                            logger.debug(f"ℹ️ [OUTCOME] umaResolutionStatuses='{uma_status}' but prices not extreme: YES={yes_price}, NO={no_price}")
                    except (ValueError, TypeError) as e:
                        logger.debug(f"⚠️ [OUTCOME] Failed to parse prices with umaResolutionStatuses: {e}")

        # 🔥 PRIORITÉ 3: Prix finaux (fallback si pas d'outcome API ni umaResolutionStatuses)
        # Utiliser les prix seulement si l'API n'a pas retourné de champ "outcome" ou "umaResolutionStatuses"
        # 🔧 FIX: Try BOTH outcomePrices (camelCase from API) AND outcome_prices (snake_case from DB)
        # 🔧 FIX 2: Handle BOTH string (JSON) and list formats
        prices = market_data.get("outcomePrices") or market_data.get("outcome_prices") or []

        # Parse if it's a JSON string
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
                # Removed verbose logging to reduce Railway log limits
            except json.JSONDecodeError as e:
                logger.debug(f"⚠️ [OUTCOME] Failed to parse prices as JSON: {prices} - {e}")
                prices = []

        if len(prices) == 2:
            try:
                yes_price, no_price = float(prices[0]), float(prices[1])
                # Removed verbose logging to reduce Railway log limits

                # 🔧 FIX: Use >= instead of > to capture prices like 0.9995, 0.999, etc.
                # Also use <= instead of < to be more inclusive
                # Note: This is a FALLBACK - API "outcome" field should be preferred
                if yes_price >= 0.99 and no_price <= 0.01:
                    # Reduced logging frequency to avoid Railway log limits
                    logger.debug(f"✅ [OUTCOME] Detected YES as winner from prices! (YES={yes_price}, NO={no_price})")
                    return 1
                elif no_price >= 0.99 and yes_price <= 0.01:
                    # Reduced logging frequency to avoid Railway log limits
                    logger.debug(f"✅ [OUTCOME] Detected NO as winner from prices! (YES={yes_price}, NO={no_price})")
                    return 0
                else:
                    logger.debug(f"ℹ️ [OUTCOME] Prices not extreme enough: YES={yes_price}, NO={no_price} (need >=0.99 to be winner)")
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ [OUTCOME] Failed to parse prices {prices}: {e}")
        elif prices:
            # Removed verbose logging to reduce Railway log limits
            pass
        else:
            # Removed verbose logging to reduce Railway log limits
            pass

        # Aucune méthode n'a fonctionné
        return None

    async def _categorize_market(self, market: Dict[str, Any]) -> str:
        """
        Extract and normalize category from Gamma API response using AI categorizer

        ONLY categorizes ACTIVE, tradeable markets to save costs and focus on relevant markets.

        Process:
        1. Check if market is ACTIVE and tradeable
        2. Extract raw category from Gamma API
        3. If empty or not in our 5 categories AND market is active, use AI categorizer
        4. Otherwise normalize existing category

        Returns:
            Normalized category: Geopolitics, Sports, Finance, Crypto, or Other
        """
        # Extract market status
        status = market.get("status", "").upper()
        active = market.get("active", False)
        accepting_orders = market.get("acceptingOrders", False)
        tradeable = market.get("tradeable", False)

        # ONLY categorize ACTIVE/tradeable markets
        is_active_market = (
            status == "ACTIVE" or
            active == True or
            accepting_orders == True or
            tradeable == True
        )

        # SIMPLIFIED: No AI categorization (was blocking TIER 0)
        # Just use static mapping from Gamma API category
        raw_category = self._extract_raw_category(market)

        # Simple static normalization
        category_map = {
            "politics": "Geopolitics",
            "geopolitics": "Geopolitics",
            "sports": "Sports",
            "finance": "Finance",
            "crypto": "Crypto",
            "cryptocurrency": "Crypto",
            "business": "Finance",
            "economics": "Finance",
            "bitcoin": "Crypto",
            "ethereum": "Crypto",
        }

        if raw_category:
            lower_cat = raw_category.lower().strip()
            normalized = category_map.get(lower_cat, raw_category)
            return normalized if normalized else "Other"

        return "Other"

    @staticmethod
    def _extract_raw_category(market: Dict[str, Any]) -> str:
        """
        Extract raw category from Gamma API response

        Gamma API returns category as:
        - Object: {"id": "crypto", "label": "Cryptocurrency", "slug": "crypto"}
        - OR String: "Sports" (rare)
        - OR Empty/None

        Returns:
            Raw Polymarket category label (e.g., "Cryptocurrency", "Sports")
        """
        category = market.get("category", "")

        if isinstance(category, dict):
            # Extract label from category object
            return category.get("label", "")
        elif isinstance(category, str):
            # Already a string, return as-is
            return category
        else:
            # None or unexpected type
            return ""

    @staticmethod
    def _build_polymarket_url(market_dict: Dict) -> str:
        """
        Construit l'URL Polymarket pour un market
        Priorité: event_slug > market_slug
        """
        events = market_dict.get('events', [])

        # Si market appartient à un event, utiliser event_slug
        if events and len(events) > 0:
            event_slug = events[0].get('event_slug')
            if event_slug:
                return f"https://polymarket.com/event/{event_slug}"

        # Sinon, utiliser market_slug
        market_slug = market_dict.get('slug', '')
        if market_slug:
            return f"https://polymarket.com/market/{market_slug}"

        return ""

    async def _enrich_market_from_event(self, market: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """Parse market from event response"""
        import json

        # Parse outcomes and prices
        outcomes = []
        outcome_prices = []
        try:
            outcomes_list = market.get("outcomes", "[]")
            if isinstance(outcomes_list, str):
                outcomes_list = json.loads(outcomes_list)
            prices_list = market.get("outcomePrices", "[]")
            if isinstance(prices_list, str):
                prices_list = json.loads(prices_list)

            for i, outcome_name in enumerate(outcomes_list):
                price = float(prices_list[i]) if i < len(prices_list) else 0.0
                outcomes.append(outcome_name)
                outcome_prices.append(round(price, 4))
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

        # Calculate mid price
        last_mid = None
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                last_mid = round(sum(outcome_prices) / len(outcome_prices), 4)
            except:
                pass

        # Parse end_date
        end_date = None
        try:
            if market.get("endDate"):
                end_date_str = market.get("endDate")
                if isinstance(end_date_str, str):
                    end_date = date_parser.parse(end_date_str)
                else:
                    end_date = end_date_str
        except:
            pass

        # Build events array from parent event
        events = []
        if event:
            try:
                events.append({
                    "event_id": event.get("id"),
                    "event_slug": event.get("slug"),
                    "event_title": event.get("title"),
                    "event_category": event.get("category"),
                    "event_volume": PollerService._cap_numeric(event.get("volume", 0)),
                })
            except:
                pass

        # 🔥 LOGIQUE DE RÉSOLUTION BASÉE SUR L'API
        # On utilise les données de l'API Gamma pour déterminer resolution_status
        #
        # Priorité:
        # 1. Champ "outcome" de l'API → RESOLVED directement
        # 2. umaResolutionStatuses="resolved" + prix extrêmes → RESOLVED
        # 3. Prix extrêmes seuls → RESOLVED (fallback)
        # 4. end_date passée → PROPOSED (en attente)
        # 5. Sinon → PENDING

        now = datetime.now(timezone.utc)
        api_closed = market.get("closed", False)

        # 🔥 ÉTAPE 1: Vérifier si l'API retourne un outcome (marché résolu)
        api_outcome = PollerService._extract_winning_outcome(market)

        if api_outcome is not None:
            # L'API a retourné un outcome → marché résolu
            status, resolution_status, winning_outcome = "CLOSED", "RESOLVED", api_outcome
            resolution_date = now
        elif end_date and end_date < now:
            # Marché expiré mais pas encore de outcome dans l'API
            grace_period = now - timedelta(hours=1)
            if end_date < grace_period:
                # Expiré >1h → PROPOSED (en attente de résolution)
                status, resolution_status, winning_outcome = "CLOSED", "PROPOSED", None
                resolution_date = None
            else:
                # Vient d'expirer (<1h) → PROPOSED
                status, resolution_status, winning_outcome = "CLOSED", "PROPOSED", None
                resolution_date = None
        elif (end_date is None or end_date > now) and api_closed:
            # Fermé prématurément (end_date future mais closed=true)
            status, resolution_status, winning_outcome = "CLOSED", "PROPOSED", None
            resolution_date = None
        elif (end_date is None or end_date > now) and not api_closed:
            # Marché actif
            status, resolution_status, winning_outcome = "ACTIVE", "PENDING", None
            resolution_date = None
        else:
            # Cas par défaut
            status, resolution_status, winning_outcome = "CLOSED", "PENDING", None
            resolution_date = None

        # Normalize clob token ids straight from Gamma payload (fallback if Polymarket match fails)
        raw_clob_ids = market.get("clob_token_ids") or market.get("clobTokenIds") or []
        clob_token_ids: List[str] = []

        # Parse clob_token_ids with minimal logging
        if isinstance(raw_clob_ids, list):
            clob_token_ids = [str(token) for token in raw_clob_ids if token]
        elif isinstance(raw_clob_ids, str):
            try:
                parsed = json.loads(raw_clob_ids)
                if isinstance(parsed, list):
                    clob_token_ids = [str(token) for token in parsed if token]
            except json.JSONDecodeError:
                pass

        # Log only mismatches (reduce noise)
        if len(clob_token_ids) != len(outcomes):
            logger.debug(f"⚠️ [TOKEN] Market {market.get('id')}: {len(outcomes)} outcomes vs {len(clob_token_ids)} tokens")

        # PHASE 1: Preserve Gamma API's updatedAt timestamp for proper sorting
        # This is CRITICAL for prioritizing recently-traded markets
        gamma_updated_at = None
        try:
            if market.get("updatedAt"):
                gamma_updated_at = date_parser.parse(market.get("updatedAt"))
        except Exception as e:
            logger.debug(f"⚠️ Failed parsing updatedAt for market {market.get('id')}: {e}")
            pass

        # Build market dict
        market_dict = {
            "market_id": market.get("id"),
            "condition_id": market.get("conditionId", ""),
            "title": market.get("question", ""),
            "slug": market.get("slug", ""),
            "status": status,
            "resolution_status": resolution_status,
            "winning_outcome": winning_outcome,
            "resolution_date": resolution_date,
            "category": await self._categorize_market(market),
            "description": market.get("description", ""),
            "outcomes": outcomes,
            "outcome_prices": outcome_prices,
            "tokens": market.get("tokens", []),  # 🔥 CRITICAL: Store tokens array for outcome matching
            "clob_token_ids": clob_token_ids,  # 🔥 FIX: Use parsed clob_token_ids from Gamma API
            "last_mid": last_mid,
            "volume": PollerService._cap_numeric(market.get("volume", 0)),
            "volume_24hr": PollerService._cap_numeric(market.get("volume24hr", 0)),
            "volume_1wk": PollerService._cap_numeric(market.get("volume1wk", 0)),
            "volume_1mo": PollerService._cap_numeric(market.get("volume1mo", 0)),
            "liquidity": PollerService._cap_numeric(market.get("liquidity", 0)),
            "tradeable": market.get("active", False),
            "accepting_orders": market.get("acceptingOrders", False),
            "end_date": end_date,
            "events": events,
            "updated_at": gamma_updated_at or datetime.now(timezone.utc),  # ✅ PHASE 1: Preserve API timestamp!
        }

        # Build Polymarket URL
        market_dict["polymarket_url"] = PollerService._build_polymarket_url(market_dict)

        return market_dict

    async def _parse_standalone_market(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Parse standalone market from /markets response"""
        import json

        # Parse outcomes and prices
        outcomes = []
        outcome_prices = []
        try:
            outcomes_list = market.get("outcomes", "[]")
            if isinstance(outcomes_list, str):
                outcomes_list = json.loads(outcomes_list)
            prices_list = market.get("outcomePrices", "[]")
            if isinstance(prices_list, str):
                prices_list = json.loads(prices_list)

            for i, outcome_name in enumerate(outcomes_list):
                price = float(prices_list[i]) if i < len(prices_list) else 0.0
                outcomes.append(outcome_name)
                outcome_prices.append(round(price, 4))
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

        # Calculate mid price
        last_mid = None
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                last_mid = round(sum(outcome_prices) / len(outcome_prices), 4)
            except:
                pass

        # Parse end_date
        end_date = None
        try:
            if market.get("endDate"):
                end_date_str = market.get("endDate")
                if isinstance(end_date_str, str):
                    end_date = date_parser.parse(end_date_str)
                else:
                    end_date = end_date_str
        except:
            pass

        # 🔥 LOGIQUE DE RÉSOLUTION BASÉE SUR L'API (même logique que _enrich_market_from_event)
        # On utilise les données de l'API Gamma pour déterminer resolution_status
        #
        # Priorité:
        # 1. Champ "outcome" de l'API → RESOLVED directement
        # 2. umaResolutionStatuses="resolved" + prix extrêmes → RESOLVED
        # 3. Prix extrêmes seuls → RESOLVED (fallback)
        # 4. end_date passée → PROPOSED (en attente)
        # 5. Sinon → PENDING

        now = datetime.now(timezone.utc)
        api_closed = market.get("closed", False)

        # 🔥 ÉTAPE 1: Vérifier si l'API retourne un outcome (marché résolu)
        api_outcome = PollerService._extract_winning_outcome(market)

        if api_outcome is not None:
            # L'API a retourné un outcome → marché résolu
            status, resolution_status, winning_outcome = "CLOSED", "RESOLVED", api_outcome
            resolution_date = now
        elif end_date and end_date < now:
            # Marché expiré mais pas encore de outcome dans l'API
            grace_period = now - timedelta(hours=1)
            if end_date < grace_period:
                # Expiré >1h → PROPOSED (en attente de résolution)
                status, resolution_status, winning_outcome = "CLOSED", "PROPOSED", None
                resolution_date = None
            else:
                # Vient d'expirer (<1h) → PROPOSED
                status, resolution_status, winning_outcome = "CLOSED", "PROPOSED", None
                resolution_date = None
        elif (end_date is None or end_date > now) and api_closed:
            # Fermé prématurément (end_date future mais closed=true)
            status, resolution_status, winning_outcome = "CLOSED", "PROPOSED", None
            resolution_date = None
        elif (end_date is None or end_date > now) and not api_closed:
            # Marché actif
            status, resolution_status, winning_outcome = "ACTIVE", "PENDING", None
            resolution_date = None
        else:
            # Cas par défaut
            status, resolution_status, winning_outcome = "CLOSED", "PENDING", None
            resolution_date = None

        raw_clob_ids = market.get("clob_token_ids") or market.get("clobTokenIds") or []
        clob_token_ids: List[str] = []

        # Parse clob_token_ids with minimal logging
        if isinstance(raw_clob_ids, list):
            clob_token_ids = [str(token) for token in raw_clob_ids if token]
        elif isinstance(raw_clob_ids, str):
            try:
                parsed = json.loads(raw_clob_ids)
                if isinstance(parsed, list):
                    clob_token_ids = [str(token) for token in parsed if token]
            except json.JSONDecodeError:
                pass

        # Log only mismatches (reduce noise)
        if len(clob_token_ids) != len(outcomes):
            logger.debug(f"⚠️ [TOKEN] Market {market.get('id')}: {len(outcomes)} outcomes vs {len(clob_token_ids)} tokens")

        # PHASE 2: Preserve Gamma API's updatedAt timestamp (same as _enrich_market_from_event)
        gamma_updated_at = None
        try:
            if market.get("updatedAt"):
                gamma_updated_at = date_parser.parse(market.get("updatedAt"))
        except Exception as e:
            logger.debug(f"⚠️ Failed parsing updatedAt for market {market.get('id')}: {e}")
            pass

        # Build market dict
        market_dict = {
            "market_id": market.get("id"),
            "condition_id": market.get("conditionId", ""),
            "title": market.get("question", ""),
            "slug": market.get("slug", ""),
            "status": status,
            "resolution_status": resolution_status,
            "winning_outcome": winning_outcome,
            "resolution_date": resolution_date,
            "category": await self._categorize_market(market),
            "description": market.get("description", ""),
            "outcomes": outcomes,
            "outcome_prices": outcome_prices,
            "tokens": market.get("tokens", []),  # 🔥 CRITICAL: Store tokens array for outcome matching
            "clob_token_ids": clob_token_ids,  # 🔥 FIX: Use parsed clob_token_ids from Gamma API
            "last_mid": last_mid,
            "volume": PollerService._cap_numeric(market.get("volume", 0)),
            "volume_24hr": PollerService._cap_numeric(market.get("volume24hr", 0)),
            "volume_1wk": PollerService._cap_numeric(market.get("volume1wk", 0)),
            "volume_1mo": PollerService._cap_numeric(market.get("volume1mo", 0)),
            "liquidity": PollerService._cap_numeric(market.get("liquidity", 0)),
            "tradeable": market.get("active", False),
            "accepting_orders": market.get("acceptingOrders", False),
            "end_date": end_date,
            # Note: events field preserved from DB in PASS 2
            "updated_at": gamma_updated_at or datetime.now(timezone.utc),  # ✅ PHASE 2: Preserve API timestamp!
        }

        # Build Polymarket URL
        market_dict["polymarket_url"] = PollerService._build_polymarket_url(market_dict)

        return market_dict

    @staticmethod
    def _validate_outcome_prices(prices: List[float]) -> bool:
        """Validate outcome prices are realistic"""
        if not prices or len(prices) < 2:
            return False

        placeholder_patterns = [
            [0.0, 1.0],
            [1.0, 0.0],
            [0.5, 0.5],
        ]

        normalized_prices = [round(p, 1) for p in prices]
        if normalized_prices in placeholder_patterns:
            return False

        price_sum = round(sum(prices), 4)
        if abs(price_sum - 1.0) > 0.01:
            return False

        for price in prices:
            if price < 0.0 or price > 1.0:
                return False

        return True


# Global poller instance
_poller_instance: Optional[PollerService] = None


async def get_poller() -> PollerService:
    """Get or create global poller instance"""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = PollerService()
    return _poller_instance


# Entry point for running poller as standalone service
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        format=settings.LOG_FORMAT,
        level=settings.LOG_LEVEL
    )

    # Silence httpx INFO logs (HTTP requests spam)
    logging.getLogger('httpx').setLevel(logging.WARNING)

    async def main():
        poller = await get_poller()
        await poller.start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Poller stopped")
        sys.exit(0)
