"""
Markets UI Formatters
Handles formatting and display of market lists and details
"""
import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional
from telegram import InlineKeyboardButton

from telegram_bot.bot.handlers.markets.hub import get_category_name
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def _build_group_ui(group_data: Dict[str, Any], index: int) -> str:
    """
    Build display text for a market group (multi-outcome event)

    Format:
    📁 1. Event Title | X markets | Vol: $X.XB
       Ends: Month Day, Year

    Args:
        group_data: Event dict with event_title, market_count, total_volume, etc.
        index: Display index (1-10)

    Returns:
        Formatted text string
    """
    # Event title - use event_title from the group data
    event_title = group_data.get('event_title', 'Unknown Event')
    # Remove markdown special characters that break parsing
    event_title = event_title.replace('*', '').replace('_', '').replace('[', '').replace(']', '').replace('`', '')

    # Market count
    count = group_data.get('market_count', 0)

    # Total volume
    total_volume = group_data.get('total_volume', 0)
    if total_volume >= 1_000_000_000:
        volume_str = f"${total_volume/1_000_000_000:.1f}B"
    elif total_volume >= 1_000_000:
        volume_str = f"${total_volume/1_000_000:.1f}M"
    elif total_volume >= 1_000:
        volume_str = f"${total_volume/1_000:.1f}K"
    else:
        volume_str = f"${total_volume:,.0f}"

    # Get end date from first market if available
    end_date_str = "TBD"
    if group_data.get('markets') and len(group_data['markets']) > 0:
        first_market = group_data['markets'][0]
        if first_market.get('end_date'):
            try:
                from datetime import datetime
                if isinstance(first_market['end_date'], str):
                    date_obj = datetime.fromisoformat(first_market['end_date'].replace('Z', '+00:00'))
                else:
                    date_obj = first_market['end_date']
                # Format as "November 4th, 2025"
                day = date_obj.day
                suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
                end_date_str = date_obj.strftime(f"%B {day}{suffix}, %Y")
            except:
                end_date_str = "TBD"

    # Build display
    if len(event_title) > 50:
        title_display = event_title[:47] + "..."
    else:
        title_display = event_title
    display = f"📁 **{index}. {title_display}**\n"
    display += f"   📊 {count} markets • 💰 Vol: {volume_str}\n"
    display += f"   ⏰ Ends: {end_date_str}\n\n"

    return display


def _build_selection_keyboard(
    markets: List[Dict[str, Any]],
    view_type: str,
    page: int,
    start_idx: int
) -> List[List[InlineKeyboardButton]]:
    """
    Build keyboard with numbered buttons for market/event selection
    Arranged in 3 columns, 3 rows for up to 9 items

    Args:
        markets: List of market dictionaries (up to 9 items)
        view_type: 'trending', 'category', 'search'
        page: Current page number
        start_idx: Starting index for numbering

    Returns:
        List of keyboard rows with selection buttons
    """
    if not markets:
        return []

    keyboard = []
    buttons_row = []

    for i, market in enumerate(markets, start_idx + 1):
        # Determine callback data based on market type
        if market.get('type') == 'event_group':
            # Event group - leads to event children display
            # Use event_id instead of event_title to avoid exceeding 64-byte limit
            # Telegram callback_data limit is 64 bytes
            event_id = market.get('event_id', 'unknown')
            # Always start event pagination at page 0 (ignore trending page)
            event_page = 0
            # Ensure callback_data is within 64-byte limit
            # Format: "event_select_{event_page}_{event_id}" (max ~20 bytes for event_id)
            callback_data = f"event_select_{event_page}_{event_id}"

            # Validate length (should be < 64 bytes)
            if len(callback_data) > 64:
                logger.warning(f"Callback data too long ({len(callback_data)} bytes): {callback_data[:50]}...")
                # Fallback: use first 20 chars of event_id
                event_id_short = event_id[:20] if len(event_id) > 20 else event_id
                callback_data = f"event_select_{event_page}_{event_id_short}"
        else:
            # Individual market - leads to market detail
            market_id = market.get('id', 'unknown')
            # Ensure market_id doesn't exceed limit
            # Format: "market_select_{market_id}_{page}"
            callback_data = f"market_select_{market_id}_{page}"

            # Validate length (should be < 64 bytes)
            if len(callback_data) > 64:
                logger.warning(f"Market callback data too long ({len(callback_data)} bytes): {callback_data[:50]}...")
                # Truncate market_id if needed
                max_market_id_len = 64 - len(f"market_select__{page}")
                market_id_short = market_id[:max_market_id_len] if len(market_id) > max_market_id_len else market_id
                callback_data = f"market_select_{market_id_short}_{page}"

        # Create numbered button
        button = InlineKeyboardButton(str(i), callback_data=callback_data)
        buttons_row.append(button)

        # 3 buttons per row (3 rows total for 9 items)
        if len(buttons_row) == 3:
            keyboard.append(buttons_row)
            buttons_row = []

    # Add remaining buttons if any
    if buttons_row:
        keyboard.append(buttons_row)

    return keyboard


