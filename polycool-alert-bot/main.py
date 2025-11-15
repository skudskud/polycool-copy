"""
Polycool Alert Bot - Main Entry Point
Monitors smart wallet trades and sends Telegram alerts
"""

import asyncio
import sys
from utils.logger import logger
from config import validate_config, BOT_USERNAME, DRY_RUN
from core.database import db
from core.poller import poller
from core.health import health_monitor


async def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("🚀 Polycool Alert Bot Starting...")
    logger.info("=" * 60)
    
    try:
        # Validate configuration
        logger.info("📋 Validating configuration...")
        validate_config()
        logger.info(f"✅ Configuration valid")
        logger.info(f"   Bot: {BOT_USERNAME}")
        logger.info(f"   Dry Run: {DRY_RUN}")
        
        # Connect to database
        logger.info("🔌 Connecting to database...")
        db.connect()
        logger.info("✅ Database connected")
        
        # Health check
        logger.info("🏥 Running health check...")
        health_monitor.log_health()
        
        # Start poller
        logger.info("🔄 Starting poller...")
        await poller.start()
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Shutdown signal received")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("=" * 60)
        logger.info("👋 Polycool Alert Bot Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

