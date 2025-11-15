"""
Trade Handler - Handle trade updates from WebSocket
Updates last trade price and volume
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import Market
from core.services.cache_manager import CacheManager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

cache_manager = CacheManager()


class TradeHandler:
    """
    Handle trade updates from WebSocket
    Updates last trade price and volume
    """

    @staticmethod
    async def update_market_trade(
        market_id: Optional[str],
        token_id: Optional[str],
        trade_price: float,
        trade_size: Optional[float]
    ) -> None:
        """
        Update market trade data in database

        Args:
            market_id: Market ID (optional)
            token_id: Token ID (optional)
            trade_price: Trade price
            trade_size: Trade size (optional)
        """
        try:
            async with get_db() as db:
                # Find market
                if market_id:
                    query = select(Market).where(Market.id == market_id)
                elif token_id:
                    query = select(Market).where(
                        Market.clob_token_ids.contains([token_id])
                    )
                else:
                    return

                result = await db.execute(query)
                market = result.scalar_one_or_none()

                if not market:
                    return

                # Update last trade price
                update_data = {
                    "source": "ws",
                    "last_trade_price": float(trade_price),
                    "updated_at": datetime.now(timezone.utc)
                }

                # Update volume if trade size provided
                if trade_size and market.volume:
                    update_data["volume"] = (market.volume or 0.0) + float(trade_size)

                await db.execute(
                    update(Market)
                    .where(Market.id == market.id)
                    .values(**update_data)
                )

                await db.commit()

                # Invalidate cache
                if market_id:
                    await cache_manager.delete(f"price:{market_id}")
                    await cache_manager.delete(f"market:{market_id}")
                    await cache_manager.delete(f"market_detail:{market_id}")

        except Exception as e:
            logger.error(f"⚠️ Error updating market trade: {e}")
            if 'db' in locals():
                await db.rollback()
