"""
Markets Search Module
Handles market search functionality
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


async def handle_search_trigger(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle search trigger - prompt for search query
    """
    await query.edit_message_text(
        "🔍 **Search Markets**\n\n"
        "Please enter your search query:",
        parse_mode='Markdown'
    )
    # Store that we're waiting for search input
    context.user_data['awaiting_search'] = True


async def handle_search_page_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle search pagination callback
    Format: "search_page_{page}" - query is stored in user_data
    """
    try:
        # Parse: "search_page_{page}"
        # Query is stored in context.user_data to avoid parsing issues with underscores
        parts = callback_data.split("_")
        if len(parts) >= 3:
            page = int(parts[-1])
        else:
            page = 0

        # Get search query from context (stored when user first searches)
        search_query = context.user_data.get('last_search_query')
        if not search_query:
            await query.edit_message_text("❌ No search query found. Please search again.")
            return

        # Use API client in SKIP_DB mode
        if SKIP_DB:
            api_client = get_api_client()
            markets = await api_client.search_markets(
                query=search_query,
                page=page,
                page_size=9,  # Match page_size used in formatters
                group_by_events=True
            )
            # Check if rate limited (returns None)
            if markets is None:
                await query.edit_message_text("⏱️ Search rate limit exceeded. Please wait before requesting more results.")
                return

            # Get total_count from cache
            total_count = None
            if api_client.cache_manager:
                query_safe = search_query.replace('/', '_').replace(':', '_')
                total_count_key = f"api:markets:search:total_count:{query_safe}:true"
                total_count = await api_client.cache_manager.get(total_count_key, 'metadata')
        else:
            # Get cache manager
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            market_service = get_market_service(cache_manager=cache_manager)
            markets, total_count = await market_service.search_markets(
                query_text=search_query,
                page=page,
                page_size=9,  # Match page_size used in formatters
                group_by_events=True
            )

        if not markets:
            await query.edit_message_text(f"❌ No results found for '{search_query}'")
            return

        message_text, keyboard = build_markets_list_ui(
            markets=markets,
            page=page,
            view_type='search',
            context_name=search_query,
            total_count=total_count
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in search page callback: {e}")
        await query.edit_message_text("❌ Error loading search results")


async def handle_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle search message when user types search query
    """
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Check if we're waiting for search input
    if not context.user_data.get('awaiting_search'):
        return  # Not in search mode, let other handlers process

    # Rate limiting: prevent spam searches (max 1 search per 2 seconds per user)
    import time
    current_time = time.time()
    last_search_time = context.user_data.get('last_search_time', 0)
    if current_time - last_search_time < 2.0:
        await update.message.reply_text("⏱️ Please wait a moment before searching again.")
        return

    try:
        # Clear the flag and update rate limit
        context.user_data.pop('awaiting_search', None)
        context.user_data['last_search_query'] = text
        context.user_data['last_search_time'] = current_time

        if not text:
            await update.message.reply_text("❌ Please enter a valid search query")
            return

        # Validate query length
        if len(text) < 2:
            await update.message.reply_text("❌ Search query must be at least 2 characters long")
            return

        logger.info(f"🔍 Search query from user {user_id}: {text}")

        # Use API client in SKIP_DB mode
        if SKIP_DB:
            api_client = get_api_client()
            markets = await api_client.search_markets(
                query=text,
                page=0,
                page_size=9,  # Match page_size used in formatters
                group_by_events=True
            )
            # Check if rate limited (returns None)
            if markets is None:
                await update.message.reply_text(
                    "⏱️ Search rate limit exceeded. Please wait a moment before searching again."
                )
                return

            # Get total_count from cache
            total_count = None
            if api_client.cache_manager:
                query_safe = text.replace('/', '_').replace(':', '_')
                total_count_key = f"api:markets:search:total_count:{query_safe}:true"
                total_count = await api_client.cache_manager.get(total_count_key, 'metadata')
        else:
            # Get cache manager
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            market_service = get_market_service(cache_manager=cache_manager)
            markets, total_count = await market_service.search_markets(
                query_text=text,
                page=0,
                page_size=9,  # Match page_size used in formatters
                group_by_events=True
            )

        if not markets:
            await update.message.reply_text(
                f"❌ No results found for '{text}'\n\n"
                "Try a different search term or use /markets to browse categories."
            )
            return

        message_text, keyboard = build_markets_list_ui(
            markets=markets,
            page=0,
            view_type='search',
            context_name=text,
            total_count=total_count
        )

        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling search message for user {user_id}: {e}")
        await update.message.reply_text("❌ Error performing search. Please try again.")
