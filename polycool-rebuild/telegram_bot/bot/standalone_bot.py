#!/usr/bin/env python3
"""
Standalone Telegram Bot Process
Runs the bot in a separate process to avoid event loop conflicts with FastAPI
"""
import asyncio
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, project_root)

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from telegram_bot.bot.application import TelegramBotApplication

logger = get_logger(__name__)

async def main():
    """Main bot function"""
    try:
        logger.info("🤖 Starting standalone Telegram bot...")

        # Create and start bot
        bot_app = TelegramBotApplication()
        await bot_app.start()

        logger.info("✅ Standalone bot started successfully")

        # Keep running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("🛑 Bot stopping...")
        if hasattr(bot_app, 'stop'):
            await bot_app.stop()
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
