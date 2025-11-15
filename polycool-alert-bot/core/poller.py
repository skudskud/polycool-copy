"""
Poller - Main logic for checking and alerting trades
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any
from config import POLL_INTERVAL_SECONDS, MAX_TRADES_PER_POLL, DRY_RUN
from utils.logger import logger
from utils.metrics import metrics
from core.database import db
from core.filters import TradeFilters, rate_limiter
from bot_telegram.bot import telegram_bot
from bot_telegram.formatter import formatter


class TradePoller:
    """
    Main poller that:
    1. Fetches pending trades
    2. Applies filters
    3. Checks rate limits
    4. Sends alerts
    """
    
    def __init__(self):
        self.is_running = False
        self.poll_count = 0
        
        # NEW: In-memory cache to prevent duplicate alerts
        # Prevents race condition where DB update hasn't committed yet
        self._recently_alerted = set()  # Set of trade IDs alerted in last 5 minutes
        self._last_cache_clear = datetime.now(timezone.utc)
    
    async def start(self):
        """Start the polling loop"""
        logger.info("🚀 Starting trade poller...")
        self.is_running = True
        
        # Initialize bot
        await telegram_bot.initialize()
        
        # Main polling loop
        while self.is_running:
            try:
                await self.poll_once()
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logger.info("⚠️ Keyboard interrupt received")
                break
            except Exception as e:
                logger.error(f"❌ Error in polling loop: {e}")
                metrics.increment_errors()
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        
        # Cleanup
        await self.stop()
    
    async def poll_once(self):
        """Execute one polling cycle"""
        self.poll_count += 1
        metrics.update_last_poll()
        
        # Clear alert cache every 5 minutes to prevent memory growth
        now = datetime.now(timezone.utc)
        if (now - self._last_cache_clear).total_seconds() > 300:  # 5 minutes
            cache_size = len(self._recently_alerted)
            if cache_size > 0:
                logger.debug(f"🧹 Clearing alert cache ({cache_size} entries)")
            self._recently_alerted.clear()
            self._last_cache_clear = now
        
        logger.info(f"🔄 Poll #{self.poll_count} - Checking for new trades...")
        
        # Fetch pending trades
        pending_trades = db.fetch_pending_trades(limit=MAX_TRADES_PER_POLL)
        
        if not pending_trades:
            logger.info("✅ No pending trades")
            self._update_health_status()
            return
        
        logger.info(f"📋 Found {len(pending_trades)} pending trade(s)")
        metrics.increment_trades_checked(len(pending_trades))
        
        # Process each trade
        alerts_sent_this_cycle = 0
        
        for trade in pending_trades:
            # Check in-memory cache FIRST (prevents race conditions)
            if trade['id'] in self._recently_alerted:
                logger.debug(f"⏭️  Trade {trade['id'][:10]} in recent cache (skip)")
                continue
            
            # Check if already alerted (double-check in database)
            if db.is_trade_alerted(trade['id']):
                logger.debug(f"⏭️  Trade {trade['id'][:10]} already alerted (skip)")
                continue
            
            # Apply quality filters
            passes, reason = TradeFilters.passes_filters(trade)
            TradeFilters.log_filter_result(trade, passes, reason)
            
            if not passes:
                metrics.increment_skipped_filters()
                continue
            
            # Check rate limit
            can_send, limit_reason = rate_limiter.can_send_alert()
            
            if not can_send:
                logger.warning(f"⏸️  Rate limit: {limit_reason}")
                metrics.increment_skipped_rate_limit()
                rate_limiter.record_alert_skipped()
                # Stop processing more trades this cycle
                break
            
            # Send alert
            success = await self._send_trade_alert(trade)
            
            if success:
                alerts_sent_this_cycle += 1
                metrics.increment_alerts_sent()
                rate_limiter.record_alert_sent()
                
                # Add to in-memory cache to prevent duplicate alerts
                self._recently_alerted.add(trade['id'])
                
                # Wait minimum interval before next alert
                from config import RATE_LIMITS
                wait_time = RATE_LIMITS['min_interval_seconds']
                logger.info(f"⏳ Waiting {wait_time}s before next alert...")
                await asyncio.sleep(wait_time)
            else:
                metrics.increment_errors()
        
        # Log summary
        logger.info(
            f"✅ Poll complete: {alerts_sent_this_cycle} sent, "
            f"{len(pending_trades) - alerts_sent_this_cycle} skipped"
        )
        
        rate_limiter.log_rate_status()
        
        # Update database stats
        self._update_stats()
        self._update_health_status()
    
    async def _send_trade_alert(self, trade: Dict[str, Any]) -> bool:
        """
        Send alert for a trade
        
        Args:
            trade: Trade dictionary
            
        Returns:
            True if successful
        """
        try:
            trade_id = trade['id']
            trade_short = trade_id[:10]
            
            # Format message
            message = formatter.format_alert(trade)
            
            # DRY RUN mode
            if DRY_RUN:
                logger.info(f"🧪 [DRY RUN] Would send alert for trade {trade_short}")
                logger.debug(f"Message preview:\n{message[:200]}...")
                return True
            
            # Send to Telegram
            message_id = await telegram_bot.send_alert(message)
            
            if message_id:
                # Mark as alerted in database
                db.mark_trade_alerted(
                    trade_id=trade_id,
                    wallet_address=trade['wallet_address'],
                    market_question=trade['market_question'],
                    value=float(trade['value']),
                    telegram_message_id=message_id,
                    telegram_chat_id=telegram_bot.channel_id
                )
                
                logger.info(
                    f"✅ Alert sent for trade {trade_short} "
                    f"(${trade['value']:,.0f}, msg_id={message_id})"
                )
                return True
            else:
                logger.error(f"❌ Failed to send alert for trade {trade_short}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Error sending alert: {e}")
            return False
    
    def _update_stats(self):
        """Update database statistics"""
        try:
            summary = metrics.get_summary()
            
            db.update_daily_stats(
                trades_checked=summary['trades_checked'],
                alerts_sent=summary['alerts_sent'],
                skipped_rate_limit=summary['alerts_skipped_rate_limit'],
                skipped_filters=summary['alerts_skipped_filters']
            )
        except Exception as e:
            logger.error(f"❌ Error updating stats: {e}")
    
    def _update_health_status(self):
        """Update health status in database"""
        try:
            summary = metrics.get_summary()
            
            db.update_health_status(
                status='running',
                last_poll_at=summary['last_poll_at'],
                last_alert_at=summary['last_alert_at'],
                errors_last_hour=summary['errors'],
                uptime_seconds=summary['uptime_seconds']
            )
        except Exception as e:
            logger.error(f"❌ Error updating health: {e}")
    
    async def stop(self):
        """Stop the poller"""
        logger.info("🛑 Stopping poller...")
        self.is_running = False
        
        # Update health to stopped
        db.update_health_status(status='stopped', uptime_seconds=metrics.get_uptime_seconds())
        
        # Shutdown bot
        await telegram_bot.shutdown()
        
        # Disconnect database
        db.disconnect()
        
        # Log final metrics
        metrics.log_summary()
        
        logger.info("✅ Poller stopped")


# Global poller instance
poller = TradePoller()

