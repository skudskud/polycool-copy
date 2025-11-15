"""
Positions View Builder
Handles UI formatting for positions display and details
"""
from typing import List, Dict, Any, Tuple, Optional
from telegram import InlineKeyboardButton


def _get_current_websocket_price_from_market(market: Optional[Dict[str, Any]], outcome: str, position: Any) -> float:
    """
    Get current WebSocket price from market data

    CRITICAL: Always uses WebSocket prices when available (source='ws')
    Falls back to position.current_price or position.entry_price only if WebSocket price unavailable

    Args:
        market: Market data dict (includes 'source' and 'outcome_prices') or None
        outcome: Position outcome ("YES" or "NO")
        position: Position object (for fallback)

    Returns:
        Current price (0-1) from WebSocket or fallback
    """
    if not market:
        # No market data - use position price as fallback
        return position.current_price if position.current_price else position.entry_price

    # Try to get WebSocket price from market
    from telegram_bot.bot.handlers.positions_handler import _extract_position_price_from_market
    price = _extract_position_price_from_market(market, outcome)

    if price is not None:
        return price

    # Fallback to position.current_price or position.entry_price only if WebSocket unavailable
    return position.current_price if position.current_price else position.entry_price


def format_price_with_precision(price: float, market: Optional[Dict[str, Any]] = None) -> str:
    """
    Format price with appropriate decimal precision
    - 3 decimals if market source is 'ws' (WebSocket - more precise)
    - 4 decimals otherwise (standard)

    Args:
        price: Price to format
        market: Market data dict (optional, to check source)

    Returns:
        Formatted price string
    """
    if price is None:
        return "N/A"

    # Check if market has source='ws' for WebSocket precision
    if market and market.get('source') == 'ws':
        return f"${price:.3f}"
    else:
        return f"${price:.4f}"


async def _get_claimable_positions(user_id: int) -> List[Dict]:
    """Get claimable (redeemable) positions for a user"""
    import os
    SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

    try:
        if SKIP_DB:
            # Use API client
            from core.services.api_client import get_api_client
            api_client = get_api_client()
            result = await api_client.get_resolved_positions(user_id, use_cache=True)
            if result and result.get('resolved_positions'):
                return result.get('resolved_positions', [])
            return []
        else:
            # Direct DB access
            from core.database.connection import get_db
            from core.database.models import ResolvedPosition
            from sqlalchemy import select

            async with get_db() as db:
                # Show PENDING, PROCESSING, and FAILED positions (all allow retry)
                query = select(ResolvedPosition).where(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.status.in_(['PENDING', 'PROCESSING', 'FAILED']),
                    ResolvedPosition.is_winner == True,
                    ResolvedPosition.tokens_held >= 0.5  # Only show positions with >= 0.5 tokens
                ).order_by(ResolvedPosition.resolved_at.desc())
                result = await db.execute(query)
                claimable = result.scalars().all()

                return [pos.to_dict() for pos in claimable]
    except Exception as e:
        from infrastructure.logging.logger import get_logger
        logger = get_logger(__name__)
        logger.error(f"❌ Error fetching claimable positions: {e}")
        return []


