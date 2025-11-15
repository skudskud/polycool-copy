#!/usr/bin/env python3
"""
Twitter Bot Webhook Adapter
Integrates Twitter Bot with unified webhook-triggered notifications
"""

import logging
from typing import Optional
from datetime import datetime, timezone

from database import db_manager
from core.persistence.models import SmartWalletTrade, SmartWallet

logger = logging.getLogger(__name__)


class TwitterBotWebhookAdapter:
    """
    Adapter to integrate Twitter Bot with webhook-triggered notifications
    
    Features:
    - Converts SmartWalletTrade → Twitter Bot format
    - Handles deduplication (check if already tweeted)
    - Respects rate limits
    - Logs tweets to database
    """
    
    def __init__(self):
        self.twitter_service = None
        self._initialized = False
        logger.info("✅ Twitter Bot Webhook Adapter created")
    
    def _lazy_init(self):
        """Lazy initialization to avoid circular imports"""
        if self._initialized:
            return
        
        try:
            from core.services.twitter_bot_service import TwitterBotService
            from core.persistence.smart_wallet_trade_repository import SmartWalletTradeRepository
            from core.persistence.smart_wallet_repository import SmartWalletRepository
            
            # Get DB session
            with db_manager.get_session() as db:
                trade_repo = SmartWalletTradeRepository(db)
                wallet_repo = SmartWalletRepository(db)
                
                self.twitter_service = TwitterBotService(
                    trade_repo=trade_repo,
                    wallet_repo=wallet_repo,
                    db_session=db,
                    market_service=None
                )
                
                logger.info(f"✅ Twitter Bot Service initialized (Enabled: {self.twitter_service.enabled}, Dry Run: {self.twitter_service.dry_run})")
                self._initialized = True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Twitter Bot Service: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._initialized = True  # Don't retry
    
    async def post_trade_tweet(self, trade: SmartWalletTrade) -> bool:
        """
        Post a tweet for a smart wallet trade
        
        Args:
            trade: SmartWalletTrade instance
            
        Returns:
            True if tweet posted successfully
        """
        try:
            self._lazy_init()
            
            if not self.twitter_service or not self.twitter_service.enabled:
                logger.debug(f"[TWITTER_WEBHOOK] Service not enabled, skipping trade {trade.id[:16]}...")
                return False
            
            # Check if already tweeted
            if trade.tweeted_at:
                logger.debug(f"[TWITTER_WEBHOOK] Trade {trade.id[:16]}... already tweeted at {trade.tweeted_at}, skipping")
                return False
            
            # Get wallet data for stats
            with db_manager.get_session() as db:
                wallet = db.query(SmartWallet).filter(
                    SmartWallet.address == trade.wallet_address.lower()
                ).first()
            
            # Convert trade to dict format expected by Twitter service
            trade_dict = {
                'id': trade.id,
                'wallet_address': trade.wallet_address,
                'market_id': trade.condition_id or trade.market_id,  # Prefer condition_id
                'market_question': trade.market_question,
                'side': trade.side,
                'outcome': trade.outcome,
                'price': float(trade.price) if trade.price else 0.5,
                'size': float(trade.size) if trade.size else 0,
                'value': float(trade.value) if trade.value else 0,
                'timestamp': trade.timestamp,
                'is_first_time': trade.is_first_time,
            }
            
            # Add wallet stats if available
            if wallet:
                trade_dict['wallet'] = {
                    'address': wallet.address,
                    'win_rate': float(wallet.win_rate) if wallet.win_rate else 0,
                    'realized_pnl': float(wallet.realized_pnl) if wallet.realized_pnl else 0,
                    'bucket_smart': wallet.bucket_smart,
                    'smartscore': float(wallet.smartscore) if wallet.smartscore else 0,
                }
            
            # Format and post tweet using Twitter service
            logger.info(f"🐦 [TWITTER_WEBHOOK] Attempting to tweet trade {trade.id[:16]}... (${trade_dict['value']:.0f})")
            
            # Use Twitter service's formatting and posting logic
            message = self.twitter_service._format_trade_tweet(trade_dict)
            success = await self._post_tweet_async(message)
            
            if success:
                # Mark as tweeted in database
                with db_manager.get_session() as db:
                    trade_obj = db.query(SmartWalletTrade).filter(
                        SmartWalletTrade.id == trade.id
                    ).first()
                    
                    if trade_obj:
                        trade_obj.tweeted_at = datetime.now(timezone.utc)
                        db.commit()
                
                logger.info(f"✅ [TWITTER_WEBHOOK] Successfully tweeted trade {trade.id[:16]}...")
                return True
            else:
                logger.warning(f"⚠️ [TWITTER_WEBHOOK] Failed to tweet trade {trade.id[:16]}...")
                return False
            
        except Exception as e:
            logger.error(f"❌ [TWITTER_WEBHOOK] Error posting tweet for trade {trade.id[:16] if trade else 'unknown'}...: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def _post_tweet_async(self, message: str) -> bool:
        """
        Post tweet asynchronously (wrapper around sync Twitter API)
        
        Args:
            message: Tweet content
            
        Returns:
            True if posted successfully
        """
        try:
            import asyncio
            
            # Twitter API is synchronous, so we run it in executor
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.twitter_service._post_tweet_sync,
                message
            )
            
            return result
        except Exception as e:
            logger.error(f"❌ [TWITTER_WEBHOOK] Error in async tweet post: {e}")
            return False


# Global singleton
_twitter_webhook_adapter: Optional[TwitterBotWebhookAdapter] = None


def get_twitter_bot_webhook_adapter() -> TwitterBotWebhookAdapter:
    """Get or create the Twitter Bot webhook adapter singleton"""
    global _twitter_webhook_adapter
    if _twitter_webhook_adapter is None:
        _twitter_webhook_adapter = TwitterBotWebhookAdapter()
        logger.info("✅ Twitter Bot Webhook Adapter initialized")
    return _twitter_webhook_adapter

