#!/usr/bin/env python3
"""
Trading Handlers
Handles market browsing, search, and trading commands
"""

import logging
import time
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters
from sqlalchemy import or_

from database import db_manager, Market
from config.config import BUY_INPUT_MESSAGE, SELL_INPUT_MESSAGE, SEARCH_MIN_LENGTH, SEARCH_MAX_LENGTH
from core.services.market_grouping_service import MarketGroupingService

logger = logging.getLogger(__name__)

# Initialize grouping service
grouping_service = MarketGroupingService()

# Import categories from category_handlers to ensure consistency
from .category_handlers import CATEGORIES


def _build_filter_buttons(current_filter: str, page: int, is_category: bool = False, category: str = None):
    """
    Build filter button row with active indicator

    Args:
        current_filter: 'volume', 'liquidity', 'newest', 'endingsoon'
        page: Current page number
        is_category: True if in category view
        category: Category name if is_category=True

    Returns:
        List of button rows for InlineKeyboardMarkup
    """

    filters = [
        ('volume', '📊 Volume'),
        ('liquidity', '💧 Liquidity'),
        ('newest', '🆕 Newest'),
        ('endingsoon', '⏰ Ending Soon')
    ]

    # Build button rows (2 buttons per row for 4 filters)
    filter_buttons = []
    row = []

    for filter_key, filter_label in filters:
        # Add checkmark to active filter
        if filter_key == current_filter:
            button_text = f"{filter_label} ✅"
        else:
            button_text = filter_label

        # Build callback data
        if is_category:
            callback_data = f"catfilter_{category}_{filter_key}_0"  # Reset to page 0 on filter change
        else:
            callback_data = f"filter_{filter_key}_0"

        row.append(InlineKeyboardButton(button_text, callback_data=callback_data))

        # 2 buttons per row
        if len(row) == 2:
            filter_buttons.append(row)
            row = []

    # Add remaining buttons
    if row:
        filter_buttons.append(row)

    return filter_buttons


async def markets_command(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager, market_db):
    """
    Unified market browsing hub - shows trending + categories + search
    Users can:
    - View trending markets (top volume across all categories)
    - Browse by category (Geopolitics, Sports, Finance, Crypto, Other)
    - Search for specific markets
    """
    user_id = update.effective_user.id
    logger.info(f"📊 /markets hub - User {user_id}")

    # Initialize user session
    session_manager.init_user(user_id)

    # Clear any previous search/category context (user is now browsing markets hub)
    session = session_manager.get(user_id)
    session.pop('last_search_query', None)
    session.pop('last_category', None)

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

    # Send unified hub message
    message = (
        "📊 **MARKET HUB**\n\n"
        "Browse trending markets, categories, or search for specific topics"
    )

    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    logger.info(f"✅ Market hub displayed for user {user_id}")


def _format_volume(volume: float) -> str:
    """Format volume as $44.0M, $12.5K, or $500"""
    if volume >= 1_000_000:
        return f"${volume/1_000_000:.1f}M"
    elif volume >= 1_000:
        return f"${volume/1_000:.1f}K"
    else:
        return f"${volume:,.0f}"


def _format_end_date(end_date) -> str:
    """Format end date as 'November 4th, 2025' or 'TBD'"""
    from datetime import datetime

    if not end_date:
        return "TBD"
    try:
        if isinstance(end_date, str):
            date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        else:
            date_obj = end_date

        day = date_obj.day
        suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        return date_obj.strftime(f"%B {day}{suffix}, %Y")
    except:
        return "TBD"


def _build_numbered_buttons(markets: list, page: int = 0, callback_prefix: str = "market_select") -> list:
    """
    Build numbered button rows [1-5] and [6-10]

    Args:
        markets: List of market dicts
        page: Page number for callback data
        callback_prefix: Prefix for callback data

    Returns:
        List of button rows for keyboard
    """
    row1 = []
    row2 = []

    for i, market in enumerate(markets[:10], start=1):
        button = InlineKeyboardButton(
            str(i),
            callback_data=f"{callback_prefix}_{market['id']}_{page}"
        )
        if i <= 5:
            row1.append(button)
        else:
            row2.append(button)

    buttons = []
    if row1:
        buttons.append(row1)
    if row2:
        buttons.append(row2)

    return buttons


