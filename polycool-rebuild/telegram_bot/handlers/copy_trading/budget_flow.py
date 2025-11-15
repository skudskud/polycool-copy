"""
Copy Trading Budget Flow
Handles budget allocation, fixed amount input, and related callbacks
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from core.services.copy_trading import get_copy_trading_service
from core.database.connection import get_db
from core.database.models import WatchedAddress
from sqlalchemy import select
from .constants import (
    ENTERING_BUDGET,
    ENTERING_FIXED_AMOUNT,
    SKIP_DB
)
from .helpers import get_leader_stats
from .formatters import format_subscription_success, format_error_message

logger = logging.getLogger(__name__)

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_budget_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle budget allocation input - accepts percentage (5-100) only"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    logger.info(f"💰 ConversationHandler: handle_budget_input called for user {user_id}, text: '{text}'")

    try:
        # Parse input as percentage (remove % if present)
        try:
            percentage_text = text.replace('%', '').strip()
            percentage = float(percentage_text)
        except ValueError:
            await update.message.reply_text(
                "❌ *Invalid Percentage*\n\n"
                "Please enter a valid number between 5 and 100 (e.g., 75 for 75%)",
                parse_mode='Markdown'
            )
            return ENTERING_BUDGET

        # Validate percentage range (5-100)
        from core.services.copy_trading.budget_calculator import CopyTradingBudgetConfig
        config = CopyTradingBudgetConfig()

        if percentage < config.MIN_ALLOCATION_PERCENTAGE or percentage > config.MAX_ALLOCATION_PERCENTAGE:
            await update.message.reply_text(
                f"❌ *Invalid Percentage*\n\n"
                f"Budget allocation must be between {config.MIN_ALLOCATION_PERCENTAGE:.0f}% and {config.MAX_ALLOCATION_PERCENTAGE:.0f}%\n\n"
                f"_Example: 75 (for 75%)_",
                parse_mode='Markdown'
            )
            return ENTERING_BUDGET

        # Budget allocation is always a percentage
        allocation_type = 'percentage'
        allocation_value = percentage

        service = get_copy_trading_service()

        # Check if this is a modification (user already has an allocation) or new subscription
        if SKIP_DB:
            api_client = get_api_client()
            existing_allocation_data = await api_client.get_follower_allocation(user_id)
            existing_allocation = existing_allocation_data is not None
        else:
            existing_allocation = await service.get_active_allocation(user_id)
        pending_leader = context.user_data.get('pending_leader_info')

        if existing_allocation and not pending_leader:
            # This is a budget modification for existing allocation
            if SKIP_DB:
                api_client = get_api_client()
                result = await api_client.update_allocation(
                    user_id=user_id,
                    allocation_value=allocation_value,
                    allocation_type=allocation_type
                )
                success = result is not None
            else:
                success = await service.update_allocation_settings(
                    follower_user_id=user_id,
                    allocation_value=allocation_value,
                    allocation_type=allocation_type
                )

            if success:
                # Get current balance to show calculated budget
                from core.services.clob.clob_service import get_clob_service
                from core.services.user.user_helper import get_user_data
                clob_service = get_clob_service()
                balance_info = await clob_service.get_balance(user_id)
                if not balance_info:
                    user_data = await get_user_data(user_id)
                    if user_data:
                        polygon_address = user_data.get('polygon_address')
                        if polygon_address:
                            balance_info = await clob_service.get_balance_by_address(polygon_address)

                current_balance = balance_info.get('balance', 0.0) if balance_info else 0.0
                calculated_budget = current_balance * (allocation_value / 100.0)

                await update.message.reply_text(
                    f"✅ *Budget Updated*\n\n"
                    f"New budget allocation: {allocation_value:.1f}% of your balance\n"
                    f"Calculated budget: ${calculated_budget:.2f} USDC\n\n"
                    f"Use /copy_trading to view your settings.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    format_error_message("Failed to update budget"),
                    parse_mode='Markdown'
                )

            # Clear context
            context.user_data.pop('awaiting_budget', None)
            return ConversationHandler.END

        elif pending_leader:
            # This is a new subscription
            if SKIP_DB:
                api_client = get_api_client()
                result = await api_client.subscribe_to_leader(
                    follower_user_id=user_id,
                    leader_address=pending_leader['address'],
                    allocation_type=allocation_type,
                    allocation_value=allocation_value,
                    mode='proportional'
                )
                # Convert API response format to match service format
                if result:
                    result = {'success': True, 'allocation_id': result.get('allocation_id')}
                else:
                    result = {'success': False, 'error': 'Failed to subscribe via API'}
            else:
                result = await service.subscribe_to_leader(
                    follower_user_id=user_id,
                    leader_address=pending_leader['address'],
                    allocation_type=allocation_type,
                    allocation_value=allocation_value,
                    mode='proportional'
                )

            if result.get('success'):
                # Get leader name (via API or DB)
                leader_stats = await get_leader_stats(pending_leader['watched_address_id'], pending_leader['address'])
                leader_name = leader_stats.get('name')

                success_text = format_subscription_success(
                    leader_address=pending_leader['address'],
                    leader_name=leader_name,
                    allocation_value=allocation_value,
                    allocation_type=allocation_type
                )

                await update.message.reply_text(success_text, parse_mode='Markdown')

                # Clear context
                context.user_data.pop('pending_leader_info', None)
                context.user_data.pop('awaiting_budget', None)

                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    format_error_message("Failed to subscribe to leader"),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
        else:
            # Unexpected state
            await update.message.reply_text(
                format_error_message("Unexpected error. Please use /copy_trading to start over."),
                parse_mode='Markdown'
            )
            context.user_data.pop('awaiting_budget', None)
            return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid Input*\n\n"
            "Please enter a valid number (e.g., 50 for $50 USDC)",
            parse_mode='Markdown'
        )
        return ENTERING_BUDGET
    except Exception as e:
        logger.error(f"Error handling budget input: {e}", exc_info=True)
        await update.message.reply_text(format_error_message(str(e)), parse_mode='Markdown')
        return ConversationHandler.END


async def handle_fixed_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle fixed amount input from user"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    logger.info(f"💵 ConversationHandler: handle_fixed_amount_input called for user {user_id}, text: '{text}'")

    try:
        # Parse input as USD amount (remove $ if present)
        try:
            fixed_amount = float(text.replace('$', '').strip())

            # Validate that fixed_amount is reasonable (not accidentally set to allocated_budget)
            if 'allocated_budget' in context.user_data:
                allocated_budget = context.user_data.get('allocated_budget', 0.0)
                if abs(fixed_amount - allocated_budget) < 0.01:  # If they match, it's likely an error
                    logger.warning(f"⚠️ fixed_amount ({fixed_amount}) suspiciously matches allocated_budget ({allocated_budget}) - possible context contamination")
                    # Don't override, but log the issue

        except ValueError:
            await update.message.reply_text(
                "❌ *Invalid Amount*\n\n"
                "Please enter a valid number (e.g., 50 for $50)\n\n"
                "_Example: 50_",
                parse_mode='Markdown'
            )
            return ENTERING_FIXED_AMOUNT

        # Validate minimum and maximum (from budget_calculator config)
        from core.services.copy_trading.budget_calculator import CopyTradingBudgetConfig
        config = CopyTradingBudgetConfig()

        if fixed_amount < config.MIN_FIXED_AMOUNT:
            await update.message.reply_text(
                f"❌ *Minimum Amount*\n\n"
                f"Fixed amount must be at least ${config.MIN_FIXED_AMOUNT:.2f}\n\n"
                f"_Try again or use /copy_trading to go back_",
                parse_mode='Markdown'
            )
            return ENTERING_FIXED_AMOUNT

        if fixed_amount > config.MAX_FIXED_AMOUNT:
            await update.message.reply_text(
                f"❌ *Maximum Amount*\n\n"
                f"Fixed amount cannot exceed ${config.MAX_FIXED_AMOUNT:.2f}\n\n"
                f"_Try again or use /copy_trading to go back_",
                parse_mode='Markdown'
            )
            return ENTERING_FIXED_AMOUNT

        # Check user balance (warning, not blocking)
        from core.services.clob.clob_service import get_clob_service
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

        if fixed_amount > current_balance:
            # Use HTML mode for cleaner formatting
            from html import escape as html_escape

            warning_msg = (
                f"⚠️ <b>Warning</b>\n\n"
                f"Fixed amount <b>{html_escape(f'${fixed_amount:.2f}')}</b> exceeds your current balance <b>{html_escape(f'${current_balance:.2f}')}</b>\n\n"
                f"This may cause trades to fail if you don't have sufficient funds.\n\n"
                f"Continue anyway?"
            )
            # Store the fixed amount and show warning
            context.user_data['pending_fixed_amount'] = fixed_amount
            context.user_data['fixed_amount_warning_shown'] = True

            keyboard = [
                [InlineKeyboardButton("✅ Continue", callback_data="copy_trading:confirm_fixed_amount")],
                [InlineKeyboardButton("❌ Cancel", callback_data="copy_trading:cancel_fixed_amount")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(warning_msg, reply_markup=reply_markup, parse_mode='HTML')
            return ENTERING_FIXED_AMOUNT

        # Amount is valid, proceed with subscription or update
        service = get_copy_trading_service()
        pending_leader = context.user_data.get('pending_leader_info')
        is_settings_update = context.user_data.get('updating_mode_in_settings', False)

        if pending_leader and not is_settings_update:
            # New subscription flow
            selected_percentage = context.user_data.get('selected_budget_percentage')
            allocated_budget = context.user_data.get('allocated_budget', 0.0)

            if not selected_percentage:
                await update.message.reply_text(
                    format_error_message("Missing budget information. Please start over."),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END

            # Subscribe with fixed amount mode
            if SKIP_DB:
                api_client = get_api_client()
                result = await api_client.subscribe_to_leader(
                    follower_user_id=user_id,
                    leader_address=pending_leader['address'],
                    allocation_type='percentage',  # Budget allocation is still percentage-based
                    allocation_value=float(selected_percentage),
                    mode='fixed_amount',  # But copy mode is fixed_amount
                    fixed_amount=fixed_amount
                )
                # Convert API response format to match service format
                if result:
                    result = {'success': True, 'allocation_id': result.get('allocation_id')}
                else:
                    result = {'success': False, 'error': 'Failed to subscribe via API'}
            else:
                result = await service.subscribe_to_leader(
                    follower_user_id=user_id,
                    leader_address=pending_leader['address'],
                    allocation_type='percentage',  # Budget allocation is still percentage-based
                    allocation_value=float(selected_percentage),
                    mode='fixed_amount',  # But copy mode is fixed_amount
                    fixed_amount=fixed_amount
                    )

            # No need for separate update - fixed_amount is now set during subscription
            if result.get('success'):
                # Get leader name (via API or DB)
                leader_stats = await get_leader_stats(pending_leader['watched_address_id'], pending_leader['address'])
                leader_name = leader_stats.get('name')

                # Use HTML mode - much simpler and less error-prone than MarkdownV2
                from html import escape as html_escape

                success_text = (
                    "✅ Successfully Subscribed!\n\n"
                    f"👤 Leader: <code>{html_escape(pending_leader['address'])}</code>\n"
                )
                if leader_name:
                    success_text += f"📛 Name: {html_escape(leader_name)}\n"

                success_text += "\n"
                success_text += f"💰 Budget Allocation: <b>{html_escape(f'{selected_percentage}%')}</b> ({html_escape(f'${allocated_budget:.2f}')} USDC)\n"
                success_text += f"💵 Fixed Amount: <b>{html_escape(f'${fixed_amount:.2f}')}</b>\n"
                success_text += f"📊 Copy Mode: <b>Fixed Amount</b>\n\n"
                success_text += "Your copy trading is now active!\n"
                success_text += "Use /copy_trading to view your dashboard."

                await update.message.reply_text(success_text, parse_mode='HTML')

                # Clear context
                context.user_data.pop('pending_leader_info', None)
                context.user_data.pop('selected_budget_percentage', None)
                context.user_data.pop('allocated_budget', None)
                context.user_data.pop('current_balance', None)
                context.user_data.pop('pending_fixed_amount', None)

                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    format_error_message("Failed to subscribe to leader. Please try again."),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END

        elif is_settings_update:
            # Settings update flow - update mode and fixed_amount in one call
            success = await service.update_allocation_settings(
                follower_user_id=user_id,
                mode='fixed_amount',
                fixed_amount=fixed_amount
            )

            if success:
                from html import escape as html_escape
                fixed_amount_str = f"${fixed_amount:.2f}"
                success_text = (
                    f"✅ <b>Fixed Amount Set!</b>\n\n"
                    f"💵 Fixed Copy Amount: <b>{html_escape(fixed_amount_str)}</b>\n"
                    f"🔄 Each copy trade will use this exact amount\n\n"
                    f"Use /copy_trading to manage your settings"
                )
                await update.message.reply_text(success_text, parse_mode='HTML')

                # Clear context
                context.user_data.pop('updating_mode_in_settings', None)
                context.user_data.pop('pending_fixed_amount', None)

                return ConversationHandler.END
            else:
                await update.message.reply_text(
                    format_error_message("Failed to update mode"),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
        else:
            # Unexpected state
            await update.message.reply_text(
                format_error_message("Unexpected error. Please use /copy_trading to start over."),
                parse_mode='Markdown'
            )
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error handling fixed amount input: {e}", exc_info=True)
        # Use HTML mode for error messages
        from html import escape as html_escape
        escaped_error = html_escape(str(e))
        await update.message.reply_text(f"❌ <b>Error:</b> {escaped_error}", parse_mode='HTML')
        return ConversationHandler.END


async def handle_cancel_fixed_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel from fixed amount input - go back to appropriate screen"""
    query = update.callback_query
    await query.answer()

    is_settings_update = context.user_data.get('updating_mode_in_settings', False)

    # Clear context
    context.user_data.pop('pending_fixed_amount', None)
    context.user_data.pop('fixed_amount_warning_shown', None)
    context.user_data.pop('updating_mode_in_settings', None)

    if is_settings_update:
        # Go back to settings
        from .callbacks import handle_settings
        await handle_settings(update, context)
    else:
        # Go back to cancel search (new subscription flow)
        from .callbacks import handle_cancel_search
        await handle_cancel_search(update, context)

    return ConversationHandler.END


