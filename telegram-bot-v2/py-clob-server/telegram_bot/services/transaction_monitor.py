#!/usr/bin/env python3
"""
TRANSACTION MONITORING SERVICE
Monitors pending transactions and updates their status when filled on-chain
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from database import SessionLocal, Transaction, User
from telegram_bot.services.user_trader import UserTrader

logger = logging.getLogger(__name__)

class TransactionMonitor:
    """
    ENTERPRISE-GRADE TRANSACTION MONITORING
    
    Features:
    - Monitor pending transactions for completion
    - Update transaction hashes when orders fill
    - Detect failed transactions
    - Provide real-time transaction status
    """
    
    def __init__(self):
        self.user_trader = None  # Will be initialized when needed
        logger.info("✅ Transaction Monitor initialized")
    
    def get_user_trader(self, user_id: int) -> Optional[UserTrader]:
        """Get UserTrader instance for a specific user"""
        try:
            # This would need to be implemented to get user's trader instance
            # For now, return None - this is a placeholder for future implementation
            return None
        except Exception as e:
            logger.error(f"❌ Error getting user trader: {e}")
            return None
    
    def get_pending_transactions(self, hours_back: int = 24) -> List[Transaction]:
        """Get transactions that might need status updates"""
        try:
            with SessionLocal() as session:
                cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
                
                # Get transactions without transaction hash (likely pending)
                pending = session.query(Transaction).filter(
                    and_(
                        Transaction.transaction_hash.is_(None),
                        Transaction.executed_at >= cutoff_time
                    )
                ).all()
                
                logger.info(f"📊 Found {len(pending)} pending transactions")
                return pending
                
        except Exception as e:
            logger.error(f"❌ Error getting pending transactions: {e}")
            return []
    
    def update_transaction_hash(self, transaction_id: int, transaction_hash: str) -> bool:
        """Update transaction with blockchain hash"""
        try:
            with SessionLocal() as session:
                transaction = session.query(Transaction).filter(
                    Transaction.id == transaction_id
                ).first()
                
                if transaction:
                    transaction.transaction_hash = transaction_hash
                    session.commit()
                    logger.info(f"✅ Updated transaction {transaction_id} with hash {transaction_hash[:20]}...")
                    return True
                else:
                    logger.warning(f"⚠️ Transaction {transaction_id} not found")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error updating transaction hash: {e}")
            return False
    
    async def monitor_pending_transactions(self):
        """Background task to monitor and update pending transactions"""
        try:
            pending_transactions = self.get_pending_transactions()
            
            for transaction in pending_transactions:
                try:
                    # Check if order has been filled and get transaction hash
                    # This would require integration with Polymarket API
                    # For now, this is a placeholder for future implementation
                    
                    logger.debug(f"🔍 Checking transaction {transaction.id} with order {transaction.order_id}")
                    
                    # TODO: Implement actual order status checking
                    # user_trader = self.get_user_trader(transaction.user_id)
                    # if user_trader:
                    #     order_status = user_trader.client.get_order(transaction.order_id)
                    #     if order_status and order_status.get('status') == 'FILLED':
                    #         tx_hash = order_status.get('transaction_hash')
                    #         if tx_hash:
                    #             self.update_transaction_hash(transaction.id, tx_hash)
                    
                except Exception as e:
                    logger.error(f"❌ Error monitoring transaction {transaction.id}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Error in monitor_pending_transactions: {e}")
    
    def get_transaction_stats(self) -> Dict:
        """Get comprehensive transaction statistics"""
        try:
            with SessionLocal() as session:
                total = session.query(Transaction).count()
                
                # Count by type
                buy_count = session.query(Transaction).filter(
                    Transaction.transaction_type == 'BUY'
                ).count()
                
                sell_count = session.query(Transaction).filter(
                    Transaction.transaction_type == 'SELL'
                ).count()
                
                # Count with/without transaction hashes
                with_hash = session.query(Transaction).filter(
                    Transaction.transaction_hash.isnot(None)
                ).count()
                
                without_hash = total - with_hash
                
                # Recent transactions (last 24 hours)
                recent_cutoff = datetime.utcnow() - timedelta(hours=24)
                recent_count = session.query(Transaction).filter(
                    Transaction.executed_at >= recent_cutoff
                ).count()
                
                return {
                    'total_transactions': total,
                    'buy_transactions': buy_count,
                    'sell_transactions': sell_count,
                    'with_transaction_hash': with_hash,
                    'without_transaction_hash': without_hash,
                    'recent_24h': recent_count,
                    'completion_rate': (with_hash / total * 100) if total > 0 else 0
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting transaction stats: {e}")
            return {}

# Global transaction monitor instance
transaction_monitor = TransactionMonitor()

def get_transaction_monitor() -> TransactionMonitor:
    """Get the global transaction monitor instance"""
    return transaction_monitor
