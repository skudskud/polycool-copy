"""
CLOB WebSocket Streamer Service
Connects to CLOB WebSocket for real-time market data.
Parses orderbook snapshots/deltas, calculates mid-price, upserts to subsquid_markets_ws.
Auto-reconnect with exponential backoff + jitter.
"""

import logging
import asyncio
import json
import websockets
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set
from time import time
import random

from ..config import settings, validate_experimental_subsquid, TABLES
from ..db.client import get_db_client

logger = logging.getLogger(__name__)


class StreamerService:
    """CLOB WebSocket streaming service"""

    def __init__(self):
        self.enabled = settings.STREAMER_ENABLED
        self.ws_uri = settings.CLOB_WSS_URL
        self.websocket = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.backoff_seconds = 1.0
        self.max_backoff = settings.WS_RECONNECT_BACKOFF_MAX
        self.stream_count = 0
        self.message_count = 0
        self.reconnection_count = 0
        self.last_message_time = None
        self.subscribed_markets: Set[str] = set()

    async def start(self):
        """Start the WebSocket streaming service"""
        if not self.enabled:
            logger.warning("⚠️ Streamer service disabled (STREAMER_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info("✅ Streamer service starting...")

        try:
            while True:
                await self._connect_and_stream()
        except KeyboardInterrupt:
            logger.info("⏹️ Streamer interrupted")
        except Exception as e:
            logger.error(f"❌ Streamer fatal error: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the streaming service"""
        if self.websocket:
            await self.websocket.close()
        logger.info("✅ Streamer stopped")

    async def _connect_and_stream(self):
        """Connect to CLOB WebSocket and stream messages"""
        try:
            logger.info(f"🔌 Connecting to CLOB WebSocket: {self.ws_uri}")
            logger.debug(f"🔍 DNS resolution for: ws.clob.polymarket.com")

            # Try to resolve DNS manually for debugging
            try:
                import socket
                resolved_ip = socket.gethostbyname("ws.clob.polymarket.com")
                logger.debug(f"✅ DNS resolved to: {resolved_ip}")
            except Exception as dns_err:
                logger.warning(f"⚠️ DNS resolution failed: {dns_err}")

            async with websockets.connect(
                self.ws_uri,
                ping_interval=30,
                ping_timeout=10,
                max_size=10 * 1024 * 1024  # 10MB max message
            ) as websocket:
                self.websocket = websocket
                logger.info("✅ WebSocket connected")

                # Reset error count on successful connection
                self.consecutive_errors = 0
                self.backoff_seconds = 1.0
                self.reconnection_count += 1

                # Subscribe to market channels
                await self._subscribe_markets()

                # Stream messages
                await self._stream_messages()

        except asyncio.CancelledError:
            logger.info("⏹️ Streamer cancelled")
            raise
        except Exception as e:
            self.consecutive_errors += 1
            logger.error(f"❌ Connection error (attempt {self.consecutive_errors}): {e}")

            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.error(f"❌ Max consecutive errors ({self.max_consecutive_errors}) reached")
                raise

            # Exponential backoff with jitter
            backoff = min(self.backoff_seconds, self.max_backoff)
            jitter = backoff * 0.1 * random.random()  # 0-10% jitter
            await asyncio.sleep(backoff + jitter)
            self.backoff_seconds *= 2.0

    async def _subscribe_markets(self):
        """Subscribe to market channels"""
        if not self.websocket:
            return

        try:
            # Get active markets from DB
            db = await get_db_client()
            active_markets = await db.get_active_markets()  # New method needed

            # Subscribe to first N markets (limit to avoid overload)
            markets_to_sub = active_markets[:settings.WS_MAX_SUBSCRIPTIONS]

            for market_id in markets_to_sub:
                subscription = {
                    "type": "subscribe",
                    "market": market_id
                }
                await self.websocket.send(json.dumps(subscription))
                self.subscribed_markets.add(market_id)
                await asyncio.sleep(0.05)  # Small delay between subscriptions

            logger.info(f"✅ Subscribed to {len(self.subscribed_markets)} markets")

        except Exception as e:
            logger.error(f"⚠️ Subscription error: {e}")

    async def _stream_messages(self):
        """Stream and process WebSocket messages"""
        async for message in self.websocket:
            try:
                self.stream_count += 1
                self.message_count += 1
                self.last_message_time = datetime.now(timezone.utc)

                data = json.loads(message)

                # Handle different message types
                if data.get("type") == "trade":
                    await self._handle_trade(data)
                elif data.get("type") == "orderbook":
                    await self._handle_orderbook(data)
                elif data.get("type") == "snapshot":
                    await self._handle_snapshot(data)
                elif data.get("type") == "delta":
                    await self._handle_delta(data)

                # Log every 100 messages
                if self.message_count % 100 == 0:
                    logger.debug(
                        f"[STREAMER] Processed {self.message_count} messages, "
                        f"subscribed to {len(self.subscribed_markets)} markets"
                    )

            except json.JSONDecodeError as e:
                logger.debug(f"⚠️ Invalid JSON: {message[:50]}")
            except Exception as e:
                logger.error(f"❌ Message processing error: {e}")
                continue

    async def _handle_trade(self, data: Dict[str, Any]):
        """Handle trade message"""
        try:
            market_id = data.get("market")
            if not market_id:
                return

            trade_data = {
                "market_id": market_id,
                "last_trade_price": float(data.get("price", 0)),
            }

            db = await get_db_client()
            await db.upsert_market_ws_trade(market_id, trade_data)

        except Exception as e:
            logger.debug(f"⚠️ Trade processing error: {e}")

    async def _handle_orderbook(self, data: Dict[str, Any]):
        """Handle orderbook update message"""
        try:
            market_id = data.get("market")
            if not market_id:
                return

            # Extract bid/ask from orderbook
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            best_bid = float(bids[0][0]) if bids else None
            best_ask = float(asks[0][0]) if asks else None
            mid = None

            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2.0

            ob_data = {
                "market_id": market_id,
                "last_bb": best_bid,
                "last_ba": best_ask,
                "last_mid": mid,
            }

            db = await get_db_client()
            await db.upsert_market_ws(market_id, ob_data)

        except Exception as e:
            logger.debug(f"⚠️ Orderbook processing error: {e}")

    async def _handle_snapshot(self, data: Dict[str, Any]):
        """Handle orderbook snapshot message"""
        try:
            market_id = data.get("market")
            if not market_id:
                return

            # Snapshot has full orderbook state
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            best_bid = float(bids[0][0]) if bids else None
            best_ask = float(asks[0][0]) if asks else None
            mid = None

            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2.0

            snapshot_data = {
                "market_id": market_id,
                "last_bb": best_bid,
                "last_ba": best_ask,
                "last_mid": mid,
            }

            db = await get_db_client()
            await db.upsert_market_ws(market_id, snapshot_data)

            logger.debug(f"📸 Snapshot for {market_id}: mid={mid}")

        except Exception as e:
            logger.debug(f"⚠️ Snapshot processing error: {e}")

    async def _handle_delta(self, data: Dict[str, Any]):
        """Handle orderbook delta (incremental update)"""
        try:
            market_id = data.get("market")
            if not market_id:
                return

            # Delta has incremental updates
            # In production, you'd maintain full orderbook state
            # For now, just track that we received an update

            delta_data = {
                "market_id": market_id,
            }

            # Extract any available bid/ask info from delta
            bid_changes = data.get("bids", [])
            ask_changes = data.get("asks", [])

            if bid_changes:
                delta_data["last_bb"] = float(bid_changes[0][0])
            if ask_changes:
                delta_data["last_ba"] = float(ask_changes[0][0])

            if "last_bb" in delta_data and "last_ba" in delta_data:
                delta_data["last_mid"] = (delta_data["last_bb"] + delta_data["last_ba"]) / 2.0

            db = await get_db_client()
            await db.upsert_market_ws(market_id, delta_data)

        except Exception as e:
            logger.debug(f"⚠️ Delta processing error: {e}")


# Global streamer instance
_streamer_instance: Optional[StreamerService] = None


async def get_streamer() -> StreamerService:
    """Get or create global streamer instance"""
    global _streamer_instance
    if _streamer_instance is None:
        _streamer_instance = StreamerService()
    return _streamer_instance


# Entry point for running streamer as standalone service
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        format=settings.LOG_FORMAT,
        level=settings.LOG_LEVEL
    )

    async def main():
        streamer = await get_streamer()
        await streamer.start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Streamer stopped")
        sys.exit(0)
