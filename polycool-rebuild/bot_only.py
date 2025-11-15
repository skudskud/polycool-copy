#!/usr/bin/env python3
"""
Telegram bot entrypoint for Railway deployment.
Starts the Telegram bot without the FastAPI application or data ingestion workers.
"""

import asyncio
import logging
import os
import signal

# Skip database import for now
# from core.database.connection import init_db
from core.services.cache_manager import CacheManager
from infrastructure.config.settings import settings
from infrastructure.logging.logger import setup_logging
from telegram_bot.bot.application import TelegramBotApplication
import httpx


async def _run_bot() -> None:
    """Initialize dependencies and keep the Telegram bot running."""
    setup_logging(__name__)
    logger = logging.getLogger(__name__)

    logger.info("🚀 Starting Polycool Telegram bot service")

    # Check if bot should initialize database
    # With SKIP_DB=true, bot should NOT initialize DB - all data access goes through API
    SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

    if not SKIP_DB:
        # Only initialize DB if SKIP_DB=false (for local development/testing)
        from core.database.connection import init_db
        try:
            await init_db()
            logger.info("✅ Database initialized")
        except Exception as e:
            logger.warning(f"⚠️ Database initialization failed: {e}")
            logger.warning("⚠️ Some features requiring database access may not work")
    else:
        logger.info("⚠️ Database initialization skipped (SKIP_DB=true) - bot will use API client for all data access")

        # Verify API service is available (critical for bot operation)
        api_url = settings.api_url.rstrip('/')
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{api_url}/health/live")
                if response.status_code == 200:
                    logger.info(f"✅ API service is healthy ({api_url})")
                else:
                    logger.warning(f"⚠️ API service health check returned {response.status_code}")
        except Exception as e:
            logger.error(f"❌ API service health check failed: {e}")
            logger.error(f"⚠️ Bot may not function correctly if API is unavailable")
            # Don't fail startup - bot can retry API calls later with circuit breaker

    cache_manager = CacheManager()
    logger.info("✅ Cache manager ready")

    # Start streamer if enabled (for WebSocket support)
    streamer = None
    if settings.data_ingestion.streamer_enabled:
        logger.info(f"🔍 STREAMER_ENABLED=true - Initializing streamer in bot_only.py...")
        from data_ingestion.streamer.streamer import StreamerService
        from core.services.websocket_manager import websocket_manager

        streamer = StreamerService()

        # Connect WebSocketManager to streamer
        websocket_manager.set_streamer_service(streamer)

        # Verify connection
        if websocket_manager.streamer is None:
            logger.error("❌ WebSocketManager not connected to streamer after set_streamer_service!")
        else:
            logger.info("✅ WebSocketManager connected to streamer")

        # Start streamer in background
        asyncio.create_task(streamer.start())
        logger.info("✅ Streamer service started in background")
    else:
        logger.info("⚠️ Streamer disabled (STREAMER_ENABLED=false) - WebSocket features unavailable")

    logger.info("🚀 Initializing Telegram bot application...")
    bot_app = TelegramBotApplication()
    logger.info("✅ TelegramBotApplication created")

    logger.info("🚀 Starting Telegram bot application...")
    await bot_app.start()
    logger.info("✅ Telegram bot application started successfully")

    stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        logger.info("⚠️ Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows compatibility (signals not supported)
            pass

    try:
        logger.info("✅ Telegram bot running")
        await stop_event.wait()
    finally:
        logger.info("🛑 Stopping Telegram bot service")
        await bot_app.stop()

        # Stop streamer if it was started
        if streamer:
            try:
                await streamer.stop()
                logger.info("✅ Streamer service stopped")
            except Exception as e:
                logger.warning(f"⚠️ Error stopping streamer: {e}")

        cache_manager.redis.close()
        cache_manager.redis.connection_pool.disconnect()


def main() -> None:
    """Launch the async bot runner."""
    asyncio.run(_run_bot())


if __name__ == "__main__":
    main()
