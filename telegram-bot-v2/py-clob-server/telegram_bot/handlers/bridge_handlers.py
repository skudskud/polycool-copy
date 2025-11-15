#!/usr/bin/env python3
"""
Bridge Handlers - Refactored
Handles SOL → USDC.e + POL bridging workflow
Integrated into the new modular architecture
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler
from functools import partial

from core.services import user_service
from solana_bridge.bridge_v3 import bridge_v3
from solana_bridge.solana_transaction import SolanaTransactionBuilder

logger = logging.getLogger(__name__)

# Initialize Solana transaction builder for balance checks
solana_tx_builder = SolanaTransactionBuilder()


async def bridge_command(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """
    Start bridge workflow
    Command: /bridge
    """
    user_id = update.effective_user.id

    try:
        # Vérifier wallet Polygon
        polygon_wallet = user_service.get_user_wallet(user_id)
        if not polygon_wallet:
            await update.message.reply_text(
                "❌ No Polygon wallet found!\n\nUse /start to create your wallet first.",
                parse_mode='Markdown'
            )
            return

        # Vérifier/Créer wallet Solana
        username = update.effective_user.username or "Unknown"
        # Get or generate Solana wallet
        result = user_service.generate_solana_wallet(user_id)
        if not result:
            solana_address = user_service.get_solana_address(user_id)
        else:
            solana_address, _ = result

        # Vérifier le solde SOL
        try:
            sol_balance = await solana_tx_builder.get_sol_balance(solana_address)
        except Exception as e:
            logger.warning(f"Could not fetch SOL balance: {e}")
            sol_balance = 0.0

        bridge_text = f"""
🌉 BRIDGE SOL TO POLYGON

📍 Your Wallets:
🔶 Solana: `{solana_address}`
🔷 Polygon: `{polygon_wallet['address']}`

💰 Current SOL Balance: {sol_balance:.4f} SOL

💡 How it works:
1. Send SOL to your Solana address above
2. Use this command to bridge
3. Receive USDC.e + POL on Polygon automatically

⚡ Features:
• Auto-convert SOL → USDC → USDC.e
• Auto gas refuel (~3 POL)
• All-in-one solution
• Takes ~3-5 minutes
        """

        # Créer les boutons en fonction du solde
        keyboard = []

        if sol_balance >= 0.1:
            # Solde suffisant : proposer bridge auto
            bridge_text += f"\n\n✅ Balance sufficient!\n\nYou can bridge up to {sol_balance:.4f} SOL"

            keyboard.append([
                InlineKeyboardButton("🌉 Bridge (Auto)", callback_data=f"bridge_auto_{sol_balance:.4f}")
            ])
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh Balance", callback_data="refresh_sol_balance")
            ])
        else:
            # Solde insuffisant : proposer refresh
            bridge_text += f"\n\n⚠️ Minimum required: 0.1 SOL\n\nPlease send SOL to your address above first."

            keyboard.append([
                InlineKeyboardButton("🔄 Refresh Balance", callback_data="refresh_sol_balance")
            ])
            keyboard.append([
                InlineKeyboardButton("📋 Copy Solana Address", callback_data="copy_solana_address")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(bridge_text, parse_mode='Markdown', reply_markup=reply_markup)

        # Store balance in session for later use
        session = session_manager.get(user_id)
        session['sol_balance'] = sol_balance
        session['state'] = 'bridge_menu'

    except Exception as e:
        logger.error(f"Error in bridge_command: {e}")
        await update.message.reply_text(
            f"❌ Error: {str(e)}\n\nPlease try again or contact support.",
            parse_mode='Markdown'
        )


async def handle_bridge_amount_input(sol_amount: float, update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """
    Handle SOL amount input and show confirmation

    Args:
        sol_amount: Amount of SOL to bridge
        update: Telegram update
        context: Callback context
        session_manager: Session manager instance
    """
    user_id = update.effective_user.id

    try:
        if sol_amount <= 0:
            await update.message.reply_text(
                "❌ Amount must be greater than 0.\n\nEnter a valid amount:",
                parse_mode='Markdown'
            )
            return False

        # Minimum check
        if sol_amount < 0.1:
            await update.message.reply_text(
                "⚠️ Minimum amount: 0.1 SOL\n\n"
                "This ensures enough for fees and bridge minimums.\n\n"
                "Enter a valid amount:",
                parse_mode='Markdown'
            )
            return False

        # Get user's Polygon wallet
        polygon_wallet = user_service.get_user_wallet(user_id)
        if not polygon_wallet:
            await update.message.reply_text(
                "❌ Polygon wallet not found!\n\nUse /start to create your wallet.",
                parse_mode='Markdown'
            )
            return False

        polygon_address = polygon_wallet['address']

        # Get user's Solana wallet
        solana_address = user_service.get_solana_address(user_id)
        solana_private_key = user_service.get_solana_private_key(user_id)
        solana_wallet = {'address': solana_address, 'private_key': solana_private_key} if solana_address else None
        if not solana_wallet:
            await update.message.reply_text(
                "❌ Solana wallet not found!\n\nUse /solana to create your Solana wallet.",
                parse_mode='Markdown'
            )
            return False

        solana_address = solana_wallet['address']

        # Store amount in session
        session = session_manager.get(user_id)
        session['pending_bridge'] = {
            'sol_amount': sol_amount,
            'solana_address': solana_address,
            'polygon_address': polygon_address
        }
        session['state'] = 'confirming_bridge'

        # Show confirmation with estimated details
        estimated_usdc = sol_amount * 150  # Rough estimate (adjust based on market)
        estimated_pol = 3.0  # Gas refuel
        estimated_usdc_e = estimated_usdc - 10  # After fees

        confirmation_text = f"""
