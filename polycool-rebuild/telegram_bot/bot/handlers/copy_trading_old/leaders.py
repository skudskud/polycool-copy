"""
Copy Trading Leaders Handler
Handles leader management: add leader, settings, address input
"""
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import CopyTradingAllocation, WatchedAddress, User
from core.services.user.user_helper import get_user_data
from core.services.user.user_service import user_service
from core.services.copy_trading.copy_trading_helper import (
    get_allocation_by_id,
    get_or_create_watched_address,
    check_existing_allocation,
    create_allocation
)
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"


async def _handle_add_leader(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle add leader callback - prompt for address"""
    try:
        # Store state
        context.user_data['awaiting_leader_address'] = True

        await query.edit_message_text(
            "➕ **Add Leader**\n\n"
            "Enter the blockchain address (Polygon) of the trader you want to copy:\n\n"
            "Example: `0x1234567890abcdef1234567890abcdef12345678`\n\n"
            "💡 _You can copy-paste the address from Polymarket or Etherscan_",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling add leader: {e}")
        await query.edit_message_text("❌ Error processing add leader request")


async def _handle_settings(query, context: ContextTypes.DEFAULT_TYPE, allocation_id: int) -> None:
    """Handle settings callback - show settings for an allocation"""
    try:
        # Get allocation
        allocation = await get_allocation_by_id(allocation_id)
        if not allocation:
            await query.edit_message_text("❌ Allocation not found")
            return

        # Verify ownership - for SKIP_DB=true, we need to get user data differently
        if SKIP_DB:
            # Get user data via helper
            user_data = await get_user_data(query.from_user.id)
            if not user_data or user_data.get('id') != allocation.get('user_id'):
                await query.edit_message_text("❌ Unauthorized")
                return
        else:
            # Direct DB access
            user = await user_service.get_by_id(allocation['user_id'])
            if not user or user.telegram_user_id != query.from_user.id:
                await query.edit_message_text("❌ Unauthorized")
                return

        # Get leader info - for SKIP_DB=true, this will be handled by API client
        # For SKIP_DB=false, we need to get the watched address
        leader_address_id = allocation.get('leader_address_id')
        leader_name = f"Leader #{allocation_id}"
        leader_address = "Unknown"

        if not SKIP_DB:
            # Only get leader info when we have direct DB access
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.id == leader_address_id)
                )
                leader = result.scalar_one_or_none()
                if leader:
                    leader_name = leader.name or leader_name
                    leader_address = leader.address

        # Build settings message
        status_emoji = "✅" if allocation.is_active else "⏸️"
        status_text = "Active" if allocation.is_active else "Paused"

        message = f"⚙️ **Settings: {leader_name}**\n\n"
        message += f"📍 Address: `{leader_address[:20]}...`\n"
        message += f"📊 Status: {status_emoji} {status_text}\n\n"

        # Allocation type
        alloc_type_text = "Percentage" if allocation.allocation_type == "percentage" else "Fixed Amount"
        if allocation.allocation_type == "percentage":
            alloc_value_text = f"{allocation.allocation_value:.0f}%"
        else:
            alloc_value_text = f"${allocation.allocation_value:.2f}"

        message += f"💰 **Allocation:** {alloc_type_text} ({alloc_value_text})\n"

        # Mode
        mode_text = "Proportional" if allocation.mode == "proportional" else "Fixed Amount"
        message += f"📊 **Mode:** {mode_text}\n"
        message += f"🔄 **Sell Mode:** Always Proportional\n\n"

        # Stats
        message += f"📈 **Stats:**\n"
        message += f"• Trades Copied: {allocation.total_copied_trades}\n"
        message += f"• Total Invested: ${allocation.total_invested:.2f}\n"
        message += f"• Total P&L: ${allocation.total_pnl:.2f}\n\n"

        message += "Select what to change:"

        # Build keyboard
        keyboard = [
            [
                InlineKeyboardButton(
                    "💰 Change Allocation",
                    callback_data=f"copy_set_allocation_type_{allocation_id}_percentage"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Change Mode",
                    callback_data=f"copy_set_mode_{allocation_id}_proportional"
                )
            ],
            [
                InlineKeyboardButton(
                    "⏸️ Pause" if allocation.is_active else "▶️ Resume",
                    callback_data=f"copy_pause_{allocation_id}" if allocation.is_active else f"copy_resume_{allocation_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Stop Following",
                    callback_data=f"copy_stop_{allocation_id}"
                )
            ],
            [
                InlineKeyboardButton("← Back", callback_data="copy_dashboard")
            ]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling settings: {e}")
        await query.edit_message_text("❌ Error loading settings")


async def _handle_leader_address_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    address: str
) -> None:
    """Handle leader address input from user"""
    try:
        user_id = update.effective_user.id

        # Clear the flag
        context.user_data.pop('awaiting_leader_address', None)

        # Validate address format (Polygon addresses start with 0x and are 42 chars)
        if not address.startswith('0x') or len(address) != 42:
            await update.message.reply_text(
                "❌ **Invalid Address Format**\n\n"
                "Please enter a valid Polygon address:\n"
                "• Must start with `0x`\n"
                "• Must be 42 characters long\n\n"
                "Example: `0x1234567890abcdef1234567890abcdef12345678`",
                parse_mode='Markdown'
            )
            return

        # Get user data (via API or DB)
        user_data = await get_user_data(user_id)
        if not user_data:
            await update.message.reply_text("❌ User not found")
            return

        # Get internal user ID for DB operations
        internal_user_id = user_data.get('id')
        if not internal_user_id:
            await update.message.reply_text("❌ User ID not found")
            return

        # Get or create watched address
        watched_address = await get_or_create_watched_address(
            address=address.lower(),
            blockchain='polygon',
            address_type='copy_leader',
            name=f"Leader {address[:10]}..."
        )

        if not watched_address:
            await update.message.reply_text("❌ Error creating watched address")
            return

        # Check if user already follows this leader
        existing = await check_existing_allocation(
            user_id=internal_user_id,
            leader_address_id=watched_address['id']
        )

        if existing:
            await update.message.reply_text(
                f"⚠️ **Already Following**\n\n"
                f"You're already copying trades from this address.\n\n"
                f"Use /copy_trading to manage your allocations.",
                parse_mode='Markdown'
            )
            return

        # Create default allocation (50% proportional)
        allocation = await create_allocation(
            user_id=internal_user_id,
            leader_address_id=watched_address['id'],
            allocation_type='percentage',
            allocation_value=50.0,  # Default 50%
            mode='proportional',
            sell_mode='proportional',
            is_active=True
        )

        if not allocation:
            await update.message.reply_text("❌ Error creating allocation")
            return

        # Success message
        keyboard = [
            [
                InlineKeyboardButton("⚙️ Configure Settings", callback_data=f"copy_settings_{allocation['id']}"),
                InlineKeyboardButton("📊 View Dashboard", callback_data="copy_dashboard")
            ]
        ]

        await update.message.reply_text(
            f"✅ **Leader Added!**\n\n"
            f"📍 Address: `{address[:20]}...`\n\n"
            f"**Default Settings:**\n"
            f"• Allocation: 50% of wallet\n"
            f"• Mode: Proportional\n"
            f"• Status: Active\n\n"
            f"💡 _Configure settings to customize your copy trading._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

        logger.info(f"✅ User {user_id} added leader {address}")

    except Exception as e:
        logger.error(f"Error handling leader address input: {e}")
        await update.message.reply_text("❌ Error processing address. Please try again.")