async def _get_filtered_markets(market_db, filter_type: str, page: int = 0):
    """
    Get markets based on filter type
    NEW: Uses MarketDataLayer for subsquid integration
    OLD: Falls back to market_db if MarketDataLayer unavailable

    Args:
        market_db: MarketDatabase instance (for fallback compatibility)
        filter_type: 'volume', 'liquidity', 'newest', 'endingsoon'
        page: Page number (0-indexed)

    Returns:
        List of filtered markets or market groups (10 per page)
    """
    import time
    start_time = time.time()
    limit = 10

    try:
        # Try using MarketDataLayer (NEW subsquid-powered)
        from core.services.market_data_layer import get_market_data_layer
        from config.config import USE_SUBSQUID_MARKETS

        market_layer = get_market_data_layer()

        logger.info(f"📊 /markets - Using {'SUBSQUID' if USE_SUBSQUID_MARKETS else 'OLD'} data layer")

        # Get grouped markets from market_data_layer (handles grouping + caching internally)
        if filter_type == 'volume':
            display_items, total = market_layer.get_high_volume_markets_page(page=page, page_size=limit, group_by_events=True)
        elif filter_type == 'liquidity':
            display_items, total = market_layer.get_high_liquidity_markets_page(page=page, page_size=limit, group_by_events=True)
        elif filter_type == 'newest':
            display_items, total = market_layer.get_new_markets_page(page=page, page_size=limit, group_by_events=True)
        elif filter_type == 'endingsoon':
            display_items, total = market_layer.get_ending_soon_markets_page(hours=168, page=page, page_size=limit, group_by_events=True)
        else:
            display_items, total = market_layer.get_high_volume_markets_page(page=page, page_size=limit, group_by_events=True)

        batch_load_time = time.time() - start_time
        logger.info(f"⏱️ Loaded {len(display_items)} display items in {batch_load_time:.3f}s from MarketDataLayer (page {page})")

        if not display_items:
            logger.warning(f"⚠️ No items available")
            return []

        return display_items

    except Exception as e:
        logger.error(f"💨 MARKET_DATA_LAYER ERROR: {e}, falling back to market_db")
        # Last resort fallback
        try:
            if filter_type == 'volume':
                all_markets = market_db.get_high_volume_markets(limit=500)
            elif filter_type == 'liquidity':
                all_markets = market_db.get_high_liquidity_markets(limit=500)
            elif filter_type == 'newest':
                all_markets = market_db.get_new_markets(limit=500)
            elif filter_type == 'endingsoon':
                all_markets = market_db.get_ending_soon_markets(hours=168, limit=500)
            else:
                all_markets = market_db.get_high_volume_markets(limit=500)

            if all_markets:
                start_idx = page * limit
                end_idx = (page + 1) * limit
                return all_markets[start_idx:end_idx]
        except Exception as e2:
            logger.error(f"❌ BOTH data sources failed: {e2}")

        return []


def _build_group_ui(group_data: Dict, index: int) -> str:
    """
    Build display text for a market group (multi-outcome event)

    Format:
    1. 🏈 Super Bowl 2026 Winner | 32 teams | Vol: $2.1B
       Ends: February 8th, 2026
       Click to select team

    Args:
        group_data: Event dict with event_title, count, volume, end_date
        index: Display index (1-10)

    Returns:
        Formatted text string
    """
    from datetime import datetime

    # Event title - use event_title from the group data
    event_title = group_data.get('event_title', 'Unknown Event')
    # Remove markdown special characters that break parsing
    event_title = event_title.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')

    # Market count (number of outcomes)
    count = group_data.get('count', 0)

    # Total volume
    total_volume = group_data.get('volume', 0)
    if total_volume >= 1_000_000:
        volume_str = f"${total_volume/1_000_000:.1f}B" if total_volume >= 1_000_000_000 else f"${total_volume/1_000_000:.1f}M"
    elif total_volume >= 1_000:
        volume_str = f"${total_volume/1_000:.1f}K"
    else:
        volume_str = f"${total_volume:,.0f}"

    # Format end date
    end_date = group_data.get('end_date')
    if end_date:
        try:
            if isinstance(end_date, str):
                date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            else:
                date_obj = end_date
            # Format as "February 8th, 2026"
            day = date_obj.day
            suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
            end_date_str = date_obj.strftime(f"%B {day}{suffix}, %Y")
        except:
            end_date_str = "TBD"
    else:
        end_date_str = "TBD"

    # Build display
    text = f"{index}. **{event_title}**\n"
    text += f"   {count} outcomes • Vol: {volume_str}\n"
    text += f"⏰ Ends: {end_date_str}\n"

    return text + "\n"


