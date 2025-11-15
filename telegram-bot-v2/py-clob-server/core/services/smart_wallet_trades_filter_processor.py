#!/usr/bin/env python3
"""
Smart Wallet Trades Filter Processor
Processes smart_wallet_trades and identifies qualified trades for sharing across all notification systems.

Single source of truth for filtering logic - ALL 4 systems (Twitter, Alert, Push, /smart_trading)
will read from smart_wallet_trades_to_share table populated by this processor.
"""

import logging
import asyncio
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from database import db_manager
from core.persistence.models import SmartWalletTrade, SmartWallet, SmartWalletTradesToShare

logger = logging.getLogger(__name__)

# Crypto price market patterns to exclude
CRYPTO_PRICE_PATTERNS = [
    'up or down',
    'higher or lower',
    'price of bitcoin',
    'price of ethereum',
    'price of eth ',
    'price of solana',
    'price of sol ',
    'price of xrp',
    'price of bnb',
    'price of cardano',
    'price of ada ',
    'price of dogecoin',
    'price of doge',
    'bitcoin above',
    'bitcoin below',
    'ethereum above',
    'ethereum below',
    'eth above',
    'eth below',
    'solana above',
    'solana below',
    'sol above',
    'sol below',
    'xrp above',
    'xrp below',
    'bnb above',
    'bnb below',
    'next 15 minutes',
    'next 30 minutes',
    'next hour',
    'in the next hour',
    'in the next 4 hours'
]


