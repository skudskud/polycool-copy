#!/usr/bin/env python3
"""
Debug backfill - simple step by step
"""
import asyncio
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def debug_simple():
    try:
        print("🔍 Starting simple backfill debug...")

        from data_ingestion.poller.unified_backfill_poller import UnifiedBackfillPoller

        poller = UnifiedBackfillPoller()
        print("✅ Poller created")

        # Just try to fetch first batch of events
        print("📡 Testing first batch fetch...")
        batch = await poller._fetch_api("/events", params={
            'closed': False,
            'offset': 0,
            'limit': 10,  # Small batch
            'order': 'volume',
            'ascending': False
        })

        if batch:
            print(f"✅ First batch successful: {len(batch)} events")
            if len(batch) > 0:
                print(f"📊 First event ID: {batch[0].get('id')}")

                # Try to process just the first event
                print("📦 Testing event processing...")
                markets = await poller._process_event_batch_with_complete_metadata([batch[0]])
                print(f"✅ Event processing successful: {len(markets)} markets extracted")

                if len(markets) > 0:
                    market = markets[0]
                    print(f"📊 Market: {market.get('question', '')[:50]}...")
                    print(f"📊 outcomePrices: {market.get('outcomePrices')}")
                    print(f"📊 outcomes: {market.get('outcomes')}")

        else:
            print("❌ First batch failed")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_simple())
