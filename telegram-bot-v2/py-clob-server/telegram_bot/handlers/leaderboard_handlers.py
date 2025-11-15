"""
Leaderboard Command Handlers
Displays weekly and all-time leaderboard rankings
"""

import logging
from decimal import Decimal
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import SessionLocal
from core.services.leaderboard_calculator import LeaderboardCalculator

logger = logging.getLogger(__name__)


async def handle_leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /leaderboard command
    Shows top 10 traders + user's position for both weekly and all-time leaderboards
    """
    try:
        user_id = update.effective_user.id

        # Get database session
        db = SessionLocal()

        # Fetch both leaderboards
        from database import LeaderboardEntry

        # Get current week bounds
        from datetime import datetime, timezone
        from core.services.leaderboard_calculator import LeaderboardCalculator
        week_start, week_end = LeaderboardCalculator.get_week_bounds()

        # Weekly leaderboard - filter by current week
        weekly_entries = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'weekly',
            LeaderboardEntry.week_start_date == week_start
        ).order_by(LeaderboardEntry.rank.asc()).all()

        # All-time leaderboard
        alltime_entries = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'all-time'
        ).order_by(LeaderboardEntry.rank.asc()).all()

        db.close()

        # Build leaderboard message
        message = await build_leaderboard_message(
            user_id,
            weekly_entries,
            alltime_entries
        )

        # Send leaderboard
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=build_leaderboard_keyboard()
        )

    except Exception as e:
        logger.error(f"Error in leaderboard command: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Error fetching leaderboard. Please try again later.",
            parse_mode=ParseMode.HTML
        )


async def build_leaderboard_message(
    user_id: int,
    weekly_entries: list,
    alltime_entries: list
) -> str:
    """
    Build formatted leaderboard message - Mobile optimized
    Shows top 10 + user's position with compact layout
    """
    message = "<b>🏆 POLYCOOL LEADERBOARD</b>\n\n"

    # Weekly Leaderboard
    message += "<b>📅 THIS WEEK</b>\n"
    message += "─────────────\n"

    if not weekly_entries:
        message += "<i>No traders this week</i>\n"
        message += "<i>(min $10 volume)</i>\n"
    else:
        # Show top 10
        for entry in weekly_entries[:10]:
            medal = get_medal_emoji(entry.rank)
            message += format_leaderboard_entry(entry, medal)

        # Find user's position
        user_position = None
        for entry in weekly_entries:
            if entry.user_id == user_id:
                user_position = entry
                break

        if user_position and user_position.rank > 10:
            message += "\n...\n"
            message += "<b>📍 YOUR RANK</b>\n"
            message += format_leaderboard_entry(user_position, "👤")

    message += "\n"

    # All-time Leaderboard
    message += "<b>🏆 ALL TIME</b>\n"
    message += "─────────────\n"

    if not alltime_entries:
        message += "<i>No traders yet</i>\n"
        message += "<i>(min $10 volume)</i>\n"
    else:
        # Show top 10
        for entry in alltime_entries[:10]:
            medal = get_medal_emoji(entry.rank)
            message += format_leaderboard_entry(entry, medal)

        # Find user's position
        user_position = None
        for entry in alltime_entries:
            if entry.user_id == user_id:
                user_position = entry
                break

        if user_position and user_position.rank > 10:
            message += "\n...\n"
            message += "<b>📍 YOUR RANK</b>\n"
            message += format_leaderboard_entry(user_position, "👤")

    message += "\n"
    message += "<i>💡 Min $10 volume • 🔄 Updates Sunday</i>"

    return message


def format_leaderboard_entry(entry, medal: str) -> str:
    """Format a single leaderboard entry - Mobile optimized"""
    pnl = Decimal(str(entry.pnl_amount)) if entry.pnl_amount else Decimal('0')
    pnl_pct = Decimal(str(entry.pnl_percentage)) if entry.pnl_percentage else Decimal('0')
    volume = Decimal(str(entry.total_volume_traded)) if entry.total_volume_traded else Decimal('0')

    # Determine color and emoji based on PNL
    if pnl >= 0:
        pnl_color = "🟢"
        pnl_symbol = "+"
    else:
        pnl_color = "🔴"
        pnl_symbol = ""

    # Truncate username for mobile (max 15 chars)
    username = (entry.username or 'Trader')[:15]
    if len((entry.username or 'Trader')) > 15:
        username += "..."

    # Mobile-optimized format: vertical layout
    line = (
        f"{medal} <b>#{entry.rank}</b> {username}\n"
        f"{'   '}{pnl_color} <b>{pnl_symbol}${pnl:.2f}</b> "
        f"({pnl_symbol}{pnl_pct:.1f}%) • "
        f"Vol: ${volume:.0f}\n"
    )

    return line


def get_medal_emoji(rank: int) -> str:
    """Get medal emoji for rank"""
    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }
    return medals.get(rank, f"#{rank:02d}")


def build_leaderboard_keyboard():
    """Build inline keyboard for leaderboard - Mobile optimized"""
    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="leaderboard_refresh"),
        ],
        [
            InlineKeyboardButton("📅 This Week", callback_data="leaderboard_weekly_stats"),
            InlineKeyboardButton("🏆 All Time", callback_data="leaderboard_alltime_stats"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_leaderboard_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle refresh button - recalculates leaderboard rankings"""
    query = update.callback_query
    await query.answer("Recalculating leaderboard...")

    # Re-run leaderboard command logic
    try:
        user_id = query.from_user.id

        db = SessionLocal()
        from database import LeaderboardEntry
        from core.services.leaderboard_calculator import LeaderboardCalculator
        from decimal import Decimal

        # Recalculate both leaderboards with $10 minimum
        weekly_leaderboard = LeaderboardCalculator.calculate_weekly_leaderboard(
            db,
            min_volume=Decimal('10')
        )
        LeaderboardCalculator.save_leaderboard_entries(db, weekly_leaderboard)

        alltime_leaderboard = LeaderboardCalculator.calculate_alltime_leaderboard(
            db,
            min_volume=Decimal('10')
        )
        LeaderboardCalculator.save_leaderboard_entries(db, alltime_leaderboard)

        # Get current week bounds
        week_start, week_end = LeaderboardCalculator.get_week_bounds()

        # Fetch updated entries - filter by current week
        weekly_entries = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'weekly',
            LeaderboardEntry.week_start_date == week_start
        ).order_by(LeaderboardEntry.rank.asc()).all()

        alltime_entries = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'all-time'
        ).order_by(LeaderboardEntry.rank.asc()).all()

        db.close()

        message = await build_leaderboard_message(user_id, weekly_entries, alltime_entries)

        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=build_leaderboard_keyboard()
        )

    except Exception as e:
        logger.error(f"Error refreshing leaderboard: {e}", exc_info=True)
        await query.answer("❌ Error refreshing", show_alert=True)



