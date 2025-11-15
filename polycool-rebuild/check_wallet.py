import asyncio
import os
from core.database.connection import get_db
from core.database.models import User
from sqlalchemy import select

async def get_wallet():
    async with get_db() as db:
        result = await db.execute(
            select(User).where(User.telegram_user_id == 6500527972)
        )
        user = result.scalar_one_or_none()
        
        if user:
            print(f"User ID: {user.id}")
            print(f"Telegram ID: {user.telegram_user_id}")
            print(f"Polygon Address: {user.polygon_address}")
            print(f"Solana Address: {user.solana_address}")
        else:
            print("User not found")

if __name__ == "__main__":
    asyncio.run(get_wallet())
