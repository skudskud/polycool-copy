import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.db.client import get_db_client, close_db_client

async def check_ws_data():
    print('\n🔍 Checking WebSocket data in subsquid_markets_ws table...\n')

    db = await get_db_client()

    # Check total count using raw query
    if db.pool:
        async with db.pool.acquire() as conn:
            count_result = await conn.fetchval('SELECT COUNT(*) FROM subsquid_markets_ws')
            total_count = count_result or 0
    else:
        total_count = 0

    print('📊 Total records in subsquid_markets_ws: {:,}'.format(total_count))

    if total_count > 0:
        # Get latest records
        latest = await db.get_markets_ws(limit=10)
        print('\n📈 Latest 10 WebSocket price updates:')
        print('-' * 60)

        for market in latest:
            market_id = market.get('market_id', 'N/A')[:20] + '...'
            last_mid = market.get('last_mid', 0)
            updated_at = market.get('updated_at', 'N/A')
            print('  {}: ${:.4f} (updated: {})'.format(market_id, last_mid, updated_at))

        # Check freshness
        freshness = await db.calculate_freshness_ws()
        if freshness:
            print('\n⏱️  Data freshness:')
            print('   Overall: {:.1f}s ago'.format(freshness.get('freshness_seconds', 0)))
            print('   P95: {:.1f}s ago'.format(freshness.get('p95_freshness_seconds', 0)))

    await close_db_client()

if __name__ == '__main__':
    asyncio.run(check_ws_data())