def _build_markets_ui(markets: list, view_type: str = 'markets', context_name: str = '', page: int = 0, filter_type: str = 'volume', total_items: int = None):
    """
    Build markets UI with filter buttons

    Args:
        markets: List of market dicts
        view_type: 'markets', 'category', 'search', or 'trending'
        context_name: Category name if view_type='category', search query if view_type='search'
        page: Current page number
        filter_type: Current filter ('volume', 'trending', etc.)
        total_items: Total number of items (for search pagination)

    Returns:
        (message_text, keyboard)
    """
    from datetime import datetime

    # PHASE 2: Add search view header
    if view_type == 'category':
        message_text = f"📊 **{context_name.capitalize()}** • Page {page + 1}\n\n"
    elif view_type == 'search':
        # Show total results and current page
        if total_items is not None:
            message_text = f"🔍 **Search:** `{context_name}`\n\nFound {total_items} result(s) • Page {page + 1}\n\n"
        else:
            message_text = f"🔍 **Search:** `{context_name}`\n\nPage {page + 1}\n\n"
    elif view_type == 'trending':
        message_text = f"🔥 **Trending Markets** • Page {page + 1}\n\n"
    else:
        message_text = f"📊 **Markets** • Page {page + 1}\n\n"

    # Store market IDs for numbered buttons
    market_buttons_row1 = []
    market_buttons_row2 = []

    # Display markets with clean formatting (10 markets max)
    for i, item in enumerate(markets[:10], start=1):
        # Check if this is an event (grouped markets) or individual market
        item_type = item.get('type', 'individual')

        if item_type == 'event_group':  # Support both new and legacy
            # Display event (Win/Draw/Win outcomes)
            market_display = _build_group_ui(item, i)
            message_text += market_display

            # Button leads to event selection (pick which outcome to trade)
            event_id = item.get('event_id') or item.get('market_group', 'unknown')
            button = InlineKeyboardButton(
                str(i),
                callback_data=f"event_select_{event_id}_{page}"
            )
        else:
            # Display individual market (standard)
            market_name = item.get('question') or item.get('title', 'Unknown Market')
            # Remove markdown special characters that break parsing
            market_name = market_name.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')

            # Format volume
            volume = item.get('volume', 0)
            if volume >= 1_000_000:
                volume_str = f"${volume/1_000_000:.1f}M"
            elif volume >= 1_000:
                volume_str = f"${volume/1_000:.1f}K"
            else:
                volume_str = f"${volume:,.0f}"

            # Format end date (e.g., "November 4th, 2025")
            end_date = item.get('end_date', '')
            if end_date:
                try:
                    if isinstance(end_date, str):
                        date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    else:
                        date_obj = end_date
                    # Format as "November 4th, 2025"
                    day = date_obj.day
                    suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
                    end_date_str = date_obj.strftime(f"%B {day}{suffix}, %Y")
                except:
                    end_date_str = "TBD"
            else:
                end_date_str = "TBD"

            # Build clean 3-line display per market
            market_display = f"{i}. **{market_name}**\n"
            market_display += f"📊 Volume: {volume_str}\n"
            market_display += f"⏰ Ends: {end_date_str}\n"

            # Add to message
            message_text += market_display + "\n"

            # Add numbered button (will be arranged in rows later)
            button = InlineKeyboardButton(
                str(i),
                callback_data=f"market_select_{item['id']}_{page}"
            )

        # First 5 buttons in row 1, next 5 in row 2
        if i <= 5:
            market_buttons_row1.append(button)
        else:
            market_buttons_row2.append(button)

    # Build keyboard layout
    keyboard = []

    # PHASE 3: Don't add filter buttons for search view
    if view_type != 'search':
        # Add filter buttons at top
        is_category = (view_type == 'category')
        filter_buttons = _build_filter_buttons(filter_type, page, is_category, context_name)
        keyboard.extend(filter_buttons)

    # Add numbered buttons in two rows [1-5] and [6-10]
    if market_buttons_row1:
        keyboard.append(market_buttons_row1)
    if market_buttons_row2:
        keyboard.append(market_buttons_row2)

    # PHASE 3: Add pagination buttons (different per view type)
    nav_buttons = []

    if view_type == 'search':
        # Search pagination + back button
        page_size = 10
        has_next = total_items is not None and (page + 1) * page_size < total_items

        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"search_page_{context_name}_{page-1}"))

        # Always show back button for search
        nav_buttons.append(InlineKeyboardButton("← Hub", callback_data="cat_menu"))

        if has_next:
            nav_buttons.append(InlineKeyboardButton("▶️ Next", callback_data=f"search_page_{context_name}_{page+1}"))

    elif view_type == 'category':
        # Category pagination
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"catfilter_{context_name}_{filter_type}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton("← Categories", callback_data="cat_menu"))
        nav_buttons.append(InlineKeyboardButton("▶️ Next", callback_data=f"catfilter_{context_name}_{filter_type}_{page+1}"))
    elif view_type == 'trending':
        # Trending pagination with back to categories button
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"filter_{filter_type}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton("← Categories", callback_data="cat_menu"))
        nav_buttons.append(InlineKeyboardButton("▶️ Next", callback_data=f"filter_{filter_type}_{page+1}"))
    else:
        # Markets pagination
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"filter_{filter_type}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton("🔄 Refresh", callback_data=f"filter_{filter_type}_{page}"))
        nav_buttons.append(InlineKeyboardButton("▶️ Next", callback_data=f"filter_{filter_type}_{page+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    return message_text, keyboard




async def _execute_search(query_text: str, loading_msg, page: int = 0, session_manager=None, user_id=None) -> bool:
    """
    Execute search and display results with Redis cache and event grouping

    Args:
        query_text: Search query string
        loading_msg: Message object to edit with results
        page: Page number for pagination (default 0)
        session_manager: Session manager instance for storing search context
        user_id: User ID for session storage

    Returns:
        True if search successful, False otherwise
    """
    try:
        # Validate search query
        query_text = query_text.strip()

        # Store search query in session for smart back button
        if session_manager and user_id:
            session = session_manager.get(user_id)
            session['last_search_query'] = query_text
            logger.info(f"💾 Stored search query '{query_text}' in session for user {user_id}")

        if len(query_text) < SEARCH_MIN_LENGTH:
            await loading_msg.edit_text(
                f"❌ **Search query too short**\n\n"
                f"Minimum {SEARCH_MIN_LENGTH} characters required.",
                parse_mode='Markdown'
            )
            return False

        if len(query_text) > SEARCH_MAX_LENGTH:
            await loading_msg.edit_text(
                f"❌ **Search query too long**\n\n"
                f"Maximum {SEARCH_MAX_LENGTH} characters allowed.",
                parse_mode='Markdown'
            )
            return False

        # Try Redis cache first
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        cached_results = redis_cache.get_search_results(query_text)
        if cached_results is not None:
            logger.info(f"🚀 SEARCH CACHE HIT: '{query_text}' → {len(cached_results)} grouped items")
            grouped_items = cached_results
        else:
            logger.info(f"💨 SEARCH CACHE MISS: '{query_text}' - querying database")

            # Search markets in PostgreSQL (subsquid_markets_poll for fresh data)
            # SIMPLE & RELIABLE SEARCH:
            # 1. Search market titles AND event titles (from JSONB)
            # 2. Use ILIKE for simple pattern matching

            with db_manager.get_session() as db:
                from datetime import datetime, timezone
                from sqlalchemy import or_
                from database import SubsquidMarketPoll
                now = datetime.now(timezone.utc)

                # Simple search conditions:
                # 1. Match in market title
                # 2. Match in any event title (using jsonb_path_exists)

                # Build SQL for event title search using raw string
                # This uses PostgreSQL's jsonb_path_exists which is bulletproof
                from sqlalchemy import text as sql_text

        # Validate and sanitize query text to prevent SQL injection and JSONPath errors
        import re

        # Remove or escape problematic characters that can break JSONPath regex
        # Characters that commonly break JSONPath: quotes, brackets, curly braces, etc.
        problematic_chars = ['"', "'", '[', ']', '{', '}', '(', ')', '^', '$', '.', '*', '+', '?', '|', '\\']

        # Check if query contains problematic characters
        has_problematic_chars = any(char in query_text for char in problematic_chars)

        if has_problematic_chars:
            # Replace problematic characters with spaces to make search still work
            sanitized_query = re.sub(r'["\'\[\]{}()^$.*+?|\\]', ' ', query_text)
            # Remove extra spaces
            sanitized_query = ' '.join(sanitized_query.split())
            logger.warning(f"Search query sanitized: '{query_text}' -> '{sanitized_query}'")
            query_text = sanitized_query

        # Escape single quotes in query for SQL
        safe_query = query_text.replace("'", "''")

        # Search both market title and event titles
        # Split query into words for multi-word search (case-insensitive)
        query_words = [word.strip() for word in query_text.split() if word.strip()]

        if len(query_words) == 1:
            # Single word - use existing logic
            title_condition = SubsquidMarketPoll.title.ilike(f'%{query_text}%')
            event_condition = sql_text(f"jsonb_path_exists(events, '$[*].event_title ? (@ like_regex \".*{safe_query}.*\" flag \"i\")')")
        else:
            # Multi-word - require ALL words in title (case-insensitive)
            from sqlalchemy import and_
            title_condition = and_(*[SubsquidMarketPoll.title.ilike(f'%{word}%') for word in query_words])
            # For events, keep simple regex for now (could be improved to require all words)
            event_condition = sql_text(f"jsonb_path_exists(events, '$[*].event_title ? (@ like_regex \".*{safe_query}.*\" flag \"i\")')")

        markets_query = db.query(SubsquidMarketPoll).filter(
            SubsquidMarketPoll.status == 'ACTIVE',
            SubsquidMarketPoll.accepting_orders == True,
            SubsquidMarketPoll.archived == False,
            or_(
                # Search market title (with multi-word support)
                title_condition,
                # Search event titles in JSONB array
                event_condition
            ),
            or_(
                SubsquidMarketPoll.end_date == None,
                SubsquidMarketPoll.end_date > now
            )
        ).order_by(SubsquidMarketPoll.volume.desc()).limit(100).all()  # Cap at 100 for performance

        results = []
        for m in markets_query:
            # PHASE 1: Convert to dict with ALL fields needed for grouping
            market_dict = {
                'id': m.market_id,
                'market_id': m.market_id,
                'title': m.title,
                'question': m.title,
                'volume': float(m.volume) if m.volume else 0,
                'liquidity': float(m.liquidity) if m.liquidity else 0,
                'end_date': m.end_date,
                'category': m.category,
                'events': m.events,  # ✅ KEY: Include JSONB events data for grouping
                'outcome_prices': m.outcome_prices,
                'clob_token_ids': m.clob_token_ids,
                'outcomes': m.outcomes,
                'active': True,
                'closed': False
            }
            results.append(market_dict)

        # PHASE 1: Apply event grouping (same as /markets and /category)
        from core.services.market_data_layer import get_market_data_layer
        market_layer = get_market_data_layer()
        grouped_items = market_layer._group_markets_by_events(results)

        logger.info(f"🔍 Search '{query_text}': {len(results)} markets → {len(grouped_items)} grouped items")

        # PHASE 4: Cache grouped results for 5 minutes
        redis_cache.cache_search_results(query_text, grouped_items, ttl=300)

        if not grouped_items:
            await loading_msg.edit_text(
                f"❌ **No markets found for:** `{query_text}`\n\n"
                f"Try different keywords or browse /markets",
                parse_mode='Markdown'
            )
            return False

        # PHASE 1: Paginate grouped results (10 items per page)
        page_size = 10
        start_idx = page * page_size
        end_idx = start_idx + page_size
        paginated_items = grouped_items[start_idx:end_idx]
        total_items = len(grouped_items)

        # PHASE 2: Use _build_markets_ui() instead of _build_search_results_ui()
        message_text, keyboard = _build_markets_ui(
            markets=paginated_items,
            view_type='search',
            context_name=query_text,
            page=page,
            filter_type='volume',
            total_items=total_items  # Pass total for pagination
        )

        reply_markup = InlineKeyboardMarkup(keyboard)

        await loading_msg.edit_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return True

    except Exception as e:
        logger.error(f"Search execution error: {e}")
        import traceback
        logger.error(traceback.format_exc())

        # Check if it's a SQL syntax error (likely from invalid JSONPath regex)
        error_msg = str(e)
        if "syntax error at or near" in error_msg and "jsonpath" in error_msg.lower():
            # User-friendly message for JSONPath syntax errors
            await loading_msg.edit_text(
                "❌ **Search Error**\n\n"
                "Invalid search query. Please avoid special characters like quotes (\") in your search.\n\n"
                "💡 **Tips:**\n"
                "• Use simple words or phrases\n"
                "• Avoid quotes, brackets, and special symbols\n"
                "• Try searching for market titles directly\n\n"
                "Try again with a simpler search term."
            )
        elif "psycopg2" in error_msg or "SQL" in error_msg:
            # Generic SQL error message
            await loading_msg.edit_text(
                "❌ **Search Error**\n\n"
                "Sorry, there was a problem with your search. This might be due to special characters or a temporary issue.\n\n"
                "💡 Try using simpler search terms without quotes or special symbols."
            )
        else:
            # Other errors - show generic message but log the details
            await loading_msg.edit_text(
                "❌ **Search Error**\n\n"
                "Sorry, something went wrong with your search. Please try again with different keywords."
            )
        return False


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """
    Search markets by keyword

    Usage:
    - /search <keyword> - Direct search (legacy mode)
    - /search - Opens ForceReply prompt for guided search (NEW)
    """
    user_id = update.effective_user.id
    session_manager.init_user(user_id)

    # Extract search query from command
    query_text = ' '.join(context.args) if context.args else ''

    if not query_text:
        # NEW: ForceReply mode for better UX
        try:
            # Get trending markets for suggestions
            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone

                trending_markets = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.status == 'ACTIVE',
                    SubsquidMarketPoll.accepting_orders == True,
                    SubsquidMarketPoll.archived == False,
                    or_(
                        SubsquidMarketPoll.end_date == None,
                        SubsquidMarketPoll.end_date > datetime.now(timezone.utc)
                    )
                ).order_by(SubsquidMarketPoll.volume.desc()).limit(3).all()

                trending_suggestions = ", ".join([
                    f"'{m.title.split()[0]}'" for m in trending_markets[:3]
                ]) if trending_markets else "'Trump', 'Bitcoin', 'NBA'"
        except Exception as e:
            logger.error(f"Error getting trending suggestions: {e}")
            trending_suggestions = "'Trump', 'Bitcoin', 'NBA'"

        # Send ForceReply prompt
        prompt_msg = await update.message.reply_text(
            f"🔍 **Search Markets**\n\n"
            f"Enter a term to find markets",
            parse_mode='Markdown',
            reply_markup=ForceReply(selective=True)
        )

        # Set state to await search input
        session_manager.set_search_state(user_id, prompt_msg.message_id)
        logger.info(f"🔍 User {user_id} opened ForceReply search prompt")
        return

    # Legacy mode: Direct search with /search <query>
    # Send loading message
    loading_msg = await update.message.reply_text(
        f"🔍 **Searching for '{query_text}'...**",
        parse_mode='Markdown'
    )

    await _execute_search(query_text, loading_msg, session_manager=session_manager, user_id=user_id)


async def handle_search_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """
    Handle user reply to ForceReply search prompt

    Args:
        update: Telegram update object
        context: Telegram context
        session_manager: Session manager instance
    """
    user_id = update.effective_user.id
    query_text = update.message.text.strip()

    logger.info(f"🔍 User {user_id} replied to search prompt: '{query_text}'")

    # Clear search state
    session_manager.clear_search_state(user_id)

    # Send loading message
    loading_msg = await update.message.reply_text(
        f"🔍 **Searching for '{query_text}'...**",
        parse_mode='Markdown'
    )

    # Execute search
    await _execute_search(query_text, loading_msg, session_manager=session_manager, user_id=user_id)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              session_manager, trading_service):
    """Handle text messages for amount input and search replies"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # PRIORITY 1: Check if this is a reply to ForceReply search prompt
    if update.message.reply_to_message and session_manager.is_awaiting_search_input(user_id):
        await handle_search_reply(update, context, session_manager)
        return

    # Get user session
    session = session_manager.get(user_id)
    state = session.get('state', 'idle')

    # Check if user is awaiting bridge amount
    if state == 'awaiting_bridge_amount':
        # Handle bridge amount input
        try:
            amount = float(text)
            from . import bridge_handlers
            await bridge_handlers.handle_bridge_amount_input(amount, update, context, session_manager)
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount. Please enter a number (e.g., 5 or 10.5):",
                parse_mode='Markdown'
            )
        return

    # WORLD-CLASS UX: Handle USD sell amount input
    if state == 'awaiting_usd_sell_amount':
        await handle_usd_sell_amount_input(update, session_manager, trading_service)
        return

    # NEW: Handle market buy amount input (Phase 3)
    if state == 'awaiting_amount':
        await _handle_market_buy_amount_input(update, session_manager)
        return

    # Check if user is in a state that expects trading amount input
    if state not in ['awaiting_buy_amount', 'awaiting_sell_amount']:
        # Ignore messages when not waiting for input
        return

    # Import validator
    from ..utils import validators

    # Validate amount
    is_valid, amount, error_msg = validators.validate_amount_input(text)

    if not is_valid:
        await update.message.reply_text(error_msg)
        return

    # Get pending trade info
    pending_trade = session.get('pending_trade', {})
    market_id = pending_trade.get('market_id')
    outcome = pending_trade.get('outcome')
    action = pending_trade.get('action')

    if not market_id or not outcome or not action:
        await update.message.reply_text("❌ Trade session expired. Please start over.")
        session_manager.clear_pending_trade(user_id)
        return

    # Show confirmation
    from ..utils import formatters
    from ..utils.escape_utils import escape_markdown
    from ..services import MarketService

    market_service = MarketService()
    market = market_service.get_market_by_id(market_id)

    # FALLBACK: If market not found by ID, try title search (for smart trading custom buy)
    if not market and pending_trade.get('source') == 'smart_trading_custom':
        # Get market question from pending_trade if available
        market_question = pending_trade.get('market_question')
        if market_question:
            logger.warning(f"⚠️ [CUSTOM_BUY] Market not found by ID, trying title search: {market_question[:50]}...")
            market = market_service.search_by_title(market_question, fuzzy=True)
            if market:
                logger.info(f"✅ [CUSTOM_BUY] Found market by title!")

    if not market:
        await update.message.reply_text("❌ Market not found.")
        return

    # 🚀 SMART TRADING CUSTOM BUY: Execute immediately (no confirmation)
    # This matches the October 30 working implementation and avoids callback_data length issues
    if pending_trade.get('source') == 'smart_trading_custom' and action == 'buy':
        logger.info(f"⚡ [SMART_CUSTOM_BUY] Executing immediately for user {user_id}, amount=${amount:.2f}")

        # Show executing message
        executing_msg = await update.message.reply_text(
            f"⚡ *Executing Custom Buy...*\n\n"
            f"Market: {market.get('question', market.get('title', 'Unknown'))[:60]}...\n"
            f"Amount: ${amount:.2f}\n"
            f"Position: {outcome.upper()}",
            parse_mode='Markdown'
        )

        # Create a simple mock query object for execute_buy
        # execute_buy expects query.from_user.id and query.answer()
        class MockQuery:
            def __init__(self, user_id):
                class User:
                    def __init__(self, uid):
                        self.id = uid
                self.from_user = User(user_id)

            async def answer(self, text):
                # Silent answer (we're showing messages via executing_msg instead)
                pass

        mock_query = MockQuery(user_id)

        # Execute buy immediately
        result = await trading_service.execute_buy(mock_query, market_id, outcome, amount, market)

        # Clear state
        session['state'] = 'idle'
        session.pop('pending_trade', None)

        if result.get('success'):
            # Clean, production-ready success message
            success_message = (
                f"✅ *Trade Executed!*\n\n"
                f"{result.get('message', '')}\n\n"
                f"💡 _Following smart wallet strategy ({outcome})_"
            )

            # Add action buttons
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [InlineKeyboardButton("📊 View My Positions", callback_data="show_positions")],
                [InlineKeyboardButton("💎 Back to Smart Trading", callback_data="back_to_smart_trading")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await executing_msg.edit_text(
                success_message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            logger.info(f"✅ [SMART_CUSTOM_BUY] Success: user_id={user_id}, amount=${amount:.2f}, outcome={outcome}")
        else:
            error_msg = result.get('message', 'Error executing trade')
            # Escape markdown characters in error message to prevent parsing errors
            from ..utils.escape_utils import escape_markdown
            error_msg_escaped = escape_markdown(error_msg)
            await executing_msg.edit_text(
                f"❌ {error_msg_escaped}",
                parse_mode='Markdown'
            )
            logger.error(f"❌ [SMART_CUSTOM_BUY] Failed: user_id={user_id}, error={error_msg}")

        return  # Done - no confirmation needed

    # 📋 REGULAR FLOW: Show confirmation for /markets and other sources
    if action == 'buy':
        # Estimate tokens for buy
        estimated_price = 0.50  # Rough estimate
        estimated_tokens = int(amount / estimated_price)

        confirmation_text = formatters.format_trade_confirmation(
            market, outcome, amount, estimated_tokens, estimated_price
        )

        keyboard = [
            [InlineKeyboardButton("✅ Confirm Buy", callback_data=f"conf_buy_{market_id}_{outcome}_{amount}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trade")]
        ]
    else:  # sell
        confirmation_text = f"""