def build_markets_list_ui(
    markets: List[Dict[str, Any]],
    page: int,
    view_type: str,
    context_name: Optional[str] = None,
    filter_type: str = 'volume',
    total_count: Optional[int] = None
) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """
    Build UI for displaying a list of markets with pagination

    Args:
        markets: List of market dictionaries (for current page)
        page: Current page number
        view_type: 'trending', 'category', 'search'
        context_name: Category name or search query
        filter_type: 'volume', 'liquidity', 'newest', 'endingsoon'
        total_count: Total number of items (if known, for accurate pagination)

    Returns:
        Tuple of (message_text, keyboard)
    """
    page_size = 9

    # Header based on view type
    if view_type == 'trending':
        header = f"🔥 **TRENDING MARKETS**"
        subheader = f"Filter: {filter_type.capitalize()}"
    elif view_type == 'category':
        category_display = get_category_name(context_name or '')
        header = f"📂 **{category_display.upper()}**"
        subheader = f"Filter: {filter_type.capitalize()}"
    elif view_type == 'search':
        header = f"🔍 **SEARCH RESULTS**"
        subheader = f"Query: '{context_name}'"
    else:
        header = "📊 **MARKETS**"
        subheader = ""

    # Calculate pagination info
    current_page_markets = len(markets) if markets else 0

    # If we know the total count, use it for accurate pagination
    if total_count is not None:
        total_markets = total_count
        has_more_pages = (page + 1) * page_size < total_count
    else:
        # Heuristic: if we got exactly page_size, there might be more
        # But if we got fewer, we're definitely on the last page
        total_markets = current_page_markets
        has_more_pages = current_page_markets == page_size and current_page_markets > 0

    start_idx = page * page_size
    end_idx = start_idx + current_page_markets

    message = f"{header}\n\n"
    if subheader:
        message += f"{subheader}\n"
    if has_more_pages:
        message += f"Showing {start_idx + 1}-{end_idx} (page {page + 1})\n\n"
    else:
        message += f"Showing {start_idx + 1}-{end_idx} of {start_idx + total_markets} markets\n\n"

    # Markets list - use all markets since they're already paginated
    for i, market in enumerate(markets, start_idx + 1):
        # Check if this is an event group (parent) or individual market
        item_type = market.get('type', 'individual')

        if item_type == 'event_group':
            # Display event group (parent)
            market_display = _build_group_ui(market, i)
            message += market_display
        else:
            # Display individual market
            market_emoji = "📄"  # Standalone market

            title = market.get('title', 'Unknown Market')
            # Truncate long titles but show full title if reasonable length
            if len(title) > 60:
                title_display = title[:57] + "..."
            else:
                title_display = title
            message += f"{market_emoji} **{i}. {title_display}**\n"

            # Prices - use dynamic outcomes
            if market.get('outcome_prices') and market.get('outcomes'):
                prices = market['outcome_prices']
                outcomes = market['outcomes']
                if len(prices) >= 2 and len(outcomes) >= 2:
                    try:
                        price0 = float(prices[0])
                        price1 = float(prices[1])
                        outcome0 = outcomes[0]
                        outcome1 = outcomes[1]
                        message += f"   {outcome0}: ${price0:.3f} | {outcome1}: ${price1:.3f}\n"
                    except (ValueError, TypeError):
                        outcome0 = outcomes[0] if len(outcomes) > 0 else "YES"
                        outcome1 = outcomes[1] if len(outcomes) > 1 else "NO"
                        message += f"   {outcome0}: ${prices[0]} | {outcome1}: ${prices[1]}\n"
                elif len(prices) == 0 and len(outcomes) >= 2:
                    # Handle markets with no price data yet
                    message += f"   {outcomes[0]} vs {outcomes[1]} (prices pending)\n"

            # Volume
            if market.get('volume'):
                try:
                    volume = float(market['volume'])
                    message += f"   💰 Volume: ${volume:,.0f}\n"
                except (ValueError, TypeError):
                    message += f"   💰 Volume: ${market['volume']}\n"

            message += "\n\n"

    # Build selection keyboard (buttons in 4 columns, 3 rows for 12 markets)
    selection_keyboard = _build_selection_keyboard(
        markets=markets,
        view_type=view_type,
        page=page,
        start_idx=start_idx
    )

    # Calculate total_pages for pagination keyboard
    if total_count is not None:
        total_pages = math.ceil(total_count / page_size)
    else:
        # Estimate based on current page and whether there are more pages
        total_pages = page + (2 if has_more_pages else 1)

    # Build pagination keyboard
    pagination_keyboard = _build_pagination_keyboard(
        view_type=view_type,
        page=page,
        total_pages=total_pages,
        context_name=context_name,
        filter_type=filter_type,
        has_more_pages=has_more_pages
    )

    # Combine keyboards (filters first, then selection, then back button)
    keyboard = pagination_keyboard[:-1] + selection_keyboard + [pagination_keyboard[-1]]

    return message.strip(), keyboard


