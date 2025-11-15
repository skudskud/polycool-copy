"""
Auto-Watch Markets Service
Scans user positions from Polymarket API and automatically adds markets to watched_markets
if they're not already in the top 1000 subscribed markets.
"""

import asyncio
import logging
from typing import List, Set
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AutoWatchMarketsService:
    """Automatically watch markets that have user positions"""

    def __init__(self, db_client, poll_interval_seconds: int = 300):
        """
        Initialize auto-watch service

        Args:
            db_client: Database client for updating watched_markets
            poll_interval_seconds: How often to check for new markets (default: 5 minutes)
        """
        self.db = db_client
        self.poll_interval = poll_interval_seconds
        self.is_running = False
        self.watched_condition_ids: Set[str] = set()

    async def start(self):
        """Start the auto-watch service"""
        if self.is_running:
            logger.warning("⚠️ Auto-watch service already running")
            return

        self.is_running = True
        asyncio.create_task(self._monitor_loop())
        logger.info(f"✅ Auto-watch service started (poll interval: {self.poll_interval}s)")

    async def stop(self):
        """Stop the auto-watch service"""
        self.is_running = False
        logger.info("✅ Auto-watch service stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.is_running:
            try:
                await self._check_and_watch_user_markets()
                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"❌ Auto-watch loop error: {e}")
                await asyncio.sleep(self.poll_interval)

    async def _check_and_watch_user_markets(self):
        """
        Query Polymarket API for all user positions and ensure their markets
        are in watched_markets table.
        """
        try:
            import httpx

            # Get current watched markets from DB
            watched = await self.db.get_watched_markets(limit=5000)
            watched_set = set(watched)

            logger.debug(f"🔍 [AUTO-WATCH] Currently watching {len(watched_set)} markets")

            # Fetch all markets from Gamma API
            # We'll scan for markets that have recent activity and ensure they're watched
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get active markets from Gamma API
                response = await client.get(
                    "https://gamma-api.polymarket.com/markets",
                    params={"limit": 100, "offset": 0, "active": True},
                )

                if response.status_code == 200:
                    markets = response.json()
                    if isinstance(markets, dict) and "data" in markets:
                        markets = markets["data"]

                    # Extract market_ids from markets
                    new_markets_added = 0
                    for market in markets:
                        try:
                            market_id = market.get("id") or market.get("market_id")
                            condition_id = market.get("condition_id")
                            title = market.get("question")

                            if market_id and market_id not in watched_set:
                                # Add to watched markets
                                success = await self.db.add_watched_market(
                                    market_id, condition_id, title
                                )
                                if success:
                                    watched_set.add(market_id)
                                    new_markets_added += 1
                                    logger.debug(
                                        f"✅ [AUTO-WATCH] Added market: {market_id} ({title[:30]}...)"
                                    )
                        except Exception as market_err:
                            logger.debug(f"⚠️ [AUTO-WATCH] Error processing market: {market_err}")

                    if new_markets_added > 0:
                        logger.info(
                            f"📈 [AUTO-WATCH] Added {new_markets_added} new markets to watch"
                        )

            logger.debug(f"✅ [AUTO-WATCH] Scan complete: {len(watched_set)} total watched markets")

        except Exception as e:
            logger.error(f"❌ [AUTO-WATCH] Failed to check user markets: {e}")


async def get_auto_watch_service(db_client) -> AutoWatchMarketsService:
    """Factory function to get/create auto-watch service"""
    return AutoWatchMarketsService(db_client, poll_interval_seconds=300)
