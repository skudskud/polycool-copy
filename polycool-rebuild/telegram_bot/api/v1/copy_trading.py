"""
Copy Trading API Routes
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.services.copy_trading import get_copy_trading_service, get_leader_resolver
from core.database.connection import get_db
from core.database.models import WatchedAddress, CopyTradingAllocation
from sqlalchemy import select, and_
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# Pydantic models for API
class LeaderStats(BaseModel):
    """Leader statistics"""
    address: str
    name: Optional[str] = None
    address_type: str
    total_trades: int = 0
    win_rate: Optional[float] = None
    total_volume: float = 0.0
    avg_trade_size: Optional[float] = None
    risk_score: Optional[float] = None
    is_active: bool = True


class FollowerAllocation(BaseModel):
    """Follower allocation info"""
    allocation_id: Optional[int] = None
    user_id: int
    leader_address: str
    allocation_type: str
    allocation_value: float
    allocation_percentage: Optional[float] = None
    mode: str
    fixed_amount: Optional[float] = None
    total_wallet_balance: float = 0.0
    allocated_budget: float = 0.0
    budget_remaining: float = 0.0
    last_wallet_sync: Optional[str] = None
    is_active: bool
    total_copied_trades: int = 0
    total_pnl: float = 0.0


class SubscribeRequest(BaseModel):
    """Request to subscribe to a leader"""
    follower_user_id: int = Field(..., description="Telegram user ID of follower")
    leader_address: str = Field(..., description="Polygon address of leader (0x...)")
    allocation_type: str = Field(default="fixed_amount", description="'percentage' or 'fixed_amount'")
    allocation_value: float = Field(..., description="Percentage (0-100) or fixed amount in USD", gt=0)
    mode: str = Field(default="proportional", description="'proportional' or 'fixed_amount'")
    fixed_amount: Optional[float] = Field(None, description="Fixed USD amount for copy trading")


class UpdateAllocationRequest(BaseModel):
    """Request to update allocation settings"""
    allocation_value: Optional[float] = Field(None, description="New allocation value (for budget percentage)", gt=0)
    allocation_type: Optional[str] = Field(None, description="'percentage' or 'fixed_amount'")
    fixed_amount: Optional[float] = Field(None, description="Fixed USD amount for copy trading", gt=0)
    mode: Optional[str] = Field(None, description="Copy mode: 'proportional' or 'fixed_amount'")


class LeaderInfo(BaseModel):
    """Leader information response"""
    leader_type: str = Field(..., description="Type of leader: 'bot_user', 'smart_trader', or 'copy_leader'")
    leader_id: Optional[int] = Field(None, description="User ID if bot_user, None otherwise")
    watched_address_id: int = Field(..., description="ID in watched_addresses table")
    address: str = Field(..., description="Normalized Polygon address")


@router.get("/leaders", response_model=List[LeaderStats])
async def get_copy_trading_leaders(
    address_type: Optional[str] = Query(None, description="Filter by address_type: 'copy_leader', 'smart_trader'"),
    active_only: bool = Query(True, description="Only return active leaders"),
    min_trades: int = Query(0, description="Minimum number of trades"),
    limit: int = Query(20, description="Maximum number of leaders to return")
):
    """
    Get list of copy trading leaders

    Query params:
    - address_type: Filter by type (copy_leader, smart_trader)
    - active_only: Only active leaders
    - min_trades: Minimum trades filter
    - limit: Max results
    """
    try:
        async with get_db() as db:
            query = select(WatchedAddress)

            filters = []
            if active_only:
                filters.append(WatchedAddress.is_active == True)
            if address_type:
                filters.append(WatchedAddress.address_type == address_type)
            if min_trades > 0:
                filters.append(WatchedAddress.total_trades >= min_trades)

            if filters:
                query = query.where(and_(*filters))

            query = query.order_by(WatchedAddress.total_volume.desc()).limit(limit)

            result = await db.execute(query)
            leaders = result.scalars().all()

            return [
                LeaderStats(
                    address=leader.address,
                    name=leader.name,
                    address_type=leader.address_type,
                    total_trades=leader.total_trades or 0,
                    win_rate=(leader.win_rate * 100) if leader.win_rate else None,
                    total_volume=leader.total_volume or 0.0,
                    avg_trade_size=leader.avg_trade_size,
                    risk_score=leader.risk_score,
                    is_active=leader.is_active
                )
                for leader in leaders
            ]

    except Exception as e:
        logger.error(f"Error fetching leaders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch leaders: {str(e)}")


@router.get("/followers/{user_id}", response_model=Optional[FollowerAllocation])
async def get_follower_allocation(user_id: int):
    """
    Get current allocation for a follower

    Args:
        user_id: Telegram user ID

    Returns:
        Allocation info or null if not following anyone
    """
    try:
        # Direct DB access for API endpoint (API always has DB access)
        from core.services.user.user_helper import get_user_data

        # Get user data to map telegram_user_id to internal user_id
        user_data = await get_user_data(user_id)
        if not user_data:
            return None

        internal_user_id = user_data.get('id')
        if not internal_user_id:
            return None

        async with get_db() as db:
            # Get active allocation
            result = await db.execute(
                select(CopyTradingAllocation).where(
                    and_(
                        CopyTradingAllocation.user_id == internal_user_id,
                        CopyTradingAllocation.is_active == True
                    )
                )
            )
            allocation = result.scalar_one_or_none()

        if not allocation:
            return None

        # Get leader info
        async with get_db() as db:
            result = await db.execute(
                select(WatchedAddress).where(WatchedAddress.id == allocation.leader_address_id)
            )
            leader = result.scalar_one_or_none()

        if not leader:
            return None

        return FollowerAllocation(
            allocation_id=allocation.id,
            user_id=allocation.user_id,
            leader_address=leader.address,
            allocation_type=allocation.allocation_type,
            allocation_value=float(allocation.allocation_value),
            allocation_percentage=float(allocation.allocation_percentage) if allocation.allocation_percentage else None,
            mode=allocation.mode,
            fixed_amount=float(allocation.fixed_amount) if allocation.fixed_amount else None,
            total_wallet_balance=float(allocation.total_wallet_balance or 0.0),
            allocated_budget=float(allocation.allocated_budget or 0.0),
            budget_remaining=float(allocation.budget_remaining or 0.0),
            last_wallet_sync=allocation.last_wallet_sync.isoformat() if allocation.last_wallet_sync else None,
            is_active=allocation.is_active,
            total_copied_trades=allocation.total_copied_trades or 0,
            total_pnl=float(allocation.total_pnl or 0.0)
        )

    except Exception as e:
        logger.error(f"Error fetching follower allocation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch allocation: {str(e)}")


@router.post("/subscribe")
async def subscribe_to_leader(request: SubscribeRequest):
    """
    Subscribe follower to a leader

    Body:
    - follower_user_id: Telegram user ID
    - leader_address: Polygon address (0x...)
    - allocation_type: 'percentage' or 'fixed_amount'
    - allocation_value: Value (0-100 for percentage, USD amount for fixed)
    - mode: 'proportional' or 'fixed_amount'
    """
    try:
        service = get_copy_trading_service()

        result = await service.subscribe_to_leader(
            follower_user_id=request.follower_user_id,
            leader_address=request.leader_address,
            allocation_type=request.allocation_type,
            allocation_value=request.allocation_value,
            mode=request.mode,
            fixed_amount=request.fixed_amount
        )

        if not result.get('success'):
            raise HTTPException(status_code=400, detail=result.get('error', 'Subscription failed'))

        return {
            "success": True,
            "message": "Successfully subscribed to leader",
            "allocation_id": result.get('allocation_id')
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error subscribing to leader: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Subscription failed: {str(e)}")


@router.put("/followers/{user_id}/allocation")
async def update_allocation(user_id: int, request: UpdateAllocationRequest):
    """
    Update allocation settings for a follower

    Args:
        user_id: Telegram user ID

    Body:
        allocation_value: New allocation value (for budget percentage)
        allocation_type: Optional new type
        fixed_amount: Fixed USD amount for copy trading
        mode: Copy mode ('proportional' or 'fixed_amount')
    """
    try:
        logger.info(f"🔄 [API] Updating allocation for user {user_id}: mode={request.mode}, allocation_value={request.allocation_value}, allocation_type={request.allocation_type}, fixed_amount={request.fixed_amount}")

        service = get_copy_trading_service()

        success = await service.update_allocation_settings(
            follower_user_id=user_id,
            allocation_value=request.allocation_value,
            allocation_type=request.allocation_type,
            fixed_amount=request.fixed_amount,
            mode=request.mode
        )

        if success:
            logger.info(f"✅ [API] Successfully updated allocation for user {user_id}")
        else:
            logger.error(f"❌ [API] Failed to update allocation for user {user_id}")

        if not success:
            raise HTTPException(status_code=400, detail="Failed to update allocation")

        return {
            "success": True,
            "message": "Allocation updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating allocation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.delete("/followers/{user_id}/subscription")
async def unsubscribe_from_leader(user_id: int):
    """
    Unsubscribe follower from current leader

    Args:
        user_id: Telegram user ID
    """
    try:
        service = get_copy_trading_service()

        success = await service.unsubscribe_from_leader(follower_user_id=user_id)

        if not success:
            raise HTTPException(status_code=400, detail="Not currently following anyone")

        return {
            "success": True,
            "message": "Successfully unsubscribed from leader"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsubscribing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unsubscribe failed: {str(e)}")


@router.get("/followers/{user_id}/stats")
async def get_follower_stats(user_id: int):
    """
    Get copy trading stats for a follower

    Args:
        user_id: Telegram user ID

    Returns:
        Stats including PnL, trades copied, etc.
    """
    try:
        service = get_copy_trading_service()
        stats = await service.get_follower_stats(user_id)

        if not stats:
            return {
                "total_trades": 0,
                "total_pnl": 0.0,
                "success_rate": None,
                "total_volume": 0.0
            }

        return stats

    except Exception as e:
        logger.error(f"Error fetching follower stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")


@router.get("/watched-address/{watched_address_id}", response_model=Optional[LeaderStats])
async def get_watched_address(watched_address_id: int):
    """
    Get watched address (leader) statistics by ID

    Args:
        watched_address_id: WatchedAddress ID

    Returns:
        Leader statistics or None if not found
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(WatchedAddress).where(WatchedAddress.id == watched_address_id)
            )
            watched_addr = result.scalar_one_or_none()

        if not watched_addr:
            return None

        return LeaderStats(
            address=watched_addr.address,
            name=watched_addr.name,
            address_type=watched_addr.address_type,
            total_trades=watched_addr.total_trades or 0,
            win_rate=(watched_addr.win_rate * 100) if watched_addr.win_rate else None,
            total_volume=watched_addr.total_volume or 0.0,
            avg_trade_size=None,  # avg_trade_size not stored in WatchedAddress model
            risk_score=watched_addr.risk_score,
            is_active=watched_addr.is_active
        )

    except Exception as e:
        logger.error(f"Error fetching watched address {watched_address_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch watched address: {str(e)}")


@router.get("/resolve-leader/{polygon_address}", response_model=LeaderInfo)
async def resolve_leader_by_address(polygon_address: str):
    """
    Resolve a Polygon address to leader information

    Uses 3-tier resolution:
    1. Bot User (from users table) → creates watched_address with user_id
    2. Smart Trader (from watched_addresses with type='smart_trader')
    3. Copy Leader (from watched_addresses with type='copy_leader' or create new)

    Args:
        polygon_address: Polygon wallet address (case-insensitive, 0x...)

    Returns:
        LeaderInfo with leader_type, leader_id, watched_address_id, address

    Raises:
        400: If address format is invalid
        500: If resolution fails
    """
    try:
        if not polygon_address or not polygon_address.startswith('0x'):
            raise HTTPException(status_code=400, detail="Invalid Polygon address format. Must start with '0x'")

        leader_resolver = get_leader_resolver()
        leader_info = await leader_resolver.resolve_leader_by_address(polygon_address)

        return LeaderInfo(
            leader_type=leader_info.leader_type,
            leader_id=leader_info.leader_id,
            watched_address_id=leader_info.watched_address_id,
            address=leader_info.address
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving leader for address {polygon_address}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to resolve leader: {str(e)}")
