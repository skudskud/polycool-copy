"""
Redis Publisher Service for DipDup Indexer
Publishes trade events to Redis channels for real-time notifications.

Channels:
- clob.trade.{market_id} - Market-level trade events
- copy_trade:{wallet_address} - Wallet-level events for copy trading

Features:
- Non-blocking (doesn't fail indexer if Redis is down)
- Auto-reconnect with exponential backoff
- Singleton pattern (reuse connection)
- JSON message serialization
"""

import logging
import json
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import redis.asyncio as redis

from ..config import settings, validate_experimental_subsquid

logger = logging.getLogger(__name__)


class RedisPublisher:
    """
    Redis Publisher for trade events

    Publishes to two channel types:
    1. Market-level: clob.trade.{market_id} (for market updates)
    2. Wallet-level: copy_trade:{wallet_address} (for copy trading)
    """

    def __init__(self):
        """Initialize Redis publisher"""
        self.enabled = getattr(settings, 'REDIS_PUBLISHER_ENABLED', True)
        self.redis_url = settings.REDIS_URL
        self.redis_client: Optional[redis.Redis] = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 1.0  # Start with 1 second
        self.max_reconnect_delay = 30.0  # Max 30 seconds
        self.publish_count = 0
        self.publish_errors = 0
        self.last_error: Optional[str] = None

    async def connect(self) -> bool:
        """
        Connect to Redis (non-blocking, retries on failure)

        Returns:
            True if connected, False otherwise
        """
        if not self.enabled:
            logger.debug("⚠️ Redis publisher disabled (REDIS_PUBLISHER_ENABLED=false)")
            return False

        if self.is_connected and self.redis_client:
            return True

        try:
            self.redis_client = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                retry_on_timeout=True,
            )

            # Test connection
            await self.redis_client.ping()
            self.is_connected = True
            self.reconnect_attempts = 0
            logger.info("✅ Redis publisher connected")
            return True

        except Exception as e:
            self.is_connected = False
            self.last_error = str(e)
            logger.warning(f"⚠️ Redis publisher connection failed: {e}")
            return False

    async def _ensure_connected(self) -> bool:
        """Ensure Redis connection, retry if needed"""
        if self.is_connected and self.redis_client:
            try:
                await self.redis_client.ping()
                return True
            except Exception:
                self.is_connected = False

        # Try to reconnect
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            delay = min(
                self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)),
                self.max_reconnect_delay
            )
            logger.debug(f"🔄 Redis publisher reconnecting (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})...")
            await asyncio.sleep(delay)
            return await self.connect()

        return False

    async def publish(
        self,
        channel: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        Publish message to Redis channel (non-blocking)

        Args:
            channel: Redis channel name (e.g., "clob.trade.248905")
            message: Message dictionary (will be JSON serialized)

        Returns:
            True if published successfully, False otherwise
        """
        if not self.enabled:
            return False

        try:
            # Ensure connection
            if not await self._ensure_connected():
                self.publish_errors += 1
                logger.debug(f"⚠️ Redis publisher not connected, skipping publish to {channel}")
                return False

            # Serialize message
            message_json = json.dumps(message, default=str)

            # Publish
            subscribers = await self.redis_client.publish(channel, message_json)
            self.publish_count += 1

            if subscribers > 0:
                logger.debug(
                    f"📤 Published to {channel}: {subscribers} subscribers "
                    f"(total: {self.publish_count}, errors: {self.publish_errors})"
                )
            else:
                logger.debug(f"📤 Published to {channel} (no subscribers)")

            return True

        except Exception as e:
            self.publish_errors += 1
            self.last_error = str(e)
            # Non-blocking: log warning but don't raise
            logger.warning(f"⚠️ Redis publish failed (non-blocking) to {channel}: {e}")
            self.is_connected = False  # Mark as disconnected for next retry
            return False

    async def publish_trade(
        self,
        market_id: str,
        tx_id: str,
        outcome: int,
        tx_type: str,
        amount: float,
        price: Optional[float],
        tx_hash: str,
        timestamp: datetime,
    ) -> bool:
        """
        Publish trade event to market-level channel

        Channel: clob.trade.{market_id}

        Args:
            market_id: Market ID (numeric string)
            tx_id: Transaction ID (unique)
            outcome: 0=NO, 1=YES
            tx_type: "BUY" or "SELL"
            amount: Token amount
            price: Fill price (None initially)
            tx_hash: Blockchain transaction hash
            timestamp: Event timestamp

        Returns:
            True if published successfully
        """
        channel = f"clob.trade.{market_id}"

        message = {
            "tx_id": tx_id,
            "market_id": market_id,
            "outcome": outcome,
            "tx_type": tx_type,
            "amount": amount,
            "price": price,
            "tx_hash": tx_hash,
            "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
            "source": "indexer",  # Distinguish from CLOB WebSocket
        }

        return await self.publish(channel, message)

    async def publish_copy_trade(
        self,
        user_address: str,
        market_id: str,
        token_id: int,
        outcome: int,
        tx_type: str,
        amount: float,
        price: Optional[float],
        tx_hash: str,
        timestamp: datetime,
    ) -> bool:
        """
        Publish trade event to wallet-level channel for copy trading

        Channel: copy_trade:{wallet_address}

        Args:
            user_address: Trader's wallet address (0x...)
            market_id: Market ID (numeric string)
            token_id: Token ID (for position tracking)
            outcome: 0=NO, 1=YES
            tx_type: "BUY" or "SELL"
            amount: Token amount
            price: Fill price (None initially)
            tx_hash: Blockchain transaction hash
            timestamp: Event timestamp

        Returns:
            True if published successfully
        """
        channel = f"copy_trade:{user_address.lower()}"

        message = {
            "tx_id": f"{tx_hash}_{token_id}",  # Unique ID
            "user_address": user_address.lower(),
            "position_id": token_id,  # For position tracking
            "market_id": market_id,
            "outcome": outcome,
            "tx_type": tx_type,
            "amount": amount,
            "price": price,
            "taking_amount": None,  # Will be enriched later
            "tx_hash": tx_hash,
            "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
            "address_type": "onchain",  # vs "bot_user" or "external_leader"
        }

        return await self.publish(channel, message)

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            try:
                await self.redis_client.close()
                logger.info("✅ Redis publisher disconnected")
            except Exception as e:
                logger.warning(f"⚠️ Error disconnecting Redis publisher: {e}")
            finally:
                self.redis_client = None
                self.is_connected = False

    def get_stats(self) -> Dict[str, Any]:
        """Get publisher statistics"""
        return {
            "enabled": self.enabled,
            "connected": self.is_connected,
            "publish_count": self.publish_count,
            "publish_errors": self.publish_errors,
            "reconnect_attempts": self.reconnect_attempts,
            "last_error": self.last_error,
        }


# Global publisher instance (singleton)
_publisher_instance: Optional[RedisPublisher] = None


async def get_redis_publisher() -> RedisPublisher:
    """
    Get or create global Redis publisher instance

    Returns:
        RedisPublisher instance
    """
    global _publisher_instance

    if _publisher_instance is None:
        _publisher_instance = RedisPublisher()
        # Try to connect immediately (non-blocking)
        await _publisher_instance.connect()

    return _publisher_instance


async def close_redis_publisher():
    """Close global Redis publisher instance"""
    global _publisher_instance

    if _publisher_instance:
        await _publisher_instance.disconnect()
        _publisher_instance = None