**🎯 Confirm Sell**

📊 Market: {escape_markdown((market.get('question') or market.get('title', 'Unknown'))[:60])}...

**Details:**
• Position: {outcome.upper()}
• Amount: ${amount:.2f}

Confirm to proceed:
        """

        keyboard = [
            [InlineKeyboardButton("✅ Confirm Sell", callback_data=f"conf_sell_{market_id}_{outcome}_{amount}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trade")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        confirmation_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def _handle_market_buy_amount_input(update: Update, session_manager):
    """
    NEW Phase 3: Handle text input for market buy amount
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()
    session = session_manager.get(user_id)

    pending_order = session.get('pending_order', {})

    if not pending_order:
        await update.message.reply_text("❌ Session expired. Please use /markets to start over.")
        session['state'] = 'idle'
        return

    # Parse amount
    try:
        # Remove $ and commas
        clean_text = text.replace('$', '').replace(',', '').strip()
        amount = float(clean_text)

        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0. Try again or /cancel")
            return

        if amount > 10000:
            await update.message.reply_text("❌ Amount too large. Maximum $10,000 per order. Try again or /cancel")
            return

        # Store amount for confirmation
        pending_order['amount'] = amount
        session['pending_order'] = pending_order
        session['state'] = 'confirming_order'

        # Get market details
        market = session.get('current_market', {})
        if not market:
            await update.message.reply_text("❌ Market data lost. Please start over with /markets")
            return

        logger.debug(f"🔍 [ORDER] Current market: id={market.get('id')}, title={market.get('title')}, question={market.get('question')}, event_title={market.get('event_title')}")

        market_id = pending_order['market_id']
        side = pending_order['side']
        price = pending_order['price']
        return_page = pending_order['return_page']

        # Calculate estimated shares
        estimated_shares = int(amount / price)

        # Build confirmation message - prioritize title (actual market question), fallback to question, then event_title
        side_emoji = "✅ YES" if side == "yes" else "❌ NO"
        message_text = f"📝 **Order Summary**\n\n"

        # Get the best market name: prefer 'title', fallback to 'question', then 'event_title'
        market_name = market.get('title') or market.get('question') or market.get('event_title') or 'Unknown'
        logger.debug(f"🔍 [ORDER] Display market_name: {market_name}")

        message_text += f"Market: {market_name}\n"
        message_text += f"Side: {side_emoji}\n"
        message_text += f"Price: {price*100:.0f}¢\n"
        message_text += f"Amount: ${amount:.2f}\n"
        message_text += f"Estimated shares: ~{estimated_shares}\n\n"
        message_text += "Confirm this order?"

        # Store confirmation in session to avoid 64-byte callback_data limit
        session['pending_confirmation'] = {
            'market_id': market_id,
            'side': side,
            'amount': amount,
            'return_page': return_page,
            'price': price
        }

        # Create confirmation buttons (short callbacks)
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data="confirm_order"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"markets_page_{return_page}")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text(
            f"❌ Invalid amount: `{text}`\n\n"
            "Please enter a number (e.g., `100` or `250.50`)\n"
            "Or type /cancel to go back",
            parse_mode='Markdown'
        )


