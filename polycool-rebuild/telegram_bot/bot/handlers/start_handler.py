"""
Start command handler
Handles user onboarding and wallet creation
Simplified onboarding: 2 stages (onboarding → ready)
"""
import os
from typing import Optional, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.user.user_service import user_service
from core.services.user.user_helper import get_user_data
from core.services.wallet.wallet_service import wallet_service
from core.services.balance.balance_service import balance_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle welcome message for new users who haven't started yet
    Shows when user sends any message (not a command) and doesn't have an account
    """
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    try:
        # Quick check: if message starts with /, it's a command, skip welcome
        if update.message.text and update.message.text.startswith('/'):
            return

        # Check if user exists (quick check to avoid showing welcome to existing users)
        user_data = await get_user_data(user_id)

        # Only show welcome if user doesn't exist yet
        if not user_data:
            welcome_text = """
🚀 **Welcome to Polycool!**

Trade prediction markets on Polymarket with ease.

**Top Features:**

💎 **Smart Trading**
Follow top-performing wallets automatically

📊 **Copy Trading**
Mirror successful traders' moves in real-time

📈 **Position Management**
Track your trades with TP/SL automation

🎁 **Referral Program**
Earn commissions from your network

**Get Started:**
Tap /start to create your account and start trading!

*Simple, fast, and powerful.*
            """.strip()

            await update.message.reply_text(
                welcome_text,
                parse_mode='Markdown'
            )
            logger.info(f"📨 Welcome message sent to new user {user_id}")
        # If user exists, let other handlers process the message (return None to continue chain)

    except Exception as e:
        logger.error(f"Error sending welcome message to user {user_id}: {e}")
        # Don't show error to user - just log it and let other handlers process


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start command
    Simplified onboarding: 2 stages instead of 5
    Supports referral codes: /start ref_username
    """
    if not update.effective_user:
        return

    user = update.effective_user
    user_id = user.id
    username = user.username

    # Extract referral code from command args (e.g., /start ref_username)
    referral_code = None
    if update.message and update.message.text:
        parts = update.message.text.split()
        if len(parts) > 1:
            referral_code = parts[1].strip()

    try:
        logger.info(f"🚀 START COMMAND RECEIVED - User {user_id} ({username}) started Polycool bot")
        if referral_code:
            logger.info(f"🔗 Referral code detected: {referral_code}")
        print(f"🚀 START COMMAND RECEIVED - User {user_id} ({username}) started Polycool bot")
        print(f"🤖 BOT @Polypolis_Bot IS ACTIVE AND RECEIVING MESSAGES!")

        # Check if user exists (via API or DB)
        user_data = await get_user_data(user_id)

        if user_data:
            # Existing user - check if referral code was provided and user not already referred
            if referral_code:
                await _handle_referral_code(update, user_data, referral_code)

            # Show appropriate dashboard
            if user_data.get('stage') == 'ready':
                await _show_ready_dashboard(update, user_data)
            else:
                await _show_onboarding_status(update, user_data)
        else:
            # New user - create wallets and handle referral
            await _create_new_user(update, user_id, username, referral_code)

    except Exception as e:
        logger.error(f"Error in start handler for user {user_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await update.message.reply_text(
            "❌ An error occurred. Please try again."
        )


