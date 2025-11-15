#!/usr/bin/env python3
"""
HYBRID POSITION SERVICE
Ultimate position management combining blockchain verification with transaction-based calculation
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

from .blockchain_position_service import get_blockchain_position_service
from .transaction_service import get_transaction_service

logger = logging.getLogger(__name__)

class HybridPositionService:
    """
    ULTIMATE HYBRID POSITION SERVICE
    
    Features:
    - Blockchain verification for accuracy
    - Transaction-based P&L calculation
    - Automatic reconciliation
    - Complete audit trail
    - Enterprise-grade reliability
    """
    
    def __init__(self):
        self.blockchain_service = get_blockchain_position_service()
        self.transaction_service = get_transaction_service()
        logger.info("✅ Hybrid Position Service initialized")
    
    def get_verified_positions(self, user_id: int, wallet_address: str) -> Dict[str, Dict]:
        """
        Get positions with blockchain verification AND transaction-based P&L
        
        Args:
            user_id: Telegram user ID
            wallet_address: User's wallet address
            
        Returns:
            Dictionary of verified positions with complete P&L data
        """
        try:
            logger.info(f"🔍 HYBRID SCAN: Getting verified positions for user {user_id}")
            
            # Step 1: Get blockchain positions (source of truth for current holdings)
            blockchain_positions = self.blockchain_service.get_user_positions(user_id, wallet_address)
            
            # Step 2: Get transaction-based positions (source of truth for P&L)
            transaction_positions = self.transaction_service.calculate_current_positions(user_id)
            
            logger.info(f"📊 HYBRID DATA: Blockchain={len(blockchain_positions)}, Transactions={len(transaction_positions)}")
            
            # Step 3: Create hybrid positions with best of both worlds
            hybrid_positions = {}
            
            # Start with blockchain positions (these are definitely real)
            for position_key, blockchain_pos in blockchain_positions.items():
                # Get transaction data for this position if available
                transaction_pos = transaction_positions.get(position_key, {})
                
                # Create hybrid position with blockchain data + transaction P&L
                hybrid_position = {
                    # Blockchain data (source of truth for current state)
                    'tokens': blockchain_pos.get('tokens', 0),
                    'token_id': blockchain_pos.get('token_id'),
                    'market': blockchain_pos.get('market', {}),
                    'market_id': blockchain_pos.get('market_id'),
                    'outcome': blockchain_pos.get('outcome'),
                    
                    # Transaction data (source of truth for P&L)
                    'buy_price': transaction_pos.get('buy_price', blockchain_pos.get('buy_price', 0)),
                    'total_cost': transaction_pos.get('total_cost', blockchain_pos.get('total_cost', 0)),
                    'transaction_count': transaction_pos.get('transaction_count', 0),
                    
                    # Hybrid metadata
                    'source': 'hybrid_verified',
                    'blockchain_verified': True,
                    'transaction_tracked': position_key in transaction_positions,
                    'created_at': transaction_pos.get('created_at', blockchain_pos.get('created_at')),
                    'last_updated': datetime.now().isoformat()
                }
                
                # Calculate enhanced P&L if we have transaction data
                if position_key in transaction_positions:
                    pnl_data = self.transaction_service.calculate_pnl(
                        user_id, 
                        hybrid_position['market_id'], 
                        hybrid_position['outcome']
                    )
                    hybrid_position.update({
                        'realized_pnl': pnl_data.get('realized_pnl', 0),
                        'unrealized_pnl': pnl_data.get('unrealized_pnl', 0),
                        'total_pnl': pnl_data.get('total_pnl', 0)
                    })
                
                hybrid_positions[position_key] = hybrid_position
                logger.debug(f"✅ HYBRID POSITION: {position_key} - {hybrid_position['tokens']} tokens, P&L tracked: {hybrid_position['transaction_tracked']}")
            
            # Step 4: Check for transaction positions not found on blockchain (sold positions)
            for position_key, transaction_pos in transaction_positions.items():
                if position_key not in hybrid_positions and transaction_pos.get('tokens', 0) > 0:
                    logger.warning(f"⚠️ DISCREPANCY: Transaction shows {transaction_pos['tokens']} tokens for {position_key} but blockchain shows 0")
                    # This could indicate a position that was sold but not properly tracked
                    # We trust the blockchain more, so we don't add these
            
            logger.info(f"✅ HYBRID COMPLETE: {len(hybrid_positions)} verified positions with full P&L data")
            return hybrid_positions
            
        except Exception as e:
            logger.error(f"❌ HYBRID POSITION ERROR: {e}")
            # Fallback to blockchain positions
            return self.blockchain_service.get_user_positions(user_id, wallet_address)
    
    def get_position_analytics(self, user_id: int) -> Dict:
        """
        Get comprehensive position analytics
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Analytics dictionary with portfolio summary
        """
        try:
            # Get transaction history for analytics
            transactions = self.transaction_service.get_user_transactions(user_id, limit=1000)
            
            if not transactions:
                return {
                    'total_trades': 0,
                    'total_invested': 0,
                    'total_proceeds': 0,
                    'realized_pnl': 0,
                    'win_rate': 0,
                    'avg_trade_size': 0
                }
            
            # Calculate analytics
            buy_transactions = [tx for tx in transactions if tx['transaction_type'] == 'BUY']
            sell_transactions = [tx for tx in transactions if tx['transaction_type'] == 'SELL']
            
            total_invested = sum(tx['total_amount'] for tx in buy_transactions)
            total_proceeds = sum(tx['total_amount'] for tx in sell_transactions)
            realized_pnl = total_proceeds - total_invested
            
            # Calculate win rate (simplified - positions that were sold for profit)
            profitable_sells = len([tx for tx in sell_transactions if tx['price_per_token'] > 0.5])  # Simplified
            total_sells = len(sell_transactions)
            win_rate = (profitable_sells / total_sells * 100) if total_sells > 0 else 0
            
            avg_trade_size = total_invested / len(buy_transactions) if buy_transactions else 0
            
            return {
                'total_trades': len(transactions),
                'buy_trades': len(buy_transactions),
                'sell_trades': len(sell_transactions),
                'total_invested': total_invested,
                'total_proceeds': total_proceeds,
                'realized_pnl': realized_pnl,
                'win_rate': win_rate,
                'avg_trade_size': avg_trade_size,
                'roi_percentage': (realized_pnl / total_invested * 100) if total_invested > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"❌ ANALYTICS ERROR: {e}")
            return {}
    
    def reconcile_positions(self, user_id: int, wallet_address: str) -> Dict:
        """
        Reconcile blockchain vs transaction positions and report discrepancies
        
        Args:
            user_id: Telegram user ID
            wallet_address: User's wallet address
            
        Returns:
            Reconciliation report
        """
        try:
            blockchain_positions = self.blockchain_service.get_user_positions(user_id, wallet_address)
            transaction_positions = self.transaction_service.calculate_current_positions(user_id)
            
            discrepancies = []
            matches = []
            
            # Check blockchain positions against transactions
            for position_key, blockchain_pos in blockchain_positions.items():
                transaction_pos = transaction_positions.get(position_key)
                
                if not transaction_pos:
                    discrepancies.append({
                        'type': 'missing_transaction_data',
                        'position_key': position_key,
                        'blockchain_tokens': blockchain_pos['tokens'],
                        'transaction_tokens': 0,
                        'message': f"Blockchain shows {blockchain_pos['tokens']} tokens but no transaction history"
                    })
                else:
                    token_diff = abs(blockchain_pos['tokens'] - transaction_pos['tokens'])
                    if token_diff > 0.1:  # Allow small floating point differences
                        discrepancies.append({
                            'type': 'token_mismatch',
                            'position_key': position_key,
                            'blockchain_tokens': blockchain_pos['tokens'],
                            'transaction_tokens': transaction_pos['tokens'],
                            'difference': token_diff,
                            'message': f"Token count mismatch: blockchain={blockchain_pos['tokens']}, transactions={transaction_pos['tokens']}"
                        })
                    else:
                        matches.append(position_key)
            
            # Check transaction positions not found on blockchain
            for position_key, transaction_pos in transaction_positions.items():
                if position_key not in blockchain_positions and transaction_pos['tokens'] > 0.1:
                    discrepancies.append({
                        'type': 'missing_blockchain_tokens',
                        'position_key': position_key,
                        'blockchain_tokens': 0,
                        'transaction_tokens': transaction_pos['tokens'],
                        'message': f"Transactions show {transaction_pos['tokens']} tokens but blockchain shows 0"
                    })
            
            return {
                'total_blockchain_positions': len(blockchain_positions),
                'total_transaction_positions': len(transaction_positions),
                'matches': len(matches),
                'discrepancies': len(discrepancies),
                'discrepancy_details': discrepancies,
                'reconciliation_score': len(matches) / max(len(blockchain_positions), 1) * 100
            }
            
        except Exception as e:
            logger.error(f"❌ RECONCILIATION ERROR: {e}")
            return {}

# Global instance
hybrid_position_service = None

def get_hybrid_position_service():
    """Get or create the global hybrid position service"""
    global hybrid_position_service
    if hybrid_position_service is None:
        hybrid_position_service = HybridPositionService()
    return hybrid_position_service
