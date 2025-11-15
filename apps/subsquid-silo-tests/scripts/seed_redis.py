#!/usr/bin/env python3
"""
CLI Script: Seed Redis with Test Data
Populates Redis channels with mock data for testing the bridge and webhook.
"""

import asyncio
import sys
import json
from pathlib import Path
import redis.asyncio as redis

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, validate_experimental_subsquid


async def seed_redis():
    """Seed Redis with test data"""
    try:
        print("\n" + "=" * 80)
        print("🌱 SEED REDIS WITH TEST DATA")
        print("=" * 80)

        # Validate feature flag
        validate_experimental_subsquid()
        print("✅ Feature flag validated\n")

        # Connect to Redis
        redis_client = await redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
        )

        print("✅ Connected to Redis\n")

        # Define test data
        test_markets = [
            "0x1234567890abcdef1234567890abcdef12345678",
            "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
            "0xfedcfedcfedcfedcfedcfedcfedcfedcfedcfedc",
        ]

        # Seed market.status.* channels
        print("📌 Seeding market.status.* channels:")
        print("-" * 80)
        for market_id in test_markets:
            channel = f"market.status.{market_id}"
            payload = {
                "market_id": market_id,
                "status": "active",
                "timestamp": "2025-11-21T12:00:00Z",
            }
            await redis_client.publish(channel, json.dumps(payload))
            print(f"  ✅ Published to {channel[:40]}...")

        # Seed clob.trade.* channels
        print("\n📌 Seeding clob.trade.* channels:")
        print("-" * 80)
        for market_id in test_markets:
            channel = f"clob.trade.{market_id}"
            payload = {
                "market_id": market_id,
                "price": 0.5432,
                "quantity": 100,
                "timestamp": "2025-11-21T12:00:00Z",
            }
            await redis_client.publish(channel, json.dumps(payload))
            print(f"  ✅ Published to {channel[:40]}...")

        # Seed clob.orderbook.* channels
        print("\n📌 Seeding clob.orderbook.* channels:")
        print("-" * 80)
        for market_id in test_markets:
            channel = f"clob.orderbook.{market_id}"
            payload = {
                "market_id": market_id,
                "bids": [[0.54, 1000], [0.53, 500]],
                "asks": [[0.55, 1000], [0.56, 500]],
                "timestamp": "2025-11-21T12:00:00Z",
            }
            await redis_client.publish(channel, json.dumps(payload))
            print(f"  ✅ Published to {channel[:40]}...")

        # Display Redis keys
        print("\n📊 Redis Keys Status:")
        print("-" * 80)
        info = await redis_client.info()
        print(f"  Keys Total:     {info.get('db0', {}).get('keys', 'N/A')}")
        print(f"  Memory Used:    {info.get('used_memory_human', 'N/A')}")
        print(f"  Connected Clients: {info.get('connected_clients', 'N/A')}")

        # Cleanup
        await redis_client.close()

        print("\n" + "=" * 80)
        print("✅ Seeding complete")
        print("=" * 80 + "\n")

        print("💡 Next Steps:")
        print("  1. Start the Redis bridge: python -m src.redis.bridge")
        print("  2. Start the webhook worker: python -m src.wh.webhook_worker")
        print("  3. Check webhook events: python scripts/read_wh.py")
        print("")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(seed_redis())
    except KeyboardInterrupt:
        print("\n👋 Interrupted")
        sys.exit(0)
