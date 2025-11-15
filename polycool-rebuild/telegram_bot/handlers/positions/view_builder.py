"""
Position View Builder - Format positions for display
"""
from typing import List, Dict, Optional
from datetime import datetime

from core.database.models import Position, Market
from telegram import InlineKeyboardButton


def format_price(price: float) -> str:
    """Format price as $0.45"""
    if price is None:
        return "N/A"
    return f"${price:.4f}"


def format_pnl(pnl_amount: float, pnl_percentage: float) -> str:
    """Format P&L with color indicator"""
    if pnl_amount >= 0:
        return f"🟢 +${pnl_amount:.2f} (+{pnl_percentage:.1f}%)"
    else:
        return f"🔴 ${pnl_amount:.2f} ({pnl_percentage:.1f}%)"


def build_positions_view(
    positions: List[Position],
    markets_map: Dict[str, Market],
    total_pnl: float = 0.0,
    total_pnl_percentage: float = 0.0,
    balance: Optional[float] = None,
    usdc_balance: Optional[float] = None,
    include_refresh: bool = True
) -> tuple[str, List[List]]:
    """
    Build positions view message and keyboard

    Args:
        positions: List of Position objects
        markets_map: Dictionary mapping market_id to Market
        total_pnl: Total P&L amount
        total_pnl_percentage: Total P&L percentage
        balance: User balance (optional)
        include_refresh: Whether to include refresh button

    Returns:
        (message_text, keyboard) tuple
    """
    if not positions:
        message = "📭 **No Active Positions**\n\n"
        message += "✨ Your wallet has no active positions.\n\n"
        message += "Use /markets to start trading!"

        keyboard = [
            [InlineKeyboardButton("📊 Browse Markets", callback_data="markets_hub")]
        ]
        return message, keyboard

    # Build header
    message = "📊 **Your Positions**\n\n"

    # Show real USDC.e balance if available, otherwise show legacy balance
    if usdc_balance is not None:
        message += f"💵 **USDC.e Balance:** ${usdc_balance:.2f}\n"
    elif balance is not None:
        message += f"💼 **Balance:** ${balance:.2f}\n"

    message += f"📈 **Total P&L:** {format_pnl(total_pnl, total_pnl_percentage)}\n"
    message += f"📊 **Active Positions:** {len(positions)}\n\n"

    # Build position list
    keyboard = []
    for i, position in enumerate(positions[:20], start=1):  # Limit to 20
        market = markets_map.get(position.market_id)
        market_title = market.title[:50] if market else "Unknown Market"

        # Format position
        outcome_emoji = "✅" if position.outcome == "YES" else "❌"
        message += f"**{i}. {outcome_emoji} {position.outcome} • {market_title}**\n"
        message += f"   📊 Entry ${position.entry_price:.4f} → Current ${position.current_price:.4f}\n"
        message += f"   💰 ${(position.current_price * position.amount):.2f} ({position.amount:.0f} tokens) • {format_pnl(position.pnl_amount, position.pnl_percentage)}\n\n"

        # Add button
        button_text = f"{position.outcome} • {market_title[:25]}..."
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"position_{position.id}")
        ])

    # Add refresh button if requested
    if include_refresh:
        keyboard.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_positions")
        ])

    # Add back button
    keyboard.append([
        InlineKeyboardButton("← Back to Hub", callback_data="markets_hub")
    ])

    return message, keyboard


def build_position_detail_view(
    position: Position,
    market: Optional[Market] = None
) -> tuple[str, List[List]]:
    """
    Build detailed view for a single position

    Args:
        position: Position object
        market: Market object (optional)

    Returns:
        (message_text, keyboard) tuple
    """
    market_title = market.title if market else "Unknown Market"
    outcome_emoji = "✅" if position.outcome == "YES" else "❌"

    message = f"**{outcome_emoji} {position.outcome} • {market_title}**\n\n"

    message += f"📊 **Entry Price:** ${position.entry_price:.4f}\n"
    message += f"📈 **Current Price:** ${position.current_price:.4f}\n"
    message += f"💰 **Position Value:** ${(position.current_price * position.amount):.2f}\n"
    message += f"📦 **Tokens:** {position.amount:.0f}\n\n"

    message += f"**P&L:** {format_pnl(position.pnl_amount, position.pnl_percentage)}\n\n"

    if market:
        if market.end_date:
            from telegram_bot.bot.handlers.markets.formatters import format_end_date
            message += f"⏰ **Ends:** {format_end_date(market.end_date)}\n"

    # Build keyboard
    keyboard = [
        [InlineKeyboardButton("💰 Sell Position", callback_data=f"sell_position_{position.id}")],
        [InlineKeyboardButton("🎯 Set TP/SL", callback_data=f"tpsl_setup_{position.id}")],
        [InlineKeyboardButton("← Back to Positions", callback_data="positions_hub")]
    ]

    return message, keyboard
