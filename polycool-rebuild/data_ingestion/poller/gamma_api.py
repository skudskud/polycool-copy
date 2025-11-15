"""
Gamma API Poller - Events Poller
Fetches markets via /events endpoint (top 500 events by volume)
"""

import asyncio
import traceback
from time import time
from datetime import datetime, timezone
from typing import List, Dict, Optional
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller

logger = get_logger(__name__)


class GammaAPIPollerEvents(BaseGammaAPIPoller):
    """
    Poll Gamma API /events endpoint
    - Fetches top 500 events by volume (30s interval)
    - Extracts markets from events (preserves event->markets relationships)
    - Covers ~99% of markets via events
    """

    def __init__(self, interval: int = 30):
        super().__init__(poll_interval=interval)

    async def _poll_cycle(self) -> None:
        """Single poll cycle - fetch events and extract markets"""
        start_time = time()

        try:
            # 1. Fetch top 500 events by volume
            events = await self._fetch_events_batch()

            if not events:
                logger.warning("No events fetched")
                return

            # 2. Extract markets from events
            markets = await self._extract_markets_from_events(events)

            if not markets:
                logger.warning("No markets extracted from events")
                return

            # 3. Upsert to unified markets table
            upserted = await self._upsert_markets(markets)

            # 4. Update stats
            self.poll_count += 1
            self.market_count += len(markets)
            self.upsert_count += upserted
            self.last_poll_time = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            duration = time() - start_time
            logger.info(f"✅ Events poll cycle completed in {duration:.2f}s - {len(events)} events, {len(markets)} markets, {upserted} upserted")

        except Exception as e:
            logger.error(f"Events poll cycle error: {e}")
            raise

    async def _fetch_events_batch(self) -> List[Dict]:
        """
        Fetch top 1000 events from Gamma API /events endpoint
        Strategy: Featured events (priority) + top volume events
        """
        events = []

        # Layer 1: Featured events (priority maximum)
        try:
            featured = await self._fetch_api("/events", params={
                'featured': True,
                'limit': 100,
                'closed': False
            })
            if featured and isinstance(featured, list):
                events.extend(featured)
                logger.info(f"📦 Fetched {len(featured)} featured events")
        except Exception as e:
            logger.warning(f"Failed to fetch featured events: {e}")

        # Layer 2: Top volume events (fill remaining to 1000)
        remaining = 1000 - len(events)
        if remaining > 0:
            offset = 0
            limit = 100  # Events API limit

            while len(events) < 1000:
                batch = await self._fetch_api("/events", params={
                    'offset': offset,
                    'limit': limit,
                    'closed': False,
                    'order': 'volume',
                    'ascending': False
                })

                if not batch or not isinstance(batch, list):
                    break

                if not batch:
                    break

                # Filter out already fetched featured events
                existing_ids = {str(e.get('id')) for e in events}
                new_batch = [e for e in batch if str(e.get('id')) not in existing_ids]
                events.extend(new_batch)

                # If less than limit, we've reached the end
                if len(batch) < limit:
                    break

                offset += limit

                # Stop at max_events
                if len(events) >= 1000:
                    events = events[:1000]
                    break

        logger.info(f"📦 Fetched {len(events)} total events ({len([e for e in events if e.get('featured')])} featured)")
        return events

    async def _extract_markets_from_events(self, events: List[Dict]) -> List[Dict]:
        """
        Extract markets from events and CREATE event parent markets
        Preserves event->markets relationships by creating parent markets
        CRITICAL: Fetches full event data to get proper endDate/startDate
        """
        all_markets = []

        for event in events:
            event_id = str(event.get('id', ''))
            event_slug = event.get('slug', '')
            event_title = event.get('title', '')
            event_category = event.get('category', '')
            event_tags = event.get('tags', [])
            event_volume = event.get('volume', 0)
            event_liquidity = event.get('liquidity', 0)

            # 🔥 CRITICAL: Fetch full event data to get endDate/startDate
            # The /events list doesn't include dates, but /events/{id} does
            full_event = None
            if event_id:
                try:
                    full_event = await self._fetch_api(f"/events/{event_id}")
                except Exception as e:
                    logger.warning(f"Failed to fetch full event {event_id}: {e}")

            # Get dates from full event data
            event_end_date = None
            event_start_date = None
            if full_event:
                event_end_date = full_event.get('endDate') or full_event.get('endsAt')
                event_start_date = full_event.get('startDate') or full_event.get('startsAt')

            # 🔥 CREATE EVENT PARENT MARKET
            event_market = {
                'id': event_id,
                'question': event_title,
                'description': full_event.get('description', '') if full_event else '',
                'category': event_category or 'Events',
                'outcomes': ['Various'],  # Events don't have simple yes/no outcomes
                'outcomePrices': [0.5],  # Placeholder price
                'events': [],  # No parent events for root events
                'volume': event_volume,
                'liquidity': event_liquidity,
                'lastTradePrice': None,
                'clobTokenIds': None,
                'conditionId': None,
                'startDate': event_start_date,
                'endDate': event_end_date,
                'event_id': event_id,  # Self-reference for event markets
                'event_slug': event_slug,
                'event_title': event_title,
                'is_event_parent': True  # Mark as parent event
            }
            all_markets.append(event_market)
            logger.debug(f"📁 Created parent event market: {event_title} ({event_id})")

            # Extract markets from this event
            markets_in_event = event.get('markets', [])

            for market in markets_in_event:
                # Add event metadata to each market (only if not already set)
                if not market.get('event_id'):
                    market['event_id'] = event_id
                if not market.get('event_slug'):
                    market['event_slug'] = event_slug
                if not market.get('event_title'):
                    market['event_title'] = event_title

                # Add dates from event if market doesn't have them
                if not market.get('endDate') and event_end_date:
                    market['endDate'] = event_end_date
                    logger.debug(f"Market {market.get('id')}: set endDate from event: {event_end_date}")
                if not market.get('startDate') and event_start_date:
                    market['startDate'] = event_start_date
                    logger.debug(f"Market {market.get('id')}: set startDate from event: {event_start_date}")

                # Add category from event if not present
                if not market.get('category') and event_category:
                    market['category'] = event_category

                # Add event tags for enrichment
                market['event_tags'] = event_tags

                # Mark as child market
                market['is_event_parent'] = False

                all_markets.append(market)

        logger.info(f"📦 Created {len([m for m in all_markets if m.get('is_event_parent')])} parent events and {len([m for m in all_markets if not m.get('is_event_parent')])} child markets from {len(events)} events")
        return all_markets


# Keep GammaAPIPollerCorrected as alias for backward compatibility
GammaAPIPollerCorrected = GammaAPIPollerEvents


async def main():
    """Main function to run the poller"""
    logger.info("🚀 Starting Gamma API Poller (Events Version)")

    poller = GammaAPIPollerEvents(interval=30)

    try:
        await poller.start_polling()

    except KeyboardInterrupt:
        logger.info("🛑 Poller stopped by user")
    except Exception as e:
        logger.error(f"❌ Poller crashed: {e}")
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    asyncio.run(main())
