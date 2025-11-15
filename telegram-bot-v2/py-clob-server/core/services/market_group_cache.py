"""
Market Group Cache Service
Stores market groups (event-based and slug-based) for fast retrieval
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MarketGroupCache:
    """
    In-memory cache for market groups to avoid recalculating slug patterns

    This cache stores:
    - event_id -> list of market IDs
    - slug_pattern event_ids -> list of market IDs

    TTL: 60 seconds (markets don't change that fast)
    """

    def __init__(self):
        self._cache = {}  # {event_id: {'market_ids': [...], 'expires_at': datetime}}
        self._enabled = True
        logger.info("✅ Market Group Cache initialized")

    def get(self, event_id: str) -> Optional[List[str]]:
        """
        Get market IDs for an event/group

        Args:
            event_id: Event ID (real or slug-based like 'slug_will-in-the-2025')

        Returns:
            List of market IDs or None if not cached/expired
        """
        if not self._enabled:
            return None

        if event_id not in self._cache:
            return None

        cached = self._cache[event_id]

        # Check expiration
        if datetime.utcnow() > cached['expires_at']:
            del self._cache[event_id]
            return None

        return cached['market_ids']

    def set(self, event_id: str, market_ids: List[str], ttl: int = 60):
        """
        Cache market IDs for an event/group

        Args:
            event_id: Event ID
            market_ids: List of market IDs in this group
            ttl: Time to live in seconds (default: 60)
        """
        if not self._enabled:
            return

        self._cache[event_id] = {
            'market_ids': market_ids,
            'expires_at': datetime.utcnow() + timedelta(seconds=ttl)
        }

        logger.debug(f"📦 Cached group {event_id} with {len(market_ids)} markets (TTL: {ttl}s)")

    def invalidate(self, event_id: str):
        """Invalidate a specific group"""
        if event_id in self._cache:
            del self._cache[event_id]
            logger.debug(f"🗑️ Invalidated cache for {event_id}")

    def clear(self):
        """Clear entire cache"""
        self._cache = {}
        logger.info("🗑️ Market group cache cleared")

    def get_stats(self) -> Dict:
        """Get cache statistics"""
        now = datetime.utcnow()
        active_entries = sum(1 for v in self._cache.values() if v['expires_at'] > now)

        return {
            'enabled': self._enabled,
            'total_entries': len(self._cache),
            'active_entries': active_entries,
            'expired_entries': len(self._cache) - active_entries
        }


# Global instance
_market_group_cache = None


def get_market_group_cache() -> MarketGroupCache:
    """Get the global market group cache instance"""
    global _market_group_cache
    if _market_group_cache is None:
        _market_group_cache = MarketGroupCache()
    return _market_group_cache
