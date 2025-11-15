"""
Gamma API Poller - Resolutions Poller
Scans markets for resolution status changes (closed markets, expired markets)
"""

import asyncio
from time import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller
from core.database.connection import get_db
from sqlalchemy import text

logger = get_logger(__name__)


class GammaAPIPollerResolutions(BaseGammaAPIPoller):
    """
    Poll for market resolutions
    - Scans ALL non-resolved markets (15min interval)
    - Priority: expired markets, markets without end_date, then all others
    - Checks for resolution status changes (resolvedBy + closedTime + winner)
    - Updates resolved markets in DB
    - Some markets resolve before end_date or have no end_date
    """

    def __init__(self, interval: int = 900):  # 15min default
        super().__init__(poll_interval=interval)

    async def _poll_cycle(self) -> None:
        """Single poll cycle - check for market resolutions"""
        start_time = time()

        try:
            # 1. Get markets that might be resolved (from DB)
            candidate_markets = await self._get_resolution_candidates()

            if not candidate_markets:
                logger.debug("No resolution candidates found")
                return

            # 2. Fetch fresh data from API for candidates
            updated_markets = await self._fetch_markets_for_resolution(candidate_markets)

            if not updated_markets:
                logger.debug("No markets updated from API")
                return

            # 3. Check which ones are actually resolved
            resolved_markets = [m for m in updated_markets if self._is_market_really_resolved(m)]

            if not resolved_markets:
                logger.debug("No newly resolved markets found")
                return

            logger.info(f"✅ Resolutions detected: {len(resolved_markets)} markets resolved out of {len(updated_markets)} checked")

            # Log one example for debugging (only if resolutions found)
            if resolved_markets:
                market = resolved_markets[0]
                winner = self._calculate_winner(market)
                logger.debug(f"  📋 Example: Market {market.get('id')}: outcome={winner}, resolvedBy={market.get('resolvedBy')}, closed={market.get('closed')}")

            # 4. Upsert resolved markets (CRITICAL: allow_resolved=True to save resolution status)
            upserted = await self._upsert_markets(resolved_markets, allow_resolved=True)

            if upserted != len(resolved_markets):
                logger.warning(f"⚠️ Resolution mismatch: {len(resolved_markets)} resolved detected but only {upserted} upserted")

            # 5. Update stats
            self.poll_count += 1
            self.market_count += len(resolved_markets)
            self.upsert_count += upserted
            self.last_poll_time = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            duration = time() - start_time
            logger.info(f"✅ Resolutions poll cycle completed in {duration:.2f}s - {len(resolved_markets)} resolved markets, {upserted} upserted")

        except Exception as e:
            logger.error(f"Resolutions poll cycle error: {e}")
            raise

    async def _get_resolution_candidates(self) -> List[str]:
        """
        Get market IDs that might be resolved
        Priority order:
        1. Markets with end_date < now() but not resolved (expired)
        2. Markets with end_date NULL but not resolved (no expiration date)
        3. All non-resolved markets (for comprehensive check)
        Limit to reasonable batch size (200 markets per cycle)
        """
        try:
            async with get_db() as db:
                # Priority 1: Expired markets not resolved (INCREASED LIMIT for faster processing)
                result = await db.execute(text("""
                    SELECT id
                    FROM markets
                    WHERE end_date < now()
                    AND (is_resolved = false OR is_resolved IS NULL)
                    AND id IS NOT NULL
                    ORDER BY end_date DESC
                    LIMIT 500
                """))
                expired_ids = [row[0] for row in result.fetchall()]

                # Priority 2: Markets without end_date but not resolved
                result = await db.execute(text("""
                    SELECT id
                    FROM markets
                    WHERE end_date IS NULL
                    AND (is_resolved = false OR is_resolved IS NULL)
                    AND id IS NOT NULL
                    ORDER BY updated_at DESC
                    LIMIT 200
                """))
                no_end_date_ids = [row[0] for row in result.fetchall()]

                # Priority 3: Any non-resolved markets (for comprehensive check)
                result = await db.execute(text("""
                    SELECT id
                    FROM markets
                    WHERE (is_resolved = false OR is_resolved IS NULL)
                    AND id IS NOT NULL
                    ORDER BY updated_at DESC
                    LIMIT 100
                """))
                other_ids = [row[0] for row in result.fetchall()]

                # Combine and deduplicate
                all_ids = list(set(expired_ids + no_end_date_ids + other_ids))
                market_ids = all_ids[:500]  # INCREASED from 200 to 500 per cycle

                # Only log if significant number of candidates found
                if len(market_ids) > 0:
                    logger.debug(f"Found {len(market_ids)} resolution candidates ({len(expired_ids)} expired, {len(no_end_date_ids)} no end_date, {len(other_ids)} other)")
                return market_ids
        except Exception as e:
            logger.error(f"Error getting resolution candidates: {e}")
            return []

    async def _fetch_markets_for_resolution(self, market_ids: List[str]) -> List[Dict]:
        """
        Fetch fresh market data from API for resolution checking
        Fetches individually (API doesn't support bulk by ID)
        """
        updated_markets = []

        # Fetch markets individually (limited to 500 markets per cycle)
        for market_id in market_ids[:500]:
            try:
                market = await self._fetch_api(f"/markets/{market_id}")
                if market:
                    # Mark as regular market (not event parent)
                    market['is_event_parent'] = False
                    updated_markets.append(market)
            except Exception as e:
                logger.debug(f"Failed to fetch market {market_id}: {e}")
                continue

            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)

        # Only log if significant number fetched
        if len(updated_markets) > 0:
            logger.debug(f"Fetched {len(updated_markets)} markets for resolution check")
        return updated_markets