async def handle_confirm_fixed_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle confirmation of fixed amount when it exceeds balance"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    # Get the pending fixed amount from context
    fixed_amount = context.user_data.get('pending_fixed_amount')
    if not fixed_amount:
        await query.edit_message_text(
            format_error_message("Fixed amount not found. Please start over."),
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # Clear the warning flag and proceed with the fixed amount
    context.user_data.pop('fixed_amount_warning_shown', None)

    # Create a fake message update to reuse handle_fixed_amount_input logic
    # We'll directly call the service instead
    service = get_copy_trading_service()
    pending_leader = context.user_data.get('pending_leader_info')
    is_settings_update = context.user_data.get('updating_mode_in_settings', False)

    try:
        if pending_leader and not is_settings_update:
            # New subscription flow
            selected_percentage = context.user_data.get('selected_budget_percentage')
            allocated_budget = context.user_data.get('allocated_budget', 0.0)

            if not selected_percentage:
                await query.edit_message_text(
                    format_error_message("Missing budget information. Please start over."),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END

            # Subscribe with fixed amount mode
            result = await service.subscribe_to_leader(
                follower_user_id=user_id,
                leader_address=pending_leader['address'],
                allocation_type='percentage',
                allocation_value=float(selected_percentage),
                mode='fixed_amount'
            )

            # Update fixed_amount field for copy trading
            if result.get('success'):
                if SKIP_DB:
                    api_client = get_api_client()
                    await api_client.update_allocation(
                        user_id=user_id,
                        fixed_amount=fixed_amount,
                        allocation_type='fixed_amount'
                    )
                else:
                    allocation = await service.get_active_allocation(user_id)
                    if allocation:
                        async with get_db() as db:
                            allocation.fixed_amount = fixed_amount
                            await db.commit()
                            await db.refresh(allocation)

            if result.get('success'):
                # Get leader name (via API or DB)
                leader_stats = await get_leader_stats(pending_leader['watched_address_id'], pending_leader['address'])
                leader_name = leader_stats.get('name')

                # Use HTML mode - much simpler and less error-prone than MarkdownV2
                from html import escape as html_escape

                success_text = (
                    "✅ Successfully Subscribed!\n\n"
                    f"👤 Leader: <code>{html_escape(pending_leader['address'])}</code>\n"
                )
                if leader_name:
                    success_text += f"📛 Name: {html_escape(leader_name)}\n"

                success_text += "\n"
                success_text += f"💰 Budget Allocation: <b>{html_escape(f'{selected_percentage}%')}</b> ({html_escape(f'${allocated_budget:.2f}')} USDC)\n"
                success_text += f"💵 Fixed Amount: <b>{html_escape(f'${fixed_amount:.2f}')}</b>\n"
                success_text += f"📊 Copy Mode: <b>Fixed Amount</b>\n\n"
                success_text += "Your copy trading is now active!\n"
                success_text += "Use /copy_trading to view your dashboard."

                await query.edit_message_text(success_text, parse_mode='HTML')

                # Clear context
                context.user_data.pop('pending_leader_info', None)
                context.user_data.pop('selected_budget_percentage', None)
                context.user_data.pop('allocated_budget', None)
                context.user_data.pop('current_balance', None)
                context.user_data.pop('pending_fixed_amount', None)

                return ConversationHandler.END
            else:
                await query.edit_message_text(
                    format_error_message("Failed to subscribe to leader. Please try again."),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END

        elif is_settings_update:
            # Settings update flow - update mode and fixed_amount in one call
            success = await service.update_allocation_settings(
                follower_user_id=user_id,
                mode='fixed_amount',
                fixed_amount=fixed_amount
            )

            if success:
                from html import escape as html_escape
                fixed_amount_str = f"${fixed_amount:.2f}"
                success_text = (
                    f"✅ <b>Fixed Amount Set!</b>\n\n"
                    f"💵 Fixed Copy Amount: <b>{html_escape(fixed_amount_str)}</b>\n"
                    f"🔄 Each copy trade will use this exact amount\n\n"
                    f"Use /copy_trading to manage your settings"
                )
                await query.edit_message_text(success_text, parse_mode='HTML')

                # Clear context
                context.user_data.pop('updating_mode_in_settings', None)
                context.user_data.pop('pending_fixed_amount', None)

                return ConversationHandler.END
            else:
                await query.edit_message_text(
                    format_error_message("Failed to update mode"),
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
        else:
            await query.edit_message_text(
                format_error_message("Unexpected error. Please use /copy_trading to start over."),
                parse_mode='Markdown'
            )
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error confirming fixed amount: {e}", exc_info=True)
        await query.edit_message_text(format_error_message(str(e)), parse_mode='Markdown')
        return ConversationHandler.END
