#!/usr/bin/env python3
"""
Background worker entrypoint for Railway deployment.
Starts data ingestion, Redis Pub/Sub, TP/SL monitor, and copy-trading listener.
"""

import asyncio
import logging
import os
import signal
from contextlib import suppress
from typing import Optional

# Defer database import to avoid startup issues
from core.services.cache_manager import CacheManager
from core.services.redis_pubsub import get_redis_pubsub_service
from infrastructure.config.settings import settings
from infrastructure.logging.logger import setup_logging


async def _start_streamer(tasks: list) -> Optional[object]:
    """Start the websocket streamer if enabled."""
    if not settings.data_ingestion.streamer_enabled:
        return None

    from data_ingestion.streamer.streamer import StreamerService
    from core.services.websocket_manager import websocket_manager

    streamer = StreamerService()
    websocket_manager.set_streamer_service(streamer)
    tasks.append(asyncio.create_task(streamer.start(), name="streamer"))
    logging.getLogger(__name__).info("✅ Streamer service launched")
    return streamer


async def _start_tpsl_monitor(tasks: list) -> Optional[object]:
    """Start TP/SL monitor if enabled."""
    if not settings.trading.tpsl_monitoring_enabled:
        return None

    from core.services.trading.tpsl_monitor import TPSLMonitor, set_tpsl_monitor

    check_interval = max(settings.trading.tpsl_check_interval, 30)
    monitor = TPSLMonitor(check_interval=check_interval)
    set_tpsl_monitor(monitor)
    tasks.append(asyncio.create_task(monitor.start(), name="tpsl_monitor"))
    logging.getLogger(__name__).info("✅ TP/SL monitor launched")
    return monitor


async def _start_notification_service(tasks: list) -> Optional[object]:
    """Start notification service for processing queued notifications."""
    try:
        from core.services.notification_service import get_notification_service

        notification_service = get_notification_service()
        await notification_service.start_processing()
        tasks.append(asyncio.create_task(notification_service._process_notifications_loop(), name="notification_processor"))
        logging.getLogger(__name__).info("✅ Notification service launched")
        return notification_service
    except Exception as e:
        logging.getLogger(__name__).error(f"❌ Failed to start notification service: {e}")
        return None


async def _start_copy_trading_listener() -> Optional[object]:
    """Start copy-trading listener."""
    try:
        from data_ingestion.indexer.copy_trading_listener import get_copy_trading_listener

        listener = get_copy_trading_listener()
        await listener.start()
        logging.getLogger(__name__).info("✅ Copy trading listener started")
        return listener
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.getLogger(__name__).error("❌ Failed to start copy trading listener: %s", exc, exc_info=True)
        return None


async def _start_websocket_subscription_listener() -> Optional[object]:
    """Start WebSocket subscription listener."""
    try:
        from data_ingestion.indexer.websocket_subscription_listener import get_websocket_subscription_listener

        listener = get_websocket_subscription_listener()
        await listener.start()
        logging.getLogger(__name__).info("✅ WebSocket subscription listener started")
        return listener
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.getLogger(__name__).error("❌ Failed to start WebSocket subscription listener: %s", exc, exc_info=True)
        return None


async def _start_watched_addresses_sync(tasks: list) -> None:
    """Start periodic cache refresh for watched addresses."""
    from data_ingestion.indexer.watched_addresses.manager import get_watched_addresses_manager

    async def _sync_loop() -> None:
        manager = get_watched_addresses_manager()
        logger = logging.getLogger(__name__)
        while True:
            try:
                await manager.refresh_cache()
                logger.debug("✅ Watched addresses cache refreshed")
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("❌ Watched addresses cache sync failed: %s", exc, exc_info=True)
            await asyncio.sleep(300)

    tasks.append(asyncio.create_task(_sync_loop(), name="watched_addresses_sync"))


