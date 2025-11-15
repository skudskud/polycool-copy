"""
Copy Trading Dashboard Handler
Handles copy trading dashboard display and refresh functionality
"""
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import CopyTradingAllocation, WatchedAddress, User
from core.services.user.user_helper import get_user_data
from core.services.user.user_service import user_service
from core.services.clob.clob_service import get_clob_service
from core.services.copy_trading.copy_trading_helper import get_user_allocations
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"


async def handle_copy_trading(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /copy_trading command - Show copy trading dashboard
    """
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    try:
        logger.info(f"👥 /copy_trading command - User {user_id}")

        # Get user data (via API or DB)
        user_data = await get_user_data(user_id)
        if not user_data:
            await update.message.reply_text(
                "❌ You are not registered. Use /start to begin."
            )
            return

        stage = user_data.get('stage', 'onboarding')
        internal_user_id = user_data.get('id')

        if not internal_user_id:
            await update.message.reply_text(
                "❌ User ID not found. Please use /start to create your account."
            )
            return

        # Check if user is ready
        if stage != "ready":
            await update.message.reply_text(
                "⏳ **Copy Trading**\n\n"
                "You need to complete onboarding first.\n\n"
                "Use /start to set up your account.",
                parse_mode='Markdown'
            )
            return

        # Show loading
        loading_msg = await update.message.reply_text("🔍 Loading copy trading dashboard...")

        # Get user's copy trading allocations
        allocations = await get_user_allocations(internal_user_id)

        # Get balance
        clob_service = get_clob_service()
        balance_info = await clob_service.get_balance(user_id)
        balance = balance_info.get('balance', 0.0) if balance_info else 0.0

        # Build dashboard
        message_text, keyboard = _build_copy_trading_dashboard(
            allocations=allocations,
            balance=balance,
            user_id=internal_user_id
        )

        await loading_msg.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

        logger.info(f"✅ Copy trading dashboard displayed for user {user_id}")

    except Exception as e:
        logger.error(f"Error in copy_trading handler for user {user_id}: {e}")
        if 'loading_msg' in locals():
            await loading_msg.edit_text("❌ An error occurred. Please try again.")
        else:
            await update.message.reply_text("❌ An error occurred. Please try again.")




def _build_copy_trading_dashboard(
    allocations: List[Dict[str, Any]],
    balance: float,
    user_id: int
) -> tuple[str, List[List]]:
    """
    Build copy trading dashboard message and keyboard

    Args:
        allocations: List of CopyTradingAllocation objects
        balance: User balance
        user_id: User ID

    Returns:
        (message_text, keyboard) tuple
    """
    message = "👥 **COPY TRADING**\n\n"
    message += f"💼 **Balance:** ${balance:.2f}\n\n"

    if not allocations:
        message += "📭 **No Active Copy Trading**\n\n"
        message += "✨ You're not copying any traders yet.\n\n"
        message += "**How it works:**\n"
        message += "• Follow expert traders (leaders)\n"
        message += "• Automatically copy their trades\n"
        message += "• Set allocation (% of wallet or fixed amount)\n"
        message += "• Choose mode: Proportional or Fixed\n\n"
        message += "💡 _Add a leader to get started!_"

        keyboard = [
            [InlineKeyboardButton("➕ Add Leader", callback_data="copy_add_leader")],
            [InlineKeyboardButton("← Back", callback_data="main_menu")]
        ]
        return message, keyboard

    # Show active allocations
    message += f"📊 **Active Copy Trading:** {len([a for a in allocations if a.get('is_active', False)])}\n"
    message += f"⏸️ **Paused:** {len([a for a in allocations if not a.get('is_active', False)])}\n\n"

    keyboard = []

    # List allocations
    for allocation in allocations[:10]:  # Limit to 10
        # Get leader address info
        leader_name = f"Leader #{allocation.get('id')}"
        status_emoji = "✅" if allocation.get('is_active', False) else "⏸️"

        # Format allocation
        if allocation.get('allocation_type') == "percentage":
            alloc_text = f"{allocation.get('allocation_value', 0):.0f}%"
        else:
            alloc_text = f"${allocation.get('allocation_value', 0):.2f}"

        mode_text = "Proportional" if allocation.get('mode') == "proportional" else "Fixed"

        message += f"{status_emoji} **{leader_name}**\n"
        message += f"   💰 Allocation: {alloc_text}\n"
        message += f"   📊 Mode: {mode_text}\n"
        message += f"   📈 Trades Copied: {allocation.get('total_copied_trades', 0)}\n"
        message += f"   💵 Total Invested: ${allocation.get('total_invested', 0):.2f}\n\n"

        # Add button for this allocation
        button_text = f"{status_emoji} {leader_name[:20]}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"copy_settings_{allocation.get('id')}"
            )
        ])

    # Add action buttons
    keyboard.append([
        InlineKeyboardButton("➕ Add Leader", callback_data="copy_add_leader")
    ])
    keyboard.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="copy_refresh")
    ])
    keyboard.append([
        InlineKeyboardButton("← Back", callback_data="main_menu")
    ])

    return message, keyboard


async def _handle_refresh_dashboard(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle refresh dashboard callback"""
    try:
        telegram_user_id = query.from_user.id

        # Get user data (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data:
            await query.edit_message_text("❌ User not found")
            return

        internal_user_id = user_data.get('id')
        if not internal_user_id:
            await query.edit_message_text("❌ User ID not found")
            return

        await query.answer("🔄 Refreshing...")

        # Get allocations
        allocations = await get_user_allocations(internal_user_id)

        # Get balance
        clob_service = get_clob_service()
        balance_info = await clob_service.get_balance(telegram_user_id)
        balance = balance_info.get('balance', 0.0) if balance_info else 0.0

        # Build dashboard
        message_text, keyboard = _build_copy_trading_dashboard(
            allocations=allocations,
            balance=balance,
            user_id=internal_user_id
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error refreshing dashboard: {e}")
        await query.edit_message_text("❌ Error refreshing dashboard")
