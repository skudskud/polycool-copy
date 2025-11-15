"""
Subsquid Silo Tests - Main Entry Point
Orchestrates all services: poller, streamer, webhook, bridge, indexer
"""

import asyncio
import logging
import sys
import signal
from typing import List

from .config import settings, log_configuration, validate_experimental_subsquid
from .polling.poller import get_poller
from .db.client import get_db_client, close_db_client

logger = logging.getLogger(__name__)


async def main():
    """Main async entry point"""
    
    # Configure logging
    logging.basicConfig(
        format=settings.LOG_FORMAT,
        level=settings.LOG_LEVEL
    )
    
    # Validate feature flag
    validate_experimental_subsquid()
    
    # Log configuration
    log_configuration()
    
    # Initialize database
    try:
        db = await get_db_client()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        sys.exit(1)
    
    # Start services
    tasks: List[asyncio.Task] = []
    
    try:
        # Start Poller (Gamma API)
        if settings.POLLER_ENABLED:
            logger.info("🚀 Starting Poller service...")
            poller = await get_poller()
            poller_task = asyncio.create_task(poller.start())
            tasks.append(poller_task)
        
        # TODO: Phase 5 - Start WebSocket Streamer
        # TODO: Phase 6 - Start Webhook Worker
        # TODO: Phase 7 - Start Redis Bridge
        # TODO: Phase 8 - Start DipDup Indexer
        
        logger.info(f"✅ Started {len(tasks)} services")
        
        # Wait for all tasks
        if tasks:
            await asyncio.gather(*tasks)
        else:
            logger.warning("⚠️ No services enabled")
    
    except KeyboardInterrupt:
        logger.info("⏹️ Shutting down...")
    
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)
    
    finally:
        # Clean up
        for task in tasks:
            if not task.done():
                task.cancel()
        
        # Close database
        await close_db_client()
        logger.info("✅ Cleanup complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Application stopped")
        sys.exit(0)
