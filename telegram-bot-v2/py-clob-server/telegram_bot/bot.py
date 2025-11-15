#!/usr/bin/env python3
"""
Polymarket Telegram Trading Bot - Main Bot Class
Clean architecture with modular handlers and services
ENHANCED WITH TP/SL PRICE MONITORING
"""

import asyncio
import logging
from telegram import BotCommand
from telegram.ext import Application, CommandHandler
from telegram.request import HTTPXRequest

from config.config import BOT_TOKEN, BOT_USERNAME

# Import session manager
from .session_manager import session_manager

# Import services
from .services import TradingService, PositionService, MarketService, PriceMonitor, set_price_monitor

# Import handlers
from .handlers import setup_handlers, trading_handlers, positions, callback_handlers, bridge_handlers, analytics_handlers, category_handlers, tpsl_handlers, referral_handlers
from .handlers.copy_trading import setup_copy_trading_handlers

logger = logging.getLogger(__name__)


class TelegramTradingBot:
    """
    Main Telegram trading bot class
    Coordinates services and handlers in a clean, modular architecture
    """

    def __init__(self):
        """Initialize bot with all services and handlers"""
        # Create HTTPX request with increased timeouts to handle slow Telegram API
        request = HTTPXRequest(
            connection_pool_size=8,
            connect_timeout=15.0,    # 15 secondes pour établir la connexion (vs 5s par défaut)
            read_timeout=15.0,       # 15 secondes pour lire la réponse (vs 5s par défaut)
            write_timeout=15.0,      # 15 secondes pour écrire la requête (vs 5s par défaut)
            pool_timeout=10.0        # 10 secondes pour obtenir une connexion du pool
        )

        # Create Telegram application with custom request and retry logic
        self.app = Application.builder().token(BOT_TOKEN).request(request).build()

        # Initialize session manager
        self.session_manager = session_manager

        # Initialize services
        self.market_service = MarketService()
        self.position_service = PositionService(self.session_manager)
        self.trading_service = TradingService(self.session_manager, self.position_service)

        # Initialize TP/SL Price Monitor (optimized interval)
        self.price_monitor = PriceMonitor(self.trading_service, check_interval=30)
        set_price_monitor(self.price_monitor)

        # PHASE 4: Connect notification service to bot
        from core.services import notification_service
        notification_service.set_bot_app(self.app)

        # PHASE 5: Connect copy trading notification service to bot
        from core.services.copy_trading.notification_service import (
            get_copy_trading_notification_service
        )
        copy_notif_service = get_copy_trading_notification_service()
        copy_notif_service.set_notification_service(notification_service)

        # Setup all handlers
        self.setup_handlers()

        logger.info("✅ TelegramTradingBot initialized with TP/SL price monitoring")

    async def _run_tpsl_migration(self):
        """
        Auto-migration: Add cancelled_reason and entry_transaction_id columns to tpsl_orders table
        Runs once on bot startup, safe to run multiple times (IF NOT EXISTS)
        """
        try:
            logger.info("📋 Running TP/SL enhancements migration...")

            from database import engine
            from sqlalchemy import text, inspect

            with engine.connect() as conn:
                # PHASE 1: Add cancelled_reason column
                conn.execute(text(
                    "ALTER TABLE tpsl_orders ADD COLUMN IF NOT EXISTS cancelled_reason VARCHAR(50);"
                ))
                conn.commit()

                # Add comment for cancelled_reason
                try:
                    conn.execute(text(
                        "COMMENT ON COLUMN tpsl_orders.cancelled_reason IS "
                        "'Tracks why TP/SL was cancelled: user_cancelled, market_closed, market_resolved, "
                        "position_closed, position_increased, insufficient_tokens, both_null';"
                    ))
                    conn.commit()
                except:
                    pass  # Comment already exists

                # Create index for cancelled_reason
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_tpsl_cancelled_reason "
                    "ON tpsl_orders(cancelled_reason) WHERE status = 'cancelled';"
                ))
                conn.commit()

                # PHASE 9: Add entry_transaction_id column
                conn.execute(text(
                    "ALTER TABLE tpsl_orders ADD COLUMN IF NOT EXISTS entry_transaction_id INTEGER;"
                ))
                conn.commit()

                # Add comment for entry_transaction_id
                try:
                    conn.execute(text(
                        "COMMENT ON COLUMN tpsl_orders.entry_transaction_id IS "
                        "'The BUY transaction that initiated this TP/SL order. Used for audit trail and display. "
                        "NULL for orders created before this feature.';"
                    ))
                    conn.commit()
                except:
                    pass

                # Add foreign key constraint (with existence check)
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.table_constraints
                            WHERE constraint_name = 'fk_tpsl_entry_transaction'
                              AND table_name = 'tpsl_orders'
                        ) THEN
                            ALTER TABLE tpsl_orders
                            ADD CONSTRAINT fk_tpsl_entry_transaction
                            FOREIGN KEY (entry_transaction_id)
                            REFERENCES transactions(id)
                            ON DELETE SET NULL;
                        END IF;
                    END $$;
                """))
                conn.commit()

                # Create index for entry_transaction_id
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_tpsl_entry_transaction "
                    "ON tpsl_orders(entry_transaction_id) "
                    "WHERE entry_transaction_id IS NOT NULL;"
                ))
                conn.commit()

            # Verify both columns
            inspector = inspect(engine)
            columns = inspector.get_columns('tpsl_orders')
            column_names = [col['name'] for col in columns]

            verified = []
            if 'cancelled_reason' in column_names:
                verified.append('cancelled_reason')
            if 'entry_transaction_id' in column_names:
                verified.append('entry_transaction_id')

            if len(verified) == 2:
                logger.info(f"✅ TP/SL migration successful - {', '.join(verified)} columns verified")
            else:
                logger.warning(f"⚠️ Migration partial - verified: {', '.join(verified) if verified else 'none'}")

        except Exception as e:
            # Don't crash bot if migration fails - columns might already exist
            logger.warning(f"⚠️ TP/SL migration note: {e} (may be already applied)")

    def setup_handlers(self):
        """Register all command and callback handlers"""
        # Register setup handlers (/start, /help, /wallet, etc.)
        setup_handlers.register(self.app, self.session_manager)

        # =====================================================================
        # CONVERSATION HANDLERS (MUST BE REGISTERED BEFORE TEXT HANDLERS!)
        # =====================================================================
        # Register withdrawal handlers (in-bot SOL/USDC withdrawal)
        # CRITICAL: This must come BEFORE trading_handlers to avoid text handler conflicts
        from telegram_bot.handlers.withdrawal_handlers import withdrawal_conversation_handler
        self.app.add_handler(withdrawal_conversation_handler)

        # Register copy trading handlers (/copy_trading - follow leaders, view PnL)
        try:
            setup_copy_trading_handlers(self.app)
            logger.info("✅ Copy trading handlers registered")
        except Exception as e:
            logger.warning(f"⚠️ Copy trading handlers registration failed: {e}")

        # Register trading handlers (/markets, /search, text messages)
        # NEW: Pass market_db for enhanced markets UI
        from market_database import MarketDatabase
        market_db = MarketDatabase()
        trading_handlers.register(self.app, self.session_manager, self.trading_service, market_db)

        # Register category handlers (/category, category browsing)
        category_handlers.register(self.app, self.session_manager, market_db)

        # Register position handlers (/positions - view all positions with TP/SL)
        from telegram_bot.handlers.positions import positions_command
        self.app.add_handler(CommandHandler("positions", positions_command))

        # Register bridge handlers (/bridge, /solana bridge workflows)
        bridge_handlers.register(self.app, self.session_manager)

        # Register analytics handlers (/pnl, /transactions, /reconcile)
        analytics_handlers.register(self.app)

        # Register TP/SL handlers (/tpsl, set/edit/cancel TP/SL)
        tpsl_handlers.register(self.app, self.session_manager)

        # Register referral handlers (/referral, claim commissions)
        referral_handlers.register(self.app)

        # Register smart trading handler (/smart_trading - view smart wallet trades)
        from telegram_bot.handlers.smart_trading_handler import smart_trading_command
        self.app.add_handler(CommandHandler("smart_trading", smart_trading_command))

        # Register leaderboard handler (/leaderboard - view weekly and all-time rankings)
        from telegram_bot.handlers.leaderboard_handlers import (
            handle_leaderboard_command,
            handle_leaderboard_refresh,
            handle_leaderboard_weekly_stats,
            handle_leaderboard_alltime_stats,
            handle_leaderboard_back
        )
        from telegram.ext import CallbackQueryHandler
        self.app.add_handler(CommandHandler("leaderboard", handle_leaderboard_command))
        self.app.add_handler(CallbackQueryHandler(handle_leaderboard_refresh, pattern='^leaderboard_refresh$'))
        self.app.add_handler(CallbackQueryHandler(handle_leaderboard_weekly_stats, pattern='^leaderboard_weekly_stats$'))
        self.app.add_handler(CallbackQueryHandler(handle_leaderboard_alltime_stats, pattern='^leaderboard_alltime_stats$'))
        self.app.add_handler(CallbackQueryHandler(handle_leaderboard_back, pattern='^leaderboard_back$'))

        # Register callback handlers (all inline buttons)
        callback_handlers.register(
            self.app,
            self.session_manager,
            self.trading_service,
            self.position_service,
            self.market_service
        )

        # ===================================================================
        # 🔍 DIAGNOSTIC: Log ALL updates to detect bot token conflicts
        # ===================================================================
        from telegram import Update
        from telegram.ext import MessageHandler, filters, ContextTypes, BaseHandler, CallbackQueryHandler

        async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Diagnostic handler to log ALL updates - helps detect conflicts"""
            try:
                if update.message:
                    logger.info(f"🔍 [DIAGNOSTIC] ✅ MESSAGE RECEIVED from user {update.effective_user.id}: '{update.message.text[:100] if update.message.text else 'No text'}'")
                    logger.info(f"🔍 [DIAGNOSTIC] Message ID: {update.message.message_id}, Chat ID: {update.message.chat_id}")
                elif update.callback_query:
                    logger.info(f"🔍 [DIAGNOSTIC] ✅ CALLBACK RECEIVED from user {update.effective_user.id}: '{update.callback_query.data[:100] if update.callback_query.data else 'No data'}'")
                elif update.edited_message:
                    logger.info(f"🔍 [DIAGNOSTIC] ✅ EDITED MESSAGE from user {update.effective_user.id}")
                else:
                    logger.info(f"🔍 [DIAGNOSTIC] ✅ UPDATE RECEIVED type: {type(update)}, ID: {update.update_id}")
            except Exception as e:
                logger.error(f"❌ [DIAGNOSTIC] Error logging update: {e}", exc_info=True)

        # Add in group -1 (FIRST) to catch ALL updates before any handler processes them
        # This ensures we see messages even if another handler consumes them
        self.app.add_handler(MessageHandler(filters.ALL, log_all_updates), group=-1)

        # Also catch callback queries
        async def log_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Log callback queries"""
            if update.callback_query:
                logger.info(f"🔍 [DIAGNOSTIC] ✅ CALLBACK QUERY from user {update.effective_user.id}: '{update.callback_query.data[:100] if update.callback_query.data else 'No data'}'")

        self.app.add_handler(CallbackQueryHandler(log_callbacks), group=-1)

        # Add error handler to catch all unhandled errors
        async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
            """Global error handler to catch all unhandled exceptions"""
            logger.error(f"❌ [ERROR_HANDLER] Unhandled error: {context.error}", exc_info=context.error)
            logger.error(f"❌ [ERROR_HANDLER] Update: {update}")
            logger.error(f"❌ [ERROR_HANDLER] Context: {context}")

        self.app.add_error_handler(error_handler)
        logger.info("✅ Diagnostic handler registered (logs ALL updates)")
        logger.info("✅ Global error handler registered")

        logger.info("✅ All handlers registered (including TP/SL, referral, and smart trading handlers)")

    async def setup_bot_commands(self):
        """
        Setup bot command menu for Telegram

        PRODUCTION MENU: Streamlined for end users
        - Hidden commands still work if typed manually
        - Removes complexity for public launch
        - Power user commands accessible via direct typing
        """
        commands = [
            BotCommand("start", "🚀 Start trading"),
            BotCommand("wallet", "💼 View wallet & balances"),
            BotCommand("markets", "🏆 Browse & trade markets"),
            BotCommand("positions", "📊 Your positions"),
            # BotCommand("leaderboard", "📈 Leaderboard & rankings"),  # Hidden but still functional
            BotCommand("copy_trading", "🔮 Copy Trading - Follow Leaders"),
            BotCommand("smart_trading", "💎 Follow expert traders"),
            BotCommand("referral", "🎁 Referral program & earnings"),
            BotCommand("restart", "🔄 Reset account"),
        ]

        # Hidden from menu but still functional if typed:
        # /bridge, /fund, /balance, /autoapprove, /generateapi, /tpsl, /history, /pnl, /category, /search, /leaderboard
        # Category and Search are now accessible via /markets button interface (unified hub)
        # These are integrated into the streamlined flow or accessible via /positions or /markets
        # Power users can still access them by typing the command manually

        await self.app.bot.set_my_commands(commands)
        logger.info("✅ Bot commands menu configured (8 visible commands)")

    def run(self):
        """Run the bot (blocking)"""
        logger.info("🤖 Starting Telegram Trading Bot with TP/SL monitoring...")

        async def initialize_and_run():
            """Initialize bot and start polling"""
            try:
                # Initialize application
                await self.app.initialize()

                # Run TP/SL enhancements migration (auto-migration)
                await self._run_tpsl_migration()

                # Setup bot commands
                await self.setup_bot_commands()

                # Start TP/SL Price Monitor
                await self.price_monitor.start()
                logger.info("🔄 TP/SL Price Monitor started")

                # Start polling
                await self.app.start()
                logger.info("✅ Bot is running and polling for updates")

                # Keep running
                await self.app.updater.start_polling()

                # Run until stopped
                await asyncio.Event().wait()

            except Exception as e:
                logger.error(f"❌ Bot run error: {e}")
                raise
            finally:
                # Cleanup: Stop price monitor
                if self.price_monitor.is_running:
                    await self.price_monitor.stop()
                    logger.info("🛑 TP/SL Price Monitor stopped")

        # Run the async event loop
        try:
            asyncio.run(initialize_and_run())
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user")
        except Exception as e:
            logger.error(f"❌ Bot crashed: {e}")
            raise


def main():
    """Main entry point for running the bot standalone"""
    # Setup logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    # Create and run bot
    bot = TelegramTradingBot()
    bot.run()


if __name__ == '__main__':
    main()
