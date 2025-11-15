"""
Position CRUD Operations - Create, Read, Update, Delete operations for positions
"""
import os
from typing import List, Optional, Any
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import Position
from infrastructure.logging.logger import get_logger
from .models import PositionFromAPI
from .pnl_calculator import calculate_pnl

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def create_position(
    user_id: int,
    market_id: str,
    outcome: str,
    amount: float,
    entry_price: float,
    is_copy_trade: bool = False,
    total_cost: Optional[float] = None,
    position_id: Optional[str] = None
) -> Optional[Any]:
    """
    Create a new position

    Args:
        user_id: User ID
        market_id: Market ID
        outcome: Outcome ("YES" or "NO")
        amount: Position size (number of tokens/shares)
        entry_price: Entry price
        is_copy_trade: True if position created via copy trading
        total_cost: Number of shares (for BUY) or sold (for SELL). If None, uses amount. Note: Despite the name 'total_cost', this stores SHARES, not USD cost.
        position_id: Token ID from blockchain (clob_token_id) - for precise position lookup

    Returns:
        Created Position object (or Position-like object from API) or None if error
    """
    try:
        # Use API if SKIP_DB is true
        if SKIP_DB:
            api_client = get_api_client()
            position_data = await api_client.create_position(
                user_id=user_id,
                market_id=market_id,
                outcome=outcome,
                amount=amount,
                entry_price=entry_price,
                is_copy_trade=is_copy_trade,
                total_cost=total_cost,
                position_id=position_id
            )

            if not position_data:
                logger.error(f"❌ Failed to create position via API for user {user_id}")
                return None

            position = PositionFromAPI(position_data)
            logger.info(f"✅ Created position {position.id} for user {user_id} via API: {amount} {outcome.upper()} @ ${entry_price:.4f} (copy_trade={is_copy_trade})")
            return position

        # Direct DB access when SKIP_DB is false
        async with get_db() as db:
            # Validate entry_price is in valid Polymarket range (0-1)
            if not (0 <= entry_price <= 1):
                logger.error(f"❌ Invalid entry price {entry_price} for Polymarket position - should be 0-1")
                return None

            # Calculate total_cost if not provided (should be same as amount since it stores shares)
            if total_cost is None:
                total_cost = amount  # total_cost stores shares, same as amount

            position = Position(
                user_id=user_id,
                market_id=market_id,
                outcome=outcome.upper(),
                amount=amount,
                entry_price=entry_price,
                current_price=entry_price,  # Initially same as entry
                pnl_amount=0.0,
                pnl_percentage=0.0,
                status="active",
                is_copy_trade=is_copy_trade,
                total_cost=total_cost,
                position_id=position_id,  # Store position_id for precise lookup
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            db.add(position)
            await db.commit()
            await db.refresh(position)

            logger.info(f"✅ Created position {position.id} for user {user_id}: {amount} {outcome.upper()} @ ${entry_price:.4f} (copy_trade={is_copy_trade})")
            return position

    except Exception as e:
        logger.error(f"❌ Error creating position: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def get_active_positions(user_id: int) -> List[Position]:
    """
    Get all active positions for a user

    Args:
        user_id: User ID

    Returns:
        List of active Position objects
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Position)
                .where(
                    and_(
                        Position.user_id == user_id,
                        Position.status == "active"
                    )
                )
                .order_by(Position.created_at.desc())
            )
            return list(result.scalars().all())
    except Exception as e:
        logger.error(f"❌ Error getting active positions for user {user_id}: {e}")
        return []


async def get_closed_positions(user_id: int, limit: int = 50) -> List[Position]:
    """
    Get closed positions for a user

    Args:
        user_id: User ID
        limit: Maximum number of positions to return

    Returns:
        List of closed Position objects
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Position)
                .where(
                    and_(
                        Position.user_id == user_id,
                        Position.status == "closed"
                    )
                )
                .order_by(Position.closed_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
    except Exception as e:
        logger.error(f"❌ Error getting closed positions for user {user_id}: {e}")
        return []


async def get_position(position_id: int) -> Optional[Position]:
    """
    Get a position by ID

    Args:
        position_id: Position ID

    Returns:
        Position object or None if not found
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.id == position_id)
            )
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"❌ Error getting position {position_id}: {e}")
        return None


async def get_positions_by_market(market_id: str) -> List[Position]:
    """
    Get all active positions for a specific market
    Used for automatic position price updates

    Args:
        market_id: Market ID

    Returns:
        List of active Position objects for this market
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Position)
                .where(
                    and_(
                        Position.market_id == market_id,
                        Position.status == "active"
                    )
                )
            )
            return list(result.scalars().all())
    except Exception as e:
        logger.error(f"❌ Error getting positions for market {market_id}: {e}")
        return []


