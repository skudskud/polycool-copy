"""
Telegram Bot Application
Main bot logic and command handlers
"""
import asyncio
from typing import Optional

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from telegram_bot.bot.handlers import (
    start_handler,
    wallet_handler,
    markets_handler,
    positions_handler,
    smart_trading_handler,
    # copy_trading_handler,  # Replaced with modular copy_trading package
    referral_handler,
    admin_handler,
)

logger = get_logger(__name__)


class TelegramBotApplication:
    """
    Main Telegram bot application class
    """

    def __init__(self):
        """Initialize bot application"""
        self.application: Optional[Application] = None
        self.running = False

    async def initialize(self) -> None:
        """Initialize the bot application"""
        try:
            # Validate token is present (required for bot service)
            if not settings.telegram.token:
                raise ValueError(
                    "TELEGRAM_BOT_TOKEN is required for bot service. "
                    "Please set it in .env.local or environment variables."
                )

            # Create application
            self.application = Application.builder().token(settings.telegram.token).build()

            # Add handlers
            await self._add_handlers()

            logger.info("✅ Telegram bot initialized successfully")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Telegram bot: {e}")
            raise

    async def _add_handlers(self) -> None:
        """Add all command and callback handlers"""
        if not self.application:
            raise RuntimeError("Bot application not initialized")

        # Command handlers
        self.application.add_handler(CommandHandler("start", start_handler.handle_start))
        self.application.add_handler(CommandHandler("wallet", wallet_handler.handle_wallet))
        self.application.add_handler(CommandHandler("markets", markets_handler.handle_markets))
        self.application.add_handler(CommandHandler("positions", positions_handler.handle_positions))
        self.application.add_handler(CommandHandler("smart_trading", smart_trading_handler.handle_smart_trading))
        # Copy trading - use new conversation handler system
        from telegram_bot.handlers.copy_trading.main import setup_copy_trading_handlers
        setup_copy_trading_handlers(self.application)
        self.application.add_handler(CommandHandler("referral", referral_handler.handle_referral))
        self.application.add_handler(CommandHandler("admin", admin_handler.handle_admin))

        # Callback query handlers for inline keyboards
        # Start/Wallet callbacks (must come before more specific patterns)
        self.application.add_handler(CallbackQueryHandler(
            start_handler.handle_start_callback,
            pattern=r"^(start_bridge|check_sol_balance|view_wallet|onboarding_help|confirm_bridge_.*|cancel_bridge)$"
        ))
        self.application.add_handler(CallbackQueryHandler(
            wallet_handler.handle_wallet_callback,
            pattern=r"^(bridge_sol|wallet_details|main_menu|show_polygon_key|show_solana_key|hide_polygon_key|hide_solana_key)$"
        ))
        # Markets callbacks (trending, categories, search, filters, trading, etc.)
        # Note: markets_hub is handled here, not in start_handler
        self.application.add_handler(CallbackQueryHandler(
            markets_handler.handle_market_callback,
            pattern=r"^(markets_hub|trending_markets_|cat_|catfilter_|filter_|market_select_|event_select_|refresh_prices_|trigger_search|search_page_|quick_buy_|buy_amount_|custom_buy_|confirm_order_)"
        ))
        self.application.add_handler(CallbackQueryHandler(
            positions_handler.handle_position_callback,
            pattern=r"^(positions_hub|refresh_positions|position_|sell_position_|sell_amount_|sell_custom_|confirm_sell_|tpsl_setup_|tpsl_set_tp_|tpsl_set_sl_|tpsl_percent_|tpsl_custom_|tpsl_clear_tp_|tpsl_clear_sl_|tpsl_save_|view_all_tpsl|history_page_|markets_page_|tpsl_edit_|redeem_position_|confirm_redeem_|cancel_redeem|check_redeemable)$"
        ))
        self.application.add_handler(CallbackQueryHandler(
            smart_trading_handler.handle_smart_callback,
            pattern=r"^smart_"
        ))
        # Copy trading callbacks (modular system with copy_trading: prefix)
        # NOTE: copy_trading:confirm_*, copy_trading:search_leader, and copy_trading:modify_budget
        # are handled by ConversationHandler in handlers/copy_trading/main.py
        # Import from new modular callbacks structure
        from telegram_bot.handlers.copy_trading.callbacks import (
            handle_settings,
            handle_history,
            handle_stop_following,
            handle_cancel_search,
            handle_dashboard,
            handle_toggle_mode,
            handle_pause_resume,
        )
        self.application.add_handler(CallbackQueryHandler(
            handle_settings,
            pattern=r"^copy_trading:settings$"
        ))
        self.application.add_handler(CallbackQueryHandler(
            handle_history,
            pattern=r"^copy_trading:history$"
        ))
        self.application.add_handler(CallbackQueryHandler(
            handle_stop_following,
            pattern=r"^copy_trading:stop_following$"
        ))
        self.application.add_handler(CallbackQueryHandler(
            handle_cancel_search,
            pattern=r"^copy_trading:cancel_search$"
        ))
        self.application.add_handler(CallbackQueryHandler(
            handle_dashboard,
            pattern=r"^copy_trading:dashboard$"
        ))
        self.application.add_handler(CallbackQueryHandler(
            handle_toggle_mode,
            pattern=r"^copy_trading:toggle_mode$"
        ))
        # Note: copy_trading:settings_mode_* callbacks are handled by ConversationHandler
        # in telegram_bot/handlers/copy_trading/main.py
        self.application.add_handler(CallbackQueryHandler(
            handle_pause_resume,
            pattern=r"^copy_trading:(pause|resume)$"
        ))

        # Welcome message handler (for new users, before they start)
        # Must be in a lower group to run before other message handlers
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            start_handler.handle_welcome_message
        ), group=0)  # Lowest group = highest priority for welcome messages

        # Message handlers for conversations
        # Search handler (when user types search query)
        # Note: Copy trading is now handled by ConversationHandler in handlers/copy_trading/main.py
        # No need for separate MessageHandler - it was causing conflicts
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            markets_handler.handle_search_message
        ), group=5)  # Higher group = lower priority, but still processes after copy trading

        # Error handler
        self.application.add_error_handler(self._error_handler)

    async def _setup_bot_commands(self) -> None:
        """Setup bot commands menu that appears when user types '/'"""
        try:
            commands = [
                BotCommand("start", "🚀 Start - Create your account"),
                BotCommand("wallet", "💼 Manage your wallet"),
                BotCommand("markets", "📊 Browse markets"),
                BotCommand("positions", "📈 View your positions"),
                BotCommand("smart_trading", "🎯 Smart trading"),
                BotCommand("copy_trading", "👥 Copy trading"),
                BotCommand("referral", "🎁 Referral program"),
                BotCommand("admin", "⚙️ Admin panel"),
            ]

            await self.application.bot.set_my_commands(commands)
            logger.info("✅ Bot commands menu configured")

        except Exception as e:
            logger.error(f"❌ Failed to set bot commands: {e}")

    async def start(self) -> None:
        """Start the bot in background (non-blocking)"""
        if not self.application:
            await self.initialize()

        try:
            self.running = True
            logger.info("🚀 Starting Telegram bot...")

            # Start the application (initializes updater and dispatcher)
            await self.application.initialize()

            # Setup bot commands menu
            await self._setup_bot_commands()

            # Start polling/webhook using the updater directly (avoids event loop conflict)
            if settings.is_development:
                # Use updater.start_polling() which works with existing event loop
                await self.application.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                logger.info("✅ Telegram bot polling started")
            else:
                # Webhook mode for production
                await self.application.updater.start_webhook(
                    listen="0.0.0.0",
                    port=8443,
                    webhook_url=settings.telegram.webhook_url,
                    secret_token=settings.telegram.webhook_secret,
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                logger.info("✅ Telegram bot webhook started")

            # Start the application (starts dispatcher)
            await self.application.start()

        except Exception as e:
            logger.error(f"❌ Failed to start Telegram bot: {e}")
            self.running = False
            raise

    async def stop(self) -> None:
        """Stop the bot gracefully"""
        if self.application and self.running:
            logger.info("🛑 Stopping Telegram bot...")
            try:
                await self.application.stop()
                await self.application.updater.stop()
                await self.application.shutdown()
            except Exception as e:
                logger.error(f"Error stopping bot: {e}")
            finally:
                self.running = False
                logger.info("✅ Telegram bot stopped")

    async def process_update(self, update_data: dict) -> None:
        """Process a webhook update"""
        if not self.application:
            logger.warning("Bot application not initialized")
            return

        try:
            update = Update.de_json(update_data, self.application.bot)
            await self.application.process_update(update)
        except Exception as e:
            logger.error(f"Error processing update: {e}")

    async def _error_handler(self, update: Update, context) -> None:
        """Handle bot errors"""
        logger.error(f"Bot error: {context.error}")

        # Send error message to admin if configured
        if update and update.effective_chat:
            try:
                await update.effective_chat.send_message(
                    "❌ An error occurred. Our team has been notified."
                )
            except Exception:
                pass  # Don't fail if we can't send error message

    async def send_message_to_user(self, user_id: int, message: str) -> bool:
        """Send message to specific user"""
        if not self.application:
            return False

        try:
            await self.application.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send message to user {user_id}: {e}")
            return False

    async def broadcast_message(self, message: str, user_ids: list[int]) -> dict:
        """Broadcast message to multiple users"""
        results = {"sent": 0, "failed": 0}

        for user_id in user_ids:
            if await self.send_message_to_user(user_id, message):
                results["sent"] += 1
            else:
                results["failed"] += 1

            # Rate limiting - small delay between messages
            await asyncio.sleep(0.1)

        return results
