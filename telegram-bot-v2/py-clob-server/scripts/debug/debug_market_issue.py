#!/usr/bin/env python3
"""
Debug script for market display issues
Identifies markets that appear in lists but don't exist in database
"""

import os
import sys
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def debug_market_issue():
    """Debug the specific market issue"""
    print("🔍 DEBUGGING MARKET DISPLAY ISSUE")
    print("=" * 50)

    try:
        from telegram_bot.services.market_service import MarketService
        from market_database import MarketDatabase

        market_service = MarketService()
        market_db = MarketDatabase()

        # Test the specific market ID from the URL
        market_id = "1760531286712"
        print(f"🎯 Testing market ID: {market_id}")

        # Check if market exists in database
        market = market_service.get_market_by_id(market_id)
        if market:
            print(f"✅ Market found in database:")
            print(f"   Question: {market.get('question')}")
            print(f"   Outcomes: {market.get('outcomes')}")
            print(f"   Active: {market.get('active')}")
            print(f"   Tradeable: {market.get('tradeable')}")
        else:
            print(f"❌ Market NOT found in database")

        # Check if market appears in any market lists
        print(f"\n🔍 Checking if market appears in market lists...")

        try:
            # Check high volume markets
            high_volume = market_db.get_high_volume_markets(limit=100)
            found_in_volume = any(str(m.get('id')) == market_id for m in high_volume)
            print(f"   High Volume List: {'✅ Found' if found_in_volume else '❌ Not found'}")

            # Check if it's a Greenland/Trump market
            greenland_markets = [m for m in high_volume if 'greenland' in m.get('question', '').lower()]
            print(f"   Greenland markets in high volume: {len(greenland_markets)}")
            for gm in greenland_markets:
                print(f"     - {gm.get('id')}: {gm.get('question')}")

        except Exception as e:
            print(f"   Error checking market lists: {e}")

        # Check cache for this market
        print(f"\n💾 Checking cache...")
        try:
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()

            if redis_cache.enabled:
                cached_market = redis_cache.get_market_data(market_id)
                if cached_market:
                    print(f"   Redis Cache: ✅ Found")
                    print(f"     Question: {cached_market.get('question')}")
                else:
                    print(f"   Redis Cache: ❌ Not found")
            else:
                print(f"   Redis Cache: ⚠️ Disabled")

        except Exception as e:
            print(f"   Error checking cache: {e}")

        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        if not market:
            print(f"   1. Market {market_id} doesn't exist in database")
            print(f"   2. This market should NOT appear in /markets list")
            print(f"   3. If it appears, there's a bug in market filtering")
            print(f"   4. User should see 'Market not found' message")
        else:
            print(f"   1. Market exists but may have invalid outcomes")
            print(f"   2. Check outcomes and outcome_prices fields")
            print(f"   3. Ensure market is active and tradeable")

    except Exception as e:
        print(f"❌ Error during debugging: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_market_issue()