async def get_position_by_market_and_outcome(
    user_id: int,
    market_id: str,
    outcome: str
) -> Optional[Position]:
    """
    Get position by user, market and outcome

    Args:
        user_id: User ID
        market_id: Market ID
        outcome: YES or NO

    Returns:
        Position object or None
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Position)
                .where(
                    and_(
                        Position.user_id == user_id,
                        Position.market_id == market_id,
                        Position.outcome == outcome,
                        Position.status == "active"
                    )
                )
            )
            return result.scalar_one_or_none()

    except Exception as e:
        logger.error(f"Error getting position for user {user_id}, market {market_id}, outcome {outcome}: {e}")
        return None


async def update_position(
    position_id: int,
    amount: Optional[float] = None,
    current_price: Optional[float] = None,
    status: Optional[str] = None
) -> Optional[Any]:
    """
    Update position amount, price, or status

    Args:
        position_id: Position ID
        amount: New amount (optional)
        current_price: New current price (optional)
        status: New status (optional, "active" or "closed")

    Returns:
        Updated Position object (or Position-like object from API) or None if error
    """
    try:
        # Use API if SKIP_DB is true
        if SKIP_DB:
            api_client = get_api_client()
            json_data = {}
            if amount is not None:
                json_data['amount'] = amount
            if current_price is not None:
                json_data['current_price'] = current_price
            if status is not None:
                json_data['status'] = status

            position_data = await api_client.update_position(
                position_id=position_id,
                **json_data
            )

            if not position_data:
                logger.error(f"❌ Failed to update position via API for position {position_id}")
                return None

            position = PositionFromAPI(position_data)
            logger.info(f"✅ Updated position {position_id} via API")
            return position

        # Direct DB access when SKIP_DB is false
        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.id == position_id)
            )
            position = result.scalar_one_or_none()

            if not position:
                return None

            # Update fields
            if amount is not None:
                position.amount = amount
            if current_price is not None:
                position.current_price = current_price
            if status is not None:
                position.status = status
                if status == "closed":
                    position.amount = 0.0  # Set amount to 0 when closing (positions with amount=0 are filtered out)
                    position.closed_at = datetime.now(timezone.utc)

            position.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.refresh(position)

            logger.info(f"✅ Updated position {position_id}")
            return position

    except Exception as e:
        logger.error(f"❌ Error updating position {position_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def update_position_tpsl(
    position_id: int,
    tpsl_type: str,
    price: float
) -> Optional[Any]:
    """
    Update TP/SL price for a position

    Args:
        position_id: Position ID
        tpsl_type: "tp" or "sl"
        price: Target price (0-1)

    Returns:
        Updated Position object (or Position-like object from API) or None if error
    """
    try:
        # Use API if SKIP_DB is true
        if SKIP_DB:
            api_client = get_api_client()
            position_data = await api_client.update_position_tpsl(
                position_id=position_id,
                tpsl_type=tpsl_type,
                price=price
            )

            if not position_data:
                logger.error(f"❌ Failed to update TP/SL via API for position {position_id}")
                return None

            position = PositionFromAPI(position_data)
            logger.info(f"✅ Updated {tpsl_type} price ${price:.4f} for position {position_id} via API")
            return position

        # Direct DB access when SKIP_DB is false
        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.id == position_id)
            )
            position = result.scalar_one_or_none()

            if not position:
                return None

            # Special case: price=0.0 means "clear" (set to None)
            # This is used when clearing TP/SL via the Clear button
            is_clear = price == 0.0

            if is_clear:
                if tpsl_type == "tp":
                    position.take_profit_price = None
                    position.take_profit_amount = None
                elif tpsl_type == "sl":
                    position.stop_loss_price = None
                    position.stop_loss_amount = None
                else:
                    logger.error(f"❌ Invalid tpsl_type: {tpsl_type}")
                    return None
            else:
                # Validate price range (0-1 for Polymarket)
                if not (0 < price <= 1):
                    logger.error(f"❌ Invalid price {price} for Polymarket position - should be 0-1 (use 0.0 to clear)")
                    return None

            # Update TP/SL price
            if tpsl_type == "tp":
                position.take_profit_price = price
            elif tpsl_type == "sl":
                position.stop_loss_price = price
            else:
                logger.error(f"❌ Invalid tpsl_type: {tpsl_type}")
                return None

            # ✅ NEW: Validate SL < TP if both are set (limit order logic)
            # Only validate when setting a price (not when clearing)
            if position.take_profit_price and position.stop_loss_price:
                if position.stop_loss_price >= position.take_profit_price:
                    logger.error(
                        f"❌ Invalid TP/SL configuration for position {position_id}: "
                        f"Stop Loss (${position.stop_loss_price:.4f}) must be < Take Profit (${position.take_profit_price:.4f})"
                    )
                    # Revert the change
                    if tpsl_type == "tp":
                        position.take_profit_price = None
                    elif tpsl_type == "sl":
                        position.stop_loss_price = None
                    return None

            position.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.refresh(position)

            if is_clear:
                logger.info(f"✅ Cleared {tpsl_type} for position {position_id}")
            else:
                logger.info(f"✅ Updated {tpsl_type} price ${price:.4f} for position {position_id}")
            return position

    except Exception as e:
        logger.error(f"❌ Error updating TP/SL for position {position_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def close_position(
    position_id: int,
    exit_price: Optional[float] = None
) -> Optional[Position]:
    """
    Close a position

    Args:
        position_id: Position ID
        exit_price: Exit price (optional, uses current_price if not provided)

    Returns:
        Closed Position object or None if error
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.id == position_id)
            )
            position = result.scalar_one_or_none()

            if not position:
                return None

            if position.status != "active":
                logger.warning(f"⚠️ Position {position_id} is not active")
                return position

            # Validate exit_price if provided
            if exit_price is not None:
                if not (0 <= exit_price <= 1):
                    raise ValueError(f"Invalid exit_price {exit_price}: Polymarket prices must be 0-1")

            # Use exit_price or current_price - NO fallback to entry_price
            if exit_price is not None:
                final_price = exit_price
            elif position.current_price is not None:
                final_price = position.current_price
            else:
                raise ValueError(f"Cannot close position {position_id}: no exit_price or current_price available")

            # Recalculate final P&L
            pnl_amount, pnl_percentage = calculate_pnl(
                position.entry_price,
                final_price,
                position.amount,
                position.outcome
            )

            position.status = "closed"
            position.amount = 0.0  # Set amount to 0 when closing (positions with amount=0 are filtered out)
            position.current_price = final_price
            position.pnl_amount = pnl_amount
            position.pnl_percentage = pnl_percentage
            position.closed_at = datetime.now(timezone.utc)
            position.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.refresh(position)

            # ✅ CRITICAL: Invalidate cache BEFORE checking positions for unsubscription
            # This ensures we get fresh data when checking if market should be unsubscribed
            try:
                from core.services.cache_manager import CacheManager
                cache_manager = CacheManager()
                await cache_manager.invalidate_pattern(f"api:positions:{position.user_id}")
                await cache_manager.delete(f"api:positions:market:{position.market_id}")
                logger.debug(f"✅ Cache invalidated for user {position.user_id} and market {position.market_id} after position close")
            except Exception as cache_error:
                logger.warning(f"⚠️ Cache invalidation failed (non-fatal): {cache_error}")

            # ✅ NOTIFY WebSocket Manager for unsubscription
            # ⚠️ CRITICAL: Always use API endpoint or Redis Pub/Sub in microservices architecture
            # Even if SKIP_DB=false, the API service doesn't have the streamer connected
            # The streamer is in the workers service, so we need to notify via API/Redis
            # ⚠️ NOTE: There's a potential race condition here - if a new position is created
            # between the commit() above and the position check in on_position_closed(),
            # we might unsubscribe incorrectly. This is mitigated by checking ALL positions
            # (not just this user's) in on_position_closed().
            try:
                logger.info(f"🚪 Attempting to unsubscribe from WebSocket for market {position.market_id} after position close")

                # Check if websocket_manager has streamer connected locally
                from core.services.websocket_manager import websocket_manager
                has_local_streamer = (
                    websocket_manager.streamer is not None and
                    websocket_manager.subscription_manager is not None
                )

                if has_local_streamer:
                    # Direct call when streamer is available locally (monolithic mode)
                    logger.debug("🚪 Using direct WebSocketManager call (streamer available locally)")
                    result = await websocket_manager.unsubscribe_user_from_market(
                        position.user_id, position.market_id
                    )
                    logger.info(f"✅ WebSocket unsubscription result for market {position.market_id}: {result}")
                else:
                    # Microservices mode: Use Redis Pub/Sub or API endpoint
                    # Try Redis Pub/Sub first (more direct), fallback to API endpoint
                    try:
                        from core.services.redis_pubsub import get_redis_pubsub_service
                        redis_pubsub = get_redis_pubsub_service()
                        if not redis_pubsub.is_connected:
                            await redis_pubsub.connect()

                        channel = f"websocket:unsubscribe:{position.user_id}:{position.market_id}"
                        message = {
                            "user_id": position.user_id,
                            "market_id": position.market_id
                        }

                        subscribers = await redis_pubsub.publish(channel, message)
                        logger.info(f"📤 Published unsubscribe request to Redis: {subscribers} subscribers for market {position.market_id}")
                        logger.info(f"✅ WebSocket unsubscription via Redis Pub/Sub for market {position.market_id}: success")
                    except Exception as redis_error:
                        logger.warning(f"⚠️ Redis Pub/Sub failed, trying API endpoint: {redis_error}")
                        # Fallback to API endpoint
                        try:
                            api_client = get_api_client()
                            result = await api_client.unsubscribe_websocket(
                                user_id=position.user_id,
                                market_id=position.market_id
                            )
                            if result and result.get('success'):
                                logger.info(f"✅ WebSocket unsubscription via API for market {position.market_id}: success")
                            else:
                                logger.warning(f"⚠️ WebSocket unsubscription via API failed: {result}")
                        except Exception as api_error:
                            logger.error(f"❌ Both Redis Pub/Sub and API endpoint failed: {api_error}")
            except Exception as ws_error:
                logger.error(f"❌ Failed to unsubscribe from WebSocket after position close: {ws_error}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Don't fail position closure if WebSocket notification fails

            logger.info(f"✅ Closed position {position_id}")
            return position

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"❌ Error closing position {position_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