async def handle_leaderboard_weekly_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed weekly stats for user"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        db = SessionLocal()
        from database import LeaderboardEntry

        # Get user's weekly entry
        user_entry = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.user_id == user_id,
            LeaderboardEntry.period == 'weekly'
        ).first()

        db.close()

        if not user_entry:
            await query.answer("You haven't traded this week yet!", show_alert=True)
            return

        # Format detailed stats
        stats_message = format_detailed_stats(user_entry, "Weekly")

        await query.edit_message_text(
            stats_message,
            parse_mode=ParseMode.HTML,
            reply_markup=build_back_keyboard()
        )

    except Exception as e:
        logger.error(f"Error getting weekly stats: {e}", exc_info=True)
        await query.answer("❌ Error fetching stats", show_alert=True)


async def handle_leaderboard_alltime_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed all-time stats for user"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        db = SessionLocal()
        from database import LeaderboardEntry

        # Get user's all-time entry
        user_entry = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.user_id == user_id,
            LeaderboardEntry.period == 'all-time'
        ).first()

        db.close()

        if not user_entry:
            await query.answer("You haven't traded yet!", show_alert=True)
            return

        # Format detailed stats
        stats_message = format_detailed_stats(user_entry, "All-Time")

        await query.edit_message_text(
            stats_message,
            parse_mode=ParseMode.HTML,
            reply_markup=build_back_keyboard()
        )

    except Exception as e:
        logger.error(f"Error getting alltime stats: {e}", exc_info=True)
        await query.answer("❌ Error fetching stats", show_alert=True)


