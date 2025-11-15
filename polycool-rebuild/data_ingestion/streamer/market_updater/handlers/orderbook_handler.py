"""
Orderbook Handler - Handle orderbook updates from WebSocket
Calculates mid price and updates market
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


class OrderbookHandler:
    """
    Handle orderbook updates from WebSocket
    Calculates mid price and updates market
    """

    @staticmethod
    def calculate_mid_price(orderbook: Dict[str, Any]) -> Optional[float]:
        """
        Calculate mid price from orderbook

        Args:
            orderbook: Orderbook data

        Returns:
            Mid price or None
        """
        try:
            # Extract best bid and ask
            bids = orderbook.get("bids") or orderbook.get("buy") or []
            asks = orderbook.get("asks") or orderbook.get("sell") or []

            if not bids or not asks:
                return None

            # Get best bid (highest) and best ask (lowest)
            best_bid = float(bids[0][0]) if bids and len(bids[0]) > 0 else None
            best_ask = float(asks[0][0]) if asks and len(asks[0]) > 0 else None

            if best_bid is None or best_ask is None:
                return None

            # Calculate mid price
            mid_price = (best_bid + best_ask) / 2.0
            return mid_price

        except Exception as e:
            logger.warning(f"⚠️ Error calculating mid price: {e}")
            return None

    @staticmethod
    async def update_market_orderbook(
        market_id: Optional[str],
        token_id: Optional[str],
        orderbook: Dict[str, Any],
        mid_price: Optional[float]
    ) -> None:
        """
        Update market orderbook in database

        Args:
            market_id: Market ID (optional)
            token_id: Token ID (optional)
            orderbook: Orderbook data
            mid_price: Calculated mid price
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

                # Update orderbook data
                update_data = {
                    "source": "ws",
                    "last_mid_price": mid_price,
                    "updated_at": datetime.now(timezone.utc)
                }

                await db.execute(
                    update(Market)
                    .where(Market.id == market.id)
                    .values(**update_data)
                )

                await db.commit()

                # Invalidate cache
                if market_id:
                    await cache_manager.delete(f"orderbook:{market_id}")
                    await cache_manager.delete(f"market:{market_id}")
                    await cache_manager.delete(f"market_detail:{market_id}")

        except Exception as e:
            logger.error(f"⚠️ Error updating market orderbook: {e}")
            if 'db' in locals():
                await db.rollback()
