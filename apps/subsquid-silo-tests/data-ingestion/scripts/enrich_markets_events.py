#!/usr/bin/env python3
"""
Script: Enrich Markets with Events Data (Bulk)
Fetches events from Gamma API /events endpoint which includes all markets with their events.
Significantly more efficient than individual market calls.
Runs ONCE during initialization to backfill all markets with complete data.
"""

import asyncio
import sys
import httpx
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid
from src.db.client import get_db_client, close_db_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MarketEnricher:
    """Enriches markets with complete data from Gamma API /events endpoint"""

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.enriched_count = 0
        self.failed_count = 0
        self.events_fetched = 0

    async def start(self):
        """Start enrichment process"""
        self.client = httpx.AsyncClient(timeout=30.0)
        try:
            await self.enrich_all_markets()
        finally:
            await self.stop()

    async def stop(self):
        """Stop enrichment service"""
        if self.client:
            await self.client.aclose()
        logger.info("✅ Enricher stopped")

    async def enrich_all_markets(self):
        """Fetch events from /events endpoint and enrich markets with events data"""
        db = await get_db_client()

        try:
            logger.info("📊 Starting market enrichment from Gamma API /events endpoint...")

            enriched_batch = []
            offset = 0
            limit = 200

            while True:
                # Fetch events (which includes all markets)
                events = await self._fetch_events(offset, limit)

                if not events:
                    break

                self.events_fetched += len(events)
                logger.info(f"📋 Fetched {len(events)} events (offset={offset})")

                # Extract markets from events with their event data
                for event in events:
                    markets = event.get("markets", [])

                    for market in markets:
                        # Build market enriched data
                        enriched = self._enrich_market_from_event(market, event)
                        enriched_batch.append(enriched)
                        self.enriched_count += 1

                        # Batch upsert every 500 markets
                        if len(enriched_batch) >= 500:
                            await db.upsert_markets_poll(enriched_batch)
                            logger.info(f"✅ Upserted {len(enriched_batch)} markets to DB")
                            enriched_batch = []

                # Check if we got less than limit (end of pagination)
                if len(events) < limit:
                    break

                offset += limit

            # Final batch
            if enriched_batch:
                await db.upsert_markets_poll(enriched_batch)
                logger.info(f"✅ Upserted final {len(enriched_batch)} markets to DB")

            # Summary
            logger.info("\n" + "=" * 80)
            logger.info(f"✅ ENRICHMENT COMPLETE")
            logger.info(f"   Events Fetched:  {self.events_fetched}")
            logger.info(f"   Markets Enriched: {self.enriched_count}")
            logger.info(f"   Failed:          {self.failed_count}")
            logger.info("=" * 80 + "\n")

        except Exception as e:
            logger.error(f"❌ Enrichment error: {e}", exc_info=True)
        finally:
            await close_db_client()

    async def _fetch_events(self, offset: int, limit: int) -> List[Dict[str, Any]]:
        """Fetch events from Gamma API /events endpoint"""
        if not self.client:
            return []

        # Use /events endpoint which returns events with ALL their markets
        url = f"{settings.GAMMA_API_URL.replace('/markets', '')}/events?limit={limit}&offset={offset}&order=id&ascending=false"

        try:
            response = await self.client.get(url, timeout=30.0)
            if response.status_code == 200:
                events = response.json()
                # Handle both list and dict responses
                return events if isinstance(events, list) else events.get("data", [])
            else:
                logger.debug(f"⚠️ API returned {response.status_code} for events offset={offset}")
                self.failed_count += 1
        except asyncio.TimeoutError:
            logger.debug(f"⏱️ Timeout fetching events at offset={offset}")
            self.failed_count += 1
        except Exception as e:
            logger.debug(f"❌ Error fetching events: {e}")
            self.failed_count += 1

        return []

    @staticmethod
    def _enrich_market_from_event(market: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and enrich market data from event response"""
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
        except (json.JSONDecodeError, ValueError, IndexError) as e:
            logger.debug(f"⚠️ Error parsing outcomes: {e}")

        # Calculate mid price
        last_mid = None
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                last_mid = round(sum(outcome_prices) / len(outcome_prices), 4)
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
                    "event_volume": round(float(event.get("volume", 0)), 4) if event.get("volume") else 0.0,
                })
            except Exception as e:
                logger.debug(f"⚠️ Error building events array: {e}")

        # Determine status
        status = "CLOSED" if market.get("closed") else "ACTIVE"

        # Build enriched market data
        enriched = {
            "market_id": market.get("id"),
            "condition_id": market.get("conditionId", ""),
            "title": market.get("question", ""),
            "slug": market.get("slug", ""),
            "status": status,
            "category": market.get("category", ""),
            "description": market.get("description", ""),
            "outcomes": outcomes,
            "outcome_prices": outcome_prices,
            "last_mid": last_mid,
            "volume": round(float(market.get("volume", 0)), 4) if market.get("volume") else 0.0,
            "volume_24hr": round(float(market.get("volume24hr", 0)), 4) if market.get("volume24hr") else 0.0,
            "volume_1wk": round(float(market.get("volume1wk", 0)), 4) if market.get("volume1wk") else 0.0,
            "volume_1mo": round(float(market.get("volume1mo", 0)), 4) if market.get("volume1mo") else 0.0,
            "liquidity": round(float(market.get("liquidity", 0)), 4) if market.get("liquidity") else 0.0,
            "tradeable": market.get("active", False),
            "accepting_orders": market.get("acceptingOrders", False),
            "end_date": market.get("endDate"),
            "events": events,
            "updated_at": datetime.now(timezone.utc),
        }

        return enriched


async def main():
    """Main entry point"""
    try:
        print("\n" + "=" * 80)
        print("🚀 MARKET ENRICHMENT SERVICE (BULK)")
        print("Fetching full market details from Gamma API /events endpoint...")
        print("=" * 80 + "\n")

        # Validate feature flag
        validate_experimental_subsquid()

        # Start enricher
        enricher = MarketEnricher()
        await enricher.start()

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Interrupted")
        sys.exit(0)
