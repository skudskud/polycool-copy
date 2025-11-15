#!/usr/bin/env python3
"""
CLI Script: Read Polling Data
Displays markets fetched from Gamma API (polling), freshness metrics, and p95 latency.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone
import json

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid
from src.db.client import get_db_client, close_db_client


async def main():
    """Main entry point"""
    try:
        print("\n" + "=" * 80)
        print("📊 SUBSQUID POLLING DATA READER")
        print("=" * 80)

        # Validate feature flag
        validate_experimental_subsquid()
        print("✅ Feature flag validated\n")

        # Get database client
        db = await get_db_client()

        # Get freshness stats
        print("📈 Freshness Metrics:")
        print("-" * 80)
        stats = await db.calculate_freshness_poll()

        if stats:
            print(f"  Total Records:        {stats.get('total_records', 0):,}")
            print(f"  Latest Update:        {stats.get('latest_update', 'N/A')}")
            print(f"  Freshness (Overall):  {stats.get('freshness_seconds', 0):.2f}s")
            print(f"  Freshness (p95):      {stats.get('p95_freshness_seconds', 0):.2f}s")
        else:
            print("  ⚠️  No data available yet")

        # Get sample data
        print("\n📋 Recent Markets (Last 5):")
        print("-" * 80)
        markets = await db.get_markets_poll(limit=5)

        if markets:
            for i, market in enumerate(markets, 1):
                print(f"\n  [{i}] Market: {market['market_id'][:20]}...")
                print(f"      Title:  {market['title'][:50]}...")
                print(f"      Status: {market['status']}")
                print(f"      Mid:    {market.get('last_mid', 'N/A')}")
                print(f"      Updated: {market['updated_at']}")
        else:
            print("  ⚠️  No markets found in polling table")

        # Summary
        print("\n" + "=" * 80)
        print("✅ Read complete")
        print("=" * 80 + "\n")

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
