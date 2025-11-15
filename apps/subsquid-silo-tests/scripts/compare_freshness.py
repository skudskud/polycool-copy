#!/usr/bin/env python3
"""
CLI Script: Compare Freshness
Compares freshness metrics between polling (Gamma API) and streaming (CLOB WS) data sources.
Displays p95 latency, trends, and performance comparison.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid
from src.db.client import get_db_client, close_db_client


async def main():
    """Main entry point"""
    try:
        print("\n" + "=" * 100)
        print("📊 FRESHNESS COMPARISON: POLLING vs STREAMING")
        print("=" * 100)

        # Validate feature flag
        validate_experimental_subsquid()
        print("✅ Feature flag validated\n")

        # Get database client
        db = await get_db_client()

        # Fetch freshness metrics
        print("🔄 Fetching metrics...\n")

        poll_stats = await db.calculate_freshness_poll()
        ws_stats = await db.calculate_freshness_ws()

        # Display comparison table
        print("=" * 100)
        print(f"{'Metric':<30} {'Polling (Gamma)':<30} {'Streaming (WS)':<30}")
        print("=" * 100)

        # Total records
        poll_records = poll_stats.get('total_records', 0) if poll_stats else 0
        ws_records = ws_stats.get('total_records', 0) if ws_stats else 0
        print(f"{'Total Records':<30} {poll_records:<30,} {ws_records:<30,}")

        # Latest update
        poll_latest = str(poll_stats.get('latest_update', 'N/A'))[:25] if poll_stats else 'N/A'
        ws_latest = str(ws_stats.get('latest_update', 'N/A'))[:25] if ws_stats else 'N/A'
        print(f"{'Latest Update':<30} {poll_latest:<30} {ws_latest:<30}")

        # Overall freshness
        poll_fresh = poll_stats.get('freshness_seconds', 0) if poll_stats else 0
        ws_fresh = ws_stats.get('freshness_seconds', 0) if ws_stats else 0
        print(f"{'Freshness (s)':<30} {poll_fresh:<30.2f} {ws_fresh:<30.2f}")

        # P95 Freshness
        poll_p95 = poll_stats.get('p95_freshness_seconds', 0) if poll_stats else 0
        ws_p95 = ws_stats.get('p95_freshness_seconds', 0) if ws_stats else 0
        print(f"{'Freshness p95 (s)':<30} {poll_p95:<30.2f} {ws_p95:<30.2f}")

        print("=" * 100)

        # Performance analysis
        print("\n🎯 Performance Analysis:")
        print("-" * 100)

        # Determine which is fresher
        fresher_source = "Streaming (WS)" if ws_p95 < poll_p95 else "Polling (Gamma)"
        freshness_delta = abs(ws_p95 - poll_p95)

        print(f"  Fresher Source:         {fresher_source}")
        print(f"  Freshness Delta (p95):  {freshness_delta:.2f}s")

        # Polling analysis
        if poll_stats:
            print(f"\n  📈 Polling (Gamma API):")
            print(f"    • Records:      {poll_records:,}")
            print(f"    • Freshness:    {poll_fresh:.2f}s (overall)")
            print(f"    • Freshness p95: {poll_p95:.2f}s (95th percentile)")
            print(f"    • Interval:     Every {settings.POLL_MS / 1000:.0f}s")
            print(f"    • Expected:     Should be close to {settings.POLL_MS / 1000:.0f}s")
        else:
            print(f"\n  📈 Polling (Gamma API): ⚠️  No data")

        # Streaming analysis
        if ws_stats:
            print(f"\n  🌊 Streaming (CLOB WS):")
            print(f"    • Records:      {ws_records:,}")
            print(f"    • Freshness:    {ws_fresh:.2f}s (overall)")
            print(f"    • Freshness p95: {ws_p95:.2f}s (95th percentile)")
            print(f"    • Expected:     <1s (real-time)")
            print(f"    • Status:       {'✅ GOOD' if ws_p95 < 5 else '⚠️  SLOW'}")
        else:
            print(f"\n  🌊 Streaming (CLOB WS): ⚠️  No data")

        # Recommendations
        print("\n💡 Recommendations:")
        print("-" * 100)

        if not poll_stats or poll_records == 0:
            print("  ⚠️  Polling service: No data. Check poller is running.")
        elif poll_p95 > settings.POLL_MS / 1000 * 1.5:
            print(f"  ⚠️  Polling latency high: {poll_p95:.2f}s vs expected {settings.POLL_MS / 1000:.0f}s")
        else:
            print(f"  ✅ Polling: Healthy (p95={poll_p95:.2f}s)")

        if not ws_stats or ws_records == 0:
            print("  ⚠️  Streaming service: No data. Check streamer is running.")
        elif ws_p95 > 10:
            print(f"  ⚠️  Streaming latency high: {ws_p95:.2f}s (expected <5s)")
        else:
            print(f"  ✅ Streaming: Healthy (p95={ws_p95:.2f}s)")

        # Summary
        print("\n" + "=" * 100)
        print("✅ Comparison complete")
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
