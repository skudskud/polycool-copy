"""
Copy Trading Main Handler
Entry point for /copy_trading command
Shows dashboard, PnL, positions, and allows searching for leaders by Polygon address
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from core.services.copy_trading import get_copy_trading_service
from .constants import (
    VIEWING_DASHBOARD,
    ASKING_POLYGON_ADDRESS,
    CONFIRMING_LEADER,
    SELECTING_BUDGET_PERCENTAGE,
    SELECTING_COPY_MODE,
    ENTERING_BUDGET,
    ENTERING_FIXED_AMOUNT,
)
from .subscription_flow import (
    handle_leader_address,
    handle_search_leader_callback,
    handle_confirm_leader_callback,
    handle_cancel_search,
)
from .budget_flow import (
    handle_budget_input,
    handle_fixed_amount_input,
    handle_cancel_fixed_amount,
    handle_confirm_fixed_amount,
)
from .callbacks import (
    handle_budget_percentage_selection,
    handle_copy_mode_selection,
    handle_modify_budget,
    handle_settings_mode_selection,
)
from .formatters import format_copy_trading_main, format_error_message

logger = logging.getLogger(__name__)


async def cmd_copy_trading(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /copy_trading command handler
    Shows copy trading dashboard with PnL and positions
    """
    user_id = update.effective_user.id
    service = get_copy_trading_service()

    try:
        # Get current leader info
        leader_info = await service.get_leader_info_for_follower(user_id)

        # Get stats if copy trading
        stats = None
        budget_info = None
        if leader_info:
            stats = await service.get_follower_stats(user_id)
            budget_info = await service.get_budget_info(user_id)

        # Format main view
        main_text = format_copy_trading_main(
            leader_info=leader_info,
            stats=stats,
            budget_info=budget_info
        )

        # Create inline keyboard
        keyboard = [
            [
                InlineKeyboardButton("🔄 Search Leader", callback_data="copy_trading:search_leader"),
                InlineKeyboardButton("⚙️ Settings", callback_data="copy_trading:settings")
            ],
            [InlineKeyboardButton("📋 History", callback_data="copy_trading:history")],
        ]

        if leader_info:
            keyboard.append([InlineKeyboardButton("🛑 Stop Following", callback_data="copy_trading:stop_following")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(main_text, reply_markup=reply_markup, parse_mode='Markdown')

        # Store context
        context.user_data['current_leader'] = leader_info

        return VIEWING_DASHBOARD

    except Exception as e:
        logger.error(f"Error in copy trading command: {e}", exc_info=True)
        await update.message.reply_text(format_error_message(str(e)), parse_mode='Markdown')
        return VIEWING_DASHBOARD


async def handle_modify_budget_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle modify budget callback and transition to budget entry state"""
    logger.info(f"💰 ConversationHandler: Handling modify_budget callback")

    # Call the existing handler which will update context.user_data
    result = await handle_modify_budget(update, context)

    logger.info(f"✅ ConversationHandler: Transitioning to ENTERING_BUDGET state")

    # Return the state to transition to
    return ENTERING_BUDGET


async def handle_settings_mode_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle settings mode selection callback and transition to fixed amount entry state if needed"""
    logger.info(f"🔄 ConversationHandler: Handling settings_mode_selection callback")

    # Call the existing handler which will update context.user_data and return state
    result = await handle_settings_mode_selection(update, context)

    # If handler returned a state, use it; otherwise check if we need to enter fixed amount
    if result is not None:
        logger.info(f"✅ ConversationHandler: Transitioning to state {result}")
        return result

    # If no state returned, check if we're entering fixed amount mode
    if context.user_data.get('updating_mode_in_settings'):
        logger.info(f"✅ ConversationHandler: Transitioning to ENTERING_FIXED_AMOUNT state")
        return ENTERING_FIXED_AMOUNT

    # Otherwise stay in dashboard
    return VIEWING_DASHBOARD


def setup_copy_trading_handlers(application):
    """Register all copy trading handlers with the application"""

    # Main copy trading conversation
    copy_trading_conv = ConversationHandler(
        entry_points=[CommandHandler("copy_trading", cmd_copy_trading)],
        states={
            VIEWING_DASHBOARD: [
                # Handle search leader callback
                CallbackQueryHandler(handle_search_leader_callback, pattern=r"^copy_trading:search_leader$"),
                # Handle modify budget callback
                CallbackQueryHandler(handle_modify_budget_callback, pattern=r"^copy_trading:modify_budget$"),
                # Handle settings mode selection callback (for fixed amount entry)
                CallbackQueryHandler(handle_settings_mode_selection_callback, pattern=r"^copy_trading:settings_mode_(fixed|proportional)$"),
                # User is viewing dashboard, waiting for button click via callbacks
                # Only handle text if we're EXPLICITLY expecting it
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leader_address),
            ],
            ASKING_POLYGON_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_leader_address),
            ],
            CONFIRMING_LEADER: [
                # Handle leader confirmation callback
                CallbackQueryHandler(handle_confirm_leader_callback, pattern=r"^copy_trading:confirm_\d+$"),
                CallbackQueryHandler(handle_cancel_search, pattern=r"^copy_trading:cancel_search$"),
            ],
            SELECTING_BUDGET_PERCENTAGE: [
                CallbackQueryHandler(handle_budget_percentage_selection, pattern=r"^copy_trading:budget_(25|50|75|100)$"),
                CallbackQueryHandler(handle_cancel_search, pattern=r"^copy_trading:cancel_search$"),
            ],
            SELECTING_COPY_MODE: [
                CallbackQueryHandler(handle_copy_mode_selection, pattern=r"^copy_trading:mode_(fixed|proportional)$"),
                CallbackQueryHandler(handle_cancel_search, pattern=r"^copy_trading:cancel_search$"),
            ],
            ENTERING_BUDGET: [
                # User is entering budget allocation
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_budget_input),
            ],
            ENTERING_FIXED_AMOUNT: [
                # User is entering fixed amount value
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fixed_amount_input),
                # Handle cancel and confirm callbacks
                CallbackQueryHandler(handle_cancel_fixed_amount, pattern=r"^copy_trading:cancel_search$"),
                CallbackQueryHandler(handle_cancel_fixed_amount, pattern=r"^copy_trading:cancel_fixed_amount$"),
                CallbackQueryHandler(handle_confirm_fixed_amount, pattern=r"^copy_trading:confirm_fixed_amount$"),
            ],
        },
        fallbacks=[
            CommandHandler("copy_trading", cmd_copy_trading),
        ],
        # Isolate conversation per user
        per_chat=True,
        per_user=True,
        # Allow other handlers to process messages if this conversation isn't active
        allow_reentry=True,
    )

    application.add_handler(copy_trading_conv)

    logger.info("✅ Copy trading handlers registered")