async def _create_new_user(update: Update, user_id: int, username: Optional[str], referral_code: Optional[str] = None) -> None:
    """Create user with wallets via API and handle referral code"""
    # Send loading message immediately
    loading_message = await update.message.reply_text(
        "⏳ **Creating your account...**\n\n"
        "Please wait while we set up your wallets and account.\n"
        "This will only take a few seconds.",
        parse_mode='Markdown'
    )

    try:
        # Generate wallets locally
        wallets = wallet_service.generate_user_wallets()

        # Create user via API
        if SKIP_DB:
            api_client = get_api_client()
            user_data = await api_client.create_user(
                telegram_user_id=user_id,
                username=username,
                polygon_address=wallets['polygon_address'],
                polygon_private_key=wallets['polygon_private_key'],
                solana_address=wallets['solana_address'],
                solana_private_key=wallets['solana_private_key'],
                stage="onboarding"
            )

            if not user_data:
                # API call failed
                try:
                    await loading_message.edit_text(
                        "❌ **Account Creation Failed**\n\n"
                        "We couldn't create your account right now. Please try again in a moment.",
                        parse_mode='Markdown'
                    )
                except:
                    await update.message.reply_text(
                        "❌ **Account Creation Failed**\n\n"
                        "We couldn't create your account right now. Please try again in a moment.",
                        parse_mode='Markdown'
                    )
                return
        else:
            # Direct DB access (for testing/development)
            user = await user_service.create_user(
                telegram_user_id=user_id,
                username=username,
                polygon_address=wallets['polygon_address'],
                polygon_private_key=wallets['polygon_private_key'],
                solana_address=wallets['solana_address'],
                solana_private_key=wallets['solana_private_key'],
                stage="onboarding"
            )
            if not user:
                try:
                    await loading_message.edit_text(
                        "❌ **Account Creation Failed**\n\n"
                        "We couldn't create your account right now. Please try again in a moment.",
                        parse_mode='Markdown'
                    )
                except:
                    await update.message.reply_text(
                        "❌ **Account Creation Failed**\n\n"
                        "We couldn't create your account right now. Please try again in a moment.",
                        parse_mode='Markdown'
                    )
                return
            user_data = {
                "id": user.id,
                "telegram_user_id": user.telegram_user_id,
                "username": user.username,
                "stage": user.stage,
                "polygon_address": user.polygon_address,
                "solana_address": user.solana_address
            }

        # Handle referral code if provided
        if referral_code:
            await _handle_referral_code(update, user_data, referral_code)

        # Show success message with wallet addresses
        message = f"""
🤖 **Welcome to Polycool Bot!**

✅ **Your account has been created!**

💰 **Your Wallets:**

🔷 **Polygon Wallet:**
`{wallets['polygon_address']}`

🟣 **Solana Wallet:**
`{wallets['solana_address']}`

📊 **Status:** ONBOARDING

💡 **Next Steps:**
1️⃣ Fund your Solana wallet with at least 0.1 SOL
2️⃣ Click "🔄 Check Balance" below to verify
3️⃣ Bridge will unlock automatically when ready

✅ Tap addresses above to copy
        """.strip()

        keyboard = [
            [InlineKeyboardButton("🔄 Check Balance", callback_data="check_sol_balance")],
            [InlineKeyboardButton("💼 View Wallet Details", callback_data="view_wallet")],
            [InlineKeyboardButton("❓ Help & FAQ", callback_data="onboarding_help")]
        ]

        # Edit loading message with final result
        try:
            await loading_message.edit_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            # If edit fails (e.g., message too different), send new message
            logger.warning(f"Could not edit loading message, sending new: {e}")
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        logger.info(f"✅ Created user {user_id} via {'API' if SKIP_DB else 'DB'}")

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"❌ Error creating new user {user_id}: {e}\n{error_details}")

        # More specific error message
        error_msg = "❌ **Account Creation Failed**\n\nWe couldn't create your account right now. Please try again in a moment."
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            error_msg = "⚠️ Account already exists. Use /wallet to view your information."

        try:
            await loading_message.edit_text(error_msg, parse_mode='Markdown')
        except:
            await update.message.reply_text(error_msg, parse_mode='Markdown')


