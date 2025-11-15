"""
Telegram bot initialization and handlers
"""

import asyncio
from typing import Optional
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
from config import BOT_TOKEN, BOT_USERNAME, TELEGRAM_CHANNEL_ID
from utils.logger import logger
from core.database import db
from bot_telegram.formatter import formatter


class TelegramBot:
    """Telegram bot wrapper"""
    
    def __init__(self):
        self.app: Optional[Application] = None
        self.bot_token = BOT_TOKEN
        self.channel_id = TELEGRAM_CHANNEL_ID
    
    async def initialize(self):
        """Initialize the bot application"""
        try:
            self.app = Application.builder().token(self.bot_token).build()
            
            # Register command handlers
            self.app.add_handler(CommandHandler("start", self.start_command))
            self.app.add_handler(CommandHandler("stats", self.stats_command))
            self.app.add_handler(CommandHandler("health", self.health_command))
            
            # Set bot commands menu
            await self.setup_commands()
            
            # Initialize the application
            await self.app.initialize()
            
            logger.info(f"✅ Telegram bot initialized: {BOT_USERNAME}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize bot: {e}")
            raise
    
    async def setup_commands(self):
        """Setup bot command menu"""
        commands = [
            BotCommand("start", "Welcome message"),
            BotCommand("stats", "View daily statistics"),
            BotCommand("health", "Check bot health"),
        ]
        
        if self.app:
            await self.app.bot.set_my_commands(commands)
            logger.info("✅ Bot commands configured")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        message = (
            "🔥 **Welcome to Polycool Alert Bot!**\n\n"
            "I monitor smart traders on Polymarket and alert you when they make moves.\n\n"
            "**Features:**\n"
            "💎 Track Very Smart wallets (>55% win rate)\n"
            "📊 First-time market entries only\n"
            "💰 High-value trades ($200+)\n\n"
            "**Commands:**\n"
            "/stats - View today's statistics\n"
            "/health - Check bot health\n\n"
            "Alerts are sent automatically. No setup needed! 🚀"
        )
        
        if update.message:
            await update.message.reply_text(message, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        try:
            # Fetch today's stats from database
            from datetime import date
            # Note: This is a simplified version. You'd query alert_bot_stats table
            stats = {
                'alerts_sent': db.get_current_hour_alerts(),
                'total_trades_checked': 0,
                'alerts_skipped_rate_limit': 0,
                'alerts_skipped_filters': 0,
            }
            
            message = formatter.format_stats_message(stats)
            
            if update.message:
                await update.message.reply_text(message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ Error in /stats command: {e}")
            if update.message:
                await update.message.reply_text("❌ Error fetching statistics")
    
    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command"""
        try:
            health = db.get_health_status()
            
            if health:
                status_emoji = "✅" if health['status'] == 'running' else "⚠️"
                message = (
                    f"{status_emoji} **Bot Health**\n\n"
                    f"Status: {health['status']}\n"
                    f"Version: {health['version']}\n"
                    f"Uptime: {health['uptime_seconds']}s\n"
                    f"Errors (last hour): {health['errors_last_hour']}\n"
                    f"Last Poll: {health['last_poll_at']}\n"
                    f"Last Alert: {health['last_alert_at']}"
                )
            else:
                message = "⚠️ Health status unavailable"
            
            if update.message:
                await update.message.reply_text(message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ Error in /health command: {e}")
            if update.message:
                await update.message.reply_text("❌ Error fetching health status")
    
    async def send_alert(self, message: str, parse_mode: str = 'Markdown') -> Optional[int]:
        """
        Send an alert message to the channel
        
        Args:
            message: Message to send
            parse_mode: Markdown or HTML
            
        Returns:
            Message ID if successful, None otherwise
        """
        try:
            if not self.app or not self.channel_id:
                logger.error("❌ Bot or channel ID not configured")
                return None
            
            # Validate message
            if not formatter.validate_message(message):
                logger.error("❌ Invalid message format")
                return None
            
            # Send message
            sent_message = await self.app.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Alert sent: message_id={sent_message.message_id}")
            return sent_message.message_id
        
        except Exception as e:
            logger.error(f"❌ Failed to send alert: {e}")
            return None
    
    async def shutdown(self):
        """Shutdown the bot gracefully"""
        if self.app:
            await self.app.shutdown()
            logger.info("🛑 Bot shut down")


# Global bot instance
telegram_bot = TelegramBot()

