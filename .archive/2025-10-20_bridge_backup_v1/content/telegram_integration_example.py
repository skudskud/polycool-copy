#!/usr/bin/env python3
"""
Example integration of Solana Bridge into telegram_bot.py

Add these methods to the TelegramTradingBot class and register the handlers
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from solana.bridge_orchestrator import bridge_orchestrator
from wallet_manager import wallet_manager

# Conversation states
AWAITING_SOL_AMOUNT, CONFIRMING_BRIDGE = range(2)


# Add these methods to TelegramTradingBot class:

async def bridge_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bridge command - Start SOL → USDC.e/POL bridge process
    """
    user_id = update.effective_user.id

    # Check if user has Polygon wallet
    polygon_wallet = wallet_manager.get_user_wallet(user_id)
    if not polygon_wallet:
        await update.message.reply_text(
            "❌ **No wallet found!**\n\n"
            "Please use /start to create your Polygon wallet first.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    welcome_msg = """
🌉 **SOLANA → POLYGON BRIDGE**

Bridge your SOL to USDC.e + POL on Polygon for Polymarket trading!

**What you'll receive:**
• USDC.e (for trading)
• POL (gas refuel ~3 POL)
• Auto-swap excess POL → USDC.e

**How much SOL do you want to bridge?**

💡 **Examples:**
• `5` - Bridge 5 SOL
• `10` - Bridge 10 SOL
• `0.5` - Bridge 0.5 SOL

Type the amount or /cancel to abort.
    """

    await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    return AWAITING_SOL_AMOUNT


async def handle_sol_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle SOL amount input and fetch quote
    """
    user_id = update.effective_user.id

    try:
        # Parse SOL amount
        sol_amount = float(update.message.text.strip())

        if sol_amount <= 0:
            await update.message.reply_text(
                "❌ Amount must be greater than 0.\n\nPlease enter a valid amount:",
                parse_mode='Markdown'
            )
            return AWAITING_SOL_AMOUNT

        # Get user's Polygon address
        polygon_wallet = wallet_manager.get_user_wallet(user_id)
        polygon_address = polygon_wallet['address']

        # Show loading message
        loading_msg = await update.message.reply_text(
            "⏳ **Getting bridge quote...**\n\nThis may take a few seconds.",
            parse_mode='Markdown'
        )

        # Get bridge quote
        quote = await bridge_orchestrator.get_bridge_quote(
            user_id=user_id,
            sol_amount=sol_amount,
            polygon_address=polygon_address
        )

        if not quote:
            await loading_msg.edit_text(
                "❌ **Failed to get bridge quote**\n\n"
                "Please try again later or contact support.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END

        # Store quote in context
        context.user_data['bridge_quote'] = quote

        # Display quote to user
        quote_text = quote['display']['formatted']

        keyboard = [
            [InlineKeyboardButton("✅ Confirm Bridge", callback_data=f"confirm_bridge_{user_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_bridge")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await loading_msg.edit_text(
            quote_text + "\n\n**Ready to proceed?**",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

        return CONFIRMING_BRIDGE

    except ValueError:
        await update.message.reply_text(
            "❌ Invalid amount format.\n\nPlease enter a number (e.g., 5 or 10.5):",
            parse_mode='Markdown'
        )
        return AWAITING_SOL_AMOUNT
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error:** {str(e)}\n\nPlease try again or contact support.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END


async def confirm_bridge_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle bridge confirmation button click
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Get quote from context
    quote = context.user_data.get('bridge_quote')
    if not quote:
        await query.edit_message_text(
            "❌ **Quote expired**\n\nPlease start over with /bridge",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # Get user's Polygon wallet
    polygon_wallet = wallet_manager.get_user_wallet(user_id)
    polygon_address = polygon_wallet['address']
    polygon_private_key = polygon_wallet['private_key']

    # Start bridge execution
    await query.edit_message_text(
        "🚀 **Bridge initiated!**\n\n"
        "⏳ This process will take 2-5 minutes.\n"
        "I'll keep you updated...",
        parse_mode='Markdown'
    )

    # Define status callback for updates
    async def status_update(message: str):
        try:
            await query.message.edit_text(
                f"🌉 **Bridge Status**\n\n{message}",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"Failed to send status update: {e}")

    # Execute complete bridge workflow
    result = await bridge_orchestrator.complete_bridge_workflow(
        user_id=user_id,
        sol_amount=quote['sol_amount'],
        polygon_address=polygon_address,
        polygon_private_key=polygon_private_key,
        status_callback=status_update
    )

    if result and result.get('success'):
        # Success message
        bridge_data = result['bridge']
        swap_data = result.get('quickswap')

        success_msg = f"""
✅ **BRIDGE COMPLETED!**

🎉 Your wallet is now ready for Polymarket trading!

📊 **Summary:**
• Bridged: {quote['sol_amount']} SOL
• Received: {bridge_data['usdc_received']:.2f} USDC.e
• Gas refuel: {bridge_data['pol_received']:.4f} POL
"""

        if swap_data:
            success_msg += f"• Swapped: {swap_data['swapped_pol']:.4f} POL → USDC.e\n"

        success_msg += f"""
🔗 **Transactions:**
• Solana: `{bridge_data['solana_tx']}`
"""

        if swap_data:
            success_msg += f"• QuickSwap: `{swap_data['tx_hash']}`\n"

        success_msg += "\n**Ready to trade!** Use /markets to start trading."

        await query.message.edit_text(success_msg, parse_mode='Markdown')
    else:
        # Error message
        error = result.get('error', 'Unknown error') if result else 'Unknown error'
        await query.message.edit_text(
            f"❌ **Bridge failed**\n\n"
            f"Error: {error}\n\n"
            f"Please try again or contact support.",
            parse_mode='Markdown'
        )

    # Clean up context
    context.user_data.pop('bridge_quote', None)
    return ConversationHandler.END


async def cancel_bridge_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle bridge cancellation
    """
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "❌ **Bridge cancelled**\n\nUse /bridge to start again.",
        parse_mode='Markdown'
    )

    # Clean up context
    context.user_data.pop('bridge_quote', None)
    return ConversationHandler.END


async def cancel_bridge_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cancel command during bridge conversation
    """
    await update.message.reply_text(
        "❌ **Bridge cancelled**\n\nUse /bridge to start again.",
        parse_mode='Markdown'
    )

    # Clean up context
    context.user_data.pop('bridge_quote', None)
    return ConversationHandler.END


# Add to setup_handlers() method:
"""
# Bridge conversation handler
bridge_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("bridge", self.bridge_command)],
    states={
        AWAITING_SOL_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_sol_amount),
        ],
        CONFIRMING_BRIDGE: [
            CallbackQueryHandler(self.confirm_bridge_callback, pattern="^confirm_bridge_"),
            CallbackQueryHandler(self.cancel_bridge_callback, pattern="^cancel_bridge$"),
        ],
    },
    fallbacks=[CommandHandler("cancel", self.cancel_bridge_command)],
)

self.app.add_handler(bridge_conv_handler)
"""


# Update setup_bot_commands() to include:
"""
BotCommand("bridge", "🌉 Bridge SOL to Polygon"),
"""
