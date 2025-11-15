"""
Centralized cache management system
Single source of truth for all caching operations
"""
import json
from typing import Any, Optional, Union
from datetime import datetime, timedelta

import redis

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class CacheManager:
    """
    Centralized Redis cache manager with TTL strategy and metrics
    """

    # TTL Strategy (seconds)
    TTL_STRATEGY = {
        'prices': settings.redis.ttl_prices,           # Ultra-court (20s)
        'positions': settings.redis.ttl_positions,     # Court (3min)
        'markets_list': settings.redis.ttl_markets,    # Moyen (5min)
        'market_detail': settings.redis.ttl_markets,   # Moyen (5min)
        'user_profile': settings.redis.ttl_user_data,  # Long (1h)
        'smart_trades': settings.redis.ttl_markets,    # Moyen (5min)
        'leaderboard': settings.redis.ttl_user_data,   # Long (1h)
    }

    def __init__(self):
        """Initialize Redis connection"""
        self.redis = redis.Redis.from_url(settings.redis.url, decode_responses=True)
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'invalidations': 0,
        }

    async def get(self, key: str, data_type: str = 'default') -> Optional[Any]:
        """
        Get value from cache with automatic metrics

        Args:
            key: Cache key
            data_type: Type for TTL strategy ('prices', 'positions', etc.)

        Returns:
            Cached value or None if miss
        """
        try:
            value = self.redis.get(key)
            if value is None:
                self.stats['misses'] += 1
                logger.debug(f"Cache miss: {key}")
                return None

            self.stats['hits'] += 1
            logger.debug(f"Cache hit: {key}")

            # Parse JSON if needed
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value

        except Exception as e:
            logger.warning(f"Cache get error for key {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        data_type: str = 'default',
        ttl: Optional[int] = None
    ) -> bool:
        """
        Set value in cache with automatic TTL

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            data_type: Type for TTL strategy
            ttl: Custom TTL in seconds (overrides data_type)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Determine TTL
            if ttl is None:
                ttl = self.TTL_STRATEGY.get(data_type, 300)  # Default 5 minutes

            # Serialize value
            if isinstance(value, (dict, list)):
                serialized_value = json.dumps(value)
            else:
                serialized_value = str(value)

            # Set in Redis
            result = self.redis.setex(key, ttl, serialized_value)
            if result:
                self.stats['sets'] += 1
                logger.debug(f"Cache set: {key} (TTL: {ttl}s)")
                return True

            return False

        except Exception as e:
            logger.warning(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete key from cache

        Args:
            key: Cache key to delete

        Returns:
            True if key was deleted, False otherwise
        """
        try:
            result = self.redis.delete(key)
            if result > 0:
                self.stats['invalidations'] += 1
                logger.debug(f"Cache delete: {key}")
                return True
            return False

        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern

        Args:
            pattern: Redis pattern (e.g., "market:*")

        Returns:
            Number of keys invalidated
        """
        try:
            keys = self.redis.keys(pattern)
            if keys:
                result = self.redis.delete(*keys)
                self.stats['invalidations'] += result
                logger.info(f"Cache pattern invalidate: {pattern} ({result} keys)")
                return result
            return 0

        except Exception as e:
            logger.warning(f"Cache pattern invalidate error for {pattern}: {e}")
            return 0

    async def get_or_set(
        self,
        key: str,
        fetch_func,
        data_type: str = 'default',
        ttl: Optional[int] = None
    ) -> Any:
        """
        Get from cache or set if missing

        Args:
            key: Cache key
            fetch_func: Function to fetch data if cache miss
            data_type: Type for TTL strategy
            ttl: Custom TTL

        Returns:
            Cached or freshly fetched data
        """
        # Try cache first
        cached_data = await self.get(key, data_type)
        if cached_data is not None:
            return cached_data

        # Cache miss - fetch fresh data
        try:
            fresh_data = await fetch_func()
            await self.set(key, fresh_data, data_type, ttl)
            return fresh_data

        except Exception as e:
            logger.error(f"Error fetching fresh data for key {key}: {e}")
            return None

    def get_stats(self) -> dict:
        """Get cache statistics"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0

        return {
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'sets': self.stats['sets'],
            'invalidations': self.stats['invalidations'],
            'hit_rate': round(hit_rate, 2),
            'total_requests': total_requests,
        }

    async def health_check(self) -> bool:
        """Check Redis connectivity"""
        try:
            return self.redis.ping()
        except Exception:
            return False

    async def clear_all(self) -> bool:
        """Clear all cache data (dangerous!)"""
        try:
            result = self.redis.flushdb()
            logger.warning("Cache cleared completely!")
            return result
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False

    async def get_set(self, key: str) -> set:
        """
        Get all members of a Redis set

        Args:
            key: Redis set key

        Returns:
            Set of members (empty set if key doesn't exist)
        """
        try:
            members = self.redis.smembers(key)
            return set(members) if members else set()
        except Exception as e:
            logger.warning(f"Cache get_set error for key {key}: {e}")
            return set()

    async def add_to_set(
        self,
        key: str,
        members: Union[str, list, set],
        ttl: Optional[int] = None
    ) -> int:
        """
        Add members to a Redis set

        Args:
            key: Redis set key
            members: Single member (str) or list/set of members
            ttl: Time to live in seconds (optional)

        Returns:
            Number of new members added
        """
        try:
            if isinstance(members, str):
                members = [members]
            elif isinstance(members, set):
                members = list(members)

            if not members:
                return 0

            # Add members to set
            result = self.redis.sadd(key, *members)

            # Set TTL if provided
            if ttl is not None:
                self.redis.expire(key, ttl)

            logger.debug(f"Cache add_to_set: {key} ({result} new members, TTL: {ttl}s)")
            return result

        except Exception as e:
            logger.warning(f"Cache add_to_set error for key {key}: {e}")
            return 0

    async def is_member(self, key: str, member: str) -> bool:
        """
        Check if member exists in Redis set

        Args:
            key: Redis set key
            member: Member to check

        Returns:
            True if member exists, False otherwise
        """
        try:
            return bool(self.redis.sismember(key, member))
        except Exception as e:
            logger.warning(f"Cache is_member error for key {key}: {e}")
            return False
