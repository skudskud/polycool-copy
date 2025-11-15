#!/usr/bin/env python3
"""
Debug pagination issue
"""
import asyncio
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def debug_pagination():
    try:
        print("🔍 Testing pagination...")

        from data_ingestion.poller.unified_backfill_poller import UnifiedBackfillPoller

        poller = UnifiedBackfillPoller()
        print("✅ Poller created")

        # Test multiple batches
        for batch_num in range(5):  # Test first 5 batches
            offset = batch_num * 200
            print(f"📡 Testing batch {batch_num + 1} (offset: {offset})...")

            batch = await poller._fetch_api("/events", params={
                'closed': False,
                'offset': offset,
                'limit': 200,
                'order': 'volume',
                'ascending': False
            })

            if batch is None:
                print(f"❌ Batch {batch_num + 1} returned None")
                break
            elif not isinstance(batch, list):
                print(f"❌ Batch {batch_num + 1} returned non-list: {type(batch)}")
                break
            elif len(batch) == 0:
                print(f"📡 Batch {batch_num + 1} returned empty list - end reached")
                break
            else:
                print(f"✅ Batch {batch_num + 1} successful: {len(batch)} events")

                # If we got fewer than 200, we've reached the end
                if len(batch) < 200:
                    print(f"📡 End of data reached at batch {batch_num + 1}")
                    break

            # Rate limiting
            await asyncio.sleep(1.0)

        print("🎉 Pagination test completed successfully!")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_pagination())
