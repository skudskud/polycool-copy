"""
CLOB WebSocket Streamer Service
Connects to CLOB WebSocket for real-time market data.
Parses orderbook snapshots/deltas, calculates mid-price, upserts to subsquid_markets_ws.
Auto-reconnect with exponential backoff + jitter.
Enhanced with health checks, metrics, deduplication, and timestamp validation.
"""

import logging
import asyncio
import json
import hashlib
import websockets
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set
from time import time
from collections import deque
import random
import httpx

from ..config import settings, validate_experimental_subsquid, TABLES
from ..db.client import get_db_client
from ..utils.health_server import start_health_server, HealthServer
from ..utils.metrics import (
    stream_messages_total,
    stream_duplicates_total,
    stream_stale_messages_total,
    stream_reconnections_total,
    stream_active_subscriptions,
    stream_last_message_age_seconds,
    stream_consecutive_errors,
    stream_message_processing_seconds
)

logger = logging.getLogger(__name__)


class StreamerService:
    """CLOB WebSocket streaming service with health checks, metrics, and deduplication"""

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

        # Health server for monitoring
        self.health_server: Optional[HealthServer] = None

        # Deduplication cache (last N message fingerprints)
        self.recent_messages = deque(maxlen=settings.STREAMER_DEDUP_CACHE_SIZE)
        self.duplicate_count = 0
        self.stale_message_count = 0

    async def start(self):
        """Start the WebSocket streaming service with health monitoring"""
        if not self.enabled:
            logger.warning("⚠️ Streamer service disabled (STREAMER_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info("✅ Streamer service starting...")

        # Start health server if enabled
        if settings.HEALTH_SERVER_ENABLED:
            try:
                self.health_server = await start_health_server(
                    service_name="streamer",
                    port=settings.HEALTH_SERVER_PORT_STREAMER,
                    error_threshold=settings.HEALTH_CHECK_ERROR_THRESHOLD,
                    degraded_threshold_seconds=settings.HEALTH_CHECK_DEGRADED_THRESHOLD_SECONDS
                )
                logger.info(f"🏥 Health server started on port {settings.HEALTH_SERVER_PORT_STREAMER}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to start health server: {e}")

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
        """Stop the streaming service and health server"""
        if self.websocket:
            await self.websocket.close()

        # Stop health server gracefully
        if self.health_server:
            await self.health_server.stop()

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

                # ✅ Track reconnection
                stream_reconnections_total.inc()
                stream_consecutive_errors.set(0)

                # Subscribe to market channels
                await self._subscribe_markets()

                # Stream messages
                await self._stream_messages()

        except asyncio.CancelledError:
            logger.info("⏹️ Streamer cancelled")
            raise
        except Exception as e:
            self.consecutive_errors += 1
            error_type = e.__class__.__name__
            logger.error(f"❌ Connection error (attempt {self.consecutive_errors}): {e}")

            # ⚠️ Update error metrics
            stream_consecutive_errors.set(self.consecutive_errors)

            # ⚠️ Update health server with error state
            if self.health_server:
                self.health_server.update(
                    consecutive_errors=self.consecutive_errors,
                    custom_metrics={
                        "last_error": error_type,
                        "reconnections": self.reconnection_count
                    }
                )

            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.error(f"❌ Max consecutive errors ({self.max_consecutive_errors}) reached")
                raise

            # Exponential backoff with jitter
            backoff = min(self.backoff_seconds, self.max_backoff)
            jitter = backoff * 0.1 * random.random()  # 0-10% jitter
            await asyncio.sleep(backoff + jitter)
            self.backoff_seconds *= 2.0

    async def _subscribe_markets(self):
        """Subscribe to market channels with CLOB authentication - optimized to avoid unnecessary resubscriptions"""
        if not self.websocket:
            return

        try:
            # Get watched markets (markets with user positions) from DB
            db = await get_db_client()
            watched_markets = await db.get_watched_markets()

            if not watched_markets:
                # Fallback to active markets if no watched markets
                logger.warning("⚠️ No watched markets found, falling back to active markets")
                active_markets = await db.get_active_markets()
                markets_to_sub = active_markets[:settings.WS_MAX_SUBSCRIPTIONS]
            else:
                # Subscribe to ALL watched markets (up to limit to avoid overload)
                markets_to_sub = watched_markets[:settings.WS_MAX_SUBSCRIPTIONS]
                logger.info(f"📈 Found {len(watched_markets)} watched markets, subscribing to {len(markets_to_sub)}")

            # PERFORMANCE OPTIMIZATION: Only resubscribe if market list has changed
            markets_set = set(markets_to_sub)
            if markets_set == self.subscribed_markets:
                logger.info(f"✅ Market subscription unchanged ({len(self.subscribed_markets)} markets) - skipping resubscription")
                return

            # Unsubscribe from markets no longer watched
            markets_to_unsub = self.subscribed_markets - markets_set
            if markets_to_unsub:
                logger.info(f"📉 Unsubscribing from {len(markets_to_unsub)} markets no longer watched")

            # Update subscribed markets set
            self.subscribed_markets = markets_set

            # Build subscription message with authentication
            subscriptions = []

            # Add authenticated CLOB user channel for trades/orders
            if settings.CLOB_API_KEY and settings.CLOB_API_SECRET and settings.CLOB_API_PASSPHRASE:
                logger.info("🔐 Adding authenticated CLOB subscriptions")
                subscriptions.append({
                    "topic": "clob_user",
                    "type": "*",  # Subscribe to all CLOB user events
                    "clob_auth": {
                        "key": settings.CLOB_API_KEY,
                        "secret": settings.CLOB_API_SECRET,
                        "passphrase": settings.CLOB_API_PASSPHRASE
                    }
                })

            # Add market price subscriptions
            for market_id in markets_to_sub:
                subscriptions.append({
                    "topic": "market",
                    "type": "update",
                    "filters": {"market_id": market_id}
                })
                self.subscribed_markets.add(market_id)

            # Send subscription message (RTDS format)
            subscription_message = {
                "action": "subscribe",
                "subscriptions": subscriptions
            }

            await self.websocket.send(json.dumps(subscription_message))
            logger.info(f"✅ Subscribed to {len(self.subscribed_markets)} markets + authenticated CLOB channels")

        except Exception as e:
            logger.error(f"⚠️ Subscription error: {e}")

    async def _stream_messages(self):
        """Stream and process WebSocket messages with validation and metrics"""
        async for message in self.websocket:
            start_time = time()
            try:
                self.stream_count += 1
                self.message_count += 1
                self.last_message_time = datetime.now(timezone.utc)

                data = json.loads(message)
                msg_type = data.get("type", "unknown")

                # ✅ Track message by type
                stream_messages_total.labels(message_type=msg_type).inc()

                # ✅ Deduplication check
                fingerprint = self._generate_fingerprint(data)
                if self._is_duplicate(fingerprint):
                    logger.debug(f"⚠️ Duplicate {msg_type} message skipped")
                    continue

                # ✅ Timestamp validation
                if self._is_message_stale(data):
                    logger.debug(f"⚠️ Stale {msg_type} message skipped")
                    continue

                # Handle different message types
                if msg_type == "trade":
                    await self._handle_trade(data)
                elif msg_type == "orderbook":
                    await self._handle_orderbook(data)
                elif msg_type == "snapshot":
                    await self._handle_snapshot(data)
                elif msg_type == "delta":
                    await self._handle_delta(data)

                # ✅ Track processing time
                processing_time = time() - start_time
                stream_message_processing_seconds.observe(processing_time)

                # ✅ Update health server periodically
                if self.message_count % 100 == 0:
                    logger.debug(
                        f"[STREAMER] Processed {self.message_count} messages, "
                        f"subscribed to {len(self.subscribed_markets)} markets, "
                        f"duplicates: {self.duplicate_count}, stale: {self.stale_message_count}"
                    )

                    # Update health metrics
                    if self.health_server:
                        self.health_server.update(
                            last_update=self.last_message_time,
                            consecutive_errors=0,
                            custom_metrics={
                                "messages_processed": self.message_count,
                                "duplicates_skipped": self.duplicate_count,
                                "stale_skipped": self.stale_message_count,
                                "subscriptions": len(self.subscribed_markets)
                            }
                        )

                    # Update Prometheus gauges
                    stream_active_subscriptions.set(len(self.subscribed_markets))
                    stream_consecutive_errors.set(0)

            except json.JSONDecodeError as e:
                logger.debug(f"⚠️ Invalid JSON: {message[:50]}")
            except Exception as e:
                logger.error(f"❌ Message processing error: {e}")
                continue

    def _generate_fingerprint(self, data: Dict[str, Any]) -> str:
        """
        Generate unique message fingerprint for deduplication.

        Uses hash of (market_id + timestamp + price) to create a compact fingerprint.
        """
        market_id = str(data.get("market", ""))
        timestamp = str(data.get("timestamp", ""))
        price = str(data.get("price", 0))

        fingerprint_str = f"{market_id}_{timestamp}_{price}"
        return hashlib.md5(fingerprint_str.encode()).hexdigest()[:12]

    def _is_duplicate(self, fingerprint: str) -> bool:
        """
        Check if message is a duplicate.

        Returns True if fingerprint already exists in recent messages cache.
        """
        if not settings.STREAMER_DEDUP_ENABLED:
            return False

        if fingerprint in self.recent_messages:
            self.duplicate_count += 1
            stream_duplicates_total.inc()
            return True

        # Add to cache
        self.recent_messages.append(fingerprint)
        return False

    def _is_message_stale(self, data: Dict[str, Any]) -> bool:
        """
        Check if message timestamp is too old (stale).

        Returns True if message is older than WS_MESSAGE_MAX_AGE_SECONDS.
        """
        if not settings.WS_TIMESTAMP_VALIDATION_ENABLED:
            return False

        try:
            timestamp_str = data.get("timestamp")
            if not timestamp_str:
                return False  # No timestamp, process anyway

            # Parse timestamp (support ISO format or unix timestamp)
            if isinstance(timestamp_str, (int, float)):
                msg_timestamp = datetime.fromtimestamp(timestamp_str, tz=timezone.utc)
            else:
                msg_timestamp = datetime.fromisoformat(str(timestamp_str).replace('Z', '+00:00'))

            now = datetime.now(timezone.utc)
            age_seconds = (now - msg_timestamp).total_seconds()

            if age_seconds > settings.WS_MESSAGE_MAX_AGE_SECONDS:
                logger.warning(
                    f"⚠️ Stale message: age={age_seconds:.0f}s, "
                    f"market={data.get('market')}, "
                    f"type={data.get('type')}"
                )
                self.stale_message_count += 1
                stream_stale_messages_total.inc()
                return True

            return False
        except Exception as e:
            logger.debug(f"⚠️ Timestamp validation error: {e}")
            return False  # Process if we can't validate

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

            # Add individual token prices for YES/NO
            await self._add_individual_token_prices(ob_data, market_id)

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

            # Add individual token prices for YES/NO
            await self._add_individual_token_prices(snapshot_data, market_id)

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

            # Add individual token prices for YES/NO
            await self._add_individual_token_prices(delta_data, market_id)

            db = await get_db_client()
            await db.upsert_market_ws(market_id, delta_data)

        except Exception as e:
            logger.debug(f"⚠️ Delta processing error: {e}")

    async def _add_individual_token_prices(self, data: Dict[str, Any], market_id: str):
        """
        Add individual YES/NO token prices to the data dict
        Fetches prices from CLOB API for each token in the market
        """
        try:
            # Get market data to find token IDs
            db = await get_db_client()

            # Query subsquid_markets_poll to find market by condition_id
            # market_id param here is condition_id (0x...)
            markets_poll = await db.get_markets_poll(limit=1000)  # Get all markets

            market_data = None
            for market in markets_poll:
                if market.get('condition_id') == market_id:
                    market_data = market
                    break

            if not market_data or not market_data.get('clob_token_ids'):
                logger.debug(f"⚠️ No token IDs found for market {market_id}")
                return

            # Parse token IDs (stored as JSON string)
            try:
                import json
                clob_token_ids = market_data['clob_token_ids']
                if isinstance(clob_token_ids, str):
                    token_ids = json.loads(clob_token_ids)
                elif isinstance(clob_token_ids, list):
                    token_ids = clob_token_ids
                else:
                    logger.debug(f"⚠️ Invalid token_ids format for market {market_id}")
                    return

                if len(token_ids) < 2:
                    logger.debug(f"⚠️ Not enough tokens for market {market_id}")
                    return

                yes_token_id = str(token_ids[0])
                no_token_id = str(token_ids[1])

            except Exception as e:
                logger.debug(f"⚠️ Failed to parse token IDs for market {market_id}: {e}")
                return

            # Fetch individual token prices from CLOB API using POST /prices
            async with httpx.AsyncClient(timeout=2.0) as client:
                try:
                    # Use POST /prices endpoint as documented
                    price_requests = [
                        {"token_id": yes_token_id, "side": "SELL"},
                        {"token_id": no_token_id, "side": "SELL"}
                    ]

                    response = await client.post(
                        "https://clob.polymarket.com/prices",
                        json=price_requests,
                        headers={"Content-Type": "application/json"}
                    )

                    if response.status_code == 200:
                        price_data = response.json()
                        logger.debug(f"✅ Price API response for market {market_id}: {price_data}")

                        # Extract prices from response
                        # Response format: {"token_id": {"SELL": "price_string"}}
                        if yes_token_id in price_data and "SELL" in price_data[yes_token_id]:
                            yes_price = float(price_data[yes_token_id]["SELL"])
                            data['last_yes_price'] = yes_price
                            logger.info(f"✅ YES price for market {market_id}: ${yes_price:.6f}")

                        if no_token_id in price_data and "SELL" in price_data[no_token_id]:
                            no_price = float(price_data[no_token_id]["SELL"])
                            data['last_no_price'] = no_price
                            logger.info(f"✅ NO price for market {market_id}: ${no_price:.6f}")
                    else:
                        logger.warning(f"⚠️ Price API failed for market {market_id}: {response.status_code} - {response.text}")

                except Exception as e:
                    logger.error(f"❌ Failed to fetch individual prices for market {market_id}: {e}")

        except Exception as e:
            logger.debug(f"⚠️ Error adding individual token prices for market {market_id}: {e}")


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
