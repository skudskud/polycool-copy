#!/usr/bin/env python3
"""
Smart Trading Handler
Handles /smart_trading command to display recent smart wallet trades with pagination
"""

import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Global references to repositories (will be set during initialization)
smart_wallet_repo = None
smart_trade_repo = None
smart_session_manager = None


def _get_current_prices_for_trades(trade_data_list: list, markets_map: dict) -> dict:
    """
    Get current prices for a list of trades using batch API calls to streamer.

    Args:
        trade_data_list: List of trade data dictionaries
        markets_map: Pre-loaded market data

    Returns:
        Dict mapping market_id to current price (or None if not available)
    """
    try:
        # Collect all market_ids that have market data
        market_ids_with_data = []
        for trade_data in trade_data_list:
            market_id = trade_data.get('market_id')
            if market_id and market_id in markets_map:
                market_ids_with_data.append(market_id)

        if not market_ids_with_data:
            logger.debug("No markets with data found for price fetching")
            return {}

        # Get token IDs for these markets
        token_ids = []
        market_to_tokens = {}

        for market_id in market_ids_with_data:
            market_data = markets_map.get(market_id)
            if market_data and 'clob_token_ids' in market_data:
                try:
                    # clob_token_ids can be a string or list
                    token_ids_raw = market_data['clob_token_ids']
                    if isinstance(token_ids_raw, str):
                        # Parse JSON string
                        import json
                        token_ids_parsed = json.loads(token_ids_raw)
                    else:
                        token_ids_parsed = token_ids_raw

                    if isinstance(token_ids_parsed, list):
                        # For each market, we need the correct token for the outcome
                        outcome = None
                        for trade_data in trade_data_list:
                            if trade_data.get('market_id') == market_id:
                                outcome = trade_data.get('outcome', '').upper()
                                break

                        # Map outcome to token index (YES = 0, NO = 1)
                        if outcome == 'YES' and len(token_ids_parsed) > 0:
                            token_ids.append(token_ids_parsed[0])
                            market_to_tokens[market_id] = token_ids_parsed[0]
                        elif outcome == 'NO' and len(token_ids_parsed) > 1:
                            token_ids.append(token_ids_parsed[1])
                            market_to_tokens[market_id] = token_ids_parsed[1]
                        elif len(token_ids_parsed) > 0:
                            # Default to first token if outcome unclear
                            token_ids.append(token_ids_parsed[0])
                            market_to_tokens[market_id] = token_ids_parsed[0]

                except Exception as e:
                    logger.debug(f"Could not parse token IDs for market {market_id}: {e}")

        if not token_ids:
            logger.debug("No token IDs found for price fetching")
            return {}

        # Get current prices in batch
        try:
            from telegram_bot.services.market_service import MarketService
            market_service = MarketService()
            prices_result = market_service.get_prices_batch(token_ids)

            # Map back to market_ids
            market_prices = {}
            for market_id, token_id in market_to_tokens.items():
                if token_id in prices_result:
                    market_prices[market_id] = prices_result[token_id]

            logger.debug(f"Retrieved current prices for {len(market_prices)}/{len(market_ids_with_data)} markets")
            return market_prices

        except Exception as e:
            logger.error(f"Error fetching current prices: {e}")
            return {}

    except Exception as e:
        logger.error(f"Error in _get_current_prices_for_trades: {e}")
        return {}


def init_repositories(wallet_repo, trade_repo, session_mgr=None):
    """
    Initialize repository references

    Args:
        wallet_repo: SmartWalletRepository instance
        trade_repo: SmartWalletTradeRepository instance
        session_mgr: SessionManager instance (optional)
    """
    global smart_wallet_repo, smart_trade_repo, smart_session_manager
    smart_wallet_repo = wallet_repo
    smart_trade_repo = trade_repo
    if session_mgr:
        smart_session_manager = session_mgr


def _calculate_potential_profit(trade_value: float, current_price: float, entry_price: float, outcome: str) -> tuple:
    """
    Calculate potential profit for a trade

    Args:
        trade_value: Amount invested (price * size)
        current_price: Current market price
        entry_price: Entry price of the trade
        outcome: YES or NO

    Returns:
        (potential_profit, profit_percentage)
    """
    # Simplified calculation: if they bought at entry_price and sold at current_price
    tokens = trade_value / entry_price if entry_price > 0 else 0
    current_value = tokens * current_price
    profit = current_value - trade_value
    profit_pct = (profit / trade_value * 100) if trade_value > 0 else 0

    return (profit, profit_pct)


