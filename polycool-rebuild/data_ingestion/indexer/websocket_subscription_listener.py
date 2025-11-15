"""
WebSocket Subscription Listener
Listens to Redis PubSub for WebSocket subscription requests from API service
and executes them via the WebSocketManager (which is connected to StreamerService)
"""
import json
from typing import Dict, Any, Optional

from core.services.redis_pubsub import get_redis_pubsub_service
from core.services.websocket_manager import websocket_manager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class WebSocketSubscriptionListener:
    """
    Listens to Redis PubSub for WebSocket subscription/unsubscription requests
    - Subscribes to websocket:subscribe:* and websocket:unsubscribe:* patterns
    - Executes subscriptions via WebSocketManager (which has access to StreamerService)
    - Used for cross-service communication: API service → Workers service
    """

    def __init__(self):
        """Initialize WebSocket Subscription Listener"""
        self.pubsub_service = get_redis_pubsub_service()
        self.running = False

        # Metrics
        self._metrics = {
            'total_subscribe_requests': 0,
            'successful_subscriptions': 0,
            'failed_subscriptions': 0,
            'total_unsubscribe_requests': 0,
            'successful_unsubscriptions': 0,
            'failed_unsubscriptions': 0,
        }

    async def start(self) -> None:
        """Start listening to Redis PubSub"""
        try:
            if self.running:
                logger.warning("⚠️ WebSocket Subscription Listener already running")
                return

            # Connect to Redis
            if not await self.pubsub_service.health_check():
                await self.pubsub_service.connect()

            # Subscribe to websocket:subscribe:* pattern
            await self.pubsub_service.subscribe(
                pattern="websocket:subscribe:*",
                callback=self._handle_subscribe_message
            )

            # Subscribe to websocket:unsubscribe:* pattern
            await self.pubsub_service.subscribe(
                pattern="websocket:unsubscribe:*",
                callback=self._handle_unsubscribe_message
            )

            self.running = True
            logger.info("✅ WebSocket Subscription Listener started")

        except Exception as e:
            logger.error(f"❌ Failed to start WebSocket Subscription Listener: {e}")
            self.running = False

    async def stop(self) -> None:
        """Stop listening"""
        try:
            self.running = False
            await self.pubsub_service.unsubscribe("websocket:subscribe:*")
            await self.pubsub_service.unsubscribe("websocket:unsubscribe:*")
            logger.info("✅ WebSocket Subscription Listener stopped")
        except Exception as e:
            logger.error(f"❌ Error stopping WebSocket Subscription Listener: {e}")

    async def _handle_subscribe_message(self, channel: str, data: str) -> None:
        """
        Handle incoming subscribe message from Redis PubSub

        Args:
            channel: Redis channel (e.g., "websocket:subscribe:6500527972:570362")
            data: JSON string with subscription data
        """
        try:
            # Parse message
            subscription_data = json.loads(data)
            user_id = subscription_data.get('user_id')
            market_id = subscription_data.get('market_id')

            if not user_id or not market_id:
                logger.warning(f"⚠️ Invalid subscribe message: missing user_id or market_id")
                return

            self._metrics['total_subscribe_requests'] += 1

            logger.info(
                f"📡 [Redis] Subscribe request: user={user_id}, market={market_id}"
            )

            # Execute subscription via WebSocketManager
            success = await websocket_manager.subscribe_user_to_market(
                user_id=user_id,
                market_id=market_id
            )

            if success:
                self._metrics['successful_subscriptions'] += 1
                logger.info(
                    f"✅ [Redis] Successfully subscribed user {user_id} to market {market_id}"
                )
            else:
                self._metrics['failed_subscriptions'] += 1
                logger.warning(
                    f"⚠️ [Redis] Failed to subscribe user {user_id} to market {market_id}"
                )

        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in subscribe message: {e}")
        except Exception as e:
            logger.error(f"❌ Error handling subscribe message: {e}", exc_info=True)

    async def _handle_unsubscribe_message(self, channel: str, data: str) -> None:
        """
        Handle incoming unsubscribe message from Redis PubSub

        Args:
            channel: Redis channel (e.g., "websocket:unsubscribe:6500527972:570362")
            data: JSON string with unsubscription data
        """
        try:
            # Parse message
            unsubscription_data = json.loads(data)
            user_id = unsubscription_data.get('user_id')
            market_id = unsubscription_data.get('market_id')

            if not user_id or not market_id:
                logger.warning(f"⚠️ Invalid unsubscribe message: missing user_id or market_id")
                return

            self._metrics['total_unsubscribe_requests'] += 1

            logger.info(
                f"🚪 [Redis] Unsubscribe request: user={user_id}, market={market_id}"
            )

            # Execute unsubscription via WebSocketManager
            success = await websocket_manager.unsubscribe_user_from_market(
                user_id=user_id,
                market_id=market_id
            )

            if success:
                self._metrics['successful_unsubscriptions'] += 1
                logger.info(
                    f"✅ [Redis] Successfully unsubscribed user {user_id} from market {market_id}"
                )
            else:
                self._metrics['failed_unsubscriptions'] += 1
                logger.warning(
                    f"⚠️ [Redis] Failed to unsubscribe user {user_id} from market {market_id}"
                )

        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in unsubscribe message: {e}")
        except Exception as e:
            logger.error(f"❌ Error handling unsubscribe message: {e}", exc_info=True)

    def get_stats(self) -> Dict[str, Any]:
        """Get listener statistics"""
        return {
            "running": self.running,
            "metrics": self._metrics.copy(),
        }


# Global instance
_websocket_subscription_listener: Optional[WebSocketSubscriptionListener] = None


def get_websocket_subscription_listener() -> WebSocketSubscriptionListener:
    """Get global WebSocket Subscription Listener instance"""
    global _websocket_subscription_listener
    if _websocket_subscription_listener is None:
        _websocket_subscription_listener = WebSocketSubscriptionListener()
    return _websocket_subscription_listener
