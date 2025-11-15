"""
Copy Trading Allocations Handler
Handles allocation type, mode, and value settings
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
from core.services.copy_trading.copy_trading_helper import get_allocation_by_id, update_allocation
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


async def _handle_set_allocation_type(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    allocation_id: int,
    alloc_type: str
) -> None:
    """Handle set allocation type callback"""
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

        # Show selection
        message = "💰 **Set Allocation Type**\n\n"
        message += "Choose how to allocate funds:\n\n"
        message += "**Percentage:** Allocate X% of your wallet\n"
        message += "Example: 50% of $1000 = $500\n\n"
        message += "**Fixed Amount:** Always use a fixed amount\n"
        message += "Example: Always trade $50\n\n"

        keyboard = [
            [
                InlineKeyboardButton(
                    "📊 Percentage",
                    callback_data=f"copy_set_allocation_type_{allocation_id}_percentage"
                )
            ],
            [
                InlineKeyboardButton(
                    "💵 Fixed Amount",
                    callback_data=f"copy_set_allocation_type_{allocation_id}_fixed_amount"
                )
            ],
            [
                InlineKeyboardButton("← Back", callback_data=f"copy_settings_{allocation_id}")
            ]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

        # If type selected, update and prompt for value
        if alloc_type in ["percentage", "fixed_amount"]:
            await update_allocation(allocation_id, allocation_type=alloc_type)

            # Prompt for value
            context.user_data['awaiting_allocation_value'] = True
            context.user_data['allocation_id'] = allocation_id
            context.user_data['allocation_type'] = alloc_type

            if alloc_type == "percentage":
                await query.edit_message_text(
                    "💰 **Set Allocation Percentage**\n\n"
                    "Enter the percentage (5-100):\n\n"
                    "Example: `50` for 50%",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    "💰 **Set Fixed Amount**\n\n"
                    "Enter the fixed amount in USD:\n\n"
                    "Example: `50.00` for $50",
                    parse_mode='Markdown'
                )

    except Exception as e:
        logger.error(f"Error setting allocation type: {e}")
        await query.edit_message_text("❌ Error setting allocation type")


async def _handle_set_mode(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    allocation_id: int,
    mode: str
) -> None:
    """Handle set mode callback"""
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

        # Show selection
        message = "📊 **Set Copy Mode**\n\n"
        message += "**Proportional:** Copy % of leader's trade\n"
        message += "Example: Leader trades 10% → You trade 10%\n\n"
        message += "**Fixed Amount:** Always trade fixed amount\n"
        message += "Example: Always trade $50\n\n"
        message += "**Note:** SELL orders are always proportional\n"

        keyboard = [
            [
                InlineKeyboardButton(
                    "📊 Proportional",
                    callback_data=f"copy_set_mode_{allocation_id}_proportional"
                )
            ],
            [
                InlineKeyboardButton(
                    "💵 Fixed Amount",
                    callback_data=f"copy_set_mode_{allocation_id}_fixed_amount"
                )
            ],
            [
                InlineKeyboardButton("← Back", callback_data=f"copy_settings_{allocation_id}")
            ]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

        # If mode selected, update
        if mode in ["proportional", "fixed_amount"]:
            await update_allocation(allocation_id, mode=mode)

            await query.answer(f"✅ Mode set to {mode}")
            await _handle_settings(query, context, allocation_id)

    except Exception as e:
        logger.error(f"Error setting mode: {e}")
        await query.edit_message_text("❌ Error setting mode")


async def _handle_set_allocation_value(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    allocation_id: int
) -> None:
    """Handle set allocation value callback - prompt for value"""
    try:
        # Store state
        context.user_data['awaiting_allocation_value'] = True
        context.user_data['allocation_id'] = allocation_id

        # Get allocation to know type
        allocation = await get_allocation_by_id(allocation_id)

        if not allocation:
            await query.edit_message_text("❌ Allocation not found")
            return

        if allocation['allocation_type'] == "percentage":
            await query.edit_message_text(
                "💰 **Set Allocation Percentage**\n\n"
                "Enter the percentage (5-100):\n\n"
                "Example: `50` for 50%",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "💰 **Set Fixed Amount**\n\n"
                "Enter the fixed amount in USD:\n\n"
                "Example: `50.00` for $50",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error setting allocation value: {e}")
        await query.edit_message_text("❌ Error setting allocation value")


async def _handle_allocation_value_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    value_text: str
) -> None:
    """Handle allocation value input from user"""
    try:
        user_id = update.effective_user.id

        # Get allocation ID and type from context
        allocation_id = context.user_data.get('allocation_id')
        allocation_type = context.user_data.get('allocation_type')

        if not allocation_id:
            await update.message.reply_text("❌ Session expired. Please try again.")
            context.user_data.pop('awaiting_allocation_value', None)
            return

        # Clear the flag
        context.user_data.pop('awaiting_allocation_value', None)
        context.user_data.pop('allocation_id', None)
        context.user_data.pop('allocation_type', None)

        # Parse value
        try:
            if allocation_type == "percentage":
                value = float(value_text)
                if value < 5 or value > 100:
                    await update.message.reply_text(
                        "❌ **Invalid Percentage**\n\n"
                        "Please enter a percentage between 5 and 100.\n\n"
                        "Example: `50` for 50%",
                        parse_mode='Markdown'
                    )
                    return
            else:
                value = float(value_text)
                if value <= 0:
                    await update.message.reply_text(
                        "❌ **Invalid Amount**\n\n"
                        "Please enter a positive amount.\n\n"
                        "Example: `50.00` for $50",
                        parse_mode='Markdown'
                    )
                    return
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid Format**\n\n"
                "Please enter a valid number.\n\n"
                "Example: `50` or `50.00`",
                parse_mode='Markdown'
            )
            return

        # Get allocation
        allocation = await get_allocation_by_id(allocation_id)

        if not allocation:
            await update.message.reply_text("❌ Allocation not found")
            return

        # Verify ownership
        user = await user_service.get_by_id(allocation['user_id'])
        if not user or user.telegram_user_id != user_id:
            await update.message.reply_text("❌ Unauthorized")
            return

        # Update allocation
        await update_allocation(allocation_id, allocation_value=value)

        # Success message
        if allocation_type == "percentage":
            value_text_formatted = f"{value:.0f}%"
        else:
            value_text_formatted = f"${value:.2f}"

        keyboard = [
            [
                InlineKeyboardButton("← Back to Settings", callback_data=f"copy_settings_{allocation_id}")
            ]
        ]

        await update.message.reply_text(
            f"✅ **Allocation Updated!**\n\n"
            f"New value: **{value_text_formatted}**\n\n"
            f"Your copy trading settings have been updated.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling allocation value input: {e}")
        await update.message.reply_text("❌ Error updating allocation")
