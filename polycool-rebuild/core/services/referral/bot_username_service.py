"""
Bot Username Service
Manages bot username dynamically with caching
"""
import os
from typing import Optional
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from core.services.cache_manager import CacheManager

logger = get_logger(__name__)

# Cache key for bot username
BOT_USERNAME_CACHE_KEY = "bot:username"
BOT_USERNAME_CACHE_TTL = 3600  # 1 hour


class BotUsernameService:
    """
    Service for managing bot username dynamically
    - Falls back to BOT_USERNAME env var
    - Caches in Redis (1h TTL)
    - Can be refreshed via bot.get_me() if needed
    """

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        """Initialize bot username service"""
        self.cache_manager = cache_manager or CacheManager()
        self._default_username = os.getenv("BOT_USERNAME", "@Polycool_bot")

    async def get_bot_username(self) -> str:
        """
        Get bot username with caching

        Returns:
            Bot username (e.g., "@Polycool_bot")
        """
        try:
            # Try cache first
            cached_username = await self.cache_manager.get(
                BOT_USERNAME_CACHE_KEY,
                data_type="user_profile"
            )

            if cached_username:
                logger.debug(f"Bot username from cache: {cached_username}")
                return cached_username

            # Fallback to env var or default
            username = self._default_username
            logger.info(f"Using bot username from env/default: {username}")

            # Cache it
            await self.cache_manager.set(
                BOT_USERNAME_CACHE_KEY,
                username,
                data_type="user_profile",
                ttl=BOT_USERNAME_CACHE_TTL
            )

            return username

        except Exception as e:
            logger.warning(f"Error getting bot username from cache: {e}")
            return self._default_username

    async def set_bot_username(self, username: str) -> None:
        """
        Set bot username (from bot.get_me() for example)

        Args:
            username: Bot username (with or without @)
        """
        try:
            # Ensure @ prefix
            if not username.startswith("@"):
                username = f"@{username}"

            # Update cache
            await self.cache_manager.set(
                BOT_USERNAME_CACHE_KEY,
                username,
                data_type="user_profile",
                ttl=BOT_USERNAME_CACHE_TTL
            )

            logger.info(f"Bot username updated: {username}")

        except Exception as e:
            logger.error(f"Error setting bot username: {e}")

    async def refresh_bot_username(self, bot_instance=None) -> str:
        """
        Refresh bot username from Telegram API

        Args:
            bot_instance: Optional Telegram bot instance to call get_me()

        Returns:
            Updated bot username
        """
        try:
            if bot_instance:
                # Get from Telegram API
                bot_info = await bot_instance.get_me()
                username = bot_info.username
                if username:
                    await self.set_bot_username(username)
                    return f"@{username}"

            # Fallback to default
            return await self.get_bot_username()

        except Exception as e:
            logger.warning(f"Error refreshing bot username from API: {e}")
            return await self.get_bot_username()


# Singleton instance
_bot_username_service: Optional[BotUsernameService] = None


def get_bot_username_service(cache_manager: Optional[CacheManager] = None) -> BotUsernameService:
    """Get singleton bot username service instance"""
    global _bot_username_service
    if _bot_username_service is None:
        _bot_username_service = BotUsernameService(cache_manager)
    return _bot_username_service
