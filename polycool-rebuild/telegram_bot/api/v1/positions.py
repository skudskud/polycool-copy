"""
Positions API Routes
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.services.user.user_service import user_service
from core.services.position.position_service import position_service
from core.services.position.outcome_helper import find_outcome_index
from core.services.cache_manager import CacheManager
from core.services.market_service import get_market_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _extract_price_from_market(market: Dict[str, Any], outcome: str) -> Optional[float]:
    """
    Extract current price for a position from market data

    CRITICAL: When source='ws', use ONLY outcome_prices (no fallbacks)
    This ensures consistency with WebSocket-streamed prices from markets table

    Args:
        market: Market data dict from database (includes 'source' and 'outcome_prices')
        outcome: Position outcome ("YES" or "NO")

    Returns:
        Current price (0-1) or None if not available
    """
    try:
        source = market.get('source', 'poll')

        # CRITICAL: When source='ws', use ONLY outcome_prices (no fallbacks)
        # This ensures we always use WebSocket prices from markets.outcome_prices
        if source == 'ws':
            outcome_prices = market.get('outcome_prices')
            if not outcome_prices:
                logger.warning(f"⚠️ Market {market.get('id', 'unknown')} has source='ws' but no outcome_prices available")
                return None

            # Handle list format [YES_price, NO_price]
            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                outcomes = market.get('outcomes', ['YES', 'NO'])
                try:
                    outcome_index = find_outcome_index(outcome, outcomes)
                    if outcome_index is not None and outcome_index < len(outcome_prices):
                        price = float(outcome_prices[outcome_index])
                        if 0 <= price <= 1:
                            return price
                except (ValueError, IndexError, TypeError) as e:
                    logger.warning(f"⚠️ Error extracting price from outcome_prices list for market {market.get('id', 'unknown')}: {e}")
                    return None
            # Handle dict format (legacy)
            elif isinstance(outcome_prices, dict):
                outcome_key = outcome.upper()
                if outcome_key in outcome_prices:
                    price = float(outcome_prices[outcome_key])
                    if 0 <= price <= 1:
                        return price
                logger.warning(f"⚠️ Market {market.get('id', 'unknown')} has source='ws' but outcome '{outcome}' not in outcome_prices dict")
                return None
            else:
                logger.warning(f"⚠️ Market {market.get('id', 'unknown')} has source='ws' but invalid outcome_prices format: {type(outcome_prices)}")
                return None

        # For source='poll' or other sources, try outcome_prices first, then fallbacks
        outcome_prices = market.get('outcome_prices')
        if outcome_prices:
            # Handle list format [YES_price, NO_price]
            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                outcomes = market.get('outcomes', ['YES', 'NO'])
                try:
                    outcome_index = find_outcome_index(outcome, outcomes)
                    if outcome_index is not None and outcome_index < len(outcome_prices):
                        price = float(outcome_prices[outcome_index])
                        if 0 <= price <= 1:
                            return price
                except (ValueError, IndexError, TypeError) as e:
                    logger.debug(f"⚠️ Error extracting price from outcome_prices list: {e}")
            # Handle dict format (legacy)
            elif isinstance(outcome_prices, dict):
                outcome_key = outcome.upper()
                if outcome_key in outcome_prices:
                    price = float(outcome_prices[outcome_key])
                    if 0 <= price <= 1:
                        return price

        # Fallback to last_mid_price (only for source='poll')
        last_mid_price = market.get('last_mid_price')
        if last_mid_price is not None:
            price = float(last_mid_price)
            if 0 <= price <= 1:
                # CORRECTED: No longer invert prices for NO positions - P&L calculator handles both outcomes the same way
                return price

        # Fallback to last_trade_price (only for source='poll')
        last_trade_price = market.get('last_trade_price')
        if last_trade_price is not None:
            price = float(last_trade_price)
            if 0 <= price <= 1:
                # CORRECTED: No longer invert prices for NO positions - P&L calculator handles both outcomes the same way
                return price

        return None
    except Exception as e:
        logger.debug(f"⚠️ Error extracting price from market: {e}")
        return None


class CreatePositionRequest(BaseModel):
    """Request model for creating a position"""
    user_id: int
    market_id: str
    outcome: str
    amount: float  # Number of tokens/shares
    entry_price: float
    is_copy_trade: bool = False
    total_cost: Optional[float] = None  # Number of shares (for BUY) or sold (for SELL). Note: Despite the name 'total_cost', this stores SHARES, not USD cost.


class UpdateTPSLRequest(BaseModel):
    """Request model for updating TP/SL"""
    tpsl_type: str  # "tp" or "sl"
    price: float


class UpdatePositionRequest(BaseModel):
    """Request model for updating position amount"""
    amount: Optional[float] = None
    current_price: Optional[float] = None
    status: Optional[str] = None  # "active" or "closed"


@router.get("/user/{user_id}")
async def get_user_positions(user_id: int):
    """
    Get user positions

    Args:
        user_id: Internal user ID (not Telegram ID)

    Returns:
        Positions data with list of active positions
    """
    try:
        # Verify user exists
        user = await user_service.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get active positions - filter by status AND amount > 0
        all_positions = await position_service.get_active_positions(user_id)

        # Filter: only positions with amount > 0 (closed positions should have amount = 0)
        positions = [pos for pos in all_positions if pos.amount and float(pos.amount) > 0]

        logger.info(f"📊 User {user_id}: Found {len(all_positions)} positions with status='active', filtered to {len(positions)} with amount > 0")

        # ✅ CRITICAL: Fetch markets for all positions to get current prices
        # Get unique market IDs
        market_ids = list(set([pos.market_id for pos in positions]))
        markets_map = {}

        # Fetch markets from database
        market_service = get_market_service()
        for market_id in market_ids:
            try:
                market = await market_service.get_market_by_id(market_id)
                if market:
                    markets_map[market_id] = market
            except Exception as e:
                logger.warning(f"⚠️ Failed to fetch market {market_id}: {e}")

        # Convert to dict format with prices from markets table
        positions_data = []
        for pos in positions:
            amount = float(pos.amount) if pos.amount else 0.0
            if amount <= 0:
                logger.warning(f"⚠️ Skipping position {pos.id} with amount={amount}")
                continue

            # ✅ Get current_price from markets table instead of positions table
            current_price = None
            market = markets_map.get(pos.market_id)
            if market:
                current_price = _extract_price_from_market(market, pos.outcome)
                if current_price is None:
                    # Fallback to position's stored current_price if market price not available
                    current_price = float(pos.current_price) if pos.current_price else None
                    logger.debug(f"⚠️ No price found in market {pos.market_id} for outcome {pos.outcome}, using stored price: {current_price}")
            else:
                # Market not found, use stored price as fallback
                current_price = float(pos.current_price) if pos.current_price else None
                logger.debug(f"⚠️ Market {pos.market_id} not found, using stored price: {current_price}")

            positions_data.append({
                "id": pos.id,
                "market_id": pos.market_id,
                "outcome": pos.outcome,
                "amount": amount,
                "entry_price": float(pos.entry_price) if pos.entry_price else 0.0,
                "current_price": current_price,  # ✅ Now from markets table
                "pnl_amount": float(pos.pnl_amount) if pos.pnl_amount else 0.0,
                "pnl_percentage": float(pos.pnl_percentage) if pos.pnl_percentage else 0.0,
                "status": pos.status,
                "take_profit_price": float(pos.take_profit_price) if pos.take_profit_price else None,
                "stop_loss_price": float(pos.stop_loss_price) if pos.stop_loss_price else None,
                "total_cost": float(pos.total_cost) if pos.total_cost else None,
                "created_at": pos.created_at.isoformat() if pos.created_at else None,
                "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
                "closed_at": pos.closed_at.isoformat() if pos.closed_at else None
            })

        return {
            "user_id": user_id,
            "telegram_user_id": user.telegram_user_id,
            "positions": positions_data,
            "total_positions": len(positions_data)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting positions for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting positions: {str(e)}")


@router.get("/market/{market_id}")
async def get_market_positions(market_id: str):
    """
    Get all active positions for a specific market

    Args:
        market_id: Market ID

    Returns:
        List of active positions for the market
    """
    try:
        # Get all active positions for this market
        positions = await position_service.get_positions_by_market(market_id)

        # Filter: only positions with amount > 0
        positions = [pos for pos in positions if pos.amount and float(pos.amount) > 0]

        logger.info(f"📊 Market {market_id}: Found {len(positions)} active positions with amount > 0")

        # Convert to dict format
        positions_data = []
        for pos in positions:
            amount = float(pos.amount) if pos.amount else 0.0
            if amount <= 0:
                continue

            positions_data.append({
                "id": pos.id,
                "user_id": pos.user_id,
                "market_id": pos.market_id,
                "outcome": pos.outcome,
                "amount": amount,
                "entry_price": float(pos.entry_price) if pos.entry_price else 0.0,
                "current_price": float(pos.current_price) if pos.current_price else None,
                "pnl_amount": float(pos.pnl_amount) if pos.pnl_amount else 0.0,
                "pnl_percentage": float(pos.pnl_percentage) if pos.pnl_percentage else 0.0,
                "status": pos.status,
                "take_profit_price": float(pos.take_profit_price) if pos.take_profit_price else None,
                "stop_loss_price": float(pos.stop_loss_price) if pos.stop_loss_price else None,
                "created_at": pos.created_at.isoformat() if pos.created_at else None,
                "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
                "closed_at": pos.closed_at.isoformat() if pos.closed_at else None
            })

        return {
            "market_id": market_id,
            "positions": positions_data,
            "total_positions": len(positions_data)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting positions for market {market_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting positions: {str(e)}")


@router.get("/{position_id}")
async def get_position(position_id: int):
    """
    Get specific position by ID

    Args:
        position_id: Position ID

    Returns:
        Position data or 404 if not found
    """
    try:
        # Get position from database
        position = await position_service.get_position(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        # Convert to dict format
        return {
            "id": position.id,
            "user_id": position.user_id,
            "market_id": position.market_id,
            "outcome": position.outcome,
            "amount": float(position.amount) if position.amount else 0.0,
            "entry_price": float(position.entry_price) if position.entry_price else 0.0,
            "current_price": float(position.current_price) if position.current_price else None,
            "pnl_amount": float(position.pnl_amount) if position.pnl_amount else 0.0,
            "pnl_percentage": float(position.pnl_percentage) if position.pnl_percentage else 0.0,
            "status": position.status,
            "take_profit_price": float(position.take_profit_price) if position.take_profit_price else None,
            "stop_loss_price": float(position.stop_loss_price) if position.stop_loss_price else None,
            "total_cost": float(position.total_cost) if position.total_cost else None,
            "created_at": position.created_at.isoformat() if position.created_at else None,
            "updated_at": position.updated_at.isoformat() if position.updated_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting position {position_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting position: {str(e)}")


@router.post("/", response_model=dict)
async def create_position(request: CreatePositionRequest):
    """
    Create a new position

    Args:
        request: Position creation request

    Returns:
        Created position data
    """
    try:
        # Verify user exists
        user = await user_service.get_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Validate entry_price is in valid Polymarket range (0-1)
        if not (0 <= request.entry_price <= 1):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid entry price {request.entry_price} for Polymarket position - should be 0-1"
            )

        # Create position via service
        position = await position_service.create_position(
            user_id=request.user_id,
            market_id=request.market_id,
            outcome=request.outcome,
            amount=request.amount,
            entry_price=request.entry_price,
            is_copy_trade=request.is_copy_trade,
            total_cost=request.total_cost
        )

        if not position:
            raise HTTPException(status_code=500, detail="Failed to create position")

        # ✅ CRITICAL: Invalidate cache after position creation (microservices cache coherence)
        try:
            cache_manager = CacheManager()
            await cache_manager.invalidate_pattern(f"api:positions:{request.user_id}")
            logger.info(f"✅ Cache invalidated for user {request.user_id} after position creation")
        except Exception as e:
            logger.warning(f"⚠️ Cache invalidation failed (non-fatal): {e}")

        # Convert to dict format
        return {
            "id": position.id,
            "user_id": position.user_id,
            "market_id": position.market_id,
            "outcome": position.outcome,
            "amount": float(position.amount) if position.amount else 0.0,
            "entry_price": float(position.entry_price) if position.entry_price else 0.0,
            "current_price": float(position.current_price) if position.current_price else None,
            "pnl_amount": float(position.pnl_amount) if position.pnl_amount else 0.0,
            "pnl_percentage": float(position.pnl_percentage) if position.pnl_percentage else 0.0,
            "status": position.status,
            "is_copy_trade": position.is_copy_trade,
            "total_cost": float(position.total_cost) if position.total_cost else None,
            "created_at": position.created_at.isoformat() if position.created_at else None,
            "updated_at": position.updated_at.isoformat() if position.updated_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating position: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating position: {str(e)}")


@router.post("/sync/{user_id}")
async def sync_positions(user_id: int):
    """
    Sync user positions from blockchain

    Args:
        user_id: Internal user ID (not Telegram ID)

    Returns:
        Sync result with number of positions synced
    """
    try:
        # Verify user exists
        user = await user_service.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.polygon_address:
            raise HTTPException(status_code=400, detail="User has no Polygon address")

        # Sync positions from blockchain
        synced_count = await position_service.sync_positions_from_blockchain(
            user_id=user_id,
            wallet_address=user.polygon_address
        )

        logger.info(f"Synced {synced_count} positions for user {user_id}")

        # Update prices for all positions
        updated_count = await position_service.update_all_positions_prices(user_id=user_id)
        logger.info(f"Updated prices for {updated_count} positions")

        # ✅ CRITICAL: Invalidate cache after sync (microservices cache coherence)
        try:
            cache_manager = CacheManager()
            await cache_manager.invalidate_pattern(f"api:positions:{user_id}")
            logger.info(f"✅ Cache invalidated for user {user_id} after positions sync")
        except Exception as e:
            logger.warning(f"⚠️ Cache invalidation failed (non-fatal): {e}")

        return {
            "user_id": user_id,
            "telegram_user_id": user.telegram_user_id,
            "synced_positions": synced_count,
            "updated_prices": updated_count,
            "success": True
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        full_traceback = traceback.format_exc()

        # Log to both logger and stderr for visibility
        logger.error(f"❌ Error syncing positions for user {user_id}: {error_type}: {error_msg}")
        logger.error(f"❌ Full traceback:\n{full_traceback}")

        # Also print to stderr for immediate visibility in terminal
        import sys
        print(f"\n{'='*80}", file=sys.stderr)
        print(f"❌ SYNC ERROR for user {user_id}", file=sys.stderr)
        print(f"Type: {error_type}", file=sys.stderr)
        print(f"Message: {error_msg}", file=sys.stderr)
        print(f"Traceback:\n{full_traceback}", file=sys.stderr)
        print(f"{'='*80}\n", file=sys.stderr)

        raise HTTPException(status_code=500, detail=f"Error syncing positions: {error_msg}")


@router.put("/{position_id}/tpsl", response_model=dict)
async def update_position_tpsl(position_id: int, request: UpdateTPSLRequest):
    """
    Update TP/SL for a position

    Args:
        position_id: Position ID
        request: TP/SL update request

    Returns:
        Updated position data
    """
    try:
        # Verify position exists
        position = await position_service.get_position(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        # Validate price range (0-1 for Polymarket)
        if not (0 <= request.price <= 1):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid price {request.price} for Polymarket position - should be 0-1"
            )

        # Validate tpsl_type
        if request.tpsl_type not in ["tp", "sl"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tpsl_type {request.tpsl_type} - must be 'tp' or 'sl'"
            )

        # ✅ NEW: Validate SL < TP if both are set (limit order logic)
        # Only validate when setting a price (not when clearing with price=0.0)
        if request.price != 0.0:
            # Get current TP/SL values
            current_tp = position.take_profit_price
            current_sl = position.stop_loss_price

            # Determine what the new values will be
            new_tp = request.price if request.tpsl_type == "tp" else current_tp
            new_sl = request.price if request.tpsl_type == "sl" else current_sl

            # Validate SL < TP if both are set
            if new_tp is not None and new_sl is not None:
                if new_sl >= new_tp:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid TP/SL configuration: Stop Loss (${new_sl:.4f}) must be < Take Profit (${new_tp:.4f})"
                    )

        # Update TP/SL via service
        updated_position = await position_service.update_position_tpsl(
            position_id=position_id,
            tpsl_type=request.tpsl_type,
            price=request.price
        )

        if not updated_position:
            raise HTTPException(status_code=500, detail="Failed to update TP/SL")

        # ✅ CRITICAL: Invalidate cache after TP/SL update (microservices cache coherence)
        try:
            cache_manager = CacheManager()
            await cache_manager.invalidate_pattern(f"api:positions:{updated_position.user_id}")
            logger.info(f"✅ Cache invalidated for user {updated_position.user_id} after TP/SL update")
        except Exception as e:
            logger.warning(f"⚠️ Cache invalidation failed (non-fatal): {e}")

        # Convert to dict format
        return {
            "id": updated_position.id,
            "user_id": updated_position.user_id,
            "market_id": updated_position.market_id,
            "outcome": updated_position.outcome,
            "amount": float(updated_position.amount) if updated_position.amount else 0.0,
            "entry_price": float(updated_position.entry_price) if updated_position.entry_price else 0.0,
            "current_price": float(updated_position.current_price) if updated_position.current_price else None,
            "pnl_amount": float(updated_position.pnl_amount) if updated_position.pnl_amount else 0.0,
            "pnl_percentage": float(updated_position.pnl_percentage) if updated_position.pnl_percentage else 0.0,
            "status": updated_position.status,
            "take_profit_price": float(updated_position.take_profit_price) if updated_position.take_profit_price else None,
            "stop_loss_price": float(updated_position.stop_loss_price) if updated_position.stop_loss_price else None,
            "total_cost": float(updated_position.total_cost) if updated_position.total_cost else None,
            "created_at": updated_position.created_at.isoformat() if updated_position.created_at else None,
            "updated_at": updated_position.updated_at.isoformat() if updated_position.updated_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating TP/SL for position {position_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating TP/SL: {str(e)}")


@router.put("/{position_id}", response_model=dict)
async def update_position(position_id: int, request: UpdatePositionRequest):
    """
    Update position amount or status (e.g., after partial sell)

    Args:
        position_id: Position ID
        request: Position update request

    Returns:
        Updated position data
    """
    try:
        # Verify position exists
        position = await position_service.get_position(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        # ✅ CRITICAL: If closing position, use close_position() to trigger WebSocket unsubscription
        if request.status == "closed":
            logger.info(f"🔒 Closing position {position_id} via API endpoint (will trigger WebSocket unsubscription)")
            updated_position = await position_service.close_position(
                position_id=position_id,
                exit_price=request.current_price
            )
        else:
            # Update position via service (partial sell or other updates)
            updated_position = await position_service.update_position(
                position_id=position_id,
                amount=request.amount,
                current_price=request.current_price,
                status=request.status
            )

        if not updated_position:
            raise HTTPException(status_code=500, detail="Failed to update position")

        # ✅ CRITICAL: Invalidate cache after position update (microservices cache coherence)
        try:
            cache_manager = CacheManager()
            await cache_manager.invalidate_pattern(f"api:positions:{updated_position.user_id}")
            logger.info(f"✅ Cache invalidated for user {updated_position.user_id} after position update")
        except Exception as e:
            logger.warning(f"⚠️ Cache invalidation failed (non-fatal): {e}")

        # Convert to dict format
        return {
            "id": updated_position.id,
            "user_id": updated_position.user_id,
            "market_id": updated_position.market_id,
            "outcome": updated_position.outcome,
            "amount": float(updated_position.amount) if updated_position.amount else 0.0,
            "entry_price": float(updated_position.entry_price) if updated_position.entry_price else 0.0,
            "current_price": float(updated_position.current_price) if updated_position.current_price else None,
            "pnl_amount": float(updated_position.pnl_amount) if updated_position.pnl_amount else 0.0,
            "pnl_percentage": float(updated_position.pnl_percentage) if updated_position.pnl_percentage else 0.0,
            "status": updated_position.status,
            "take_profit_price": float(updated_position.take_profit_price) if updated_position.take_profit_price else None,
            "stop_loss_price": float(updated_position.stop_loss_price) if updated_position.stop_loss_price else None,
            "total_cost": float(updated_position.total_cost) if updated_position.total_cost else None,
            "created_at": updated_position.created_at.isoformat() if updated_position.created_at else None,
            "updated_at": updated_position.updated_at.isoformat() if updated_position.updated_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating position {position_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating position: {str(e)}")


@router.get("/resolved/{user_id}")
async def get_resolved_positions(user_id: int):
    """
    Get resolved (redeemable) positions for a user

    Args:
        user_id: Internal user ID (not Telegram ID)

    Returns:
        List of resolved positions that can be redeemed
    """
    try:
        from core.database.connection import get_db
        from core.database.models import ResolvedPosition
        from sqlalchemy import select

        # Verify user exists
        user = await user_service.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        async with get_db() as db:
            # Show PENDING, PROCESSING, and FAILED positions (all allow retry)
            query = select(ResolvedPosition).where(
                ResolvedPosition.user_id == user_id,
                ResolvedPosition.status.in_(['PENDING', 'PROCESSING', 'FAILED']),
                ResolvedPosition.is_winner == True,
                ResolvedPosition.tokens_held >= 0.5  # Only show positions with >= 0.5 tokens
            ).order_by(ResolvedPosition.resolved_at.desc())
            result = await db.execute(query)
            claimable = result.scalars().all()

            return {
                "user_id": user_id,
                "resolved_positions": [pos.to_dict() for pos in claimable],
                "count": len(claimable)
            }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Error getting resolved positions: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting resolved positions: {str(e)}")


@router.get("/resolved/{user_id}/{resolved_position_id}")
async def get_resolved_position(user_id: int, resolved_position_id: int):
    """
    Get a specific resolved position

    Args:
        user_id: Internal user ID (not Telegram ID)
        resolved_position_id: Resolved position ID

    Returns:
        Resolved position data
    """
    try:
        from core.database.connection import get_db
        from core.database.models import ResolvedPosition
        from sqlalchemy import select

        # Verify user exists
        user = await user_service.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        async with get_db() as db:
            query = select(ResolvedPosition).where(
                ResolvedPosition.id == resolved_position_id,
                ResolvedPosition.user_id == user_id
            )
            result = await db.execute(query)
            resolved_pos = result.scalar_one_or_none()

            if not resolved_pos:
                raise HTTPException(status_code=404, detail="Resolved position not found")

            return resolved_pos.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Error getting resolved position: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting resolved position: {str(e)}")


class DetectRedeemableRequest(BaseModel):
    """Request to detect redeemable positions"""
    positions_data: List[Dict[str, Any]]
    wallet_address: str


@router.post("/resolved/{user_id}/detect")
async def detect_redeemable_positions(user_id: int, request: DetectRedeemableRequest):
    """
    Detect and create redeemable positions for a user

    Args:
        user_id: Internal user ID (not Telegram ID)
        request: Request with positions data and wallet address

    Returns:
        Dict with redeemable_positions and resolved_condition_ids
    """
    try:
        from core.services.redeem.redeemable_detector import get_redeemable_detector

        logger.info(
            f"🔍 [API] detect_redeemable_positions called for user {user_id}, "
            f"wallet {request.wallet_address[:10]}..., "
            f"{len(request.positions_data)} positions"
        )

        # Verify user exists
        user = await user_service.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Count closed vs active positions
        closed_count = sum(1 for p in request.positions_data if p.get('closed', False))
        active_count = len(request.positions_data) - closed_count
        logger.info(
            f"📊 [API] Processing {active_count} active, {closed_count} closed positions "
            f"for user {user_id}"
        )

        # Detect redeemable positions
        detector = get_redeemable_detector()
        redeemable_positions, resolved_condition_ids = await detector.detect_redeemable_positions(
            request.positions_data,
            user_id,
            request.wallet_address
        )

        logger.info(
            f"✅ [API] Detected {len(redeemable_positions)} redeemable positions, "
            f"{len(resolved_condition_ids)} resolved condition IDs for user {user_id}"
        )

        return {
            "user_id": user_id,
            "redeemable_positions": redeemable_positions,
            "resolved_condition_ids": resolved_condition_ids,
            "count": len(redeemable_positions)
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Error detecting redeemable positions: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error detecting redeemable positions: {str(e)}")


class RedeemPositionRequest(BaseModel):
    """Request to redeem a resolved position"""
    private_key: str  # User's decrypted private key (sent securely)


@router.post("/resolved/{user_id}/{resolved_position_id}/redeem")
async def redeem_resolved_position(user_id: int, resolved_position_id: int, request: RedeemPositionRequest):
    """
    Execute redemption for a resolved position

    Args:
        user_id: Internal user ID (not Telegram ID)
        resolved_position_id: Resolved position ID
        request: Request with private key

    Returns:
        Redemption result with tx_hash and status
    """
    try:
        from core.services.redeem.redemption_service import get_redemption_service

        # Verify user exists
        user = await user_service.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Execute redemption
        redemption_service = get_redemption_service()
        result = await redemption_service.redeem_position(resolved_position_id, request.private_key)

        return result

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Error redeeming position: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error redeeming position: {str(e)}")
