"""
WebSocket Client for Polymarket CLOB Market Channel
Connects to CLOB WebSocket for real-time market data (orderbook, prices, trades).
Implements selective subscription management (only active positions).
"""
import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set, Callable
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class WebSocketClient:
    """
    WebSocket client for Polymarket CLOB Market Channel
    - Selective subscriptions (only markets with active positions)
    - Auto-reconnect with exponential backoff
    - Message handling and routing
    """

    def __init__(self):
        self.ws_url = settings.polymarket.clob_wss_url
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.subscribed_token_ids: Set[str] = set()

        # Connection management
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.backoff_seconds = 1.0
        self.max_backoff = 300  # 5 minutes max

        # Ping/Pong management (Polymarket requirement)
        self.ping_task: Optional[asyncio.Task] = None
        self.ping_interval = 10  # Polymarket: ping every 10 seconds

        # Stats
        self.message_count = 0
        self.reconnection_count = 0
        self.last_message_time: Optional[datetime] = None

        # Message handlers
        self.message_handlers: Dict[str, Callable] = {}

    def register_handler(self, message_type: str, handler: Callable):
        """Register a message handler for a specific message type"""
        self.message_handlers[message_type] = handler

    async def start(self) -> None:
        """Start the WebSocket client"""
        self.running = True
        logger.info("🌐 WebSocket Client starting...")

        # Check if we have subscriptions before starting the connection loop
        if not self.subscribed_token_ids:
            logger.info("⚠️ No subscriptions - waiting for subscriptions to be added")
            await self._wait_for_subscriptions()

        while self.running:
            try:
                await self._connect_and_stream()
            except KeyboardInterrupt:
                logger.info("⏹️ WebSocket Client interrupted")
                self.running = False
                break
            except ConnectionClosed as e:
                # Only reconnect if we have subscriptions
                if self.subscribed_token_ids and self.running:
                    logger.warning(f"⚠️ WebSocket connection closed: {e}")
                    logger.info("🔄 Attempting to reconnect...")
                    self.consecutive_errors += 1
                    if self.consecutive_errors >= self.max_consecutive_errors:
                        logger.error(f"❌ Max consecutive errors reached - stopping")
                        self.running = False
                        break
                    # Clean up current connection before reconnecting
                    await self._cleanup_connection()
                    backoff = min(self.backoff_seconds, self.max_backoff)
                    jitter = backoff * 0.1 * random.random()
                    await asyncio.sleep(backoff + jitter)
                    self.backoff_seconds *= 2.0
                else:
                    logger.info("⚠️ No subscriptions - stopping reconnection loop")
                    self.running = False
                    break
            except Exception as e:
                logger.error(f"❌ WebSocket Client fatal error: {e}")
                import traceback
                logger.debug(f"Traceback: {traceback.format_exc()}")
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.error(f"❌ Max consecutive errors reached - stopping")
                    self.running = False
                    break
                # Clean up before reconnecting
                await self._cleanup_connection()
                backoff = min(self.backoff_seconds, self.max_backoff)
                jitter = backoff * 0.1 * random.random()
                await asyncio.sleep(backoff + jitter)
                self.backoff_seconds *= 2.0

        # Only call stop() if we're actually stopping (not reconnecting)
        if not self.running:
            await self.stop()

    async def _wait_for_subscriptions(self) -> None:
        """Wait for subscriptions to be added before starting connection loop"""
        while self.running and not self.subscribed_token_ids:
            logger.debug("⏳ Waiting for subscriptions...")
            await asyncio.sleep(10)  # Check every 10 seconds
            # Reset consecutive errors while waiting
            self.consecutive_errors = 0
            self.backoff_seconds = 1.0

    async def _cleanup_connection(self) -> None:
        """Clean up current connection without stopping the client (for reconnection)"""
        # Stop ping task first
        if self.ping_task and not self.ping_task.done():
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass
            self.ping_task = None

        # Clear websocket reference (connection will be closed by context manager)
        self.websocket = None

    async def stop(self) -> None:
        """Stop the WebSocket client"""
        self.running = False

        # Stop ping task first
        if self.ping_task and not self.ping_task.done():
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket connection
        if self.websocket:
            try:
                # Check if websocket is already closed using available attributes
                is_closed = False
                try:
                    if hasattr(self.websocket, 'closed'):
                        is_closed = self.websocket.closed
                    elif hasattr(self.websocket, 'state'):
                        is_closed = self.websocket.state == 'CLOSED'
                except Exception:
                    pass

                if not is_closed:
                    await self.websocket.close(code=1000, reason="Client shutdown")
                    logger.info("✅ WebSocket connection closed cleanly")
                else:
                    logger.debug("WebSocket already closed")
            except Exception as e:
                logger.warning(f"⚠️ Error closing WebSocket: {e}")
                # Force close if clean close fails
                try:
                    if hasattr(self.websocket, '_close_transport'):
                        self.websocket._close_transport()
                    elif hasattr(self.websocket, 'transport') and self.websocket.transport:
                        self.websocket.transport.close()
                except Exception as force_close_error:
                    logger.warning(f"⚠️ Force close also failed: {force_close_error}")
                    pass

        logger.info("✅ WebSocket Client stopped")

    async def _connect_and_stream(self) -> None:
        """Connect to WebSocket and stream messages"""
        try:
            logger.info(f"🔌 Connecting to Polymarket CLOB WebSocket: {self.ws_url}")

            async with websockets.connect(
                self.ws_url,
                ping_interval=None,  # Disable auto ping, we handle manually
                ping_timeout=10,
                max_size=10 * 1024 * 1024  # 10MB max message
            ) as websocket:
                self.websocket = websocket
                logger.info("✅ WebSocket connected")

                # Reset error count on successful connection
                self.consecutive_errors = 0
                self.backoff_seconds = 1.0
                self.reconnection_count += 1

                # Start ping loop (Polymarket requirement)
                self.ping_task = asyncio.create_task(self._ping_loop())

                try:
                    # Sync subscriptions after reconnection
                    await self._sync_subscriptions_after_reconnect()

                    # Stream messages
                    await self._stream_messages()
                finally:
                    # Clean up ping task
                    if self.ping_task and not self.ping_task.done():
                        self.ping_task.cancel()
                        try:
                            await self.ping_task
                        except asyncio.CancelledError:
                            pass

        except ConnectionClosed as e:
            logger.warning(f"⚠️ WebSocket connection closed: {e}")
            # Don't raise - let start() handle reconnection
            raise
        except WebSocketException as e:
            logger.error(f"❌ WebSocket error: {e}")
            raise
        except Exception as e:
            self.consecutive_errors += 1
            logger.error(f"❌ Connection error (attempt {self.consecutive_errors}): {e}")

            if self.consecutive_errors >= self.max_consecutive_errors:
                raise

            # Exponential backoff with jitter
            backoff = min(self.backoff_seconds, self.max_backoff)
            jitter = backoff * 0.1 * random.random()
            await asyncio.sleep(backoff + jitter)
            self.backoff_seconds *= 2.0

    async def _ping_loop(self) -> None:
        """Ping loop to maintain WebSocket connection (Polymarket requirement)"""
        while self.running and self.websocket:
            try:
                # Check if websocket is closed using the correct attribute/method
                # For websockets library, use connection state or try to check attributes
                is_closed = False
                try:
                    # Try the most common attributes for closed state
                    if hasattr(self.websocket, 'closed'):
                        is_closed = self.websocket.closed
                    elif hasattr(self.websocket, 'state'):
                        # Some websocket implementations use 'state' attribute
                        is_closed = self.websocket.state == 'CLOSED'
                    else:
                        # If we can't determine state, assume it's open and let send() fail if closed
                        is_closed = False
                except Exception:
                    # If state check fails, assume connection is still open
                    is_closed = False

                if is_closed:
                    logger.debug("🏓 WebSocket appears to be closed, stopping ping loop")
                    break

                await self.websocket.send("PING")
                logger.debug("🏓 Sent PING to maintain connection")
                await asyncio.sleep(self.ping_interval)
            except Exception as e:
                logger.warning(f"⚠️ Ping error: {e}")
                break

    async def _stream_messages(self) -> None:
        """Stream and process WebSocket messages"""
        try:
            logger.info(f"🔄 Starting message stream loop (subscribed to {len(self.subscribed_token_ids)} tokens)")
            async for message in self.websocket:
                try:
                    # Filter out empty or invalid messages before JSON parsing
                    if not message or not isinstance(message, str) or not message.strip():
                        logger.debug(f"⚠️ Skipping empty/invalid message: {repr(message)[:100]}")
                        continue

                    # Handle PONG responses BEFORE JSON parsing (PONG is not JSON)
                    if message.strip() == "PONG":
                        logger.debug("🏓 Received PONG (heartbeat response)")
                        self.last_message_time = datetime.now(timezone.utc)
                        continue

                    # Try to parse as JSON
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError as e:
                        # If not JSON and not PONG, log as warning but continue
                        logger.warning(f"⚠️ Message is not JSON and not PONG: {str(message)[:200]}")
                        continue

                    # Handle empty arrays (Polymarket sometimes sends empty arrays)
                    if isinstance(data, list):
                        if len(data) == 0:
                            logger.debug("⚠️ Received empty array message, skipping")
                            continue
                        else:
                            logger.warning(f"⚠️ Received non-empty array message (not supported): {data[:3]}")
                            continue

                    # Log at INFO level to see messages in production logs
                    logger.info(f"📨 Received WebSocket message: {json.dumps(data)[:500]}")  # Log first 500 chars
                    await self._handle_message(data)
                    self.message_count += 1
                    self.last_message_time = datetime.now(timezone.utc)
                except Exception as e:
                    logger.error(f"⚠️ Error handling message: {e}, raw: {str(message)[:200]}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

        except ConnectionClosed as e:
            logger.warning(f"⚠️ WebSocket connection closed during streaming: {e}")
            # Only raise if we have subscriptions, otherwise it's expected
            if self.subscribed_token_ids:
                raise
            else:
                logger.info("⚠️ WebSocket closed due to no subscriptions (expected)")
                return
        except Exception as e:
            logger.error(f"❌ Streaming error: {e}")
            raise

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message (data is already parsed JSON)

        Note: PONG messages are handled in _stream_messages before JSON parsing
        """

        # Skip list/array messages (some Polymarket messages are arrays)
        if isinstance(data, list):
            logger.debug(f"⚠️ Skipping list message (not supported): {len(data)} items")
            return

        # Ensure data is a dictionary
        if not isinstance(data, dict):
            logger.debug(f"⚠️ Skipping non-dict message: {type(data)}")
            return

        # Log message structure at INFO level to diagnose issues
        logger.info(f"🔍 Message structure - type: {data.get('type')}, event_type: {data.get('event_type')}, keys: {list(data.keys())[:15]}")

        # Handle Polymarket event types
        event_type = data.get("event_type")
        if event_type:
            await self._handle_polymarket_event(event_type, data)
            return

        # Handle Polymarket "market" type messages (standard format)
        message_type = data.get("type")
        if message_type == "market":
            # Polymarket market update - route to price_update handler
            handler = self.message_handlers.get("price_update")
            if handler:
                try:
                    logger.info(f"📊 Routing 'market' type message to price_update handler")
                    await handler(data)
                except Exception as e:
                    logger.error(f"⚠️ Handler error for market type: {e}")
            else:
                logger.warning("⚠️ No price_update handler registered for market type")
            return

        # Fallback to legacy message type handling
        message_type = message_type or data.get("action")

        if not message_type:
            logger.debug(f"⚠️ Message without type: {data}")
            return

        # Route to registered handler
        handler = self.message_handlers.get(message_type)
        if handler:
            try:
                await handler(data)
            except Exception as e:
                logger.error(f"⚠️ Handler error for {message_type}: {e}")
        else:
            logger.debug(f"⚠️ No handler for message type: {message_type}")

    async def _handle_polymarket_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle Polymarket-specific event types"""
        try:
            logger.debug(f"🎯 Handling Polymarket event: {event_type}")

            if event_type == "book":
                # Orderbook update
                handler = self.message_handlers.get("orderbook")
                if handler:
                    await handler(data)
                else:
                    logger.debug("⚠️ No orderbook handler registered")

            elif event_type == "price_change" or event_type == "price":
                # Price change event
                handler = self.message_handlers.get("price_update")
                if handler:
                    logger.info(f"📊 Routing price_change event to price_update handler")
                    await handler(data)
                else:
                    logger.warning("⚠️ No price_update handler registered")

            elif event_type == "trade":
                # Trade event
                handler = self.message_handlers.get("trade")
                if handler:
                    await handler(data)
                else:
                    logger.debug("⚠️ No trade handler registered")

            elif event_type == "tick_size_change":
                # Tick size change
                logger.info(f"📏 Tick size changed: {data}")
                # Handle tick size changes if needed

            else:
                logger.debug(f"⚠️ Unknown Polymarket event type: {event_type}, routing to price_update anyway")
                # Fallback: try price_update handler for unknown event types that might be price-related
                handler = self.message_handlers.get("price_update")
                if handler:
                    await handler(data)

        except Exception as e:
            logger.error(f"⚠️ Error handling Polymarket event {event_type}: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")

    async def _sync_subscriptions_after_reconnect(self) -> None:
        """Sync subscriptions after reconnection"""
        logger.info("🔄 Syncing subscriptions after reconnection...")
        logger.info(f"📊 Current subscribed token_ids: {list(self.subscribed_token_ids) if self.subscribed_token_ids else 'None'}")

        # Resend all stored subscriptions after reconnection
        if self.subscribed_token_ids and self.websocket:
            try:
                subscription_message = {
                    "assets_ids": list(self.subscribed_token_ids),
                    "type": "market"
                }
                subscription_json = json.dumps(subscription_message)
                logger.info(f"📡 Resending subscriptions after reconnect: {subscription_message}")
                logger.info(f"📡 Subscription JSON: {subscription_json}")
                await self.websocket.send(subscription_json)
                logger.info(f"✅ Resent {len(self.subscribed_token_ids)} subscriptions")
            except Exception as e:
                logger.error(f"❌ Error resending subscriptions: {e}")
        elif not self.subscribed_token_ids:
            logger.info("⚠️ No active subscriptions - WebSocket will close due to inactivity (expected)")
        else:
            logger.warning("⚠️ WebSocket not available for subscription sync")

    async def subscribe_markets(self, token_ids: Set[str]) -> None:
        """
        Subscribe to markets by CLOB token IDs (Polymarket format)

        Args:
            token_ids: Set of CLOB token IDs to subscribe to
        """
        if not token_ids:
            logger.info("⚠️ No token_ids provided for subscription")
            return

        try:
            # Validate token_ids format (should be strings)
            valid_token_ids = []
            for tid in token_ids:
                if isinstance(tid, str) and tid.strip():
                    valid_token_ids.append(tid.strip())
                else:
                    logger.warning(f"⚠️ Invalid token_id format: {tid} (type: {type(tid)})")

            if not valid_token_ids:
                logger.warning("⚠️ No valid token_ids to subscribe to")
                return

            # If WebSocket is not connected, just store the subscriptions
            # They will be sent when the connection is established
            self.subscribed_token_ids.update(valid_token_ids)
            logger.info(f"✅ Added {len(valid_token_ids)} subscriptions: {valid_token_ids}")

            # If WebSocket is connected, send the subscription immediately
            if self.websocket:
                # Polymarket Market Channel subscription format (from official docs)
                # Format: {"assets_ids": [...], "type": "market"}
                subscription_message = {
                    "assets_ids": valid_token_ids,
                    "type": "market"
                }

                logger.info(f"📡 Sending subscription message: {subscription_message}")
                subscription_json = json.dumps(subscription_message)
                logger.info(f"📡 Subscription JSON: {subscription_json}")
                await self.websocket.send(subscription_json)
                logger.info(f"✅ Subscription message sent for {len(valid_token_ids)} tokens")

                # Wait a bit to see if subscription is accepted or if we get any response
                await asyncio.sleep(0.5)  # Short wait to see if we get immediate response
            else:
                logger.info("📝 WebSocket not connected - subscriptions stored for later")

        except Exception as e:
            logger.error(f"❌ Subscription error: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")

    async def unsubscribe_markets(self, token_ids: Set[str]) -> None:
        """
        Unsubscribe from markets by CLOB token IDs (Polymarket format)

        Args:
            token_ids: Set of CLOB token IDs to unsubscribe from
        """
        if not self.websocket or not token_ids:
            return

        try:
            # Polymarket Market Channel unsubscription format
            unsubscribe_message = {
                "assets_ids": list(token_ids),
                "type": "market",
                "action": "unsubscribe"
            }

            await self.websocket.send(json.dumps(unsubscribe_message))
            self.subscribed_token_ids -= token_ids
            logger.info(f"🚪 Unsubscribed from {len(token_ids)} markets (Polymarket format)")

        except Exception as e:
            logger.error(f"⚠️ Unsubscription error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get WebSocket client statistics"""
        connected = False
        try:
            if self.websocket:
                if hasattr(self.websocket, 'closed'):
                    connected = not self.websocket.closed
                elif hasattr(self.websocket, 'state'):
                    connected = self.websocket.state != 'CLOSED'
                else:
                    connected = True  # Assume connected if we can't check
        except Exception:
            connected = False

        return {
            "running": self.running,
            "connected": connected,
            "subscribed_markets": len(self.subscribed_token_ids),
            "message_count": self.message_count,
            "reconnection_count": self.reconnection_count,
            "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
            "consecutive_errors": self.consecutive_errors,
        }
