#!/usr/bin/env python3
"""
Flush stale market cache from Redis

This script clears all cached market pages to force fresh data from the database.
Use this when:
- Markets display is showing empty results
- After migration or major data updates
- When cache versioning changes

Usage:
    python scripts/flush_market_cache.py
"""
import sys
import os

# Add parent directory to path to import project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.redis_price_cache import get_redis_cache
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Flush all market list caches from Redis"""
    logger.info("🔄 Starting market cache flush...")

    redis_cache = get_redis_cache()

    if not redis_cache.enabled:
        logger.error("❌ Redis not enabled - cannot flush cache")
        logger.error("Check REDIS_URL environment variable")
        return 1

    logger.info(f"✅ Connected to Redis: {redis_cache.redis_client.connection_pool.connection_kwargs.get('host', 'unknown')}")

    # Flush all market list caches (passing None flushes everything)
    success = redis_cache.invalidate_markets_cache(filter_name=None)

    if success:
        logger.info("✅ Successfully flushed all market caches")
        logger.info("ℹ️  Next /markets request will fetch fresh data from database")
        return 0
    else:
        logger.error("❌ Failed to flush market caches")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
