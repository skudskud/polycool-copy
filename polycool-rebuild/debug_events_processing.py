#!/usr/bin/env python3
"""
Debug events processing issue
"""
import asyncio
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def debug_events_processing():
    try:
        print("🔍 Testing events processing...")

        from data_ingestion.poller.unified_backfill_poller import UnifiedBackfillPoller

        poller = UnifiedBackfillPoller()
        print("✅ Poller created")

        # Fetch just first 5 events
        print("📡 Fetching first 5 events...")
        events_batch = await poller._fetch_api("/events", params={
            'closed': False,
            'offset': 0,
            'limit': 5,
            'order': 'volume',
            'ascending': False
        })

        if not events_batch or len(events_batch) == 0:
            print("❌ No events fetched")
            return

        print(f"✅ Fetched {len(events_batch)} events")

        # Process them one by one
        all_markets = []
        for i, event in enumerate(events_batch):
            print(f"📦 Processing event {i+1}/{len(events_batch)}: ID {event.get('id')}")

            try:
                markets = await poller._process_event_batch_with_complete_metadata([event])
                print(f"✅ Event {event.get('id')} processed: {len(markets)} markets")

                if len(markets) > 0:
                    market = markets[0]
                    print(f"  📊 Sample market: {market.get('question', '')[:50]}...")

                all_markets.extend(markets)

            except Exception as e:
                print(f"❌ Error processing event {event.get('id')}: {e}")
                break

            # Small delay
            await asyncio.sleep(0.5)

        print(f"🎉 Processing test completed! Total markets: {len(all_markets)}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_events_processing())
