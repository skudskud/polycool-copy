"""
WebSocket API Routes
Endpoints for WebSocket subscription management
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.services.websocket_manager import websocket_manager
from core.services.redis_pubsub import get_redis_pubsub_service
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class SubscribeRequest(BaseModel):
    """Request model for subscribing to a market"""
    user_id: int
    market_id: str


class UnsubscribeRequest(BaseModel):
    """Request model for unsubscribing from a market"""
    user_id: int
    market_id: str


@router.post("/subscribe", response_model=dict)
async def subscribe_to_market(request: SubscribeRequest):
    """
    Subscribe user to market WebSocket updates

    This endpoint triggers WebSocket subscription for a specific market.
    Called automatically after trade execution, but can also be called manually.

    In multi-service deployments (API + Workers), this publishes to Redis Pub/Sub
    and the Workers service handles the subscription via WebSocketManager.

    Args:
        request: Subscribe request with user_id and market_id

    Returns:
        Subscription result with success status
    """
    try:
        logger.info(f"📡 [API] Subscribe request: user={request.user_id}, market={request.market_id}")

        # Check if WebSocketManager is connected locally (monolithic mode)
        if websocket_manager.streamer is not None and websocket_manager.subscription_manager is not None:
            # Direct call (monolithic mode or API has streamer)
            logger.debug("📡 [API] Using direct WebSocketManager call (streamer available locally)")
            success = await websocket_manager.subscribe_user_to_market(
                user_id=request.user_id,
                market_id=request.market_id
            )
        else:
            # Multi-service mode: publish to Redis Pub/Sub
            logger.debug("📡 [API] Publishing to Redis Pub/Sub (multi-service mode)")
            try:
                redis_pubsub = get_redis_pubsub_service()
                if not redis_pubsub.is_connected:
                    await redis_pubsub.connect()

                channel = f"websocket:subscribe:{request.user_id}:{request.market_id}"
                message = {
                    "user_id": request.user_id,
                    "market_id": request.market_id
                }

                subscribers = await redis_pubsub.publish(channel, message)
                logger.info(f"📤 [API] Published subscribe request to Redis: {subscribers} subscribers")

                # Assume success if published (workers service will handle it)
                # In production, workers service should be listening
                success = subscribers > 0 or settings.data_ingestion.streamer_enabled

            except Exception as redis_error:
                logger.error(f"❌ [API] Failed to publish to Redis: {redis_error}")
                success = False

        if success:
            logger.info(f"✅ [API] Successfully subscribed user {request.user_id} to market {request.market_id}")
            return {
                "success": True,
                "message": f"Subscribed to market {request.market_id}",
                "user_id": request.user_id,
                "market_id": request.market_id
            }
        else:
            logger.warning(f"⚠️ [API] Failed to subscribe user {request.user_id} to market {request.market_id}")
            return {
                "success": False,
                "message": "Subscription failed - WebSocket manager may not be connected or Redis Pub/Sub unavailable",
                "user_id": request.user_id,
                "market_id": request.market_id
            }

    except Exception as e:
        logger.error(f"❌ [API] Error subscribing to market: {e}")
        raise HTTPException(status_code=500, detail=f"Error subscribing to market: {str(e)}")


@router.post("/unsubscribe", response_model=dict)
async def unsubscribe_from_market(request: UnsubscribeRequest):
    """
    Unsubscribe user from market WebSocket updates

    This endpoint triggers WebSocket unsubscription for a specific market.
    Called automatically when position is closed, but can also be called manually.

    In multi-service deployments (API + Workers), this publishes to Redis Pub/Sub
    and the Workers service handles the unsubscription via WebSocketManager.

    Args:
        request: Unsubscribe request with user_id and market_id

    Returns:
        Unsubscription result with success status
    """
    try:
        logger.info(f"🚪 [API] Unsubscribe request: user={request.user_id}, market={request.market_id}")

        # Check if WebSocketManager is connected locally (monolithic mode)
        if websocket_manager.streamer is not None and websocket_manager.subscription_manager is not None:
            # Direct call (monolithic mode or API has streamer)
            logger.debug("🚪 [API] Using direct WebSocketManager call (streamer available locally)")
            success = await websocket_manager.unsubscribe_user_from_market(
                user_id=request.user_id,
                market_id=request.market_id
            )
        else:
            # Multi-service mode: ALWAYS publish to Redis Pub/Sub
            # Even if subscription is not in local tracking, we need to notify workers service
            logger.debug("🚪 [API] Publishing to Redis Pub/Sub (multi-service mode)")
            try:
                redis_pubsub = get_redis_pubsub_service()
                if not redis_pubsub.is_connected:
                    await redis_pubsub.connect()

                channel = f"websocket:unsubscribe:{request.user_id}:{request.market_id}"
                message = {
                    "user_id": request.user_id,
                    "market_id": request.market_id
                }

                subscribers = await redis_pubsub.publish(channel, message)
                logger.info(f"📤 [API] Published unsubscribe request to Redis: {subscribers} subscribers")

                # Always consider success if published (workers service will handle actual unsubscription)
                # Even if subscribers=0, the message is queued in Redis
                success = True

            except Exception as redis_error:
                logger.error(f"❌ [API] Failed to publish to Redis: {redis_error}")
                success = False

        if success:
            logger.info(f"✅ [API] Successfully unsubscribed user {request.user_id} from market {request.market_id}")
            return {
                "success": True,
                "message": f"Unsubscribed from market {request.market_id}",
                "user_id": request.user_id,
                "market_id": request.market_id
            }
        else:
            # Get more detailed error info
            error_details = {
                "streamer_connected": websocket_manager.streamer is not None,
                "subscription_manager_connected": websocket_manager.subscription_manager is not None,
            }
            logger.warning(
                f"⚠️ [API] Failed to unsubscribe user {request.user_id} from market {request.market_id}. "
                f"Details: {error_details}"
            )
            return {
                "success": False,
                "message": "Unsubscription failed - WebSocket manager may not be connected or Redis Pub/Sub unavailable",
                "user_id": request.user_id,
                "market_id": request.market_id,
                "error_details": error_details
            }

    except Exception as e:
        logger.error(f"❌ [API] Error unsubscribing from market: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error unsubscribing from market: {str(e)}")


@router.get("/subscriptions/{user_id}", response_model=dict)
async def get_user_subscriptions(user_id: int):
    """
    Get all markets a user is subscribed to

    Args:
        user_id: User ID

    Returns:
        List of market IDs user is subscribed to
    """
    try:
        market_ids = await websocket_manager.get_user_subscriptions(user_id)

        return {
            "user_id": user_id,
            "subscriptions": market_ids,
            "count": len(market_ids)
        }

    except Exception as e:
        logger.error(f"❌ [API] Error getting user subscriptions: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user subscriptions: {str(e)}")


@router.post("/cleanup", response_model=dict)
async def cleanup_websocket_subscriptions():
    """
    Cleanup all WebSocket subscriptions that have no active positions

    This endpoint:
    1. Finds all markets with source='ws' that have no active positions
    2. Changes their source to 'poll'
    3. Optionally cleans up WebSocketManager subscriptions

    Can be called manually for debugging or scheduled periodically.

    Returns:
        Cleanup results with counts and details
    """
    try:
        logger.info("🧹 [API] Starting WebSocket subscriptions cleanup...")

        from sqlalchemy import select, update, func
        from core.database.connection import get_db
        from core.database.models import Market, Position

        async with get_db() as db:
            # Find all markets with source='ws' and check their active positions
            result = await db.execute(
                select(
                    Market.id,
                    Market.title,
                    func.count(Position.id).filter(
                        Position.status == 'active',
                        Position.amount > 0
                    ).label('active_positions')
                )
                .outerjoin(Position, Market.id == Position.market_id)
                .where(Market.source == 'ws')
                .group_by(Market.id, Market.title)
            )
            ws_markets = result.all()

            logger.info(f"🔍 [API] Found {len(ws_markets)} markets with source='ws'")

            if not ws_markets:
                logger.info("✅ [API] No markets with source='ws' to clean up")
                return {
                    "success": True,
                    "cleaned_count": 0,
                    "kept_count": 0,
                    "total_checked": 0,
                    "markets_cleaned": []
                }

            cleaned_count = 0
            kept_count = 0
            markets_cleaned = []

            for market_id, market_title, active_positions in ws_markets:
                if active_positions == 0:
                    # No active positions - change source to 'poll'
                    await db.execute(
                        update(Market)
                        .where(Market.id == market_id)
                        .values(source='poll')
                    )
                    cleaned_count += 1
                    markets_cleaned.append({
                        "market_id": market_id,
                        "title": market_title[:50] if market_title else "Unknown"
                    })
                    logger.info(f"🧹 [API] Cleaned market {market_id} ({market_title[:50] if market_title else 'Unknown'}...): {active_positions} active positions")
                else:
                    kept_count += 1
                    logger.debug(f"✅ [API] Kept market {market_id} ({market_title[:50] if market_title else 'Unknown'}...): {active_positions} active positions")

            await db.commit()

            # Also cleanup WebSocketManager subscriptions if available
            ws_manager_cleaned = 0
            try:
                if websocket_manager.active_subscriptions:
                    # Get all active positions from DB
                    positions_result = await db.execute(
                        select(Position.user_id, Position.market_id)
                        .where(Position.status == 'active', Position.amount > 0)
                        .distinct()
                    )
                    active_positions_set = {(row[0], row[1]) for row in positions_result.fetchall()}

                    # Check each subscription
                    subscriptions_to_remove = []
                    for subscription_key in list(websocket_manager.active_subscriptions):
                        try:
                            user_id_str, market_id = subscription_key.split(":", 1)
                            user_id = int(user_id_str)

                            # Check if there's an active position for this user+market
                            if (user_id, market_id) not in active_positions_set:
                                subscriptions_to_remove.append(subscription_key)
                        except ValueError:
                            logger.warning(f"⚠️ [API] Invalid subscription key format: {subscription_key}")
                            continue

                    # Remove subscriptions without active positions
                    for subscription_key in subscriptions_to_remove:
                        websocket_manager.active_subscriptions.discard(subscription_key)
                        ws_manager_cleaned += 1
                        logger.debug(f"🧹 [API] Removed subscription {subscription_key} from WebSocketManager")
            except Exception as ws_error:
                logger.warning(f"⚠️ [API] WebSocketManager cleanup skipped: {ws_error}")

            logger.info(f"✅ [API] Cleanup complete:")
            logger.info(f"   • Markets cleaned (changed to 'poll'): {cleaned_count}")
            logger.info(f"   • Markets kept (still 'ws'): {kept_count}")
            logger.info(f"   • WebSocketManager subscriptions removed: {ws_manager_cleaned}")
            logger.info(f"   • Total checked: {len(ws_markets)}")

            return {
                "success": True,
                "cleaned_count": cleaned_count,
                "kept_count": kept_count,
                "total_checked": len(ws_markets),
                "markets_cleaned": markets_cleaned,
                "websocket_manager_cleaned": ws_manager_cleaned
            }

    except Exception as e:
        logger.error(f"❌ [API] Error during cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error during cleanup: {str(e)}")
