#!/usr/bin/env python3
"""
Alert Bot Webhook Adapter
Integrates Alert Channel Bot with unified webhook-triggered notifications
"""

import logging
import os
from typing import Optional
from datetime import datetime, timezone
import asyncio

from telegram import Bot
from telegram.error import TelegramError

from database import db_manager
from core.persistence.models import SmartWalletTrade, SmartWallet

logger = logging.getLogger(__name__)


class AlertBotWebhookAdapter:
    """
    Adapter to integrate Alert Channel Bot with webhook-triggered notifications
    
    Features:
    - Sends alerts to Telegram channel instantly
    - Handles deduplication (track in alert_bot_sent table)
    - Rate limiting (10/hour, 60s intervals)
    - Beautiful message formatting
    """
    
    def __init__(self):
        self.bot = None
        self.channel_id = None
        self.enabled = False
        self._initialized = False
        
        # Rate limiting state
        self.alerts_sent_this_hour = 0
        self.current_hour = datetime.now(timezone.utc).hour
        self.last_alert_time = None
        self.max_per_hour = 10
        self.min_interval_seconds = 60
        
        logger.info("✅ Alert Bot Webhook Adapter created")
    
    def _lazy_init(self):
        """Lazy initialization to avoid import issues"""
        if self._initialized:
            return
        
        try:
            # Get config from environment
            bot_token = os.getenv("ALERT_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
            self.channel_id = os.getenv("ALERT_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
            
            if not bot_token or not self.channel_id:
                logger.warning("⚠️ Alert Bot not configured (missing ALERT_BOT_TOKEN or ALERT_CHANNEL_ID)")
                self.enabled = False
                self._initialized = True
                return
            
            # Initialize Telegram bot
            self.bot = Bot(token=bot_token)
            self.enabled = True
            
            logger.info(f"✅ Alert Bot initialized - Channel: {self.channel_id}")
            self._initialized = True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Alert Bot: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.enabled = False
            self._initialized = True
    
    async def send_alert_to_channel(self, trade: SmartWalletTrade) -> bool:
        """
        Send alert to Telegram channel for a smart wallet trade
        
        Args:
            trade: SmartWalletTrade instance
            
        Returns:
            True if alert sent successfully
        """
        try:
            self._lazy_init()
            
            if not self.enabled:
                logger.debug(f"[ALERT_WEBHOOK] Bot not enabled, skipping trade {trade.id[:16]}...")
                return False
            
            # Check if already alerted
            if await self._is_already_alerted(trade.id):
                logger.debug(f"[ALERT_WEBHOOK] Trade {trade.id[:16]}... already alerted, skipping")
                return False
            
            # Check rate limits
            if not self._can_send_alert():
                logger.warning(f"⏸️ [ALERT_WEBHOOK] Rate limit reached, skipping trade {trade.id[:16]}...")
                return False
            
            # Get wallet data for stats
            with db_manager.get_session() as db:
                wallet = db.query(SmartWallet).filter(
                    SmartWallet.address == trade.wallet_address.lower()
                ).first()
            
            # Format message
            message = self._format_alert_message(trade, wallet)
            
            # Send to channel
            logger.info(f"📢 [ALERT_WEBHOOK] Sending alert to channel for trade {trade.id[:16]}... (${float(trade.value):.0f})")
            
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            # Mark as alerted in database
            await self._mark_as_alerted(trade.id)
            
            # Update rate limiting
            self._record_alert_sent()
            
            logger.info(f"✅ [ALERT_WEBHOOK] Successfully sent alert for trade {trade.id[:16]}...")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ [ALERT_WEBHOOK] Telegram error sending alert: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ [ALERT_WEBHOOK] Error sending alert for trade {trade.id[:16] if trade else 'unknown'}...: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _format_alert_message(self, trade: SmartWalletTrade, wallet: Optional[SmartWallet]) -> str:
        """
        Format trade alert message for Telegram channel
        
        Args:
            trade: SmartWalletTrade instance
            wallet: SmartWallet instance (optional)
            
        Returns:
            Formatted message string
        """
        # Market title
        market_title = trade.market_question or "Unknown Market"
        if len(market_title) > 150:
            market_title = market_title[:147] + "..."
        
        # Wallet stats
        if wallet and wallet.win_rate:
            win_rate_pct = float(wallet.win_rate) * 100
            total_pnl = float(wallet.realized_pnl) if wallet.realized_pnl else 0
            
            if abs(total_pnl) >= 1000:
                wallet_stats = f"{win_rate_pct:.1f}% WR | ${total_pnl/1000:.1f}K profit"
            else:
                wallet_stats = f"{win_rate_pct:.1f}% WR | ${total_pnl:.0f} profit"
        else:
            wallet_stats = "Expert Trader"
        
        # Trade details
        outcome = trade.outcome or "Unknown"
        entry_price_cents = float(trade.price) * 100 if trade.price else 50
        invested = float(trade.value) if trade.value else 0
        
        # Time ago
        if trade.timestamp:
            now = datetime.now(timezone.utc)
            trade_time = trade.timestamp
            if trade_time.tzinfo is None:
                trade_time = trade_time.replace(tzinfo=timezone.utc)
            
            seconds = int((now - trade_time).total_seconds())
            if seconds < 60:
                time_ago = f"{seconds}s ago"
            elif seconds < 3600:
                time_ago = f"{seconds // 60}m ago"
            else:
                time_ago = f"{seconds // 3600}h ago"
        else:
            time_ago = "Just now"
        
        # Build message
        message = (
            f"🚨 *EXPERT TRADE ALERT*\n\n"
            f"💎 Trader: {wallet_stats}\n"
            f"🟢 BUY {outcome} @ {entry_price_cents:.0f}¢ • ${invested:,.0f} invested\n\n"
            f"📊 {market_title}\n\n"
            f"⏱️ {time_ago}"
        )
        
        return message
    
    async def _is_already_alerted(self, trade_id: str) -> bool:
        """Check if trade already alerted"""
        try:
            with db_manager.get_session() as db:
                result = db.execute(
                    "SELECT 1 FROM alert_bot_sent WHERE trade_id = :trade_id LIMIT 1",
                    {"trade_id": trade_id}
                ).fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"Error checking if trade alerted: {e}")
            return False
    
    async def _mark_as_alerted(self, trade_id: str):
        """Mark trade as alerted in database"""
        try:
            with db_manager.get_session() as db:
                db.execute(
                    """
                    INSERT INTO alert_bot_sent (trade_id, sent_at)
                    VALUES (:trade_id, :sent_at)
                    ON CONFLICT (trade_id) DO NOTHING
                    """,
                    {
                        "trade_id": trade_id,
                        "sent_at": datetime.now(timezone.utc)
                    }
                )
                db.commit()
        except Exception as e:
            logger.error(f"Error marking trade as alerted: {e}")
    
    def _can_send_alert(self) -> bool:
        """Check if we can send an alert (rate limiting)"""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        
        # Reset hourly counter if new hour
        if current_hour != self.current_hour:
            self.alerts_sent_this_hour = 0
            self.current_hour = current_hour
        
        # Check hourly limit
        if self.alerts_sent_this_hour >= self.max_per_hour:
            return False
        
        # Check minimum interval
        if self.last_alert_time:
            seconds_since_last = (now - self.last_alert_time).total_seconds()
            if seconds_since_last < self.min_interval_seconds:
                return False
        
        return True
    
    def _record_alert_sent(self):
        """Record that an alert was sent (for rate limiting)"""
        self.alerts_sent_this_hour += 1
        self.last_alert_time = datetime.now(timezone.utc)
        
        logger.debug(f"[ALERT_WEBHOOK] Alerts this hour: {self.alerts_sent_this_hour}/{self.max_per_hour}")


# Global singleton
_alert_webhook_adapter: Optional[AlertBotWebhookAdapter] = None


def get_alert_bot_webhook_adapter() -> AlertBotWebhookAdapter:
    """Get or create the Alert Bot webhook adapter singleton"""
    global _alert_webhook_adapter
    if _alert_webhook_adapter is None:
        _alert_webhook_adapter = AlertBotWebhookAdapter()
        logger.info("✅ Alert Bot Webhook Adapter initialized")
    return _alert_webhook_adapter