🌉 BRIDGE CONFIRMATION

📊 Bridge Details:
• Amount: {sol_amount} SOL
• From: `{solana_address[:20]}...`
• To: `{polygon_address[:20]}...`

💰 Estimated Receive (approximate):
• USDC.e: ~{estimated_usdc_e:.2f} USDC.e
• POL: ~{estimated_pol:.1f} POL (for gas)

⚠️ Important:
• Make sure you have {sol_amount} SOL in your Solana wallet
• Bridge takes 3-5 minutes
• Fees: ~3% total (Solana swap + bridge + Polygon swap)

✅ Ready to proceed?
        """

        keyboard = [
            [InlineKeyboardButton("✅ Confirm Bridge", callback_data=f"confirm_bridge_{user_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_bridge")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            confirmation_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

        return True

    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format.\n\nEnter a number (e.g., 5 or 10.5):",
            parse_mode='Markdown'
        )
        return False
    except Exception as e:
        logger.error(f"Error in handle_bridge_amount_input: {e}")
        await update.message.reply_text(
            f"❌ Error: {str(e)}\n\nTry again or contact support.",
            parse_mode='Markdown'
        )
        return False


async def handle_confirm_bridge(query, session_manager):
    """
    Execute bridge transaction after confirmation
    """
    user_id = query.from_user.id

    try:
        # Get pending bridge data from session
        session = session_manager.get(user_id)
        pending_bridge = session.get('pending_bridge')

        if not pending_bridge:
            await query.edit_message_text(
                "❌ Bridge data expired\n\nPlease restart with /bridge",
                parse_mode='Markdown'
            )
            return

        sol_amount = pending_bridge['sol_amount']
        solana_address = pending_bridge['solana_address']
        polygon_address = pending_bridge['polygon_address']

        logger.info(f"🌉 ========== BRIDGE EXECUTION ==========")
        logger.info(f"   User ID: {user_id}")
        logger.info(f"   SOL Amount: {sol_amount}")
        logger.info(f"   Solana: {solana_address}")
        logger.info(f"   Polygon: {polygon_address}")

        # Get wallets with private keys
        polygon_wallet = user_service.get_user_wallet(user_id)
        solana_address = user_service.get_solana_address(user_id)
        solana_private_key = user_service.get_solana_private_key(user_id)
        solana_wallet = {'address': solana_address, 'private_key': solana_private_key} if solana_address else None

        if not polygon_wallet or not solana_wallet:
            await query.edit_message_text(
                "❌ Wallet not found\n\nPlease restart with /start",
                parse_mode='Markdown'
            )
            return

        polygon_private_key = polygon_wallet['private_key']
        solana_private_key = solana_wallet['private_key']

        # Start bridge execution
        await query.edit_message_text(
            "🌉 BRIDGING IN PROGRESS\n\n"
            "Step 1: Swapping SOL... (~30s)\n"
            "Step 2: Bridging to Polygon... (~3 min)\n"
            "Step 3: Final setup... (~10s)\n\n"
            "⏱️ Total: ~3-5 minutes\n\n"
            "You can close this - we'll notify you when done!",
            parse_mode='Markdown'
        )

        # Define status callback for live updates
        async def status_update(message: str):
            try:
                await query.message.edit_text(
                    f"🌉 BRIDGE IN PROGRESS\n\n{message}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send status update: {e}")

        # Execute complete bridge workflow V3
        result = await bridge_v3.execute_full_bridge(
            sol_amount=sol_amount,
            solana_address=solana_address,
            solana_private_key=solana_private_key,
            polygon_address=polygon_address,
            polygon_private_key=polygon_private_key,
            status_callback=status_update
        )

        if result and result.get('success'):
            # Success message
            success_msg = f"""
