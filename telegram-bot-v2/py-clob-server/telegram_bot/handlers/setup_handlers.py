#!/usr/bin/env python3
"""
Setup Handlers
Handles user setup commands: /start, /help, /wallet, /fund, /approve, /autoapprove, /generateapi, /balance, /solana
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application, CommandHandler

from core.services import user_service, balance_checker

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """
    PHASE 5: Streamlined welcome with state-aware UI
    Shows different flows based on user onboarding stage
    ENHANCED: Referral detection via deep link
    """
    user_id = update.effective_user.id
    username = update.effective_user.username or "Anonymous"

    try:
        # REFERRAL SYSTEM: Detect referral parameter from deep link
        referrer_username = None
        if context.args and len(context.args) > 0:
            referrer_username = context.args[0]
            logger.info(f"🔗 REFERRAL: User {user_id} accessed via link from @{referrer_username}")

        # Generate wallet for new user or get existing one
        user = user_service.create_user(telegram_user_id=user_id, username=username)

        if not user:
            await update.message.reply_text("❌ Error retrieving wallet data. Please try /start again.")
            return

        # REFERRAL SYSTEM: Process referral if present
        if referrer_username and user:
            from telegram_bot.services.referral_service import get_referral_service
            referral_service = get_referral_service()

            success, message = referral_service.create_referral(
                referrer_username=referrer_username,
                referred_user_id=user_id
            )

            if success:
                # Notify user they were referred
                await update.message.reply_text(
                    f"🎉 Welcome!\n\n"
                    f"You were referred by @{referrer_username}\n"
                    f"They'll earn commissions on your trades!\n\n"
                    f"Setting up your wallet...",
                    parse_mode='Markdown'
                )
                logger.info(f"✅ REFERRAL: Successfully linked {user_id} to @{referrer_username}")

        # PHASE 5: Detect user stage for state-aware UI
        from core.services.user_states import UserStateValidator, UserStage

        stage = UserStateValidator.get_user_stage(user)
        progress = UserStateValidator.get_user_progress_info(user)

        # PHASE 5: Show different UI based on stage
        if stage == UserStage.READY:
            # Fully set up - show quick actions
            await _show_ready_user_flow(update, user, username)

        elif stage == UserStage.SOL_GENERATED:
            # Has wallets, needs funding - show SOL address + bridge button
            await _show_new_user_flow(update, user, username, session_manager)

        elif stage in [UserStage.FUNDED, UserStage.APPROVED]:
            # In progress - show status + estimated time
            await _show_progress_flow(update, user, username, stage)

        else:
            # Fallback: CREATED stage (rare - auto-creates SOL wallet)
            await _show_new_user_flow(update, user, username, session_manager)

    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        error_text = f"❌ Error creating wallet: {str(e)}\n\nPlease try /start again or contact support."
        await update.message.reply_text(error_text, parse_mode='Markdown')


async def _show_new_user_flow(update: Update, user, username: str, session_manager):
    """
    PHASE 5: New user flow - show SOL address and bridge button
    For users at SOL_GENERATED stage (have wallets, need funding)
    """
    user_id = update.effective_user.id

    # Get SOL wallet info
    solana_address = user.solana_address
    if not solana_address:
        # Edge case: SOL wallet not created yet
        result = user_service.generate_solana_wallet(user_id)
        if result:
            solana_address, _ = result

    # Get SOL balance
    try:
        from solana_bridge.solana_transaction import SolanaTransactionBuilder
        solana_tx_builder = SolanaTransactionBuilder()
        sol_balance = await solana_tx_builder.get_sol_balance(solana_address)
    except Exception as e:
        logger.warning(f"Could not fetch SOL balance: {e}")
        sol_balance = 0.0

    balance_status = f"💰 Current Balance: {sol_balance:.4f} SOL" if sol_balance > 0 else ""

    welcome_text = f"""
🚀 WELCOME TO POLYMARKET BOT

👋 Hi @{username}!

📍 Your SOL Address:
`{solana_address}`
{balance_status}

