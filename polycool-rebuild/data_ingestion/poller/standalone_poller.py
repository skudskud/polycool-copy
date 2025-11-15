"""
Gamma API Poller - Standalone Markets Poller
Fetches top 500 standalone markets (markets without events) by volume
"""

from time import time
from datetime import datetime, timezone
from typing import List, Dict, Optional
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller

logger = get_logger(__name__)


class GammaAPIPollerStandalone(BaseGammaAPIPoller):
    """
    Poll Gamma API /markets endpoint for standalone markets
    - Fetches top 500 markets by volume (5min interval)
    - Filters out markets that have event_id (standalone only)
    - Covers ~1% of markets (standalone popular markets)
    """

    def __init__(self, interval: int = 300):
        super().__init__(poll_interval=interval)

    async def _poll_cycle(self) -> None:
        """Single poll cycle - fetch standalone markets"""
        start_time = time()

        try:
            # 1. Fetch top 500 markets by volume
            markets = await self._fetch_standalone_markets()

            if not markets:
                logger.warning("No standalone markets fetched")
                return

            # 2. Filter to ensure only standalone (no event_id)
            standalone_only = [m for m in markets if not m.get('event_id') and not m.get('events')]

            if not standalone_only:
                logger.info("No standalone markets found after filtering")
                return

            # 3. Upsert to unified markets table
            upserted = await self._upsert_markets(standalone_only)

            # 4. Update stats
            self.poll_count += 1
            self.market_count += len(standalone_only)
            self.upsert_count += upserted
            self.last_poll_time = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            duration = time() - start_time
            logger.info(f"✅ Standalone poll cycle completed in {duration:.2f}s - {len(standalone_only)} standalone markets, {upserted} upserted")

        except Exception as e:
            logger.error(f"Standalone poll cycle error: {e}")
            raise

    async def _fetch_standalone_markets(self) -> List[Dict]:
        """
        Fetch top 500 markets from /markets endpoint
        Filters out markets with events (standalone only)
        ENHANCED: Enrich markets with event data if they belong to events
        """
        markets = []
        offset = 0
        limit = 100  # Markets API limit
        max_markets = 500  # Target: top 500 standalone markets

        while offset < max_markets:
            batch = await self._fetch_api("/markets", params={
                'offset': offset,
                'limit': limit,
                'closed': False,
                'order': 'volumeNum',  # Order by volume (numeric)
                'ascending': False
            })

            if not batch or not isinstance(batch, list):
                break

            if not batch:
                break

            # Enrich markets with event data before adding to list
            enriched_batch = await self._enrich_markets_with_event_data(batch)
            markets.extend(enriched_batch)

            # If less than limit, we've reached the end
            if len(batch) < limit:
                break

            offset += limit

            # Stop at max_markets
            if len(markets) >= max_markets:
                markets = markets[:max_markets]
                break

        logger.info(f"📦 Fetched {len(markets)} markets from /markets endpoint (target: {max_markets})")
        return markets

    async def _enrich_markets_with_event_data(self, markets: List[Dict]) -> List[Dict]:
        """
        Enrich markets with event data if they belong to events
        This fixes the issue where markets don't have event_id but should be grouped
        """
        enriched_markets = []

        for market in markets:
            try:
                # Check if market already has event data
                if market.get('event_id') or market.get('events'):
                    enriched_markets.append(market)
                    continue

                # Try to find event data by searching for the market in events
                # This is a fallback for markets that should belong to events but don't have event_id
                market_id = market.get('id')
                if not market_id:
                    enriched_markets.append(market)
                    continue

                # Search for events that might contain this market
                # We'll search events by title similarity or other criteria
                event_data = await self._find_event_for_market(market)
                if event_data:
                    # Enrich market with event data
                    market['event_id'] = event_data.get('id')
                    market['event_slug'] = event_data.get('slug')
                    market['event_title'] = event_data.get('title')
                    market['events'] = [event_data]  # Add event data to events array
                    logger.debug(f"Enriched market {market_id} with event {event_data.get('id')}")

                enriched_markets.append(market)

            except Exception as e:
                logger.warning(f"Error enriching market {market.get('id')} with event data: {e}")
                enriched_markets.append(market)  # Still include market even if enrichment fails

        return enriched_markets

    async def _find_event_for_market(self, market: Dict) -> Optional[Dict]:
        """
        Try to find the event that contains this market
        Uses title similarity and other heuristics
        """
        try:
            market_title = market.get('question', '').lower()

            # Look for Super Bowl pattern
            if 'super bowl' in market_title and 'win super bowl' in market_title:
                # This is likely a Super Bowl team market
                # Search for Super Bowl 2026 event
                events = await self._fetch_api("/events", params={
                    'limit': 50,
                    'closed': False,
                    'order': 'volume',
                    'ascending': False
                })

                if events:
                    for event in events:
                        event_title = event.get('title', '').lower()
                        if 'super bowl' in event_title and '2026' in event_title:
                            # Found Super Bowl 2026 event
                            logger.debug(f"Found Super Bowl event for market {market.get('id')}: {event.get('id')}")
                            return event

            # Could extend this for other event patterns (NFL, NBA, etc.)

        except Exception as e:
            logger.warning(f"Error finding event for market {market.get('id')}: {e}")

        return None
