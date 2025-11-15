"""
WebSocket Streamer Service
Main service that orchestrates WebSocket client, subscription manager, and market updater
"""
import asyncio
from typing import Optional

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from .websocket_client import WebSocketClient
from .market_updater import MarketUpdater
from .subscription_manager import SubscriptionManager

logger = get_logger(__name__)


class StreamerService:
    """
    Main WebSocket Streamer Service
    Orchestrates WebSocket client, subscription manager, and market updater
    """

    def __init__(self):
        self.enabled = settings.data_ingestion.streamer_enabled
        logger.info(f"🔍 StreamerService.__init__() - enabled={self.enabled}, settings.streamer_enabled={settings.data_ingestion.streamer_enabled}")
        self.websocket_client = WebSocketClient()
        self.market_updater = MarketUpdater()
        self.subscription_manager = SubscriptionManager(self.websocket_client, self.market_updater)
        self.running = False

    async def start(self) -> None:
        """Start the streamer service"""
        logger.info(f"🔍 StreamerService.start() called - enabled={self.enabled}")
        if not self.enabled:
            logger.warning("⚠️ Streamer service disabled (STREAMER_ENABLED=false)")
            logger.warning(f"   self.enabled={self.enabled}, settings.data_ingestion.streamer_enabled={settings.data_ingestion.streamer_enabled}")
            return

        logger.info("🌐 Streamer Service starting...")
        self.running = True

        # Register message handlers
        self.websocket_client.register_handler("price_update", self.market_updater.handle_price_update)
        self.websocket_client.register_handler("orderbook", self.market_updater.handle_orderbook_update)
        self.websocket_client.register_handler("trade", self.market_updater.handle_trade_update)
        self.websocket_client.register_handler("market", self.market_updater.handle_price_update)

        # Start market updater (starts price buffer)
        await self.market_updater.start()

        # Start subscription manager
        await self.subscription_manager.start()

        # Check if we have active positions before starting WebSocket
        has_active_positions = await self._check_active_positions()

        if has_active_positions:
            logger.info("✅ Active positions found - starting WebSocket client")
            # Subscribe to active positions
            await self.subscription_manager.subscribe_active_positions()
            # Start WebSocket client
            await self.websocket_client.start()
        else:
            logger.info("⚠️ No active positions - streamer will wait for trades")
            # Don't start WebSocket client yet
            # It will be started when on_trade_executed is called

    async def stop(self) -> None:
        """Stop the streamer service"""
        logger.info("⏹️ Streamer Service stopping...")
        self.running = False

        await self.subscription_manager.stop()
        await self.websocket_client.stop()
        await self.market_updater.stop()

        logger.info("✅ Streamer Service stopped")

    async def on_trade_executed(self, user_id: int, market_id: str) -> None:
        """
        Notify streamer that a trade was executed
        Start WebSocket if it's not running

        Args:
            user_id: User ID who executed the trade
            market_id: Market ID where trade was executed
        """
        try:
            logger.info(f"📡 Trade executed for market {market_id} - checking if WebSocket needs to start")
            logger.debug(f"   WebSocket client running: {getattr(self.websocket_client, 'running', False)}")

            # Subscribe to the market
            await self.subscription_manager.on_trade_executed(user_id, market_id)

            # Check if WebSocket client is running
            if not hasattr(self.websocket_client, 'running') or not self.websocket_client.running:
                logger.info("🚀 Starting WebSocket client after first trade")
                # Start WebSocket client in background
                asyncio.create_task(self.websocket_client.start())
                logger.info("✅ WebSocket client start task created")
            else:
                logger.debug(f"✅ WebSocket client already running")

        except Exception as e:
            logger.error(f"❌ Error in on_trade_executed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def _check_active_positions(self) -> bool:
        """Check if there are any active positions"""
        try:
            import os
            skip_db = os.getenv("SKIP_DB", "false").lower() == "true"

            if skip_db:
                # When SKIP_DB=true, try to check via API instead
                logger.info("🔍 SKIP_DB=true - checking active positions via API")
                try:
                    from core.services.api_client import get_api_client
                    api_client = get_api_client()

                    # Try to get positions for a known user (user_id=1)
                    # This is a workaround - ideally we'd check all users
                    positions_data = await api_client.get_user_positions(1, use_cache=False)
                    if positions_data:
                        positions_list = positions_data.get('positions', [])
                        active_count = len([p for p in positions_list if p.get('status') == 'active' and p.get('amount', 0) > 0])
                        logger.info(f"📊 Found {active_count} active positions via API")
                        return active_count > 0
                    return False
                except Exception as api_error:
                    logger.warning(f"⚠️ Could not check positions via API: {api_error}")
                    # Fallback: assume no positions (WebSocket will start after first trade)
                    return False

            # Normal DB check
            from core.database.connection import get_db
            from core.database.models import Position
            from sqlalchemy import select, func

            async with get_db() as db:
                result = await db.execute(
                    select(func.count(Position.id))
                    .where(Position.status == "active")
                )
                count = result.scalar() or 0
                return count > 0
        except Exception as e:
            logger.error(f"Error checking active positions: {e}")
            return False

    async def on_position_closed(self, user_id: int, market_id: str) -> None:
        """
        Notify streamer that a position was closed
        This will check if unsubscribe is needed

        Args:
            user_id: User ID who closed the position
            market_id: Market ID where position was closed
        """
        await self.subscription_manager.on_position_closed(user_id, market_id)

    def get_stats(self) -> dict:
        """Get streamer service statistics"""
        return {
            "enabled": self.enabled,
            "running": self.running,
            "websocket": self.websocket_client.get_stats(),
            "subscription_manager": self.subscription_manager.get_stats(),
            "market_updater": self.market_updater.get_stats(),
        }