Setup (3-5 mins):
1. Fund wallet with 0.1+ SOL (~$20)
2. We auto-bridge & approve
3. Start trading!

💡 Tap address above to copy
🔒 Non-custodial & secure
    """

    keyboard = []

    if sol_balance >= 0.1:
        # Has enough SOL - show bridge button
        keyboard.append([InlineKeyboardButton("🌉 I've Funded - Start Bridge", callback_data="start_streamlined_bridge")])
    else:
        # Not funded yet - show refresh button
        keyboard.append([InlineKeyboardButton("🔄 Check Balance", callback_data="refresh_sol_balance_start")])

    # 2-column layout for Wallet Details and Browse Markets
    keyboard.append([
        InlineKeyboardButton("💼 View Wallet Details", callback_data="show_wallet"),
        InlineKeyboardButton("📊 Browse Markets", callback_data="markets_page_0")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def _show_ready_user_flow(update: Update, user, username: str):
    """
    PHASE 5: Ready user flow - quick actions for trading
    For users at READY stage (fully set up)
    """
    polygon_address = user.polygon_address

    # Get balances
    try:
        from core.services import balance_checker
        usdc_balance, _ = balance_checker.check_usdc_balance(polygon_address)
        usdc_balance = f"{usdc_balance:.2f}" if isinstance(usdc_balance, (int, float)) else "Error"
    except Exception as e:
        logger.error(f"Error fetching balance: {e}")
        usdc_balance = "Error"

    welcome_text = f"""
👋 Welcome back, @{username}!

Status: ✅ READY TO TRADE

💼 Wallet: `{polygon_address}`
💰 Balance: ${usdc_balance} USDC

Quick Actions:
📊 Browse markets
📈 View positions  
📜 Transaction history
    """

    keyboard = [
        [
            InlineKeyboardButton("📊 Browse Markets", callback_data="markets_page_0"),
            InlineKeyboardButton("📊 View Positions", callback_data="view_positions")
        ],
        [
            InlineKeyboardButton("💼 Wallet Details", callback_data="show_wallet"),
            InlineKeyboardButton("📜 History", callback_data="show_history")
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def _show_progress_flow(update: Update, user, username: str, stage):
    """
    PHASE 5: Progress flow - show ongoing processes
    For users at FUNDED or APPROVED stage (setup in progress)
    """
    from core.services.user_states import UserStage

    if stage == UserStage.FUNDED:
        status_emoji = "⏳"
        status_text = "Bridge/Approval in Progress"
        detail_text = "⚡ Processing bridge and approving contracts...\n⏱️ Estimated: 2-3 minutes\n\nYour wallet will be ready soon!"
    elif stage == UserStage.APPROVED:
        status_emoji = "🔑"
        status_text = "Generating API Keys"
        detail_text = "🔑 Creating your API credentials...\n⏱️ Estimated: 30 seconds\n\nAlmost ready!"
    else:
        status_emoji = "🔧"
        status_text = "Setting Up"
        detail_text = "⚙️ Completing setup..."

    welcome_text = f"""
{status_emoji} SETUP IN PROGRESS

👤 @{username}

Status: {status_text}

{detail_text}

