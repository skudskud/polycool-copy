"""
Copy Trading Settings Callbacks
Handles settings, modify budget, toggle mode, and pause/resume
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from core.services.copy_trading import get_copy_trading_service
from ..constants import VIEWING_DASHBOARD, ENTERING_BUDGET
from ..formatters import format_budget_settings, format_error_message

logger = logging.getLogger(__name__)


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Settings' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    service = get_copy_trading_service()

    try:
        allocation = await service.get_active_allocation(user_id)
        if not allocation:
            await query.edit_message_text(
                format_error_message("No active copy trading subscription"),
                parse_mode='Markdown'
            )
            return

        budget_info = await service.get_budget_info(user_id)
        if not budget_info:
            await query.edit_message_text(
                format_error_message("Could not retrieve budget information"),
                parse_mode='Markdown'
            )
            return

        settings_text = format_budget_settings(
            allocation_value=allocation.allocation_value,
            allocation_type=allocation.allocation_type,
            copy_mode=allocation.mode,
            budget_remaining=budget_info.get('budget_remaining', 0.0),
            is_active=allocation.is_active
        )

        # Build keyboard with pause/resume button
        keyboard = [
            [InlineKeyboardButton("💰 Modify Budget", callback_data="copy_trading:modify_budget")],
            [InlineKeyboardButton("🔄 Toggle Copy Mode", callback_data="copy_trading:toggle_mode")],
        ]

        # Add pause/resume button based on current status
        if allocation.is_active:
            keyboard.append([InlineKeyboardButton("⏸️ Pause", callback_data="copy_trading:pause")])
        else:
            keyboard.append([InlineKeyboardButton("▶️ Resume", callback_data="copy_trading:resume")])

        keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="copy_trading:dashboard")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(settings_text, reply_markup=reply_markup, parse_mode='Markdown')
        except BadRequest as e:
            # Message content hasn't changed - this is fine, just ignore
            if "Message is not modified" in str(e):
                logger.debug("Settings message unchanged, skipping edit")
            else:
                raise

    except Exception as e:
        logger.error(f"Error in settings: {e}", exc_info=True)
        await query.edit_message_text(format_error_message(str(e)), parse_mode='Markdown')


async def handle_modify_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Modify Budget' button click"""
    query = update.callback_query
    await query.answer()

    from core.services.copy_trading.budget_calculator import CopyTradingBudgetConfig
    config = CopyTradingBudgetConfig()

    await query.edit_message_text(
        "💰 *Enter New Budget Allocation*\n\n"
        f"Enter a percentage between {config.MIN_ALLOCATION_PERCENTAGE:.0f}% and {config.MAX_ALLOCATION_PERCENTAGE:.0f}% "
        f"of your USDC balance to allocate for copy trading:\n\n"
        "_Example: 75 (for 75% of your balance)_",
        parse_mode='Markdown'
    )

    context.user_data['awaiting_budget'] = True

    return ENTERING_BUDGET


async def handle_toggle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Toggle Copy Mode' button click - show mode selection page"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    service = get_copy_trading_service()

    try:
        allocation = await service.get_active_allocation(user_id)
        if not allocation:
            await query.answer("❌ Not following a leader", show_alert=True)
            return

        budget_info = await service.get_budget_info(user_id)
        current_mode = allocation.mode

        # Show mode selection page
        mode_selection_text = (
            f"📊 *Select Copy Mode*\n\n"
            f"Current Mode: *{'Fixed Amount' if current_mode == 'fixed_amount' else 'Proportional'}*\n\n"
            f"• *Fixed Amount*: Always copy the same USD amount per trade\n"
            f"• *Proportional*: Copy % of your budget based on leader's % of wallet\n\n"
            f"_Select a mode to continue._"
        )

        keyboard = [
            [
                InlineKeyboardButton("💵 Fixed Amount", callback_data="copy_trading:settings_mode_fixed"),
                InlineKeyboardButton("📊 Proportional", callback_data="copy_trading:settings_mode_proportional"),
            ],
            [InlineKeyboardButton("⬅️ Back to Settings", callback_data="copy_trading:settings")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(mode_selection_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error showing mode selection: {e}", exc_info=True)
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_pause_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Pause' or 'Resume' button click"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    service = get_copy_trading_service()

    try:
        allocation = await service.get_active_allocation(user_id)
        if not allocation:
            await query.answer("❌ Not following a leader", show_alert=True)
            return

        # Determine action based on callback data
        is_pause = query.data == "copy_trading:pause"
        new_status = not allocation.is_active if is_pause else True

        success = await service.update_allocation_settings(
            follower_user_id=user_id,
            is_active=new_status
        )

        if success:
            action = "paused" if is_pause else "resumed"
            await query.answer(f"✅ Copy trading {action}", show_alert=True)

            # Get updated allocation and budget info
            allocation = await service.get_active_allocation(user_id)  # Refresh allocation
            budget_info = await service.get_budget_info(user_id)

            if allocation and budget_info:
                # Build updated settings message
                settings_text = format_budget_settings(
                    allocation_value=allocation.allocation_value,
                    allocation_type=allocation.allocation_type,
                    copy_mode=allocation.mode,
                    budget_remaining=budget_info.get('budget_remaining', 0.0),
                    is_active=allocation.is_active
                )

                # Build updated keyboard
                keyboard = [
                    [InlineKeyboardButton("💰 Modify Budget", callback_data="copy_trading:modify_budget")],
                    [InlineKeyboardButton("🔄 Toggle Copy Mode", callback_data="copy_trading:toggle_mode")],
                ]

                # Add pause/resume button based on current status
                if allocation.is_active:
                    keyboard.append([InlineKeyboardButton("⏸️ Pause", callback_data="copy_trading:pause")])
                else:
                    keyboard.append([InlineKeyboardButton("▶️ Resume", callback_data="copy_trading:resume")])

                keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="copy_trading:dashboard")])

                reply_markup = InlineKeyboardMarkup(keyboard)

                # Update the message directly
                try:
                    await query.edit_message_text(
                        settings_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                except BadRequest as e:
                    if "Message is not modified" in str(e):
                        logger.debug("Settings message unchanged after pause/resume - this is expected")
                    else:
                        raise
        else:
            await query.answer("❌ Failed to update status", show_alert=True)

    except Exception as e:
        logger.error(f"Error pausing/resuming: {e}", exc_info=True)
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)
