import asyncio
import os
from core.database.connection import get_db
from core.database.models import Position
from sqlalchemy import select
from datetime import datetime, timezone

async def fix_positions_real():
    # Données réelles depuis l'API Polymarket
    real_size = 6.134964
    real_avg_price = 0.977999
    
    print(f"🔧 Correction avec les VRAIES données de l'API Polymarket:")
    print(f"  Size: {real_size}")
    print(f"  Avg Price: ${real_avg_price:.6f}")
    print(f"  Market: Xi Jinping out in 2025?")
    print(f"  Outcome: No")
    print()
    
    # Distribuer équitablement sur les 3 positions (simulation de 3 trades séparés)
    size_per_position = real_size / 3  # ~2.044988
    price_per_position = real_avg_price  # même prix moyen
    
    async def update_position(position_id, amount, entry_price):
        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.id == position_id)
            )
            position = result.scalar_one_or_none()
            
            if position:
                position.amount = amount
                position.entry_price = entry_price
                position.current_price = entry_price  # Pour commencer
                position.updated_at = datetime.now(timezone.utc)
                await db.commit()
                print(f"✅ Position {position_id} corrigée: amount={amount:.6f}, entry_price=${entry_price:.6f}")
            else:
                print(f"❌ Position {position_id} non trouvée")

    # Corriger chaque position avec la portion équitable
    await update_position(1, size_per_position, price_per_position)
    await update_position(2, size_per_position, price_per_position) 
    await update_position(3, size_per_position, price_per_position)

if __name__ == "__main__":
    asyncio.run(fix_positions_real())
