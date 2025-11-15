"""
Price Poller - Maintains fresh prices for popular markets
Uses layered strategy: featured events, top volume, trending, user positions, copy trading
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


class PricePoller(BaseGammaAPIPoller):
    """
    Poller to maintain fresh prices for popular markets
    Layered strategy:
    1. Featured events (featured=true) - priority maximum
    2. Top 200 by volume (very active markets)
    3. Top 300 by volume24hr (trending)
    4. Markets with active user positions (200)
    5. Markets with copy trading active (300)
    Total: ~1000 markets max
    Frequency: 30s
    """

    def __init__(self, interval: int = 30):
        super().__init__(poll_interval=interval)

    async def _poll_cycle(self) -> None:
        """Single poll cycle - update prices for popular markets"""
        start_time = time()

        try:
            all_market_ids: Set[str] = set()

            # Layer 1: Featured events (priority maximum)
            featured_markets = await self._fetch_featured_markets()
            for market in featured_markets:
                all_market_ids.add(str(market.get('id')))

            # Layer 2: Top volume markets
            top_volume_markets = await self._fetch_top_volume_markets(200)
            for market in top_volume_markets:
                all_market_ids.add(str(market.get('id')))

            # Layer 3: Trending markets (volume24hr)
            trending_markets = await self._fetch_trending_markets(300)
            for market in trending_markets:
                all_market_ids.add(str(market.get('id')))

            # Layer 4: User positions (from DB)
            user_position_markets = await self._get_markets_with_user_positions(200)
            all_market_ids.update(user_position_markets)

            # Layer 5: Copy trading (from DB)
            copy_trading_markets = await self._get_copy_trading_markets(300)
            all_market_ids.update(copy_trading_markets)

            # Limit to 1000 markets max
            market_ids_list = list(all_market_ids)[:1000]
            logger.info(f"📊 Price poller: {len(market_ids_list)} unique markets to update")

            # Fetch fresh data for all markets
            updated_markets = await self._fetch_markets_by_ids(market_ids_list)

            if not updated_markets:
                logger.debug("No markets updated")
                return

            # Upsert updated markets
            upserted = await self._upsert_markets(updated_markets)

            # Update stats
            self.poll_count += 1
            self.market_count += len(updated_markets)
            self.upsert_count += upserted
            self.last_poll_time = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            duration = time() - start_time
            logger.info(f"✅ Price poll cycle completed in {duration:.2f}s - {len(updated_markets)} markets updated, {upserted} upserted")

        except Exception as e:
            logger.error(f"Price poll cycle error: {e}")
            raise

    async def _fetch_featured_markets(self) -> List[Dict]:
        """Fetch markets from featured events AND create event parent markets"""
        try:
            featured_events = await self._fetch_api("/events", params={
                'featured': True,
                'limit': 50,
                'closed': False
            })

            if not featured_events or not isinstance(featured_events, list):
                return []

            # Extract markets from featured events
            all_markets = []
            for event in featured_events:
                event_id = str(event.get('id', ''))
                event_slug = event.get('slug', '')
                event_title = event.get('title', '')

                # CREATE EVENT PARENT MARKET
                event_market = {
                    'id': event_id,
                    'question': event_title,
                    'description': event.get('description', ''),
                    'category': 'Events',
                    'outcomes': ['Various'],  # Events don't have simple yes/no outcomes
                    'outcomePrices': [0.5],  # Placeholder price
                    'events': [],  # No parent events for root events
                    'volume': event.get('volume', 0),
                    'liquidity': event.get('liquidity', 0),
                    'lastTradePrice': None,
                    'clobTokenIds': None,
                    'conditionId': None,
                    'startDate': event.get('startDate'),
                    'endDate': event.get('endDate'),
                    'event_id': event_id,  # Self-reference for event markets
                    'event_slug': event_slug,
                    'event_title': event_title,
                    'is_event_parent': True  # Custom flag to mark as parent
                }
                all_markets.append(event_market)

                # Add child markets
                markets_in_event = event.get('markets', [])
                for market in markets_in_event:
                    market['event_id'] = event_id
                    market['event_slug'] = event_slug
                    market['event_title'] = event_title
                    market['is_event_parent'] = False  # Mark as child
                    all_markets.append(market)

            logger.debug(f"Found {len(all_markets)} markets/events from {len(featured_events)} featured events")
            return all_markets
        except Exception as e:
            logger.error(f"Error fetching featured markets: {e}")
            return []

    async def _fetch_top_volume_markets(self, limit: int) -> List[Dict]:
        """Fetch top markets by volume"""
        try:
            markets = await self._fetch_api("/markets", params={
                'limit': limit,
                'closed': False,
                'order': 'volumeNum',
                'ascending': False
            })

            if not markets or not isinstance(markets, list):
                return []

            # Mark as regular markets (not event parents)
            for market in markets:
                market['is_event_parent'] = False

            logger.debug(f"Fetched {len(markets)} top volume markets")
            return markets
        except Exception as e:
            logger.error(f"Error fetching top volume markets: {e}")
            return []

    async def _fetch_trending_markets(self, limit: int) -> List[Dict]:
        """Fetch trending markets (by volume24hr)"""
        try:
            # Note: API might not have volume24hr ordering, use volumeNum as fallback
            markets = await self._fetch_api("/markets", params={
                'limit': limit,
                'closed': False,
                'order': 'volumeNum',  # Fallback if volume24hr not available
                'ascending': False
            })

            if not markets or not isinstance(markets, list):
                return []

            # Mark as regular markets (not event parents)
            for market in markets:
                market['is_event_parent'] = False

            logger.debug(f"Fetched {len(markets)} trending markets")
            return markets
        except Exception as e:
            logger.error(f"Error fetching trending markets: {e}")
            return []

    async def _get_markets_with_user_positions(self, limit: int) -> Set[str]:
        """Get market IDs with active user positions from DB"""
        try:
            async with get_db() as db:
                result = await db.execute(text("""
                    SELECT DISTINCT market_id
                    FROM positions
                    WHERE market_id IS NOT NULL
                    AND (closed_at IS NULL OR closed_at > now())
                    LIMIT :limit
                """), {'limit': limit})
                rows = result.fetchall()
                market_ids = {str(row[0]) for row in rows}
                logger.debug(f"Found {len(market_ids)} markets with user positions")
                return market_ids
        except Exception as e:
            logger.debug(f"Error getting markets with user positions (table might not exist): {e}")
            return set()

    async def _get_copy_trading_markets(self, limit: int) -> Set[str]:
        """Get market IDs with active copy trading from DB"""
        try:
            async with get_db() as db:
                # Check if copy_trading table exists, if not return empty set
                result = await db.execute(text("""
                    SELECT DISTINCT market_id
                    FROM copy_trading
                    WHERE market_id IS NOT NULL
                    AND active = true
                    LIMIT :limit
                """), {'limit': limit})
                rows = result.fetchall()
                market_ids = {str(row[0]) for row in rows}
                logger.debug(f"Found {len(market_ids)} markets with copy trading")
                return market_ids
        except Exception as e:
            logger.debug(f"Error getting copy trading markets (table might not exist): {e}")
            return set()

    async def _fetch_markets_by_ids(self, market_ids: List[str]) -> List[Dict]:
        """Fetch fresh market data for given IDs"""
        updated_markets = []

        # Fetch markets individually (API doesn't support bulk by ID)
        for market_id in market_ids:
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
            await asyncio.sleep(0.05)  # 50ms delay

        logger.debug(f"Fetched {len(updated_markets)} markets by ID")
        return updated_markets
