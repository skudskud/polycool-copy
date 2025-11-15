"""
Copy Trading Main Handler
Entry point for /copy_trading command
Shows dashboard, PnL, positions, and allows searching for leaders by Polygon address
"""

import logging
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters

from core.services.copy_trading import get_copy_trading_service
from .formatters import (
    format_copy_trading_main,
    format_leader_stats,
    format_success_message,
    format_error_message,
)

logger = logging.getLogger(__name__)

# Conversation states
VIEWING_DASHBOARD = 0
ASKING_POLYGON_ADDRESS = 1
CONFIRMING_LEADER = 2
ENTERING_FIXED_AMOUNT = 3


async def cmd_copy_trading(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /copy_trading command handler
    Shows copy trading dashboard with PnL and positions
    """
    user_id = update.effective_user.id
    service = get_copy_trading_service()

    try:
        # Get current leader (refresh from DB, no cache)
        leader_id = service.get_leader_for_follower(user_id)
        logger.debug(f"📊 Copy trading dashboard: user {user_id} following leader {leader_id}")

        # Get leader address if following someone
        leader_address = None
        if leader_id:
            try:
                from database import SessionLocal
                db = SessionLocal()
                from database import User, ExternalLeader

                # Try to find in users table first
                leader_user = db.query(User).filter(User.telegram_user_id == leader_id).first()
                if leader_user and leader_user.polygon_address:
                    leader_address = leader_user.polygon_address
                else:
                    # Fallback: Try external_leaders table (for non-Telegram leaders)
                    external_leader = db.query(ExternalLeader).filter(ExternalLeader.virtual_id == leader_id).first()
                    if external_leader and external_leader.polygon_address:
                        leader_address = external_leader.polygon_address

                db.close()
            except Exception as e:
                logger.warning(f"Could not fetch leader address for {leader_id}: {e}")

        # Get stats if copy trading
        pnl_data = None
        budget_info = None
        if leader_id:
            pnl_data = service.get_follower_pnl_and_trades(user_id)
            budget = service._get_repo().get_budget(user_id)
            if budget:
                budget_info = {
                    'allocated_budget': float(budget.allocated_budget),
                    'allocation_percentage': float(budget.allocation_percentage),
                    'budget_remaining': float(budget.budget_remaining),
                }

        # Format main view
        main_text = format_copy_trading_main(leader_id, leader_address=leader_address, stats=pnl_data, budget_info=budget_info)

        # Create inline keyboard
        keyboard = [
            [
                InlineKeyboardButton("🔄 Search Leader", callback_data="switch_leader"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            ],
            [InlineKeyboardButton("📋 History", callback_data="history")],
        ]

        if leader_id:
            keyboard.append([InlineKeyboardButton("🛑 Stop Following", callback_data="stop_following")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(main_text, reply_markup=reply_markup)

        # Store context
        context.user_data['current_leader'] = leader_id

        return VIEWING_DASHBOARD

    except Exception as e:
        logger.error(f"Error in copy trading command: {e}")
        await update.message.reply_text(format_error_message(str(e)))
        return VIEWING_DASHBOARD


async def handle_leader_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process entered Polygon address and validate leader"""
    from telegram_bot.handlers.callbacks.copy_trading_callbacks import (
        handle_fixed_amount_input,
        handle_budget_percentage_input
    )

    # ✅ CRITICAL FIX: Check if we're actually in copy trading flow
    # If user didn't explicitly click "Search Leader", exit conversation
    if not context.user_data.get('expecting_polygon_address') and \
       not context.user_data.get('awaiting_fixed_amount') and \
       not context.user_data.get('awaiting_budget_percentage'):
        # User is typing in another flow (like /markets custom amount)
        # Exit this conversation and let other handlers process it
        logger.debug(f"[COPY_TRADING] User input not expected, exiting conversation")
        return ConversationHandler.END

    # Check if we're waiting for other input types first
    if context.user_data.get('awaiting_fixed_amount'):
        # Delegate to fixed amount handler
        return await handle_fixed_amount_input(update, context)

    if context.user_data.get('awaiting_budget_percentage'):
        # Delegate to budget percentage handler
        return await handle_budget_percentage_input(update, context)

    # Otherwise, treat as polygon address
    user_id = update.effective_user.id
    polygon_address = update.message.text.strip()
    service = get_copy_trading_service()

    try:
        # Validate address format (basic check)
        if not polygon_address.startswith('0x') or len(polygon_address) < 10:
            await update.message.reply_text(
                "❌ *Invalid Address Format*\n\n"
                "Please enter a valid Polygon address starting with 0x",
                )

            return ASKING_POLYGON_ADDRESS

        # Resolve address to leader ID
        try:
            leader_id = service.resolve_leader_by_address(polygon_address)
        except Exception as e:
            await update.message.reply_text(
                f"❌ *Leader Not Found*\n\n"
                f"No active trader found with address:\n`{polygon_address}`\n\n"
                f"Try another address or use /copy_trading to search again.",
                )

            return ASKING_POLYGON_ADDRESS

        # Get leader stats for confirmation
        leader_stats = service.get_leader_stats_for_display(leader_id)
        confirm_text = format_leader_stats(leader_stats)

        keyboard = [
            [InlineKeyboardButton("✅ Follow This Leader", callback_data=f"confirm_leader_{leader_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_leader_search")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(confirm_text, reply_markup=reply_markup)

        # Store pending leader in context
        context.user_data['pending_leader_id'] = leader_id
        context.user_data['pending_leader_address'] = polygon_address

        # Clear the flag
        context.user_data.pop('expecting_polygon_address', None)

        return CONFIRMING_LEADER

    except Exception as e:
        logger.error(f"Error processing leader address: {e}")
        await update.message.reply_text(format_error_message(str(e)))
        return ASKING_POLYGON_ADDRESS


def setup_copy_trading_handlers(application):
    """Register all copy trading handlers with the application"""

    # Import the fixed amount input handler
    from telegram_bot.handlers.callbacks.copy_trading_callbacks import handle_fixed_amount_input

    # Main copy trading conversation
    copy_trading_conv = ConversationHandler(
        entry_points=[CommandHandler("copy_trading", cmd_copy_trading)],
        states={
            VIEWING_DASHBOARD: [
                # User is viewing dashboard, waiting for button click via callbacks
                # ⚠️ CRITICAL: Only handle text if we're EXPLICITLY expecting it
                # Don't intercept text from other flows (like /markets custom amount)
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leader_address),
            ],
            ASKING_POLYGON_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leader_address),
            ],
            CONFIRMING_LEADER: [
                # Inline callbacks handle confirmation (via registry)
            ],
            ENTERING_FIXED_AMOUNT: [
                # User is entering fixed amount for copy trading
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fixed_amount_input),
            ],
        },
        fallbacks=[
            CommandHandler("copy_trading", cmd_copy_trading),
        ],
        # ✅ CRITICAL: Isolate conversation per user
        per_chat=True,
        per_user=True,
        # ✅ Allow other handlers to process messages if this conversation isn't active
        allow_reentry=True,
    )

    application.add_handler(copy_trading_conv)

    logger.info("✅ Copy trading handlers registered (using centralized callback registry)")
