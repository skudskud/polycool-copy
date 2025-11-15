#!/usr/bin/env python3
"""
Fix incorrect position prices
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

async def fix_positions():
    """Fix incorrect position prices in database"""
    try:
        from core.database.connection import get_db
        from sqlalchemy import text

        async with get_db() as db:
            print("🔧 Fixing incorrect position prices...")

            # Update positions for Xi Jinping market (ID: 551963) with NO outcome
            # Correct price should be 0.9775, not 0.010224950224950225
            result = await db.execute(text('''
                UPDATE positions
                SET entry_price = 0.9775, current_price = 0.9775
                WHERE market_id = '551963'
                AND outcome = 'NO'
                AND entry_price < 0.1  -- Only fix the incorrect ones
            '''))

            await db.commit()

            print(f'✅ Updated {result.rowcount} positions with incorrect prices')

            # Verify the fix
            result = await db.execute(text('''
                SELECT id, outcome, entry_price, current_price
                FROM positions
                WHERE market_id = '551963'
                ORDER BY id
            '''))

            rows = result.fetchall()
            print(f'Positions for Xi Jinping market:')
            for row in rows:
                print(f'  ID {row[0]}: {row[1]} @ ${row[2]:.6f} (current: ${row[3]:.6f})')

    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(fix_positions())
