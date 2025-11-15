#!/usr/bin/env python3
"""
Market Cache Preloader Service
Preloads popular market pages in background to ensure instant /markets responses
"""

import logging
from typing import List, Dict
from core.services.market_data_layer import get_market_data_layer
from core.services.redis_price_cache import get_redis_cache

logger = logging.getLogger(__name__)

class MarketCachePreloader:
    """
    Preloads popular market pages to ensure instant /markets responses
    Runs in background every 5 minutes to refresh cache
    """

    def __init__(self):
        self.market_layer = get_market_data_layer()
        self.redis_cache = get_redis_cache()

    def preload_popular_pages(self) -> Dict[str, int]:
        """
        Preload the most popular market pages (0-2 for each filter)
        This ensures instant responses for 90% of users

        Returns:
            Dict with preload statistics
        """
        stats = {
            "pages_preloaded": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0
        }

        # Popular pages to preload (pages 0-2 for each filter)
        popular_pages = [
            ("volume", 0),      # Most popular
            ("volume", 1),      # Second page
            ("volume", 2),      # Third page
            ("liquidity", 0),   # Liquidity filter
            ("liquidity", 1),   # Liquidity page 2
            ("new", 0),         # New markets
            ("ending_168h", 0), # Ending soon
        ]

        logger.info(f"🔄 Starting market cache preload for {len(popular_pages)} pages...")

        for filter_name, page in popular_pages:
            try:
                # Check if already cached
                cached = self.redis_cache.get_markets_page(filter_name, page)
                if cached is not None:
                    stats["cache_hits"] += 1
                    logger.debug(f"✅ Page {filter_name}:{page} already cached")
                    continue

                # Preload this page
                logger.debug(f"🔄 Preloading {filter_name} page {page}...")

                if filter_name == "volume":
                    markets, _ = self.market_layer.get_high_volume_markets_page(page=page, page_size=10)
                elif filter_name == "liquidity":
                    markets, _ = self.market_layer.get_high_liquidity_markets_page(page=page, page_size=10)
                elif filter_name == "new":
                    markets, _ = self.market_layer.get_new_markets_page(page=page, page_size=10)
                elif filter_name == "ending_168h":
                    markets, _ = self.market_layer.get_ending_soon_markets_page(hours=168, page=page, page_size=10)
                else:
                    continue

                if markets:
                    stats["pages_preloaded"] += 1
                    stats["cache_misses"] += 1
                    logger.debug(f"✅ Preloaded {len(markets)} markets for {filter_name}:{page}")
                else:
                    logger.warning(f"⚠️ No markets returned for {filter_name}:{page}")

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"❌ Error preloading {filter_name}:{page}: {e}")

        logger.info(f"📊 Preload complete: {stats['pages_preloaded']} pages, {stats['cache_hits']} hits, {stats['cache_misses']} misses, {stats['errors']} errors")
        return stats

    def warm_cache(self) -> Dict[str, int]:
        """
        Warm up cache by preloading essential pages
        Called on startup to ensure cache is ready
        """
        logger.info("🔥 Warming up market cache...")
        return self.preload_popular_pages()

# Global instance
_preloader_instance = None

def get_market_cache_preloader() -> MarketCachePreloader:
    """Get global market cache preloader instance"""
    global _preloader_instance
    if _preloader_instance is None:
        _preloader_instance = MarketCachePreloader()
    return _preloader_instance