class SmartWalletTradesFilterProcessor:
    """
    Processes smart_wallet_trades and filters for qualified shareable trades.
    
    Unified filtering logic ensures ALL 4 notification systems see SAME trades.
    """
    
    def __init__(self):
        self.cycle_count = 0
        self.total_processed = 0
        self.total_qualified = 0
        self.rejection_stats = {
            'not_buy': 0,
            'not_first_time': 0,
            'value_too_low': 0,
            'no_market_title': 0,
            'not_very_smart': 0,
            'crypto_price_market': 0,
            'too_old': 0,
            'already_shared': 0
        }
    
    async def process_cycle(self):
        """
        Run one filter processing cycle.
        Finds recent unprocessed trades and adds qualified ones to share table.
        """
        try:
            self.cycle_count += 1
            cycle_start = datetime.now(timezone.utc)
            
            logger.debug(f"🔄 [FILTER] Starting cycle #{self.cycle_count}")
            
            with db_manager.get_session() as db:
                # Get recent trades not yet in share table (last 5 minutes)
                cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)
                
                # Get already shared trade_ids for exclusion
                shared_trade_ids = {
                    row[0] for row in db.query(SmartWalletTradesToShare.trade_id).all()
                }
                
                # Query recent unprocessed trades
                recent_trades = db.query(SmartWalletTrade).filter(
                    SmartWalletTrade.timestamp >= cutoff_time,
                    SmartWalletTrade.id.notin_(shared_trade_ids) if shared_trade_ids else True
                ).order_by(SmartWalletTrade.timestamp.desc()).limit(100).all()
                
                if not recent_trades:
                    logger.debug(f"[FILTER] No new trades to process")
                    return
                
                logger.debug(f"🔍 [FILTER] Processing {len(recent_trades)} recent trades...")
                
                processed = 0
                qualified = 0
                
                for trade in recent_trades:
                    self.total_processed += 1
                    processed += 1
                    
                    # Get wallet data
                    wallet = db.query(SmartWallet).filter(
                        SmartWallet.address == trade.wallet_address.lower()
                    ).first()
                    
                    # Apply unified filters
                    is_qualified, rejection_reason = self._meets_sharing_criteria(trade, wallet)
                    
                    if not is_qualified:
                        if rejection_reason:
                            self.rejection_stats[rejection_reason] += 1
                        continue
                    
                    # Insert into share table
                    try:
                        # 🔧 FIX: Use FULL trade_id from Subsquid (including suffix)
                        # The UNIQUE constraint on trade_id will handle any true duplicates
                        # Different suffixes (_300, _344) represent different events in same transaction
                        # Don't strip them - they're meaningful identifiers from Subsquid!
                        
                        shareable_trade = SmartWalletTradesToShare(
                            trade_id=trade.id,  # Use full ID, no stripping
                            wallet_address=trade.wallet_address,
                            wallet_bucket=wallet.bucket_smart if wallet else None,
                            wallet_win_rate=wallet.win_rate if wallet else None,
                            wallet_smartscore=wallet.smartscore if wallet else None,
                            wallet_realized_pnl=wallet.realized_pnl if wallet else None,
                            side=trade.side,
                            outcome=trade.outcome,
                            price=trade.price,
                            size=trade.size,
                            value=trade.value,
                            market_id=trade.market_id,  # ✅ FIX: Use numeric market_id from smart_wallet_trades (works with database lookups)
                            condition_id=trade.condition_id,
                            market_question=trade.market_question,
                            timestamp=trade.timestamp,
                            is_first_time=trade.is_first_time,
                            created_at=datetime.now(timezone.utc)
                        )
                        
                        db.add(shareable_trade)
                        db.commit()
                        
                        qualified += 1
                        self.total_qualified += 1
                        
                        logger.debug(
                            f"✅ [FILTER] Qualified trade: {trade.id[:16]}... "
                            f"| ${float(trade.value):.0f} | {trade.market_question[:50]}..."
                        )
                        
                    except Exception as e:
                        db.rollback()
                        if 'duplicate key' in str(e).lower():
                            self.rejection_stats['already_shared'] += 1
                        else:
                            logger.error(f"❌ [FILTER] Error inserting trade {trade.id[:16]}...: {e}")
                
                duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
                
                logger.debug(
                    f"✅ [FILTER] Cycle #{self.cycle_count} complete in {duration:.2f}s: "
                    f"{processed} processed, {qualified} qualified"
                )
                
                # Log stats every 10 cycles
                if self.cycle_count % 10 == 0:
                    self._log_statistics()
        
        except Exception as e:
            logger.error(f"❌ [FILTER] Error in processing cycle: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _meets_sharing_criteria(
        self, 
        trade: SmartWalletTrade, 
        wallet: Optional[SmartWallet]
    ) -> tuple[bool, Optional[str]]:
        """
        UNIFIED FILTERING LOGIC - Single source of truth for ALL systems
        
        Returns:
            (is_qualified, rejection_reason)
        """
        
        # 1. Must be BUY
        if not trade.side or trade.side.upper() != 'BUY':
            return (False, 'not_buy')
        
        # 2. Must be first-time entry
        if not trade.is_first_time:
            return (False, 'not_first_time')
        
        # 3. Must be >= $400 (raised to filter quality trades)
        if not trade.value or float(trade.value) < 400.0:
            return (False, 'value_too_low')
        
        # 4. Must have market title
        if not trade.market_question or trade.market_question.strip() == '':
            return (False, 'no_market_title')
        
        # 5. Must be "Very Smart" wallet
        if not wallet or wallet.bucket_smart != 'Very Smart':
            return (False, 'not_very_smart')
        
        # 6. Exclude crypto price markets
        question_lower = trade.market_question.lower()
        if any(pattern in question_lower for pattern in CRYPTO_PRICE_PATTERNS):
            return (False, 'crypto_price_market')
        
        # 7. Freshness check (< 5 minutes old)
        if trade.timestamp:
            now = datetime.now(timezone.utc)
            trade_time = trade.timestamp
            if trade_time.tzinfo is None:
                trade_time = trade_time.replace(tzinfo=timezone.utc)
            
            age_seconds = (now - trade_time).total_seconds()
            if age_seconds > 300:  # 5 minutes
                return (False, 'too_old')
        
        # ALL criteria met!
        return (True, None)
    
    def _log_statistics(self):
        """Log processing statistics"""
        logger.info(
            f"📊 [FILTER] Statistics after {self.cycle_count} cycles:\n"
            f"   Total processed: {self.total_processed}\n"
            f"   Total qualified: {self.total_qualified} ({self.total_qualified/self.total_processed*100:.1f}%)\n"
            f"   Rejections:\n"
            f"     - Not BUY: {self.rejection_stats['not_buy']}\n"
            f"     - Not first-time: {self.rejection_stats['not_first_time']}\n"
            f"     - Value < $400: {self.rejection_stats['value_too_low']}\n"
            f"     - No market title: {self.rejection_stats['no_market_title']}\n"
            f"     - Not Very Smart: {self.rejection_stats['not_very_smart']}\n"
            f"     - Crypto price market: {self.rejection_stats['crypto_price_market']}\n"
            f"     - Too old: {self.rejection_stats['too_old']}\n"
            f"     - Already shared: {self.rejection_stats['already_shared']}"
        )


# Singleton instance
_filter_processor: Optional[SmartWalletTradesFilterProcessor] = None


def get_filter_processor() -> SmartWalletTradesFilterProcessor:
    """Get or create the filter processor singleton"""
    global _filter_processor
    if _filter_processor is None:
        _filter_processor = SmartWalletTradesFilterProcessor()
        logger.info("✅ Smart Wallet Trades Filter Processor initialized")
    return _filter_processor

