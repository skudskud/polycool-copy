"""
Smart Trading View Handler
Handles /smart_trading command and displays recommendations
"""
import os
import asyncio
import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.smart_trading import SmartTradingService
from core.services.api_client.api_client import get_api_client
from core.services.market.market_helper import get_market_data, get_markets_data
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Pagination settings
TRADES_PER_PAGE = 5

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Initialize services
smart_trading_service = SmartTradingService()
api_client = get_api_client() if SKIP_DB else None


async def handle_smart_trading_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /smart_trading command - Show recent smart wallet trades
    """
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    try:
        logger.info(f"💎 /smart_trading command - User {user_id}")

        # Get ALL recommendations without pagination (we'll filter and paginate client-side)
        # Use API client if SKIP_DB=true, otherwise use service directly
        if SKIP_DB and api_client:
            # Get all trades (large limit) for client-side filtering
            result = await api_client.get_smart_trading_recommendations(
                page=1,
                limit=50,  # Get max available trades for filtering
                min_trade_value=300.0,
                min_win_rate=0.55,
                max_age_minutes=1440  # 24 hours to show recent trades
            )
            # Convert API response format to match service format
            if result:
                # Extract data from API wrapper: {"status": "success", "data": {...}}
                data = result.get('data', {})
                all_trades = data.get('trades', [])
            else:
                all_trades = []
        else:
            # Get all trades from service for client-side filtering
            all_trades_result = await smart_trading_service.get_recent_recommendations_cached(
                max_age_minutes=1440,
                min_trade_value=300.0,
                min_win_rate=0.55,
                limit=50  # Get max available trades for filtering
            )
            all_trades = all_trades_result if all_trades_result else []

        if not all_trades:
            await update.message.reply_text(
                "💎 **EXPERT TRADER ACTIVITY**\n\n"
                "_We track the best Polymarket traders and show their fresh positions._\n\n"
                "📊 No recent trades found.\n\n"
                "What we're looking for:\n"
                "• BUY positions from expert traders\n"
                "• Trade value over $300\n"
                "• Smart wallets with win rate > 55%\n"
                "• Active markets (not expired/resolved)\n\n"
                "💡 _Try again in a few minutes when smart wallets make new trades!_",
                parse_mode='Markdown'
            )
            return

        # Store all trades for client-side filtering and pagination
        context.user_data['smart_trades_raw'] = all_trades
        context.user_data['smart_trades_page'] = 1  # Initialize current page

        # Display first page (will filter and paginate client-side)
        await _display_trades_page(update, context, page=1)

    except Exception as e:
        logger.error(f"Error in smart_trading handler for user {user_id}: {e}\n{traceback.format_exc()}")
        await update.message.reply_text(
            "❌ An error occurred. Please try again."
        )


async def _display_trades_page(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 1,
    is_callback: bool = False
) -> None:
    """
    Display a page of smart trades

    Args:
        update_or_query: Update or CallbackQuery object
        context: Context
        page: Page number (1-indexed)
        is_callback: Whether this is a callback query
    """
    try:
        trades_data = context.user_data.get('smart_trades_raw', [])

        if not trades_data:
            message = "❌ No trades available. Please run /smart_trading again."
            if is_callback:
                await update_or_query.edit_message_text(message)
            else:
                await update_or_query.message.reply_text(message)
            return

        # Build message
        message = "💎 **EXPERT TRADER ACTIVITY**\n\n"
        message += "_Recent trades from top Polymarket traders_\n\n"

        # Use cached filtered trades if available and page hasn't changed significantly
        # Only recalculate if we don't have cached filtered trades
        filtered_trades = context.user_data.get('smart_trades_filtered', [])

        # If we have cached filtered trades, use them (faster pagination)
        # Otherwise, resolve markets and filter (first time or if cache is lost)
        if not filtered_trades:
            # ⚡ OPTIMIZATION: Parallel batch resolve market titles and URLs for all trades
            # We need URLs for all trades, even if they already have titles
            market_title_map = {}
            market_url_map = {}
            position_id_to_market = {}  # Cache to avoid duplicate resolutions

            # Collect unique position_ids that need resolution
            from telegram_bot.handlers.smart_trading.callbacks import _resolve_market_by_position_id

            # First pass: collect all unique position_ids that need resolution
            position_ids_to_resolve = []
            seen_position_ids = set()

            for trade in trades_data:
                position_id = trade.get('position_id')
                if not position_id:
                    continue

                # Skip if already cached or already in list
                if position_id not in position_id_to_market and position_id not in seen_position_ids:
                    position_ids_to_resolve.append(position_id)
                    seen_position_ids.add(position_id)

            # ⚡ PARALLEL RESOLUTION: Resolve all markets concurrently with concurrency limit
            if position_ids_to_resolve:
                logger.info(f"🔍 Resolving {len(position_ids_to_resolve)} markets in parallel...")

                # Semaphore to limit concurrent requests (prevent API overload)
                # Limit to 10 concurrent requests for optimal performance
                semaphore = asyncio.Semaphore(10)

                async def resolve_with_semaphore(position_id: str):
                    """Resolve market with semaphore to limit concurrency"""
                    async with semaphore:
                        try:
                            market = await _resolve_market_by_position_id(position_id, context)
                            return position_id, market
                        except Exception as e:
                            logger.warning(f"Failed to resolve market for position_id {position_id[:20]}...: {e}")
                            return position_id, None

                # Execute all resolutions in parallel
                resolution_start = datetime.now()
                results = await asyncio.gather(
                    *[resolve_with_semaphore(pid) for pid in position_ids_to_resolve],
                    return_exceptions=True
                )
                resolution_time = (datetime.now() - resolution_start).total_seconds()

                # Process results and populate cache
                successful_resolutions = 0
                for result in results:
                    if isinstance(result, Exception):
                        logger.warning(f"Exception during parallel resolution: {result}")
                        continue

                    position_id, market = result
                    if market:
                        position_id_to_market[position_id] = market
                        successful_resolutions += 1

                logger.info(f"✅ Resolved {successful_resolutions}/{len(position_ids_to_resolve)} markets in {resolution_time:.2f}s (parallel)")

            # Second pass: build maps from resolved markets
            for trade in trades_data:
                position_id = trade.get('position_id')
                if not position_id:
                    continue

                market = position_id_to_market.get(position_id)
                if market:
                    market_id = market.get('id')
                    if market_id:
                        # Store title (only if not already set or if it's "Unknown Market")
                        if not trade.get('market_title') or trade.get('market_title') == "Unknown Market":
                            market_title_map[market_id] = market.get('title', 'Unknown Market')
                        # Always store URL
                        market_url_map[market_id] = market.get('polymarket_url')
                        # Also store URL by position_id for direct lookup
                        market_url_map[position_id] = market.get('polymarket_url')

            # Display trades with filters applied
            filtered_trades = []
            for trade in trades_data:
                try:
                    price = trade.get('price')
                    market_title_from_api = trade.get('market_title')

                    # Skip trades with price > 0.985
                    if price and float(price) > 0.985:
                        continue

                    # Get market title (use resolved title or batch-resolved)
                    market_title = None
                    if market_title_from_api and market_title_from_api != "Unknown Market":
                        market_title = market_title_from_api
                    else:
                        # Use batch-resolved title
                        market_title = market_title_map.get(trade['market_id'])

                    # Skip if we don't have a proper market title (no fallback ID display)
                    if not market_title:
                        continue

                    # Add filtered trade with resolved market title and URL
                    filtered_trade = trade.copy()
                    filtered_trade['resolved_market_title'] = market_title
                    # Try to get URL from market_url_map using position_id or market_id
                    position_id = trade.get('position_id')
                    market_id = trade.get('market_id')
                    if position_id and position_id in market_url_map:
                        filtered_trade['polymarket_url'] = market_url_map[position_id]
                    elif market_id and market_id in market_url_map:
                        filtered_trade['polymarket_url'] = market_url_map[market_id]
                    filtered_trades.append(filtered_trade)
                except Exception as e:
                    logger.error(f"Error processing trade {trade.get('trade_id', 'unknown')}: {e}")
                    continue

            # Store filtered trades in context for consistency with callbacks (only if we recalculated)
            context.user_data['smart_trades_filtered'] = filtered_trades

        # Client-side pagination for filtered trades
        total_filtered = len(filtered_trades)
        total_pages = (total_filtered + TRADES_PER_PAGE - 1) // TRADES_PER_PAGE

        # Adjust page to be within bounds
        page = max(1, min(page, total_pages)) if total_pages > 0 else 1

        # Get trades for current page
        start_idx = (page - 1) * TRADES_PER_PAGE
        end_idx = start_idx + TRADES_PER_PAGE
        page_trades = filtered_trades[start_idx:end_idx]

        # Display trades for current page
        for page_idx, trade in enumerate(page_trades, start=1):
            market_title = trade['resolved_market_title']

            # Format market title for display (wrap on two lines if needed)
            if len(market_title) <= 50:
                display_title = market_title
            else:
                # Split on word boundaries or at 50 chars
                split_point = market_title.rfind(' ', 0, 50)
                if split_point == -1:
                    split_point = 50
                display_title = market_title[:split_point] + '\n' + market_title[split_point:].lstrip()

            # Format time ago
            time_ago = _format_time_ago(trade['timestamp'])

            # Format wallet info - use full address with real win rate
            wallet_address = trade.get('wallet_address', 'Unknown Address')
            win_rate = trade.get('win_rate')
            if win_rate is not None:
                # Convert from decimal (0-1) to percentage (0-100)
                win_rate_pct = win_rate * 100 if win_rate <= 1.0 else win_rate
                wallet_info = f"{wallet_address} ({win_rate_pct:.1f}% WR)"
            else:
                wallet_info = wallet_address

            # Format side and outcome - use resolved values
            side = trade.get('side', 'BUY')  # ✅ Get side from trade (BUY/SELL)
            outcome = trade.get('outcome', '')

            # ✅ Display side with outcome if available and not UNKNOWN
            if outcome and outcome.upper() != 'UNKNOWN':
                outcome_display = f"{side} {outcome}"
            else:
                outcome_display = side  # Just show side if outcome is UNKNOWN or missing

            message += f"**{page_idx}. {display_title}**\n"
            message += f"   💼 {wallet_info}\n"
            message += f"   📈 {outcome_display} • ${trade['value']:.0f}\n"
            message += f"   💰 Price: ${trade['price']:.4f}\n"
            message += f"   🕒 {time_ago}\n\n"

        # Add pagination info
        message += f"📄 Page {page}/{total_pages} • {total_filtered} trades\n"

        # Build keyboard
        keyboard = []

        # Trade action buttons (3 buttons per row for better UX) - use page trades
        for i, trade in enumerate(page_trades, start=1):
            # Get Polymarket URL for this trade
            polymarket_url = trade.get('polymarket_url')

            # Create buttons: See on Polymarket (if URL available) or View Market, Quick Buy, Custom Buy
            row_buttons = []

            if polymarket_url:
                # Use URL button for "See on Polymarket"
                row_buttons.append(
                    InlineKeyboardButton(
                        f"🔗 View #{i}",
                        url=polymarket_url
                    )
                )
            else:
                # Fallback to View Market callback if no URL
                row_buttons.append(
                    InlineKeyboardButton(
                        f"📊 View Market #{i}",
                        callback_data=f"smart_view_{i}"
                    )
                )

            row_buttons.append(
                InlineKeyboardButton(
                    f"⚡ Quick Buy #{i} ($2)",
                    callback_data=f"smart_buy_{i}"
                )
            )
            row_buttons.append(
                InlineKeyboardButton(
                    f"💰 Custom Buy #{i}",
                    callback_data=f"smart_custom_buy_{i}"
                )
            )

            keyboard.append(row_buttons)

        # Pagination buttons
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"smart_page_{page-1}"))
        nav_buttons.append(InlineKeyboardButton("🔄 Refresh", callback_data=f"smart_page_{page}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"smart_page_{page+1}"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Back button
        keyboard.append([
            InlineKeyboardButton("← Back to Hub", callback_data="markets_hub")
        ])

        # Update context
        context.user_data['smart_trades_page'] = page

        # Send or edit message
        if is_callback:
            await update_or_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        else:
            await update_or_query.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown',
                disable_web_page_preview=True
            )

    except Exception as e:
        logger.error(f"Error displaying trades page: {e}\n{traceback.format_exc()}")
        error_msg = "❌ Error displaying trades. Please try again."
        if is_callback:
            await update_or_query.edit_message_text(error_msg)
        else:
            await update_or_query.message.reply_text(error_msg)


def _format_time_ago(timestamp) -> str:
    """Format timestamp as time ago (e.g., '5 minutes ago')"""
    from datetime import datetime

    if not timestamp:
        return "Unknown time"

    # Handle both datetime objects and ISO strings
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except:
            return "Unknown time"
    elif not isinstance(timestamp, datetime):
        return "Unknown time"

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta = now - timestamp

    if delta.total_seconds() < 60:
        return "Just now"
    elif delta.total_seconds() < 3600:
        minutes = int(delta.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    elif delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    else:
        days = int(delta.total_seconds() / 86400)
        return f"{days} day{'s' if days > 1 else ''} ago"
