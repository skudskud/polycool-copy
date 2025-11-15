"""
Positions command handler
Routes /positions commands and callbacks to specialized modules
"""
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.user.user_service import user_service
from core.services.position.position_service import position_service
from core.services.clob.clob_service import get_clob_service
from core.services.market_service import get_market_service
from telegram_bot.bot.handlers.positions.view_builder import build_positions_view, build_position_detail_view
from core.services.balance.balance_service import balance_service
from telegram_bot.bot.handlers.positions.refresh_handler import handle_refresh_positions
from telegram_bot.bot.handlers.positions.sell_handler import (
    handle_sell_position, handle_sell_amount, handle_sell_custom, handle_confirm_sell
)
from telegram_bot.bot.handlers.positions.tpsl_handler import (
    handle_tpsl_setup, handle_tpsl_set_price, handle_tpsl_clear, handle_tpsl_save
)
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


async def handle_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /positions command - Show user positions
    """
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    try:
        logger.info(f"📈 /positions command - User {user_id}")

        # Get user
        user = await user_service.get_by_telegram_id(user_id)
        if not user:
            await update.message.reply_text(
                "❌ Vous n'êtes pas enregistré. Utilisez /start pour commencer."
            )
            return

        # Show loading message
        loading_msg = await update.message.reply_text("🔍 Loading your positions...")

        # Sync positions from blockchain
        synced = await position_service.sync_positions_from_blockchain(
            user_id=user.id,
            wallet_address=user.polygon_address
        )
        logger.info(f"Synced {synced} positions from blockchain")

        # Update prices for all positions
        updated = await position_service.update_all_positions_prices(user_id=user.id)
        logger.info(f"Updated prices for {updated} positions")

        # Get active positions
        positions = await position_service.get_active_positions(user_id=user.id)

        # Get markets for positions
        markets_map = {}
        cache_manager = None
        if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
            cache_manager = context.bot.application.bot_data.get('cache_manager')

        market_service = get_market_service(cache_manager=cache_manager)

        for position in positions:
            if position.market_id not in markets_map:
                market = await market_service.get_market_by_id(position.market_id)
                if market:
                    markets_map[position.market_id] = market

        # Calculate total P&L
        total_pnl = sum(p.pnl_amount for p in positions)
        total_invested = sum(p.entry_price * p.amount for p in positions)
        total_pnl_percentage = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

        # Get USDC.e balance
        usdc_balance = None
        if user.polygon_address:
            try:
                usdc_balance = await balance_service.get_usdc_balance(user.polygon_address)
            except Exception as e:
                logger.warning(f"Could not fetch USDC.e balance: {e}")

        # Legacy balance for backward compatibility
        clob_service = get_clob_service()
        balance_info = await clob_service.get_balance(user_id)
        balance = balance_info.get('balance') if balance_info else None

        # Build view
        message_text, keyboard = build_positions_view(
            positions=positions,
            markets_map=markets_map,
            total_pnl=total_pnl,
            total_pnl_percentage=total_pnl_percentage,
            balance=balance,
            usdc_balance=usdc_balance,
            include_refresh=True
        )

        await loading_msg.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

        logger.info(f"✅ Positions displayed for user {user_id}")

    except Exception as e:
        logger.error(f"Error in positions handler for user {user_id}: {e}")
        if 'loading_msg' in locals():
            await loading_msg.edit_text("❌ An error occurred. Please try again.")
        else:
            await update.message.reply_text("❌ An error occurred. Please try again.")


async def handle_position_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle position callback queries - Route to specialized handlers
    """
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id

    try:
        await query.answer()

        # Route callbacks to specialized handlers
        if callback_data == "positions_hub" or callback_data == "refresh_positions":
            await handle_refresh_positions(query, context)
        elif callback_data.startswith("position_"):
            await _handle_position_detail(query, context, callback_data)
        elif callback_data.startswith("sell_position_"):
            await handle_sell_position(query, context, callback_data)
        elif callback_data.startswith("sell_amount_"):
            await handle_sell_amount(query, context, callback_data)
        elif callback_data.startswith("sell_custom_"):
            await handle_sell_custom(query, context, callback_data)
        elif callback_data.startswith("confirm_sell_"):
            await handle_confirm_sell(query, context, callback_data)
        elif callback_data.startswith("tpsl_setup_"):
            await handle_tpsl_setup(query, context, callback_data)
        elif callback_data.startswith("tpsl_set_tp_") or callback_data.startswith("tpsl_set_sl_"):
            await handle_tpsl_set_price(query, context, callback_data)
        elif callback_data.startswith("tpsl_clear_tp_") or callback_data.startswith("tpsl_clear_sl_"):
            await handle_tpsl_clear(query, context, callback_data)
        elif callback_data.startswith("tpsl_save_"):
            await handle_tpsl_save(query, context, callback_data)
        else:
            logger.warning(f"Unknown position callback: {callback_data}")
            await query.edit_message_text("❌ Unknown action")

    except Exception as e:
        logger.error(f"Error handling position callback for user {user_id}: {e}")
        if query.message:
            await query.edit_message_text("❌ An error occurred. Please try again.")


async def _handle_position_detail(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle position detail view callback"""
    try:
        # Parse: "position_{position_id}"
        position_id = int(callback_data.split("_")[-1])

        # Get position
        position = await position_service.get_position(position_id)
        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Get market
        cache_manager = None
        if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
            cache_manager = context.bot.application.bot_data.get('cache_manager')

        market_service = get_market_service(cache_manager=cache_manager)
        market = await market_service.get_market_by_id(position.market_id)

        # Build detail view
        message_text, keyboard = build_position_detail_view(position, market)

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error showing position detail: {e}")
        await query.edit_message_text("❌ Error loading position details")
