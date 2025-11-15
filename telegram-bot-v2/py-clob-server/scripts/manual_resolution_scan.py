#!/usr/bin/env python3
"""
Manual Resolution Monitor Trigger
Run this to manually trigger a market resolution scan
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    print("🔍 MANUAL RESOLUTION SCAN")
    print("=" * 50)
    
    try:
        from core.services.market_resolution_monitor import get_resolution_monitor
        
        monitor = get_resolution_monitor()
        
        # Run scan with 7-day lookback (like initial scan)
        print("\n🔍 Starting scan with 7-day lookback...")
        stats = await monitor.scan_for_resolutions(lookback_minutes=10080)  # 7 days
        
        print("\n✅ SCAN COMPLETE!")
        print("=" * 50)
        print(f"📊 Results:")
        print(f"   Markets scanned: {stats['markets']}")
        print(f"   Positions created: {stats['positions']}")
        print(f"   Winners: {stats['winners']}")
        print(f"   Losers: {stats['losers']}")
        print("=" * 50)
        
        if stats['positions'] > 0:
            print("\n💰 Check your Telegram bot - resolved positions should appear!")
        else:
            print("\n⚠️ No resolved positions found")
            print("   This could mean:")
            print("   - No markets with positions have resolved")
            print("   - Markets are CLOSED but not yet resolved")
            print("   - No transactions found for resolved markets")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