async def build_positions_view(
    positions: List[Any],
    markets_map: Dict[str, Any],
    total_pnl: float,
    total_pnl_percentage: float,
    balance: Optional[float],
    usdc_balance: Optional[float] = None,
    include_refresh: bool = True,
    user_id: Optional[int] = None  # ✅ NEW: For fetching claimable positions
) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """
    Build positions portfolio view

    Args:
        positions: List of position objects
        markets_map: Dict mapping market_id to market data
        total_pnl: Total P&L amount
        total_pnl_percentage: Total P&L percentage
        balance: User balance or None
        usdc_balance: USDC balance or None
        include_refresh: Whether to include refresh button
        user_id: Internal user ID for fetching claimable positions (optional)

    Returns:
        Tuple of (message_text, keyboard)
    """
    # ✅ OPTIMIZATION: Lazy load claimable positions - try cache first, show placeholder if not available
    # Claimable positions will be loaded in background and message updated if needed
    claimable_positions = []
    claimable_loading = False
    if user_id:
        # Try to get from cache first (fast path - non-blocking)
        try:
            # Use use_cache=True to get from cache quickly
            import os
            SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"
            if SKIP_DB:
                from core.services.api_client import get_api_client
                api_client = get_api_client()
                result = await api_client.get_resolved_positions(user_id, use_cache=True)
                if result and result.get('resolved_positions'):
                    claimable_positions = result.get('resolved_positions', [])
            else:
                claimable_positions = await _get_claimable_positions(user_id)
        except Exception as e:
            from infrastructure.logging.logger import get_logger
            logger = get_logger(__name__)
            logger.debug(f"⚠️ Could not fetch claimable positions immediately: {e}")
            # Mark as loading - will be updated in background
            claimable_loading = True

    # Header with total P&L
    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

    message = f"📊 **YOUR PORTFOLIO** ({len(positions)} positions)\n\n"
    # Format P&L with proper sign (consistent with individual positions)
    pnl_formatted = f"${total_pnl:+.2f}" if total_pnl != 0 else "$0.00"
    pnl_pct_formatted = f"{total_pnl_percentage:+.1f}%" if total_pnl_percentage != 0 else "0.0%"
    message += f"{pnl_emoji} **Total P&L:** {pnl_formatted} ({pnl_pct_formatted})\n"

    # Show real USDC.e balance if available, otherwise show legacy balance
    if usdc_balance is not None:
        message += f"💵 **USDC.e Balance:** ${usdc_balance:.2f}\n"
    elif balance is not None:
        message += f"💰 **Balance:** ${balance:.2f}\n"

    # ✅ Add claimable winnings section if any (or show loading placeholder)
    keyboard = []
    if claimable_loading:
        message += f"\n🔍 **CLAIMABLE WINNINGS**\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"
        message += "⏳ Loading claimable positions...\n\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"
    elif claimable_positions:
        message += f"\n🎊 **CLAIMABLE WINNINGS**\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"

        for idx, claimable in enumerate(claimable_positions[:5]):  # Show max 5
            title = claimable['market_title']
            if len(title) > 50:
                title = title[:47] + "..."

            net_value = claimable['net_value']
            tokens = claimable['tokens_held']
            outcome = claimable['outcome']
            pnl = claimable['pnl']
            pnl_pct = claimable['pnl_percentage']
            status = claimable.get('status', 'PENDING')
            last_error = claimable.get('last_redemption_error')
            attempt_count = claimable.get('redemption_attempt_count', 0)

            profit_emoji = "📈" if pnl > 0 else "📉"
            profit_sign = "+" if pnl > 0 else ""

            # Show status indicator
            if status == 'FAILED':
                status_emoji = "⚠️"
                status_text = " (Previous attempt failed)"
            elif status == 'PROCESSING':
                status_emoji = "🔄"
                status_text = " (Processing...)"
            else:
                status_emoji = "✅"
                status_text = ""

            message += f"{idx + 1}. {status_emoji} {title}{status_text}\n"
            message += f"   💰 **Claimable:** ${net_value:.2f}\n"
            message += f"   {profit_emoji} **P&L:** {profit_sign}${pnl:.2f} ({profit_sign}{pnl_pct:.1f}%)\n"
            message += f"   📦 {tokens:.2f} {outcome} tokens\n"

            # Show error if previous attempt failed
            if status == 'FAILED' and last_error:
                error_short = last_error[:60] + "..." if len(last_error) > 60 else last_error
                message += f"   ⚠️ Last error: {error_short}\n"

            message += "\n"

            # Add redeem button
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 Redeem #{idx + 1}",
                    callback_data=f"redeem_position_{claimable['id']}"
                )
            ])

        message += "━━━━━━━━━━━━━━━━━━━━\n\n"

    message += "**Positions:**\n"

    # Positions list (limited to avoid message too long)
    # Note: keyboard already initialized above for claimable positions
    max_positions = 8  # Limit for UX

    for i, position in enumerate(positions[:max_positions], 1):
        market = markets_map.get(position.market_id, {})
        market_title = market.get('title', 'Unknown Market')

        # Position P&L
        pos_pnl_emoji = "🟢" if position.pnl_amount >= 0 else "🔴"
        pnl_display = f"{pos_pnl_emoji} ${position.pnl_amount:+.2f}"

        # Position summary line
        # Format entry price and current price based on market source
        # CRITICAL: Use WebSocket price from market for accurate display
        entry_price_formatted = format_price_with_precision(position.entry_price, market)
        current_price = _get_current_websocket_price_from_market(market, position.outcome, position)
        current_price_formatted = format_price_with_precision(current_price, market)
        message += f"{i}. **{market_title}**\n"
        message += f"   {position.outcome} • {position.amount:.2f} shares\n"
        message += f"   Entry: {entry_price_formatted} → Current: {current_price_formatted}\n"
        message += f"   {pnl_display} ({position.pnl_percentage:+.1f}%)\n\n"

        # Action buttons per position (1 per row for better readability)
        # Check if position has TP/SL set
        has_tpsl = position.take_profit_price or position.stop_loss_price

        if has_tpsl:
            # Position has TP/SL - show Edit option
            keyboard.append([
                InlineKeyboardButton(f"📝 {i}. Edit TP/SL", callback_data=f"tpsl_edit_{position.id}"),
                InlineKeyboardButton(f"💸 {i}. Sell Position", callback_data=f"sell_position_{position.id}")
            ])
        else:
            # Position has no TP/SL - show Set option
            keyboard.append([
                InlineKeyboardButton(f"⚙️ {i}. Set TP/SL", callback_data=f"tpsl_setup_{position.id}"),
                InlineKeyboardButton(f"💸 {i}. Sell Position", callback_data=f"sell_position_{position.id}")
            ])

    # Add global action buttons (like old code structure)
    if include_refresh:
        # First row: Refresh and View All TP/SL
        keyboard.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_positions"),
            InlineKeyboardButton("📊 View All TP/SL", callback_data="view_all_tpsl")
        ])

        # Second row: History and Check Redeemable
        keyboard.append([
            InlineKeyboardButton("📜 History", callback_data="history_page_0"),
            InlineKeyboardButton("🔍 Check Redeemable", callback_data="check_redeemable")
        ])

    # Add pagination hint if there are more positions
    if len(positions) > max_positions:
        message += f"*... and {len(positions) - max_positions} more positions*\n"
        keyboard.append([InlineKeyboardButton("📄 Show More", callback_data="positions_page_1")])

    return message.strip(), keyboard


