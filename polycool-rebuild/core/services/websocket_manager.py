"""
WebSocket Manager - Centralisé WebSocket Management Service
Single source of truth for all WebSocket operations (Phase 7)
"""
from typing import List, Optional, Set
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from data_ingestion.streamer.streamer import StreamerService

logger = get_logger(__name__)


class WebSocketManager:
    """
    WebSocket Manager - Centralisé management des connexions WebSocket
    Single source of truth pour toutes les subscriptions

    Features:
    - Subscription management centralisé
    - User-market tracking
    - Auto-subscribe/unsubscribe
    - Health monitoring
    """

    def __init__(self, streamer_service: Optional[StreamerService] = None):
        """
        Initialize WebSocket Manager

        Args:
            streamer_service: StreamerService instance (will be injected by app)
        """
        self.streamer = streamer_service
        self.subscription_manager = streamer_service.subscription_manager if streamer_service else None

        # Stats
        self.active_subscriptions: Set[str] = set()  # user_id:market_id format
        self.total_subscriptions_created = 0
        self.total_subscriptions_removed = 0

    def set_streamer_service(self, streamer_service: StreamerService):
        """Set streamer service (for dependency injection)"""
        self.streamer = streamer_service
        self.subscription_manager = streamer_service.subscription_manager
        logger.info("✅ WebSocketManager connected to StreamerService")

    async def subscribe_user_to_market(self, user_id: int, market_id: str) -> bool:
        """
        Subscribe user to market WebSocket updates
        Called when user creates position or executes trade

        Args:
            user_id: User ID
            market_id: Market ID

        Returns:
            True if subscription successful, False otherwise
        """
        if not self.streamer or not self.subscription_manager:
            logger.warning("⚠️ WebSocketManager not connected to streamer")
            logger.warning(f"   streamer={self.streamer is not None}, subscription_manager={self.subscription_manager is not None}")
            logger.warning(f"   This usually means STREAMER_ENABLED=false or streamer not started in main.py")
            return False

        try:
            subscription_key = f"{user_id}:{market_id}"

            # Avoid duplicate subscriptions
            if subscription_key in self.active_subscriptions:
                logger.debug(f"📡 Subscription already exists: {subscription_key}")
                return True

            # Subscribe via streamer (which will also start WebSocket if needed)
            await self.streamer.on_trade_executed(user_id, market_id)

            # Track subscription
            self.active_subscriptions.add(subscription_key)
            self.total_subscriptions_created += 1

            logger.info(f"📡 User {user_id} subscribed to market {market_id}")
            return True

        except Exception as e:
            logger.error(f"⚠️ Error subscribing user {user_id} to market {market_id}: {e}")
            return False

    async def on_trade_executed(self, user_id: int, market_id: str) -> bool:
        """
        Notify WebSocket manager that a trade was executed
        This will trigger auto-subscription to the market

        Args:
            user_id: User ID who executed the trade
            market_id: Market ID where trade was executed

        Returns:
            True if subscription successful, False otherwise
        """
        return await self.subscribe_user_to_market(user_id, market_id)

    async def unsubscribe_user_from_market(self, user_id: int, market_id: str) -> bool:
        """
        Unsubscribe user from market WebSocket updates
        Called when user closes position

        Args:
            user_id: User ID
            market_id: Market ID

        Returns:
            True if unsubscription successful, False otherwise
        """
        subscription_key = f"{user_id}:{market_id}"

        # Check if subscription exists in tracking
        subscription_exists = subscription_key in self.active_subscriptions

        if not self.streamer or not self.subscription_manager:
            logger.warning(
                f"⚠️ WebSocketManager not connected to streamer - "
                f"streamer={self.streamer is not None}, "
                f"subscription_manager={self.subscription_manager is not None}"
            )
            # If subscription doesn't exist in tracking, consider it already unsubscribed
            if not subscription_exists:
                logger.info(f"🚪 Subscription {subscription_key} not in tracking and streamer not connected - considered unsubscribed")
                return True
            return False

        try:
            # Remove from tracking first (idempotent operation)
            if subscription_exists:
                self.active_subscriptions.discard(subscription_key)
                self.total_subscriptions_removed += 1
                logger.debug(f"🚪 Removed subscription {subscription_key} from tracking")

            # Always try to unsubscribe via subscription manager
            # This handles the case where subscription exists at WebSocket level but not in tracking
            # on_position_closed() already checks positions and updates source, so no need for double check
            await self.subscription_manager.on_position_closed(user_id, market_id)

            # Note: _ensure_market_source_updated() was removed to avoid redundant checks
            # on_position_closed() already handles source update correctly

            logger.info(f"🚪 User {user_id} unsubscribed from market {market_id}")
            return True

        except Exception as e:
            logger.error(f"⚠️ Error unsubscribing user {user_id} from market {market_id}: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return False

    async def _ensure_market_source_updated(self, user_id: int, market_id: str) -> None:
        """
        Ensure market source is updated to 'poll' if no active positions remain
        This is a safety check to ensure source is updated even if on_position_closed doesn't do it

        Args:
            user_id: User ID who unsubscribed
            market_id: Market ID
        """
        try:
            import os
            SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"

            # Check if there are any active positions on this market
            active_count = 0

            if SKIP_DB:
                try:
                    from core.services.api_client import get_api_client
                    api_client = get_api_client()
                    positions_data = await api_client.get_market_positions(market_id, use_cache=False)
                    if positions_data:
                        positions_list = positions_data.get('positions', [])
                        active_positions = [p for p in positions_list
                                          if p.get('status') == 'active'
                                          and p.get('amount', 0) > 0]
                        active_count = len(active_positions)
                except Exception as e:
                    logger.debug(f"Could not check active positions via API: {e}")
                    return  # Don't update if we can't check
            else:
                try:
                    from core.database.connection import get_db
                    from core.database.models import Position
                    from sqlalchemy import select, func
                    async with get_db() as db:
                        count = await db.execute(
                            select(func.count(Position.id))
                            .where(
                                Position.market_id == market_id,
                                Position.status == "active"
                            )
                        )
                        active_count = count.scalar() or 0
                except Exception as e:
                    logger.debug(f"Could not check active positions via DB: {e}")
                    return  # Don't update if we can't check

            # If no active positions, ensure source is 'poll'
            if active_count == 0:
                logger.debug(f"🔍 No active positions on market {market_id}, ensuring source is 'poll'")
                try:
                    if not SKIP_DB:
                        from core.database.connection import get_db
                        from core.database.models import Market
                        from sqlalchemy import update
                        async with get_db() as db:
                            result = await db.execute(
                                update(Market)
                                .where(Market.id == market_id)
                                .values(source='poll')
                            )
                            await db.commit()
                            if result.rowcount > 0:
                                logger.info(f"✅ Ensured market {market_id} source is 'poll' (no active positions)")
                    else:
                        # Use API
                        from core.services.api_client import get_api_client
                        api_client = get_api_client()
                        response = await api_client.client.put(
                            f"{api_client.base_url}/markets/{market_id}",
                            json={"source": "poll"},
                            timeout=5.0
                        )
                        if response.status_code == 200:
                            logger.info(f"✅ Ensured market {market_id} source is 'poll' via API (no active positions)")
                except Exception as e:
                    logger.debug(f"Could not update market source: {e}")
        except Exception as e:
            logger.debug(f"Error in _ensure_market_source_updated: {e}")

    async def get_user_subscriptions(self, user_id: int) -> List[str]:
        """
        Get all markets user is subscribed to

        Args:
            user_id: User ID

        Returns:
            List of market IDs user is subscribed to
        """
        user_subscriptions = [
            sub.split(":")[1] for sub in self.active_subscriptions
            if sub.startswith(f"{user_id}:")
        ]
        return user_subscriptions

    async def get_market_subscribers(self, market_id: str) -> List[int]:
        """
        Get all users subscribed to a market

        Args:
            market_id: Market ID

        Returns:
            List of user IDs subscribed to the market
        """
        market_subscribers = [
            int(sub.split(":")[0]) for sub in self.active_subscriptions
            if sub.endswith(f":{market_id}")
        ]
        return market_subscribers

    async def resync_user_subscriptions(self, user_id: int) -> bool:
        """
        Resync user subscriptions based on active positions
        Useful after reconnection or state recovery

        Args:
            user_id: User ID

        Returns:
            True if resync successful
        """
        try:
            from core.services.position.position_service import PositionService
            position_service = PositionService()

            # Get active positions for user
            active_positions = await position_service.get_active_positions(user_id)
            active_market_ids = list(set(pos.market_id for pos in active_positions))

            # Get current subscriptions
            current_subscriptions = await self.get_user_subscriptions(user_id)

            # Subscribe to new markets
            for market_id in active_market_ids:
                if market_id not in current_subscriptions:
                    await self.subscribe_user_to_market(user_id, market_id)

            # Unsubscribe from markets without positions
            for market_id in current_subscriptions:
                if market_id not in active_market_ids:
                    await self.unsubscribe_user_from_market(user_id, market_id)

            logger.info(f"🔄 Resynced subscriptions for user {user_id}: {len(active_market_ids)} active markets")
            return True

        except Exception as e:
            logger.error(f"⚠️ Error resyncing subscriptions for user {user_id}: {e}")
            return False

    async def health_check(self) -> dict:
        """
        Health check for WebSocket manager

        Returns:
            Health status dict
        """
        health = {
            "websocket_manager": "healthy",
            "streamer_connected": self.streamer is not None,
            "subscription_manager_connected": self.subscription_manager is not None,
            "active_subscriptions": len(self.active_subscriptions),
            "total_subscriptions_created": self.total_subscriptions_created,
            "total_subscriptions_removed": self.total_subscriptions_removed,
        }

        # Check streamer health if connected
        if self.streamer:
            try:
                streamer_stats = self.streamer.get_stats()
                health["streamer_stats"] = streamer_stats
                health["websocket_connected"] = streamer_stats.get("websocket", {}).get("connected", False)
            except Exception as e:
                health["streamer_error"] = str(e)
                health["websocket_manager"] = "degraded"

        return health

    def get_stats(self) -> dict:
        """Get WebSocket manager statistics"""
        return {
            "active_subscriptions": len(self.active_subscriptions),
            "total_subscriptions_created": self.total_subscriptions_created,
            "total_subscriptions_removed": self.total_subscriptions_removed,
            "streamer_connected": self.streamer is not None,
            "subscription_manager_connected": self.subscription_manager is not None,
        }


# Singleton instance
websocket_manager = WebSocketManager()