def _build_pagination_keyboard(
    view_type: str,
    page: int,
    total_pages: int,
    context_name: Optional[str] = None,
    filter_type: str = 'volume',
    has_more_pages: bool = False
) -> List[List[InlineKeyboardButton]]:
    """
    Build pagination keyboard for market lists

    Args:
        view_type: 'trending', 'category', 'search'
        page: Current page number
        total_pages: Total number of pages (may be estimated)
        context_name: Category name or search query
        filter_type: Current filter type
        has_more_pages: True if we got exactly page_size markets (indicating more pages might exist)
    """
    keyboard = []

    # Filter buttons for trending and category views
    if view_type in ['trending', 'category']:
        filter_row = []
        filters = [
            ('volume', '💰 Volume'),
            ('liquidity', '💧 Liq'),
            ('newest', '🆕 New'),
            ('endingsoon', '⏰ Soon')
        ]

        for filter_key, filter_label in filters:
            if filter_type == filter_key:
                filter_label = f"✅ {filter_label}"
            # Ensure context_name is lowercase for category callbacks consistency
            context_for_callback = (context_name or '').lower() if view_type == 'category' else (context_name or '')
            callback_data = f"{'catfilter' if view_type == 'category' else 'filter'}_{context_for_callback}_{filter_key}_{page}"
            filter_row.append(InlineKeyboardButton(filter_label, callback_data=callback_data))

        # Always split filters into two rows of 2
        if len(filter_row) >= 4:
            keyboard.append(filter_row[:2])  # First row: Volume, Liq
            keyboard.append(filter_row[2:])  # Second row: New, Soon
        elif len(filter_row) >= 2:
            keyboard.append(filter_row[:2])  # First row: first 2
            if len(filter_row) > 2:
                keyboard.append(filter_row[2:])  # Second row: remaining
        else:
            keyboard.append(filter_row)  # Single row for 1 or fewer

    # Pagination buttons - show if we have more than one page OR if current page indicates more pages
    if total_pages > 1 or (page > 0) or has_more_pages:
        pagination_row = []

        if page > 0:
            if view_type == 'trending':
                prev_callback = f"trending_markets_{page - 1}"
            elif view_type == 'category':
                # Ensure context_name is lowercase for consistency with callback format
                context_for_callback = (context_name or '').lower()
                prev_callback = f"cat_{context_for_callback}_{page - 1}"
            elif view_type == 'search':
                prev_callback = f"search_page_{page - 1}"
            else:
                prev_callback = f"page_{page - 1}"

            pagination_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=prev_callback))

        # No page numbering - just Prev/Next buttons
        if has_more_pages or page < total_pages - 1:
            if view_type == 'trending':
                next_callback = f"trending_markets_{page + 1}"
            elif view_type == 'category':
                # Ensure context_name is lowercase for consistency with callback format
                context_for_callback = (context_name or '').lower()
                next_callback = f"cat_{context_for_callback}_{page + 1}"
            elif view_type == 'search':
                next_callback = f"search_page_{page + 1}"
            else:
                next_callback = f"page_{page + 1}"

            pagination_row.append(InlineKeyboardButton("Next ➡️", callback_data=next_callback))

        keyboard.append(pagination_row)

    # Back button
    back_callback = "markets_hub"
    keyboard.append([InlineKeyboardButton("⬅️ Back to Hub", callback_data=back_callback)])

    return keyboard


def format_end_date(end_date) -> str:
    """
    Format end date for display
    """
    if not end_date:
        return "Date TBD"

    try:
        # Handle different date formats
        if isinstance(end_date, str):
            # Try to parse string date
            dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        elif isinstance(end_date, datetime):
            dt = end_date
        else:
            return "Date TBD"

        # Ensure timezone awareness
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Format for display
        now = datetime.now(timezone.utc)
        if dt.date() == now.date():
            return f"Today {dt.strftime('%H:%M UTC')}"
        elif (dt - now).days == 1:
            return f"Tomorrow {dt.strftime('%H:%M UTC')}"
        else:
            return dt.strftime('%Y-%m-%d %H:%M UTC')

    except (ValueError, AttributeError, TypeError):
        return "Date TBD"
