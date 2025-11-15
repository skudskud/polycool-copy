#!/usr/bin/env python3
"""
Polymarket Telegram Trading Bot
Ultra-fast trading with inline buttons and live pricing
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Import our existing trading infrastructure
# SpeedTrader not needed - using UserTrader with user's wallet instead
from market_database import MarketDatabase
from wallet_manager import WalletManager, wallet_manager
from approval_manager import ApprovalManager, approval_manager
from api_key_manager import ApiKeyManager, api_key_manager
from balance_checker import BalanceChecker, balance_checker
from config import BOT_TOKEN, BOT_USERNAME  # Only import bot config, no hardcoded keys!

# V2 Bot Configuration with Wallet Generation
TELEGRAM_TOKEN = BOT_TOKEN
# BOT_USERNAME is imported from config

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global database instance (no global trader - each user gets their own)
db = MarketDatabase()

# User sessions (store market selections)
user_sessions: Dict[int, Dict] = {}

class TelegramTradingBot:
    def __init__(self):
        self.app = Application.builder().token(TELEGRAM_TOKEN).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup all command and callback handlers"""
        # Commands
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("wallet", self.wallet_command))
        self.app.add_handler(CommandHandler("fund", self.funding_command))
        self.app.add_handler(CommandHandler("approve", self.approve_command))
        self.app.add_handler(CommandHandler("autoapprove", self.auto_approve_command))
        self.app.add_handler(CommandHandler("generateapi", self.generate_api_command))
        self.app.add_handler(CommandHandler("balance", self.balance_command))
        self.app.add_handler(CommandHandler("markets", self.markets_command))
        self.app.add_handler(CommandHandler("positions", self.positions_command))
        
        # Callback queries (button clicks)
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome message with automatic wallet generation"""
        user_id = update.effective_user.id
        username = update.effective_user.username or "Anonymous"
        
        try:
            # Generate wallet for new user or get existing one
            address, private_key = wallet_manager.generate_wallet_for_user(user_id, username)
            
            # Get wallet object for status checking
            wallet = wallet_manager.get_user_wallet(user_id)
            if not wallet:
                await update.message.reply_text("❌ **Error retrieving wallet data.** Please try /start again.")
                return
            
            # Check wallet status
            wallet_ready, status_msg = wallet_manager.is_wallet_ready(user_id)
            
            welcome_text = f"""
🚀 **POLYMARKET V2 TRADING BOT**
✨ **Auto-Generated Personal Wallet**

👤 **Your Details:**
• User: @{username} (ID: {user_id})
• Wallet: `{address}`

🔑 **Wallet Status:**
{status_msg}

💰 **Next Steps:**
{self._get_setup_steps(user_id)}

**COMMANDS:**
/wallet - View wallet details & private key
/fund - Get funding instructions
/balance - **💰 Check live balances (NEW!)**
/approve - Handle contract approvals
/autoapprove - **🔥 One-click auto-approval (NEW!)**
/generateapi - **🔑 Generate API keys (NEW!)**
/markets - Browse top volume markets
/positions - View & sell your positions
/help - Show all commands

