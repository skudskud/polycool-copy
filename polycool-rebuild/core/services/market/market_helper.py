"""
Market Helper Functions
Shared utilities for getting market data that work with both SKIP_DB=true and SKIP_DB=false
"""
import os
from typing import Optional, Dict, Any

from core.services.market_service import get_market_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client

# Import ContextTypes only when needed (for type hints)
try:
    from telegram.ext import ContextTypes
except ImportError:
    # Fallback if telegram is not available (e.g., in services)
    ContextTypes = None


async def get_market_data(
    market_id: str,
    context: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """
    Get market data - uses API client if SKIP_DB=true, otherwise direct DB access

    Args:
        market_id: Market identifier
        context: Optional Telegram context for cache_manager access
                 Can be ContextTypes.DEFAULT_TYPE or None

    Returns:
        Market dict or None if not found
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.get_market(market_id)
    else:
        # Get cache manager from context if available
        cache_manager = None
        if context and hasattr(context, 'bot'):
            if hasattr(context.bot, 'application'):
                if hasattr(context.bot.application, 'bot_data'):
                    cache_manager = context.bot.application.bot_data.get('cache_manager')

        market_service = get_market_service(cache_manager=cache_manager)
        return await market_service.get_market_by_id(market_id)


async def get_markets_data(
    market_ids: list[str],
    context: Optional[Any] = None
) -> list[Dict[str, Any]]:
    """
    Get multiple market data in batch - optimized for performance

    Args:
        market_ids: List of market identifiers
        context: Optional Telegram context for cache_manager access

    Returns:
        List of market dicts (may be fewer than requested if some not found)
    """
    if not market_ids:
        return []

    if SKIP_DB:
        # For API mode, use batch endpoint for better performance
        api_client = get_api_client()
        try:
            # Use batch endpoint if available (optimized)
            markets = await api_client.get_markets_batch(market_ids, use_cache=True)
            if markets:
                logger.debug(f"✅ Fetched {len(markets)} markets in batch via API")
                return markets
            else:
                # Fallback to empty list if batch returns None
                logger.warning(f"⚠️ Batch endpoint returned None, falling back to individual calls")
                markets = []
                for market_id in market_ids:
                    try:
                        market = await api_client.get_market(market_id)
                        if market:
                            markets.append(market)
                    except Exception as e:
                        logger.warning(f"Failed to get market {market_id}: {e}")
                return markets
        except Exception as e:
            logger.warning(f"⚠️ Batch endpoint failed: {e}, falling back to individual calls")
            # Fallback to individual calls on error
            markets = []
            for market_id in market_ids:
                try:
                    market = await api_client.get_market(market_id)
                    if market:
                        markets.append(market)
                except Exception as e:
                    logger.warning(f"Failed to get market {market_id}: {e}")
            return markets
    else:
        # Get cache manager from context if available
        cache_manager = None
        if context and hasattr(context, 'bot'):
            if hasattr(context.bot, 'application'):
                if hasattr(context.bot.application, 'bot_data'):
                    cache_manager = context.bot.application.bot_data.get('cache_manager')

        market_service = get_market_service(cache_manager=cache_manager)

        # Use batch method if available, otherwise fallback to individual calls
        if hasattr(market_service, 'get_markets_by_ids'):
            return await market_service.get_markets_by_ids(market_ids)
        else:
            # Fallback to individual calls
            markets = []
            for market_id in market_ids:
                try:
                    market = await market_service.get_market_by_id(market_id)
                    if market:
                        markets.append(market)
                except Exception as e:
                    logger.warning(f"Failed to get market {market_id}: {e}")
            return markets
