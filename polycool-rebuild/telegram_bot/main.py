"""
Polycool Telegram Bot - Main FastAPI Application
"""
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from infrastructure.config.settings import settings
import logging
from infrastructure.logging.logger import setup_logging
from infrastructure.monitoring.health_checks import router as health_router
from telegram_bot.api.routes import api_router
from telegram_bot.bot.application import TelegramBotApplication


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager"""

    # Setup logging first
    setup_logging(__name__)

    logger = logging.getLogger(__name__)

    # Startup
    logger.info("🚀 Starting Polycool Telegram Bot")

    # Initialize database (skip if SKIP_DB=true for local VPN testing)
    import os
    from infrastructure.config.settings import settings
    logger.info(f"🔍 Database URL: {settings.database.effective_url}")
    if os.getenv("SKIP_DB", "false").lower() != "true":
        from core.database.connection import init_db
        await init_db()
        logger.info("✅ Database initialized")
    else:
        logger.warning("⚠️ Database initialization SKIPPED (SKIP_DB=true)")

    # Initialize cache
    from core.services.cache_manager import CacheManager
    app.state.cache = CacheManager()

    # Start data ingestion services
    logger.info(f"🔍 Data ingestion config: poller={settings.data_ingestion.poller_enabled}, streamer={settings.data_ingestion.streamer_enabled}")

    if settings.data_ingestion.poller_enabled:
        from data_ingestion.poller.gamma_api import GammaAPIPollerCorrected

        poller = GammaAPIPollerCorrected()
        app.state.poller = poller

        asyncio.create_task(poller.start_polling())
        logger.info("✅ Gamma API Poller started")
    else:
        logger.info("⚠️ Poller disabled (POLLER_ENABLED=false)")

    if settings.data_ingestion.streamer_enabled:
        logger.info("🔍 STREAMER_ENABLED=true - Initializing streamer...")
        from data_ingestion.streamer.streamer import StreamerService
        from core.services.websocket_manager import websocket_manager

        streamer = StreamerService()
        app.state.streamer = streamer

        # Connect WebSocketManager to streamer
        websocket_manager.set_streamer_service(streamer)
        app.state.websocket_manager = websocket_manager

        # Verify connection
        if websocket_manager.streamer is None:
            logger.error("❌ WebSocketManager not connected to streamer after set_streamer_service!")
        else:
            logger.info("✅ WebSocketManager connected to streamer")

        asyncio.create_task(streamer.start())
        logger.info("✅ WebSocketManager initialized with StreamerService")

    # Indexer not yet implemented
    # if settings.data_ingestion.indexer_enabled:
    #     from data_ingestion.indexer.watched_addresses import AddressIndexer
    #     indexer = AddressIndexer()
    #     app.state.indexer = indexer
    #     asyncio.create_task(indexer.start_indexing())

    # Start Telegram bot (non-blocking, same event loop)
    bot_app = TelegramBotApplication()
    app.state.bot = bot_app
    # Start bot in background task (non-blocking)
    asyncio.create_task(bot_app.start())
    logger.info("✅ Telegram bot started in background")

    # Start Redis PubSub Service (for copy trading events)
    try:
        from core.services.redis_pubsub import get_redis_pubsub_service
        redis_pubsub = get_redis_pubsub_service()
        connected = await redis_pubsub.connect()
        if connected:
            app.state.redis_pubsub = redis_pubsub
            logger.info("✅ Redis PubSub Service connected")
        else:
            logger.warning("⚠️ Redis PubSub Service connection failed (will retry on demand)")
    except Exception as e:
        logger.error(f"❌ Failed to start Redis PubSub Service: {e}", exc_info=True)
        # Non-blocking: Continue even if Redis fails

    # Start TP/SL Monitor if enabled (reduced frequency to avoid DB pool exhaustion)
    if settings.trading.tpsl_monitoring_enabled:
        from core.services.trading.tpsl_monitor import TPSLMonitor, set_tpsl_monitor
        # Increase check interval to 30 seconds to reduce DB load
        check_interval = max(settings.trading.tpsl_check_interval, 30)
        tpsl_monitor = TPSLMonitor(check_interval=check_interval)
        set_tpsl_monitor(tpsl_monitor)
        app.state.tpsl_monitor = tpsl_monitor
        asyncio.create_task(tpsl_monitor.start())
        logger.info(f"✅ TP/SL Monitor started (check interval: {check_interval}s)")

    # Start Copy Trading Listener (for instant copy trading via Redis PubSub)
    try:
        from data_ingestion.indexer.copy_trading_listener import get_copy_trading_listener
        copy_trading_listener = get_copy_trading_listener()
        app.state.copy_trading_listener = copy_trading_listener
        await copy_trading_listener.start()
        logger.info("✅ Copy Trading Listener started")
    except Exception as e:
        logger.error(f"❌ Failed to start Copy Trading Listener: {e}", exc_info=True)
        # Non-blocking: Continue even if listener fails (fallback to polling)

    # Start Watched Addresses Cache Sync (background job - syncs every 1 minute)
    try:
        from data_ingestion.indexer.watched_addresses.manager import get_watched_addresses_manager

        async def sync_watched_addresses_cache():
            """Background task to sync watched_addresses to Redis cache"""
            manager = get_watched_addresses_manager()
            while True:
                try:
                    await manager.refresh_cache()
                    await asyncio.sleep(300)  # Sync every 5 minutes (reduced frequency)
                except Exception as e:
                    logger.error(f"❌ Error syncing watched addresses cache: {e}", exc_info=True)
                    await asyncio.sleep(300)  # Retry after 5 minutes on error

        asyncio.create_task(sync_watched_addresses_cache())
        logger.info("✅ Watched Addresses Cache Sync started (every 5 minutes)")
    except Exception as e:
        logger.error(f"❌ Failed to start Watched Addresses Cache Sync: {e}", exc_info=True)
        # Non-blocking: Continue even if sync fails

    logger.info("✅ All services started successfully")

    yield

    # Shutdown
    logger.info("🛑 Shutting down Polycool Telegram Bot")

    # Stop services
    if hasattr(app.state, 'bot'):
        await app.state.bot.stop()

    if hasattr(app.state, 'poller'):
        await app.state.poller.stop_polling()

    if hasattr(app.state, 'streamer'):
        await app.state.streamer.stop()

    if hasattr(app.state, 'tpsl_monitor'):
        await app.state.tpsl_monitor.stop()

    # Stop Copy Trading Listener
    if hasattr(app.state, 'copy_trading_listener'):
        await app.state.copy_trading_listener.stop()

    # Disconnect Redis PubSub
    if hasattr(app.state, 'redis_pubsub'):
        await app.state.redis_pubsub.disconnect()
        logger.info("✅ Redis PubSub disconnected")

    # Indexer not yet implemented
    # if hasattr(app.state, 'indexer'):
    #     await app.state.indexer.stop()

    logger.info("✅ All services stopped successfully")


# Create FastAPI app
app = FastAPI(
    title=settings.name,
    version=settings.version,
    description="Telegram bot for Polymarket trading with real-time data",
    lifespan=lifespan,
    debug=settings.debug,
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not settings.is_development:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"],  # Configure for production
    )

# Include routers
app.include_router(
    health_router,
    prefix="/health",
    tags=["health"],
)

app.include_router(
    api_router,
    prefix=settings.api_prefix,
)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.name,
        "version": settings.version,
        "environment": settings.environment,
        "status": "running"
    }

# Webhook endpoint for Telegram
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Handle Telegram webhook updates"""
    if hasattr(request.app.state, 'bot'):
        data = await request.json()
        await request.app.state.bot.process_update(data)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "telegram_bot.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Désactivé pour éviter les restarts automatiques pendant les tests
        log_level=settings.logging.level.lower(),
    )