def register(app: Application, session_manager, trading_service, market_db):
    """Register all trading command handlers"""
    from functools import partial

    # Bind dependencies to handlers
    markets_with_deps = partial(markets_command, session_manager=session_manager, market_db=market_db)
    search_with_deps = partial(search_command, session_manager=session_manager)
    text_with_deps = partial(handle_text_message, session_manager=session_manager,
                            trading_service=trading_service)

    app.add_handler(CommandHandler("markets", markets_with_deps))
    app.add_handler(CommandHandler("search", search_with_deps))
    # Register text handler in group 5 to give priority to ConversationHandlers (group 0)
    # This prevents conflicts with withdrawal, copy trading, and other conversation flows
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_with_deps), group=5)

    logger.info("✅ Trading handlers registered")


async def handle_usd_sell_amount_input(update: Update, session_manager, trading_service):
    """WORLD-CLASS UX: Handle USD amount input for selling"""
    user_id = update.effective_user.id
    session = session_manager.get(user_id)
    text = update.message.text.strip()

    try:
        # Parse USD amount
        usd_amount = float(text.replace('$', '').replace(',', ''))

        if usd_amount <= 0:
            await update.message.reply_text("❌ Please enter a positive amount (e.g., 25.50)")
            return

        if usd_amount > 10000:  # Reasonable limit
            await update.message.reply_text("❌ Amount too large. Please enter a smaller amount.")
            return

        # Get pending sell data
        pending_sell = session.get('pending_sell', {})
        position_index = pending_sell.get('position_index')

        if position_index is None:
            await update.message.reply_text("❌ Session expired. Please try again from /positions")
            return

        # 🔥 BLOCKCHAIN-FIRST: Get position data using same logic as /positions (with cache & filtering)
        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)

        if not wallet:
            await update.message.reply_text("❌ Wallet not found. Please run /start")
            return

        # ✅ REUSE: Use same positions fetching logic as /positions command
        from core.services.redis_price_cache import get_redis_cache
        from core.utils.aiohttp_client import get_http_client
        import aiohttp

        wallet_address = wallet['address']
        redis_cache = get_redis_cache()

        # Check cache first (same TTL as /positions)
        cached_positions = redis_cache.get_user_positions(wallet_address)

        if cached_positions is not None:
            positions_data = cached_positions
            logger.info(f"🚀 CACHE HIT: USD sell using {len(positions_data)} cached positions")
        else:
            # Cache miss - fetch from API (same as /positions)
            logger.info(f"💨 CACHE MISS: Fetching positions for USD sell from API")
            url = f"https://data-api.polymarket.com/positions?user={wallet_address}"

            session = await get_http_client()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    raise Exception(f"API Error: {response.status}")
                positions_data = await response.json()

            # Cache with same TTL as /positions
            redis_cache.cache_user_positions(wallet_address, positions_data, ttl=30)
            logger.info(f"📊 Cached {len(positions_data)} positions for USD sell (30s TTL)")

        # Apply same filtering as /positions
        if positions_data:
            from database import SessionLocal, ResolvedPosition
            with SessionLocal() as db:
                resolved_condition_ids = db.query(ResolvedPosition.condition_id).filter(
                    ResolvedPosition.user_id == user_id
                ).all()
                resolved_condition_ids = set(r[0] for r in resolved_condition_ids)

                # Filter resolved positions
                positions_data = [
                    pos for pos in positions_data
                    if pos.get('conditionId') not in resolved_condition_ids
                ]

                # Filter dust positions
                positions_data = [
                    pos for pos in positions_data
                    if float(pos.get('size', 0)) >= 0.1
                ]

        # Convert to dict format for compatibility (same as old _get_positions_from_blockchain)
        positions = {}
        for idx, pos in enumerate(positions_data):
            key = f"{pos.get('conditionId', 'unknown')}_{pos.get('outcome', 'unknown').lower()}"
            positions[key] = {
                'tokens': float(pos.get('size', 0)),
                'buy_price': float(pos.get('avgPrice', 0)),
                'token_id': pos.get('asset', ''),
                'outcome': pos.get('outcome', 'unknown').lower(),
                'market': {
                    'id': pos.get('conditionId'),
                    'question': pos.get('title', 'Unknown Market')
                },
                'condition_id': pos.get('conditionId', '')
            }

        position_keys = list(positions.keys())
        logger.info(f"✅ BLOCKCHAIN: Found {len(positions)} filtered positions for USD sell")

        if position_index >= len(position_keys):
            await update.message.reply_text("❌ Position not found")
            return

        position_key = position_keys[position_index]
        position = positions.get(position_key)

        if not position:
            await update.message.reply_text("❌ Position not found")
            return

        # Show confirmation with professional formatting
        current_tokens = position.get('tokens', 0)
        buy_price = position.get('buy_price', 0)
        estimated_tokens = min(int(usd_amount / buy_price), int(current_tokens))
        market_question = position.get('market', {}).get('question', 'Unknown Market')[:40]
        outcome = position.get('outcome', 'unknown').upper()

        confirmation_msg = f"🎯 **Confirm Sell Order**\n\n"
        confirmation_msg += f"📊 **Market:** {market_question}...\n"
        confirmation_msg += f"🎯 **Position:** {outcome}\n"
        confirmation_msg += f"💵 **Sell Amount:** ${usd_amount:.2f}\n"
        confirmation_msg += f"📦 **Est. Tokens:** ~{estimated_tokens} tokens\n"
        confirmation_msg += f"💰 **Est. Price:** ~${buy_price:.4f}/token\n\n"
        confirmation_msg += f"⚡ **Ready to execute instantly!**"

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [InlineKeyboardButton("✅ Confirm Sell", callback_data=f"conf_usd_sell_{position_index}_{usd_amount}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="refresh_positions")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            confirmation_msg,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

        # Clear state
        session['state'] = 'idle'
        session.pop('pending_sell', None)

    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g., 25.50)")
    except Exception as e:
        logger.error(f"USD sell amount input error: {e}")
        await update.message.reply_text("❌ Error processing amount. Please try again.")
