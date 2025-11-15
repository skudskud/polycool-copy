"""
Copy Trading Leader Callbacks
Handles leader confirmation and stop following
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from core.services.user.user_helper import get_user_data
from core.services.copy_trading import get_copy_trading_service
from core.services.clob.clob_service import get_clob_service
from ..constants import SELECTING_BUDGET_PERCENTAGE
from ..formatters import format_error_message

logger = logging.getLogger(__name__)


async def handle_confirm_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Follow This Leader' button click - show budget percentage selection"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    # Extract watched_address_id from callback_data
    watched_address_id = int(query.data.split('_')[-1])

    # Get pending leader info
    pending_leader = context.user_data.get('pending_leader_info')
    if not pending_leader:
        # Use escape_markdown for error messages
        from telegram.helpers import escape_markdown
        escaped_error = escape_markdown("Leader information not found. Please start over.", version=2)
        await query.edit_message_text(
            f"❌ *Error:* {escaped_error}",
            parse_mode='MarkdownV2'
        )
        return ConversationHandler.END

    # Get current USDC balance
    clob_service = get_clob_service()
    balance_info = await clob_service.get_balance(user_id)

    # Debug logging
    logger.debug(f"Balance info for user {user_id}: {balance_info}")

    if not balance_info:
        logger.warning(f"⚠️ Could not get balance for user {user_id}, trying fallback...")
        # Try fallback: get balance by address
        user_data = await get_user_data(user_id)
        if user_data:
            polygon_address = user_data.get('polygon_address')
            if polygon_address:
                balance_info = await clob_service.get_balance_by_address(polygon_address)
                logger.debug(f"Fallback balance info: {balance_info}")

    current_balance = balance_info.get('balance', 0.0) if balance_info else 0.0

    logger.info(f"💰 User {user_id} balance: ${current_balance:.2f}")

    if current_balance <= 0:
        error_msg = (
            "❌ *No USDC Balance*\n\n"
            "You need USDC in your wallet to start copy trading.\n\n"
            "Use /wallet to fund your account."
        )
        if balance_info is None:
            error_msg += "\n\n⚠️ _Could not retrieve balance. Please try again or contact support._"

        await query.edit_message_text(error_msg, parse_mode='MarkdownV2')
        return ConversationHandler.END

    # Transition to budget percentage selection

    # Calculate amounts for each percentage
    amounts = {
        25: current_balance * 0.25,
        50: current_balance * 0.50,
        75: current_balance * 0.75,
        100: current_balance * 1.00
    }

    # Show balance and budget percentage options
    # Use escape_markdown for dynamic values to prevent parsing issues
    from telegram.helpers import escape_markdown
    escaped_balance = escape_markdown(f"${current_balance:.2f}", version=2)
    escaped_25 = escape_markdown(f"${amounts[25]:.2f}", version=2)
    escaped_50 = escape_markdown(f"${amounts[50]:.2f}", version=2)
    escaped_75 = escape_markdown(f"${amounts[75]:.2f}", version=2)
    escaped_100 = escape_markdown(f"${amounts[100]:.2f}", version=2)

    budget_text = (
        f"💰 *Set Budget Allocation*\n\n"
        f"Your USDC Balance: *{escaped_balance}*\n\n"
        f"Select the percentage of your wallet to allocate for copy trading\\:\n\n"
        f"• *25\\%* → {escaped_25} USDC\n"
        f"• *50\\%* → {escaped_50} USDC\n"
        f"• *75\\%* → {escaped_75} USDC\n"
        f"• *100\\%* → {escaped_100} USDC\n\n"
        f"_This budget will be recalculated from your current balance every hour\\._"
    )

    keyboard = [
        [
            InlineKeyboardButton("25%", callback_data=f"copy_trading:budget_25"),
            InlineKeyboardButton("50%", callback_data=f"copy_trading:budget_50"),
        ],
        [
            InlineKeyboardButton("75%", callback_data=f"copy_trading:budget_75"),
            InlineKeyboardButton("100%", callback_data=f"copy_trading:budget_100"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="copy_trading:cancel_search")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(budget_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    # Store pending leader and current balance
    context.user_data['pending_leader_info'] = pending_leader
    context.user_data['current_balance'] = current_balance

    return SELECTING_BUDGET_PERCENTAGE


async def handle_stop_following(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Stop Following' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    service = get_copy_trading_service()

    try:
        success = await service.unsubscribe_from_leader(user_id)

        if success:
            keyboard = [
                [InlineKeyboardButton("⬅️ Back to Copy Trading", callback_data="copy_trading:dashboard")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "✅ *You stopped following the leader*\n\n"
                "Your existing positions are unchanged\\.\n"
                "Use 'Search Leader' to follow a new trader\\.",
                reply_markup=reply_markup,
                parse_mode='MarkdownV2'
            )
        else:
            await query.answer("❌ You are not following anyone", show_alert=True)

    except Exception as e:
        logger.error(f"Error stopping follow: {e}", exc_info=True)
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)
