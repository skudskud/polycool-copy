#!/usr/bin/env python3
"""
Script to invalidate markets cache after deploying grouping logic fix.

Usage:
    python scripts/invalidate_markets_cache.py [--filter FILTER_NAME]

Examples:
    # Invalidate ALL market caches
    python scripts/invalidate_markets_cache.py

    # Invalidate specific filter
    python scripts/invalidate_markets_cache.py --filter volume_grouped
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.market_data_layer import get_market_data_layer
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description='Invalidate markets cache')
    parser.add_argument('--filter', type=str, help='Specific filter to invalidate (e.g., volume_grouped, liquidity_grouped)', default=None)
    args = parser.parse_args()

    logger.info("🔄 Starting cache invalidation...")
    
    try:
        market_layer = get_market_data_layer()
        
        if args.filter:
            logger.info(f"📦 Invalidating cache for filter: {args.filter}")
            market_layer.invalidate_markets_cache(filter_name=args.filter)
            logger.info(f"✅ Cache invalidated for filter: {args.filter}")
        else:
            logger.info("📦 Invalidating ALL market caches...")
            market_layer.invalidate_markets_cache(filter_name=None)
            logger.info("✅ ALL market caches invalidated")
        
        logger.info("🎉 Cache invalidation complete!")
        
    except Exception as e:
        logger.error(f"❌ Error during cache invalidation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
