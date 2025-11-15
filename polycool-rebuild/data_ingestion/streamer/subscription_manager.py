"""
Subscription Manager - Manages WebSocket subscriptions intelligently
- Subscribe ONLY to markets with active user positions
- Auto-subscribe after trade execution
- Auto-unsubscribe when position closed
- Periodic cleanup (5min)
"""
import asyncio
import os
from typing import Set, Optional
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import Market, Position
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"

# Import API client (needed for both SKIP_DB and non-SKIP_DB scenarios)
from core.services.api_client import get_api_client


class SubscriptionManager:
    """
    Manages WebSocket subscriptions intelligently
    - Subscribe positions actives uniquement
    - Subscribe après trade
    - Unsubscribe quand position fermée
    - Periodic cleanup
    """

    def __init__(self, websocket_client, market_updater=None):
        """
        Initialize subscription manager

        Args:
            websocket_client: WebSocketClient instance
            market_updater: Optional MarketUpdater instance (for cleaning price buffer on unsubscribe)
        """
        self.websocket_client = websocket_client
        self.market_updater = market_updater
        self.running = False
        self.cleanup_task: Optional[asyncio.Task] = None
        self.cleanup_interval = 300  # 5 minutes

    async def start(self) -> None:
        """Start the subscription manager"""
        self.running = True
        logger.info("🔄 Subscription Manager starting...")

        # Start periodic cleanup task
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def stop(self) -> None:
        """Stop the subscription manager"""
        self.running = False

        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("✅ Subscription Manager stopped")

    async def on_trade_executed(self, user_id: int, market_id: str) -> None:
        """
        Subscribe to market after trade execution

        Args:
            user_id: User ID who executed the trade
            market_id: Market ID where trade was executed
        """
        try:
            logger.info(f"🔍 Getting token IDs for market {market_id} after trade by user {user_id}")
            # Get token IDs for this market
            token_ids = await self._get_market_token_ids(market_id)
            logger.info(f"🔍 Found token IDs for market {market_id}: {token_ids}")

            if token_ids:
                logger.info(f"📡 Subscribing to {len(token_ids)} tokens for market {market_id}: {list(token_ids)}")
                await self.websocket_client.subscribe_markets(token_ids)
                logger.info(f"✅ Auto-subscribed to market {market_id} after trade (tokens: {list(token_ids)})")
                # Log current subscriptions for debugging
                logger.info(f"📊 Current subscribed token_ids: {list(self.websocket_client.subscribed_token_ids)}")

                # ✅ CRITICAL: Update market source to 'ws' immediately after subscription
                # This indicates the market is now subscribed to WebSocket
                await self._update_market_source_to_ws(market_id)
            else:
                logger.warning(f"⚠️ No token IDs found for market {market_id}")

        except Exception as e:
            logger.error(f"❌ Error subscribing after trade: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")

    async def on_position_closed(self, user_id: int, market_id: str) -> None:
        """
        Check if unsubscribe needed when position closed

        Args:
            user_id: User ID who closed the position
            market_id: Market ID where position was closed
        """
        logger.info(f"🔍 Checking unsubscribe for market {market_id} after position closed by user {user_id}")
        try:
            active_count = 0

            # Use API if SKIP_DB=true
            if SKIP_DB:
                try:
                    api_client = get_api_client()
                    # Get all active positions for this market (all users)
                    positions_data = await api_client.get_market_positions(market_id, use_cache=False)
                    if positions_data:
                        positions_list = positions_data.get('positions', [])
                        active_positions = [p for p in positions_list
                                          if p.get('status') == 'active'
                                          and p.get('amount', 0) > 0]
                        active_count = len(active_positions)
                        logger.debug(f"🔍 Found {active_count} active positions for market {market_id} via API (all users)")
                    else:
                        active_count = 0
                except Exception as api_error:
                    logger.error(f"❌ Error checking active positions via API: {api_error}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    # Don't unsubscribe if we can't check - safer to keep subscription
                    return
            else:
                # Use DB if SKIP_DB=false
                async with get_db() as db:
                    count = await db.execute(
                        select(func.count(Position.id))
                        .where(
                            Position.market_id == market_id,
                            Position.status == "active"
                        )
                    )
                    active_count = count.scalar() or 0

            logger.info(f"📊 Found {active_count} active positions on market {market_id}")

            if active_count == 0:
                # No more active positions, unsubscribe
                logger.info(f"🚪 Starting unsubscription process for market {market_id}")
                token_ids = await self._get_market_token_ids(market_id)
                logger.debug(f"🔑 Found {len(token_ids) if token_ids else 0} token IDs for market {market_id}: {token_ids}")
                if token_ids:
                    await self.websocket_client.unsubscribe_markets(token_ids)
                    logger.info(f"🚪 Auto-unsubscribed from market {market_id} (no active positions)")

                    # ✅ CRITICAL: Clean up price buffer for this market
                    # Prevents processing stale price updates after unsubscription
                    if self.market_updater:
                        self.market_updater.on_market_unsubscribed(market_id)

                    # ✅ CRITICAL: Change market source to 'poll' after unsubscription
                    # This prevents WebSocket from updating prices for unsubscribed markets
                    try:
                        if not SKIP_DB:
                            from core.database.connection import get_db
                            from core.database.models import Market
                            from sqlalchemy import update
                            async with get_db() as db:
                                await db.execute(
                                    update(Market)
                                    .where(Market.id == market_id)
                                    .values(source='poll')
                                )
                                await db.commit()
                                logger.info(f"✅ Changed market {market_id} source from 'ws' to 'poll' after unsubscription")
                        else:
                            # Use API to update market source
                            api_client = get_api_client()
                            response = await api_client.client.put(
                                f"{api_client.base_url}/markets/{market_id}",
                                json={"source": "poll"},
                                timeout=5.0
                            )
                            if response.status_code == 200:
                                logger.info(f"✅ Changed market {market_id} source to 'poll' via API after unsubscription")
                            else:
                                logger.error(
                                    f"❌ Failed to update market {market_id} source via API: "
                                    f"status={response.status_code}, response={response.text}"
                                )
                                # Try to update source directly via SQL as fallback
                                await self._update_market_source_fallback(market_id, 'poll')
                    except Exception as e:
                        logger.error(f"❌ Failed to update market {market_id} source to 'poll': {e}")
                        import traceback
                        logger.error(f"Traceback: {traceback.format_exc()}")
                        # Try fallback method
                        try:
                            await self._update_market_source_fallback(market_id, 'poll')
                        except Exception as fallback_error:
                            logger.error(f"❌ Fallback update also failed: {fallback_error}")
                else:
                    logger.warning(f"⚠️ No token IDs found for market {market_id} - cannot unsubscribe")
            else:
                logger.debug(f"✅ Market {market_id} still has {active_count} active positions - keeping subscription")

        except Exception as e:
            logger.error(f"⚠️ Error checking unsubscribe: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def subscribe_active_positions(self) -> None:
        """
        Subscribe to all markets with active user positions
        Called on startup and after reconnection
        """
        try:
            market_ids = []

            # Use API if SKIP_DB=true
            if SKIP_DB:
                try:
                    api_client = get_api_client()
                    # Get positions for user 1 (workaround - ideally check all users)
                    positions_data = await api_client.get_user_positions(1, use_cache=False)
                    if positions_data:
                        positions_list = positions_data.get('positions', [])
                        logger.info(f"📊 API returned {len(positions_list)} positions for user 1")
                        active_positions = [p for p in positions_list if p.get('status') == 'active' and p.get('amount', 0) > 0]
                        logger.info(f"📊 Filtered to {len(active_positions)} active positions with amount > 0")
                        market_ids = list(set(p.get('market_id') for p in active_positions if p.get('market_id')))
                        logger.info(f"📊 Found {len(market_ids)} distinct markets with active positions via API: {market_ids}")
                        # Log each position for debugging
                        for pos in active_positions:
                            logger.info(f"   - Position: market_id={pos.get('market_id')}, amount={pos.get('amount')}, status={pos.get('status')}")
                except Exception as api_error:
                    logger.error(f"❌ Error getting active positions via API: {api_error}")
                    return
            else:
                # Use DB if SKIP_DB=false
                async with get_db() as db:
                    # Get distinct market IDs with active positions
                    result = await db.execute(
                        select(Position.market_id)
                        .where(Position.status == "active")
                        .distinct()
                    )
                    market_ids = [row[0] for row in result.fetchall()]

            if not market_ids:
                logger.info("⚠️ No active positions found - no subscriptions needed")
                return

            # Get token IDs for all markets
            all_token_ids: Set[str] = set()
            for market_id in market_ids:
                token_ids = await self._get_market_token_ids(market_id)
                all_token_ids.update(token_ids)

            if all_token_ids:
                await self.websocket_client.subscribe_markets(all_token_ids)
                logger.info(f"📡 Subscribed to {len(all_token_ids)} token IDs from {len(market_ids)} markets with active positions")
            else:
                logger.warning("⚠️ No token IDs found for active positions")

        except Exception as e:
            logger.error(f"⚠️ Error subscribing active positions: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def _periodic_cleanup(self) -> None:
        """
        Periodic cleanup of unused subscriptions (every 5min)
        """
        while self.running:
            try:
                await asyncio.sleep(self.cleanup_interval)

                if not self.running:
                    break

                await self._cleanup_unused_subscriptions()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"⚠️ Error in periodic cleanup: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def _cleanup_unused_subscriptions(self) -> None:
        """Cleanup subscriptions for markets with no active positions"""
        try:
            # Get currently subscribed token IDs
            subscribed_token_ids = self.websocket_client.subscribed_token_ids.copy()

            if not subscribed_token_ids:
                logger.debug("✅ Cleanup: No subscriptions to check")
                return

            # Get markets with active positions
            active_market_ids = set()

            # Use API if SKIP_DB=true
            if SKIP_DB:
                try:
                    api_client = get_api_client()
                    # Get positions for user 1 (workaround - ideally check all users)
                    positions_data = await api_client.get_user_positions(1, use_cache=False)
                    if positions_data:
                        positions_list = positions_data.get('positions', [])
                        active_positions = [p for p in positions_list
                                          if p.get('status') == 'active'
                                          and p.get('amount', 0) > 0]
                        active_market_ids = {p.get('market_id') for p in active_positions if p.get('market_id')}
                        logger.debug(f"📊 Found {len(active_market_ids)} distinct markets with active positions via API")
                except Exception as api_error:
                    logger.error(f"❌ Error getting active positions via API during cleanup: {api_error}")
                    # Don't unsubscribe if we can't check - safer to keep subscriptions
                    return
            else:
                # Use DB if SKIP_DB=false
                async with get_db() as db:
                    result = await db.execute(
                        select(Position.market_id)
                        .where(Position.status == "active")
                        .distinct()
                    )
                    active_market_ids = {row[0] for row in result.fetchall()}

            # Get token IDs for active markets
            active_token_ids: Set[str] = set()
            for market_id in active_market_ids:
                token_ids = await self._get_market_token_ids(market_id)
                active_token_ids.update(token_ids)

            # Find token IDs to unsubscribe (subscribed but not active)
            to_unsubscribe = subscribed_token_ids - active_token_ids

            if to_unsubscribe:
                await self.websocket_client.unsubscribe_markets(to_unsubscribe)
                logger.info(f"🧹 Cleanup: Unsubscribed from {len(to_unsubscribe)} unused token IDs")

                # ✅ CRITICAL: Find markets with source='ws' that have no active positions
                # and update their source to 'poll'
                markets_to_update = []

                if SKIP_DB:
                    try:
                        api_client = get_api_client()
                        # Get all markets with source='ws' (we'll check positions for each)
                        # For now, we'll update markets that we know have no active positions
                        # by checking the active_market_ids we already computed
                        # Markets not in active_market_ids but with source='ws' should be updated
                        pass  # API doesn't have a direct way to query markets by source
                    except Exception as api_error:
                        logger.debug(f"Could not check markets via API during cleanup: {api_error}")
                else:
                    # Use DB to find markets with source='ws' and no active positions
                    try:
                        async with get_db() as db:
                            from core.database.models import Market
                            from sqlalchemy import update

                            # Find markets with source='ws' that are not in active_market_ids
                            result = await db.execute(
                                select(Market.id)
                                .where(Market.source == 'ws')
                            )
                            all_ws_markets = {row[0] for row in result.fetchall()}

                            # Markets to update: those with source='ws' but no active positions
                            markets_to_update = list(all_ws_markets - active_market_ids)

                            if markets_to_update:
                                # Update all markets at once
                                await db.execute(
                                    update(Market)
                                    .where(Market.id.in_(markets_to_update))
                                    .values(source='poll')
                                )
                                await db.commit()
                                logger.info(f"✅ Cleanup: Updated {len(markets_to_update)} markets from 'ws' to 'poll'")
                    except Exception as db_error:
                        logger.debug(f"Could not update market sources via DB during cleanup: {db_error}")
            else:
                logger.debug("✅ Cleanup: All subscriptions are still active")

        except Exception as e:
            logger.error(f"⚠️ Error in cleanup: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")

    async def _get_market_token_ids(self, market_id: str) -> Set[str]:
        """
        Get CLOB token IDs for a market

        Args:
            market_id: Market ID

        Returns:
            Set of token IDs
        """
        try:
            # Use API if SKIP_DB=true
            if SKIP_DB:
                try:
                    api_client = get_api_client()
                    market_data = await api_client.get_market(market_id)
                    if not market_data:
                        logger.warning(f"⚠️ Market {market_id} not found via API")
                        return set()

                    clob_token_ids = market_data.get('clob_token_ids')
                    if not clob_token_ids:
                        logger.warning(f"⚠️ No clob_token_ids found for market {market_id} via API")
                        return set()

                    # Handle both list and string formats
                    if isinstance(clob_token_ids, str):
                        import json
                        try:
                            clob_token_ids = json.loads(clob_token_ids)
                        except json.JSONDecodeError:
                            logger.warning(f"⚠️ Invalid JSON in clob_token_ids for market {market_id}")
                            return set()

                    if isinstance(clob_token_ids, list):
                        token_set = set(str(tid) for tid in clob_token_ids if tid)
                        logger.debug(f"✅ Got {len(token_set)} token IDs for market {market_id} via API")
                        return token_set
                    else:
                        logger.warning(f"⚠️ Unexpected clob_token_ids format for market {market_id}: {type(clob_token_ids)}")
                        return set()
                except Exception as api_error:
                    logger.error(f"❌ Error getting market {market_id} via API: {api_error}")
                    return set()

            # Use DB if SKIP_DB=false
            async with get_db() as db:
                result = await db.execute(
                    select(Market.clob_token_ids)
                    .where(Market.id == market_id)
                )
                row = result.scalar_one_or_none()

            if not row:
                logger.warning(f"⚠️ No clob_token_ids found for market {market_id}")
                return set()

            logger.debug(f"🔍 Raw clob_token_ids for market {market_id}: '{row}' (type: {type(row)})")

            # Handle properly stored JSONB array (single decode now)
            if isinstance(row, str):
                try:
                    # Single JSON decode for properly stored data
                    import json
                    token_ids = json.loads(row)
                    logger.debug(f"🔍 Parsed token_ids: {token_ids} (type: {type(token_ids)})")
                    return {str(tid).strip() for tid in token_ids if tid}
                except json.JSONDecodeError as e:
                    logger.error(f"⚠️ JSON decode error for market {market_id}: {e}")
                    return set()
            # Extract token IDs from JSONB array
            elif isinstance(row, list):
                return {str(tid) for tid in row if tid}
            else:
                logger.warning(f"⚠️ Unexpected clob_token_ids type for market {market_id}: {type(row)}")
                return set()

        except Exception as e:
            logger.warning(f"⚠️ Error getting token IDs for market {market_id}: {e}")
            return set()

    async def _update_market_source_to_ws(self, market_id: str) -> None:
        """
        Update market source to 'ws' after subscription
        This indicates the market is now subscribed to WebSocket

        Args:
            market_id: Market ID
        """
        try:
            if not SKIP_DB:
                from core.database.connection import get_db
                from core.database.models import Market
                from sqlalchemy import update
                async with get_db() as db:
                    await db.execute(
                        update(Market)
                        .where(Market.id == market_id)
                        .values(source='ws')
                    )
                    await db.commit()
                    logger.info(f"✅ Changed market {market_id} source to 'ws' after subscription")
            else:
                # Use API to update market source
                api_client = get_api_client()
                try:
                    response = await api_client.client.put(
                        f"{api_client.base_url}/markets/{market_id}",
                        json={"source": "ws"},
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        logger.info(f"✅ Changed market {market_id} source to 'ws' via API after subscription")
                    else:
                        logger.warning(f"⚠️ Failed to update market {market_id} source via API: {response.status_code}")
                except Exception as api_error:
                    logger.warning(f"⚠️ Error updating market {market_id} source via API: {api_error}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to update market {market_id} source to 'ws': {e}")

    async def _update_market_source_fallback(self, market_id: str, source: str) -> None:
        """
        Fallback method to update market source when API/DB update fails
        Tries to use direct DB connection if available

        Args:
            market_id: Market ID
            source: New source value ('poll' or 'ws')
        """
        try:
            # Try direct DB update if SKIP_DB is false
            if not SKIP_DB:
                from core.database.connection import get_db
                from core.database.models import Market
                from sqlalchemy import update
                async with get_db() as db:
                    await db.execute(
                        update(Market)
                        .where(Market.id == market_id)
                        .values(source=source)
                    )
                    await db.commit()
                    logger.info(f"✅ Fallback: Changed market {market_id} source to '{source}' via direct DB")
            else:
                logger.warning(
                    f"⚠️ Cannot use fallback DB update for market {market_id} "
                    f"(SKIP_DB=true). Source remains unchanged."
                )
        except Exception as e:
            logger.error(f"❌ Fallback update failed for market {market_id}: {e}")

    def get_stats(self) -> dict:
        """Get subscription manager statistics"""
        return {
            "running": self.running,
            "cleanup_interval": self.cleanup_interval,
            "subscribed_markets": len(self.websocket_client.subscribed_token_ids) if self.websocket_client else 0,
        }