💡 Refresh this page in a minute to see updates!
    """

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Status", callback_data="refresh_start")],
        [InlineKeyboardButton("💼 View Wallet", callback_data="show_wallet")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


# OLD start_command preserved as backup (can be removed after testing)
async def start_command_old(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """OLD VERSION - kept as backup, can be removed after Phase 5 testing"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Anonymous"

    try:
        # Generate wallet for new user or get existing one
        # Create user with Polygon wallet
        user = user_service.create_user(telegram_user_id=user_id, username=username)

        if not user:
            await update.message.reply_text("❌ Error retrieving wallet data. Please try /start again.")
            return

        # Check wallet status
        wallet_ready, status_msg = user_service.is_wallet_ready(user_id)

        # Get wallet address
        address = user.polygon_address

        welcome_text = f"""
🚀 POLYMARKET V2 TRADING BOT
✨ Auto-Generated Personal Wallet

👤 Your Details:
• User: @{username}
• Telegram ID: {user_id}
• Wallet: `{address}`

🔑 Wallet Status:
{status_msg}

💰 Next Steps:
{_get_setup_steps(user_id)}

COMMANDS:
/search - 🔍 Search markets by keyword (NEW!)
/markets - Browse top volume markets
/positions - View & sell your positions
/balance - 💰 Check live balances (NEW!)
/wallet - View wallet details & private key
/fund - Get funding instructions
/approve - Handle contract approvals
/autoapprove - 🔥 One-click auto-approval (NEW!)
/generateapi - 🔑 Generate API keys (NEW!)
/help - Show all commands

YOUR PERSONAL TRADING WALLET IS READY! 🏎️💨
        """

        keyboard = [
            [InlineKeyboardButton("💼 View Wallet", callback_data="show_wallet")],
            [InlineKeyboardButton("💰 Fund Wallet", callback_data="show_funding")],
        ]

        # Add appropriate action buttons based on wallet status
        if user.funded:
            if not user.usdc_approved or not user.polymarket_approved:
                keyboard.append([InlineKeyboardButton("🔄 Auto-Approve Contracts", callback_data="auto_approve")])

            if not user.api_key:
                keyboard.append([InlineKeyboardButton("🔑 Generate API Keys", callback_data="generate_api")])

        keyboard.append([InlineKeyboardButton("📊 Browse Markets", callback_data="markets_page_0")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    except Exception as e:
        error_text = f"❌ Error creating wallet: {str(e)}\n\nPlease try /start again or contact support."
        await update.message.reply_text(error_text, parse_mode='Markdown')


def _get_setup_steps(user_id: int) -> str:
    """Get setup steps based on wallet status"""
    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        return "❌ No wallet found"

    steps = []
    if not wallet.get('funded', False):
        steps.append("1. 💰 Fund wallet with USDC.e + POL")
    if not wallet.get('usdc_approved', False):
        steps.append("2. ✅ Approve USDC.e spending")
    if not wallet.get('polymarket_approved', False):
        steps.append("3. ✅ Approve Polymarket contracts")

    if not steps:
        return "✅ Wallet ready for trading!"

    return "\n".join(steps)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help message"""
    help_text = """
📋 QUICK START

Trading
/markets - Browse markets
/search - Find specific markets
/category - Browse by topic

Portfolio
/positions - Your active trades
/pnl - Profit & loss
/tpsl - Auto sell rules

Advanced
/smart_trading - Follow experts
/copy_trading - Copy leaders

Wallet
/wallet - Balances & keys
/referral - Earn commissions

💡 Tap any command to use
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show wallet details with private key option and balances"""
    user_id = update.effective_user.id

    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        await update.message.reply_text(
            "❌ No wallet found!\n\nUse /start to create your wallet.",
            parse_mode='Markdown'
        )
        return

    # Get Polygon wallet info
    polygon_address = wallet['address']
    wallet_ready, status_msg = user_service.is_wallet_ready(user_id)

    # Get Solana wallet info
    # Generate Solana wallet if needed
    result = user_service.generate_solana_wallet(user_id)
    if result:
        solana_address, _ = result
    else:
        solana_address = user_service.get_solana_address(user_id)

    # Get balances
    try:
        usdc_balance, _ = balance_checker.check_usdc_balance(polygon_address)
        pol_balance, _ = balance_checker.check_pol_balance(polygon_address)
        usdc_balance = f"{usdc_balance:.2f}" if isinstance(usdc_balance, (int, float)) else "Error"
        pol_balance = f"{pol_balance:.4f}" if isinstance(pol_balance, (int, float)) else "Error"
    except Exception as e:
        logger.error(f"Error fetching Polygon balances: {e}")
        usdc_balance = "Error"
        pol_balance = "Error"

    # Get SOL balance
    try:
        from solana_bridge.solana_transaction import SolanaTransactionBuilder
        solana_tx_builder = SolanaTransactionBuilder()
        sol_balance = await solana_tx_builder.get_sol_balance(solana_address)
        sol_balance_str = f"{sol_balance:.4f}" if isinstance(sol_balance, (int, float)) else "Error"
    except Exception as e:
        logger.error(f"Error fetching SOL balance: {e}")
        sol_balance_str = "Error"

    wallet_text = f"""
💼 YOUR WALLETS

🔷 POLYGON WALLET
📍 Address: `{polygon_address}`
💰 Balances:
  • USDC.e: {usdc_balance}
  • POL: {pol_balance}

🔶 SOLANA WALLET
📍 Address: `{solana_address}`
💰 Balance:
  • SOL: {sol_balance_str}
    """

    keyboard = [
        [
            InlineKeyboardButton("🔑 Polygon Key", callback_data="show_polygon_key"),
            InlineKeyboardButton("🔑 Solana Key", callback_data="show_solana_key")
        ],
        [InlineKeyboardButton("🌉 Bridge SOL → USDC", callback_data="bridge_from_wallet")],
        [
            InlineKeyboardButton("💸 Withdraw SOL", callback_data="withdraw_sol"),
            InlineKeyboardButton("💸 Withdraw USDC", callback_data="withdraw_usdc")
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        wallet_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def funding_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show funding instructions"""
    user_id = update.effective_user.id

    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        await update.message.reply_text(
            "❌ No wallet found!\n\nUse /start to create your wallet.",
            parse_mode='Markdown'
        )
        return

    address = wallet['address']

    funding_text = f"""
💰 FUND YOUR WALLET

📍 Your Polygon Address:
`{address}`

🔹 Required Assets:
• USDC.e (for trading)
• POL (for gas fees ~3 POL)

🌉 Funding Options:

1️⃣ Bridge from Solana (RECOMMENDED)
• Use /solana to generate Solana wallet
• Use /bridge to bridge SOL → USDC.e + POL
• Automatic + includes gas refuel!

2️⃣ Direct Polygon Deposit
• Send USDC.e + POL directly to address above
• From exchange or another wallet
• Make sure to use Polygon network!

⚠️ IMPORTANT:
• USDC.e contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
• Use Polygon network (not Ethereum!)
• Keep ~3 POL for gas fees
    """

    keyboard = [
        [InlineKeyboardButton("🌉 Bridge from Solana", callback_data="fund_bridge_solana")],
        [InlineKeyboardButton("💰 Check Balance", callback_data="check_balance")],
        [InlineKeyboardButton("✅ Mark as Funded", callback_data="mark_funded")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        funding_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show approval instructions"""
    user_id = update.effective_user.id

    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        await update.message.reply_text(
            "❌ No wallet found!\n\nUse /start to create your wallet.",
            parse_mode='Markdown'
        )
        return

    if not wallet.get('funded', False):
        await update.message.reply_text(
            "⚠️ Wallet not funded yet!\n\nPlease fund your wallet first.",
            parse_mode='Markdown'
        )
        return

    approve_text = """
✅ CONTRACT APPROVALS

Before trading, you need to approve 2 contracts:

1️⃣ USDC.e Spending
• Allows Polymarket to use your USDC.e
• One-time approval
• ~0.01 POL gas fee

2️⃣ Polymarket Contracts (SetApprovalForAll)
• Allows trading position tokens
• One-time approval
• ~0.01 POL gas fee

🔥 QUICK OPTION:
Use /autoapprove for automatic approval!

⚠️ Manual Approval:
Use Polygonscan or Metamask if needed.
    """

    keyboard = [
        [InlineKeyboardButton("🔥 Auto-Approve (Recommended)", callback_data="auto_approve")],
        [InlineKeyboardButton("✅ Check Approval Status", callback_data="check_approvals")],
        [InlineKeyboardButton("📝 Mark USDC Approved", callback_data="mark_usdc_approved")],
        [InlineKeyboardButton("📝 Mark Polymarket Approved", callback_data="mark_poly_approved")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        approve_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def auto_approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-approve contracts command"""
    user_id = update.effective_user.id

    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        await update.message.reply_text(
            "❌ No wallet found!\n\nUse /start to create your wallet.",
            parse_mode='Markdown'
        )
        return

    if not wallet.get('funded', False):
        await update.message.reply_text(
            "⚠️ Wallet not funded yet!\n\nPlease fund your wallet first.",
            parse_mode='Markdown'
        )
        return

    auto_text = """
🔥 AUTO-APPROVAL SERVICE

✨ What it does:
• Automatically approves USDC.e spending
• Automatically approves Polymarket contracts
• Waits for unfunded wallets and auto-approves when funded

⚡ How it works:
1. Click "Enable Auto-Approval" below
2. When your wallet gets funded, approvals happen automatically
3. No manual intervention needed!

💰 Gas fees: ~0.02 POL total (paid from your wallet)

⏱️ Processing: Usually 30-60 seconds after funding

🔒 Safe: Uses your wallet's private key securely
    """

    keyboard = [
        [InlineKeyboardButton("✅ Enable Auto-Approval", callback_data="auto_approve")],
        [InlineKeyboardButton("📊 Check Status", callback_data="check_approvals")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        auto_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def generate_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate API credentials command"""
    user_id = update.effective_user.id

    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        await update.message.reply_text(
            "❌ No wallet found!\n\nUse /start to create your wallet.",
            parse_mode='Markdown'
        )
        return

    if not wallet.get('funded', False):
        await update.message.reply_text(
            "⚠️ Wallet not funded yet!\n\nPlease fund your wallet first.",
            parse_mode='Markdown'
        )
        return

    api_text = """
🔑 GENERATE API CREDENTIALS

✨ Why you need this:
• Faster order placement
• Better rate limits
• Enhanced trading features
• Required for high-volume trading

⚡ What happens:
1. Bot generates API key, secret, and passphrase
2. Credentials are securely stored
3. Used automatically for all trades
4. Can regenerate anytime

🔒 Security:
• Keys stored encrypted
• Never shared
• Used only for your trades

💡 One-click generation!
    """

    keyboard = [
        [InlineKeyboardButton("🔑 Generate Credentials", callback_data="generate_api")],
        [InlineKeyboardButton("🧪 Test Credentials", callback_data="test_api_credentials")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        api_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check live wallet balances"""
    user_id = update.effective_user.id

    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        await update.message.reply_text(
            "❌ No wallet found!\n\nUse /start to create your wallet.",
            parse_mode='Markdown'
        )
        return

    address = wallet['address']

    # Send checking message
    checking_msg = await update.message.reply_text("🔍 Checking balances...", parse_mode='Markdown')

    try:
        # Get live balances
        balances = balance_checker.check_balance(address)

        usdc_balance = balances.get('usdc', 0)
        pol_balance = balances.get('pol', 0)

        # Determine status
        is_funded = usdc_balance > 0 and pol_balance >= 1.0
        status_emoji = "✅" if is_funded else "⚠️"

        balance_text = f"""💰 WALLET BALANCES

📍 Address: `{address}`

💵 USDC.e Balance:
{usdc_balance:.2f} USDC

⛽ POL Balance:
{pol_balance:.4f} POL

{status_emoji} Status:
"""

        if is_funded:
            balance_text += "✅ Wallet is funded and ready for trading!"
        else:
            if usdc_balance == 0:
                balance_text += "⚠️ No USDC.e found - deposit required for trading"
            if pol_balance < 1.0:
                balance_text += "\n⚠️ Low POL - you need gas fees (~3 POL recommended)"

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="check_balance")],
            [InlineKeyboardButton("💰 Fund Wallet", callback_data="show_funding")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await checking_msg.edit_text(
            balance_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Balance check error: {e}")
        await checking_msg.edit_text(
            f"❌ Error checking balance: {str(e)}\n\nPlease try again later.",
            parse_mode='Markdown'
        )


async def solana_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and show Solana wallet for bridging"""
    user_id = update.effective_user.id

    try:
        # Generate or retrieve Solana wallet
        result = user_service.generate_solana_wallet(user_id)
        if not result:
            await update.message.reply_text("❌ Failed to generate Solana wallet. Please use /start first.")
            return
        solana_address, solana_private_key = result

        solana_text = f"""
🌐 YOUR SOLANA WALLET

📍 Solana Address:
`{solana_address}`

🌉 Use for Bridging:
This Solana wallet is linked to your Polygon wallet for easy bridging.

💡 Next Steps:
1. Send SOL to this address
2. Use /bridge to bridge SOL → USDC.e + POL
3. Funds arrive on Polygon automatically!

⚡ Bridge Features:
• Instant USDC.e conversion
• Auto gas refuel (~3 POL)
• All-in-one solution

🔑 Security:
Your Solana key is stored securely and used only for bridging operations.
        """

        keyboard = [
            [InlineKeyboardButton("🔑 Show Private Key", callback_data="show_solana_key")],
            [InlineKeyboardButton("🌉 Bridge SOL", callback_data="fund_bridge_solana")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            solana_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Solana wallet generation error: {e}")
        await update.message.reply_text(
            f"❌ Error: {str(e)}\n\nPlease try again or contact support.",
            parse_mode='Markdown'
        )


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """
    COMPLETE account deletion for testing (PHASE 3)
    Deletes user entirely - test as a brand new user
    """
    user_id = update.effective_user.id

    try:
        # Check if user exists
        user = user_service.get_user(user_id)

        if not user:
            await update.message.reply_text(
                "❌ No account found\n\nUse /start to create one.",
                parse_mode='Markdown'
            )
            return

        # Show confirmation dialog
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Delete Everything", callback_data=f"confirm_restart_{user_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_restart")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        current_stage_info = ""
        try:
            from core.services.user_states import UserStateValidator
            stage = UserStateValidator.get_user_stage(user)
            current_stage_info = f"\n\n📊 Current Status: {stage.display_name} ({stage.progress_percentage}%)"
        except:
            pass

        await update.message.reply_text(
            f"⚠️ DELETE ACCOUNT?\n\n"
            f"This will COMPLETELY DELETE:\n"
            f"• All wallets (Polygon + SOL)\n"
            f"• All wallet keys\n"
            f"• Funding status\n"
            f"• Approvals\n"
            f"• API keys\n"
            f"• Transaction history\n"
            f"• Everything!\n"
            f"{current_stage_info}\n\n"
            f"🔥 You'll start completely fresh!\n"
            f"Perfect for testing as a brand new user.\n\n"
            f"⚠️ Warning: This cannot be undone!\n\n"
            f"Are you sure?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Restart command error: {e}")
        await update.message.reply_text(
            f"❌ Error: {str(e)}",
            parse_mode='Markdown'
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE, session_manager):
    """
    NEW: Cancel current operation and clear state
    """
    user_id = update.effective_user.id

    # Get session and clear state
    session = session_manager.get(user_id)
    if session:
        return_page = session.get('return_page', 0)
        session['state'] = None
        session['pending_order'] = None
        session['pending_trade'] = None

        await update.message.reply_text(
            "❌ Operation cancelled.\n\nUse /markets to browse markets or /positions to view your holdings.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("Nothing to cancel.")


def register(app: Application, session_manager):
    """Register all setup command handlers"""
    from functools import partial

    # Bind session_manager to start_command
    start_with_session = partial(start_command, session_manager=session_manager)
    restart_with_session = partial(restart_command, session_manager=session_manager)
    cancel_with_session = partial(cancel_command, session_manager=session_manager)

    app.add_handler(CommandHandler("start", start_with_session))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("fund", funding_command))
    app.add_handler(CommandHandler("autoapprove", auto_approve_command))
    app.add_handler(CommandHandler("generateapi", generate_api_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("restart", restart_with_session))  # PHASE 3: New command
    app.add_handler(CommandHandler("cancel", cancel_with_session))  # NEW: Cancel operation

    logger.info("✅ Setup handlers registered (including /restart and /cancel)")
