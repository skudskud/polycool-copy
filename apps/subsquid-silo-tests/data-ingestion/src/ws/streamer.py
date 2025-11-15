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
    """CLOB WebSocket streaming service with dynamic subscription management"""

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

        # Dynamic subscription management
        self.subscription_refresh_interval = 60  # 1 minute (fast refresh for user positions)
        self.subscription_refresh_task: Optional[asyncio.Task] = None
        self.last_subscription_refresh = None

    async def start(self):
        """Start the WebSocket streaming service"""
        if not self.enabled:
            logger.warning("⚠️ Streamer service disabled (STREAMER_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info("✅ Streamer service starting...")

        # Start subscription refresh task
        self.subscription_refresh_task = asyncio.create_task(self._periodic_subscription_refresh())
        logger.info(f"🔄 Started subscription refresh task (every {self.subscription_refresh_interval}s)")

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

        # Cancel subscription refresh task
        if self.subscription_refresh_task and not self.subscription_refresh_task.done():
            self.subscription_refresh_task.cancel()
            try:
                await self.subscription_refresh_task
            except asyncio.CancelledError:
                pass

        logger.info("✅ Streamer stopped")

    async def _connect_and_stream(self):
        """Connect to CLOB WebSocket and stream messages"""
        try:
            # Build WebSocket URL with credentials if using CLOB endpoint
            ws_url = self.ws_uri
            if "ws-subscriptions-clob" in ws_url and settings.CLOB_API_KEY:
                # Add credentials as query parameters for CLOB WebSocket
                ws_url = f"{ws_url}?apikey={settings.CLOB_API_KEY}&secret={settings.CLOB_API_SECRET}&passphrase={settings.CLOB_API_PASSPHRASE}"
                logger.info(f"🔌 Connecting to CLOB WebSocket with authentication")
            else:
                logger.info(f"🔌 Connecting to CLOB WebSocket: {ws_url}")

            # Try to resolve DNS manually for debugging
            try:
                import socket
                host = ws_url.split("//")[1].split("/")[0].split("?")[0]
                resolved_ip = socket.gethostbyname(host)
                logger.debug(f"✅ DNS resolved to: {resolved_ip}")
            except Exception as dns_err:
                logger.warning(f"⚠️ DNS resolution failed: {dns_err}")

            async with websockets.connect(
                ws_url,
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

                # CRITICAL: Sync subscriptions after reconnection
                await self._sync_subscriptions_after_reconnect()

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

    async def _sync_subscriptions_after_reconnect(self):
        """Sync subscriptions after WebSocket reconnection to prevent data loss"""
        try:
            logger.info("🔄 Syncing subscriptions after reconnection...")

            # Force immediate subscription refresh
            db = await get_db_client()
            current_token_ids = await db.get_active_position_token_ids(limit=500)

            if not current_token_ids:
                logger.warning("⚠️ No active positions found during reconnection sync")
                return

            # Calculate changes
            to_unsubscribe = self.subscribed_markets - set(current_token_ids)
            to_subscribe = set(current_token_ids) - self.subscribed_markets

            # Unsubscribe from markets no longer needed
            if to_unsubscribe:
                await self._unsubscribe_markets(to_unsubscribe)
                logger.info(f"🚪 Unsubscribed {len(to_unsubscribe)} markets during reconnection")

            # Subscribe to new markets
            if to_subscribe:
                await self._subscribe_specific_markets(to_subscribe)
                logger.info(f"📈 Subscribed {len(to_subscribe)} markets during reconnection")

            # Update subscription set
            self.subscribed_markets = set(current_token_ids)

            logger.info(f"✅ Subscription sync complete: {len(self.subscribed_markets)} active markets")

        except Exception as e:
            logger.error(f"❌ Failed to sync subscriptions after reconnection: {e}")
            # Continue anyway - better to have partial subscriptions than none

    async def _subscribe_markets(self):
        """Subscribe to market channels with CLOB authentication"""
        if not self.websocket:
            return

        try:
            # Get CLOB token IDs from database (for asset-based subscription)
            subscriptions = []
            token_ids = []

            try:
                db = await get_db_client()
                # Get token IDs for top markets (optimized to 500 to reduce bandwidth)
                # User positions + smart traders still included for 100% critical coverage
                token_ids = await db.get_market_token_ids(limit=500)

                if not token_ids:
                    logger.error("❌ No token IDs retrieved - cannot subscribe")
                    return

                logger.info(f"✅ Got {len(token_ids)} token IDs for CLOB market channel subscription")

            except Exception as db_error:
                logger.error(f"⚠️ Could not get token IDs from DB: {db_error}", exc_info=True)
                logger.error("❌ Cannot proceed without token IDs - exiting")
                return

            # Send CLOB Market Channel subscription (correct format per docs)
            subscription_message = {
                "action": "subscribe",
                "type": "market",
                "assets_ids": token_ids
            }

            await self.websocket.send(json.dumps(subscription_message))
            logger.info(f"✅ Subscribed to CLOB Market Channel with {len(token_ids)} asset IDs")

            # Track subscribed markets (we need market_ids, not token_ids)
            # For now, we'll track token_ids as market identifiers
            # TODO: Map token_ids back to market_ids properly
            self.subscribed_markets.update(token_ids)  # Track all subscribed tokens

            logger.info(f"🔍 Waiting for market data (book, last_trade_price, price_change)...")

        except Exception as e:
            logger.error(f"⚠️ Subscription error: {e}")

    async def _periodic_subscription_refresh(self):
        """
        Refresh market subscriptions every 60s.
        Also checks for manual trigger flag from bot trades for immediate refresh.
        """
        while True:
            try:
                # Check for manual trigger flag (set by bot after trades)
                should_refresh_now = False
                try:
                    import redis.asyncio as aioredis
                    from ..config import settings

                    if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
                        redis_client = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                        flag = await redis_client.get("streamer:watched_markets_changed")

                        if flag:
                            logger.info("🔔 Manual trigger detected - refreshing subscriptions NOW")
                            should_refresh_now = True
                            await redis_client.delete("streamer:watched_markets_changed")

                        await redis_client.close()
                except Exception as e:
                    logger.debug(f"⚠️ Could not check Redis flag (non-critical): {e}")

                # Wait for interval (unless manual trigger)
                if not should_refresh_now:
                    await asyncio.sleep(self.subscription_refresh_interval)

                # ✅ NEW: Get current active markets from user_positions
                db = await get_db_client()
                current_token_ids = await db.get_active_position_token_ids(limit=500)

                if not current_token_ids:
                    logger.warning("⚠️ No active markets found during subscription refresh")
                    continue

                # Find markets to unsubscribe (no longer active)
                to_unsubscribe = self.subscribed_markets - set(current_token_ids)

                # Find markets to subscribe (new high-volume markets)
                to_subscribe = set(current_token_ids) - self.subscribed_markets

                # Unsubscribe inactive markets
                if to_unsubscribe:
                    await self._unsubscribe_markets(to_unsubscribe)
                    logger.debug(f"🚪 Unsubscribed from {len(to_unsubscribe)} inactive markets")

                # Subscribe to new high-volume markets
                if to_subscribe:
                    await self._subscribe_specific_markets(to_subscribe)
                    logger.debug(f"📈 Subscribed to {len(to_subscribe)} new high-volume markets")

                self.last_subscription_refresh = datetime.now(timezone.utc)

                # Log status - only if there were changes
                if to_subscribe or to_unsubscribe:
                    total_subscribed = len(self.subscribed_markets)
                    logger.info(f"🔄 Subscription refresh: {total_subscribed} total markets | +{len(to_subscribe)} | -{len(to_unsubscribe)}")

            except Exception as e:
                logger.error(f"⚠️ Subscription refresh error: {e}")
                # Don't crash the entire streamer, just log and continue
                await asyncio.sleep(60)  # Wait a bit before retrying

    async def _unsubscribe_markets(self, token_ids: Set[str]):
        """Unsubscribe from specific markets"""
        if not self.websocket or not token_ids:
            return

        try:
            # CLOB WebSocket unsubscription format
            unsubscribe_message = {
                "action": "unsubscribe",
                "type": "market",
                "assets_ids": list(token_ids)
            }

            await self.websocket.send(json.dumps(unsubscribe_message))
            self.subscribed_markets -= token_ids
            logger.debug(f"✅ Unsubscribed from {len(token_ids)} markets")

        except Exception as e:
            logger.error(f"❌ Failed to unsubscribe from markets: {e}")

    async def _subscribe_specific_markets(self, token_ids: Set[str]):
        """Subscribe to specific markets"""
        if not self.websocket or not token_ids:
            return

        try:
            subscription_message = {
                "action": "subscribe",
                "type": "market",
                "assets_ids": list(token_ids)
            }

            await self.websocket.send(json.dumps(subscription_message))
            self.subscribed_markets.update(token_ids)
            logger.debug(f"✅ Subscribed to {len(token_ids)} new markets")

        except Exception as e:
            logger.error(f"❌ Failed to subscribe to markets: {e}")

    async def _stream_messages(self):
        """Stream and process WebSocket messages"""
        logger.info("🎧 Starting message stream listener...")
        async for message in self.websocket:
            try:
                self.stream_count += 1
                self.message_count += 1
                self.last_message_time = datetime.now(timezone.utc)

                data = json.loads(message)

                # Handle array of messages (first message might be array)
                if isinstance(data, list):
                    for item in data:
                        await self._process_message(item)
                    continue

                # Handle single message
                await self._process_message(data)

                # Log first few messages to see what we're getting
                if self.message_count <= 5:
                    logger.info(f"📨 Message #{self.message_count}: {json.dumps(data)[:200]}")

                # Log every 1000 messages (reduced from 100 to kill 90% of logs)
                if self.message_count % 1000 == 0:
                    logger.info(
                        f"[STREAMER] Processed {self.message_count} messages, "
                        f"subscribed to {len(self.subscribed_markets)} markets"
                    )

            except json.JSONDecodeError as e:
                logger.debug(f"⚠️ Invalid JSON: {message[:50]}")
            except Exception as e:
                logger.error(f"❌ Message processing error: {e}")
                continue

    async def _process_message(self, data: Dict[str, Any]):
        """Process a single market data message"""
        try:
            event_type = data.get("event_type")
            msg_type = data.get("type")

            # Debug: Log message types we receive (first 20 messages only)
            if self.message_count <= 20:
                logger.debug(f"📨 Message #{self.message_count}: type={msg_type}, event={event_type}, keys={list(data.keys())[:5]}")

            # Handle price_change events (most common)
            if event_type == "price_change" or "price_changes" in data:
                await self._handle_price_change(data)
            # Handle other message types
            elif msg_type == "trade":
                await self._handle_trade(data)
            elif msg_type == "orderbook" or msg_type == "book":
                await self._handle_orderbook(data)
            elif msg_type == "snapshot":
                await self._handle_snapshot(data)
            elif msg_type == "delta":
                await self._handle_delta(data)
            else:
                # Log unknown message types (only first 10)
                if self.message_count <= 10:
                    logger.debug(f"⚠️ Unknown event: {event_type}, type: {msg_type} - keys: {list(data.keys())}")

        except Exception as e:
            logger.error(f"❌ Error processing message: {e}")

    async def _handle_price_change(self, data: Dict[str, Any]):
        """Handle price_change event from CLOB Market Channel"""
        try:
            market_hex = data.get("market")
            price_changes = data.get("price_changes", [])
            timestamp = data.get("timestamp")

            if not market_hex or not price_changes:
                return

            logger.debug(f"🔄 HANDLER: _handle_price_change called for market {market_hex[:10]}... with {len(price_changes)} changes")
            logger.debug(f"📨 RAW EVENT: market={market_hex[:20]}, price_changes={price_changes}, timestamp={timestamp}")

            # Get market data to know token mappings
            logger.debug(f"🔍 Looking up market data for condition_id: {market_hex}")
            market_data = await self._get_market_data(market_hex)
            if not market_data:
                logger.warning(f"⚠️ Could not get market data for {market_hex} - market not found in DB")
                return

            logger.debug(f"✅ Found market data: {market_data.get('title', 'Unknown')} with {len(market_data.get('outcomes', []))} outcomes")

            clob_token_ids = market_data.get('clob_token_ids', [])
            outcomes = market_data.get('outcomes', [])
            if not clob_token_ids or len(clob_token_ids) < 2:
                logger.warning(f"⚠️ Invalid token_ids for market {market_hex}: {clob_token_ids}")
                return
            if not outcomes or len(outcomes) < 2:
                logger.warning(f"⚠️ Invalid outcomes for market {market_hex}: {outcomes}")
                return

            logger.debug(f"📊 Market {market_hex[:10]}...: tokens={[t[:10]+'...' for t in clob_token_ids]}, outcomes={outcomes}")

            yes_token_id = str(clob_token_ids[0])
            no_token_id = str(clob_token_ids[1])

            # Get all outcomes and token mappings
            outcomes = market_data.get('outcomes', [])
            token_ids = market_data.get('clob_token_ids', [])

            # Prepare update data for the market
            update_data = {}

            # Store individual prices in a JSON structure for all outcomes
            outcome_prices = {}

            # Process each asset's price change
            for change in price_changes:
                asset_id = change.get("asset_id")

                # ✅ NEW FORMAT (Sept 2025): Use best_bid/best_ask to calculate mid price
                # This is more accurate than the legacy "price" field
                best_bid = change.get("best_bid")
                best_ask = change.get("best_ask")
                legacy_price = change.get("price")  # Fallback for old format

                # Calculate mid price from orderbook (most accurate)
                price_float = None
                price_source = None

                if best_bid is not None and best_ask is not None:
                    # NEW FORMAT: Calculate mid from bid/ask (RECOMMENDED)
                    best_bid_float = float(best_bid)
                    best_ask_float = float(best_ask)
                    price_float = (best_bid_float + best_ask_float) / 2.0
                    price_source = f"bid/ask (${best_bid_float:.4f}/${best_ask_float:.4f})"
                elif legacy_price is not None:
                    # OLD FORMAT: Fallback to legacy price field
                    price_float = float(legacy_price)
                    price_source = "legacy"
                    logger.warning(f"⚠️ Using legacy price field for asset {asset_id[:20]}... - consider upgrading WebSocket format")

                if asset_id and price_float is not None:
                    # Find which outcome this token corresponds to
                    try:
                        token_index = token_ids.index(asset_id)
                        if token_index < len(outcomes):
                            outcome_name = outcomes[token_index]
                            outcome_prices[outcome_name] = price_float
                            logger.debug(f"✅ {outcome_name.upper()} PRICE: market={market_hex[:10]}... asset_id={asset_id[:20]}..., token_index={token_index}, price=${price_float:.6f} (from {price_source})")
                            logger.debug(f"🔍 TOKEN MAPPING: token_ids[{token_index}]={token_ids[token_index][:20]}... → outcomes[{token_index}]={outcome_name}")

                            # For backward compatibility with binary markets, also set YES/NO columns
                            if len(outcomes) == 2 and outcomes[0].lower() in ['yes', 'up'] and outcomes[1].lower() in ['no', 'down']:
                                if outcome_name.lower() in ['yes', 'up']:
                                    update_data['last_yes_price'] = price_float
                                elif outcome_name.lower() in ['no', 'down']:
                                    update_data['last_no_price'] = price_float
                        else:
                            logger.warning(f"⚠️ Token index {token_index} out of range for outcomes {outcomes}")
                    except ValueError:
                        logger.warning(f"⚠️ Token {asset_id[:20]}... not found in market token_ids")

            # Store the complete outcome prices as JSON
            if outcome_prices:
                update_data['outcome_prices'] = outcome_prices

                # ❌ REMOVED: last_mid calculation (incorrect for prediction markets)
                # The mid price should come from orderbook bid/ask, not from averaging YES/NO token prices
                # Users need individual YES/NO prices for PnL calculation, not a fake "mid"

                # Find the correct market_id for this market_hex
                market_id = await self._map_condition_to_market_id(market_hex)

                if market_id:
                    db = await get_db_client()
                    await db.upsert_market_ws(market_id, update_data)
                    logger.debug(f"✅ UPDATED: Market {market_id[:10]}... with outcomes: {list(outcome_prices.keys())}, prices: {outcome_prices}")
                else:
                    logger.warning(f"⚠️ Could not map condition_id {market_hex[:20]}... to market_id")

        except Exception as e:
            logger.error(f"❌ Price change processing error: {e}")

    async def _get_market_data(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """
        Get market data by condition_id from subsquid_markets_poll

        Args:
            condition_id: The condition_id (0x... format)

        Returns:
            Market data dict or None
        """
        try:
            db = await get_db_client()
            async with db.pool.acquire() as conn:
                query = f"""
                    SELECT market_id, condition_id, clob_token_ids, title, outcomes
                    FROM {TABLES['markets_poll']}
                    WHERE condition_id = $1
                    AND status = 'ACTIVE'
                    LIMIT 1
                """

                row = await conn.fetchrow(query, condition_id)
                if row:
                    # Parse clob_token_ids
                    clob_token_ids_raw = row['clob_token_ids']
                    token_ids = []
                    if clob_token_ids_raw:
                        try:
                            import json
                            cleaned = clob_token_ids_raw
                            if cleaned.startswith('"') and cleaned.endswith('"'):
                                cleaned = cleaned[1:-1]
                            cleaned = cleaned.replace('\\\\', '\\').replace('\\"', '"')
                            token_ids = json.loads(cleaned)
                        except Exception as parse_err:
                            logger.debug(f"Could not parse clob_token_ids for condition_id {condition_id}: {parse_err}")

                    # Parse outcomes
                    outcomes_raw = row['outcomes']
                    outcomes = []
                    if outcomes_raw:
                        try:
                            import json
                            if isinstance(outcomes_raw, str):
                                outcomes = json.loads(outcomes_raw)
                            elif isinstance(outcomes_raw, list):
                                outcomes = outcomes_raw
                        except Exception as parse_err:
                            logger.debug(f"Could not parse outcomes for condition_id {condition_id}: {parse_err}")

                    return {
                        'market_id': row['market_id'],
                        'condition_id': row['condition_id'],
                        'clob_token_ids': token_ids,
                        'outcomes': outcomes,
                        'title': row['title']
                    }

        except Exception as e:
            logger.error(f"❌ Error getting market data for condition_id {condition_id}: {e}")

        return None

    async def _map_condition_to_market_id(self, condition_id: str) -> Optional[str]:
        """
        Map condition_id to market_id

        Args:
            condition_id: The condition_id (0x... format)

        Returns:
            market_id (short format) or None
        """
        try:
            market_data = await self._get_market_data(condition_id)
            return market_data.get('market_id') if market_data else None
        except Exception as e:
            logger.error(f"❌ Error mapping condition_id {condition_id} to market_id: {e}")
            return None

    async def _map_token_to_market_id(self, token_id: str) -> Optional[str]:
        """
        Map a token_id to its corresponding market_id using subsquid_markets_poll data

        Args:
            token_id: The CLOB token ID

        Returns:
            market_id if found, None otherwise
        """
        try:
            db = await get_db_client()
            async with db.pool.acquire() as conn:
                # Search for markets containing this token_id in their clob_token_ids
                # The clob_token_ids field contains JSON arrays of token IDs
                query = f"""
                    SELECT market_id, clob_token_ids
                    FROM {TABLES['markets_poll']}
                    WHERE status = 'ACTIVE'
                      AND clob_token_ids IS NOT NULL
                      AND clob_token_ids != ''
                """

                rows = await conn.fetch(query)

                for row in rows:
                    clob_token_ids_raw = row['clob_token_ids']
                    if clob_token_ids_raw:
                        try:
                            import json
                            # Parse the JSON array (may be double-encoded)
                            cleaned = clob_token_ids_raw
                            if cleaned.startswith('"') and cleaned.endswith('"'):
                                cleaned = cleaned[1:-1]
                            cleaned = cleaned.replace('\\\\', '\\').replace('\\"', '"')

                            token_array = json.loads(cleaned)
                            if isinstance(token_array, list) and token_id in token_array:
                                return row['market_id']
                        except Exception as parse_err:
                            logger.debug(f"Could not parse clob_token_ids for market {row['market_id']}: {parse_err}")
                            continue

        except Exception as e:
            logger.error(f"❌ Error mapping token {token_id[:20]}... to market_id: {e}")

        return None

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

            logger.debug(f"🔄 HANDLER: _handle_orderbook called for market {market_id[:10]}...")

            # Extract bid/ask from orderbook
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            best_bid = float(bids[0][0]) if bids else None
            best_ask = float(asks[0][0]) if asks else None

            # ✅ Store bid/ask but NOT last_mid
            # last_mid is meaningless for WebSocket data (should come from orderbook aggregation)
            ob_data = {
                "last_bb": best_bid,
                "last_ba": best_ask,
            }

            db = await get_db_client()
            await db.upsert_market_ws(market_id, ob_data)

            logger.debug(f"✅ STORED: Orderbook for market={market_id[:10]}... BB=${best_bid}, BA=${best_ask}")

        except Exception as e:
            logger.error(f"❌ Orderbook processing error: {e}")

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

            # ✅ Store bid/ask but NOT last_mid
            snapshot_data = {
                "market_id": market_id,
                "last_bb": best_bid,
                "last_ba": best_ask,
            }

            db = await get_db_client()
            await db.upsert_market_ws(market_id, snapshot_data)

            logger.debug(f"📸 Snapshot for {market_id}: bb={best_bid}, ba={best_ask}")

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

            # ✅ REMOVED: last_mid calculation
            # We only store bid/ask from deltas, mid is meaningless here

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

    # Silence httpx INFO logs (HTTP requests spam)
    logging.getLogger('httpx').setLevel(logging.WARNING)

    async def main():
        streamer = await get_streamer()
        await streamer.start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Streamer stopped")
        sys.exit(0)
