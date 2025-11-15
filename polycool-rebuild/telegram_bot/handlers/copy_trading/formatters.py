"""
Copy Trading Message Formatters
Pure formatting functions for Telegram messages
"""
from typing import Dict, Any, List, Optional


def format_copy_trading_main(
    leader_info: Optional[Dict[str, Any]] = None,
    stats: Optional[Dict[str, Any]] = None,
    budget_info: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Format main copy trading view

    Args:
        leader_info: Dict with leader info (address, type, name)
        stats: Dict with stats (trades_copied, total_invested, total_pnl)
        budget_info: Dict with budget info (allocation_percentage, budget_remaining)
    """
    lines = [
        "📊 *Copy Trading Dashboard*\n",
    ]

    if leader_info:
        leader_address = leader_info.get('address', 'Unknown')
        leader_name = leader_info.get('name', leader_address[:10] + '...')
        leader_type = leader_info.get('type', 'copy_leader')

        lines.append(f"👥 *Current Leader:* `{leader_address}`")
        if leader_name and leader_name != leader_address[:10] + '...':
            lines.append(f"   {leader_name}")
        lines.append("")

        if stats:
            lines.append("📈 *Stats:*")
            trades_copied = stats.get('trades_copied') or 0
            total_invested = stats.get('total_invested') or 0.0
            total_pnl = stats.get('total_pnl') or 0.0
            lines.append(f"  • Trades Copied: {trades_copied}")
            lines.append(f"  • Total Invested: ${float(total_invested):.2f}")
            lines.append(f"  • PnL: ${float(total_pnl):.2f}")
            lines.append("")

        if budget_info:
            allocation_value = budget_info.get('allocation_value') or budget_info.get('allocation_percentage') or 0.0
            allocation_type = budget_info.get('allocation_type', 'fixed_amount')
            budget_remaining = budget_info.get('budget_remaining') or 0.0

            lines.append("💰 *Budget:*")
            if allocation_type == 'percentage':
                lines.append(f"  • Allocation: {float(allocation_value):.0f}% of USDC.e balance")
            else:
                lines.append(f"  • Fixed Amount: ${float(allocation_value):.2f} USDC")
            lines.append(f"  • Remaining: ${float(budget_remaining):.2f}")
            lines.append("")
    else:
        lines.append("❌ *Not Currently Copy Trading*\n")
        lines.append("Use 'Search Leader' to start following a trader.")

    return "\n".join(lines)


def format_budget_settings(
    allocation_value: float,
    allocation_type: str,
    copy_mode: str,
    budget_remaining: float,
    is_active: bool = True
) -> str:
    """Format budget settings view"""
    lines = [
        "⚙️ *Copy Trading Settings*\n",
    ]

    # Ensure values are not None
    allocation_value = allocation_value or 0.0
    budget_remaining = budget_remaining or 0.0
    copy_mode = copy_mode or 'proportional'

    # Status indicator
    status_emoji = "✅" if is_active else "⏸️"
    status_text = "Active" if is_active else "Paused"
    lines.append(f"{status_emoji} *Status:* {status_text}\n")

    # allocation_value is always a percentage now
    percentage_str = f"{float(allocation_value):.1f}"
    lines.append(f"💼 *Budget Allocation:* {percentage_str}%\n")

    # Convert mode to user-friendly display name
    mode_display_name = _get_mode_display_name(copy_mode)
    lines.append(f"🔄 *Copy Mode:* {mode_display_name}\n")

    budget_str = f"{float(budget_remaining):.2f}"
    lines.append(f"⏳ *Budget Remaining:* ${budget_str}\n")
    lines.append("*⏬ You can change:*")
    lines.append("  • Budget allocation percentage (5-100%)")
    lines.append("  • Copy mode (Proportional / Fixed)")
    lines.append("  • Pause/Resume copy trading")

    return "\n".join(lines)


def format_leader_stats(stats: Dict[str, Any]) -> str:
    """Format leader statistics view"""
    lines = [
        "👑 *Leader Statistics*\n",
    ]

    leader_address = stats.get('address', 'Unknown')
    leader_name = stats.get('name', leader_address[:10] + '...')

    lines.append(f"👥 *Leader:* `{leader_address}`")
    if leader_name:
        lines.append(f"   {leader_name}")
    lines.append("")

    total_trades = stats.get('total_trades')
    if total_trades:
        lines.append(f"📊 *Total Trades:* {total_trades}")

    win_rate = stats.get('win_rate')
    if win_rate is not None:
        lines.append(f"🎯 *Win Rate:* {float(win_rate):.1f}%")

    total_volume = stats.get('total_volume')
    if total_volume:
        lines.append(f"💵 *Total Volume:* ${float(total_volume):.2f}")

    risk_score = stats.get('risk_score')
    if risk_score is not None:
        lines.append(f"📈 *Smartscore:* {float(risk_score):.2f}")

    return "\n".join(lines)


def format_error_message(error: str) -> str:
    """Format error message"""
    return f"❌ *Error:* {error}"


def format_success_message(message: str) -> str:
    """Format success message"""
    return f"✅ {message}"


def _get_mode_display_name(mode: str) -> str:
    """
    Convert mode value to user-friendly display name

    Args:
        mode: Mode value ('fixed_amount', 'proportional', etc.)

    Returns:
        User-friendly display name
    """
    mode_lower = (mode or '').lower()
    if mode_lower == 'fixed_amount':
        return 'Fixed Amount'
    elif mode_lower == 'proportional':
        return 'Proportional'
    else:
        # Fallback: capitalize and replace underscores
        return mode.replace('_', ' ').title() if mode else 'Proportional'


def _escape_markdown(text: str) -> str:
    """
    Escape special Markdown characters for Telegram (Markdown mode, not MarkdownV2)
    Only escape characters that are actually special in Markdown mode:
    - _ (underscore for italic)
    - * (asterisk for bold)
    - [ (opening bracket for links)
    - ] (closing bracket for links)
    - ` (backtick for code)
    - ~ (tilde for strikethrough, but not always needed)
    """
    # Only escape characters that are special in Markdown mode
    special_chars = ['_', '*', '[', ']', '`']
    escaped = text
    for char in special_chars:
        escaped = escaped.replace(char, f'\\{char}')
    return escaped


def format_subscription_success(
    leader_address: str,
    leader_name: Optional[str],
    allocation_value: float,
    allocation_type: str
) -> str:
    """Format successful subscription confirmation"""
    # Escape special characters for Markdown
    escaped_address = _escape_markdown(leader_address)

    lines = [
        "✅ Successfully Following Leader!",
        "",
        "👥 Leader:",
        f"`{escaped_address}`",
    ]

    # Add leader name if available (safely escaped)
    if leader_name:
        escaped_name = _escape_markdown(str(leader_name))
        lines.insert(3, f"   {escaped_name}")

    lines.extend([
        "",
        f"💰 Budget Allocation: ${allocation_value:.2f} USDC",
        "",
        "📊 Copy Mode: PROPORTIONAL",
        "",
        "Your trades will be copied automatically!",
        "",
        "Use /copy_trading to manage your settings.",
    ])

    return "\n".join(lines)
