"""
Position Service - Main orchestration service for positions
Delegates to specialized modules: CRUD, P&L, Price Updates, Blockchain Sync
"""
from typing import List, Optional, Any

from infrastructure.logging.logger import get_logger
from . import crud
from . import price_updater
from . import blockchain_sync
from .pnl_calculator import calculate_pnl
from core.database.models import Position

logger = get_logger(__name__)


class PositionService:
    """
    Position Service - Main orchestration service
    Delegates to specialized modules for better maintainability
    """

    # CRUD Operations
    async def create_position(
        self,
        user_id: int,
        market_id: str,
        outcome: str,
        amount: float,
        entry_price: float,
        is_copy_trade: bool = False,
        total_cost: Optional[float] = None,
        position_id: Optional[str] = None
    ) -> Optional[Any]:
        """Create a new position"""
        return await crud.create_position(
            user_id=user_id,
            market_id=market_id,
            outcome=outcome,
            amount=amount,
            entry_price=entry_price,
            is_copy_trade=is_copy_trade,
            total_cost=total_cost,
            position_id=position_id
        )

    async def get_active_positions(self, user_id: int) -> List[Position]:
        """Get all active positions for a user"""
        return await crud.get_active_positions(user_id)

    async def get_closed_positions(self, user_id: int, limit: int = 50) -> List[Position]:
        """Get closed positions for a user"""
        return await crud.get_closed_positions(user_id, limit=limit)

    async def get_position(self, position_id: int) -> Optional[Position]:
        """Get a position by ID"""
        return await crud.get_position(position_id)

    async def get_positions_by_market(self, market_id: str) -> List[Position]:
        """Get all active positions for a specific market"""
        return await crud.get_positions_by_market(market_id)

    async def update_position(
        self,
        position_id: int,
        amount: Optional[float] = None,
        current_price: Optional[float] = None,
        status: Optional[str] = None
    ) -> Optional[Any]:
        """Update position amount, price, or status"""
        return await crud.update_position(
            position_id=position_id,
            amount=amount,
            current_price=current_price,
            status=status
        )

    async def update_position_tpsl(
        self,
        position_id: int,
        tpsl_type: str,
        price: float
    ) -> Optional[Any]:
        """Update TP/SL price for a position"""
        return await crud.update_position_tpsl(
            position_id=position_id,
            tpsl_type=tpsl_type,
            price=price
        )

    async def close_position(
        self,
        position_id: int,
        exit_price: Optional[float] = None
    ) -> Optional[Position]:
        """Close a position"""
        return await crud.close_position(
            position_id=position_id,
            exit_price=exit_price
        )

    # Price Updates
    async def update_position_price(
        self,
        position_id: int,
        current_price: float
    ) -> Optional[Position]:
        """Update position current price and recalculate P&L"""
        return await price_updater.update_position_price(
            position_id=position_id,
            current_price=current_price
        )

    async def batch_update_positions_prices(
        self,
        position_updates: List[dict]
    ) -> int:
        """Batch update position prices"""
        return await price_updater.batch_update_positions_prices(position_updates)

    # P&L Calculations
    def _calculate_pnl(
        self,
        entry_price: float,
        current_price: float,
        amount: float,
        outcome: str
    ) -> tuple:
        """
        Calculate P&L for a position
        Delegates to pnl_calculator module
        """
        return calculate_pnl(
            entry_price=entry_price,
            current_price=current_price,
            amount=amount,
            outcome=outcome
        )

    # Blockchain Synchronization
    async def get_positions_from_blockchain(
        self,
        wallet_address: str
    ) -> List[dict]:
        """Get current positions from blockchain via Polymarket API"""
        return await blockchain_sync.get_positions_from_blockchain(wallet_address)

    async def get_closed_positions_from_blockchain(
        self,
        wallet_address: str
    ) -> List[dict]:
        """Get closed positions from blockchain via Polymarket API"""
        return await blockchain_sync.get_closed_positions_from_blockchain(wallet_address)

    async def sync_positions_from_blockchain(
        self,
        user_id: int,
        wallet_address: str
    ) -> int:
        """
        Sync positions from blockchain to database
        Uses ONLY 'size' field from Polymarket API
        NO hardcoded fallbacks - raises ValueError if required data is missing
        """
        return await blockchain_sync.sync_positions_from_blockchain(
            user_id=user_id,
            wallet_address=wallet_address
        )

    # Utility methods (kept for backward compatibility)
    async def get_markets_with_active_positions(self) -> List[str]:
        """
        Get list of market IDs that have active positions
        Used for WebSocket subscription management
        """
        try:
            from core.database.connection import get_db
            from sqlalchemy import select

            async with get_db() as db:
                result = await db.execute(
                    select(Position.market_id)
                    .where(Position.status == "active")
                    .distinct()
                )
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.error(f"❌ Error getting markets with active positions: {e}")
            return []

    async def update_all_positions_prices(
        self,
        user_id: int
    ) -> int:
        """
        Update prices for all active positions of a user
        Priority: WebSocket prices > CLOB API > market.last_mid_price
        NO fallback to entry_price - raises ValueError if no price available
        """
        return await price_updater.update_all_positions_prices_with_priority(user_id)


# Global instance
position_service = PositionService()