✅ BRIDGE COMPLETE!

🎉 Your wallet is now ready for Polymarket!

📊 Summary:
• SOL bridged: {sol_amount:.6f} SOL
• USDC.e received: ~{result.get('usdc_e_received', 0):.2f} USDC.e
• POL for gas: ~{result.get('pol_kept_for_gas', 3):.1f} POL

🔗 Transactions:
• Solana Swap: `{result.get('swap_signature', 'N/A')[:20]}...`
• Bridge TX: `{result.get('debridge_signature', 'N/A')[:20]}...`
"""

            if result.get('quickswap_tx'):
                success_msg += f"• Polygon Swap: `{result['quickswap_tx'][:20]}...`\n"

            success_msg += "\n✅ Ready to trade! Use /markets to start."

            await query.message.edit_text(success_msg, parse_mode='Markdown')
        else:
            # Error message
            error = result.get('error', 'Unknown error') if result else 'Unknown error'
            step = result.get('step', 'unknown') if result else 'unknown'

            # Escape markdown characters in error message (all special chars)
            error_str = str(error)
            error_escaped = (error_str
                .replace('_', '\\_')
                .replace('*', '\\*')
                .replace('[', '\\[')
                .replace(']', '\\]')
                .replace('(', '\\(')
                .replace(')', '\\)')
                .replace('~', '\\~')
                .replace('`', '\\`')
                .replace('>', '\\>')
                .replace('#', '\\#')
                .replace('+', '\\+')
                .replace('-', '\\-')
                .replace('=', '\\=')
                .replace('|', '\\|')
                .replace('{', '\\{')
                .replace('}', '\\}')
                .replace('.', '\\.')
                .replace('!', '\\!')
            )
            
            step_escaped = (str(step)
                .replace('_', '\\_')
                .replace('*', '\\*')
                .replace('[', '\\[')
                .replace(']', '\\]')
                .replace('(', '\\(')
                .replace(')', '\\)')
            )

            error_msg = f"""
❌ Bridge Failed

📍 Failed at: {step_escaped}
⚠️ Error: {error_escaped}

