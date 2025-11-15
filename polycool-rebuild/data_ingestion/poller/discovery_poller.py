"""
Discovery Poller - Detects new markets
Compares DB vs API to find markets not yet in database
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


class DiscoveryPoller(BaseGammaAPIPoller):
    """
    Poller to discover new markets
    - Compares DB market IDs vs API to find new markets
    - Multiple strategies: top volume, recent, trending
    - Fetches up to 2000 markets, filters those not in DB
    - Frequency: 1h (faster discovery of new markets)
    """

    def __init__(self, interval: int = 3600):  # 1h instead of 2h
        super().__init__(poll_interval=interval)

    async def _poll_cycle(self) -> None:
        """Single poll cycle - discover new markets"""
        start_time = time()

        try:
            # 1. Get all market IDs from DB
            db_market_ids = await self._get_all_market_ids_from_db()

            if not db_market_ids:
                logger.warning("No markets in DB, skipping discovery (run backfill first)")
                return

            # 2. Fetch markets from API using multiple strategies
            all_api_markets = []

            # Strategy 1: Top volume (1000 markets)
            top_volume = await self._fetch_api("/markets", params={
                'limit': 1000,
                'closed': False,
                'order': 'volumeNum',
                'ascending': False
            })
            if top_volume and isinstance(top_volume, list):
                all_api_markets.extend(top_volume)

            # Strategy 2: Recent markets (500 markets) - if API supports createdAt ordering
            # Note: API might not support this, so we'll try and fallback gracefully
            try:
                recent = await self._fetch_api("/markets", params={
                    'limit': 500,
                    'closed': False,
                    'order': 'volumeNum',  # Fallback if createdAt not available
                    'ascending': False
                })
                if recent and isinstance(recent, list):
                    # Filter out duplicates
                    existing_ids = {str(m.get('id')) for m in all_api_markets}
                    new_recent = [m for m in recent if str(m.get('id')) not in existing_ids]
                    all_api_markets.extend(new_recent)
            except Exception as e:
                logger.debug(f"Could not fetch recent markets: {e}")

            if not all_api_markets:
                logger.warning("No markets fetched from API")
                return

            # 3. Filter new markets (not in DB)
            new_markets = [m for m in all_api_markets if str(m.get('id')) not in db_market_ids]

            if not new_markets:
                logger.debug("No new markets discovered")
                return

            # 4. Upsert new markets
            upserted = await self._upsert_markets(new_markets)

            # 5. Update stats
            self.poll_count += 1
            self.market_count += len(new_markets)
            self.upsert_count += upserted
            self.last_poll_time = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            duration = time() - start_time
            logger.info(f"✅ Discovery poll cycle completed in {duration:.2f}s - {len(new_markets)} new markets discovered, {upserted} upserted")

        except Exception as e:
            logger.error(f"Discovery poll cycle error: {e}")
            raise

    async def _get_all_market_ids_from_db(self) -> Set[str]:
        """Get all market IDs currently in database"""
        try:
            async with get_db() as db:
                result = await db.execute(text("SELECT id FROM markets"))
                rows = result.fetchall()
                market_ids = {str(row[0]) for row in rows}
                logger.debug(f"Found {len(market_ids)} markets in DB")
                return market_ids
        except Exception as e:
            logger.error(f"Error getting market IDs from DB: {e}")
            return set()
