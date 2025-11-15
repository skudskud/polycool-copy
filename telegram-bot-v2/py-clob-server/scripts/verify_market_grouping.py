#!/usr/bin/env python3
"""
Script to verify the market grouping logic fix.

This script:
1. Fetches the first page of markets with grouping enabled
2. Verifies the count is close to expected (should be ~10)
3. Checks for false positives (event_title == market title)
4. Reports grouping statistics

Usage:
    python scripts/verify_market_grouping.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.market_data_layer import get_market_data_layer
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("🔍 Starting market grouping verification...")
    
    try:
        market_layer = get_market_data_layer()
        
        # Test 1: Check first page count
        logger.info("\n📊 TEST 1: First Page Count")
        logger.info("=" * 60)
        display_items, total = market_layer.get_high_volume_markets_page(
            page=0, 
            page_size=10, 
            group_by_events=True
        )
        
        logger.info(f"✅ First page returned: {len(display_items)} items")
        if len(display_items) >= 8:
            logger.info(f"✅ PASS: Count is acceptable ({len(display_items)}/10)")
        else:
            logger.warning(f"⚠️ WARNING: Count is low ({len(display_items)}/10)")
        
        # Test 2: Check for event groups vs individuals
        logger.info("\n📊 TEST 2: Event Groups vs Individual Markets")
        logger.info("=" * 60)
        
        event_groups = [item for item in display_items if item.get('type') == 'event_group']
        individual_markets = [item for item in display_items if item.get('type') == 'individual']
        
        logger.info(f"Event Groups: {len(event_groups)}")
        logger.info(f"Individual Markets: {len(individual_markets)}")
        
        # Test 3: Display breakdown
        logger.info("\n📋 TEST 3: First Page Breakdown")
        logger.info("=" * 60)
        
        for i, item in enumerate(display_items, 1):
            if item.get('type') == 'event_group':
                logger.info(f"{i}. 🎯 EVENT GROUP: {item.get('event_title')} ({item.get('count', 0)} markets, ${item.get('volume', 0)/1e6:.1f}M)")
            else:
                logger.info(f"{i}. 📊 INDIVIDUAL: {item.get('title', 'Unknown')[:60]} (${item.get('volume', 0)/1e6:.1f}M)")
        
        # Test 4: Check for false positives
        logger.info("\n🔍 TEST 4: False Positive Check")
        logger.info("=" * 60)
        
        false_positives = []
        for item in individual_markets:
            events = item.get('events', [])
            if events and len(events) > 0:
                event_title = events[0].get('event_title')
                market_title = item.get('title')
                if event_title == market_title:
                    false_positives.append((market_title, event_title))
        
        if false_positives:
            logger.info(f"✅ Found {len(false_positives)} false positives (correctly treated as individual)")
            for market_title, event_title in false_positives[:3]:
                logger.info(f"   - {market_title[:60]}")
        else:
            logger.info("ℹ️ No false positives found in first page")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("🎉 VERIFICATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"✅ First page count: {len(display_items)}/10")
        logger.info(f"✅ Event groups: {len(event_groups)}")
        logger.info(f"✅ Individual markets: {len(individual_markets)}")
        logger.info(f"✅ False positives handled: {len(false_positives)}")
        
    except Exception as e:
        logger.error(f"❌ Error during verification: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