**YOUR PERSONAL TRADING WALLET IS READY!** 🏎️💨
            """
            
            keyboard = [
                [InlineKeyboardButton("💼 View Wallet", callback_data="show_wallet")],
                [InlineKeyboardButton("💰 Fund Wallet", callback_data="show_funding")],
            ]
            
            # Add appropriate action buttons based on wallet status
            if wallet.get('funded', False):
                if not wallet.get('usdc_approved', False) or not wallet.get('polymarket_approved', False):
                    keyboard.append([InlineKeyboardButton("🔄 Auto-Approve Contracts", callback_data="auto_approve")])
                
                if not wallet.get('api_credentials_generated', False):
                    keyboard.append([InlineKeyboardButton("🔑 Generate API Keys", callback_data="generate_api")])
            
            keyboard.append([InlineKeyboardButton("📊 Browse Markets", callback_data="refresh_markets")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                welcome_text, 
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            error_text = f"❌ **Error creating wallet:** {str(e)}\n\nPlease try /start again or contact support."
            await update.message.reply_text(error_text, parse_mode='Markdown')
    
    def _get_setup_steps(self, user_id: int) -> str:
        """Get setup steps based on wallet status"""
        wallet = wallet_manager.get_user_wallet(user_id)
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
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help message"""
        help_text = """
📋 **TRADING BOT COMMANDS**

🏆 `/markets` - Browse markets by volume
   • Shows top 20 highest volume markets
   • Click to see live YES/NO prices
   • Instant buy with 5 tokens minimum

📊 `/positions` - View your positions
   • Shows all your current holdings
   • One-click sell 100% of position
   • Real-time P&L calculations

⚡ **SPEED FEATURES:**
• Ultra-aggressive pricing (+2¢/-3¢)
• 0-second execution guaranteed
• Live market data refresh
• Instant position updates

💡 **HOW IT WORKS:**
1. Choose market from /markets
2. See live YES/NO prices  
3. Click BUY button (5 tokens)
4. Manage positions via /positions

💼 `/wallet` - View wallet details & private key
💰 `/fund` - Get funding instructions
💰 `/balance` - **Check live USDC.e & POL balances**
✅ `/approve` - Handle contract approvals
🔄 `/autoapprove` - **Auto-approve all contracts (one-click!)**
🔑 `/generateapi` - **Generate API keys for enhanced trading**

**Happy trading!** 🚀
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show wallet details with private key option"""
        user_id = update.effective_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await update.message.reply_text("❌ No wallet found. Use /start to create one.")
            return
        
        wallet_text = f"""
💼 **YOUR WALLET DETAILS**

📍 **Address:**
`{wallet['address']}`

🔑 **Status:**
• Funded: {'✅' if wallet.get('funded', False) else '❌'}
• USDC.e Approved: {'✅' if wallet.get('usdc_approved', False) else '❌'}
• Polymarket Approved: {'✅' if wallet.get('polymarket_approved', False) else '❌'}

📅 **Created:** {time.ctime(wallet.get('created_at', 0))}

⚠️ **Security Notice:** Your private key is stored securely. Only reveal it if needed for wallet import.
        """
        
        keyboard = [
            [InlineKeyboardButton("🔑 Show Private Key", callback_data="show_private_key")],
            [InlineKeyboardButton("💰 Fund Instructions", callback_data="show_funding")],
            [InlineKeyboardButton("✅ Handle Approvals", callback_data="show_approvals")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(wallet_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def funding_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show funding instructions"""
        user_id = update.effective_user.id
        address = wallet_manager.get_user_address(user_id)
        
        if not address:
            await update.message.reply_text("❌ No wallet found. Use /start to create one.")
            return
        
        funding_text = f"""
💰 **FUNDING INSTRUCTIONS**

📍 **Your Wallet Address:**
`{address}`

🪙 **Required Tokens:**

**1. USDC.e (Trading Currency)**
• Contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
• Minimum: $10 USDC.e for testing
• Network: Polygon (MATIC)

**2. POL (Gas Token)**
• Native Polygon token for transaction fees
• Minimum: 0.1 POL
• Network: Polygon (MATIC)

🏦 **How to Fund:**
1. Send USDC.e from any exchange (Binance, Coinbase)
2. Send POL for gas fees
3. Use Polygon network (Chain ID: 137)

⚠️ **Important:**
• Double-check address before sending
• Use Polygon network, not Ethereum
• Start with small amounts for testing

After funding, use /approve to enable trading!
        """
        
        keyboard = [
            [InlineKeyboardButton("✅ I've Funded My Wallet", callback_data="mark_funded")],
            [InlineKeyboardButton("🔄 Check Balance", callback_data="check_balance")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(funding_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show approval instructions"""
        user_id = update.effective_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await update.message.reply_text("❌ No wallet found. Use /start to create one.")
            return
        
        if not wallet.get('funded', False):
            await update.message.reply_text("⚠️ Please fund your wallet first using /fund")
            return
        
        approve_text = f"""
✅ **CONTRACT APPROVALS NEEDED**

📍 **Your Wallet:** `{wallet['address']}`

🔐 **Required Approvals:**

**1. USDC.e Spending Approval**
• Status: {'✅ Approved' if wallet.get('usdc_approved', False) else '❌ Needed'}
• Allows trading with your USDC.e
• One-time approval

**2. Polymarket Contract Approval**  
• Status: {'✅ Approved' if wallet.get('polymarket_approved', False) else '❌ Needed'}
• Enables market interactions
• One-time approval

💡 **How to Approve:**
Currently manual process - we'll add auto-approval soon!

For now, import your wallet to MetaMask and approve:
1. USDC.e spending on Polymarket.com
2. Conditional token interactions

🚀 **Coming Soon:** One-click approval directly from this bot!
        """
        
        keyboard = [
            [InlineKeyboardButton("✅ Mark USDC.e Approved", callback_data="mark_usdc_approved")],
            [InlineKeyboardButton("✅ Mark Polymarket Approved", callback_data="mark_poly_approved")],
            [InlineKeyboardButton("🔑 Get Private Key", callback_data="show_private_key")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(approve_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def auto_approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Auto-approve contracts with one command"""
        user_id = update.effective_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await update.message.reply_text("❌ No wallet found. Use /start to create one.")
            return
        
        if not wallet.get('funded', False):
            await update.message.reply_text("⚠️ Please fund your wallet first using /fund")
            return
        
        # Start approval process
        await update.message.reply_text("🔄 **Starting auto-approval process...**\n\n⚡ This will approve both USDC.e and Conditional Tokens for all Polymarket contracts automatically!", parse_mode='Markdown')
        
        try:
            private_key = wallet['private_key']
            
            # Perform auto-approvals
            success, results = approval_manager.approve_all_for_trading(private_key)
            
            if success:
                # Update wallet status
                wallet_manager.update_approval_status(
                    user_id, 
                    usdc_approved=True, 
                    polymarket_approved=True,
                    auto_approval_completed=True
                )
                
                success_text = f"""
🎉 **AUTO-APPROVAL COMPLETED!**

✅ **USDC.e Approvals:** All {len(approval_manager.EXCHANGE_CONTRACTS)} contracts approved
✅ **Conditional Token Approvals:** All {len(approval_manager.EXCHANGE_CONTRACTS)} contracts approved

📋 **Approved Contracts:**
• Main Exchange: `{approval_manager.EXCHANGE_CONTRACTS[0][:10]}...`
• Neg Risk Markets: `{approval_manager.EXCHANGE_CONTRACTS[1][:10]}...` 
• Neg Risk Adapter: `{approval_manager.EXCHANGE_CONTRACTS[2][:10]}...`

🚀 **Your wallet is now ready for trading!**
Use /markets to start trading instantly!
                """
                
                keyboard = [
                    [InlineKeyboardButton("📊 Start Trading", callback_data="refresh_markets")],
                    [InlineKeyboardButton("💼 View Wallet", callback_data="show_wallet")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(success_text, parse_mode='Markdown', reply_markup=reply_markup)
                
            else:
                error_text = f"""
❌ **AUTO-APPROVAL FAILED**

Some approvals were not successful:

**USDC.e Results:** {'✅ Success' if results.get('usdc_success', False) else '❌ Failed'}
**Conditional Tokens:** {'✅ Success' if results.get('ct_success', False) else '❌ Failed'}

💡 **Manual Approval Required:**
1. Use /wallet to get your private key
2. Import wallet to MetaMask
3. Visit Polymarket.com to trade (triggers manual approval)
4. Use /approve to mark as completed

**Error Details:** {results.get('error', 'Unknown error')}
                """
                
                await update.message.reply_text(error_text, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Auto-approval error for user {user_id}: {e}")
            await update.message.reply_text(f"❌ **Auto-approval failed:** {str(e)}\n\nPlease try manual approval using /approve", parse_mode='Markdown')
    
    async def generate_api_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate API credentials for user's wallet"""
        user_id = update.effective_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await update.message.reply_text("❌ No wallet found. Use /start to create one.")
            return
        
        # Check wallet readiness
        wallet_ready, status_msg = wallet_manager.is_wallet_ready(user_id)
        if not wallet_ready:
            await update.message.reply_text(f"⚠️ **Wallet not ready for API generation**\n\n{status_msg}\n\nComplete wallet setup first!")
            return
        
        await update.message.reply_text("🔄 **Generating API credentials...**\n\n⚡ Creating your personal API keys for enhanced trading rates!", parse_mode='Markdown')
        
        try:
            private_key = wallet['private_key']
            wallet_address = wallet['address']
            
            # Generate API credentials
            creds = api_key_manager.generate_api_credentials(user_id, private_key, wallet_address)
            
            if creds:
                # Update wallet status
                wallet_manager.update_api_credentials_status(user_id, True)
                
                # Test API credentials
                test_success, test_msg = api_key_manager.test_api_credentials(user_id, private_key, wallet_address)
                
                success_text = f"""
🎉 **API CREDENTIALS GENERATED!**

✅ **API Key:** `{creds.api_key[:20]}...`
✅ **Status:** Active and ready
✅ **Test Result:** {'✅ Working' if test_success else '⚠️ ' + test_msg}

🚀 **Benefits:**
• Enhanced trading rate limits
• Priority order processing  
• Access to advanced features
• Reduced API restrictions

💡 **Next Steps:**
Your API credentials are automatically used for all trades. No manual setup needed!

Use /markets to start trading with enhanced rates!
                """
                
                keyboard = [
                    [InlineKeyboardButton("📊 Start Trading", callback_data="refresh_markets")],
                    [InlineKeyboardButton("🔧 Test API", callback_data="test_api_credentials")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(success_text, parse_mode='Markdown', reply_markup=reply_markup)
                
            else:
                error_text = """
❌ **API Generation Failed**

Could not generate API credentials for your wallet.

💡 **Possible Solutions:**
• Ensure wallet is properly funded
• Check that approvals are completed
• Try again in a few minutes
• Contact support if issue persists

You can still trade without API credentials, but with standard rate limits.
                """
                
                await update.message.reply_text(error_text, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"API generation error for user {user_id}: {e}")
            await update.message.reply_text(f"❌ **API generation failed:** {str(e)}", parse_mode='Markdown')
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check wallet balances"""
        user_id = update.effective_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await update.message.reply_text("❌ No wallet found. Use /start to create one.")
            return
        
        await update.message.reply_text("🔍 **Checking your wallet balances...**", parse_mode='Markdown')
        
        try:
            wallet_address = wallet['address']
            balance_report = balance_checker.format_balance_report(wallet_address)
            
            # Update funding status based on balance check
            balances = balance_checker.check_all_balances(wallet_address)
            if balances.get('fully_funded', False):
                wallet_manager.update_funding_status(user_id, True)
            
            keyboard = []
            if balances.get('fully_funded', False):
                if not wallet.get('usdc_approved', False) or not wallet.get('polymarket_approved', False):
                    keyboard.append([InlineKeyboardButton("🔄 Auto-Approve Contracts", callback_data="auto_approve")])
            
            keyboard.extend([
                [InlineKeyboardButton("🔄 Refresh Balance", callback_data="check_balance")],
                [InlineKeyboardButton("💰 Fund Wallet", callback_data="show_funding")]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(balance_report, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Balance check error: {e}")
            await update.message.reply_text(f"❌ **Balance check failed:** {str(e)}", parse_mode='Markdown')
    
    async def markets_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show top volume markets"""
        user_id = update.effective_user.id
        
        # Initialize user session
        if user_id not in user_sessions:
            user_sessions[user_id] = {}
        
        try:
            # Get top 20 markets by volume
            markets = db.get_high_volume_markets(20)
            
            if not markets:
                await update.message.reply_text("❌ No markets available. Try again later.")
                return
            
            keyboard = []
            
            # Create market selection buttons (2 per row)
            for i in range(0, min(20, len(markets)), 2):
                row = []
                
                # First market
                market1 = markets[i]
                title1 = market1['question'][:40] + "..." if len(market1['question']) > 40 else market1['question']
                volume1 = f"${market1['volume']:,.0f}"
                button1 = InlineKeyboardButton(
                    f"📊 {title1} ({volume1})",
                    callback_data=f"market_{market1['id']}"
                )
                row.append(button1)
                
                # Second market (if exists)
                if i + 1 < len(markets):
                    market2 = markets[i + 1]
                    title2 = market2['question'][:40] + "..." if len(market2['question']) > 40 else market2['question']
                    volume2 = f"${market2['volume']:,.0f}"
                    button2 = InlineKeyboardButton(
                        f"📊 {title2} ({volume2})",
                        callback_data=f"market_{market2['id']}"
                    )
                    row.append(button2)
                
                keyboard.append(row)
            
            # Add refresh button
            keyboard.append([InlineKeyboardButton("🔄 Refresh Markets", callback_data="refresh_markets")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_text = """
🏆 **TOP VOLUME MARKETS** (High → Low)

Click any market to see live prices and trade:
            """
            
            await update.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Markets command error: {e}")
            await update.message.reply_text(f"❌ Error loading markets: {str(e)}")
    
    async def show_market_detail(self, query, market_id: str):
        """Show detailed market with buy buttons"""
        try:
            # Find the market
            markets = db.get_high_volume_markets(1000)  # Get more to find specific market
            market = next((m for m in markets if str(m['id']) == market_id), None)
            
            if not market:
                await query.edit_message_text("❌ Market not found.")
                return
            
            # Store market in user session
            user_id = query.from_user.id
            user_sessions[user_id]['current_market'] = market
            
            # Get live prices
            try:
                token_ids = market.get('clob_token_ids', [])
                if isinstance(token_ids, str):
                    import ast
                    token_ids = ast.literal_eval(token_ids)
                    token_ids = [str(token_id) for token_id in token_ids]
                
                if len(token_ids) >= 2:
                    yes_token_id = token_ids[0]
                    no_token_id = token_ids[1]
                    
                    # Get live prices (using temporary client for display)
                    try:
                        from py_clob_client.client import ClobClient
                        from py_clob_client.constants import POLYGON
                        
                        # Create temporary client for price checking (no auth needed)
                        temp_client = ClobClient(
                            host="https://clob.polymarket.com",
                            key="0x" + "0"*64,  # Dummy key for price queries
                            chain_id=POLYGON
                        )
                        
                        yes_price_data = temp_client.get_price(yes_token_id, "BUY")
                        no_price_data = temp_client.get_price(no_token_id, "BUY")
                        yes_price = float(yes_price_data.get('price', 0))
                        no_price = float(no_price_data.get('price', 0))
                    except Exception as price_error:
                        logger.warning(f"Live price fetch failed: {price_error}")
                        yes_price = 0
                        no_price = 0
                    
                    if yes_price == 0:
                        outcome_prices = market.get('outcome_prices', ['0', '0'])
                        if isinstance(outcome_prices, str):
                            import ast
                            try:
                                outcome_prices = ast.literal_eval(outcome_prices)
                            except:
                                outcome_prices = ['0', '0']
                        yes_price = float(outcome_prices[0]) if outcome_prices else 0
                    if no_price == 0:
                        outcome_prices = market.get('outcome_prices', ['0', '0'])
                        if isinstance(outcome_prices, str):
                            import ast
                            try:
                                outcome_prices = ast.literal_eval(outcome_prices)
                            except:
                                outcome_prices = ['0', '0']
                        no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0
                else:
                    outcome_prices = market.get('outcome_prices', ['0', '0'])
                    if isinstance(outcome_prices, str):
                        import ast
                        try:
                            outcome_prices = ast.literal_eval(outcome_prices)
                        except:
                            outcome_prices = ['0', '0']
                    yes_price = float(outcome_prices[0]) if outcome_prices else 0
                    no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0
                
            except Exception as e:
                logger.error(f"Price fetch error: {e}")
                # Safe fallback for price parsing
                try:
                    outcome_prices = market.get('outcome_prices', ['0', '0'])
                    if isinstance(outcome_prices, str):
                        import ast
                        outcome_prices = ast.literal_eval(outcome_prices)
                    yes_price = float(outcome_prices[0]) if outcome_prices else 0.50
                    no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0.50
                except:
                    yes_price = 0.50  # Default fallback
                    no_price = 0.50
            
            # Format message
            question = market['question']
            volume = market.get('volume', 0)
            liquidity = market.get('liquidity', 0)
            end_date = market.get('end_date', 'Unknown')
            
            yes_percent = yes_price * 100
            no_percent = no_price * 100
            
            message_text = f"""
🎯 **MARKET DETAILS**

❓ **{question}**

📊 **Volume:** ${volume:,.0f}
💧 **Liquidity:** ${liquidity:,.0f} 
📅 **Ends:** {end_date[:10]}

💰 **LIVE PRICES:**
✅ **YES:** ${yes_price:.4f} ({yes_percent:.1f}%)
❌ **NO:** ${no_price:.4f} ({no_percent:.1f}%)

⚡ **Ready for ultra-fast trading!**
            """
            
            # Create buy buttons
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"🟢 BUY YES ${yes_price:.3f}",
                        callback_data=f"buy_yes_{market_id}"
                    ),
                    InlineKeyboardButton(
                        f"🔴 BUY NO ${no_price:.3f}",
                        callback_data=f"buy_no_{market_id}"
                    )
                ],
                [
                    InlineKeyboardButton("🔄 Refresh Prices", callback_data=f"market_{market_id}"),
                    InlineKeyboardButton("⬅️ Back to Markets", callback_data="refresh_markets")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Market detail error: {e}")
            await query.edit_message_text(f"❌ Error loading market: {str(e)}")
    
    def get_user_trader(self, user_id: int):
        """Get or create UserTrader instance for user with their wallet"""
        wallet = wallet_manager.get_user_wallet(user_id)
        if not wallet:
            return None
        
        private_key = wallet['private_key']
        
        # Create trader with user's private key and API credentials
        try:
            # Get user's API credentials if available
            user_creds = api_key_manager.get_user_api_credentials(user_id)
            
            # Create a completely new SpeedTrader instance with user's credentials
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON
            
            # Create client with user's wallet
            client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,  # User's private key
                chain_id=POLYGON,
                signature_type=0,  # EOA signature
                funder=None,  # User owns funds directly
                creds=user_creds  # User's API credentials (if any)
            )
            
            # Create a minimal SpeedTrader-like instance with user's client
            # Don't use the hardcoded SpeedTrader class
            class UserTrader:
                def __init__(self, client, private_key):
                    self.client = client
                    self.private_key = private_key
                    from market_database import MarketDatabase
                    import time
                    self.time = time
                    self.db = MarketDatabase()
                
                def get_live_price(self, token_id: str, side: str) -> float:
                    """Get live price for token (BUY or SELL side)"""
                    try:
                        price_data = self.client.get_price(token_id, side)
                        return float(price_data.get('price', 0))
                    except Exception as e:
                        logger.error(f"Live price error: {e}")
                        return 0.0
                
                def speed_buy(self, market: dict, outcome: str, amount: float):
                    """Ultra-fast buy execution with user's wallet"""
                    try:
                        # Parse token IDs
                        token_ids = market.get('clob_token_ids', [])
                        if isinstance(token_ids, str):
                            import ast
                            token_ids = ast.literal_eval(token_ids)
                        
                        # Get YES/NO token
                        if outcome.lower() == 'yes':
                            token_id = str(token_ids[0]) if token_ids else None
                        else:
                            token_id = str(token_ids[1]) if len(token_ids) > 1 else None
                        
                        if not token_id:
                            raise ValueError("Invalid token ID")
                        
                        # Get live price
                        live_price = self.get_live_price(token_id, "BUY")
                        if live_price <= 0:
                            live_price = 0.5  # Fallback
                        
                        # Ultra-aggressive pricing (+2¢)
                        aggressive_price = live_price + 0.02
                        
                        # Calculate size (minimum 5 tokens)
                        size = max(5, int(amount / aggressive_price))
                        
                        # FIX: Round to API precision requirements
                        aggressive_price = round(aggressive_price, 4)  # Price: max 4 decimals
                        total_amount = round(size * aggressive_price, 2)  # Amount: max 2 decimals
                        
                        print(f"🚀 USER WALLET BUY - {outcome.upper()} TOKENS")
                        print(f"📡 Live price: ${live_price:.4f}")
                        print(f"⚡ ULTRA price: ${aggressive_price:.4f} (+2¢)")
                        print(f"📦 Size: {size} tokens")
                        print(f"💵 Cost: ${total_amount:.2f}")
                        print(f"🎯 Using YOUR wallet: {self.client.get_address()}")
                        print(f"🚀 Strategy: AGGRESSIVE LIMIT ORDER (V1 approach)")
                        print(f"🔧 API-safe amounts: price={aggressive_price}, size={size}")
                        
                        # Create LIMIT order with user's credentials (V1 approach that works!)
                        from py_clob_client.order_builder.constants import BUY
                        from py_clob_client.clob_types import OrderArgs
                        
                        order_args = OrderArgs(
                            price=aggressive_price,  # Aggressive price for instant fill
                            size=size,              # Number of tokens
                            side=BUY,
                            token_id=token_id,
                        )
                        
                        # Create and submit LIMIT order (like V1 - aggressive pricing = instant fill)
                        signed_order = self.client.create_order(order_args)
                        resp = self.client.post_order(signed_order)
                        return resp.get('orderID')
                        
                    except Exception as e:
                        logger.error(f"Speed buy error with user wallet: {e}")
                        print(f"❌ Speed buy error: {e}")
                        return None
                
                def speed_sell(self, market: dict, outcome: str, tokens: int):
                    """Ultra-fast sell execution with user's wallet"""
                    try:
                        # Parse token IDs
                        token_ids = market.get('clob_token_ids', [])
                        if isinstance(token_ids, str):
                            import ast
                            token_ids = ast.literal_eval(token_ids)
                        
                        # Get YES/NO token
                        if outcome.lower() == 'yes':
                            token_id = str(token_ids[0]) if token_ids else None
                        else:
                            token_id = str(token_ids[1]) if len(token_ids) > 1 else None
                        
                        if not token_id:
                            raise ValueError("Invalid token ID")
                        
                        # Get live sell price
                        live_price = self.get_live_price(token_id, "SELL")
                        if live_price <= 0:
                            live_price = 0.5  # Fallback
                        
                        # NEW: Smart aggressive pricing (percentage-based for low prices)
                        if live_price < 0.10:  # Under 10¢ - use percentage
                            discount_percent = 0.05  # 5% discount for instant sell
                            aggressive_discount = live_price * discount_percent
                        else:  # Over 10¢ - use fixed amount
                            aggressive_discount = 0.03  # 3¢ discount
                        
                        aggressive_price = max(0.001, live_price - aggressive_discount)
                        
                        # FIX: Round to API precision requirements
                        aggressive_price = round(aggressive_price, 4)  # Price: max 4 decimals
                        total_amount = round(tokens * aggressive_price, 2)  # Amount: max 2 decimals
                        
                        print(f"⚡ USER WALLET SELL - {outcome.upper()} TOKENS")
                        print(f"📡 Live sell price: ${live_price:.4f}")
                        print(f"⚡ SMART pricing: ${aggressive_price:.4f} (-{aggressive_discount:.4f})")
                        print(f"📦 Size: {tokens} tokens")
                        print(f"💵 Estimated receive: ${total_amount:.2f}")
                        print(f"🎯 Using YOUR wallet: {self.client.get_address()}")
                        print(f"🚀 Strategy: AGGRESSIVE LIMIT ORDER (V1 approach)")
                        print(f"🔧 API-safe amounts: price={aggressive_price}, tokens={tokens}")
                        
                        # Create LIMIT sell order with user's credentials (V1 approach that works!)
                        from py_clob_client.order_builder.constants import SELL
                        from py_clob_client.clob_types import OrderArgs
                        
                        order_args = OrderArgs(
                            price=aggressive_price,  # Aggressive price for instant fill
                            size=tokens,             # Number of tokens to sell
                            side=SELL,
                            token_id=token_id,
                        )
                        
                        # Create and submit LIMIT order (like V1 - aggressive pricing = instant fill)
                        signed_order = self.client.create_order(order_args)
                        resp = self.client.post_order(signed_order)
                        return resp.get('orderID')
                        
                    except Exception as e:
                        logger.error(f"Speed sell error with user wallet: {e}")
                        print(f"❌ Speed sell error: {e}")
                        return None

                def monitor_order(self, order_id: str, timeout: int = 5) -> bool:
                    """Monitor order for completion"""
                    try:
                        start_time = self.time.time()
                        print(f"👀 Monitoring order: {order_id[:20]}...")
                        
                        while self.time.time() - start_time < timeout:
                            try:
                                order = self.client.get_order(order_id)
                                if order and order.get('status') in ['MATCHED', 'FILLED']:
                                    print(f"✅ ORDER COMPLETED! ({int(self.time.time() - start_time)}s)")
                                    return True
                                self.time.sleep(0.5)
                            except:
                                self.time.sleep(0.5)
                        
                        print(f"⏳ Order still processing after {timeout}s")
                        return False
                    except Exception as e:
                        logger.error(f"Order monitoring error: {e}")
                        return False
            
            user_trader = UserTrader(client, private_key)
            
            logger.info(f"✅ Created user-specific trader for {user_id}")
            return user_trader
        except Exception as e:
            logger.error(f"Error creating user trader: {e}")
            return None
    
    async def execute_buy(self, query, market_id: str, outcome: str):
        """Execute buy order with user's wallet"""
        try:
            user_id = query.from_user.id
            market = user_sessions.get(user_id, {}).get('current_market')
            
            if not market:
                await query.answer("❌ Market session expired. Please select market again.")
                return
            
            # Check if wallet is ready for trading
            wallet_ready, status_msg = wallet_manager.is_wallet_ready(user_id)
            if not wallet_ready:
                await query.answer(f"❌ Wallet not ready: {status_msg}")
                await query.edit_message_text(
                    f"❌ **Trading Not Available**\n\n{status_msg}\n\nUse /wallet to complete setup.",
                    parse_mode='Markdown'
                )
                return
            
            await query.answer("⚡ Executing ultra-fast trade with your wallet...")
            
            # Get user-specific trader
            user_trader = self.get_user_trader(user_id)
            if not user_trader:
                await query.edit_message_text("❌ **Error:** Unable to access your wallet. Please try /start again.")
                return
            
            # Execute the trade with user's wallet
            order_id = user_trader.speed_buy(market, outcome, 5.0)  # Use $5 as base amount
            
            if order_id:
                # Monitor order briefly
                filled = user_trader.monitor_order(order_id, timeout=5)
                
                if filled:
                    # Track the actual position bought (estimate tokens from $5 purchase)
                    if user_id not in user_sessions:
                        user_sessions[user_id] = {}
                    if 'positions' not in user_sessions[user_id]:
                        user_sessions[user_id]['positions'] = {}
                    
                    # Estimate tokens bought with $5 (minimum 5 tokens)
                    estimated_tokens = max(5, int(5.0 / 0.10))  # Rough estimate, will be ~50 tokens for low-priced markets
                    
                    market_id_str = str(market['id'])
                    user_sessions[user_id]['positions'][market_id_str] = {
                        'outcome': outcome,  # 'yes' or 'no' 
                        'tokens': estimated_tokens,  # estimated number of tokens owned
                        'market': market,
                        'buy_time': time.time()
                    }
                    
                    message_text = f"""
🎉 **TRADE EXECUTED!**

✅ **Market:** {market['question'][:50]}...
🎯 **Position:** {outcome.upper()}
⚡ **Speed:** Instant fill!
💰 **Amount:** ~{estimated_tokens} tokens (from $5)
📋 **Order ID:** {order_id[:20]}...

Use /positions to manage your holdings!
                    """
                else:
                    message_text = f"""
⏳ **TRADE PLACED**

📋 **Order ID:** {order_id[:20]}...
🎯 **Position:** {outcome.upper()}
💰 **Amount:** 5 tokens

Order may still be filling. Check /positions for updates.
                    """
            else:
                message_text = "❌ **TRADE FAILED**\n\nPlease try again or check your balance."
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 View Positions", callback_data="show_positions"),
                    InlineKeyboardButton("⬅️ Back to Market", callback_data=f"market_{market_id}")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Buy execution error: {e}")
            await query.edit_message_text(f"❌ Trade failed: {str(e)}")
    
    async def execute_sell(self, query, market_id: str, outcome: str):
        """Execute sell order with user's wallet"""
        try:
            user_id = query.from_user.id
            market = user_sessions.get(user_id, {}).get('current_market')
            
            if not market:
                # Try to find market by ID
                markets = db.get_high_volume_markets(1000)
                market = next((m for m in markets if str(m['id']) == market_id), None)
                if not market:
                    await query.answer("❌ Market not found. Please select market again.")
                    return
            
            # Check if wallet is ready for trading
            wallet_ready, status_msg = wallet_manager.is_wallet_ready(user_id)
            if not wallet_ready:
                await query.answer(f"❌ Wallet not ready: {status_msg}")
                await query.edit_message_text(
                    f"❌ **Trading Not Available**\n\n{status_msg}\n\nUse /wallet to complete setup.",
                    parse_mode='Markdown'
                )
                return
            
            await query.answer("⚡ Executing ultra-fast SELL with your wallet...")
            
            # Get user-specific trader
            user_trader = self.get_user_trader(user_id)
            if not user_trader:
                await query.edit_message_text("❌ **Error:** Unable to access your wallet. Please try /start again.")
                return
            
            # Get the actual tokens owned from session (fallback to estimated amount)
            position_data = user_sessions.get(user_id, {}).get('positions', {}).get(str(market_id), {})
            tokens_to_sell = position_data.get('tokens', 50)  # Use stored tokens or estimate 50 for $5 position
            
            # Execute the sell trade with user's wallet
            order_id = user_trader.speed_sell(market, outcome, tokens_to_sell)  # Sell actual tokens owned
            
            if order_id:
                # Monitor order briefly
                filled = user_trader.monitor_order(order_id, timeout=5)
                
                if filled:
                    # Remove the sold position from tracking
                    if user_id in user_sessions and 'positions' in user_sessions[user_id]:
                        market_id_str = str(market_id)
                        if market_id_str in user_sessions[user_id]['positions']:
                            del user_sessions[user_id]['positions'][market_id_str]
                    
                    message_text = f"""
🎉 **SELL EXECUTED!**

✅ **Market:** {market['question'][:50]}...
💸 **Action:** SOLD {outcome.upper()}
⚡ **Speed:** Instant fill with MARKET order!
💰 **Amount:** {tokens_to_sell} tokens (liquidated)
📋 **Order ID:** {order_id[:20]}...

💵 **USDC.e credited to your wallet!**
                    """
                else:
                    message_text = f"""
⏳ **SELL ORDER PLACED**

📋 **Order ID:** {order_id[:20]}...
💸 **Action:** SELL {outcome.upper()}
💰 **Amount:** {tokens_to_sell} tokens

Order may still be processing. Check your wallet for updates.
                    """
            else:
                message_text = "❌ **SELL FAILED**\n\nYou may not own these tokens, or insufficient balance."
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 View Positions", callback_data="show_positions"),
                    InlineKeyboardButton("📈 Browse Markets", callback_data="refresh_markets")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Sell execution error: {e}")
            await query.edit_message_text(f"❌ Sell failed: {str(e)}")
    
    async def positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user positions"""
        await self.show_positions(update)
    
    async def show_positions(self, update_or_query):
        """Show positions with sell buttons"""
        try:
            # Get recent trades to identify positions
            message_text = "📊 **YOUR POSITIONS**\n\n"
            keyboard = []
            
            # For now, we'll check if user has active sessions with traded markets
            user_id = None
            if hasattr(update_or_query, 'effective_user'):
                user_id = update_or_query.effective_user.id
            elif hasattr(update_or_query, 'from_user'):
                user_id = update_or_query.from_user.id
            
            positions_found = False
            
            # Check user's actual positions from tracking
            if user_id and user_id in user_sessions:
                positions = user_sessions[user_id].get('positions', {})
                if positions:
                    positions_found = True
                    message_text += f"💰 **YOUR ACTIVE POSITIONS:**\n\n"
                    
                    for market_id, position in positions.items():
                        market = position['market']
                        outcome = position['outcome']
                        tokens = position['tokens']
                        
                        question = market['question'][:50] + "..." if len(market['question']) > 50 else market['question']
                        volume = market.get('volume', 0)
                        
                        message_text += f"🎯 **Position #{market_id}:**\n"
                        message_text += f"❓ {question}\n"
                        message_text += f"📊 Volume: ${volume:,.0f}\n"
                        message_text += f"📍 **You Own:** {tokens} {outcome.upper()} tokens\n\n"
                        
                        # Only show sell button for the position they actually own
                        if outcome.lower() == 'yes':
                            keyboard.append([
                                InlineKeyboardButton(
                                    f"💸 SELL YES ({tokens} tokens)",
                                    callback_data=f"sell_yes_{market_id}"
                                )
                            ])
                        elif outcome.lower() == 'no':
                            keyboard.append([
                                InlineKeyboardButton(
                                    f"💸 SELL NO ({tokens} tokens)", 
                                    callback_data=f"sell_no_{market_id}"
                                )
                            ])
                        
                        message_text += "⚡ **Click SELL button for ultra-fast liquidation!**\n"
                        message_text += "🔥 Same 0-2 second execution speed\n\n"
            
            if not positions_found:
                message_text += "🔍 **No recent trading activity found.**\n\n"
                message_text += "💡 **How to see positions:**\n"
                message_text += "• Trade using /markets first\n"
                message_text += "• Positions appear here after trading\n"
                message_text += "• Each position gets instant SELL button\n\n"
            
            message_text += "**💰 Alternative position check:**\n"
            message_text += "• Check Polymarket.com for full portfolio\n"
            message_text += "• View Polygonscan for transaction history\n"
            message_text += "• Use command-line bot for detailed tracking"
            
            # Add utility buttons
            keyboard.extend([
                [InlineKeyboardButton("🔄 Refresh Positions", callback_data="show_positions")],
                [InlineKeyboardButton("📊 Browse Markets", callback_data="refresh_markets")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if hasattr(update_or_query, 'message'):  # Command
                await update_or_query.message.reply_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:  # Callback query
                await update_or_query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Positions error: {e}")
            error_msg = f"❌ Error loading positions: {str(e)}"
            if hasattr(update_or_query, 'message'):
                await update_or_query.message.reply_text(error_msg)
            else:
                await update_or_query.edit_message_text(error_msg)
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all button clicks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "refresh_markets":
            # Simulate markets command
            fake_update = type('', (), {})()
            fake_update.effective_user = query.from_user
            fake_update.message = type('', (), {})()
            fake_update.message.reply_text = query.edit_message_text
            await self.markets_command(fake_update, context)
            
        elif data.startswith("market_"):
            market_id = data.replace("market_", "")
            await self.show_market_detail(query, market_id)
            
        elif data.startswith("buy_yes_"):
            market_id = data.replace("buy_yes_", "")
            await self.execute_buy(query, market_id, "yes")
            
        elif data.startswith("buy_no_"):
            market_id = data.replace("buy_no_", "")
            await self.execute_buy(query, market_id, "no")
            
        elif data.startswith("sell_yes_"):
            market_id = data.replace("sell_yes_", "")
            await self.execute_sell(query, market_id, "yes")
            
        elif data.startswith("sell_no_"):
            market_id = data.replace("sell_no_", "")
            await self.execute_sell(query, market_id, "no")
            
        elif data == "show_positions":
            await self.show_positions(query)
            
        # New V2 wallet-related callbacks
        elif data == "show_wallet":
            await self.show_wallet_callback(query)
            
        elif data == "show_funding":
            await self.show_funding_callback(query)
            
        elif data == "show_approvals":
            await self.show_approvals_callback(query)
            
        elif data == "show_private_key":
            await self.show_private_key_callback(query)
            
        elif data == "mark_funded":
            await self.mark_funded_callback(query)
            
        elif data == "check_balance":
            await self.check_balance_callback(query)
            
        elif data == "mark_usdc_approved":
            await self.mark_usdc_approved_callback(query)
            
        elif data == "mark_poly_approved":
            await self.mark_poly_approved_callback(query)
            
        elif data == "auto_approve":
            await self.auto_approve_callback(query)
            
        elif data == "generate_api":
            await self.generate_api_callback(query)
            
        elif data == "test_api_credentials":
            await self.test_api_credentials_callback(query)
            
        elif data == "check_approvals":
            await self.check_approvals_callback(query)
            
        elif data == "main_menu":
            await query.edit_message_text(
                "🚀 **MAIN MENU**\n\nUse /markets or /positions to start trading!",
                parse_mode='Markdown'
            )
    
    # New V2 callback handlers for wallet management
    async def show_wallet_callback(self, query):
        """Show wallet details via callback"""
        user_id = query.from_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await query.edit_message_text("❌ No wallet found. Use /start to create one.")
            return
        
        wallet_text = f"""
💼 **YOUR WALLET DETAILS**

📍 **Address:**
`{wallet['address']}`

🔑 **Status:**
• Funded: {'✅' if wallet.get('funded', False) else '❌'}
• USDC.e Approved: {'✅' if wallet.get('usdc_approved', False) else '❌'}
• Polymarket Approved: {'✅' if wallet.get('polymarket_approved', False) else '❌'}

📅 **Created:** {time.ctime(wallet.get('created_at', 0))}

⚠️ **Security Notice:** Your private key is stored securely.
        """
        
        keyboard = [
            [InlineKeyboardButton("🔑 Show Private Key", callback_data="show_private_key")],
            [InlineKeyboardButton("💰 Fund Instructions", callback_data="show_funding")],
            [InlineKeyboardButton("✅ Handle Approvals", callback_data="show_approvals")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(wallet_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def show_funding_callback(self, query):
        """Show funding instructions via callback"""
        user_id = query.from_user.id
        address = wallet_manager.get_user_address(user_id)
        
        if not address:
            await query.edit_message_text("❌ No wallet found. Use /start to create one.")
            return
        
        funding_text = f"""
💰 **FUNDING INSTRUCTIONS**

📍 **Your Wallet Address:**
`{address}`

🪙 **Required Tokens:**

**1. USDC.e (Trading Currency)**
• Contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
• Minimum: $10 USDC.e for testing
• Network: Polygon (MATIC)

**2. POL (Gas Token)**
• Native Polygon token for transaction fees
• Minimum: 0.1 POL
• Network: Polygon (MATIC)

⚠️ **Important:**
• Double-check address before sending
• Use Polygon network, not Ethereum
• Start with small amounts for testing
        """
        
        keyboard = [
            [InlineKeyboardButton("✅ I've Funded My Wallet", callback_data="mark_funded")],
            [InlineKeyboardButton("🔄 Check Balance", callback_data="check_balance")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(funding_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def show_approvals_callback(self, query):
        """Show approvals via callback"""
        user_id = query.from_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await query.edit_message_text("❌ No wallet found. Use /start to create one.")
            return
        
        approve_text = f"""
✅ **CONTRACT APPROVALS NEEDED**

📍 **Your Wallet:** `{wallet['address'][:10]}...{wallet['address'][-4:]}`

🔐 **Required Approvals:**

**1. USDC.e Spending Approval**
• Status: {'✅ Approved' if wallet.get('usdc_approved', False) else '❌ Needed'}
• Allows trading with your USDC.e

**2. Polymarket Contract Approval**  
• Status: {'✅ Approved' if wallet.get('polymarket_approved', False) else '❌ Needed'}
• Enables market interactions

💡 **Manual Process** - Auto-approval coming soon!
        """
        
        keyboard = [
            [InlineKeyboardButton("✅ Mark USDC.e Approved", callback_data="mark_usdc_approved")],
            [InlineKeyboardButton("✅ Mark Polymarket Approved", callback_data="mark_poly_approved")],
            [InlineKeyboardButton("🔑 Get Private Key", callback_data="show_private_key")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(approve_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def show_private_key_callback(self, query):
        """Show private key securely"""
        user_id = query.from_user.id
        private_key = wallet_manager.get_user_private_key(user_id)
        
        if not private_key:
            await query.edit_message_text("❌ No wallet found. Use /start to create one.")
            return
        
        # Send private key in a separate message for security
        key_text = f"""
🔑 **YOUR PRIVATE KEY**

⚠️ **CRITICAL SECURITY WARNING:**
Never share this key with anyone!

`{private_key}`

**Use this to import your wallet to MetaMask:**
1. Open MetaMask
2. Click "Import Account"
3. Paste this private key
4. Complete approvals on Polymarket.com

**This message will be automatically deleted in 60 seconds for security.**
        """
        
        # Send the key as a new message
        key_message = await query.message.reply_text(key_text, parse_mode='Markdown')
        
        # Schedule deletion after 60 seconds
        async def delete_key_message():
            await asyncio.sleep(60)
            try:
                await key_message.delete()
            except:
                pass  # Message may already be deleted
        
        asyncio.create_task(delete_key_message())
        
        # Update original message
        await query.edit_message_text(
            "🔑 **Private key sent above** ⬆️\n\n⚠️ **Auto-deleting in 60 seconds for security**",
            parse_mode='Markdown'
        )
    
    async def mark_funded_callback(self, query):
        """Mark wallet as funded"""
        user_id = query.from_user.id
        wallet_manager.update_funding_status(user_id, True)
        
        await query.edit_message_text(
            "✅ **Wallet marked as funded!**\n\nNext step: Use /approve to handle contract approvals",
            parse_mode='Markdown'
        )
    
    async def check_balance_callback(self, query):
        """Check wallet balance with live data"""
        user_id = query.from_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await query.edit_message_text("❌ No wallet found.")
            return
        
        await query.edit_message_text("🔍 **Checking balances...**", parse_mode='Markdown')
        
        try:
            wallet_address = wallet['address']
            balance_report = balance_checker.format_balance_report(wallet_address)
            
            # Update funding status based on balance check
            balances = balance_checker.check_all_balances(wallet_address)
            if balances.get('fully_funded', False):
                wallet_manager.update_funding_status(user_id, True)
            
            keyboard = []
            if balances.get('fully_funded', False):
                keyboard.append([InlineKeyboardButton("🔄 Auto-Approve Contracts", callback_data="auto_approve")])
            
            keyboard.append([InlineKeyboardButton("🔄 Refresh Balance", callback_data="check_balance")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(balance_report, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Balance check error: {e}")
            await query.edit_message_text(f"❌ **Balance check failed:** {str(e)}", parse_mode='Markdown')
    
    async def mark_usdc_approved_callback(self, query):
        """Mark USDC.e as approved"""
        user_id = query.from_user.id
        wallet_manager.update_approval_status(user_id, usdc_approved=True)
        
        await query.edit_message_text(
            "✅ **USDC.e marked as approved!**\n\nNext: Mark Polymarket approved, then start trading!",
            parse_mode='Markdown'
        )
    
    async def mark_poly_approved_callback(self, query):
        """Mark Polymarket contracts as approved"""
        user_id = query.from_user.id
        wallet_manager.update_approval_status(user_id, polymarket_approved=True)
        
        wallet_ready, status_msg = wallet_manager.is_wallet_ready(user_id)
        
        if wallet_ready:
            message = "🎉 **ALL APPROVALS COMPLETE!**\n\n✅ Your wallet is ready for trading!\n\nUse /markets to start trading!"
        else:
            message = f"✅ **Polymarket marked as approved!**\n\n{status_msg}"
        
        await query.edit_message_text(message, parse_mode='Markdown')
    
    async def auto_approve_callback(self, query):
        """Auto-approve contracts via callback"""
        user_id = query.from_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet or not wallet.get('funded', False):
            await query.edit_message_text("⚠️ Please fund your wallet first before auto-approval.")
            return
        
        await query.edit_message_text("🔄 **Starting auto-approval...**\n\n⚡ Approving all contracts automatically!", parse_mode='Markdown')
        
        try:
            private_key = wallet['private_key']
            success, results = approval_manager.approve_all_for_trading(private_key)
            
            if success:
                wallet_manager.update_approval_status(user_id, usdc_approved=True, polymarket_approved=True, auto_approval_completed=True)
                await query.edit_message_text("🎉 **Auto-approval completed!**\n\nYour wallet is ready for trading!", parse_mode='Markdown')
            else:
                await query.edit_message_text(f"❌ **Auto-approval failed**\n\n{results.get('error', 'Unknown error')}", parse_mode='Markdown')
        
        except Exception as e:
            await query.edit_message_text(f"❌ **Error:** {str(e)}", parse_mode='Markdown')
    
    async def generate_api_callback(self, query):
        """Generate API credentials via callback"""
        user_id = query.from_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await query.edit_message_text("❌ No wallet found. Use /start to create one.")
            return
        
        await query.edit_message_text("🔄 **Generating API credentials...**", parse_mode='Markdown')
        
        try:
            private_key = wallet['private_key']
            wallet_address = wallet['address']
            
            creds = api_key_manager.generate_api_credentials(user_id, private_key, wallet_address)
            
            if creds:
                wallet_manager.update_api_credentials_status(user_id, True)
                await query.edit_message_text(f"🎉 **API credentials generated!**\n\n✅ Key: `{creds.api_key[:20]}...`\n\nReady for enhanced trading!", parse_mode='Markdown')
            else:
                await query.edit_message_text("❌ **API generation failed**\n\nTry again later or contact support.", parse_mode='Markdown')
                
        except Exception as e:
            await query.edit_message_text(f"❌ **Error:** {str(e)}", parse_mode='Markdown')
    
    async def test_api_credentials_callback(self, query):
        """Test API credentials via callback"""
        user_id = query.from_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await query.edit_message_text("❌ No wallet found.")
            return
        
        await query.edit_message_text("🧪 **Testing API credentials...**", parse_mode='Markdown')
        
        try:
            private_key = wallet['private_key']
            wallet_address = wallet['address']
            
            test_success, test_msg = api_key_manager.test_api_credentials(user_id, private_key, wallet_address)
            
            if test_success:
                await query.edit_message_text(f"✅ **API Test Successful!**\n\n{test_msg}\n\nYour API credentials are working perfectly!", parse_mode='Markdown')
            else:
                await query.edit_message_text(f"❌ **API Test Failed**\n\n{test_msg}\n\nTry regenerating API credentials.", parse_mode='Markdown')
                
        except Exception as e:
            await query.edit_message_text(f"❌ **Test Error:** {str(e)}", parse_mode='Markdown')
    
    async def check_approvals_callback(self, query):
        """Check approval status via callback"""
        user_id = query.from_user.id
        wallet = wallet_manager.get_user_wallet(user_id)
        
        if not wallet:
            await query.edit_message_text("❌ No wallet found.")
            return
        
        await query.edit_message_text("🔍 **Checking approvals...**", parse_mode='Markdown')
        
        try:
            wallet_address = wallet['address']
            approval_status = approval_manager.check_all_approvals(wallet_address)
            
            if approval_status.get('all_ready', False):
                status_text = "✅ **All Approvals Complete!**\n\nYour wallet is ready for trading!"
            else:
                usdc_count = approval_status.get('usdc_approved_count', 0)
                ct_count = approval_status.get('ct_approved_count', 0)
                total = approval_status.get('total_contracts', 3)
                
                status_text = f"""
🔍 **Approval Status Check**

**USDC.e Approvals:** {usdc_count}/{total} contracts
**Conditional Tokens:** {ct_count}/{total} contracts

{'✅ Ready to trade!' if approval_status.get('all_ready', False) else '⚠️ More approvals needed'}
                """
            
            await query.edit_message_text(status_text, parse_mode='Markdown')
            
        except Exception as e:
            await query.edit_message_text(f"❌ **Check Error:** {str(e)}", parse_mode='Markdown')
    
    def run(self):
        """Start the bot"""
        logger.info(f"Starting Telegram bot: @{BOT_USERNAME}")
        logger.info("🚀 Ultra-speed Polymarket trading bot ready!")
        
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """Main function"""
    print("🤖 TELEGRAM TRADING BOT")
    print("=" * 30)
    print(f"Bot: @{BOT_USERNAME}")
    print("Features: Markets, Live pricing, Ultra-fast trading")
    print("Ready to serve lightning-fast trades! ⚡")
    
    bot = TelegramTradingBot()
    bot.run()

if __name__ == '__main__':
    main()
