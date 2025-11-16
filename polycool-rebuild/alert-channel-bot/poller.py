"""
Database poller for fallback when webhooks fail
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from config import settings
from database import get_recent_qualified_trades, check_trade_sent, mark_trade_sent, save_alert_history
from formatter import format_alert_message, calculate_confidence_score
from sender import get_alert_sender

logger = logging.getLogger(__name__)


class TradePoller:
    """Polls database for new qualified trades (fallback mechanism)"""
    
    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start polling loop"""
        if self.running:
            logger.warning("⚠️ Poller already running")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"✅ Trade poller started (interval: {settings.poll_interval_seconds}s)")
    
    async def stop(self):
        """Stop polling loop"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("✅ Trade poller stopped")
    
    async def _poll_loop(self):
        """Main polling loop"""
        while self.running:
            try:
                await self._check_for_new_trades()
            except Exception as e:
                logger.error(f"❌ Error in poll loop: {e}")
            
            # Wait before next poll
            await asyncio.sleep(settings.poll_interval_seconds)
    
    async def _check_for_new_trades(self):
        """Check for new qualified trades and send alerts"""
        try:
            # Get recent qualified trades
            trades = await get_recent_qualified_trades(max_age_minutes=settings.max_age_minutes)
            
            if not trades:
                logger.debug("No new qualified trades found")
                return
            
            logger.info(f"🔍 Found {len(trades)} qualified trades, processing...")
            
            sender = get_alert_sender()
            
            for trade in trades:
                try:
                    trade_id = trade.get('trade_id')
                    trade_value = trade.get('value', 0.0)
                    
                    # Filter: Skip trades below minimum trade value (double-check)
                    if trade_value < settings.min_trade_value:
                        logger.debug(f"⏭️ Trade {trade_id[:20]}... filtered (value: ${trade_value:.2f} < ${settings.min_trade_value:.2f})")
                        continue
                    
                    # Filter: Skip trades below minimum smart score (double-check)
                    smart_score = trade.get('risk_score')  # risk_score is smart_score
                    if smart_score is None or smart_score < settings.min_smart_score:
                        logger.debug(f"⏭️ Trade {trade_id[:20]}... filtered (smart_score: {smart_score} < {settings.min_smart_score})")
                        continue
                    
                    # Filter: Skip trades with unknown outcome or missing market title
                    if trade.get('outcome') == 'UNKNOWN' or not trade.get('market_title'):
                        logger.debug(f"⏭️ Trade {trade_id[:20]}... filtered (outcome: {trade.get('outcome')}, market: {trade.get('market_title')})")
                        continue
                    
                    # Double-check deduplication (race condition protection)
                    if await check_trade_sent(trade_id):
                        logger.debug(f"⏭️ Trade {trade_id[:20]}... already sent, skipping")
                        continue
                    
                    # Format message
                    message = format_alert_message(trade)
                    
                    # Send to Telegram channel
                    success = await sender.send_alert(message)
                    
                    if not success:
                        logger.warning(f"⚠️ Failed to send alert for trade {trade_id[:20]}... (rate limit?)")
                        continue
                    
                    # Mark as sent
                    await mark_trade_sent(trade_id)
                    
                    # Calculate confidence score for history
                    confidence_score = calculate_confidence_score(trade.get('win_rate'))
                    
                    # Save to history
                    await save_alert_history(
                        trade_id=trade_id,
                        market_id=trade.get('market_id'),
                        market_title=trade.get('market_title'),
                        wallet_address=trade.get('wallet_address'),
                        wallet_name=trade.get('wallet_name'),
                        win_rate=trade.get('win_rate'),
                        smart_score=trade.get('risk_score'),  # risk_score is smart_score
                        confidence_score=confidence_score,
                        outcome=trade.get('outcome'),
                        side=trade.get('side'),
                        price=trade.get('price'),
                        value=trade.get('value'),
                        amount_usdc=trade.get('value'),
                        message_text=message
                    )
                    
                    logger.info(f"✅ Sent alert for trade {trade_id[:20]}... (via poller)")
                    
                    # Small delay between alerts to respect rate limits
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing trade {trade.get('trade_id', 'unknown')[:20]}...: {e}")
                    continue
            
            logger.info(f"✅ Processed {len(trades)} trades from poller")
            
        except Exception as e:
            logger.error(f"❌ Error checking for new trades: {e}")


# Global poller instance
_poller: Optional[TradePoller] = None


def get_poller() -> TradePoller:
    """Get or create poller instance"""
    global _poller
    if _poller is None:
        _poller = TradePoller()
    return _poller

