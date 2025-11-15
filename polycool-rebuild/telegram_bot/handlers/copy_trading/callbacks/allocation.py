"""
Copy Trading Allocation Callbacks
Handles budget percentage and copy mode selection
"""
import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest

from core.services.copy_trading import get_copy_trading_service
from core.services.clob.clob_service import get_clob_service
from ..constants import SELECTING_COPY_MODE, ENTERING_FIXED_AMOUNT
from ..helpers import get_leader_stats
from ..formatters import format_error_message, format_success_message, format_budget_settings

logger = logging.getLogger(__name__)


async def handle_budget_percentage_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle budget percentage selection (25%, 50%, 75%, 100%)"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    # Extract percentage from callback_data (e.g., "copy_trading:budget_25" -> 25)
    percentage = int(query.data.split('_')[-1])

    # Get pending leader info and current balance
    pending_leader = context.user_data.get('pending_leader_info')
    current_balance = context.user_data.get('current_balance', 0.0)

    if not pending_leader:
        await query.edit_message_text(
            format_error_message("Leader information not found. Please start over."),
            parse_mode='MarkdownV2'
        )
        return ConversationHandler.END

    # Calculate allocated budget
    allocated_budget = current_balance * (percentage / 100.0)

    # Store selected percentage
    context.user_data['selected_budget_percentage'] = percentage
    context.user_data['allocated_budget'] = allocated_budget

    # Show confirmation and ask for copy mode
    # Use escape_markdown for dynamic values to prevent parsing issues
    from telegram.helpers import escape_markdown
    escaped_percentage = escape_markdown(f"{percentage}%", version=2)
    escaped_current_balance = escape_markdown(f"${current_balance:.2f}", version=2)
    escaped_allocated_budget = escape_markdown(f"${allocated_budget:.2f}", version=2)

    mode_text = (
        f"✅ *Budget Allocation Set*\n\n"
        f"Selected: *{escaped_percentage}* of {escaped_current_balance}\n"
        f"Allocated Budget: *{escaped_allocated_budget} USDC*\n\n"
        f"📊 *Select Copy Mode\\:*\n\n"
        f"• *Fixed Amount*\\: Always copy the same USD amount per trade\n"
        f"• *Proportional*\\: Copy \\% of your budget based on leader's \\% of wallet\n\n"
        f"_You can change this later in Settings\\._"
    )

    keyboard = [
        [
            InlineKeyboardButton("💵 Fixed Amount", callback_data="copy_trading:mode_fixed"),
            InlineKeyboardButton("📊 Proportional", callback_data="copy_trading:mode_proportional"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="copy_trading:cancel_search")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(mode_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    return SELECTING_COPY_MODE


async def handle_copy_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle copy mode selection (Fixed Amount or Proportional)"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    # Extract mode from callback_data (e.g., "copy_trading:mode_fixed" -> "fixed_amount")
    mode_str = query.data.split('_')[-1]  # "fixed" or "proportional"
    mode = 'fixed_amount' if mode_str == 'fixed' else 'proportional'

    # Get pending leader info and selected percentage
    pending_leader = context.user_data.get('pending_leader_info')
    selected_percentage = context.user_data.get('selected_budget_percentage')
    allocated_budget = context.user_data.get('allocated_budget', 0.0)

    if not pending_leader or selected_percentage is None:
        await query.edit_message_text(
            format_error_message("Missing information. Please start over."),
            parse_mode='MarkdownV2'
        )
        return ConversationHandler.END

    service = get_copy_trading_service()

    try:
        # If Fixed Amount mode, prompt for amount input
        if mode == 'fixed_amount':
            # Get current balance for reference
            from core.services.user.user_helper import get_user_data
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

            # Use escape_markdown for dynamic values to prevent parsing issues
            from telegram.helpers import escape_markdown
            escaped_percentage = escape_markdown(f"{selected_percentage}%", version=2)
            escaped_allocated_budget = escape_markdown(f"${allocated_budget:.2f}", version=2)
            escaped_current_balance = escape_markdown(f"${current_balance:.2f}", version=2)

            fixed_amount_text = (
                f"💵 *Enter Fixed Amount*\n\n"
                f"Your Budget Allocation: *{escaped_percentage}* \\({escaped_allocated_budget} USDC\\)\n"
                f"Your Current Balance: *{escaped_current_balance}*\n\n"
                f"Enter the fixed amount in USD for each copy trade\\:\n\n"
                f"_Example: 50 \\(for \\$50 per trade\\)_\n\n"
                f"💡 *Note\\:* Fixed amount must be between \\$2 and \\$1000"
            )

            keyboard = [
                [InlineKeyboardButton("❌ Cancel", callback_data="copy_trading:cancel_search")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(fixed_amount_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

            # Store mode in context for later use
            context.user_data['selected_mode'] = mode

            return ENTERING_FIXED_AMOUNT

        # If Proportional mode, subscribe immediately
        else:
            result = await service.subscribe_to_leader(
                follower_user_id=user_id,
                leader_address=pending_leader['address'],
                allocation_type='percentage',
                allocation_value=float(selected_percentage),
                mode=mode
            )

            if result.get('success'):
                # Get leader name for success message (via API or DB)
                leader_stats = await get_leader_stats(pending_leader['watched_address_id'], pending_leader['address'])
                leader_name = leader_stats.get('name')

                mode_display = "Proportional"

                # Build success message with safe text formatting
                success_text = "✅ *Successfully Subscribed!*\n\n"
                success_text += f"👤 Leader: `{pending_leader['address'][:10]}...`\n"

                if leader_name:
                    # Escape Markdown special characters in name
                    escaped_name = escape_markdown(leader_name, version=2)
                    success_text += f"📛 Name: {escaped_name}\n"

                success_text += "\n"
                # Use escape_markdown for dynamic values to prevent parsing issues
                from telegram.helpers import escape_markdown
                escaped_percentage = escape_markdown(f"{selected_percentage}%", version=2)
                escaped_allocated_budget = escape_markdown(f"${allocated_budget:.2f}", version=2)
                escaped_mode = escape_markdown(mode_display, version=2)

                success_text += f"💰 Budget Allocation: *{escaped_percentage}* \\({escaped_allocated_budget} USDC\\)\n"
                success_text += f"📊 Copy Mode: *{escaped_mode}*\n\n"
                success_text += "Your copy trading is now active\\!\n"
                success_text += "Use /copy_trading to view your dashboard\\."

                await query.edit_message_text(success_text, parse_mode='MarkdownV2')

                # Clear context
                context.user_data.pop('pending_leader_info', None)
                context.user_data.pop('selected_budget_percentage', None)
                context.user_data.pop('allocated_budget', None)
                context.user_data.pop('current_balance', None)

                return ConversationHandler.END
            else:
                await query.edit_message_text(
                    format_error_message("Failed to subscribe to leader. Please try again."),
                    parse_mode='MarkdownV2'
                )
                return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in copy mode selection: {e}", exc_info=True)
        await query.edit_message_text(
            format_error_message(f"Error: {str(e)}"),
            parse_mode='MarkdownV2'
        )
        return ConversationHandler.END


async def handle_settings_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mode selection from settings (Fixed Amount or Proportional)"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    # Extract mode from callback_data (e.g., "copy_trading:settings_mode_fixed" -> "fixed_amount")
    mode_str = query.data.split('_')[-1]  # "fixed" or "proportional"
    mode = 'fixed_amount' if mode_str == 'fixed' else 'proportional'

    service = get_copy_trading_service()

    try:
        # Check if SKIP_DB is true for service calls
        SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"
        if SKIP_DB:
            from core.services.api_client import get_api_client
            api_client = get_api_client()
            allocation = await api_client.get_follower_allocation(user_id)
            allocation = allocation if allocation else None
        else:
            allocation = await service.get_active_allocation(user_id)

        if not allocation:
            await query.answer("❌ Not following a leader", show_alert=True)
            return

        # If Fixed Amount mode, prompt for amount input
        if mode == 'fixed_amount':
            # Get current balance for reference
            from core.services.user.user_helper import get_user_data
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

            # Get allocation percentage from budget info
            SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"
            if SKIP_DB:
                from core.services.api_client import get_api_client
                api_client = get_api_client()
                budget_info = await api_client.get_follower_allocation(user_id)
                allocation_percentage = budget_info.get('allocation_percentage', budget_info.get('allocation_value', 0.0)) if budget_info else 0.0
            else:
                budget_info = await service.get_budget_info(user_id)
                allocation_percentage = budget_info.get('allocation_percentage', 0.0) if budget_info else 0.0

            # Always calculate allocated_budget from CURRENT balance and percentage
            # Don't trust cached allocated_budget as balance may have changed
            allocated_budget = current_balance * (allocation_percentage / 100.0) if allocation_percentage > 0 else 0.0

            # Format values for HTML
            from html import escape as html_escape
            percentage_str = f"{allocation_percentage:.1f}%"
            allocated_budget_str = f"${allocated_budget:.2f}"
            current_balance_str = f"${current_balance:.2f}"

            fixed_amount_text = (
                f"💵 <b>Enter Fixed Amount</b>\n\n"
                f"Your Budget Allocation: <b>{html_escape(percentage_str)}</b> ({html_escape(allocated_budget_str)} USDC)\n"
                f"Your Current Balance: <b>{html_escape(current_balance_str)}</b>\n\n"
                f"Enter the fixed amount in USD for each copy trade:\n\n"
                f"<i>Example: 50 (for $50 per trade)</i>\n\n"
                f"💡 <b>Note:</b> Fixed amount must be between $2 and $1000"
            )

            keyboard = [
                [InlineKeyboardButton("❌ Cancel", callback_data="copy_trading:settings")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(fixed_amount_text, reply_markup=reply_markup, parse_mode='HTML')

            # Mark that we're updating mode in settings
            context.user_data['updating_mode_in_settings'] = True

            # Return state for ConversationHandler
            return ENTERING_FIXED_AMOUNT

        # If Proportional mode, update immediately
        else:
            success = await service.update_allocation_settings(
                follower_user_id=user_id,
                mode=mode
            )

            if success:
                # Invalidate cache to ensure we get fresh data
                if SKIP_DB:
                    from core.services.cache_manager import CacheManager
                    cache_manager = CacheManager()
                    await cache_manager.invalidate_pattern(f"api:copy_trading:followers:{user_id}*")

                # Small delay to ensure DB/API has updated
                import asyncio
                await asyncio.sleep(0.1)

                # Refresh allocation and budget info
                allocation = await service.get_active_allocation(user_id)
                budget_info = await service.get_budget_info(user_id)

                # Verify mode was actually updated
                if allocation and allocation.mode != mode:
                    logger.error(f"❌ Mode update failed! Expected {mode}, got {allocation.mode}")
                    await query.answer(f"❌ Failed to update mode. Current: {allocation.mode}", show_alert=True)
                    return

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

                    # Update the message
                    try:
                        await query.edit_message_text(
                            settings_text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                        await query.answer("✅ Mode changed to Proportional", show_alert=False)
                    except BadRequest as e:
                        # Message content hasn't changed - this can happen if mode didn't update
                        if "Message is not modified" in str(e):
                            logger.warning(f"⚠️ Message not modified - mode may not have updated. Current mode: {allocation.mode}")
                            await query.answer("⚠️ Mode update may have failed. Please check settings.", show_alert=True)
                        else:
                            raise

                # Return to dashboard state for ConversationHandler
                from ..constants import VIEWING_DASHBOARD
                return VIEWING_DASHBOARD
            else:
                await query.answer("❌ Failed to update mode", show_alert=True)
                # Return to dashboard state even on failure
                from ..constants import VIEWING_DASHBOARD
                return VIEWING_DASHBOARD

    except Exception as e:
        logger.error(f"Error in settings mode selection: {e}", exc_info=True)
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)
        # Return to dashboard state on error
        from ..constants import VIEWING_DASHBOARD
        return VIEWING_DASHBOARD
