#!/usr/bin/env python3
"""
Test script to populate markets from Gamma API
Run this to test Phase 2: Markets population
"""

import sys
import os
import logging

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

def main():
    """Test market population from Gamma API"""
    logger.info("🚀 Starting market population test...")
    logger.info("=" * 60)
    
    try:
        # Import market fetcher service
        from market_fetcher_service import market_fetcher
        
        # Test 1: Fetch first 50 markets (for speed)
        logger.info("\n📊 Test 1: Fetching 50 markets from Gamma API...")
        stats = market_fetcher.fetch_and_populate_markets(limit=50)
        
        logger.info(f"\n✅ Fetch Results:")
        for key, value in stats.items():
            logger.info(f"   {key}: {value}")
        
        # Test 2: Get current stats
        logger.info("\n📊 Test 2: Getting market statistics...")
        db_stats = market_fetcher.get_market_stats()
        
        logger.info(f"\n📈 Database Stats:")
        for key, value in db_stats.items():
            logger.info(f"   {key}: {value}")
        
        # Test 3: Query some markets
        logger.info("\n📊 Test 3: Querying sample markets...")
        from database import db_manager, Market
        
        with db_manager.get_session() as db:
            # Get top 5 tradeable markets by volume
            top_markets = db.query(Market).filter(
                Market.tradeable == True
            ).order_by(Market.volume.desc()).limit(5).all()
            
            logger.info(f"\n🏆 Top 5 Tradeable Markets by Volume:")
            for market in top_markets:
                logger.info(f"   - {market.question[:60]}...")
                logger.info(f"     Volume: ${market.volume:,.2f} | Liquidity: ${market.liquidity:,.2f}")
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ ALL TESTS PASSED!")
        logger.info("=" * 60)
        
        return 0
        
    except Exception as e:
        logger.error(f"\n❌ Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())