💡 What to do:
1. Check your Solana wallet balance
2. Try again with /wallet
3. If issue persists, contact support
"""

            if result and result.get('swap_signature'):
                error_msg += f"\nSwap TX: `{result['swap_signature']}`"

            await query.message.edit_text(error_msg, parse_mode='Markdown')

        # Clean up session
        session['pending_bridge'] = None
        session['state'] = 'idle'

    except Exception as e:
        logger.error(f"Error in handle_confirm_bridge: {e}")
        try:
            # Escape ALL markdown special characters
            error_str = str(e)
            error_escaped = (error_str
                .replace('_', '\\_')
                .replace('*', '\\*')
                .replace('[', '\\[')
                .replace(']', '\\]')
                .replace('(', '\\(')
                .replace(')', '\\)')
                .replace('~', '\\~')
                .replace('`', '\\`')
                .replace('>', '\\>')
                .replace('#', '\\#')
                .replace('+', '\\+')
                .replace('-', '\\-')
                .replace('=', '\\=')
                .replace('|', '\\|')
                .replace('{', '\\{')
                .replace('}', '\\}')
                .replace('.', '\\.')
                .replace('!', '\\!')
            )
            await query.edit_message_text(
                f"❌ Unexpected error: {error_escaped}\n\nPlease try again or contact support\\.",
                parse_mode='Markdown'
            )
        except:
            # Fallback: send without markdown
            await query.edit_message_text(
                f"❌ Unexpected error: {str(e)}\n\nPlease try again or contact support."
            )


async def handle_cancel_bridge(query, session_manager):
    """
    Cancel bridge transaction
    """
    user_id = query.from_user.id

    # Clean up session
    session = session_manager.get(user_id)
    session['pending_bridge'] = None
    session['state'] = 'idle'

    await query.edit_message_text(
        "❌ Bridge cancelled\n\nYou can start again anytime with /bridge",
        parse_mode='Markdown'
    )


async def handle_fund_bridge_solana(query, session_manager):
    """
    Start bridge workflow from inline button
    (Called from /fund or /solana buttons)
    """
    user_id = query.from_user.id

    try:
        # Vérifier wallets
        polygon_wallet = user_service.get_user_wallet(user_id)
        if not polygon_wallet:
            await query.edit_message_text(
                "❌ No Polygon wallet found!\n\nUse /start to create your wallet first.",
                parse_mode='Markdown'
            )
            return

        # Créer/récupérer wallet Solana
        username = query.from_user.username or "Unknown"
        # Get or generate Solana wallet
        result = user_service.generate_solana_wallet(user_id)
        if not result:
            solana_address = user_service.get_solana_address(user_id)
        else:
            solana_address, _ = result

        bridge_text = f"""
🌉 BRIDGE FROM SOLANA

📍 Your Wallets:
🔶 Solana: `{solana_address}`
🔷 Polygon: `{polygon_wallet['address']}`

💡 Next Steps:
1. Send SOL to your Solana address
2. Type the amount to bridge (e.g., `5`)
3. Confirm and wait 3-5 minutes

⚡ Or use /bridge command for full details.

💬 Enter SOL amount to bridge:
        """

        await query.edit_message_text(bridge_text, parse_mode='Markdown')

        # Set user state
        session = session_manager.get(user_id)
        session['state'] = 'awaiting_bridge_amount'

    except Exception as e:
        logger.error(f"Error in handle_fund_bridge_solana: {e}")
        await query.edit_message_text(
            f"❌ Error: {str(e)}\n\nTry /bridge command instead.",
            parse_mode='Markdown'
        )


async def handle_refresh_sol_balance(query, session_manager):
    """
    Refresh SOL balance and update bridge menu
    Callback: refresh_sol_balance
    """
    user_id = query.from_user.id

    try:
        await query.answer("🔄 Refreshing balance...")

        # Get wallets
        polygon_wallet = user_service.get_user_wallet(user_id)
        solana_address = user_service.get_solana_address(user_id)
        solana_private_key = user_service.get_solana_private_key(user_id)
        solana_wallet = {'address': solana_address, 'private_key': solana_private_key} if solana_address else None

        if not solana_wallet:
            await query.edit_message_text(
                "❌ No Solana wallet found!\n\nUse /bridge to create one.",
                parse_mode='Markdown'
            )
            return

        solana_address = solana_wallet['address']

        # Fetch fresh balance
        try:
            sol_balance = await solana_tx_builder.get_sol_balance(solana_address)
        except Exception as e:
            logger.error(f"Error fetching SOL balance: {e}")
            await query.answer("❌ Could not fetch balance. Try again.", show_alert=True)
            return

        bridge_text = f"""