async def _start_leader_balance_updater(tasks: list) -> None:
    """Start periodic leader balance updates (hourly)."""
    from core.services.copy_trading.leader_balance_updater import get_leader_balance_updater

    async def _update_loop() -> None:
        updater = get_leader_balance_updater()
        logger = logging.getLogger(__name__)

        # Run immediately on startup, then every hour
        while True:
            try:
                await updater.update_all_leader_balances()
                logger.info("✅ Leader balance update cycle completed")
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("❌ Leader balance update failed: %s", exc, exc_info=True)

            # Wait 1 hour (3600 seconds) before next update
            await asyncio.sleep(3600)

    tasks.append(asyncio.create_task(_update_loop(), name="leader_balance_updater"))


async def _start_market_resolution_detector(tasks: list) -> Optional[object]:
    """Start market resolution detector (checks closed_positions every 20 min)."""
    try:
        from core.services.market.resolution_detector import get_resolution_detector

        detector = get_resolution_detector()
        # start() already creates the detection loop task internally
        await detector.start()
        logging.getLogger(__name__).info("✅ Market Resolution Detector launched")
        return detector
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.getLogger(__name__).error("❌ Failed to start market resolution detector: %s", exc, exc_info=True)
        return None


async def _is_db_empty() -> bool:
    """Check if markets table is empty"""
    try:
        from core.database.connection import get_db
        from sqlalchemy import text

        async with get_db() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM markets"))
            count = result.scalar()
            return count == 0
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not check if DB is empty: {e}")
        return False

async def _start_poller(tasks: list) -> Optional[tuple]:
    """Start Gamma API poller with multiple modes (backfill, discovery, events, resolutions, price)."""
    if not settings.data_ingestion.poller_enabled:
        return None

    # Check if database is initialized (poller requires DB)
    if os.getenv("SKIP_DB", "true").lower() == "true":
        logging.getLogger(__name__).warning("⚠️ Poller requires database but SKIP_DB=true. Skipping poller startup.")
        return None

    # Verify database is actually initialized
    try:
        from core.database.connection import async_session_factory
        if async_session_factory is None:
            logging.getLogger(__name__).error("❌ Database not initialized. Cannot start poller.")
            return None
    except (ImportError, AttributeError):
        logging.getLogger(__name__).error("❌ Cannot verify database initialization. Skipping poller startup.")
        return None

    try:
        # 1. Backfill (one-shot if DB is empty)
        if await _is_db_empty():
            logging.getLogger(__name__).info("📦 Database empty, starting backfill...")
            from data_ingestion.poller.backfill_poller import BackfillPoller
            backfill_poller = BackfillPoller()
            await backfill_poller.backfill_all_active_markets()
            logging.getLogger(__name__).info("✅ Backfill completed")

        # 2. Discovery (2h interval)
        from data_ingestion.poller.discovery_poller import DiscoveryPoller
        discovery_poller = DiscoveryPoller(interval=7200)
        tasks.append(asyncio.create_task(discovery_poller.start_polling(), name="poller_discovery"))

        # 3. Events (30s interval) - now includes featured support
        from data_ingestion.poller.gamma_api import GammaAPIPollerEvents
        events_poller = GammaAPIPollerEvents(interval=30)
        tasks.append(asyncio.create_task(events_poller.start_polling(), name="poller_events"))

        # 4. Resolution (15min interval)
        from data_ingestion.poller.resolutions_poller import GammaAPIPollerResolutions
        resolutions_poller = GammaAPIPollerResolutions(interval=900)
        tasks.append(asyncio.create_task(resolutions_poller.start_polling(), name="poller_resolutions"))

        # 5. Price (30s interval) - layered strategy
        from data_ingestion.poller.price_poller import PricePoller
        price_poller = PricePoller(interval=30)
        tasks.append(asyncio.create_task(price_poller.start_polling(), name="poller_price"))

        # 6. Keyword (5min interval) - priority markets with keywords
        from data_ingestion.poller.keyword_poller import KeywordPoller
        keyword_poller = KeywordPoller(interval=300)
        tasks.append(asyncio.create_task(keyword_poller.start_polling(), name="poller_keyword"))

        logging.getLogger(__name__).info("✅ Poller services launched (backfill, discovery, events, resolutions, price, keyword)")
        return (discovery_poller, events_poller, resolutions_poller, price_poller, keyword_poller)
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.getLogger(__name__).error("❌ Failed to start poller services: %s", exc, exc_info=True)
        return None


