#!/usr/bin/env python3
"""
Category Handlers
Handles category browsing with 5 simplified categories (Oct 2025)
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler
from .telegram_utils import safe_answer_callback_query

logger = logging.getLogger(__name__)

# 5 Simplified categories (Oct 2025)
# Updated to match MarketCategorizerService categories
CATEGORIES = [
    {"name": "Geopolitics", "emoji": "🌍"},
    {"name": "Sports", "emoji": "⚽"},
    {"name": "Finance", "emoji": "💹"},
    {"name": "Crypto", "emoji": "₿"},
    {"name": "Other", "emoji": "📊"},
]


def _normalize_polymarket_category(raw_category: str) -> str:
    """
    Normalize Polymarket categories to our 5 simplified categories

    Args:
        raw_category: Raw category from Polymarket (e.g., "Cryptocurrency", "US Politics")

    Returns:
        Normalized category: Geopolitics, Sports, Finance, Crypto, or Other
    """
    if not raw_category:
        return "Other"

    cat_lower = raw_category.lower()

    # Geopolitics mapping
    if any(keyword in cat_lower for keyword in [
        'politic', 'election', 'government', 'war', 'international',
        'geopolitic', 'trump', 'biden', 'congress', 'senate'
    ]):
        return "Geopolitics"

    # Sports mapping
    if any(keyword in cat_lower for keyword in [
        'sport', 'nba', 'nfl', 'mlb', 'nhl', 'soccer', 'football',
        'baseball', 'basketball', 'esport', 'olympics', 'championship'
    ]):
        return "Sports"

    # Crypto mapping
    if any(keyword in cat_lower for keyword in [
        'crypto', 'bitcoin', 'ethereum', 'blockchain', 'nft', 'defi', 'web3'
    ]):
        return "Crypto"

    # Finance mapping
    if any(keyword in cat_lower for keyword in [
        'business', 'finance', 'econom', 'stock', 'fed', 'market',
        'company', 'ipo', 'interest rate'
    ]):
        return "Finance"

    # Default to Other (Tech, Science, Entertainment, Culture, etc.)
    return "Other"


def _item_matches_category(item: dict, category: str) -> bool:
    """
    Check if a display item (event group or individual market) matches category

    Uses normalization to map Polymarket categories to our 5 categories.

    Args:
        item: Display item from MarketDataLayer (can be event_group or individual)
        category: Category to match (e.g., 'geopolitics', 'sports')

    Returns:
        True if item matches category, False otherwise

    Examples:
        - Event group with all Sports markets → Matches 'sports'
        - Individual market with "US Politics" → Matches 'geopolitics' (normalized)
        - Event group with mixed categories → Matches if ANY outcome matches
    """
    item_type = item.get('type', 'individual')
    category_lower = category.lower()

    if item_type == 'event_group':
        # For grouped events, check if ANY market in the group matches category
        # This ensures we show the event if at least one outcome has this category
        markets = item.get('markets', [])

        return any(
            _normalize_polymarket_category(m.get('category', '')).lower() == category_lower
            for m in markets
        )
    else:
        # For individual markets, normalize the category first
        raw_category = item.get('category', '')
        normalized = _normalize_polymarket_category(raw_category)
        return normalized.lower() == category_lower


async def category_command(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager, market_db):
    """
    Show 5 category buttons for browsing markets (simplified Oct 2025)
    """
    user_id = update.effective_user.id

    # Initialize user session
    session_manager.init_user(user_id)

    # Build category buttons (2 per row)
    keyboard = []
    row = []
    for i, category in enumerate(CATEGORIES):
        button = InlineKeyboardButton(
            f"{category['emoji']} {category['name']}",
            callback_data=f"cat_{category['name'].lower()}_0"  # cat_<category>_<page>
        )
        row.append(button)

        # Add row after 2 buttons
        if len(row) == 2 or i == len(CATEGORIES) - 1:
            keyboard.append(row)
            row = []

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "🔥 *Trending Markets*\n\n"
        "Select a category to browse markets:\n"
    )

    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_category_markets(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager, market_db, category: str, page: int = 0):
    """
    Show markets for a specific category with pagination and event grouping

    NEW (Oct 2025): Uses MarketDataLayer with group_by_events=True to avoid duplicates
    - Groups multi-outcome markets (e.g., "Highest grossing movie" with 6 outcomes)
    - Shows "X outcomes • Vol: $Y" for grouped events
    - Consistent with /markets command behavior
    """
    query = update.callback_query
    await safe_answer_callback_query(query)

    user_id = update.effective_user.id
    session_manager.init_user(user_id)

    # ✅ Store category context in session for smart back button
    session = session_manager.get(user_id)
    session['last_category'] = category.lower()
    logger.info(f"💾 Stored category '{category}' in session for user {user_id}")

    # Find category emoji
    category_emoji = next((c['emoji'] for c in CATEGORIES if c['name'].lower() == category.lower()), "📊")
    category_display = category.capitalize()

    try:
        # Import MarketDataLayer for event grouping
        from core.services.market_data_layer import get_market_data_layer
        from config.config import USE_SUBSQUID_MARKETS

        # Get market data layer with event grouping
        market_layer = get_market_data_layer()
        logger.info(f"📊 /category - Using {'SUBSQUID' if USE_SUBSQUID_MARKETS else 'OLD'} data layer")

        # Get ALL markets with event grouping (fetch large set to filter by category)
        # NOTE: We fetch 1000 to have enough after category filtering
        all_display_items, total = market_layer.get_high_volume_markets_page(
            page=0,
            page_size=1000,  # Fetch many items to filter by category
            group_by_events=True  # ✅ KEY: This groups markets by events to avoid duplicates!
        )

        logger.info(f"📋 Fetched {len(all_display_items)} display items (events + individual markets)")

        # DEBUG: Log first few items to understand structure
        if all_display_items:
            logger.info(f"🔍 DEBUG: First item type={all_display_items[0].get('type')}, category={all_display_items[0].get('category')}, has markets={len(all_display_items[0].get('markets', []))}")
            if all_display_items[0].get('type') == 'event_group' and all_display_items[0].get('markets'):
                first_market = all_display_items[0]['markets'][0]
                logger.info(f"🔍 DEBUG: First market in group - category={first_market.get('category')}, title={first_market.get('title', '')[:50]}")

        # Filter display items by category
        # This handles both event groups (checks markets array) and individuals (checks category field)
        category_items = [
            item for item in all_display_items
            if _item_matches_category(item, category)
        ]

        logger.info(f"🏷️ Filtered to {len(category_items)} items for category '{category}'")

        # Sort by volume (both event groups and individuals have 'volume' field)
        category_items.sort(key=lambda x: x.get('volume', 0), reverse=True)

        # Pagination (10 items per page)
        limit = 10
        start_idx = page * limit
        end_idx = start_idx + limit
        page_items = category_items[start_idx:end_idx]
        total_pages = (len(category_items) + limit - 1) // limit

        if not page_items:
            await query.edit_message_text(
                f"{category_emoji} *{category_display}*\n\n"
                f"❌ No active markets in this category.",
                parse_mode='Markdown'
            )
            return

        # Import the same UI builder as main markets
        from .trading_handlers import _build_markets_ui

        # Build message and keyboard using same format as main markets
        # This handles both event_groups and individual markets automatically
        message_text, keyboard = _build_markets_ui(page_items, 'category', category, page)

        # Update header to show category context
        message_text = f"{category_emoji} **{category_display}** • Page {page + 1}\n\n" + message_text.split('\n\n', 1)[1]

        # Update navigation to include category context
        # Find and replace the navigation row
        for i, row in enumerate(keyboard):
            # Look for navigation row (contains Previous/Refresh/Next)
            if len(row) >= 2 and any("Previous" in btn.text or "Next" in btn.text or "Refresh" in btn.text for btn in row):
                # Replace with category-specific navigation
                nav_row = []
                if page > 0:
                    nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"cat_{category}_{page-1}"))
                nav_row.append(InlineKeyboardButton("← Categories", callback_data="cat_menu"))
                if page < total_pages - 1:
                    nav_row.append(InlineKeyboardButton("▶️ Next", callback_data=f"cat_{category}_{page+1}"))

                keyboard[i] = nav_row
                break

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error showing category markets: {e}")
        await query.edit_message_text(f"❌ Error loading {category} markets: {str(e)}")


async def _get_filtered_category_markets(market_db, category: str, filter_type: str, page: int = 0):
    """
    Get markets for a category with specific filter

    Args:
        market_db: MarketDatabase instance
        category: 'politics', 'trump', etc.
        filter_type: 'volume', 'liquidity', 'newest', 'endingsoon'
        page: Page number

    Returns:
        List of filtered markets for this category
    """
    limit = 10

    try:
        # Get base set based on filter type
        # NOTE: Repository methods already filter for active markets
        if filter_type == 'volume':
            all_markets = market_db.get_high_volume_markets(limit=1000)
        elif filter_type == 'liquidity':
            all_markets = market_db.get_high_liquidity_markets(limit=1000)
        elif filter_type == 'newest':
            all_markets = market_db.get_new_markets(limit=1000)
        elif filter_type == 'endingsoon':
            all_markets = market_db.get_ending_soon_markets(hours=168, limit=1000)
        else:
            all_markets = market_db.get_high_volume_markets(limit=1000)

        # Only filter by category (repository already filters for active, etc.)
        category_markets = [
            m for m in all_markets
            if m.get('category') and m.get('category').lower() == category.lower()
        ]

        # Paginate
        start_idx = page * limit
        end_idx = start_idx + limit
        return category_markets[start_idx:end_idx]

    except Exception as e:
        logger.error(f"Error filtering category {category} by {filter_type}: {e}")
        return []


async def show_category_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Show unified market hub (matches /markets command)
    Used by "🔙 Categories" back button
    """
    query = update.callback_query
    await safe_answer_callback_query(query)

    # Build keyboard
    keyboard = []

    # Add Trending button (full width, top position)
    keyboard.append([
        InlineKeyboardButton("🔥 Trending Markets", callback_data="trending_markets")
    ])

    # Build category buttons (2 per row)
    row = []

    for i, category in enumerate(CATEGORIES):
        button = InlineKeyboardButton(
            f"{category['emoji']} {category['name']}",
            callback_data=f"cat_{category['name'].lower()}_0"
        )
        row.append(button)

        # 2 buttons per row
        if len(row) == 2:
            keyboard.append(row)
            row = []

    # Add remaining category button if odd number
    if row:
        keyboard.append(row)

    # Add search button (full width, bottom position)
    keyboard.append([
        InlineKeyboardButton("Search Markets", callback_data="trigger_search")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Match the /markets hub message exactly
    message = (
        "📊 **MARKET HUB**\n\n"
        "Browse trending markets, categories, or search for specific topics"
    )

    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


def register(app: Application, session_manager, market_db):
    """Register category handlers"""
    # Wrap handlers to pass dependencies
    async def category_cmd_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await category_command(update, context, session_manager, market_db)

    app.add_handler(CommandHandler("category", category_cmd_wrapper))
    logger.info("✅ Category handlers registered")