def format_detailed_stats(entry, period: str) -> str:
    """Format detailed trading statistics - Mobile optimized"""
    pnl = Decimal(str(entry.pnl_amount)) if entry.pnl_amount else Decimal('0')
    pnl_pct = Decimal(str(entry.pnl_percentage)) if entry.pnl_percentage else Decimal('0')
    buy_vol = Decimal(str(entry.total_buy_volume)) if entry.total_buy_volume else Decimal('0')
    sell_vol = Decimal(str(entry.total_sell_volume)) if entry.total_sell_volume else Decimal('0')
    total_vol = Decimal(str(entry.total_volume_traded)) if entry.total_volume_traded else Decimal('0')
    win_rate = Decimal(str(entry.win_rate)) if entry.win_rate else Decimal('0')

    # Determine emoji based on performance
    if pnl >= 0:
        pnl_emoji = "🟢"
    else:
        pnl_emoji = "🔴"

    message = f"<b>📊 {period} STATS</b>\n\n"
    message += f"<b>🏅 Rank:</b> #{entry.rank}\n"
    message += f"<b>👤 Trader:</b> {entry.username or 'Anonymous'}\n\n"

    # Compact P&L section
    message += f"<b>{pnl_emoji} P&L:</b>\n"
    message += f"• Amount: <code>${pnl:.2f}</code>\n"
    message += f"• Return: <code>{pnl_pct:+.2f}%</code>\n\n"

    # Compact Volume section
    message += f"<b>💰 Volume:</b>\n"
    message += f"• Buy: <code>${buy_vol:.2f}</code>\n"
    message += f"• Sell: <code>${sell_vol:.2f}</code>\n"
    message += f"• Total: <code>${total_vol:.2f}</code>\n\n"

    # Compact Trading stats
    message += f"<b>🎯 Performance:</b>\n"
    message += f"• Trades: <code>{entry.total_trades}</code>\n"
    message += f"• Wins: <code>{entry.winning_trades}</code>\n"
    message += f"• Losses: <code>{entry.losing_trades}</code>\n"
    message += f"• Win Rate: <code>{win_rate:.1f}%</code>\n"

    return message


def build_back_keyboard():
    """Build back button keyboard - Mobile optimized"""
    keyboard = [
        [InlineKeyboardButton("⬅️ Back to Leaderboard", callback_data="leaderboard_back")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_leaderboard_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to main leaderboard view"""
    query = update.callback_query

    try:
        user_id = query.from_user.id

        db = SessionLocal()
        from database import LeaderboardEntry

        # Get current week bounds
        from core.services.leaderboard_calculator import LeaderboardCalculator
        week_start, _ = LeaderboardCalculator.get_week_bounds()

        weekly_entries = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'weekly',
            LeaderboardEntry.week_start_date == week_start
        ).order_by(LeaderboardEntry.rank.asc()).all()

        alltime_entries = db.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'all-time'
        ).order_by(LeaderboardEntry.rank.asc()).all()

        db.close()

        message = await build_leaderboard_message(user_id, weekly_entries, alltime_entries)

        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=build_leaderboard_keyboard()
        )

    except Exception as e:
        logger.error(f"Error going back to leaderboard: {e}", exc_info=True)
        await query.answer("❌ Error", show_alert=True)
