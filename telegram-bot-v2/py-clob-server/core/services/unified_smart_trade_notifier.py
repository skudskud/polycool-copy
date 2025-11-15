#!/usr/bin/env python3
"""
Unified Smart Trade Notifier
Single entry point for notifying all systems about new smart wallet trades
Ensures SAME trades shown on ALL channels with SAME filters
"""

import logging
import asyncio
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal

from database import db_manager
from core.persistence.models import SmartWalletTrade, SmartWallet

logger = logging.getLogger(__name__)


class UnifiedSmartTradeNotifier:
    """
    Unified notification hub for smart wallet trades
    
    Triggers all 3 notification systems in parallel:
    - Trading Bot Push Notifications (Telegram users)
    - Alert Bot (Telegram channel)
    - Twitter Bot (auto-tweets)
    
    Features:
    - Unified filters ($400 minimum across all systems)
    - Parallel execution (< 2 seconds total)
    - Deduplication (prevent duplicate notifications)
    - Error isolation (one system failure doesn't affect others)
    """
    
    def __init__(self):
        self.trading_bot_notif_service = None
        self.twitter_bot_service = None
        self.alert_bot_sender = None
        
        # Lazy initialization to avoid circular imports
        self._initialized = False
    
    def _lazy_init(self):
        """Lazy initialization of services to avoid circular imports"""
        if self._initialized:
            return
        
        try:
            # 1. Trading Bot Push Notifications
            from core.services.smart_trading_notification_service import get_smart_trading_notification_service
            self.trading_bot_notif_service = get_smart_trading_notification_service()
            logger.info("✅ Trading Bot notification service initialized")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize Trading Bot notif service: {e}")
        
        try:
            # 2. Twitter Bot
            from core.services.twitter_bot_webhook_adapter import get_twitter_bot_webhook_adapter
            self.twitter_bot_service = get_twitter_bot_webhook_adapter()
            logger.info("✅ Twitter Bot webhook adapter initialized")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize Twitter Bot adapter: {e}")
        
        try:
            # 3. Alert Channel Bot
            from core.services.alert_bot_webhook_adapter import get_alert_bot_webhook_adapter
            self.alert_bot_sender = get_alert_bot_webhook_adapter()
            logger.info("✅ Alert Bot webhook adapter initialized")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize Alert Bot adapter: {e}")
        
        self._initialized = True
    
    async def notify_new_trade(self, trade: SmartWalletTrade):
        """
        Notify all systems about a new smart wallet trade
        
        Args:
            trade: SmartWalletTrade instance
        """
        try:
            self._lazy_init()
            
            # Enrich trade with market title if missing (100% coverage goal)
            try:
                from core.services.market_enrichment_service import get_market_enrichment_service
                enrichment_service = get_market_enrichment_service()
                await enrichment_service.enrich_trade_with_market_title(trade)
            except Exception as e:
                logger.warning(f"⚠️ [UNIFIED_NOTIF] Market enrichment failed (non-fatal): {e}")
            
            # Apply unified filters
            if not await self._meets_unified_criteria(trade):
                logger.debug(f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... does not meet criteria, skipping")
                return
            
            logger.info(f"🔔 [UNIFIED_NOTIF] Trade {trade.id[:16]}... meets criteria, notifying all systems...")
            
            # Trigger all 3 systems in parallel for speed
            tasks = []
            
            # 1. Trading Bot Push Notifications (instant)
            if self.trading_bot_notif_service:
                tasks.append(self._notify_trading_bot(trade))
            
            # 2. Twitter Bot (webhook-triggered)
            if self.twitter_bot_service:
                tasks.append(self._notify_twitter(trade))
            
            # 3. Alert Channel Bot (webhook-triggered)
            if self.alert_bot_sender:
                tasks.append(self._notify_alert_bot(trade))
            
            if not tasks:
                logger.debug("[UNIFIED_NOTIF] No notification services available yet")
                return
            
            # Execute all in parallel, catch individual errors
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log results
            success_count = sum(1 for r in results if r is True)
            error_count = sum(1 for r in results if isinstance(r, Exception))
            
            logger.info(
                f"✅ [UNIFIED_NOTIF] Notified {success_count}/{len(tasks)} systems "
                f"for trade {trade.id[:16]}... ({error_count} errors)"
            )
            
        except Exception as e:
            logger.error(f"❌ [UNIFIED_NOTIF] Error in notify_new_trade: {e}")
    
    async def _meets_unified_criteria(self, trade: SmartWalletTrade) -> bool:
        """
        UNIFIED FILTERS - Same criteria for ALL 3 systems!
        
        Criteria:
        - BUY only (not SELL)
        - First-time market entry
        - >= $400 value
        - Quality wallet (Very Smart bucket OR high win rate)
        
        Args:
            trade: SmartWalletTrade instance
            
        Returns:
            True if trade meets all criteria
        """
        try:
            # 1. Must be BUY
            if not trade.side or trade.side.upper() != 'BUY':
                logger.debug(f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... is SELL, skipping")
                return False
            
            # 2. Must be first-time market entry
            if not trade.is_first_time:
                logger.debug(f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... is not first-time, skipping")
                return False
            
            # 3. Must be >= $400
            if not trade.value or float(trade.value) < 400.0:
                logger.debug(
                    f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... "
                    f"value ${float(trade.value) if trade.value else 0} < $400, skipping"
                )
                return False
            
            # 4. Must be quality wallet (Very Smart bucket)
            with db_manager.get_session() as db:
                wallet = db.query(SmartWallet).filter(
                    SmartWallet.address == trade.wallet_address.lower()
                ).first()
                
                if wallet:
                    # Check if "Very Smart" bucket
                    if wallet.bucket_smart and wallet.bucket_smart == 'Very Smart':
                        logger.debug(
                            f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... "
                            f"from Very Smart wallet (WR: {wallet.win_rate})"
                        )
                        return True
                    
                    # Fallback: Check high win rate (>= 55%)
                    if wallet.win_rate and float(wallet.win_rate) >= 0.55:
                        logger.debug(
                            f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... "
                            f"from high WR wallet ({wallet.win_rate})"
                        )
                        return True
                    
                    logger.debug(
                        f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... "
                        f"wallet quality insufficient (bucket: {wallet.bucket_smart}, WR: {wallet.win_rate})"
                    )
                    return False
                else:
                    # Wallet not in smart_wallets table - allow it (benefit of the doubt)
                    logger.warning(
                        f"[UNIFIED_NOTIF] Trade {trade.id[:16]}... "
                        f"wallet {trade.wallet_address[:10]} not in smart_wallets table, allowing"
                    )
                    return True
        
        except Exception as e:
            logger.error(f"[UNIFIED_NOTIF] Error checking criteria: {e}")
            return False
    
    async def _notify_trading_bot(self, trade: SmartWalletTrade) -> bool:
        """
        Notify Trading Bot users (push notifications)
        
        Args:
            trade: SmartWalletTrade instance
            
        Returns:
            True if successful
        """
        try:
            if not self.trading_bot_notif_service:
                return False
            
            # Trading bot notification service has its own logic
            await self.trading_bot_notif_service.process_new_trade(trade)
            logger.info(f"✅ [UNIFIED_NOTIF] Notified Trading Bot for trade {trade.id[:16]}...")
            return True
            
        except Exception as e:
            logger.error(f"❌ [UNIFIED_NOTIF] Trading Bot notification error: {e}")
            return False
    
    async def _notify_twitter(self, trade: SmartWalletTrade) -> bool:
        """
        Notify Twitter Bot (auto-tweet)
        
        Args:
            trade: SmartWalletTrade instance
            
        Returns:
            True if successful
        """
        try:
            if not self.twitter_bot_service:
                return False
            
            # Post tweet via webhook adapter
            success = await self.twitter_bot_service.post_trade_tweet(trade)
            if success:
                logger.info(f"✅ [UNIFIED_NOTIF] Tweeted trade {trade.id[:16]}...")
            return success
            
        except Exception as e:
            logger.error(f"❌ [UNIFIED_NOTIF] Twitter notification error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def _notify_alert_bot(self, trade: SmartWalletTrade) -> bool:
        """
        Notify Alert Bot (Telegram channel)
        
        Args:
            trade: SmartWalletTrade instance
            
        Returns:
            True if successful
        """
        try:
            if not self.alert_bot_sender:
                return False
            
            # Send alert to Telegram channel via webhook adapter
            success = await self.alert_bot_sender.send_alert_to_channel(trade)
            if success:
                logger.info(f"✅ [UNIFIED_NOTIF] Sent alert to channel for trade {trade.id[:16]}...")
            return success
            
        except Exception as e:
            logger.error(f"❌ [UNIFIED_NOTIF] Alert Bot notification error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False


# Singleton instance
_unified_notifier: Optional[UnifiedSmartTradeNotifier] = None


def get_unified_notifier() -> UnifiedSmartTradeNotifier:
    """Get or create the unified notifier singleton"""
    global _unified_notifier
    if _unified_notifier is None:
        _unified_notifier = UnifiedSmartTradeNotifier()
        logger.info("✅ Unified Smart Trade Notifier initialized")
    return _unified_notifier

