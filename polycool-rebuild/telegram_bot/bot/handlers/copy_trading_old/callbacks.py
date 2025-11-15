"""
Copy Trading Callbacks Handler
Handles callbacks routing and message processing for copy trading
"""

from datetime import datetime, timezone
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import CopyTradingAllocation, WatchedAddress, User
from core.services.user.user_service import user_service
from core.services.copy_trading.copy_trading_helper import get_allocation_by_id, update_allocation, get_or_create_watched_address, check_existing_allocation, create_allocation
from infrastructure.logging.logger import get_logger

# Import from other modules in the same package
from .dashboard import _handle_refresh_dashboard
from .leaders import _handle_add_leader, _handle_settings, _handle_leader_address_input
from .allocations import _handle_set_allocation_type, _handle_set_mode, _handle_set_allocation_value, _handle_allocation_value_input

logger = get_logger(__name__)


async def handle_copy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle copy trading callback queries
    Routes: copy_add_leader, copy_settings_{id}, copy_pause_{id}, copy_resume_{id}, copy_stop_{id}
    """
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id

    try:
        await query.answer()

        # Route callbacks
        if callback_data == "copy_dashboard" or callback_data == "copy_refresh":
            await _handle_refresh_dashboard(query, context)
        elif callback_data == "copy_add_leader":
            await _handle_add_leader(query, context)
        elif callback_data.startswith("copy_trading:"):
            # Delegate all copy_trading:* callbacks to the new system
            from telegram_bot.handlers.copy_trading.callbacks import (
                handle_search_leader, handle_settings, handle_history,
                handle_stop_following, handle_confirm_leader, handle_cancel_search,
                handle_dashboard, handle_modify_budget, handle_toggle_mode
            )

            # Convert Update format
            update = Update(update_id=0, callback_query=query)

            # Route based on callback data
            if callback_data == "copy_trading:search_leader":
                await handle_search_leader(update, context)
            elif callback_data == "copy_trading:settings":
                await handle_settings(update, context)
            elif callback_data == "copy_trading:history":
                await handle_history(update, context)
            elif callback_data == "copy_trading:stop_following":
                await handle_stop_following(update, context)
            elif callback_data.startswith("copy_trading:confirm_"):
                await handle_confirm_leader(update, context)
            elif callback_data == "copy_trading:cancel_search":
                await handle_cancel_search(update, context)
            elif callback_data == "copy_trading:dashboard":
                await handle_dashboard(update, context)
            elif callback_data == "copy_trading:modify_budget":
                await handle_modify_budget(update, context)
            elif callback_data == "copy_trading:toggle_mode":
                await handle_toggle_mode(update, context)
            else:
                logger.warning(f"Unknown copy_trading callback: {callback_data}")
                await query.edit_message_text("❌ Unknown action")
            return
        elif callback_data.startswith("copy_settings_"):
            allocation_id = int(callback_data.split("_")[-1])
            await _handle_settings(query, context, allocation_id)
        elif callback_data.startswith("copy_pause_"):
            allocation_id = int(callback_data.split("_")[-1])
            await _handle_pause_resume(query, context, allocation_id, pause=True)
        elif callback_data.startswith("copy_resume_"):
            allocation_id = int(callback_data.split("_")[-1])
            await _handle_pause_resume(query, context, allocation_id, pause=False)
        elif callback_data.startswith("copy_stop_"):
            allocation_id = int(callback_data.split("_")[-1])
            await _handle_stop_following(query, context, allocation_id)
        elif callback_data.startswith("copy_set_allocation_type_"):
            # Parse: "copy_set_allocation_type_{allocation_id}_{type}"
            parts = callback_data.split("_")
            allocation_id = int(parts[4])
            alloc_type = parts[5]  # "percentage" or "fixed"
            await _handle_set_allocation_type(query, context, allocation_id, alloc_type)
        elif callback_data.startswith("copy_set_mode_"):
            # Parse: "copy_set_mode_{allocation_id}_{mode}"
            parts = callback_data.split("_")
            allocation_id = int(parts[3])
            mode = parts[4]  # "proportional" or "fixed_amount"
            await _handle_set_mode(query, context, allocation_id, mode)
        elif callback_data.startswith("copy_set_allocation_value_"):
            # Parse: "copy_set_allocation_value_{allocation_id}"
            allocation_id = int(callback_data.split("_")[-1])
            await _handle_set_allocation_value(query, context, allocation_id)
        elif callback_data.startswith("copy_confirm_stop_"):
            # Parse: "copy_confirm_stop_{allocation_id}"
            allocation_id = int(callback_data.split("_")[-1])
            await _handle_confirm_stop_following(query, context, allocation_id)
        else:
            logger.warning(f"Unknown copy trading callback: {callback_data}")
            await query.edit_message_text("❌ Unknown action")

    except Exception as e:
        logger.error(f"Error handling copy trading callback for user {user_id}: {e}")
        if query.message:
            await query.edit_message_text("❌ An error occurred. Please try again.")


async def _handle_pause_resume(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    allocation_id: int,
    pause: bool
) -> None:
    """Handle pause/resume callback"""
    try:
        # Get allocation
        allocation = await get_allocation_by_id(allocation_id)

        if not allocation:
            await query.edit_message_text("❌ Allocation not found")
            return

        # Verify ownership
        user = await user_service.get_by_id(allocation['user_id'])
        if not user or user.telegram_user_id != query.from_user.id:
            await query.edit_message_text("❌ Unauthorized")
            return

        # Update status
        await update_allocation(allocation_id, is_active=not pause)

        action = "paused" if pause else "resumed"
        await query.answer(f"✅ Copy trading {action}")
        await _handle_settings(query, context, allocation_id)

    except Exception as e:
        logger.error(f"Error pausing/resuming: {e}")
        await query.edit_message_text("❌ Error updating status")


async def _handle_stop_following(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    allocation_id: int
) -> None:
    """Handle stop following callback - delete allocation"""
    try:
        # Get allocation
        allocation = await get_allocation_by_id(allocation_id)

        if not allocation:
            await query.edit_message_text("❌ Allocation not found")
            return

        # Verify ownership
        user = await user_service.get_by_id(allocation['user_id'])
        if not user or user.telegram_user_id != query.from_user.id:
            await query.edit_message_text("❌ Unauthorized")
            return

        # Confirm deletion
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"copy_confirm_stop_{allocation_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"copy_settings_{allocation_id}")
            ]
        ]

        await query.edit_message_text(
            "❌ **Stop Following**\n\n"
            "Are you sure you want to stop copying this trader?\n\n"
            "This will:\n"
            "• Stop copying new trades\n"
            "• Keep your existing positions\n"
            "• Remove this allocation\n\n"
            "This action cannot be undone.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error stopping following: {e}")
        await query.edit_message_text("❌ Error processing request")


async def _handle_confirm_stop_following(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    allocation_id: int
) -> None:
    """Handle confirm stop following callback - delete allocation"""
    try:
        # Get allocation
        allocation = await get_allocation_by_id(allocation_id)

        if not allocation:
            await query.edit_message_text("❌ Allocation not found")
            return

        # Verify ownership
        user = await user_service.get_by_id(allocation['user_id'])
        if not user or user.telegram_user_id != query.from_user.id:
            await query.edit_message_text("❌ Unauthorized")
            return

        # For deletion, we need direct DB access for now since we don't have a delete helper
        # This is a temporary solution until we add delete functionality to the helper
        async with get_db() as db:
            # Get leader info
            result = await db.execute(
                select(WatchedAddress)
                .where(WatchedAddress.id == allocation['leader_address_id'])
            )
            leader = result.scalar_one_or_none()

            leader_name = leader.name if leader else f"Leader #{allocation_id}"

            # Re-fetch allocation in this session to ensure it's attached
            allocation_result = await db.execute(
                select(CopyTradingAllocation)
                .where(CopyTradingAllocation.id == allocation_id)
            )
            allocation_to_delete = allocation_result.scalar_one_or_none()

            if allocation_to_delete:
                await db.delete(allocation_to_delete)
                await db.commit()

        await query.answer("✅ Stopped following")
        await query.edit_message_text(
            f"✅ **Stopped Following**\n\n"
            f"You're no longer copying trades from {leader_name}.\n\n"
            f"Your existing positions are unchanged.",
            parse_mode='Markdown'
        )

        # Refresh dashboard
        await _handle_refresh_dashboard(query, context)

        logger.info(f"✅ User {user.id} stopped following leader {allocation['leader_address_id']}")

    except Exception as e:
        logger.error(f"Error confirming stop following: {e}")
        await query.edit_message_text("❌ Error stopping following")


async def handle_copy_trading_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages for copy trading (leader address, allocation values)
    """
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    try:
        # Check if user is entering custom amount for markets (let markets handler process)
        if context.user_data.get('awaiting_custom_amount'):
            # Let markets handler process this message
            return

        # Check if we're waiting for leader address
        if context.user_data.get('awaiting_leader_address'):
            await _handle_leader_address_input(update, context, text)
            return

        # Check if we're waiting for allocation value
        if context.user_data.get('awaiting_allocation_value'):
            await _handle_allocation_value_input(update, context, text)
            return

        # Check if we're waiting for budget allocation (new copy trading system)
        if context.user_data.get('awaiting_budget'):
            # Delegate to new copy trading system
            from telegram_bot.handlers.copy_trading.main import handle_budget_input
            await handle_budget_input(update, context, text)
            return

        # Not in copy trading mode, let other handlers process
        return

    except Exception as e:
        logger.error(f"Error handling copy trading message for user {user_id}: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")
