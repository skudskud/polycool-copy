#!/usr:bin/env python3
"""
Formatters
Message formatting utilities for Telegram bot
"""

from typing import Dict, List, Optional


def format_market_info(market: dict, include_details: bool = True) -> str:
    """
    Format market information for display

    Args:
        market: Market dictionary
        include_details: Whether to include detailed information

    Returns:
        Formatted market string
    """
    question = market.get('question', 'Unknown Market')

    if not include_details:
        return f"**{question}**"

    # Get current prices if available
    outcomes = market.get('outcomes', [])
    outcome_prices = market.get('outcome_prices', [])
    yes_price = None
    no_price = None

    # outcome_prices is a separate array: ["0.897", "0.103"]
    if len(outcome_prices) >= 2:
        try:
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
        except (ValueError, TypeError, IndexError):
            pass

    formatted = f"**📊 {question}**\n\n"

    if yes_price is not None and no_price is not None:
        formatted += f"✅ YES: {yes_price:.1%}\n"
        formatted += f"❌ NO: {no_price:.1%}\n\n"

    # Add market metadata
    if market.get('volume'):
        formatted += f"💰 Volume: ${market['volume']:,.0f}\n"

    if market.get('end_date'):
        formatted += f"⏰ Ends: {market['end_date']}\n"

    return formatted


def format_position(position: dict, market: dict, pnl: Optional[Dict] = None) -> str:
    """
    Format position information for display

    Args:
        position: Position dictionary
        market: Market dictionary
        pnl: Optional P&L dictionary

    Returns:
        Formatted position string
    """
    outcome = position['outcome'].upper()
    tokens = position['tokens']
    buy_price = position.get('buy_price', 0)
    total_cost = position.get('total_cost', 0)
    question = market.get('question', 'Unknown Market')[:50]

    formatted = f"**{question}...**\n"
    formatted += f"🎯 Position: {outcome}\n"
    formatted += f"📦 Tokens: {tokens}\n"
    formatted += f"💵 Cost: ${total_cost:.2f} (${buy_price:.4f}/token)\n"

    if pnl:
        current_value = pnl['current_value']
        pnl_amount = pnl['pnl_amount']
        pnl_percentage = pnl['pnl_percentage']

        # Choose emoji based on profit/loss
        if pnl_amount > 0:
            pnl_emoji = "📈"
            sign = "+"
        elif pnl_amount < 0:
            pnl_emoji = "📉"
            sign = ""
        else:
            pnl_emoji = "➖"
            sign = ""

        formatted += f"{pnl_emoji} Value: ${current_value:.2f}\n"
        formatted += f"💰 P&L: {sign}${pnl_amount:.2f} ({sign}{pnl_percentage:.1f}%)\n"

    return formatted


def format_positions_summary(positions: Dict, include_pnl: bool = False) -> str:
    """
    Format summary of all positions

    Args:
        positions: Dictionary of all positions
        include_pnl: Whether to include P&L summary

    Returns:
        Formatted positions summary string
    """
    if not positions:
        return "📭 **No open positions**\n\nUse /markets to start trading!"

    position_count = len(positions)
    formatted = f"📊 **Your Positions** ({position_count})\n\n"

    if include_pnl:
        total_cost = sum(p.get('total_cost', 0) for p in positions.values())
        formatted += f"💵 Total Invested: ${total_cost:.2f}\n\n"

    formatted += "Use buttons below to manage positions:"

    return formatted


def format_wallet_info(wallet: dict, balance: Optional[float] = None) -> str:
    """
    Format wallet information for display

    Args:
        wallet: Wallet dictionary
        balance: Optional USDC balance

    Returns:
        Formatted wallet string
    """
    address = wallet.get('address', 'Unknown')

    formatted = f"**👛 Your Polygon Wallet**\n\n"
    formatted += f"📍 Address:\n`{address}`\n\n"

    if balance is not None:
        formatted += f"💰 USDC Balance: ${balance:.2f}\n\n"

    formatted += "✅ Wallet is ready for trading!"

    return formatted


def format_error_message(error: str, suggestion: Optional[str] = None) -> str:
    """
    Format error message with optional suggestion

    Args:
        error: Error message
        suggestion: Optional suggestion for resolving the error

    Returns:
        Formatted error string
    """
    formatted = f"❌ **Error**\n\n{error}\n"

    if suggestion:
        formatted += f"\n💡 **Suggestion:** {suggestion}"

    return formatted


def format_trade_confirmation(market: dict, outcome: str, amount: float,
                              estimated_tokens: int, estimated_price: float) -> str:
    """
    Format trade confirmation message

    Args:
        market: Market dictionary
        outcome: "yes" or "no"
        amount: USD amount
        estimated_tokens: Estimated tokens to receive
        estimated_price: Estimated price per token

    Returns:
        Formatted confirmation string
    """
    from .escape_utils import escape_markdown
    question = escape_markdown(market.get('question', 'Unknown Market')[:60])

    formatted = f"**🎯 Confirm Trade**\n\n"
    formatted += f"📊 Market: {question}...\n\n"
    formatted += f"**Details:**\n"
    formatted += f"• Position: {outcome.upper()}\n"
    formatted += f"• Amount: ${amount:.2f}\n"
    formatted += f"• Est. Tokens: ~{estimated_tokens}\n"
    formatted += f"• Est. Price: ${estimated_price:.4f}/token\n\n"
    formatted += f"⚡ **Ultra-fast execution** with aggressive pricing!\n\n"
    formatted += f"Confirm to proceed:"

    return formatted


def format_bridge_quote(sol_amount: float, usdc_amount: float, pol_amount: float,
                       fees: dict) -> str:
    """
    Format bridge quote information

    Args:
        sol_amount: SOL amount to bridge
        usdc_amount: Estimated USDC to receive
        pol_amount: Estimated POL for gas
        fees: Dictionary with fee breakdown

    Returns:
        Formatted bridge quote string
    """
    formatted = f"**🌉 Bridge Quote**\n\n"
    formatted += f"**Send:**\n"
    formatted += f"• {sol_amount:.4f} SOL (Solana)\n\n"
    formatted += f"**Receive on Polygon:**\n"
    formatted += f"• ~${usdc_amount:.2f} USDC.e (trading)\n"
    formatted += f"• ~{pol_amount:.4f} POL (gas)\n\n"

    if fees:
        total_fees = fees.get('total_fees', 0)
        formatted += f"**Fees:** ~{total_fees:.4f} SOL\n\n"

    formatted += f"⏱️ Estimated time: 2-5 minutes\n"
    formatted += f"✅ Auto-swap excess POL → USDC.e"

    return formatted


def format_success_message(title: str, details: List[str]) -> str:
    """
    Format success message with details

    Args:
        title: Success message title
        details: List of detail lines

    Returns:
        Formatted success string
    """
    formatted = f"✅ **{title}**\n\n"

    for detail in details:
        formatted += f"{detail}\n"

    return formatted


def truncate_text(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate text to maximum length

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format percentage with proper sign

    Args:
        value: Percentage value
        decimals: Number of decimal places

    Returns:
        Formatted percentage string
    """
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_usd(value: float, decimals: int = 2) -> str:
    """
    Format USD amount

    Args:
        value: USD value
        decimals: Number of decimal places

    Returns:
        Formatted USD string
    """
    return f"${value:.{decimals}f}"
