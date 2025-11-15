"""
Copy Trading Callbacks
Handles all inline button interactions for copy trading
"""

import logging
import os
import sys
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

# Import telegram_utils using absolute import
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from telegram_utils import safe_answer_callback_query

from core.services.copy_trading import get_copy_trading_service
from telegram_bot.handlers.copy_trading.formatters import (
    format_copy_trading_main,
    format_budget_settings,
    format_copy_history,
    format_error_message,
    format_success_message,
)

logger = logging.getLogger(__name__)


async def handle_switch_leader(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Search Leader' button click"""
    from telegram_bot.handlers.copy_trading.main import ASKING_POLYGON_ADDRESS

    query = update.callback_query
    await safe_answer_callback_query(query)

    await query.edit_message_text(
        "💼 *Enter Leader's Polygon Address:*\n\n"
        "_Example: 0x1234567890abcdef..._\n\n"
        "Type or paste the address directly.",
    )

    # ✅ FIX: Set flag to indicate we're expecting a Polygon address
    # This prevents other flows (like /markets custom amount) from being intercepted
    context.user_data['expecting_polygon_address'] = True

    return ASKING_POLYGON_ADDRESS


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Settings' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        pnl_data = service.get_follower_pnl_and_trades(user_id)
        budget = service._get_repo().get_budget(user_id)

        budget_info = {
            'allocation_percentage': float(budget.allocation_percentage) if budget else 50.0,
            'total_wallet_balance': float(budget.total_wallet_balance) if budget else 0,
            'allocated_budget': float(budget.allocated_budget) if budget else 0,
            'budget_used': float(budget.budget_used) if budget else 0,
            'budget_remaining': float(budget.budget_remaining) if budget else 0,
        }

        subscription = service._get_repo().get_active_subscription_for_follower(user_id)
        copy_mode = subscription.copy_mode if subscription else 'PROPORTIONAL'

        settings_text = format_budget_settings(
            allocation_pct=budget_info['allocation_percentage'],
            copy_mode=copy_mode,
            budget_remaining=budget_info['budget_remaining']
        )

        keyboard = [
            [InlineKeyboardButton("💰 Modify Budget %", callback_data="modify_budget")],
            [InlineKeyboardButton("🔄 Toggle Copy Mode", callback_data="modify_mode")],
            [InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="back_to_dashboard")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(settings_text, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error in settings: {e}")
        await query.edit_message_text(format_error_message(str(e)))


async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'History' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        grouped_history = service.get_grouped_history(user_id)
        history_text = format_copy_history(grouped_history)

        keyboard = [
            [InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="back_to_dashboard")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(history_text, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error in history: {e}")
        await query.edit_message_text(format_error_message(str(e)))


async def handle_stop_following(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Stop Following' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        leader_id = service.get_leader_for_follower(user_id)

        if not leader_id:
            await query.answer("❌ You are not following anyone", show_alert=True)
            return

        # Double-check: ensure we still have an active subscription before unsubscribing
        # (prevents issues if user clicks multiple times)
        current_leader = service.get_leader_for_follower(user_id)
        if not current_leader or current_leader != leader_id:
            await query.answer("❌ You are no longer following anyone", show_alert=True)
            return

        # Unsubscribe
        service.unsubscribe_from_leader(user_id, leader_id)

        # Verify the unsubscription worked
        final_leader = service.get_leader_for_follower(user_id)
        if final_leader:
            logger.error(f"❌ Unfollow failed: still following {final_leader} after unsubscribe")
            await query.answer("❌ Error: Failed to stop following", show_alert=True)
            return

        await query.edit_message_text(
            f"✅ *You stopped following leader {leader_id}*",
        )

    except Exception as e:
        logger.error(f"Error stopping follow: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_modify_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Modify Budget' button click - ask for new percentage"""
    query = update.callback_query
    await safe_answer_callback_query(query)

    # Set flag in user_data to indicate we're waiting for budget percentage
    context.user_data['awaiting_budget_percentage'] = True

    await query.edit_message_text(
        "💰 *Enter New Budget Allocation %:*\n\n"
        "_Enter a number between 5 and 100_\n"
        "_Example: 75_",
    )


async def handle_modify_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Toggle Copy Mode' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        subscription = service._get_repo().get_active_subscription_for_follower(user_id)

        if not subscription:
            await query.answer("❌ Not following a leader", show_alert=True)
            return

        # Show mode options
        current_mode = subscription.copy_mode

        keyboard = [
            [InlineKeyboardButton("📊 Proportional (% of wallet)", callback_data="mode_proportional")],
            [InlineKeyboardButton("💵 Fixed Amount", callback_data="mode_fixed")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_settings")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"🔄 *Select Copy Mode*\n\n"
            f"Current: {current_mode}\n\n"
            f"📊 Proportional: Copy a percentage of your wallet\n"
            f"💵 Fixed: Always copy a fixed amount",
            reply_markup=reply_markup,
        )

    except Exception as e:
        logger.error(f"Error in modify mode: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_back_to_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Back to Dashboard' button"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        leader_id = service.get_leader_for_follower(user_id)
        pnl_data = service.get_follower_pnl_and_trades(user_id)
        budget = service._get_repo().get_budget(user_id)

        budget_info = {
            'allocated_budget': float(budget.allocated_budget) if budget else 0,
            'allocation_percentage': float(budget.allocation_percentage) if budget else 0,
            'budget_remaining': float(budget.budget_remaining) if budget else 0,
        }

        dashboard_text = format_copy_trading_main(
            current_leader_id=leader_id,
            stats=pnl_data,
            budget_info=budget_info
        )

        keyboard = [
            [InlineKeyboardButton("🔄 Search Leader", callback_data="switch_leader")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            [InlineKeyboardButton("📋 History", callback_data="history")],
        ]
        if leader_id:
            keyboard.append([InlineKeyboardButton("🛑 Stop Following", callback_data="stop_following")])

        # Remove empty lists
        keyboard = [row for row in keyboard if row]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(dashboard_text, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error back to dashboard: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_confirm_leader_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline confirmation to follow a leader"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        leader_id = context.user_data.get('pending_leader_id')

        if not leader_id:
            await query.edit_message_text("❌ *Error:* Leader not found in context")
            return

        # Subscribe to leader
        result = service.subscribe_to_leader(
            follower_id=user_id,
            leader_id=leader_id,
            copy_mode='PROPORTIONAL',
        )

        from telegram_bot.handlers.copy_trading.formatters import format_subscription_success
        success_msg = format_subscription_success(leader_id, result.get('budget_allocation_pct', 50))

        await query.edit_message_text(success_msg)

        # Clean up context
        if 'pending_leader_id' in context.user_data:
            del context.user_data['pending_leader_id']
        if 'pending_leader_address' in context.user_data:
            del context.user_data['pending_leader_address']

    except Exception as e:
        logger.error(f"Error confirming leader: {e}")
        await query.edit_message_text(format_error_message(str(e)))


async def handle_cancel_leader_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel leader search"""
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f'Error answering query: {e}')

    # Clean up context
    if 'pending_leader_id' in context.user_data:
        del context.user_data['pending_leader_id']
    if 'pending_leader_address' in context.user_data:
        del context.user_data['pending_leader_address']

    await query.edit_message_text("❌ *Search Cancelled*\n\nUse /copy_trading to start over.")


async def handle_budget_percentage_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle budget percentage input from user (message handler)"""
    from telegram.ext import ConversationHandler

    user_id = update.effective_user.id
    service = get_copy_trading_service()

    try:
        # Parse input
        text = update.message.text.strip()
        allocation_pct = float(text)

        # Validate range (from config)
        from core.services.copy_trading.config import COPY_TRADING_CONFIG
        if allocation_pct < COPY_TRADING_CONFIG.MIN_ALLOCATION_PERCENTAGE or allocation_pct > COPY_TRADING_CONFIG.MAX_ALLOCATION_PERCENTAGE:
            await update.message.reply_text(
                f"❌ *Invalid Budget %*\n\n"
                f"Budget allocation must be between {COPY_TRADING_CONFIG.MIN_ALLOCATION_PERCENTAGE:.0f}% and {COPY_TRADING_CONFIG.MAX_ALLOCATION_PERCENTAGE:.0f}%\n\n"
                f"_Try again or use /copy_trading to go back_",
            )
            # Keep the flag to allow retry
            return None

        # Update budget
        result = service.set_allocation_percentage(user_id, allocation_pct)

        await update.message.reply_text(
            f"✅ *Budget Updated!*\n\n"
            f"💰 New Allocation: {result['allocation_percentage']:.1f}%\n"
            f"📦 Allocated Budget: ${result['allocated_budget']:.2f}\n"
            f"💵 Remaining: ${result['budget_remaining']:.2f}\n\n"
            f"Use /copy_trading to manage your settings",
        )

        # Clear the flag
        context.user_data.pop('awaiting_budget_percentage', None)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid Input*\n\n"
            "Please enter a valid number (5-100)\n\n"
            "_Example: 75_",
        )
        # Keep the flag to allow retry
        return None
    except Exception as e:
        logger.error(f"Error updating budget: {e}")
        await update.message.reply_text(format_error_message(str(e)))
        # Clear the flag
        context.user_data.pop('awaiting_budget_percentage', None)
        return ConversationHandler.END


async def handle_mode_proportional(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Proportional Mode' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        subscription = service._get_repo().get_active_subscription_for_follower(user_id)

        if not subscription:
            await query.answer("❌ Not following a leader", show_alert=True)
            return

        # Update mode to proportional
        subscription.copy_mode = 'PROPORTIONAL'
        subscription.fixed_amount = None
        service._get_repo().db.commit()

        await query.edit_message_text(
            "✅ *Mode Updated to Proportional*\n\n"
            "📊 Your copy trading will now use:\n"
            "• A percentage of your wallet balance\n"
            "_The exact % is set in your budget allocation_\n\n"
            "Use /copy_trading to return to dashboard",
        )

    except Exception as e:
        logger.error(f"Error setting proportional mode: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_mode_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Fixed Mode' button click - ask for amount"""
    query = update.callback_query
    await safe_answer_callback_query(query)

    # Set flag in user_data to indicate we're waiting for fixed amount
    context.user_data['awaiting_fixed_amount'] = True

    await query.edit_message_text(
        "💵 *Enter Fixed Amount (USD):*\n\n"
        "_Every copy will use this exact amount_\n"
        "_Example: 50_",
    )


async def handle_fixed_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle fixed amount input from user (message handler)"""
    from telegram.ext import ConversationHandler

    user_id = update.effective_user.id
    service = get_copy_trading_service()

    try:
        # Parse input
        text = update.message.text.strip()
        fixed_amount = float(text)

        # Validate minimum (from config)
        from core.services.copy_trading.config import COPY_TRADING_CONFIG
        if fixed_amount < COPY_TRADING_CONFIG.MIN_COPY_AMOUNT_USD:
            await update.message.reply_text(
                f"❌ *Minimum Amount*\n\n"
                f"Fixed amount must be at least ${COPY_TRADING_CONFIG.MIN_COPY_AMOUNT_USD:.2f}\n\n"
                f"_Try again or use /copy_trading to go back_",
            )
            # Keep the flag to allow retry
            return None

        # Update mode and fixed amount
        subscription = service._get_repo().get_active_subscription_for_follower(user_id)
        if not subscription:
            await update.message.reply_text("❌ You are not following a leader")
            # Clear the flag
            context.user_data.pop('awaiting_fixed_amount', None)
            return ConversationHandler.END

        subscription.copy_mode = 'FIXED'
        subscription.fixed_amount = fixed_amount
        service._get_repo().db.commit()

        await update.message.reply_text(
            f"✅ *Fixed Amount Set!*\n\n"
            f"💵 Fixed Copy Amount: ${fixed_amount:.2f}\n"
            f"🔄 Each copy trade will use this exact amount\n\n"
            f"Use /copy_trading to manage your settings",
        )

        # Clear the flag
        context.user_data.pop('awaiting_fixed_amount', None)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid Input*\n\n"
            "Please enter a valid amount\n\n"
            "_Example: 50_",
        )
        # Keep the flag to allow retry
        return None
    except Exception as e:
        logger.error(f"Error setting fixed amount: {e}")
        await update.message.reply_text(format_error_message(str(e)))
        # Clear the flag
        context.user_data.pop('awaiting_fixed_amount', None)
        return ConversationHandler.END


async def handle_back_to_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Back to Settings' button"""
    query = update.callback_query
    user_id = update.effective_user.id
    await safe_answer_callback_query(query)

    service = get_copy_trading_service()

    try:
        budget = service._get_repo().get_budget(user_id)
        subscription = service._get_repo().get_active_subscription_for_follower(user_id)
        copy_mode = subscription.copy_mode if subscription else 'PROPORTIONAL'

        budget_info = {
            'allocation_percentage': float(budget.allocation_percentage) if budget else 50.0,
            'budget_remaining': float(budget.budget_remaining) if budget else 0,
        }

        settings_text = format_budget_settings(
            allocation_pct=budget_info['allocation_percentage'],
            copy_mode=copy_mode,
            budget_remaining=budget_info['budget_remaining']
        )

        keyboard = [
            [InlineKeyboardButton("💰 Modify Budget %", callback_data="modify_budget")],
            [InlineKeyboardButton("🔄 Toggle Copy Mode", callback_data="modify_mode")],
            [InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="back_to_dashboard")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(settings_text, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error returning to settings: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)
