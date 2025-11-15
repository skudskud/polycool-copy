#!/usr/bin/env python3
"""
Redis Price Cache Service
High-performance caching for token prices and user positions
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Import circuit breaker for graceful degradation
try:
    from .redis_circuit_breaker import get_circuit_breaker
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    logger.warning("⚠️ Circuit breaker not available - graceful degradation disabled")

# Redis import with graceful fallback
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("⚠️ Redis package not installed - caching disabled")


class RedisPriceCache:
    """
    Redis-based caching service for token prices and positions
    Provides 100x performance improvement with automatic TTL expiration
    """

    def __init__(self):
        """Initialize Redis connection from environment variable"""
        self.enabled = False
        self.redis_client = None
        self.stats = {'hits': 0, 'misses': 0, 'errors': 0}

        # Circuit breaker for graceful degradation
        self.circuit_breaker = get_circuit_breaker() if CIRCUIT_BREAKER_AVAILABLE else None

        if not REDIS_AVAILABLE:
            logger.warning("⚠️ Redis caching disabled - package not installed")
            return

        redis_url = os.getenv('REDIS_URL')

        if not redis_url:
            logger.warning("⚠️ REDIS_URL not set - caching disabled")
            return

        try:
            # Create Redis client with connection pool
            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,  # Auto-decode bytes to str
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=True,
                max_connections=20
            )

            # Test connection
            self.redis_client.ping()
            self.enabled = True

            logger.info(f"✅ Redis cache initialized and connected")

        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            logger.warning("⚠️ Continuing without Redis cache - will use API fallback")
            self.enabled = False

    def _should_attempt_redis(self) -> bool:
        """
        Check if Redis operations should be attempted based on circuit breaker state.

        Returns:
            True if Redis should be tried, False to use fallback immediately
        """
        if not self.enabled:
            return False

        if self.circuit_breaker:
            return self.circuit_breaker.should_attempt_redis()

        return True  # No circuit breaker = always attempt

    def _record_redis_success(self):
        """Record successful Redis operation for circuit breaker"""
        if self.circuit_breaker:
            self.circuit_breaker.record_success()

    def _record_redis_failure(self, error: Exception):
        """Record failed Redis operation for circuit breaker"""
        if self.circuit_breaker:
            self.circuit_breaker.record_failure(error)

    def get_fallback_reason(self) -> str:
        """Get reason why fallback is being used"""
        if not self.enabled:
            return "Redis disabled (connection failed)"
        elif self.circuit_breaker:
            return self.circuit_breaker.get_fallback_reason()
        else:
            return "Unknown"

    # ========================================
    # DISTRIBUTED LOCKS (REDLOCK ALGORITHM)
    # ========================================

    def acquire_lock(self, lock_key: str, ttl_seconds: int = 10) -> bool:
        """
        Acquire a distributed lock using Redis SET NX EX

        Args:
            lock_key: Unique lock identifier
            ttl_seconds: Lock TTL to prevent deadlocks

        Returns:
            True if lock acquired, False if already locked
        """
        if not self._should_attempt_redis():
            logger.debug(f"🚫 Circuit breaker: Skipping lock acquisition for {lock_key}")
            return False

        try:
            # Use SET NX EX for atomic lock acquisition
            lock_value = f"locked:{id(self)}:{time.time()}"
            acquired = self.redis_client.set(lock_key, lock_value, ex=ttl_seconds, nx=True)

            if acquired:
                logger.debug(f"🔒 Acquired lock: {lock_key}")
                return True
            else:
                logger.debug(f"🚫 Lock already held: {lock_key}")
                return False

        except Exception as e:
            logger.error(f"❌ Lock acquisition error for {lock_key}: {e}")
            self._record_redis_failure(e)
            return False

    def release_lock(self, lock_key: str, expected_value: str = None) -> bool:
        """
        Release a distributed lock safely

        Args:
            lock_key: Lock identifier
            expected_value: Expected lock value for safety

        Returns:
            True if lock released
        """
        if not self._should_attempt_redis():
            logger.debug(f"🚫 Circuit breaker: Skipping lock release for {lock_key}")
            return False

        try:
            # Use Lua script for atomic check-and-delete
            unlock_script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
            """

            if expected_value:
                # Safe unlock with value check
                result = self.redis_client.eval(unlock_script, 1, lock_key, expected_value)
            else:
                # Simple unlock (less safe)
                result = self.redis_client.delete(lock_key)

            if result:
                logger.debug(f"🔓 Released lock: {lock_key}")
                self._record_redis_success()
                return True
            else:
                logger.debug(f"🚫 Lock not released (expired or wrong value): {lock_key}")
                return False

        except Exception as e:
            logger.error(f"❌ Lock release error for {lock_key}: {e}")
            self._record_redis_failure(e)
            return False

    # ========================================
    # MEMORY MONITORING & HEALTH CHECKS
    # ========================================

    def get_memory_stats(self) -> Dict:
        """
        Get Redis memory usage statistics and health metrics.

        Returns:
            Dict with memory stats, alerts, and recommendations
        """
        if not self.enabled:
            return {"status": "disabled", "reason": "Redis not connected"}

        try:
            info = self.redis_client.info('memory')
            stats = self.redis_client.info('stats')

            # Calculate memory metrics
            used_memory = info.get('used_memory', 0)
            max_memory = info.get('maxmemory', 0) or (512 * 1024 * 1024)  # Default 512MB
            memory_usage_pct = (used_memory / max_memory) * 100 if max_memory > 0 else 0

            # Key count (our cache keys)
            cache_keys = 0
            try:
                # Count keys matching our patterns
                price_keys = self.redis_client.keys("price:*")
                clob_keys = self.redis_client.keys("clob_fresh*")
                cache_keys = len(price_keys) + len(clob_keys)
            except:
                pass

            # Generate alerts
            alerts = []
            recommendations = []

            if memory_usage_pct > 90:
                alerts.append("🚨 CRITICAL: Redis memory >90%")
                recommendations.append("Increase Redis maxmemory or reduce TTL")
            elif memory_usage_pct > 80:
                alerts.append("⚠️ WARNING: Redis memory >80%")
                recommendations.append("Monitor memory growth closely")
            elif memory_usage_pct > 70:
                alerts.append("ℹ️ INFO: Redis memory >70%")
                recommendations.append("Consider optimizing cache TTL")

            # Key count alerts
            if cache_keys > 10000:
                alerts.append(f"⚠️ High key count: {cache_keys} keys")
                recommendations.append("Consider LRU eviction or shorter TTL")

            # Hit rate alerts
            if self.stats['hits'] + self.stats['misses'] > 100:
                hit_rate = (self.stats['hits'] / (self.stats['hits'] + self.stats['misses'])) * 100
                if hit_rate < 50:
                    alerts.append(f"⚠️ Low cache hit rate: {hit_rate:.1f}%")
                    recommendations.append("Review cache TTL and invalidation strategy")

            return {
                "status": "healthy" if not alerts else "warning",
                "memory": {
                    "used_bytes": used_memory,
                    "max_bytes": max_memory,
                    "usage_percent": round(memory_usage_pct, 1),
                    "human_used": self._format_bytes(used_memory),
                    "human_max": self._format_bytes(max_memory)
                },
                "cache": {
                    "keys_count": cache_keys,
                    "hits": self.stats['hits'],
                    "misses": self.stats['misses'],
                    "errors": self.stats['errors'],
                    "hit_rate_percent": round(hit_rate, 1) if 'hit_rate' in locals() else 0
                },
                "alerts": alerts,
                "recommendations": recommendations,
                "circuit_breaker": self.circuit_breaker.get_health_status() if self.circuit_breaker else None
            }

        except Exception as e:
            logger.error(f"❌ Memory stats error: {e}")
            return {"status": "error", "error": str(e)}

    def _format_bytes(self, bytes_count: int) -> str:
        """Format bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_count < 1024:
                return f"{bytes_count:.1f}{unit}"
            bytes_count /= 1024
        return f"{bytes_count:.1f}TB"

    def log_memory_alerts(self):
        """Log current memory alerts if any"""
        stats = self.get_memory_stats()
        alerts = stats.get('alerts', [])

        for alert in alerts:
            logger.warning(alert)

        if stats.get('recommendations'):
            for rec in stats['recommendations']:
                logger.info(f"💡 {rec}")

    # ========================================
    # TOKEN PRICE CACHING
    # ========================================

    def cache_token_price(self, token_id: str, price: float, ttl: int = 180) -> bool:
        """
        Cache a single token price with circuit breaker protection

        Args:
            token_id: ERC-1155 token ID
            price: Current price in USD
            ttl: Time to live in seconds (default: 180)

        Returns:
            True if cached successfully
        """
        if not self._should_attempt_redis():
            logger.debug(f"🚫 Circuit breaker: Skipping Redis cache for {token_id[:10]}... ({self.get_fallback_reason()})")
            return False

        try:
            key = f"price:{token_id}"
            self.redis_client.setex(key, ttl, str(price))
            logger.debug(f"💾 Cached price for token {token_id[:10]}...: ${price:.4f} (TTL: {ttl}s)")

            # Record success for circuit breaker
            self._record_redis_success()
            return True

        except Exception as e:
            logger.error(f"❌ Redis cache error for token {token_id[:10]}...: {e}")
            self.stats['errors'] += 1

            # Record failure for circuit breaker
            self._record_redis_failure(e)
            return False

    def get_token_price(self, token_id: str) -> Optional[float]:
        """
        Get cached token price with circuit breaker protection

        Args:
            token_id: ERC-1155 token ID

        Returns:
            Cached price or None if not found/expired or Redis unavailable
        """
        if not self._should_attempt_redis():
            logger.debug(f"🚫 Circuit breaker: Skipping Redis get for {token_id[:10]}... ({self.get_fallback_reason()})")
            if self.circuit_breaker:
                self.circuit_breaker.record_cache_miss()
            return None

        try:
            key = f"price:{token_id}"
            cached = self.redis_client.get(key)

            if cached is not None:
                self.stats['hits'] += 1
                if self.circuit_breaker:
                    self.circuit_breaker.record_cache_hit()
                price = float(cached)
                logger.debug(f"🚀 CACHE HIT: Token {token_id[:10]}... = ${price:.4f}")

                # Record success for circuit breaker
                self._record_redis_success()
                return price

            self.stats['misses'] += 1
            if self.circuit_breaker:
                self.circuit_breaker.record_cache_miss()
            logger.debug(f"💨 CACHE MISS: Token {token_id[:10]}...")
            return None

        except Exception as e:
            logger.error(f"❌ Redis get error for token {token_id[:10]}...: {e}")
            self.stats['errors'] += 1

            # Record failure for circuit breaker
            self._record_redis_failure(e)
            return None

    def get_token_price_with_stats(self, token_id: str) -> tuple[Optional[float], bool, int]:
        """
        Get cached token price with hit/miss status and TTL info

        Args:
            token_id: ERC-1155 token ID

        Returns:
            Tuple of (price, cache_hit, ttl_remaining)
        """
        if not self.enabled:
            return None, False, 0

        try:
            key = f"price:{token_id}"
            cached = self.redis_client.get(key)
            ttl = self.redis_client.ttl(key) if cached is not None else 0

            if cached is not None:
                self.stats['hits'] += 1
                price = float(cached)
                logger.debug(f"🚀 CACHE HIT: Token {token_id[:10]}... = ${price:.4f} (TTL: {ttl}s)")
                return price, True, ttl

            self.stats['misses'] += 1
            logger.debug(f"💨 CACHE MISS: Token {token_id[:10]}...")
            return None, False, 0

        except Exception as e:
            logger.error(f"❌ Redis get error for token {token_id[:10]}...: {e}")
            self.stats['errors'] += 1
            return None, False, 0

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics

        Returns:
            Dictionary with cache hit rate and stats
        """
        total = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0

        return {
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'errors': self.stats['errors'],
            'hit_rate': hit_rate,
            'total_requests': total
        }

    def cache_token_prices_batch(self, prices: Dict[str, float], ttl: int = 20) -> int:
        """
        Cache multiple token prices efficiently using pipeline

        Args:
            prices: Dictionary mapping token_id to price
            ttl: Time to live in seconds

        Returns:
            Number of prices successfully cached
        """
        if not self.enabled or not prices:
            return 0

        try:
            # Use pipeline for atomic batch operations
            pipe = self.redis_client.pipeline()

            for token_id, price in prices.items():
                if price is not None:
                    key = f"price:{token_id}"
                    pipe.setex(key, ttl, str(price))

            pipe.execute()

            logger.info(f"💾 Cached {len(prices)} token prices (TTL: {ttl}s)")
            return len(prices)

        except Exception as e:
            logger.error(f"❌ Redis batch cache error: {e}")
            self.stats['errors'] += 1
            return 0

    def get_token_prices_batch(self, token_ids: List[str]) -> Dict[str, Optional[float]]:
        """
        Get multiple token prices efficiently using pipeline

        Args:
            token_ids: List of token IDs

        Returns:
            Dictionary mapping token_id to price (None if not cached)
        """
        if not self.enabled or not token_ids:
            return {tid: None for tid in token_ids}

        try:
            # Use pipeline for batch get
            pipe = self.redis_client.pipeline()

            for token_id in token_ids:
                key = f"price:{token_id}"
                pipe.get(key)

            results = pipe.execute()

            # Build response dictionary
            prices = {}
            hits = 0
            misses = 0

            for i, token_id in enumerate(token_ids):
                cached = results[i]
                if cached is not None:
                    prices[token_id] = float(cached)
                    hits += 1
                else:
                    prices[token_id] = None
                    misses += 1

            self.stats['hits'] += hits
            self.stats['misses'] += misses

            logger.debug(f"🚀 BATCH GET: {hits} hits, {misses} misses out of {len(token_ids)} tokens")
            return prices

        except Exception as e:
            logger.error(f"❌ Redis batch get error: {e}")
            self.stats['errors'] += 1
            return {tid: None for tid in token_ids}

    # ========================================
    # POSITION CACHING
    # ========================================

    def cache_user_positions(self, wallet_address: str, positions: List, ttl: int = 30) -> bool:
        """
        Cache user positions from blockchain API

        Args:
            wallet_address: User's Polygon wallet address
            positions: List of position dictionaries
            ttl: Time to live in seconds (default: 30)

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            key = f"positions:{wallet_address.lower()}"
            positions_json = json.dumps(positions, default=str)
            self.redis_client.setex(key, ttl, positions_json)

            logger.debug(f"💾 Cached {len(positions)} positions for {wallet_address[:10]}... (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"❌ Redis position cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_user_positions(self, wallet_address: str) -> Optional[List]:
        """
        Get cached user positions

        Args:
            wallet_address: User's Polygon wallet address

        Returns:
            List of positions or None if not cached/expired
        """
        if not self.enabled:
            return None

        try:
            key = f"positions:{wallet_address.lower()}"
            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                positions = json.loads(cached)
                logger.info(f"🚀 CACHE HIT: Positions for {wallet_address[:10]}... ({len(positions)} positions)")
                return positions

            self.stats['misses'] += 1
            logger.info(f"💨 CACHE MISS: Positions for {wallet_address[:10]}...")
            return None

        except Exception as e:
            logger.error(f"❌ Redis position get error: {e}")
            self.stats['errors'] += 1
            return None

    def invalidate_user_positions(self, wallet_address: str) -> bool:
        """
        Invalidate cached positions (e.g., after trade execution)

        Args:
            wallet_address: User's Polygon wallet address

        Returns:
            True if invalidated successfully
        """
        if not self.enabled:
            return False

        try:
            key = f"positions:{wallet_address.lower()}"
            deleted = self.redis_client.delete(key)

            if deleted:
                logger.debug(f"🗑️ Invalidated positions cache for {wallet_address[:10]}...")

            return bool(deleted)

        except Exception as e:
            logger.error(f"❌ Redis invalidation error: {e}")
            self.stats['errors'] += 1
            return False

    def mark_recent_trade(self, wallet_address: str) -> bool:
        """
        Mark that a trade was recently executed for this wallet
        Flag expires automatically after 60 seconds (zero cleanup overhead)

        Args:
            wallet_address: User's Polygon wallet address

        Returns:
            True if marked successfully
        """
        if not self.enabled:
            return False

        try:
            key = f"recent_trade:{wallet_address.lower()}"
            self.redis_client.setex(key, 60, "1")  # 1 byte, auto-expire after 60s
            logger.debug(f"🔥 Marked recent trade for {wallet_address[:10]}... (TTL: 60s)")
            return True

        except Exception as e:
            logger.error(f"❌ Redis mark trade error: {e}")
            self.stats['errors'] += 1
            return False

    def has_recent_trade(self, wallet_address: str) -> bool:
        """
        Check if wallet has recent trade activity (last 60s)
        Used to apply shorter cache TTL for faster position updates

        Args:
            wallet_address: User's Polygon wallet address

        Returns:
            True if trade within last 60s
        """
        if not self.enabled:
            return False

        try:
            key = f"recent_trade:{wallet_address.lower()}"
            exists = self.redis_client.exists(key)
            return exists > 0

        except Exception as e:
            logger.error(f"❌ Redis check trade error: {e}")
            self.stats['errors'] += 1
            return False

    # ========================================
    # MARKET OUTCOME PRICE CACHING
    # ========================================

    def cache_market_outcome_price(
        self,
        market_id: str,
        outcome: str,
        price: float,
        ttl: int = 20
    ) -> bool:
        """
        Cache market outcome price (YES or NO)

        Args:
            market_id: Market identifier
            outcome: 'yes' or 'no'
            price: Current price
            ttl: Time to live in seconds

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            key = f"market_price:{market_id}:{outcome.lower()}"
            self.redis_client.setex(key, ttl, str(price))
            return True

        except Exception as e:
            logger.error(f"❌ Redis market price cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_market_outcome_price(self, market_id: str, outcome: str) -> Optional[float]:
        """
        Get cached market outcome price

        Args:
            market_id: Market identifier
            outcome: 'yes' or 'no'

        Returns:
            Cached price or None if not found
        """
        if not self.enabled:
            return None

        try:
            key = f"market_price:{market_id}:{outcome.lower()}"
            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                return float(cached)

            self.stats['misses'] += 1
            return None

        except Exception as e:
            logger.error(f"❌ Redis market price get error: {e}")
            self.stats['errors'] += 1
            return None

    # ========================================
    # MARKET SPREAD CACHING (NEW!)
    # ========================================

    def cache_market_spread(
        self,
        market_id: str,
        outcome: str,
        bid_price: float,
        ask_price: float,
        ttl: int = 20
    ) -> bool:
        """
        Cache market spread (bid-ask difference) for fast access
        Pre-calculated so selling doesn't require 2x API calls

        Args:
            market_id: Market identifier
            outcome: 'yes' or 'no'
            bid_price: Current BID (what buyers pay)
            ask_price: Current ASK (what sellers want)
            ttl: Time to live in seconds

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            # Calculate spread
            spread = ask_price - bid_price
            spread_pct = (spread / bid_price * 100) if bid_price > 0 else 0

            # Store as JSON with both prices and spread info
            spread_data = {
                'bid': bid_price,
                'ask': ask_price,
                'spread': spread,
                'spread_pct': spread_pct
            }

            key = f"market_spread:{market_id}:{outcome.lower()}"
            self.redis_client.setex(key, ttl, json.dumps(spread_data, default=str))

            logger.debug(f"💾 Cached spread for {market_id}:{outcome} - BID: ${bid_price:.4f}, ASK: ${ask_price:.4f}, Spread: {spread_pct:.2f}%")
            return True

        except Exception as e:
            logger.error(f"❌ Redis spread cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_market_spread(self, market_id: str, outcome: str) -> Optional[Dict]:
        """
        Get cached market spread (bid-ask with prices)

        Args:
            market_id: Market identifier
            outcome: 'yes' or 'no'

        Returns:
            Dict with 'bid', 'ask', 'spread', 'spread_pct' or None if not cached
        """
        if not self.enabled:
            return None

        try:
            key = f"market_spread:{market_id}:{outcome.lower()}"
            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                spread_data = json.loads(cached)
                logger.debug(f"🚀 CACHE HIT: Spread for {market_id}:{outcome} - BID: ${spread_data['bid']:.4f}, ASK: ${spread_data['ask']:.4f}")
                return spread_data

            self.stats['misses'] += 1
            return None

        except Exception as e:
            logger.error(f"❌ Redis spread get error: {e}")
            self.stats['errors'] += 1
            return None

    # ========================================
    # MARKET LIST CACHING
    # ========================================

    def cache_market_data(self, market_id: str, market_dict: Dict, ttl: int = 60) -> bool:
        """
        Cache complete market data (not just price)
        Used for pre-caching markets when displaying events

        Args:
            market_id: Market identifier
            market_dict: Complete market dictionary
            ttl: Time to live in seconds (default: 60)

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            key = f"market:v2:{market_id}"
            self.redis_client.setex(
                key,
                ttl,
                json.dumps(market_dict, default=str)  # default=str for datetime serialization
            )
            logger.debug(f"💾 Cached market {market_id[:10]}... (TTL: {ttl}s)")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to cache market {market_id[:10]}...: {e}")
            self.stats['errors'] += 1
            return False

    def get_market_data(self, market_id: str) -> Optional[Dict]:
        """
        Get cached market data

        Args:
            market_id: Market identifier

        Returns:
            Market dictionary or None if not cached
        """
        if not self.enabled:
            return None

        try:
            key = f"market:v2:{market_id}"
            data = self.redis_client.get(key)

            if data:
                self.stats['hits'] += 1
                return json.loads(data)

            self.stats['misses'] += 1
            return None
        except Exception as e:
            logger.error(f"❌ Failed to get cached market {market_id[:10]}...: {e}")
            self.stats['errors'] += 1
            return None

    def cache_market_list(self, filter_type: str, markets: List, ttl: int = 60) -> bool:
        """
        Cache filtered market list (for /markets command)

        Args:
            filter_type: 'volume', 'liquidity', 'newest', etc.
            markets: List of market dictionaries
            ttl: Time to live in seconds (default: 60)

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            key = f"market_list:{filter_type}"
            markets_json = json.dumps(markets, default=str)
            self.redis_client.setex(key, ttl, markets_json)

            logger.info(f"💾 Cached {len(markets)} markets for filter '{filter_type}' (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"❌ Redis market list cache error: {e}")
            self.stats['errors'] += 1
            return False

    def cache_market_ids_lightweight(self, filter_type: str, market_ids: List[str], ttl: int = 60) -> bool:
        """
        Cache lightweight market ID list (10x faster than full objects)

        Args:
            filter_type: 'volume', 'liquidity', 'newest', etc.
            market_ids: List of market IDs only
            ttl: Time to live in seconds (default: 60)

        Returns:
            True if cached successfully

        PERFORMANCE: JSON serialization of IDs is 10x faster than full market objects
        """
        if not self.enabled:
            return False

        try:
            key = f"market_ids:{filter_type}"
            ids_json = json.dumps(market_ids, default=str)
            self.redis_client.setex(key, ttl, ids_json)

            logger.info(f"💾 Cached {len(market_ids)} market IDs for filter '{filter_type}' (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"❌ Redis market IDs cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_market_list(self, filter_type: str) -> Optional[List]:
        """
        Get cached market list

        Args:
            filter_type: 'volume', 'liquidity', 'newest', etc.

        Returns:
            List of markets or None if not cached
        """
        if not self.enabled:
            return None

        try:
            key = f"market_list:{filter_type}"
            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                markets = json.loads(cached)
                logger.info(f"🚀 CACHE HIT: Market list '{filter_type}' ({len(markets)} markets)")
                return markets

            self.stats['misses'] += 1
            logger.info(f"💨 CACHE MISS: Market list '{filter_type}'")
            return None

        except Exception as e:
            logger.error(f"❌ Redis market list get error: {e}")
            self.stats['errors'] += 1
            return None

    def get_market_ids_lightweight(self, filter_type: str) -> Optional[List[str]]:
        """
        Get cached market IDs (lightweight, fast)

        Args:
            filter_type: 'volume', 'liquidity', 'newest', etc.

        Returns:
            List of market IDs or None if not cached

        PERFORMANCE: JSON deserialization of IDs is 10x faster than full objects
        """
        if not self.enabled:
            return None

        try:
            key = f"market_ids:{filter_type}"
            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                market_ids = json.loads(cached)
                logger.info(f"🚀 CACHE HIT: Market IDs '{filter_type}' ({len(market_ids)} IDs)")
                return market_ids

            self.stats['misses'] += 1
            logger.info(f"💨 CACHE MISS: Market IDs '{filter_type}'")
            return None

        except Exception as e:
            logger.error(f"❌ Redis market IDs get error: {e}")
            self.stats['errors'] += 1
            return None

    # ========================================
    # MARKET CACHING (NEW)
    # ========================================

    # Cache version for market lists - increment when query logic changes
    MARKET_CACHE_VERSION = "v1"

    def cache_markets_page(
        self,
        filter_name: str,
        page: int,
        markets: List[Dict],
        ttl: int = 600  # 10min for markets (OPTIMIZED)
    ) -> bool:
        """
        Cache a page of markets by filter

        Args:
            filter_name: e.g., 'volume', 'liquidity', 'ending_soon'
            page: Page number (0-indexed)
            markets: List of market dicts
            ttl: Time to live in seconds

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            # ✅ VERSIONED CACHE KEY: Auto-invalidates when logic changes
            key = f"markets:{self.MARKET_CACHE_VERSION}:{filter_name}:page:{page}"
            value = json.dumps(markets, default=str)
            self.redis_client.setex(key, ttl, value)
            logger.debug(f"📦 Cached {len(markets)} markets: {key} (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"❌ Redis market cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_markets_page(self, filter_name: str, page: int) -> Optional[List[Dict]]:
        """
        Get cached markets page

        Args:
            filter_name: e.g., 'volume', 'liquidity', 'ending_soon'
            page: Page number (0-indexed)

        Returns:
            List of markets or None if not cached
        """
        if not self.enabled:
            return None

        try:
            # ✅ VERSIONED CACHE KEY: Matches cache_markets_page()
            key = f"markets:{self.MARKET_CACHE_VERSION}:{filter_name}:page:{page}"
            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                logger.debug(f"✅ Cache HIT: {key}")
                return json.loads(cached)

            self.stats['misses'] += 1
            logger.debug(f"💨 Cache MISS: {key}")
            return None

        except Exception as e:
            logger.error(f"❌ Redis market get error: {e}")
            self.stats['errors'] += 1
            return None

    def invalidate_markets_cache(self, filter_name: Optional[str] = None) -> bool:
        """
        Invalidate markets cache by filter or all
        Useful when Poller/WebSocket updates data

        Args:
            filter_name: Specific filter to invalidate, or None for all

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        try:
            if filter_name:
                # Invalidate specific filter (all pages, current version)
                # ✅ VERSIONED PATTERN: Only invalidates current version
                pattern = f"markets:{self.MARKET_CACHE_VERSION}:{filter_name}:page:*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
                    logger.info(f"🗑️ Invalidated {len(keys)} pages for filter: {filter_name}")
            else:
                # Invalidate ALL markets cache (including ALL versions for full cleanup)
                # Note: This catches both versioned and unversioned keys
                pattern = "markets:*:page:*"
                keys = self.redis_client.keys(pattern)

                # Also invalidate category caches
                category_pattern = "markets:category_*:page:*"
                category_keys = self.redis_client.keys(category_pattern)

                # Also invalidate search cache (since market updates affect search results)
                search_pattern = "search:*"
                search_keys = self.redis_client.keys(search_pattern)

                all_keys = list(keys) + (list(category_keys) if category_keys else []) + (list(search_keys) if search_keys else [])

                if all_keys:
                    self.redis_client.delete(*all_keys)
                    logger.info(
                        f"🗑️ Invalidated ALL caches: "
                        f"{len(keys)} market pages + "
                        f"{len(category_keys) if category_keys else 0} category pages + "
                        f"{len(search_keys) if search_keys else 0} search queries"
                    )

            return True

        except Exception as e:
            logger.error(f"❌ Redis market invalidate error: {e}")
            self.stats['errors'] += 1
            return False

    def invalidate_search_cache(self, query: Optional[str] = None) -> bool:
        """
        Invalidate search results cache
        Useful when market data updates and search results need to be refreshed

        Args:
            query: Specific search query to invalidate, or None for all searches

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        try:
            if query:
                # Invalidate specific search query
                key = f"search:{query.lower()}"
                deleted = self.redis_client.delete(key)
                if deleted:
                    logger.info(f"🗑️ Invalidated search cache for query: '{query}'")
            else:
                # Invalidate ALL search cache
                pattern = "search:*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
                    logger.info(f"🗑️ Invalidated ALL search cache ({len(keys)} queries)")

            return True

        except Exception as e:
            logger.error(f"❌ Redis search invalidate error: {e}")
            self.stats['errors'] += 1
            return False

    def cache_market_metadata(self, market_id: str, metadata: Dict, ttl: int = 600) -> bool:
        """
        Cache individual market metadata for quick lookup

        Args:
            market_id: Market ID
            metadata: Market dict
            ttl: Time to live in seconds

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            key = f"market_meta:{market_id}"
            value = json.dumps(metadata, default=str)
            self.redis_client.setex(key, ttl, value)
            return True

        except Exception as e:
            logger.error(f"❌ Redis market metadata cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_market_metadata(self, market_id: str) -> Optional[Dict]:
        """
        Get cached market metadata

        Args:
            market_id: Market ID

        Returns:
            Market dict or None if not cached
        """
        if not self.enabled:
            return None

        try:
            key = f"market_meta:{market_id}"
            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                return json.loads(cached)

            self.stats['misses'] += 1
            return None

        except Exception as e:
            logger.error(f"❌ Redis market metadata get error: {e}")
            self.stats['errors'] += 1
            return None

    # ========================================
    # SEARCH CACHE (NEW!)
    # ========================================

    def cache_search_results(self, query: str, results: List[Dict], ttl: int = 300) -> bool:
        """
        Cache search results to eliminate 2-second SQL queries

        Args:
            query: Search query string (normalized)
            results: List of market dictionaries
            ttl: Time to live in seconds (default: 5min)

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            # Normalize query for consistent caching
            normalized_query = query.strip().lower()
            # ✅ FIX: Add version to cache key to bust old regex results
            # Increment SEARCH_CACHE_VERSION when search logic changes
            SEARCH_CACHE_VERSION = "v3"  # v3: Smart search (event titles + market titles + fuzzy)
            key = f"search:{SEARCH_CACHE_VERSION}:{normalized_query}"

            # Store with metadata for cache analytics
            cache_data = {
                'results': results,
                'count': len(results),
                'cached_at': datetime.now().isoformat(),
                'query': normalized_query,
                'version': SEARCH_CACHE_VERSION
            }

            self.redis_client.setex(key, ttl, json.dumps(cache_data, default=str))

            logger.debug(f"💾 Cached {len(results)} search results for '{normalized_query}' (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"❌ Redis search cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_search_results(self, query: str) -> Optional[List[Dict]]:
        """
        Get cached search results

        Args:
            query: Search query string

        Returns:
            List of market dictionaries or None if not cached
        """
        if not self.enabled:
            return None

        try:
            normalized_query = query.strip().lower()
            # ✅ FIX: Use same version key to match cache_search_results
            SEARCH_CACHE_VERSION = "v3"  # v3: Smart search (event titles + market titles + fuzzy)
            key = f"search:{SEARCH_CACHE_VERSION}:{normalized_query}"

            cached = self.redis_client.get(key)

            if cached:
                self.stats['hits'] += 1
                cache_data = json.loads(cached)
                results = cache_data['results']

                logger.debug(f"🚀 SEARCH CACHE HIT: '{normalized_query}' → {len(results)} results")
                return results

            self.stats['misses'] += 1
            logger.debug(f"💨 SEARCH CACHE MISS: '{normalized_query}'")
            return None

        except Exception as e:
            logger.error(f"❌ Redis search get error: {e}")
            self.stats['errors'] += 1
            return None

    # ========================================
    # MARKET IDS CACHING (OPT 3 - PERFORMANCE)
    # ========================================

    def cache_active_market_ids(self, market_ids: List[str], ttl: int = 300) -> bool:
        """
        Cache list of active market IDs (évite 1739 requêtes DB)

        Args:
            market_ids: List of active market IDs
            ttl: Time to live in seconds (default: 5min)

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        try:
            key = "market_ids:active"
            # Use Redis SET for O(1) membership testing
            pipe = self.redis_client.pipeline()
            pipe.delete(key)  # Clear old set
            if market_ids:
                pipe.sadd(key, *market_ids)
            pipe.expire(key, ttl)
            pipe.execute()

            logger.info(f"💾 Cached {len(market_ids)} active market IDs (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"❌ Redis market IDs cache error: {e}")
            self.stats['errors'] += 1
            return False

    def get_active_market_ids(self) -> Optional[set]:
        """
        Get cached active market IDs (O(1) membership testing)

        Returns:
            Set of market IDs or None if not cached
        """
        if not self.enabled:
            return None

        try:
            key = "market_ids:active"
            # Check if key exists
            if not self.redis_client.exists(key):
                self.stats['misses'] += 1
                logger.debug(f"💨 CACHE MISS: Active market IDs")
                return None

            # Get all members from SET
            market_ids = self.redis_client.smembers(key)

            if market_ids:
                self.stats['hits'] += 1
                logger.info(f"🚀 CACHE HIT: {len(market_ids)} active market IDs (instant lookup!)")
                return market_ids

            self.stats['misses'] += 1
            return None

        except Exception as e:
            logger.error(f"❌ Redis market IDs get error: {e}")
            self.stats['errors'] += 1
            return None

    def is_market_active(self, market_id: str) -> Optional[bool]:
        """
        Check if market_id exists in active markets (O(1) Redis SET check)

        Args:
            market_id: Market ID to check

        Returns:
            True if active, False if not, None if cache miss
        """
        if not self.enabled:
            return None

        try:
            key = "market_ids:active"
            if not self.redis_client.exists(key):
                self.stats['misses'] += 1
                return None

            exists = self.redis_client.sismember(key, market_id)
            self.stats['hits'] += 1
            return exists

        except Exception as e:
            logger.error(f"❌ Redis market check error: {e}")
            self.stats['errors'] += 1
            return None

    # ========================================
    # STATISTICS & MONITORING
    # ========================================

    def count_cached_markets(self) -> int:
        """
        Count how many markets are currently cached

        Returns:
            Number of cached markets
        """
        if not self.enabled:
            return 0

        try:
            # Count keys matching "market:*"
            keys = self.redis_client.keys("market:*")
            return len(keys)
        except Exception as e:
            logger.error(f"❌ Failed to count cached markets: {e}")
            return 0

    def get_cache_stats(self) -> Dict:
        """
        Get cache performance statistics

        Returns:
            Dictionary with hit rate, miss rate, error count, etc.
        """
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0

        stats = {
            'enabled': self.enabled,
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'errors': self.stats['errors'],
            'total_requests': total_requests,
            'hit_rate_percent': round(hit_rate, 2)
        }

        # Add circuit breaker stats if available
        if self.circuit_breaker:
            circuit_stats = self.circuit_breaker.get_health_status()
            stats['circuit_breaker'] = {
                'state': circuit_stats['state'],
                'failure_count': circuit_stats['failure_count'],
                'is_healthy': circuit_stats['is_healthy'],
                'cache_hits': circuit_stats['cache_hits'],
                'cache_misses': circuit_stats['cache_misses'],
                'circuit_hit_rate': circuit_stats['hit_rate'],
                'fallback_reason': self.get_fallback_reason()
            }

        # Add Redis server stats if available
        if self.enabled:
            try:
                info = self.redis_client.info('stats')
                stats['redis_server'] = {
                    'total_commands_processed': info.get('total_commands_processed'),
                    'instantaneous_ops_per_sec': info.get('instantaneous_ops_per_sec'),
                    'keyspace_hits': info.get('keyspace_hits'),
                    'keyspace_misses': info.get('keyspace_misses')
                }

                # Memory info
                memory_info = self.redis_client.info('memory')
                stats['memory'] = {
                    'used_memory_human': memory_info.get('used_memory_human'),
                    'maxmemory_human': memory_info.get('maxmemory_human')
                }

                # Count keys
                stats['total_keys'] = self.redis_client.dbsize()

            except Exception as e:
                logger.error(f"❌ Error getting Redis stats: {e}")

        return stats

    def clear_all(self) -> bool:
        """Clear all cached data (use with caution!)"""
        if not self.enabled:
            return False

        try:
            self.redis_client.flushdb()
            logger.warning("🗑️ Redis cache cleared completely")
            return True

        except Exception as e:
            logger.error(f"❌ Redis clear error: {e}")
            return False

    def health_check(self) -> bool:
        """Check if Redis connection is healthy"""
        if not self.enabled:
            return False

        try:
            return self.redis_client.ping()
        except:
            return False


# Singleton instance
_redis_cache_instance = None

def get_redis_cache() -> RedisPriceCache:
    """Get singleton RedisPriceCache instance"""
    global _redis_cache_instance
    if _redis_cache_instance is None:
        _redis_cache_instance = RedisPriceCache()
    return _redis_cache_instance
