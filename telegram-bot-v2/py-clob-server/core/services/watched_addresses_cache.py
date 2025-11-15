"""
Watched Addresses Cache Manager
Maintains a Redis cache of all watched addresses for fast indexer access
"""

import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import redis.asyncio as redis

from config.config import REDIS_URL
from database import db_manager, ExternalLeader
from core.persistence.models import SmartWallet

logger = logging.getLogger(__name__)

class WatchedAddressesCacheManager:
    """Manages Redis cache of watched addresses"""

    CACHE_KEY = "watched_addresses:cache:v1"
    CACHE_TTL = 300  # 5 minutes (reduced from 10min for faster refresh)

    def __init__(self):
        self.redis_url = REDIS_URL

    async def refresh_cache(self) -> Dict[str, Any]:
        """
        Refresh the watched addresses cache from database
        Called by background job every 1 minute (synchronized with indexer)

        Returns:
            Cache data that was stored
        """
        try:
            start_time = datetime.now()

            # Fetch from database
            with db_manager.get_session() as db:
                # Get active external leaders
                leaders = db.query(ExternalLeader).filter(
                    ExternalLeader.is_active == True,
                    ExternalLeader.polygon_address.isnot(None)
                ).all()

                # Get all smart wallets
                smart_wallets = db.query(SmartWallet).filter(
                    SmartWallet.address.isnot(None)
                ).all()

                # Build address list
                addresses = []

                for leader in leaders:
                    addresses.append({
                        'address': leader.polygon_address.lower(),
                        'type': 'external_leader',
                        'user_id': leader.virtual_id
                    })

                for wallet in smart_wallets:
                    addresses.append({
                        'address': wallet.address.lower(),
                        'type': 'smart_wallet',
                        'user_id': None
                    })

            # Build cache data
            cache_data = {
                'addresses': addresses,
                'total': len(addresses),
                'breakdown': {
                    'external_leaders': len(leaders),
                    'smart_wallets': len(smart_wallets)
                },
                'cached_at': datetime.now(timezone.utc).isoformat(),
                'version': 1
            }

            # Store in Redis
            redis_client = await redis.from_url(self.redis_url, decode_responses=True)
            await redis_client.setex(
                self.CACHE_KEY,
                self.CACHE_TTL,
                json.dumps(cache_data)
            )
            await redis_client.close()

            elapsed = (datetime.now() - start_time).total_seconds()

            logger.info(
                f"✅ [WATCHED_CACHE] Refreshed cache: {len(addresses)} addresses "
                f"({len(leaders)} leaders, {len(smart_wallets)} smart wallets) "
                f"in {elapsed:.2f}s"
            )

            return cache_data

        except Exception as e:
            logger.error(f"❌ [WATCHED_CACHE] Failed to refresh cache: {e}", exc_info=True)
            raise

    async def get_cached_addresses(self) -> Optional[Dict[str, Any]]:
        """
        Get watched addresses from cache

        Returns:
            Cached data or None if cache miss
        """
        try:
            redis_client = await redis.from_url(self.redis_url, decode_responses=True)
            cached = await redis_client.get(self.CACHE_KEY)
            await redis_client.close()

            if cached:
                data = json.loads(cached)
                logger.debug(
                    f"[WATCHED_CACHE] Cache hit: {data['total']} addresses "
                    f"(cached {data['cached_at']})"
                )
                return data
            else:
                logger.warning("[WATCHED_CACHE] Cache miss")
                return None

        except Exception as e:
            logger.error(f"❌ [WATCHED_CACHE] Failed to read cache: {e}")
            return None

    async def invalidate_cache(self):
        """Manually invalidate the cache (useful when addresses are added/removed)"""
        try:
            redis_client = await redis.from_url(self.redis_url, decode_responses=True)
            await redis_client.delete(self.CACHE_KEY)
            await redis_client.close()
            logger.info("✅ [WATCHED_CACHE] Cache invalidated")
        except Exception as e:
            logger.error(f"❌ [WATCHED_CACHE] Failed to invalidate cache: {e}")

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring"""
        try:
            redis_client = await redis.from_url(self.redis_url, decode_responses=True)

            # Check if cache exists
            exists = await redis_client.exists(self.CACHE_KEY)

            # Get TTL
            ttl = await redis_client.ttl(self.CACHE_KEY) if exists else -1

            # Get cache data
            cached = await redis_client.get(self.CACHE_KEY) if exists else None

            await redis_client.close()

            if cached:
                data = json.loads(cached)
                return {
                    'cached': True,
                    'total_addresses': data['total'],
                    'breakdown': data['breakdown'],
                    'cached_at': data['cached_at'],
                    'ttl_seconds': ttl,
                    'expires_in': f"{ttl // 60}m {ttl % 60}s" if ttl > 0 else "expired"
                }
            else:
                return {
                    'cached': False,
                    'message': 'Cache not populated'
                }

        except Exception as e:
            logger.error(f"❌ [WATCHED_CACHE] Failed to get stats: {e}")
            return {'cached': False, 'error': str(e)}


# Global instance
watched_addresses_cache_manager = WatchedAddressesCacheManager()
