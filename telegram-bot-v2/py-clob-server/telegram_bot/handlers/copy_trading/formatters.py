"""
Copy Trading Message Formatters
Pure formatting functions for Telegram messages
"""

from typing import Dict, Any, List


def format_copy_trading_main(
    current_leader_id: int = None,
    leader_address: str = None,
    stats: Dict[str, Any] = None,
    budget_info: Dict[str, Any] = None,
) -> str:
    """Format main copy trading view"""
    lines = [
        "📊 Copy Trading Dashboard\n",
    ]

    if current_leader_id:
        if leader_address:
            # Show full address instead of user_id
            lines.append(f"👥 Current Leader: `{leader_address}`")
        else:
            # Fallback to user_id if no address
            lines.append(f"👥 Current Leader: {current_leader_id}")
        lines.append("")  # Empty line after leader info

        if stats:
            lines.append(f"📈 Stats:")
            lines.append(f"  • Trades Copied: {stats.get('trades_copied', 0)}")
            lines.append(f"  • Total Invested: ${stats.get('total_invested', 0):.2f}")
            lines.append(f"  • PnL: ${stats.get('total_pnl', 0):.2f}")
            lines.append("")

        if budget_info:
            allocation_pct = budget_info.get('allocation_percentage', 0)
            lines.append(f"💰 Budget:")
            lines.append(f"  • Allocation: {allocation_pct:.0f}% of USDC.e balance")
            lines.append(f"  • Calculated live on each trade")
            lines.append("")
    else:
        lines.append("❌ Not Currently Copy Trading\n")



    return "\n".join(lines)


def format_budget_settings(allocation_pct: float, copy_mode: str, budget_remaining: float) -> str:
    """Format budget settings view"""
    lines = [
        "⚙️ *Copy Trading Settings*\n",
        f"💼 *Budget Allocation:* {allocation_pct:.1f}%\n",
        f"🔄 *Copy Mode:* {copy_mode}\n",
        f"⏳ *Budget Remaining:* ${budget_remaining:.2f}\n",
        "*⏬ You can change:*",
        "  • Budget allocation percentage (5-100%)",
        "  • Copy mode (Proportional / Fixed)",
    ]
    return "\n".join(lines)


def format_copy_history(history_data: Dict[str, Any], limit: int = 10) -> str:
    """
    Format copy history view

    Args:
        history_data: Dict grouped by leader_id (from get_grouped_history)
        limit: Max records to display per leader
    """
    lines = [
        "📋 *Copy Trading History*\n",
    ]

    if not history_data:
        lines.append("No copy trades yet.")
        return "\n".join(lines)

    # history_data is a Dict[leader_id, stats]
    # Iterate through leaders
    for leader_id, leader_data in history_data.items():
        lines.append(f"\n👤 *Leader:* {leader_id}")
        lines.append(
            f"📊 {leader_data['total_trades']} trades | "
            f"✅ {leader_data['successful']} | "
            f"❌ {leader_data['failed']} | "
            f"💸 {leader_data['insufficient_budget']}"
        )
        lines.append(f"💰 Total invested: ${leader_data['total_invested']:.2f}\n")

        # Show recent records
        records = leader_data.get('records', [])
        if records:
            lines.append("Recent trades:")
            for record in records[:limit]:
                status_emoji = {
                    'SUCCESS': '✅',
                    'FAILED': '❌',
                    'PENDING': '⏳',
                    'INSUFFICIENT_BUDGET': '💸',
                    'CANCELLED': '🛑',
                }.get(record.get('status'), '❓')

                tx_type = record.get('transaction_type', 'UNKNOWN')
                outcome = record.get('outcome', 'unknown')
                amount = record.get('actual_copy_amount') or record.get('calculated_copy_amount', 0)

                lines.append(
                    f"  {status_emoji} {tx_type} {outcome.upper()} | ${float(amount):.2f}"
                )

    return "\n".join(lines)


def format_leader_stats(stats: Dict[str, Any]) -> str:
    """Format leader statistics view"""
    lines = [
        "👑 *Leader Statistics*\n",
        f"👥 *Active Followers:* {stats.get('total_active_followers', 0)}",
        f"📊 *Trades Copied:* {stats.get('total_trades_copied', 0)}",
        f"💵 *Volume Copied:* ${stats.get('total_volume_copied', 0):.2f}",
        f"🎁 *Fees Earned:* ${stats.get('total_fees_from_copies', 0):.2f}",
    ]

    if stats.get('total_pnl_followers'):
        lines.append(f"📈 *Follower PnL:* ${stats['total_pnl_followers']:.2f}")

    return "\n".join(lines)


def format_error_message(error: str) -> str:
    """Format error message"""
    return f"❌ *Error:* {error}"


def format_success_message(message: str) -> str:
    """Format success message"""
    return f"✅ {message}"


def format_subscription_success(leader_id: int, budget_allocation_pct: float) -> str:
    """Format successful subscription confirmation"""
    return (
        f"✅ *Successfully Following Leader!*\n\n"
        f"👥 *Leader ID:* {leader_id}\n"
        f"💰 *Budget Allocation:* {budget_allocation_pct:.1f}%\n"
        f"📊 *Copy Mode:* PROPORTIONAL\n\n"
        f"Your trades will be copied automatically!\n"
        f"Use /copy_trading to manage your settings."
    )


def format_positions_list(positions: List[Dict[str, Any]]) -> str:
    """Format active positions from copy trades"""
    lines = [
        "📈 *Active Positions (From Copied Trades)*\n",
    ]

    if not positions:
        lines.append("No active positions.")
        return "\n".join(lines)

    for pos in positions[:20]:  # Limit to 20
        lines.append(
            f"• {pos.get('market_id', 'Unknown')} - {pos.get('outcome', '?').upper()} "
            f"| Qty: {pos.get('quantity', 0):.2f} | PnL: ${pos.get('pnl', 0):.2f}"
        )

    return "\n".join(lines)


def format_pnl_summary(stats: Dict[str, Any]) -> str:
    """Format PnL summary for copy trading"""
    lines = [
        "📊 *Copy Trading P&L Summary*\n",
        f"💵 *Total Invested:* ${stats.get('total_invested', 0):.2f}",
        f"📈 *Current PnL:* ${stats.get('total_pnl', 0):.2f}",
    ]

    pnl_pct = 0
    if stats.get('total_invested', 0) > 0:
        pnl_pct = (stats.get('total_pnl', 0) / stats.get('total_invested', 0)) * 100

    pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
    lines.append(f"{pnl_emoji} *Return:* {pnl_pct:.2f}%")

    lines.append(f"\n🎯 *Trades Copied:* {stats.get('total_trades_copied', 0)}")
    lines.append(f"💼 *Budget Remaining:* ${stats.get('budget_remaining', 0):.2f}")

    return "\n".join(lines)
