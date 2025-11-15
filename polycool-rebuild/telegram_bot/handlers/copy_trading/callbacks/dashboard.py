"""
Copy Trading Dashboard Callbacks
Handles dashboard, history, and search leader callbacks
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from core.services.copy_trading import get_copy_trading_service
from ..constants import VIEWING_DASHBOARD, ASKING_POLYGON_ADDRESS
from ..formatters import format_copy_trading_main, format_error_message

logger = logging.getLogger(__name__)


async def handle_search_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Search Leader' button click"""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💼 *Enter Leader's Polygon Address:*\n\n"
        "_Example: 0x1234567890abcdef..._\n\n"
        "Type or paste the address directly.",
        parse_mode='Markdown'
    )

    # Set flag to indicate we're expecting a Polygon address
    context.user_data['expecting_polygon_address'] = True

    return ASKING_POLYGON_ADDRESS


async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'History' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    service = get_copy_trading_service()

    try:
        stats = await service.get_follower_stats(user_id)
        allocation = await service.get_active_allocation(user_id)

        # Check if there are any trades
        trades_copied = stats.get('trades_copied', 0)
        total_invested = stats.get('total_invested', 0.0)

        if not allocation or trades_copied == 0:
            history_text = "📋 *Copy Trading History*\n\nNo trades yet."
        else:
            history_text = (
                "📋 *Copy Trading History*\n\n"
                f"📊 *Trades Copied:* {trades_copied}\n"
                f"💰 *Total Invested:* ${float(total_invested):.2f}\n"
                f"📈 *Total PnL:* ${float(stats.get('total_pnl', 0)):.2f}\n"
            )

        keyboard = [
            [InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="copy_trading:dashboard")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(history_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in history: {e}", exc_info=True)
        await query.edit_message_text(format_error_message(str(e)), parse_mode='Markdown')


async def handle_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Back to Dashboard' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    service = get_copy_trading_service()

    try:
        # Get current leader info
        leader_info = await service.get_leader_info_for_follower(user_id)

        # Get stats if copy trading
        stats = None
        budget_info = None
        if leader_info:
            stats = await service.get_follower_stats(user_id)
            budget_info = await service.get_budget_info(user_id)

        # Format main view
        main_text = format_copy_trading_main(
            leader_info=leader_info,
            stats=stats,
            budget_info=budget_info
        )

        # Create inline keyboard
        keyboard = [
            [
                InlineKeyboardButton("🔄 Search Leader", callback_data="copy_trading:search_leader"),
                InlineKeyboardButton("⚙️ Settings", callback_data="copy_trading:settings")
            ],
            [InlineKeyboardButton("📋 History", callback_data="copy_trading:history")],
        ]

        if leader_info:
            keyboard.append([InlineKeyboardButton("🛑 Stop Following", callback_data="copy_trading:stop_following")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(main_text, reply_markup=reply_markup, parse_mode='Markdown')

        # Store context
        context.user_data['current_leader'] = leader_info

    except Exception as e:
        logger.error(f"Error in dashboard: {e}", exc_info=True)
        await query.edit_message_text(format_error_message(str(e)), parse_mode='Markdown')


async def handle_cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Cancel' button click"""
    query = update.callback_query
    await query.answer()

    # Clear pending data
    context.user_data.pop('pending_leader_info', None)
    context.user_data.pop('expecting_polygon_address', None)
    context.user_data.pop('selected_budget_percentage', None)
    context.user_data.pop('allocated_budget', None)
    context.user_data.pop('current_balance', None)

    await query.edit_message_text(
        "❌ *Search Cancelled*\n\n"
        "Use /copy_trading to start again.",
        parse_mode='Markdown'
    )

    return ConversationHandler.END
