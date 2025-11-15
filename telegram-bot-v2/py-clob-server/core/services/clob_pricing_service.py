#!/usr/bin/env python3
"""
CLOB Pricing Service - Fresh API Calls for Market Details
Integrates with existing PriceCalculator and Redis cache architecture
Provides ultra-fresh prices (sub-second) for specific market interactions
"""

import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams
from py_clob_client.constants import POLYGON

from .redis_price_cache import get_redis_cache

logger = logging.getLogger(__name__)


class CLOBPricingService:
    """
    Service for fresh CLOB API pricing calls
    Integrated with existing Redis cache and PriceCalculator architecture

    Usage Pattern:
    - Navigation: Use poller prices (60s)
    - Market Details: Call get_fresh_market_prices() → cache 30s
    - Trading: Use WebSocket/PriceCalculator cascade
    """

    def __init__(self):
        """Initialize with read-only CLOB client"""
        self.client = ClobClient(host="https://clob.polymarket.com", chain_id=POLYGON)
        self.redis_cache = get_redis_cache()
        self.fresh_price_ttl = 30  # 30 seconds cache for fresh prices

        logger.info("✅ CLOB Pricing Service initialized (30s fresh price TTL)")

    async def get_fresh_market_prices(
        self,
        market_id: str,
        token_ids: List[str],
        force_refresh: bool = False
    ) -> Optional[Dict]:
        """
        Get ultra-fresh prices from CLOB API for market details view
        Called when user clicks on specific market for detailed view

        Args:
            market_id: Market identifier
            token_ids: List of token IDs [yes_token, no_token]
            force_refresh: Skip cache check

        Returns:
            Dict with fresh pricing data or None if failed
        """
        try:
            # Check cache first (unless forced refresh)
            if not force_refresh:
                cached_data = self._get_cached_fresh_prices(market_id)
                if cached_data:
                    logger.debug(f"🚀 CLOB CACHE HIT: Market {market_id[:10]}...")
                    return cached_data

            # Cache miss - fetch fresh from API with distributed lock
            logger.info(f"🔄 CLOB FRESH FETCH: Market {market_id[:10]}... ({len(token_ids)} tokens)")

            # Acquire distributed lock to prevent race conditions and duplicate API calls
            lock_key = f"lock:clob_fresh:{market_id}"
            lock_acquired = self.redis_cache.acquire_lock(lock_key, ttl_seconds=15)

            if not lock_acquired:
                # Another instance is already fetching this data
                logger.debug(f"🔒 Lock held by another instance for market {market_id}, waiting briefly...")
                await asyncio.sleep(0.5)  # Brief wait

                # Check cache again after wait
                cached_data = self._get_cached_fresh_prices(market_id)
                if cached_data:
                    logger.debug(f"🚀 CLOB CACHE HIT after lock wait: Market {market_id[:10]}...")
                    return cached_data

                # Still no data, proceed (lock might have expired)
                logger.debug(f"⚠️ Proceeding with fetch despite lock for market {market_id}")

            try:
                # Get midpoints and spreads
                fresh_data = await self._fetch_fresh_pricing_data(token_ids)

                if fresh_data:
                    # Cache for 30 seconds
                    self._cache_fresh_prices(market_id, fresh_data)

                    logger.info(f"✅ CLOB FRESH SUCCESS: Market {market_id[:10]}... cached for 30s")
                    return fresh_data
                else:
                    logger.warning(f"⚠️ CLOB FRESH FAILED: Market {market_id[:10]}...")
                    return None

            except Exception as e:
                logger.error(f"❌ CLOB pricing fetch error for market {market_id}: {e}")
                return None

            finally:
                # Always release the lock if we acquired it
                if lock_acquired:
                    self.redis_cache.release_lock(lock_key)
                    logger.debug(f"🔓 Released lock for market {market_id}")

        except Exception as e:
            logger.error(f"❌ CLOB pricing error for market {market_id}: {e}")
            return None

    async def _fetch_fresh_pricing_data(self, token_ids: List[str]) -> Optional[Dict]:
        """
        Fetch fresh pricing data from CLOB API
        Includes midpoints, spreads, and individual prices
        """
        try:
            # Prepare batch parameters
            params = [BookParams(token_id=tid) for tid in token_ids]

            # Fetch midpoints (fastest)
            midpoints = await asyncio.get_event_loop().run_in_executor(
                None, self.client.get_midpoints, params
            )

            # Fetch individual prices for spread calculation
            buy_params = [BookParams(token_id=token_ids[0], side="BUY")]
            sell_params = [BookParams(token_id=token_ids[1], side="SELL")]

            buy_prices = await asyncio.get_event_loop().run_in_executor(
                None, self.client.get_prices, buy_params
            )

            sell_prices = await asyncio.get_event_loop().run_in_executor(
                None, self.client.get_prices, sell_params
            )

            # Process results
            if not midpoints or len(midpoints) < 2:
                return None

            # Extract prices
            yes_mid = float(midpoints[0].get('mid', 0))
            no_mid = float(midpoints[1].get('mid', 0))

            # Calculate spread from individual prices
            yes_buy = float(buy_prices[0].get('price', yes_mid)) if buy_prices else yes_mid
            no_sell = float(sell_prices[0].get('price', no_mid)) if sell_prices else no_mid

            spread = abs(yes_buy - no_sell)
            spread_pct = (spread / min(yes_buy, no_sell) * 100) if min(yes_buy, no_sell) > 0 else 0

            return {
                'midpoints': [yes_mid, no_mid],
                'spread': spread,
                'spread_pct': spread_pct,
                'individual_prices': {
                    'yes_buy': yes_buy,
                    'no_sell': no_sell
                },
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'source': 'clob_fresh'
            }

        except Exception as e:
            logger.error(f"❌ CLOB API fetch error: {e}")
            return None

    def _get_cached_fresh_prices(self, market_id: str) -> Optional[Dict]:
        """Get cached fresh prices from Redis"""
        if not self.redis_cache.enabled:
            return None

        try:
            key = f"clob_fresh:{market_id}"
            cached = self.redis_cache.redis_client.get(key)

            if cached:
                import json
                data = json.loads(cached)

                # Check if still fresh (< 30s old)
                fetched_at = datetime.fromisoformat(data['fetched_at'])
                age = (datetime.now(timezone.utc) - fetched_at).total_seconds()

                if age < self.fresh_price_ttl:
                    return data
                else:
                    # Stale - delete
                    self.redis_cache.redis_client.delete(key)
                    return None

            return None

        except Exception as e:
            logger.debug(f"Cache read error: {e}")
            return None

    def _cache_fresh_prices(self, market_id: str, data: Dict) -> bool:
        """Cache fresh prices in Redis for 30 seconds"""
        if not self.redis_cache.enabled:
            return False

        try:
            key = f"clob_fresh:{market_id}"
            import json
            self.redis_cache.redis_client.setex(key, self.fresh_price_ttl, json.dumps(data))
            return True

        except Exception as e:
            logger.debug(f"Cache write error: {e}")
            return False

    def invalidate_fresh_cache(self, market_id: str) -> bool:
        """Invalidate fresh price cache for a market"""
        if not self.redis_cache.enabled:
            return False

        try:
            key = f"clob_fresh:{market_id}"
            return bool(self.redis_cache.redis_client.delete(key))
        except Exception as e:
            return False


# Singleton instance
_clob_pricing_instance = None

def get_clob_pricing_service() -> CLOBPricingService:
    """Get singleton CLOBPricingService instance"""
    global _clob_pricing_instance
    if _clob_pricing_instance is None:
        _clob_pricing_instance = CLOBPricingService()
    return _clob_pricing_instance