🌉 BRIDGE SOL TO POLYGON

📍 Your Wallets:
🔶 Solana: `{solana_address}`
🔷 Polygon: `{polygon_wallet['address']}`

💰 Current SOL Balance: {sol_balance:.4f} SOL

💡 How it works:
1. Send SOL to your Solana address above
2. Use this command to bridge
3. Receive USDC.e + POL on Polygon automatically

⚡ Features:
• Auto-convert SOL → USDC → USDC.e
• Auto gas refuel (~3 POL)
• All-in-one solution
• Takes ~3-5 minutes
        """

        # Créer les boutons en fonction du solde
        keyboard = []

        if sol_balance >= 0.1:
            # Solde suffisant : proposer bridge auto
            bridge_text += f"\n\n✅ Balance sufficient!\n\nYou can bridge up to {sol_balance:.4f} SOL"

            keyboard.append([
                InlineKeyboardButton("🌉 Bridge (Auto)", callback_data=f"bridge_auto_{sol_balance:.4f}")
            ])
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh Balance", callback_data="refresh_sol_balance")
            ])
        else:
            # Solde insuffisant : proposer refresh
            bridge_text += f"\n\n⚠️ Minimum required: 0.1 SOL\n\nPlease send SOL to your address above first."

            keyboard.append([
                InlineKeyboardButton("🔄 Refresh Balance", callback_data="refresh_sol_balance")
            ])
            keyboard.append([
                InlineKeyboardButton("📋 Copy Solana Address", callback_data="copy_solana_address")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(bridge_text, parse_mode='Markdown', reply_markup=reply_markup)

        # Update session
        session = session_manager.get(user_id)
        session['sol_balance'] = sol_balance
        session['state'] = 'bridge_menu'

    except Exception as e:
        logger.error(f"Error refreshing SOL balance: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_bridge_auto(query, session_manager):
    """
    Handle automatic bridge with full balance
    Callback: bridge_auto_{amount}
    """
    user_id = query.from_user.id

    try:
        # Extract amount from callback data
        callback_data = query.data
        sol_amount_str = callback_data.replace("bridge_auto_", "")
        sol_amount = float(sol_amount_str)

        # Reserve a small amount for fees (0.01 SOL)
        sol_to_bridge = max(0.1, sol_amount - 0.01)

        await query.answer(f"🌉 Preparing to bridge {sol_to_bridge:.4f} SOL...")

        # Get wallets
        polygon_wallet = user_service.get_user_wallet(user_id)
        solana_address = user_service.get_solana_address(user_id)
        solana_private_key = user_service.get_solana_private_key(user_id)
        solana_wallet = {'address': solana_address, 'private_key': solana_private_key} if solana_address else None

        if not solana_wallet or not polygon_wallet:
            await query.edit_message_text(
                "❌ Wallet error!\n\nPlease use /bridge to start over.",
                parse_mode='Markdown'
            )
            return

        solana_address = solana_wallet['address']

        # Estimate output
        estimated_usdc = sol_to_bridge * 147  # Rough estimate ~$147/SOL
        estimated_pol = 3.0

        confirmation_text = f"""
🌉 BRIDGE CONFIRMATION (Auto)

📊 Bridge Details:
• Amount: {sol_to_bridge:.4f} SOL (full balance minus fees)
• Destination: Polygon

💰 Estimated Output:
• USDC.e: ~{estimated_usdc:.2f} USDC.e
• POL (gas): ~{estimated_pol:.1f} POL

⏱️ Estimated Time: 3-5 minutes

🔶 From: `{solana_address[:8]}...{solana_address[-8:]}`
🔷 To: `{polygon_wallet['address'][:8]}...{polygon_wallet['address'][-8:]}`