async def _show_onboarding_status(update: Update, user_data: Dict[str, Any]) -> None:
    """Show onboarding status for users in onboarding stage"""
    # Check SOL balance to show appropriate UI
    from core.services.bridge import get_bridge_service
    bridge_service = get_bridge_service()

    solana_address = user_data.get('solana_address', '')
    username = user_data.get('username')
    stage = user_data.get('stage', 'onboarding')

    try:
        sol_balance = await bridge_service.get_sol_balance(solana_address)
    except Exception as e:
        logger.warning(f"Could not fetch SOL balance: {e}")
        sol_balance = 0.0

    balance_status = f"💰 **Current Balance:** {sol_balance:.4f} SOL" if sol_balance > 0 else ""

    message = f"""
🚀 **ONBOARDING IN PROGRESS**

👋 Hi {username or 'there'}!

Your wallets are ready:

🔶 **SOLANA ADDRESS:**
`{solana_address}`

{balance_status}

📊 **Status:** {stage.upper()}

💡 **Next Steps:**
1️⃣ Fund your Solana wallet with at least 0.1 SOL
   • From a CEX (Binance, Kraken, etc.) or your own wallet
   • Send to address above
2️⃣ Click "🔄 Check Balance" to verify
3️⃣ Bridge will unlock automatically when ready
    """.strip()

    keyboard = []

    # Show appropriate button based on balance
    if sol_balance >= 0.1:
        keyboard.append([InlineKeyboardButton("🌉 I've Funded - Start Bridge", callback_data="start_bridge")])
    else:
        keyboard.append([InlineKeyboardButton("🔄 Check Balance", callback_data="check_sol_balance")])

    keyboard.append([InlineKeyboardButton("💼 View Wallet", callback_data="view_wallet")])

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def _show_ready_dashboard(update: Update, user_data: Dict[str, Any]) -> None:
    """Show trading dashboard for READY users"""
    polygon_address = user_data.get('polygon_address', '')
    solana_address = user_data.get('solana_address', '')
    username = user_data.get('username')

    # Get USDC.e balance
    usdc_balance = None
    if polygon_address:
        try:
            usdc_balance = await balance_service.get_usdc_balance(polygon_address)
        except Exception as e:
            logger.warning(f"Could not fetch USDC balance: {e}")

    balance_display = balance_service.format_balance_display(usdc_balance) if usdc_balance is not None else "💵 **Balance:** Checking..."

    message = f"""
👋 **Welcome back, {username or 'there'}!**

✅ **Status: READY TO TRADE**

{balance_display}

💼 **Polygon Wallet:**
`{polygon_address[:10]}...{polygon_address[-8:] if polygon_address else "Not set"}`

🔶 **Solana Wallet:**
`{solana_address[:10]}...{solana_address[-8:] if solana_address else "Not set"}`

📊 **Quick Actions:**
    """.strip()

    keyboard = [
        [InlineKeyboardButton("📊 Browse Markets", callback_data="markets_hub")],
        [InlineKeyboardButton("📈 View Positions", callback_data="view_positions")],
        [InlineKeyboardButton("💼 Wallet", callback_data="view_wallet")],
        [InlineKeyboardButton("🎯 Smart Trading", callback_data="smart_trading")]
    ]

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callbacks from start handler buttons
    Routes: start_bridge, view_wallet, onboarding_help, confirm_bridge_*, cancel_bridge
    Note: markets_hub, view_positions, smart_trading are handled by their respective handlers
    """
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id

    try:
        await query.answer()

        logger.info(f"🔄 START_HANDLER callback received: {callback_data} for user {user_id}")

        if callback_data == "start_bridge":
            await _handle_start_bridge(query, context)
        elif callback_data == "check_sol_balance":
            await _handle_check_sol_balance(query, context)
        elif callback_data == "view_wallet":
            await _handle_view_wallet(query, context)
        elif callback_data == "onboarding_help":
            await _handle_onboarding_help(query, context)
        elif callback_data.startswith("confirm_bridge_"):
            await _handle_confirm_bridge(query, context)
        elif callback_data == "cancel_bridge":
            await _handle_cancel_bridge(query, context)
        else:
            logger.warning(f"Unknown start callback: {callback_data}")
            await query.edit_message_text("❌ Unknown action")

    except Exception as e:
        logger.error(f"Error handling start callback for user {user_id}: {e}")
        if query.message:
            await query.edit_message_text("❌ An error occurred. Please try again.")


async def _handle_check_sol_balance(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle check SOL balance callback - verify balance and update UI"""
    try:
        user_id = query.from_user.id
        user_data = await get_user_data(user_id)

        if not user_data:
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        solana_address = user_data.get('solana_address')
        if not solana_address:
            await query.edit_message_text("❌ Solana wallet not found. Please complete onboarding.")
            return

        # Show checking message
        await query.answer("🔍 Checking balance...")

        # Get bridge service and check balance
        from core.services.bridge import get_bridge_service
        bridge_service = get_bridge_service()

        sol_balance = await bridge_service.get_sol_balance(solana_address)

        # Add timestamp for unique message content
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Update UI based on balance
        balance_status = f"💰 **Current Balance:** {sol_balance:.4f} SOL" if sol_balance > 0 else ""

        if sol_balance < 0.1:
            # Insufficient balance - show instructions
            message = f"""
❌ **Insufficient SOL Balance**

📊 **Current Balance:** {sol_balance:.6f} SOL
⚠️ **Minimum Required:** 0.1 SOL (~$20)
🕒 **Last checked:** {timestamp}

📍 **Your SOL Address:**
`{solana_address}`

💡 **How to Fund:**

**From a CEX** (Binance, Kraken, Coinbase, etc.):
1. Copy address above
2. Send at least 0.1 SOL to this address
3. Wait for confirmation (~30 seconds)
4. Click "🔄 Check Balance Again" below

**From your own wallet:**
1. Copy address above
2. Send at least 0.1 SOL to this address
3. Wait for confirmation (~30 seconds)
4. Click "🔄 Check Balance Again" below

✅ Tap address above to copy
            """.strip()

            keyboard = [
                [InlineKeyboardButton("🔄 Check Balance Again", callback_data="check_sol_balance")],
                [InlineKeyboardButton("💼 View Wallet Details", callback_data="view_wallet")],
                [InlineKeyboardButton("❓ Help & FAQ", callback_data="onboarding_help")]
            ]

            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            # Sufficient balance - show bridge option
            message = f"""
✅ **Balance Verified!**

{balance_status}
🕒 **Last checked:** {timestamp}

🌉 **Ready to Bridge**

Your wallet has enough SOL to start the bridge process.

**What happens next:**
1️⃣ Swap SOL → USDC (Jupiter)
2️⃣ Bridge USDC → POL (deBridge)
3️⃣ Swap POL → USDC.e (QuickSwap)
4️⃣ Auto-approve contracts
5️⃣ Generate API keys

⏱️ **Estimated time:** 3-5 minutes

Click "Start Bridge" to begin!
            """.strip()

            keyboard = [
                [InlineKeyboardButton("🌉 Start Bridge", callback_data="start_bridge")],
                [InlineKeyboardButton("🔄 Check Balance Again", callback_data="check_sol_balance")],
                [InlineKeyboardButton("💼 View Wallet Details", callback_data="view_wallet")]
            ]

            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error checking SOL balance: {e}")
        await query.edit_message_text(
            "❌ Error checking balance. Please try again.",
            parse_mode='Markdown'
        )


