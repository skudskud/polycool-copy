"""
Wallet command handler
Displays user wallets (Polygon + Solana) and balances
Delegates to wallet.view module for main functionality
"""
import os
from telegram import Update
from telegram.ext import ContextTypes

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram_bot.handlers.wallet.view import handle_wallet_command
from core.services.user.user_helper import get_user_data
from core.services.user.user_service import user_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"


async def handle_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet command - Delegate to wallet view module"""
    await handle_wallet_command(update, context)


async def handle_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callbacks from wallet handler buttons
    Routes: bridge_sol, wallet_details, main_menu, show_polygon_key, show_solana_key, hide_polygon_key, hide_solana_key
    """
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id

    try:
        # Route to appropriate handler
        if callback_data == "bridge_sol":
            await _handle_bridge_sol(query, context)
        elif callback_data == "wallet_details":
            await _handle_wallet_details(query, context)
        elif callback_data == "main_menu":
            await _handle_main_menu(query, context)
        elif callback_data == "show_polygon_key":
            logger.info(f"🔄 [WALLET_HANDLER] Routing show_polygon_key callback for user {user_id}")
            from telegram_bot.handlers.wallet.view import handle_show_polygon_key_callback
            await handle_show_polygon_key_callback(update, context)
            return  # Don't answer callback again
        elif callback_data == "show_solana_key":
            from telegram_bot.handlers.wallet.view import handle_show_solana_key_callback
            await handle_show_solana_key_callback(update, context)
            return  # Don't answer callback again
        elif callback_data == "hide_polygon_key":
            from telegram_bot.handlers.wallet.view import handle_hide_polygon_key_callback
            await handle_hide_polygon_key_callback(update, context)
            return  # Don't answer callback again
        elif callback_data == "hide_solana_key":
            from telegram_bot.handlers.wallet.view import handle_hide_solana_key_callback
            await handle_hide_solana_key_callback(update, context)
            return  # Don't answer callback again
        else:
            logger.warning(f"Unknown wallet callback: {callback_data}")
            await query.answer()
            await query.edit_message_text("❌ Unknown action")

    except Exception as e:
        logger.error(f"Error handling wallet callback for user {user_id}: {e}")
        try:
            await query.answer()
            if query.message:
                await query.edit_message_text("❌ An error occurred. Please try again.")
        except:
            pass


async def _handle_bridge_sol(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bridge SOL callback - initiate bridge"""
    logger.info(f"🔄 BRIDGE_SOL callback received for user {query.from_user.id}")
    try:
        telegram_user_id = query.from_user.id
        logger.info(f"🔍 Getting user data for user_id: {telegram_user_id}")

        user_data = await get_user_data(telegram_user_id)
        logger.info(f"👤 User found: {user_data is not None}")

        if not user_data:
            logger.error("❌ User not found")
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        solana_address = user_data.get('solana_address')
        stage = user_data.get('stage', 'onboarding')

        logger.info(f"📊 User stage: {stage}, SOL address: {solana_address is not None}")

        if not solana_address:
            logger.error("❌ Solana address not found")
            await query.edit_message_text("❌ Solana wallet not found. Please use /start")
            return

        # Get bridge service to check balance
        from core.services.bridge import get_bridge_service
        bridge_service = get_bridge_service()

        logger.info("💰 Checking SOL balance for bridge calculation...")
        sol_balance = await bridge_service.get_sol_balance(solana_address)
        logger.info(f"💰 SOL balance: {sol_balance:.6f} SOL")

        if sol_balance < 0.1:
            logger.error("❌ Insufficient SOL balance")
            await query.edit_message_text(
                f"❌ **Insufficient SOL Balance**\n\n"
                f"📊 **Current Balance:** {sol_balance:.6f} SOL\n"
                f"⚠️ **Minimum Required:** 0.1 SOL\n\n"
                f"📍 **Your SOL Address:**\n`{solana_address}`\n\n"
                f"Please fund your wallet first.",
                parse_mode='Markdown'
            )
            return

        # Calculate bridge amount (use 80% of balance)
        bridge_amount = sol_balance * 0.8
        logger.info(f"💸 Calculated bridge amount: {bridge_amount:.6f} SOL")

        # Show confirmation with direct confirm callback
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = [
            [InlineKeyboardButton(f"✅ Bridge {bridge_amount:.4f} SOL", callback_data=f"confirm_bridge_{bridge_amount:.6f}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_bridge")]
        ]

        await query.edit_message_text(
            f"🌉 **Bridge Confirmation**\n\n"
            f"**Balance:** {sol_balance:.6f} SOL\n"
            f"**Bridge Amount:** {bridge_amount:.6f} SOL\n"
            f"**Reserve:** {(sol_balance - bridge_amount):.6f} SOL (for fees)\n\n"
            f"⚠️ **This will bridge SOL → USDC → POL**\n"
            f"⏱️ **Duration:** 2-5 minutes\n\n"
            f"Ready to bridge?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"❌ Error in bridge_sol callback: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        await query.edit_message_text("❌ Error initiating bridge. Please try again.")


async def _handle_wallet_details(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle wallet details callback - show detailed wallet info"""
    try:
        telegram_user_id = query.from_user.id
        user_data = await get_user_data(telegram_user_id)

        if not user_data:
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        polygon_address = user_data.get('polygon_address')
        solana_address = user_data.get('solana_address')
        stage = user_data.get('stage', 'onboarding')

        # Get balance info (if available)
        balance_info = None
        try:
            from core.services.clob.clob_service import get_clob_service
            clob_service = get_clob_service()
            balance_info = await clob_service.get_balance(telegram_user_id)
        except Exception as e:
            logger.debug(f"Could not fetch balance: {e}")

        # Build detailed message
        message = f"""
💼 **WALLET DETAILS**

🔷 **POLYGON WALLET**
📍 Address: `{polygon_address or 'Not set'}`
{f'🔗 [View on Polygonscan](https://polygonscan.com/address/{polygon_address})' if polygon_address else ''}

🔶 **SOLANA WALLET**
📍 Address: `{solana_address or 'Not set'}`
{f'🔗 [View on Solscan](https://solscan.io/account/{solana_address})' if solana_address else ''}

📊 **Status:** {stage.upper()}
        """.strip()

        if balance_info:
            balance = balance_info.get('balance', 0)
            message += f"\n\n💰 **Balance:** ${balance:.2f} USDC"

        keyboard = [
            [InlineKeyboardButton("🌉 Bridge SOL → USDC", callback_data="bridge_sol")],
            [InlineKeyboardButton("← Back", callback_data="main_menu")]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown',
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Error in wallet_details callback: {e}")
        await query.edit_message_text("❌ Error loading wallet details. Please try again.")


async def _handle_main_menu(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle main menu callback - return to start menu"""
    try:
        telegram_user_id = query.from_user.id
        user_data = await get_user_data(telegram_user_id)

        if not user_data:
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        # Import start handler to reuse logic
        from telegram_bot.bot.handlers import start_handler

        # Create a fake update for start handler
        class FakeUpdate:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.message = query.message

        fake_update = FakeUpdate(query)
        await start_handler.handle_start(fake_update, context)

    except Exception as e:
        logger.error(f"Error in main_menu callback: {e}")
        await query.edit_message_text("❌ Error loading main menu. Please try again.")
