import asyncio
import os
from core.database.connection import get_db
from core.database.models import Position
from sqlalchemy import select

async def check_positions():
    async with get_db() as db:
        result = await db.execute(
            select(Position).where(Position.user_id == 1).where(Position.status == 'active')
        )
        positions = result.scalars().all()
        
        print(f'✅ FINAL CHECK - Positions après corrections:')
        total_value = 0
        for p in positions:
            value = p.amount * p.entry_price
            total_value += value
            print(f'  📊 Position {p.id}: {p.amount:.6f} tokens @ ${p.entry_price:.6f} = ${value:.6f}')
        
        print(f'  💰 Valeur totale: ${total_value:.6f}')
        print(f'  🎯 Boutons: Edit TP/SL + Sell (selon état TP/SL)')
        print(f'  🔄 Boutons globaux: Refresh, View All TP/SL, History, Markets')

asyncio.run(check_positions())
