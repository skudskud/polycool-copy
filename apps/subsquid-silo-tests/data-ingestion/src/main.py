#!/usr/bin/env python3
"""
Main entry point for Subsquid Silo Data Ingestion
Coordinates Poller, Streamer, Webhook Worker, and Redis Bridge
"""

import asyncio
import logging
import signal
from typing import List

from .config import settings, validate_experimental_subsquid, log_configuration
from .polling.poller import get_poller
from .ws.streamer import get_streamer
from .ws.watched_markets_api import get_watched_markets_api
from .wh.webhook_worker import get_webhook_worker
from .redis.bridge import get_bridge

logger = logging.getLogger(__name__)


class DataIngestionCoordinator:
    """Coordinates all data ingestion services"""

    def __init__(self):
        self.services = []
        self.running = False

    async def start_all(self):
        """Start all data ingestion services"""
        logger.info("🚀 Starting Subsquid Silo Data Ingestion...")

        # Validate configuration
        validate_experimental_subsquid()
        log_configuration()

        # Start services based on configuration
        if settings.POLLER_ENABLED:
            poller = await get_poller()
            await poller.start()
            self.services.append(("Poller", poller))
            logger.info("✅ Poller started")

        if settings.STREAMER_ENABLED:
            streamer = await get_streamer()
            await streamer.start()
            self.services.append(("Streamer", streamer))
            logger.info("✅ Streamer started")

            # Start watched markets API alongside streamer
            watched_api = await get_watched_markets_api()
            await watched_api.start()
            self.services.append(("Watched Markets API", watched_api))
            logger.info("✅ Watched Markets API started")

        if settings.WEBHOOK_ENABLED:
            webhook_worker = await get_webhook_worker()
            await webhook_worker.start()
            self.services.append(("Webhook Worker", webhook_worker))
            logger.info("✅ Webhook Worker started")

        if settings.BRIDGE_ENABLED:
            bridge = await get_bridge()
            await bridge.start()
            self.services.append(("Redis Bridge", bridge))
            logger.info("✅ Redis Bridge started")

        self.running = True
        logger.info(f"🎉 All services started! Running: {len(self.services)} services")

        # Keep running until interrupted
        try:
            while self.running:
                await asyncio.sleep(1)
                # Could add health checks here
        except KeyboardInterrupt:
            logger.info("⏹️ Received shutdown signal")
        finally:
            await self.stop_all()

    async def stop_all(self):
        """Stop all services gracefully"""
        logger.info("🛑 Stopping all services...")

        for service_name, service in reversed(self.services):
            try:
                if hasattr(service, 'stop'):
                    await service.stop()
                logger.info(f"✅ {service_name} stopped")
            except Exception as e:
                logger.error(f"❌ Error stopping {service_name}: {e}")

        self.services.clear()
        logger.info("🎯 All services stopped")


async def main():
    """Main entry point"""
    coordinator = DataIngestionCoordinator()

    # Handle graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"📡 Received signal {signum}, initiating shutdown...")
        coordinator.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await coordinator.start_all()
    except Exception as e:
        logger.error(f"❌ Fatal error in data ingestion: {e}")
        raise
    finally:
        logger.info("👋 Data ingestion coordinator shutting down")


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        format=settings.LOG_FORMAT,
        level=settings.LOG_LEVEL
    )
    
    # Silence httpx INFO logs (HTTP requests spam)
    logging.getLogger('httpx').setLevel(logging.WARNING)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Data ingestion stopped")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        exit(1)