async def _run_workers() -> None:
    """Bootstraps all worker services and keeps them alive."""
    setup_logging(__name__)
    logger = logging.getLogger(__name__)

    logger.info("🚀 Starting Polycool worker service")

    # Skip database initialization if network is unreachable
    if os.getenv("SKIP_DB", "true").lower() != "true":
        from core.database.connection import init_db
        try:
            await init_db()
            logger.info("✅ Database initialized")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            logger.warning("⚠️ Continuing without database")
    else:
        logger.warning("⚠️ Database initialization skipped (SKIP_DB=true)")

    cache_manager = CacheManager()
    logger.info("✅ Cache manager ready")

    redis_pubsub = get_redis_pubsub_service()
    redis_connected = await redis_pubsub.connect()
    if redis_connected:
        logger.info("✅ Redis PubSub connected")
    else:
        logger.warning("⚠️ Redis PubSub connection failed at startup (will retry automatically)")

    background_tasks: list[asyncio.Task] = []
    streamer = await _start_streamer(background_tasks)
    tpsl_monitor = await _start_tpsl_monitor(background_tasks)
    notification_service = await _start_notification_service(background_tasks)

    # Start Copy Trading Listener (requires Redis PubSub)
    # The listener will use the same Redis PubSub service instance (singleton)
    if redis_connected:
        logger.info("🚀 Starting Copy Trading Listener (Redis PubSub is connected)")
        copy_trading_listener = await _start_copy_trading_listener()
        if copy_trading_listener:
            logger.info("✅ Copy Trading Listener started successfully")
        else:
            logger.warning("⚠️ Copy Trading Listener failed to start (will retry on next trade)")
    else:
        logger.warning("⚠️ Skipping Copy Trading Listener startup (Redis PubSub not connected)")
        copy_trading_listener = None
    websocket_subscription_listener = await _start_websocket_subscription_listener()
    await _start_watched_addresses_sync(background_tasks)
    await _start_leader_balance_updater(background_tasks)
    resolution_detector = await _start_market_resolution_detector(background_tasks)
    pollers = await _start_poller(background_tasks)

    stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        logger.info("⚠️ Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    try:
        logger.info("✅ Worker services running")
        await stop_event.wait()
    finally:
        logger.info("🛑 Stopping worker services")

        # Stop pollers
        if pollers:
            discovery_poller, events_poller, resolutions_poller, price_poller, keyword_poller = pollers
            with suppress(Exception):
                await discovery_poller.stop_polling()
            with suppress(Exception):
                await events_poller.stop_polling()
            with suppress(Exception):
                await resolutions_poller.stop_polling()
            with suppress(Exception):
                await price_poller.stop_polling()
            with suppress(Exception):
                await keyword_poller.stop_polling()

        if copy_trading_listener:
            with suppress(Exception):
                await copy_trading_listener.stop()

        if websocket_subscription_listener:
            with suppress(Exception):
                await websocket_subscription_listener.stop()

        if resolution_detector:
            with suppress(Exception):
                await resolution_detector.stop()

        if tpsl_monitor:
            with suppress(Exception):
                await tpsl_monitor.stop()

        if notification_service:
            with suppress(Exception):
                await notification_service.stop_processing()

        if streamer:
            with suppress(Exception):
                await streamer.stop()

        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task

        with suppress(Exception):
            await redis_pubsub.disconnect()

        cache_manager.redis.close()
        cache_manager.redis.connection_pool.disconnect()


def main() -> None:
    """Launch the async worker runner."""
    asyncio.run(_run_workers())


if __name__ == "__main__":
    main()