async def _handle_start_bridge(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle start bridge callback - initiate SOL to USDC bridge"""
    logger.info(f"🌉 START_BRIDGE callback received for user {query.from_user.id}")
    import asyncio
    from core.services.bridge import get_bridge_service

    try:
        user_id = query.from_user.id
        logger.info(f"🔍 Getting user data for bridge: {user_id}")
        user_data = await get_user_data(user_id)
        logger.info(f"👤 User found: {user_data is not None}")

        if not user_data:
            logger.error("❌ User not found")
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        solana_address = user_data.get('solana_address')
        polygon_address = user_data.get('polygon_address')
        stage = user_data.get('stage', 'onboarding')

        logger.info(f"📊 User stage: {stage}, SOL: {bool(solana_address)}, POL: {bool(polygon_address)}")

        if not solana_address:
            logger.error("❌ Solana wallet missing")
            await query.edit_message_text("❌ Solana wallet not found. Please complete onboarding.")
            return

        if not polygon_address:
            logger.error("❌ Polygon wallet missing")
            await query.edit_message_text("❌ Polygon wallet not found. Please complete onboarding.")
            return

        logger.info("✅ Wallets validated, getting bridge service")

        # Get bridge service
        bridge_service = get_bridge_service()
        logger.info("🔧 Bridge service initialized")

        # Check SOL balance first (CRITICAL: verify before allowing bridge)
        logger.info("💰 Checking SOL balance...")
        await query.answer("🔍 Verifying balance...")

        sol_balance = await bridge_service.get_sol_balance(solana_address)
        logger.info(f"💰 SOL balance: {sol_balance:.6f} SOL")

        # Enforce minimum balance requirement
        if sol_balance < 0.1:
            await query.edit_message_text(
                f"❌ **Insufficient SOL Balance**\n\n"
                f"📊 **Current Balance:** {sol_balance:.6f} SOL\n"
                f"⚠️ **Minimum Required:** 0.1 SOL\n\n"
                f"📍 **Your SOL Address:**\n`{solana_address}`\n\n"
                f"Please fund your wallet first, then click \"🔄 Check Balance\" to verify.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Check Balance", callback_data="check_sol_balance")
                ]]),
                parse_mode='Markdown'
            )
            return

        # Calculate amount to bridge (use 80% of balance, reserve rest for fees)
        bridge_amount = sol_balance * 0.8

        # Confirm bridge amount
        keyboard = [
            [InlineKeyboardButton(f"✅ Bridge {bridge_amount:.4f} SOL", callback_data=f"confirm_bridge_{bridge_amount:.6f}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_bridge")]
        ]

        logger.info(f"🔄 Displaying bridge confirmation with amount: {bridge_amount:.6f} SOL")

        await query.edit_message_text(
            f"🌉 **Bridge Confirmation**\n\n"
            f"**Balance:** {sol_balance:.6f} SOL\n"
            f"**Bridge Amount:** {bridge_amount:.6f} SOL\n"
            f"**Reserve:** {sol_balance - bridge_amount:.6f} SOL (for fees)\n\n"
            f"**Process:**\n"
            f"1️⃣ Swap SOL → USDC (Jupiter)\n"
            f"2️⃣ Bridge USDC → POL (deBridge)\n"
            f"3️⃣ Wait for arrival (~2-5 min)\n\n"
            f"⏱️ Estimated time: 3-5 minutes\n\n"
            f"Confirm to proceed?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in start_bridge callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text("❌ Error initiating bridge. Please try again.")


async def _handle_view_wallet(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle view wallet callback - show wallet details"""
    try:
        user_id = query.from_user.id
        user_data = await get_user_data(user_id)

        if not user_data:
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        # Import wallet handler to reuse logic
        from telegram_bot.bot.handlers import wallet_handler

        # Create a fake update for wallet handler
        class FakeUpdate:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.message = query.message

        fake_update = FakeUpdate(query)
        await wallet_handler.handle_wallet(fake_update, context)

    except Exception as e:
        logger.error(f"Error in view_wallet callback: {e}")
        await query.edit_message_text("❌ Error loading wallet. Please try again.")


async def _handle_onboarding_help(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle onboarding help callback - show FAQ"""
    try:
        user_id = query.from_user.id
        user_data = await get_user_data(user_id)

        solana_address = user_data.get('solana_address', 'N/A') if user_data else "N/A"

        help_message = f"""
❓ **HELP & FAQ**

**Getting Started:**
1️⃣ Fund your Solana wallet with at least 0.1 SOL
   • From a CEX (Binance, Kraken, Coinbase, etc.)
   • Or from your own wallet
   • Send to: `{solana_address}`
2️⃣ Click "🔄 Check Balance" to verify
3️⃣ Bridge will unlock automatically when ready
4️⃣ Click "Start Bridge" to begin the process

**Wallets:**
• **Solana Wallet:** For receiving SOL (funding)
• **Polygon Wallet:** For trading on Polymarket

**Bridge Process:**
1️⃣ Swap SOL → USDC (via Jupiter)
2️⃣ Bridge USDC → POL (via deBridge)
3️⃣ Swap POL → USDC.e (via QuickSwap, keeps 3 POL for gas)
4️⃣ Auto-approve contracts
5️⃣ Generate API keys

⏱️ **Total time:** ~3-5 minutes

**Need More Help?**
• Use /wallet to view your wallets
• Use /markets to browse markets
• Use /positions to view your positions

**Minimum Requirements:**
• At least 0.1 SOL needed to start bridge
• Bridge will reserve some SOL/POL for gas fees
        """.strip()

        keyboard = [
            [InlineKeyboardButton("🔄 Check Balance", callback_data="check_sol_balance")],
            [InlineKeyboardButton("← Back", callback_data="start_bridge")]
        ]

        await query.edit_message_text(
            help_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in onboarding_help callback: {e}")
        await query.edit_message_text("❌ Error loading help. Please try again.")


async def _handle_confirm_bridge(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bridge confirmation - execute bridge in background"""
    logger.info(f"✅ CONFIRM_BRIDGE callback received for user {query.from_user.id}")
    import asyncio
    from core.services.bridge import get_bridge_service

    try:
        user_id = query.from_user.id
        callback_data = query.data
        logger.info(f"📊 Callback data: {callback_data}")

        # Extract bridge amount from callback data
        bridge_amount_str = callback_data.replace("confirm_bridge_", "")
        bridge_amount = float(bridge_amount_str)
        logger.info(f"💸 Bridge amount extracted: {bridge_amount:.6f} SOL")

        # Update message to show bridge started
        await query.edit_message_text(
            f"🌉 **Bridge Started**\n\n"
            f"Amount: {bridge_amount:.6f} SOL\n\n"
            f"⏳ Processing...\n"
            f"This will take 3-5 minutes.\n\n"
            f"You'll receive updates here.",
            parse_mode='Markdown'
        )

        # Status callback for updates
        async def status_callback(status_message: str):
            """Update Telegram message with bridge status"""
            try:
                await query.edit_message_text(
                    f"🌉 **Bridge Progress**\n\n{status_message}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Failed to update bridge status: {e}")

        # Execute bridge in background task
        bridge_service = get_bridge_service()

        # Run bridge in background
        asyncio.create_task(
            _execute_bridge_background(
                bridge_service=bridge_service,
                user_id=user_id,
                sol_amount=bridge_amount,
                status_callback=status_callback,
                query=query
            )
        )

    except Exception as e:
        logger.error(f"Error confirming bridge: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text("❌ Error starting bridge. Please try again.")


async def _execute_bridge_background(
    bridge_service,
    user_id: int,
    sol_amount: float,
    status_callback,
    query
) -> None:
    """Execute bridge in background with status updates"""
    try:
        result = await bridge_service.execute_bridge(
            telegram_user_id=user_id,
            sol_amount=sol_amount,
            status_callback=status_callback
        )

        if result.get('success'):
            # Update user stage to ready if bridge succeeded
            # Note: Stage update should be handled by bridge service or API
            # For now, just show success message
            user_data = await get_user_data(user_id)

            await query.edit_message_text(
                f"✅ **Bridge Completed!**\n\n"
                f"POL received: {result.get('pol_received', 0):.4f} POL\n\n"
                f"Swap TX: `{result.get('swap_signature', 'N/A')}`\n"
                f"Bridge TX: `{result.get('debridge_signature', 'N/A')}`\n\n"
                f"You're now ready to trade!",
                parse_mode='Markdown'
            )
        else:
            error_msg = result.get('error', 'unknown_error')
            await query.edit_message_text(
                f"❌ **Bridge Failed**\n\n"
                f"Error: {error_msg}\n\n"
                f"Please check your balances and try again.",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error executing bridge: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text(
            f"❌ **Bridge Error**\n\n"
            f"An error occurred: {str(e)}\n\n"
            f"Please try again or contact support.",
            parse_mode='Markdown'
        )


async def _handle_cancel_bridge(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bridge cancellation"""
    try:
        await query.edit_message_text(
            "❌ Bridge cancelled.\n\n"
            "Use /start to try again when ready."
        )
    except Exception as e:
        logger.error(f"Error cancelling bridge: {e}")


async def _handle_referral_code(update, user_data: Dict[str, Any], referral_code: str) -> None:
    """
    Handle referral code when user starts with /start ref_code
    Creates referral relationship via API or service
    """
    try:
        user_id = user_data.get('id')
        telegram_user_id = user_data.get('telegram_user_id')

        if not user_id:
            logger.warning(f"Could not get internal user ID for referral code handling")
            return

        logger.info(f"🔗 Processing referral code '{referral_code}' for user {telegram_user_id}")

        # Create referral via API or service
        if SKIP_DB:
            api_client = get_api_client()
            result = await api_client._post(
                "/referral/create",
                {
                    "referrer_code": referral_code,
                    "referred_telegram_user_id": telegram_user_id
                }
            )

            if result and result.get('success'):
                logger.info(f"✅ Referral created successfully for user {telegram_user_id}")
                # Show success message (non-blocking, don't interrupt onboarding)
                if update.message:
                    await update.message.reply_text(
                        f"🎉 **Referral Link Activated!**\n\n"
                        f"You've been referred by `{referral_code}`.\n"
                        f"You'll get 10% discount on trading fees!",
                        parse_mode='Markdown'
                    )
            else:
                # Enhanced error logging
                if result:
                    error_message = result.get('message', 'Unknown error')
                    error_detail = result.get('detail', '')
                    logger.warning(f"⚠️ Referral creation failed for user {telegram_user_id}: {error_message}")
                    if error_detail:
                        logger.warning(f"   Error detail: {error_detail}")
                else:
                    logger.error(f"❌ API call to /referral/create failed - no response returned")
                    logger.error(f"   Referrer code: {referral_code}, Referred user: {telegram_user_id}")
                # Don't show error to user (non-critical, don't interrupt onboarding)
        else:
            # Direct service call
            from core.services.referral.referral_service import get_referral_service
            referral_service = get_referral_service()
            success, message = await referral_service.create_referral(
                referrer_code=referral_code,
                referred_user_id=user_id
            )

            if success:
                logger.info(f"✅ Referral created successfully for user {telegram_user_id}")
                if update.message:
                    await update.message.reply_text(
                        f"🎉 **Referral Link Activated!**\n\n"
                        f"You've been referred by `{referral_code}`.\n"
                        f"You'll get 10% discount on trading fees!",
                        parse_mode='Markdown'
                    )
            else:
                logger.warning(f"⚠️ Referral creation failed: {message}")

    except Exception as e:
        logger.error(f"❌ Error handling referral code: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # Don't interrupt onboarding flow if referral fails
