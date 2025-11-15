"""
Redis PubSub Service
Async Redis Pub/Sub for real-time messaging (separate from CacheManager)
"""
import asyncio
import json
import time
from typing import Callable, Optional, Dict, Any
from datetime import datetime, timezone

import redis.asyncio as redis
from redis.asyncio.client import PubSub

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class RedisPubSubService:
    """
    Redis Pub/Sub Service for real-time messaging
    Separate from CacheManager (separation of concerns)

    Features:
    - Async publish/subscribe
    - Auto-reconnect with exponential backoff
    - Pattern subscription support
    - Health check
    """

    def __init__(self):
        """Initialize Redis PubSub service"""
        self.redis_url = settings.redis.url
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[PubSub] = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 1.0  # Start with 1 second
        self.max_reconnect_delay = 60.0  # Max 60 seconds
        self._listening = False
        self._subscribers: Dict[str, Callable] = {}  # pattern -> callback

    async def connect(self) -> bool:
        """
        Connect to Redis

        Returns:
            True if connected successfully, False otherwise
        """
        try:
            if self.is_connected and self.redis_client:
                return True

            logger.info(f"🔌 Connecting to Redis PubSub: {self.redis_url[:30]}...")

            self.redis_client = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=None,  # No timeout for Pub/Sub (waits indefinitely)
                health_check_interval=30,
            )

            # Test connection
            await self.redis_client.ping()

            self.pubsub = self.redis_client.pubsub()
            self.is_connected = True
            self.reconnect_attempts = 0
            self.reconnect_delay = 1.0

            logger.info("✅ Redis PubSub connected successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis PubSub: {e}")
            self.is_connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis"""
        try:
            self._listening = False

            if self.pubsub:
                await self.pubsub.unsubscribe()
                await self.pubsub.close()
                self.pubsub = None

            if self.redis_client:
                await self.redis_client.close()
                self.redis_client = None

            self.is_connected = False
            logger.info("✅ Redis PubSub disconnected")

        except Exception as e:
            logger.error(f"❌ Error disconnecting Redis PubSub: {e}")

    async def publish(self, channel: str, message: Dict[str, Any]) -> int:
        """
        Publish message to Redis channel

        Args:
            channel: Redis channel name (e.g., "copy_trade:0xabc...")
            message: Message dictionary (will be JSON serialized)

        Returns:
            Number of subscribers that received the message
        """
        try:
            if not self.is_connected:
                if not await self.connect():
                    logger.warning(f"⚠️ Cannot publish to {channel}: not connected")
                    return 0

            # Serialize message to JSON
            message_json = json.dumps(message)

            # Publish
            subscribers = await self.redis_client.publish(channel, message_json)

            logger.debug(f"📤 Published to {channel}: {subscribers} subscribers")
            return subscribers

        except Exception as e:
            logger.error(f"❌ Error publishing to {channel}: {e}")
            # Try to reconnect
            await self._reconnect()
            return 0

    async def subscribe(
        self,
        pattern: str,
        callback: Callable[[str, str], None]
    ) -> None:
        """
        Subscribe to Redis channel pattern

        Args:
            pattern: Redis pattern (e.g., "copy_trade:*")
            callback: Async callback function(channel: str, data: str) -> None
        """
        try:
            if not self.is_connected:
                if not await self.connect():
                    logger.error(f"❌ Cannot subscribe to {pattern}: not connected")
                    return

            # Store callback
            self._subscribers[pattern] = callback

            # Subscribe to pattern
            await self.pubsub.psubscribe(pattern)
            logger.info(f"✅ Subscribed to pattern: {pattern}")

            # Start listening if not already started
            if not self._listening:
                asyncio.create_task(self._listen_loop())

        except Exception as e:
            logger.error(f"❌ Error subscribing to {pattern}: {e}")
            await self._reconnect()

    async def unsubscribe(self, pattern: str) -> None:
        """
        Unsubscribe from Redis channel pattern

        Args:
            pattern: Redis pattern to unsubscribe from
        """
        try:
            if self.pubsub and pattern in self._subscribers:
                await self.pubsub.punsubscribe(pattern)
                del self._subscribers[pattern]
                logger.info(f"✅ Unsubscribed from pattern: {pattern}")
        except Exception as e:
            logger.error(f"❌ Error unsubscribing from {pattern}: {e}")

    async def _listen_loop(self) -> None:
        """Main listening loop for Pub/Sub messages"""
        self._listening = True
        logger.info("🔄 Starting Redis PubSub listener loop")

        while self._listening:
            try:
                if not self.is_connected or not self.pubsub:
                    await asyncio.sleep(1)
                    continue

                # Wait for message (non-blocking with timeout)
                message = await asyncio.wait_for(
                    self.pubsub.get_message(timeout=1.0),
                    timeout=1.0
                )

                if message is None:
                    continue  # Timeout, continue loop

                # Handle message
                await self._handle_message(message)

            except asyncio.TimeoutError:
                # Normal timeout, continue
                continue
            except Exception as e:
                logger.error(f"❌ Error in listen loop: {e}")
                await asyncio.sleep(1)
                # Try to reconnect
                await self._reconnect()

        logger.info("🛑 Redis PubSub listener loop stopped")

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """Handle incoming Pub/Sub message"""
        try:
            msg_type = message.get('type')

            if msg_type == 'pmessage':
                # Pattern message
                pattern = message.get('pattern')
                channel = message.get('channel')
                data = message.get('data')

                if pattern in self._subscribers:
                    callback = self._subscribers[pattern]
                    try:
                        await callback(channel, data)
                    except Exception as e:
                        logger.error(f"❌ Error in subscriber callback for {pattern}: {e}")

            elif msg_type == 'psubscribe':
                pattern = message.get('pattern')
                logger.debug(f"✅ Pattern subscribed: {pattern}")

            elif msg_type == 'punsubscribe':
                pattern = message.get('pattern')
                logger.debug(f"✅ Pattern unsubscribed: {pattern}")

        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")

    async def _reconnect(self) -> None:
        """Reconnect to Redis with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"❌ Max reconnect attempts reached ({self.max_reconnect_attempts})")
            return

        self.reconnect_attempts += 1
        delay = min(
            self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)),
            self.max_reconnect_delay
        )

        logger.warning(f"🔄 Reconnecting to Redis (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}) in {delay:.1f}s")

        await asyncio.sleep(delay)

        # Disconnect old connection
        await self.disconnect()

        # Try to reconnect
        if await self.connect():
            # Re-subscribe to all patterns
            for pattern, callback in self._subscribers.items():
                try:
                    await self.pubsub.psubscribe(pattern)
                    logger.info(f"✅ Re-subscribed to pattern: {pattern}")
                except Exception as e:
                    logger.error(f"❌ Error re-subscribing to {pattern}: {e}")

    async def health_check(self) -> bool:
        """
        Check Redis PubSub health

        Returns:
            True if healthy, False otherwise
        """
        try:
            if not self.is_connected or not self.redis_client:
                return False

            await self.redis_client.ping()
            return True

        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        return {
            "is_connected": self.is_connected,
            "reconnect_attempts": self.reconnect_attempts,
            "subscribers_count": len(self._subscribers),
            "subscribed_patterns": list(self._subscribers.keys()),
            "listening": self._listening,
        }

    async def stop(self) -> None:
        """Stop the service gracefully"""
        logger.info("🛑 Stopping Redis PubSub service")
        self._listening = False
        await self.disconnect()


# Global instance
_redis_pubsub_service: Optional[RedisPubSubService] = None


def get_redis_pubsub_service() -> RedisPubSubService:
    """Get global Redis PubSub service instance"""
    global _redis_pubsub_service
    if _redis_pubsub_service is None:
        _redis_pubsub_service = RedisPubSubService()
    return _redis_pubsub_service

