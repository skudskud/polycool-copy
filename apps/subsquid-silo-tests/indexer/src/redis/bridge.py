"""
Redis Pub/Sub Bridge Service
Subscribes to Redis channels (market.status.*, clob.trade.*, clob.orderbook.*).
For each message, POSTs to webhook worker endpoint for processing.
Enables event propagation: Redis → Webhook → Database
"""

import logging
import asyncio
import json
import httpx
from datetime import datetime, timezone
from typing import Optional, Set
import redis.asyncio as redis

from ..config import settings, validate_experimental_subsquid

logger = logging.getLogger(__name__)


class RedisBridge:
    """Redis Pub/Sub bridge service"""

    def __init__(self):
        self.enabled = settings.REDIS_BRIDGE_ENABLED
        self.redis_url = settings.REDIS_URL
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub = None
        self.webhook_url = settings.REDIS_BRIDGE_WEBHOOK_URL
        # Copy trade webhook URL (defaults to same host with /wh/copy_trade)
        self.copy_trade_webhook_url = (
            settings.REDIS_BRIDGE_COPY_TRADE_WEBHOOK_URL
            or self.webhook_url.replace("/wh/market", "/wh/copy_trade")
        )
        self.http_client: Optional[httpx.AsyncClient] = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 10
        self.message_count = 0
        self.success_count = 0
        self.error_count = 0
        self.channels_subscribed: Set[str] = set()

        # Channel patterns to subscribe to
        self.channel_patterns = [
            settings.REDIS_PREFIX_MARKET_STATUS,  # "market.status.*"
            settings.REDIS_PREFIX_CLOB_TRADE,      # "clob.trade.*"
            settings.REDIS_PREFIX_CLOB_ORDERBOOK,  # "clob.orderbook.*"
            settings.REDIS_PREFIX_COPY_TRADE,      # "copy_trade:*" (for copy trading)
        ]

    async def start(self):
        """Start the Redis bridge service"""
        if not self.enabled:
            logger.warning("⚠️ Redis bridge disabled (REDIS_BRIDGE_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info("✅ Redis bridge starting...")

        try:
            # Connect to Redis
            self.redis_client = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )

            # Create HTTP client for webhook POSTs
            self.http_client = httpx.AsyncClient(timeout=10.0)

            logger.info("✅ Connected to Redis")

            # Subscribe and listen
            await self._subscribe_and_listen()

        except KeyboardInterrupt:
            logger.info("⏹️ Redis bridge interrupted")
        except Exception as e:
            logger.error(f"❌ Redis bridge fatal error: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the Redis bridge service"""
        if self.http_client:
            await self.http_client.aclose()
        if self.redis_client:
            await self.redis_client.close()
        logger.info("✅ Redis bridge stopped")

    async def _subscribe_and_listen(self):
        """Subscribe to channels and listen for messages"""
        if not self.redis_client:
            return

        try:
            # Use PubSub for pattern subscriptions
            pubsub = self.redis_client.pubsub()

            # Subscribe to channel patterns
            for pattern in self.channel_patterns:
                await pubsub.psubscribe(pattern)
                logger.info(f"📻 Subscribed to pattern: {pattern}")

            logger.info(f"✅ Subscribed to {len(self.channel_patterns)} channel patterns")

            # Listen for messages
            async for message in pubsub.listen():
                try:
                    if message['type'] == 'pmessage':
                        await self._handle_message(
                            channel=message['channel'],
                            pattern=message['pattern'],
                            data=message['data']
                        )

                except Exception as e:
                    self.error_count += 1
                    logger.error(f"❌ Message processing error: {e}")

                    # Reset error count periodically
                    if self.message_count % 100 == 0:
                        self.consecutive_errors = 0

        finally:
            await pubsub.close()

    async def _handle_message(self, channel: str, pattern: str, data: str):
        """Handle received Redis message"""
        try:
            self.message_count += 1

            # Parse Redis message
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"raw_message": data}

            # Determine event type from channel
            event = self._determine_event_type(channel)

            # Handle copy_trade channels differently (no market_id in channel name)
            if "copy_trade" in channel:
                # For copy_trade, forward payload directly to copy_trade webhook endpoint
                # The payload already contains all necessary fields (user_address, market_id, etc.)
                # Use configured copy_trade webhook URL (can point to bot service)

                # POST payload directly (it's already in the correct format)
                await self._post_to_webhook(payload, webhook_url=self.copy_trade_webhook_url)
                return

            # For other channels, extract market_id and wrap in webhook format
            market_id = self._extract_market_id(channel)
            if not market_id:
                logger.debug(f"⚠️ Could not extract market_id from channel: {channel}")
                return

            # Prepare webhook payload
            webhook_payload = {
                "market_id": market_id,
                "event": event,
                "payload": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # POST to webhook
            await self._post_to_webhook(webhook_payload)

            # Log every 50 messages
            if self.message_count % 50 == 0:
                logger.info(
                    f"[REDIS_BRIDGE] Processed {self.message_count} messages, "
                    f"success: {self.success_count}, errors: {self.error_count}"
                )

        except Exception as e:
            logger.error(f"❌ Handle message error: {e}")

    async def _post_to_webhook(self, payload: dict, webhook_url: Optional[str] = None):
        """POST message to webhook endpoint"""
        if not self.http_client:
            return

        url = webhook_url or self.webhook_url

        try:
            response = await self.http_client.post(
                url,
                json=payload,
                timeout=5.0
            )

            if response.status_code in (200, 201):
                self.success_count += 1
                # Handle both market-level and copy_trade payloads
                identifier = payload.get('market_id') or payload.get('user_address', 'unknown')[:10]
                event_type = payload.get('event') or payload.get('tx_type', 'unknown')
                logger.debug(
                    f"✅ Webhook POST success for {identifier}: "
                    f"{event_type} ({response.status_code})"
                )
            else:
                logger.warning(
                    f"⚠️ Webhook POST failed with status {response.status_code}: "
                    f"{response.text[:100]}"
                )
                self.error_count += 1

        except httpx.TimeoutException:
            identifier = payload.get('market_id') or payload.get('user_address', 'unknown')[:10]
            logger.warning(f"⚠️ Webhook POST timeout for {identifier}")
            self.error_count += 1
        except Exception as e:
            logger.error(f"❌ Webhook POST error: {e}")
            self.error_count += 1

    @staticmethod
    def _extract_market_id(channel: str) -> Optional[str]:
        """Extract market_id from channel name"""
        # Channels: market.status.0x123, clob.trade.0x123, clob.orderbook.0x123
        # The market_id is everything after the second dot
        parts = channel.split('.', 2)  # Split on first 2 dots only
        if len(parts) >= 3:
            return parts[2]  # Everything after the first two dots is the market_id
        return None

    @staticmethod
    def _determine_event_type(channel: str) -> str:
        """Determine event type from channel name"""
        if "market.status" in channel:
            return "market.status.update"
        elif "clob.trade" in channel:
            return "clob.trade.executed"
        elif "clob.orderbook" in channel:
            return "clob.orderbook.updated"
        elif "copy_trade" in channel:
            return "copy_trade.executed"
        else:
            return "unknown"


# Global bridge instance
_bridge_instance: Optional[RedisBridge] = None


async def get_redis_bridge() -> RedisBridge:
    """Get or create global Redis bridge instance"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = RedisBridge()
    return _bridge_instance


# Entry point for running bridge as standalone service
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        format=settings.LOG_FORMAT,
        level=settings.LOG_LEVEL
    )

    async def main():
        bridge = await get_redis_bridge()
        await bridge.start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Redis bridge stopped")
        sys.exit(0)