async def smart_trading_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Display 10 most recent FRESH first-time smart wallet trades over $400

    UNIFIED STANDARDS (aligned with Twitter bot + Telegram alerts):
    - Freshness: Max 5 minutes old (optimal for copy trading)
    - Min value: $400+ (high quality signals)
    - No crypto price markets (filtered automatically)

    Enhanced UX with:
    - Explanation header
    - Market title
    - Position taken (BUY YES/NO)
    - Amount invested + potential profit
    - Full wallet address + Win Rate
    - Action buttons (View Market, Quick Buy)
    """
    try:
        # Check if repositories are initialized
        if not smart_wallet_repo or not smart_trade_repo:
            await update.message.reply_text(
                "❌ Smart wallet monitoring service not initialized yet. Please try again in a moment."
            )
            return

        # Get RECENT first-time BUY trades (sorted by timestamp DESC = newest first)
        # Goal: Show last 20 trades that happened, regardless of how old
        # User can see timestamps to judge freshness themselves

        # Fetch recent trades - no time limit, just get the most recent ones
        # UNIFIED: Query smart_wallet_trades_to_share table directly (single source of truth)
        logger.info(f"🔍 [SMART_TRADING] Fetching trades from smart_wallet_trades_to_share...")
        trades = smart_trade_repo.get_recent_first_time_trades(
            limit=100,          # Fetch more to account for filtering
            min_value=100.0,    # Legacy parameter (ignored by repository)
            max_age_minutes=None  # No time limit - get all recent trades
        )
        
        logger.info(f"🔍 [SMART_TRADING] Retrieved {len(trades)} trades from smart_wallet_trades_to_share")

        # Filter out SELL trades - we only want to see BUY positions
        buy_trades_count = len([t for t in trades if t.side and t.side.upper() == 'BUY'])
        trades = [t for t in trades if t.side and t.side.upper() == 'BUY']
        logger.info(f"🔍 [SMART_TRADING] After filtering BUY only: {len(trades)} trades (was {buy_trades_count})")

        # UNIFIED: Trust the FilterProcessor - ALL trades in smart_wallet_trades_to_share are pre-qualified
        # No additional filtering needed to maintain unification across all 4 systems
        # 'trades' variable already contains qualified trades from unified table
        # FilterProcessor is the single source of truth for ALL 4 systems

        if not trades:
            await update.message.reply_text(
                "💎 EXPERT TRADER ACTIVITY\n\n"
                "_We track the best Polymarket traders and show their fresh positions._\n\n"
                "📊 No recent trades found.\n\n"
                "What we're looking for:\n"
                "• First-time BUY positions (new entries)\n"
                "• Trade value over $100\n"
                "• Active markets (not expired/resolved)\n"
                "• No crypto price prediction markets\n\n"
                "💡 _Try again in a few minutes when smart wallets make new trades!_"
            , parse_mode='Markdown')
            return

        # Pre-load all wallets in batch to avoid N+1 queries
        wallet_addresses = [t.wallet_address for t in trades]
        wallets_map = {}
        try:
            # Batch load wallets - use set to avoid duplicates
            for addr in set(wallet_addresses):
                try:
                    w = smart_wallet_repo.get_wallet(addr)
                    if w:
                        wallets_map[addr] = w
                except Exception as wallet_err:
                    logger.warning(f"⚠️ [SMART_TRADING] Could not load wallet {addr[:8]}...: {wallet_err}")
                    # Continue without this wallet's data
                    continue
            logger.debug(f"📦 [SMART_TRADING] Batch loaded {len(wallets_map)} wallets (out of {len(set(wallet_addresses))} total)")
        except Exception as e:
            logger.error(f"❌ [SMART_TRADING] Error in wallet batch loading: {e}")
            # Continue with empty wallets_map - trades will show without wallet stats
            wallets_map = {}
        
        # Initialize empty markets cache (will be populated on-demand later)
        markets_map = {}

        # Store all trades in session with pagination metadata
        user_id = update.effective_user.id
        from ..session_manager import session_manager
        session = session_manager.get(user_id)

        # Calculate pagination
        trades_per_page = 5
        total_trades = len(trades)
        total_pages = (total_trades + trades_per_page - 1) // trades_per_page  # Ceiling division

        # Store all trades with pagination metadata - convert to plain dicts for session storage
        session['smart_trades_pagination'] = {
            'trades': [
                {
                    'market_id': trade.market_id,  # ✅ FIX: Use numeric market_id (not condition_id)
                    'condition_id': trade.condition_id,
                    'outcome': trade.outcome,
                    'value': float(trade.value) if trade.value else 0.0,
                    'side': trade.side,
                    'price': float(trade.price) if trade.price else 0.50,
                    'size': float(trade.size) if trade.size else 0,
                    'wallet_address': trade.wallet_address,
                    'market_question': trade.market_question or 'Unknown Market',
                    'timestamp': trade.timestamp.isoformat() if trade.timestamp else None,
                    'index': idx + 1  # Global index (1-20)
                }
                for idx, trade in enumerate(trades)
            ],
            'current_page': 1,
            'total_pages': total_pages,
            'trades_per_page': trades_per_page,
            'total_trades': total_trades,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'wallets_cache': wallets_map,  # Cache wallet data
            'markets_cache': markets_map   # Cache market data
        }

        # LOG: What market_ids are we storing in the session?
        logger.info(f"🔍 [SMART_TRADING] Storing {len(trades)} trades in paginated session for user {user_id} ({total_pages} pages)")
        for idx, trade_data in enumerate(session['smart_trades_pagination']['trades'][:5]):  # Log first 5
            logger.info(f"🔍 [SMART_TRADING] Trade {idx+1}: market_id={trade_data['market_id']}, outcome={trade_data['outcome']}, value={trade_data['value']}")

        # Build FIRST page (trades 1-5)
        message, buttons = _build_page_message(
            page_num=1,
            session_data=session['smart_trades_pagination'],
            wallets_map=wallets_map,
            markets_map=markets_map
        )

        # Send paginated message
        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=buttons,
            disable_web_page_preview=True
        )

        logger.info(f"Sent paginated smart trading info to user {update.effective_user.id} (page 1/{total_pages})")

    except Exception as e:
        logger.error(f"❌ [SMART_TRADING] Error in smart_trading_command: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await update.message.reply_text(
            "❌ Error retrieving smart wallet trades. Please try again later."
        )


def _create_all_trade_buttons(num_trades: int) -> InlineKeyboardMarkup:
    """
    Create action buttons for all trades (DEPRECATED - use _build_pagination_buttons instead)

    Uses session storage to avoid callback_data length limits (64 bytes max)

    Args:
        num_trades: Number of trades to create buttons for

    Returns:
        InlineKeyboardMarkup with action buttons for all trades
    """
    buttons = []

    # Create 2 buttons per row (View Market + Quick Buy)
    # Create buttons for ALL displayed trades (up to 10)
    max_buttons = min(num_trades, 10)  # Support up to 10 trades

    for i in range(max_buttons):
        trade_num = i + 1
        buttons.append([
            InlineKeyboardButton(
                f"📊 Market #{trade_num}",
                callback_data=f"smart_view_{trade_num}"
            ),
            InlineKeyboardButton(
                f"⚡ Buy #{trade_num} (2$)",
                callback_data=f"smart_buy_{trade_num}"
            )
        ])

    return InlineKeyboardMarkup(buttons)


def _build_pagination_buttons(
    page_num: int,
    total_pages: int,
    page_trades: list,
    start_idx: int
) -> InlineKeyboardMarkup:
    """
    Build action buttons + pagination controls

    Layout:
    [Market #1] [Buy #1]
    [Market #2] [Buy #2]
    [Market #3] [Buy #3]
    [Market #4] [Buy #4]
    [Market #5] [Buy #5]
    ━━━━━━━━━━━━━━━━━━━━
    [← Prev] [Page 2/4] [Next →]

    Args:
        page_num: Current page number (1-indexed)
        total_pages: Total number of pages
        page_trades: List of trades on this page
        start_idx: Starting index for this page (0-indexed)

    Returns:
        InlineKeyboardMarkup with action + navigation buttons
    """
    buttons = []

    # Row 1-5: Action buttons for each trade on this page (3 columns)
    for i, trade in enumerate(page_trades):
        trade_num = start_idx + i + 1  # Global trade number (e.g., 6, 7, 8...)
        
        # Get market_id and outcome for custom buy button
        market_id = trade.get('market_id', '')
        outcome = trade.get('outcome', 'YES')
        
        # Encode market_id (first 10 chars) + outcome initial for callback_data
        # Format: scb_0x1bcf4088_Y (scb = smart_custom_buy, shortened to fit 64 byte limit)
        market_id_short = market_id[:10] if market_id else 'unknown'
        outcome_initial = outcome[0].upper() if outcome else 'Y'
        custom_callback = f"scb_{market_id_short}_{outcome_initial}"
        
        buttons.append([
            InlineKeyboardButton(
                f"📊 Market #{trade_num}",
                callback_data=f"smart_view_{trade_num}"
            ),
            InlineKeyboardButton(
                f"⚡ Buy #{trade_num} (2$)",
                callback_data=f"smart_buy_{trade_num}"
            ),
            InlineKeyboardButton(
                f"💰 Custom",
                callback_data=custom_callback  # No session dependency!
            )
        ])

    # Navigation row
    nav_row = []

    # Previous button (only show if not on page 1)
    if page_num > 1:
        nav_row.append(
            InlineKeyboardButton(
                "← Previous",
                callback_data="smart_page_prev"
            )
        )

    # Page indicator (non-clickable info)
    nav_row.append(
        InlineKeyboardButton(
            f"📄 {page_num}/{total_pages}",
            callback_data=f"smart_page_info"  # No-op callback
        )
    )

    # Next button (only show if not on last page)
    if page_num < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                "Next →",
                callback_data="smart_page_next"
            )
        )

    buttons.append(nav_row)

    # Optional: "Back to Page 1" button on later pages
    if page_num > 1:
        buttons.append([
            InlineKeyboardButton(
                "🏠 Back to Page 1",
                callback_data="smart_page_first"
            )
        ])

    return InlineKeyboardMarkup(buttons)


def _build_page_message(
    page_num: int,
    session_data: dict,
    wallets_map: dict,
    markets_map: dict
) -> tuple:
    """
    Build message and buttons for a specific page

    Args:
        page_num: Page number (1-indexed)
        session_data: Pagination data from session
        wallets_map: Pre-loaded wallet data
        markets_map: Pre-loaded market data

    Returns:
        (message_text, keyboard_markup)
    """
    trades_per_page = session_data['trades_per_page']
    total_pages = session_data['total_pages']
    total_trades = session_data['total_trades']
    all_trades = session_data['trades']

    # Calculate slice for this page
    start_idx = (page_num - 1) * trades_per_page
    end_idx = min(start_idx + trades_per_page, total_trades)
    page_trades = all_trades[start_idx:end_idx]

    # Get current prices for this page's trades
    current_prices = _get_current_prices_for_trades(page_trades, markets_map)

    # Build header
    message = (
        f"💎 EXPERT TRADERS\n\n"
        f"{total_trades} fresh trades • Min $100 • Page {page_num}/{total_pages}\n\n"
    )

    # Add trades for this page (NO SEPARATORS - compact format)
    for i, trade_data in enumerate(page_trades):
        trade_index = start_idx + i + 1  # Global index (1-20)

        # Get wallet from cache
        wallet_address = trade_data['wallet_address']
        wallet = wallets_map.get(wallet_address)

        if not wallet:
            # Skip if wallet not in cache
            continue

        # Get current price for this market
        market_id = trade_data.get('market_id')
        current_price = current_prices.get(market_id) if market_id else None

        # Format trade using cached data (already compact, no separators needed)
        message += _format_trade_from_session(trade_data, wallet, trade_index, markets_map, current_price)

    # Build buttons
    buttons = _build_pagination_buttons(
        page_num=page_num,
        total_pages=total_pages,
        page_trades=page_trades,
        start_idx=start_idx
    )

    return (message, buttons)


def format_smart_trading_message(trades: list, page_num: int, total_pages: int) -> tuple:
    """
    Public wrapper for formatting smart trading message (used by back button)
    
    Args:
        trades: List of all trades
        page_num: Current page number
        total_pages: Total number of pages
    
    Returns:
        (message_text, keyboard_markup)
    """
    # Build simplified message without wallet/market lookups (for back button)
    total_trades = len(trades)
    trades_per_page = 5
    
    start_idx = (page_num - 1) * trades_per_page
    end_idx = min(start_idx + trades_per_page, total_trades)
    page_trades = trades[start_idx:end_idx]
    
    # Build header
    message = (
        f"💎 EXPERT TRADERS\n\n"
        f"{total_trades} fresh trades • Min $100 • Page {page_num}/{total_pages}\n\n"
    )
    
    # Add simplified trade list
    for i, trade in enumerate(page_trades):
        trade_num = start_idx + i + 1
        market_q = trade.get('market_question', 'Unknown Market')
        outcome = trade.get('outcome', 'YES')
        value = trade.get('value', 0)
        
        message += f"**#{trade_num}** {market_q[:40]}...\n"
        message += f"  💰 ${value:.0f} • {outcome}\n\n"
    
    # Build buttons
    buttons = _build_pagination_buttons(
        page_num=page_num,
        total_pages=total_pages,
        page_trades=page_trades,
        start_idx=start_idx
    )
    
    return (message, buttons)


def _format_trade_from_session(trade_data: dict, wallet, position: int, markets_map: dict, current_price: float = None) -> str:
    """
    Format a trade from session data (used for pagination) - compact mobile-friendly format

    Args:
        trade_data: Trade data dict from session
        wallet: Wallet object
        position: Global position number (1-20)
        markets_map: Pre-loaded market data
        current_price: Current market price from streamer (optional)

    Returns:
        Formatted message string
    """
    # Market title
    market_title = trade_data.get('market_question') or "Unknown Market"

    # If we have market_data from markets_map, use title field
    market_id = trade_data.get('market_id')
    market_data = markets_map.get(market_id) if markets_map else None
    if market_data and market_data.get('title'):
        market_title = market_data['title']

    # Position taken
    outcome = trade_data.get('outcome') or "Unknown"

    # Amount invested
    invested = trade_data.get('value', 0.0)

    # Entry price
    entry_price = trade_data.get('price', 0.50)

    # Wallet info (convert Decimal to float)
    win_rate = float(wallet.win_rate) * 100 if wallet.win_rate else 0
    pnl = float(wallet.realized_pnl) if wallet.realized_pnl else 0

    # Format timestamp with "time ago" for better freshness visibility
    timestamp_str = trade_data.get('timestamp')
    time_ago_str = ""
    if timestamp_str:
        try:
            timestamp_dt = datetime.fromisoformat(timestamp_str)

            # Ensure timezone-aware
            if timestamp_dt.tzinfo is None:
                timestamp_dt = timestamp_dt.replace(tzinfo=timezone.utc)

            # Calculate time difference
            now = datetime.now(timezone.utc)
            time_diff = now - timestamp_dt

            # Format time ago
            seconds = int(time_diff.total_seconds())
            if seconds < 60:
                time_ago_str = f"{seconds}s ago"
            elif seconds < 3600:
                minutes = seconds // 60
                time_ago_str = f"{minutes}m ago"
            elif seconds < 86400:
                hours = seconds // 3600
                time_ago_str = f"{hours}h ago"
            else:
                days = seconds // 86400
                time_ago_str = f"{days}d ago"
        except Exception as e:
            logger.debug(f"Error formatting timestamp from session: {e}")
            time_ago_str = ""

    # Compact mobile-friendly format (2 lines per trade)
    # Convert to cents for display
    entry_price_cents = entry_price * 100

    # Current price in cents (1 decimal precision)
    current_price_str = ""
    if current_price is not None:
        current_price_cents = current_price * 100
        current_price_str = f" → Now: {current_price_cents:.1f}¢"

    # Format PnL with K/M suffix for readability
    if abs(pnl) >= 1000:
        pnl_str = f"${pnl/1000:.1f}K"
    else:
        pnl_str = f"${pnl:.0f}"

    # Format invested amount (remove cents for cleaner look)
    invested_str = f"${invested:,.0f}"

    message = (
        f"*#{position}* ⏱️ {time_ago_str} | {market_title}\n"
        f"    {invested_str} 🟢 BUY {outcome} @ {entry_price_cents:.0f}¢{current_price_str} | 👤 {win_rate:.1f}% WR\n\n"
    )

    return message
