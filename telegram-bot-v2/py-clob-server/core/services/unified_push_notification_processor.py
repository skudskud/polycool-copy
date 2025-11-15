#!/usr/bin/env python3
"""
Unified Push Notification Processor
Reads from smart_wallet_trades_to_share and sends push notifications
"""

import logging
import asyncio
from typing import Optional
from datetime import datetime, timezone

from database import db_manager
from core.persistence.models import SmartWalletTradesToShare
from core.services.smart_trading_notification_service import SmartTradingNotificationService

logger = logging.getLogger(__name__)


class UnifiedPushNotificationProcessor:
    """
    Processes smart_wallet_trades_to_share and sends push notifications
    
    Runs every 30 seconds to check for new qualified trades to push notify.
    Ensures UNIFIED notifications - same trades as Twitter/Alert/Command.
    """
    
    def __init__(self, notification_service: Optional[SmartTradingNotificationService] = None):
        self.notification_service = notification_service
        self.cycle_count = 0
        self.total_sent = 0
        logger.info("✅ Unified Push Notification Processor initialized")
    
    def set_notification_service(self, notification_service: SmartTradingNotificationService):
        """Set the notification service (called after Telegram bot is ready)"""
        self.notification_service = notification_service
        logger.info("✅ Push notification processor connected to notification service")
    
    async def process_cycle(self):
        """
        Run one notification processing cycle.
        Finds trades not yet push-notified and sends notifications.
        """
        try:
            if not self.notification_service or not self.notification_service._bot_app:
                logger.debug("[PUSH_PROC] Notification service not ready yet, skipping")
                return
            
            self.cycle_count += 1
            
            with db_manager.get_session() as db:
                # Get trades that haven't been push notified yet (or have low push count)
                # We track push_notification_count because multiple users get notified per trade
                pending_trades = db.query(SmartWalletTradesToShare).filter(
                    SmartWalletTradesToShare.push_notification_count == 0
                ).order_by(
                    SmartWalletTradesToShare.timestamp.desc()
                ).limit(10).all()
                
                if not pending_trades:
                    return
                
                logger.info(f"📲 [PUSH_PROC] Processing {len(pending_trades)} trades → sending to {len(self.notification_service._eligible_users_cache or [])} users")
                
                for trade in pending_trades:
                    try:
                        # Get eligible users
                        eligible_users = await self.notification_service.get_eligible_users()
                        
                        if not eligible_users:
                            continue
                        
                        # Send to all eligible users
                        notified_count = 0
                        for user_id in eligible_users:
                            try:
                                # Convert to dict format expected by notification service
                                trade_dict = {
                                    'id': trade.trade_id,
                                    'wallet_address': trade.wallet_address,
                                    'market_question': trade.market_question,
                                    'condition_id': trade.condition_id,
                                    'market_id': trade.market_id,
                                    'side': trade.side,
                                    'outcome': trade.outcome,
                                    'price': float(trade.price) if trade.price else 0.5,
                                    'size': float(trade.size) if trade.size else 0,
                                    'value': float(trade.value) if trade.value else 0,
                                    'timestamp': trade.timestamp,
                                    'is_first_time': trade.is_first_time,
                                }
                                
                                # Wallet stats
                                wallet_data = {
                                    'win_rate': float(trade.wallet_win_rate) if trade.wallet_win_rate else None,
                                    'realized_pnl': float(trade.wallet_realized_pnl) if trade.wallet_realized_pnl else None,
                                    'bucket_smart': trade.wallet_bucket,
                                    'smartscore': float(trade.wallet_smartscore) if trade.wallet_smartscore else None
                                }
                                
                                # Send notification using existing service
                                success = await self.notification_service.send_notification_direct(
                                    user_id=user_id,
                                    trade_dict=trade_dict,
                                    wallet_dict=wallet_data
                                )
                                
                                if success:
                                    notified_count += 1
                                # Don't log per-user failures - too spammy
                                
                                # Rate limiting: 25 msgs/second (buffer below Telegram's 30/sec limit)
                                await asyncio.sleep(0.04)
                                
                            except Exception as e:
                                logger.error(f"❌ [PUSH_PROC] Failed to notify user {user_id}: {e}")
                        
                        # Update smart_wallet_trades_to_share with notification count
                        trade.push_notification_count = notified_count
                        trade.last_push_notification_at = datetime.now(timezone.utc)
                        db.commit()
                        
                        self.total_sent += notified_count
                        
                        if notified_count > 0:
                            logger.info(f"✅ [PUSH_PROC] Sent {notified_count} notifications for trade {trade.trade_id[:16]}...")
                        
                    except Exception as e:
                        logger.error(f"❌ [PUSH_PROC] Error processing trade {trade.trade_id[:16]}...: {e}")
                        db.rollback()
                        continue
                
                logger.debug(f"✅ [PUSH_PROC] Cycle #{self.cycle_count} complete")
        
        except Exception as e:
            logger.error(f"❌ [PUSH_PROC] Error in processing cycle: {e}")
            import traceback
            logger.error(traceback.format_exc())


# Singleton instance
_push_processor: Optional[UnifiedPushNotificationProcessor] = None


def get_push_processor() -> UnifiedPushNotificationProcessor:
    """Get or create the push notification processor singleton"""
    global _push_processor
    if _push_processor is None:
        _push_processor = UnifiedPushNotificationProcessor()
        logger.info("✅ Unified Push Notification Processor created")
    return _push_processor

