#!/usr/bin/env python3
"""
Withdrawal Handlers
Handles the conversational UI for withdrawing SOL and USDC
Uses ConversationHandler for multi-step flow
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters
)

from telegram_bot.services.withdrawal_service import get_withdrawal_service
from core.services import balance_checker
from telegram_bot.utils.address_validator import (
    validate_solana_address,
    validate_ethereum_address,
    detect_network_mismatch,
    format_address_display,
    check_same_address
)
from core.services import user_service
from solana_bridge.solana_transaction import SolanaTransactionBuilder
from .telegram_utils import safe_answer_callback_query

logger = logging.getLogger(__name__)

# Conversation states
WITHDRAW_AMOUNT, WITHDRAW_ADDRESS, WITHDRAW_CONFIRM = range(3)


# ========================================================================
# Entry Points (from buttons)
# ========================================================================

async def withdraw_sol_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Start SOL withdrawal conversation
    Entry point from "withdraw_sol" callback button
    """
    query = update.callback_query
    await safe_answer_callback_query(query)

    user_id = query.from_user.id

    try:
        # Check rate limit
        withdrawal_service = get_withdrawal_service()
        can_withdraw, limit_msg = withdrawal_service.check_rate_limit(user_id)

        if not can_withdraw:
            await query.edit_message_text(limit_msg)
            return ConversationHandler.END

        # Get user's SOL balance
        solana_address = user_service.get_solana_address(user_id)
        if not solana_address:
            await query.edit_message_text("❌ Solana wallet not found. Use /start to set up.")
            return ConversationHandler.END

        # Get balance
        solana_tx_builder = SolanaTransactionBuilder()
        sol_balance = await solana_tx_builder.get_sol_balance(solana_address)

        if sol_balance <= 0.001:  # Need some SOL for gas
            await query.edit_message_text(
                f"❌ Insufficient Balance\n\n"
                f"Your SOL balance: {sol_balance:.4f} SOL\n\n"
                f"You need at least 0.01 SOL to withdraw.\n\n"
                f"💡 Fund your wallet via /bridge"
            )
            return ConversationHandler.END

        # Store context
        context.user_data['withdrawal_token'] = 'SOL'
        context.user_data['withdrawal_network'] = 'SOL'
        context.user_data['user_balance'] = sol_balance
        context.user_data['user_address'] = solana_address

        # Show amount prompt
        message = (
            f"💸 WITHDRAW SOL\n\n"
            f"Balance: {sol_balance:.4f} SOL (~${sol_balance * 195:.2f})\n\n"
            f"How much to withdraw?\n\n"
            f"Examples: `0.1` or `0.5` or `all`\n"
            f"Minimum: 0.01 SOL (~$2)\n\n"
            f"Type /cancel anytime to stop"
        )

        keyboard = [[InlineKeyboardButton("❌ Cancel Withdrawal", callback_data="cancel_withdrawal")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, reply_markup=reply_markup)
        return WITHDRAW_AMOUNT

    except Exception as e:
        logger.error(f"❌ Error starting SOL withdrawal: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def withdraw_usdc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Start USDC withdrawal conversation
    Entry point from "withdraw_usdc" callback button
    """
    query = update.callback_query
    await safe_answer_callback_query(query)

    user_id = query.from_user.id

    try:
        # Check rate limit
        withdrawal_service = get_withdrawal_service()
        can_withdraw, limit_msg = withdrawal_service.check_rate_limit(user_id)

        if not can_withdraw:
            await query.edit_message_text(limit_msg)
            return ConversationHandler.END

        # Get user's Polygon address
        polygon_address = user_service.get_polygon_address(user_id)
        if not polygon_address:
            await query.edit_message_text("❌ Polygon wallet not found. Use /start to set up.")
            return ConversationHandler.END

        # Get USDC.e balance
        usdc_balance, _ = balance_checker.check_usdc_balance(polygon_address)

        if usdc_balance < 5.0:
            await query.edit_message_text(
                f"❌ Insufficient Balance\n\n"
                f"Your USDC.e balance: ${usdc_balance:.2f}\n\n"
                f"Minimum withdrawal: $5.00\n\n"
                f"💡 Fund your wallet via /bridge"
            )
            return ConversationHandler.END

        # Get POL balance (for gas)
        pol_balance, _ = balance_checker.check_pol_balance(polygon_address)

        if pol_balance < 0.002:
            await query.edit_message_text(
                f"⚠️ Insufficient Gas\n\n"
                f"Your POL balance: {pol_balance:.4f} POL\n"
                f"Need: 0.002 POL (~$0.003) for gas\n\n"
                f"💡 Get POL via /bridge to pay for gas fees."
            )
            return ConversationHandler.END

        # Store context
        context.user_data['withdrawal_token'] = 'USDC.e'
        context.user_data['withdrawal_network'] = 'POLYGON'
        context.user_data['user_balance'] = usdc_balance
        context.user_data['user_address'] = polygon_address
        context.user_data['pol_balance'] = pol_balance

        # Show amount prompt
        message = (
            f"💸 WITHDRAW USDC\n\n"
            f"Balance: ${usdc_balance:.2f} USDC\n"
            f"Gas: {pol_balance:.4f} POL\n\n"
            f"How much to withdraw?\n\n"
            f"Examples: `50` or `100` or `all`\n"
            f"Minimum: $5.00\n\n"
            f"Type /cancel anytime to stop"
        )

        keyboard = [[InlineKeyboardButton("❌ Cancel Withdrawal", callback_data="cancel_withdrawal")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, reply_markup=reply_markup)
        return WITHDRAW_AMOUNT

    except Exception as e:
        logger.error(f"❌ Error starting USDC withdrawal: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


# ========================================================================
# State 1: Handle Amount Input
# ========================================================================

async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's amount input"""
    user_id = update.effective_user.id
    user_input = update.message.text.strip()

    try:
        token = context.user_data.get('withdrawal_token')
        balance = context.user_data.get('user_balance')

        # Handle "all" keyword
        if user_input.lower() == 'all':
            # Reserve a bit for gas
            if token == 'SOL':
                amount = balance - 0.000005  # Reserve for gas
                if amount < 0.01:
                    await update.message.reply_text(
                        f"❌ Insufficient Balance\n\n"
                        f"After reserving gas, you have {amount:.4f} SOL available.\n"
                        f"Minimum withdrawal: 0.01 SOL"
                    )
                    return WITHDRAW_AMOUNT
            else:  # USDC
                amount = balance
        else:
            # Parse amount (strip common symbols like $, commas)
            try:
                # Remove $, commas, and whitespace
                cleaned_input = user_input.replace('$', '').replace(',', '').strip()
                amount = float(cleaned_input)
            except ValueError:
                await update.message.reply_text(
                    f"❌ Invalid Amount\n\n"
                    f"Please enter a valid number (e.g., `5`, `10.5`, `50`)\n"
                    f"Or type `all` to withdraw everything\n\n"
                    f"Type /cancel to cancel",
                    parse_mode='Markdown'
                )
                return WITHDRAW_AMOUNT

        # Validate amount
        if amount <= 0:
            await update.message.reply_text(
                f"❌ Invalid Amount\n\n"
                f"Amount must be positive.\n\n"
                f"Type /cancel to cancel"
            )
            return WITHDRAW_AMOUNT

        # Check minimum
        if token == 'SOL' and amount < 0.01:
            await update.message.reply_text(
                f"❌ Below Minimum\n\n"
                f"Minimum withdrawal: 0.01 SOL (~$2)\n"
                f"You entered: {amount:.4f} SOL\n\n"
                f"Type /cancel to cancel"
            )
            return WITHDRAW_AMOUNT

        if token == 'USDC.e' and amount < 5.0:
            await update.message.reply_text(
                f"❌ Below Minimum\n\n"
                f"Minimum withdrawal: $5.00\n"
                f"You entered: ${amount:.2f}\n\n"
                f"Type /cancel to cancel"
            )
            return WITHDRAW_AMOUNT

        # Check sufficient balance
        if amount > balance:
            # Format balance for display
            balance_fmt = f"{balance:.4f}" if token == 'SOL' else f"{balance:.2f}"
            amount_fmt = f"{amount:.4f}" if token == 'SOL' else f"{amount:.2f}"
            shortfall_fmt = f"{(amount - balance):.4f}" if token == 'SOL' else f"{(amount - balance):.2f}"

            keyboard = [
                [InlineKeyboardButton(f"Withdraw {balance_fmt} (Max)", callback_data="withdraw_max")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdrawal")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"❌ Insufficient Balance\n\n"
                f"You requested: {amount_fmt} {token}\n"
                f"Your balance: {balance_fmt} {token}\n"
                f"Shortfall: {shortfall_fmt} {token}\n\n"
                f"💡 What would you like to do?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return WITHDRAW_AMOUNT

        # Store amount
        context.user_data['withdrawal_amount'] = amount

        # Move to address input
        # Format amount for display
        amount_fmt = f"{amount:.4f}" if token == 'SOL' else f"{amount:.2f}"
        usd_value = amount * 195 if token == 'SOL' else amount

        message = (
            f"✅ Amount: {amount_fmt} {token} "
            f"(~${usd_value:.2f})\n\n"
        )

        if token == 'SOL':
            message += (
                f"💡 Enter Solana Wallet Address\n\n"
                f"🚨 CRITICAL: Check network!\n"
                f"• Must be SOLANA address (32-44 characters)\n"
                f"• Wrong network = Funds lost forever\n\n"
                f"Example: `7xKXtg2...JosgAsU`\n\n"
                f"Type /cancel to stop"
            )
        else:
            message += (
                f"💡 Enter Polygon/Ethereum Address\n\n"
                f"🚨 CRITICAL: Check network!\n"
                f"• Must be POLYGON/ETH address (starts with 0x)\n"
                f"• Wrong network = Funds lost forever\n\n"
                f"Example: `0x742d35...6c7Dd5`\n\n"
                f"Type /cancel to stop"
            )

        keyboard = [[InlineKeyboardButton("❌ Cancel Withdrawal", callback_data="cancel_withdrawal")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message, reply_markup=reply_markup)
        return WITHDRAW_ADDRESS

    except Exception as e:
        logger.error(f"❌ Error handling amount: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


# ========================================================================
# State 2: Handle Address Input
# ========================================================================

async def handle_address_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's address input"""
    user_id = update.effective_user.id
    address = update.message.text.strip()

    try:
        token = context.user_data.get('withdrawal_token')
        amount = context.user_data.get('withdrawal_amount')
        user_address = context.user_data.get('user_address')

        # Validate address format
        if token == 'SOL':
            is_valid, error = validate_solana_address(address)
        else:
            is_valid, error = validate_ethereum_address(address)

        if not is_valid:
            await update.message.reply_text(
                f"❌ Invalid Address\n\n{error}\n\n"
                f"Please try again or /cancel to cancel"
            )
            return WITHDRAW_ADDRESS

        # Check network mismatch
        is_mismatch, warning = detect_network_mismatch(token, address)
        if is_mismatch:
            await update.message.reply_text(
                f"{warning}\n\n"
                f"Please enter the correct address or /cancel to cancel"
            )
            return WITHDRAW_ADDRESS

        # Check if same address
        is_same, warning = check_same_address(address, user_address)
        if is_same:
            await update.message.reply_text(
                f"{warning}\n\n"
                f"Please enter a different address or /cancel to cancel"
            )
            return WITHDRAW_ADDRESS

        # Store address
        context.user_data['withdrawal_destination'] = address

        # Move to confirmation
        await show_confirmation(update, context)
        return WITHDRAW_CONFIRM

    except Exception as e:
        logger.error(f"❌ Error handling address: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


# ========================================================================
# State 3: Show Confirmation
# ========================================================================

async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show withdrawal confirmation screen"""
    try:
        token = context.user_data.get('withdrawal_token')
        network = context.user_data.get('withdrawal_network')
        amount = context.user_data.get('withdrawal_amount')
        destination = context.user_data.get('withdrawal_destination')
        balance = context.user_data.get('user_balance')

        # Estimate gas
        withdrawal_service = get_withdrawal_service()
        if network == 'SOL':
            gas_cost = withdrawal_service.estimate_gas_sol()
            gas_display = f"{gas_cost:.6f} SOL (~$0.001)"
            total_cost = amount + gas_cost
            new_balance = balance - total_cost
            network_icon = "⚡"
            time_estimate = "5-15 seconds"
            explorer = "Solscan"
        else:
            gas_cost_pol, gas_cost_usd = withdrawal_service.estimate_gas_polygon()
            gas_display = f"{gas_cost_pol:.4f} POL (~${gas_cost_usd:.3f})"
            total_cost = amount
            new_balance = balance - amount
            network_icon = "🟣"
            time_estimate = "10-30 seconds"
            explorer = "PolygonScan"

        # Format address for display
        destination_short = format_address_display(destination, 6)

        # Calculate percentage remaining
        percent_remaining = (new_balance / balance * 100) if balance > 0 else 0

        # Format amounts for display
        amount_fmt = f"{amount:.4f}" if token == 'SOL' else f"{amount:.2f}"
        total_cost_fmt = f"{total_cost:.4f}" if token == 'SOL' else f"{total_cost:.2f}"
        new_balance_fmt = f"{new_balance:.4f}" if token == 'SOL' else f"{new_balance:.2f}"
        balance_fmt = f"{balance:.4f}" if token == 'SOL' else f"{balance:.2f}"

        # Build message
        message = (
            f"💸 WITHDRAWAL CONFIRMATION\n\n"
            f"Network: {network} {network_icon}\n"
            f"Token: {token}\n"
            f"Amount: {amount_fmt} {token}\n"
            f"Gas Fee: {gas_display}\n"
            f"Total Cost: ~{total_cost_fmt} {token}\n\n"
            f"From: `{format_address_display(context.user_data.get('user_address'), 6)}`\n"
            f"To: `{destination_short}`\n\n"
            f"Your Balance After:\n"
            f"├─ {token}: {new_balance_fmt} (from {balance_fmt})\n"
            f"└─ You keep: {percent_remaining:.1f}%\n\n"
            f"⏱️ Est. Time: {time_estimate}\n"
            f"🔗 Network: {network} Mainnet\n\n"
            f"⚠️ WARNING: This transaction cannot be reversed!\n"
            f"Once confirmed, funds will be transferred immediately.\n\n"
            f"Please verify the destination address carefully!"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Confirm & Send", callback_data="confirm_withdrawal")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdrawal")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ Error showing confirmation: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


# ========================================================================
# Confirmation Buttons
# ========================================================================

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation button click"""
    query = update.callback_query
    await safe_answer_callback_query(query)

    user_id = query.from_user.id

    # Get withdrawal details from context
    token = context.user_data.get('withdrawal_token')
    network = context.user_data.get('withdrawal_network')
    amount = context.user_data.get('withdrawal_amount')
    destination = context.user_data.get('withdrawal_destination')

    # CRITICAL FIX: Send a NEW message instead of editing the query
    # This prevents "Timed out" errors when blockchain confirmation takes >30s
    processing_msg = await query.message.reply_text(
        "⏳ Processing Withdrawal...\n\n"
        "🔐 Authorizing transaction...\n"
        "📡 Broadcasting to network...\n"
        "⏱️ Waiting for blockchain confirmation...\n\n"
        "This may take 1-2 minutes depending on network conditions.\n"
        "Please be patient! ⏳",
        parse_mode='Markdown'
    )

    try:
        # Execute withdrawal
        withdrawal_service = get_withdrawal_service()

        if network == 'SOL':
            estimated_usd = amount * 195  # Rough SOL price
            success, message, tx_hash = await withdrawal_service.withdraw_sol(
                user_id, amount, destination, estimated_usd
            )
            explorer_url = f"https://solscan.io/tx/{tx_hash}" if tx_hash else None
            explorer_name = "Solscan"
        else:
            success, message, tx_hash = withdrawal_service.withdraw_usdc(
                user_id, amount, destination, amount
            )
            explorer_url = f"https://polygonscan.com/tx/{tx_hash}" if tx_hash else None
            explorer_name = "PolygonScan"

        if success and tx_hash:
            # Format amount for display
            amount_fmt = f"{amount:.4f}" if token == 'SOL' else f"{amount:.2f}"

            # Success message
            result_message = (
                f"✅ WITHDRAWAL SUCCESSFUL!\n\n"
                f"💸 Sent: {amount_fmt} {token}\n"
                f"📍 To: `{format_address_display(destination, 6)}`\n"
                f"🔗 Transaction: [View on {explorer_name}]({explorer_url})\n\n"
                f"{message}\n\n"
                f"🎉 Your funds have been transferred!\n"
                f"Check your wallet to confirm receipt."
            )

            keyboard = [
                [InlineKeyboardButton(f"🔗 View on {explorer_name}", url=explorer_url)],
                [InlineKeyboardButton("🏠 Back to Wallet", callback_data="show_wallet")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Update the processing message with success
            await processing_msg.edit_text(result_message, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            # Failure message
            await processing_msg.edit_text(
                f"❌ Withdrawal Failed\n\n"
                f"{message}\n\n"
                f"Your funds are SAFE!\n"
                f"• No transaction was completed\n"
                f"• Your balance is unchanged\n\n"
                f"💡 Please try again or contact support if problem persists.",
                parse_mode='Markdown'
            )

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"❌ Error executing withdrawal: {e}")
        try:
            await processing_msg.edit_text(
                f"❌ Withdrawal Error\n\n"
                f"Error: {str(e)}\n\n"
                f"Your funds are SAFE!\n"
                f"Please check your wallet to confirm if the transaction was completed.\n\n"
                f"💡 If funds were deducted but you see this error, check the blockchain explorer.\n"
                f"Contact support if you need assistance.",
                parse_mode='Markdown'
            )
        except:
            # If editing fails, send a new message
            await query.message.reply_text(
                f"❌ Withdrawal Error\n\n"
                f"Error: {str(e)}\n\n"
                f"Your funds may be SAFE!\n"
                f"Please check your wallet and blockchain explorer to verify.\n\n"
                f"Contact support if you need assistance.",
                parse_mode='Markdown'
            )
        return ConversationHandler.END


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancellation"""
    if update.callback_query:
        query = update.callback_query
        await safe_answer_callback_query(query)
        await query.edit_message_text(
            "❌ Withdrawal Cancelled\n\n"
            "No funds were transferred.\n"
            "Use /wallet to try again."
        )
    else:
        await update.message.reply_text(
            "❌ Withdrawal Cancelled\n\n"
            "No funds were transferred.\n"
            "Use /wallet to try again."
        )

    return ConversationHandler.END


async def handle_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle conversation timeout"""
    await update.message.reply_text(
        "⏱️ Withdrawal Timeout\n\n"
        "Conversation expired after 5 minutes of inactivity.\n"
        "No funds were transferred.\n\n"
        "Use /wallet to start a new withdrawal."
    )
    return ConversationHandler.END


# ========================================================================
# ConversationHandler Setup
# ========================================================================

withdrawal_conversation_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(withdraw_sol_start, pattern="^withdraw_sol$"),
        CallbackQueryHandler(withdraw_usdc_start, pattern="^withdraw_usdc$"),
    ],
    states={
        WITHDRAW_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount_input),
            CallbackQueryHandler(handle_cancel, pattern="^cancel_withdrawal$"),
        ],
        WITHDRAW_ADDRESS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address_input),
            CallbackQueryHandler(handle_cancel, pattern="^cancel_withdrawal$"),
        ],
        WITHDRAW_CONFIRM: [
            CallbackQueryHandler(handle_confirmation, pattern="^confirm_withdrawal$"),
            CallbackQueryHandler(handle_cancel, pattern="^cancel_withdrawal$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", handle_cancel),
        CallbackQueryHandler(handle_cancel, pattern="^cancel_withdrawal$"),
    ],
    conversation_timeout=300,  # 5 minutes
    per_message=False,
    per_chat=True,
    per_user=True,
    name="withdrawal_conversation",
)