⚠️ Important:
• This will bridge your entire balance
• Cannot be reversed once started
• Make sure you have enough SOL for fees

Ready to proceed?
        """

        keyboard = [
            [InlineKeyboardButton("✅ Confirm Bridge", callback_data=f"confirm_bridge_{user_id}_{sol_to_bridge}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_bridge")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(confirmation_text, parse_mode='Markdown', reply_markup=reply_markup)

        # Store in session
        session = session_manager.get(user_id)
        session['pending_bridge'] = {
            'sol_amount': sol_to_bridge,
            'solana_address': solana_address,
            'polygon_address': polygon_wallet['address']
        }
        session['state'] = 'confirming_bridge'

    except Exception as e:
        logger.error(f"Error in bridge_auto: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_bridge_custom_amount(query, session_manager):
    """
    Switch to custom amount input mode
    Callback: bridge_custom_amount
    """
    user_id = query.from_user.id

    try:
        await query.answer("✏️ Enter custom amount...")

        solana_address = user_service.get_solana_address(user_id)
        solana_private_key = user_service.get_solana_private_key(user_id)
        solana_wallet = {'address': solana_address, 'private_key': solana_private_key} if solana_address else None
        solana_address = solana_wallet['address']

        session = session_manager.get(user_id)
        sol_balance = session.get('sol_balance', 0.0)

        custom_text = f"""
🌉 BRIDGE - CUSTOM AMOUNT

💰 Your Balance: {sol_balance:.4f} SOL
🔶 Solana Address: `{solana_address}`

💬 Enter the amount of SOL to bridge:
(Example: type `5` to bridge 5 SOL)

⚠️ Minimum: 0.1 SOL
        """

        await query.edit_message_text(custom_text, parse_mode='Markdown')

        # Set state
        session['state'] = 'awaiting_bridge_amount'

    except Exception as e:
        logger.error(f"Error in bridge_custom_amount: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_copy_solana_address(query, session_manager):
    """
    Show Solana address for easy copying
    Callback: copy_solana_address
    """
    user_id = query.from_user.id

    try:
        solana_address = user_service.get_solana_address(user_id)
        solana_private_key = user_service.get_solana_private_key(user_id)
        solana_wallet = {'address': solana_address, 'private_key': solana_private_key} if solana_address else None

        if not solana_wallet:
            await query.answer("❌ No Solana wallet found!", show_alert=True)
            return

        solana_address = solana_wallet['address']

        copy_text = f"""
📋 YOUR SOLANA ADDRESS

`{solana_address}`

💡 How to use:
1. Tap the address above to select it
2. Copy it to your clipboard
3. Send SOL from your exchange/wallet
4. Wait 1-2 minutes for confirmation

⚠️ Important: Only send SOL to this address!
        """

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Balance", callback_data="refresh_sol_balance")],
            [InlineKeyboardButton("🌉 Back to Bridge Menu", callback_data="back_to_bridge_menu")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(copy_text, parse_mode='Markdown', reply_markup=reply_markup)
        await query.answer("📋 Address ready to copy!", show_alert=False)

    except Exception as e:
        logger.error(f"Error showing Solana address: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_back_to_bridge_menu(query, session_manager):
    """
    Return to main bridge menu
    Callback: back_to_bridge_menu
    """
    user_id = query.from_user.id

    try:
        await query.answer("← Returning to bridge menu...")

        # Trigger refresh to show updated menu
        await handle_refresh_sol_balance(query, session_manager)

    except Exception as e:
        logger.error(f"Error returning to bridge menu: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


def register(app: Application, session_manager):
    """
    Register all bridge command handlers

    Args:
        app: Telegram Application instance
        session_manager: Session manager instance
    """
    # Bind session_manager to commands
    bridge_cmd = partial(bridge_command, session_manager=session_manager)

    # Register commands
    app.add_handler(CommandHandler("bridge", bridge_cmd))

    logger.info("✅ Bridge handlers registered")
