"""
Telegram message sender with rate limiting
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

from config import settings

logger = logging.getLogger(__name__)


class AlertSender:
    """Telegram alert sender with rate limiting"""
    
    def __init__(self):
        self.bot: Optional[Bot] = None
        self.channel_id: Optional[str] = None
        self.enabled: bool = False
        
        # Rate limiting state
        self.alerts_sent_this_hour = 0
        self.current_hour = datetime.now(timezone.utc).hour
        self.last_alert_time: Optional[datetime] = None
        
        self._initialize()
    
    def _initialize(self):
        """Initialize Telegram bot"""
        try:
            if not settings.bot_token:
                logger.warning("⚠️ BOT_TOKEN not set, alert sender disabled")
                self.enabled = False
                return
            
            if not settings.telegram_channel_id:
                logger.warning("⚠️ TELEGRAM_CHANNEL_ID not set, alert sender disabled")
                self.enabled = False
                return
            
            self.bot = Bot(token=settings.bot_token)
            self.channel_id = settings.telegram_channel_id
            self.enabled = True
            
            logger.info(f"✅ Alert sender initialized - Channel: {self.channel_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize alert sender: {e}")
            self.enabled = False
    
    def _can_send_alert(self) -> bool:
        """Check if we can send an alert (rate limiting)"""
        if not self.enabled:
            return False
        
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        
        # Reset hourly counter if new hour
        if current_hour != self.current_hour:
            self.alerts_sent_this_hour = 0
            self.current_hour = current_hour
        
        # Check hourly limit
        if self.alerts_sent_this_hour >= settings.rate_limit_max_per_hour:
            logger.warning(f"⏸️ Rate limit reached: {self.alerts_sent_this_hour}/{settings.rate_limit_max_per_hour} alerts this hour")
            return False
        
        # Check minimum interval
        if self.last_alert_time:
            seconds_since_last = (now - self.last_alert_time).total_seconds()
            if seconds_since_last < settings.rate_limit_min_interval_seconds:
                logger.debug(f"⏸️ Too soon since last alert: {seconds_since_last:.1f}s < {settings.rate_limit_min_interval_seconds}s")
                return False
        
        return True
    
    def _record_alert_sent(self):
        """Record that an alert was sent (for rate limiting)"""
        self.alerts_sent_this_hour += 1
        self.last_alert_time = datetime.now(timezone.utc)
        logger.debug(f"📊 Alerts this hour: {self.alerts_sent_this_hour}/{settings.rate_limit_max_per_hour}")
    
    async def send_alert(self, message: str) -> bool:
        """
        Send alert message to Telegram channel
        
        Args:
            message: Formatted message text
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if not self.enabled:
                logger.debug("Alert sender not enabled, skipping")
                return False
            
            if not self._can_send_alert():
                logger.warning("⏸️ Cannot send alert (rate limit or disabled)")
                return False
            
            logger.info(f"📢 Sending alert to channel {self.channel_id}...")
            
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            self._record_alert_sent()
            logger.info("✅ Alert sent successfully")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Telegram error sending alert: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error sending alert: {e}")
            return False


# Global sender instance
_alert_sender: Optional[AlertSender] = None


def get_alert_sender() -> AlertSender:
    """Get or create alert sender instance"""
    global _alert_sender
    if _alert_sender is None:
        _alert_sender = AlertSender()
    return _alert_sender

