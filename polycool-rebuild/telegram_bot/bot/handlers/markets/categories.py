"""
Markets Categories Module
Handles category browsing and filtering
"""
import os
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from infrastructure.logging.logger import get_logger
from telegram_bot.bot.handlers.markets.formatters import build_markets_list_ui

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client
else:
    from core.services.market_service import get_market_service


async def handle_category_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle category selection callback
    Format: "cat_geopolitics_0"
    """
    try:
        # Parse: "cat_geopolitics_0"
        parts = callback_data.split("_")
        category_key = parts[1].lower()  # Keep lowercase for API/callbacks
        category_display = parts[1].capitalize()  # For display: geopolitics -> Geopolitics
        page = int(parts[2])

        # Store in context (use lowercase for consistency)
        context.user_data['last_category'] = category_key

        # Use API client in SKIP_DB mode
        if SKIP_DB:
            api_client = get_api_client()
            markets = await api_client.get_category_markets(
                category=category_display,  # API expects capitalized
                page=page,
                page_size=9,
                filter_type='volume'
            )
        else:
            # Get cache manager
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            market_service = get_market_service(cache_manager=cache_manager)
            markets, _ = await market_service.get_category_markets(
                category=category_display,  # API expects capitalized
                page=page,
                page_size=9,
                group_by_events=True,
                filter_type='volume'
            )

        if not markets:
            await query.edit_message_text(f"❌ No markets found in {category_display}")
            return

        message_text, keyboard = build_markets_list_ui(
            markets=markets,
            page=page,
            view_type='category',
            context_name=category_key,  # Use lowercase for callbacks consistency
            filter_type='volume'
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in category callback: {e}")
        await query.edit_message_text("❌ Error loading category markets")


async def handle_category_filter_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle category filter callback
    Format: "catfilter_geopolitics_volume_0"
    """
    try:
        # Parse: "catfilter_geopolitics_volume_0"
        parts = callback_data.split("_")
        category_key = parts[1].lower()  # Keep lowercase for callbacks
        category_display = parts[1].capitalize()  # For API: geopolitics -> Geopolitics
        filter_type = parts[2]
        page = int(parts[3])

        # Use API client in SKIP_DB mode
        if SKIP_DB:
            api_client = get_api_client()
            markets = await api_client.get_category_markets(
                category=category_display,  # API expects capitalized
                page=page,
                page_size=9,
                filter_type=filter_type
            )
        else:
            # Get cache manager
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            market_service = get_market_service(cache_manager=cache_manager)
            markets, _ = await market_service.get_category_markets(
                category=category_display,  # API expects capitalized
                page=page,
                page_size=9,
                group_by_events=True,
                filter_type=filter_type
            )

        if not markets:
            await query.edit_message_text(f"❌ No markets found")
            return

        message_text, keyboard = build_markets_list_ui(
            markets=markets,
            page=page,
            view_type='category',
            context_name=category_key,  # Use lowercase for callbacks consistency
            filter_type=filter_type
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in category filter callback: {e}")
        await query.edit_message_text("❌ Error loading markets")
