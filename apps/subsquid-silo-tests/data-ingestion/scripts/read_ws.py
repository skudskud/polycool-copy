#!/usr/bin/env python3
"""
CLI Script: Read WebSocket Streaming Data
Displays markets from CLOB WebSocket, real-time pricing, and freshness metrics.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid
from src.db.client import get_db_client, close_db_client


async def main():
    """Main entry point"""
    try:
        print("\n" + "=" * 100)
        print("🌊 SUBSQUID WEBSOCKET STREAMING DATA READER")
        print("=" * 100)

        # Validate feature flag
        validate_experimental_subsquid()
        print("✅ Feature flag validated\n")

        # Get database client
        db = await get_db_client()

        # Get freshness stats
        print("📈 Freshness Metrics (WebSocket):")
        print("-" * 100)
        stats = await db.calculate_freshness_ws()

        if stats:
            print(f"  Total Records:        {stats.get('total_records', 0):,}")
            print(f"  Latest Update:        {stats.get('latest_update', 'N/A')}")
            print(f"  Freshness (Overall):  {stats.get('freshness_seconds', 0):.2f}s")
            print(f"  Freshness (p95):      {stats.get('p95_freshness_seconds', 0):.2f}s")
        else:
            print("  ⚠️  No data available yet")

        # Get sample data with pricing
        print("\n💰 Recent Markets (Last 10) - Real-Time Pricing:")
        print("-" * 100)
        markets = await db.get_markets_ws(limit=10)

        if markets:
            print(f"{'#':<3} {'Market ID':<15} {'Bid':<8} {'Ask':<8} {'Mid':<8} {'Trade':<8} {'Updated':<25}")
            print("-" * 100)

            for i, market in enumerate(markets, 1):
                bid = f"{market.get('last_bb', 0):.4f}" if market.get('last_bb') else "N/A"
                ask = f"{market.get('last_ba', 0):.4f}" if market.get('last_ba') else "N/A"
                mid = f"{market.get('last_mid', 0):.4f}" if market.get('last_mid') else "N/A"
                trade = f"{market.get('last_trade_price', 0):.4f}" if market.get('last_trade_price') else "N/A"

                market_id = market['market_id'][:13] + ".." if len(market['market_id']) > 13 else market['market_id']

                print(f"{i:<3} {market_id:<15} {bid:<8} {ask:<8} {mid:<8} {trade:<8} {str(market['updated_at']):<25}")
        else:
            print("  ⚠️  No markets found in WebSocket table")

        # Spread analysis
        print("\n📊 Spread Analysis (Last 5):")
        print("-" * 100)
        if markets and len(markets) >= 5:
            spreads = []
            for market in markets[:5]:
                bid = market.get('last_bb')
                ask = market.get('last_ba')
                if bid and ask:
                    spread = ((ask - bid) / bid * 100) if bid != 0 else 0
                    spreads.append({
                        'market_id': market['market_id'][:20],
                        'spread_bps': spread * 100,  # In basis points
                    })

            for i, data in enumerate(spreads, 1):
                print(f"  [{i}] {data['market_id']}...")
                print(f"      Spread: {data['spread_bps']:.2f} bps")

        # Summary
        print("\n" + "=" * 100)
        print("✅ Read complete")
        print("=" * 100 + "\n")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        await close_db_client()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Interrupted")
        sys.exit(0)