def build_position_detail_view(position: Any, market: Optional[Dict[str, Any]]) -> Tuple[str, List[List[InlineKeyboardButton]]]:
    """
    Build detailed position view

    Args:
        position: Position object
        market: Market data dict or None

    Returns:
        Tuple of (message_text, keyboard)
    """
    market_title = market.get('title', 'Unknown Market') if market else 'Unknown Market'
    market_desc = market.get('description', '')[:150] if market else ''

    # Position metrics
    # CRITICAL: Use WebSocket price from market for accurate display
    current_price = _get_current_websocket_price_from_market(market, position.outcome, position)
    position_value = current_price * position.amount
    pnl_amount = position.pnl_amount
    pnl_percentage = position.pnl_percentage

    pnl_emoji = "🟢" if pnl_amount >= 0 else "🔴"
    pnl_sign = "+" if pnl_amount >= 0 else ""

    message = f"📊 **Position Details**\n\n"
    message += f"**Market:** {market_title[:60]}\n"

    if market_desc:
        message += f"**Description:** {market_desc}...\n"

    message += f"**Outcome:** {position.outcome}\n"
    message += f"**Tokens:** {position.amount:.2f}\n"
    # Format prices based on market source
    entry_price_formatted = format_price_with_precision(position.entry_price, market)
    current_price_formatted = format_price_with_precision(current_price, market)
    message += f"**Entry Price:** {entry_price_formatted}\n"
    message += f"**Current Price:** {current_price_formatted}\n"
    message += f"**Position Value:** ${position_value:.2f}\n\n"

    # Format P&L with proper sign
    pnl_formatted = f"${abs(pnl_amount):.2f}" if pnl_amount != 0 else "$0.00"
    pnl_pct_formatted = f"{abs(pnl_percentage):.1f}%" if pnl_percentage != 0 else "0.0%"
    message += f"**P&L:** {pnl_emoji} {pnl_sign}{pnl_formatted} ({pnl_sign}{pnl_pct_formatted})\n"

    # TP/SL status - format prices based on market source
    if position.take_profit_price:
        tp_price_formatted = format_price_with_precision(position.take_profit_price, market)
        message += f"🎯 **Take Profit:** {tp_price_formatted}\n"
    else:
        message += f"⏸️ **Take Profit:** Not set\n"

    if position.stop_loss_price:
        sl_price_formatted = format_price_with_precision(position.stop_loss_price, market)
        message += f"🛑 **Stop Loss:** {sl_price_formatted}\n"
    else:
        message += f"⏸️ **Stop Loss:** Not set\n"

    # Action buttons
    keyboard = [
        [
            InlineKeyboardButton("💰 Sell Position", callback_data=f"sell_position_{position.id}"),
            InlineKeyboardButton("🎯 Set TP/SL", callback_data=f"tpsl_setup_{position.id}")
        ],
        [InlineKeyboardButton("← Back to Portfolio", callback_data="refresh_positions")]
    ]

    return message.strip(), keyboard
