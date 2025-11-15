#!/usr/bin/env python3
"""
Position Service
Handles position management, P&L calculations, and position recovery
"""

import logging
import time
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


class PositionService:
    """
    Service for position-related operations
    Manages position tracking, P&L calculation, and recovery
    """

    def __init__(self, session_manager):
        """
        Initialize position service

        Args:
            session_manager: SessionManager instance for accessing user sessions
        """
        self.session_manager = session_manager

    def calculate_pnl(self, position: dict, user_trader) -> Optional[Dict]:
        """
        Calculate P&L for a position with current market prices

        Args:
            position: Position dictionary with token_id, tokens, buy_price, etc.
            user_trader: UserTrader instance to get current prices

        Returns:
            Dictionary with P&L metrics or None if error
        """
        try:
            token_id = position.get('token_id')
            if not token_id:
                return None

            # Get current sell price (what we could sell for now)
            current_sell_price = user_trader.get_live_price(token_id, "SELL")

            if current_sell_price <= 0:
                return None  # Handle API errors gracefully

            # Calculate P&L
            tokens = position['tokens']
            buy_price = position['buy_price']
            total_cost = position['total_cost']

            current_value = tokens * current_sell_price
            pnl_amount = current_value - total_cost
            pnl_percentage = (pnl_amount / total_cost) * 100 if total_cost > 0 else 0

            return {
                'current_price': current_sell_price,
                'current_value': current_value,
                'pnl_amount': pnl_amount,
                'pnl_percentage': pnl_percentage,
                'is_profit': pnl_amount > 0,
                'price_change': current_sell_price - buy_price,
                'price_change_percent': ((current_sell_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
            }

        except Exception as e:
            logger.error(f"P&L calculation error: {e}")
            return None

    def sync_wallet_positions(self, user_id: int) -> bool:
        """
        Enhanced wallet position sync with PostgreSQL recovery

        Args:
            user_id: Telegram user ID

        Returns:
            True if sync successful
        """
        try:
            # Check if user has any positions in memory
            session = self.session_manager.get(user_id)
            current_positions = session.get('positions', {})

            if not current_positions:
                logger.info(f"🔍 No positions found for user {user_id} in memory, attempting recovery")

                # Try to load from PostgreSQL
                from core.persistence import postgresql_persistence
                loaded_positions = postgresql_persistence.load_positions()

                if user_id in loaded_positions:
                    user_session = loaded_positions[user_id]
                    recovered_positions = user_session.get('positions', {})

                    if recovered_positions:
                        session['positions'] = recovered_positions
                        position_count = len(recovered_positions)
                        logger.info(f"✅ Recovered {position_count} positions for user {user_id} from PostgreSQL")
                        return True
                    else:
                        logger.info(f"⚠️ User {user_id} found in PostgreSQL but has no positions")
                        return False
                else:
                    logger.info(f"⚠️ User {user_id} not found in PostgreSQL storage")
                    return False
            else:
                logger.debug(f"✅ User {user_id} has {len(current_positions)} positions in memory")
                return True

        except Exception as e:
            logger.error(f"❌ Error syncing wallet positions: {e}")
            return False

    def recover_missing_position(self, user_id: int, market_id: str, outcome: str,
                                 tokens: int, market_data: dict) -> bool:
        """
        Manually add a missing position to user session

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: "yes" or "no"
            tokens: Number of tokens
            market_data: Market data dictionary

        Returns:
            True if recovery successful
        """
        try:
            session = self.session_manager.get(user_id)

            if 'positions' not in session:
                session['positions'] = {}

            market_id_str = str(market_id)
            session['positions'][market_id_str] = {
                'outcome': outcome,
                'tokens': tokens,
                'market': market_data,
                'buy_time': time.time(),
                'recovered': True  # Mark as recovered position
            }

            # Save positions after recovery
            self.session_manager.save_all_positions()

            logger.info(f"✅ Recovered missing position for user {user_id}: {tokens} {outcome} tokens in market {market_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error recovering position: {e}")
            return False

    def verify_transaction_success(self, order_id: str, market_id: str, outcome: str, user_id: int) -> bool:
        """
        Verify if transaction succeeded even if monitoring failed

        Args:
            order_id: Order identifier
            market_id: Market identifier
            outcome: "yes" or "no"
            user_id: Telegram user ID

        Returns:
            True if transaction verified as successful

        Note:
            This is a placeholder for future blockchain verification implementation
        """
        try:
            # TODO: Implement actual blockchain transaction verification
            # This would involve:
            # 1. Query transaction receipt by order_id/hash
            # 2. Check if transaction succeeded on-chain
            # 3. Parse transaction logs for position changes
            # 4. Add verified positions to user session

            logger.info(f"Transaction verification requested for order {order_id[:20]}... - blockchain integration pending")
            return False

        except Exception as e:
            logger.error(f"❌ Error verifying transaction: {e}")
            return False

    def get_all_positions(self, user_id: int) -> Dict:
        """
        Get all positions for a user with enterprise-grade logging
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Dictionary of all positions keyed by position_key (market_id_outcome)
        """
        try:
            session = self.session_manager.get(user_id)
            positions = session.get('positions', {})
            
            # ENTERPRISE LOGGING: Track position access patterns
            logger.info(f"🔍 POSITION ACCESS: User {user_id} has {len(positions)} positions")
            
            if positions:
                # Log position keys for debugging key format issues
                position_keys = list(positions.keys())
                logger.debug(f"🔍 POSITION KEYS: {position_keys[:5]}{'...' if len(position_keys) > 5 else ''}")
                
                # Validate position data integrity
                valid_positions = {}
                for pos_key, position in positions.items():
                    if self._validate_position_structure(position, pos_key):
                        valid_positions[pos_key] = position
                    else:
                        logger.error(f"❌ INVALID POSITION DATA: User {user_id}, key {pos_key}")
                
                logger.info(f"✅ POSITION VALIDATION: {len(valid_positions)}/{len(positions)} positions valid for user {user_id}")
                return valid_positions
            else:
                logger.info(f"📭 NO POSITIONS: User {user_id} has no positions")
                return {}
                
        except Exception as e:
            logger.error(f"❌ ERROR getting positions for user {user_id}: {e}")
            return {}
    
    def _validate_position_structure(self, position: Dict, position_key: str) -> bool:
        """
        ENTERPRISE VALIDATION: Validate position data structure
        
        Args:
            position: Position dictionary
            position_key: Position key for logging
            
        Returns:
            True if position structure is valid
        """
        try:
            required_fields = ['outcome', 'tokens', 'buy_price', 'total_cost', 'market']
            
            for field in required_fields:
                if field not in position:
                    logger.error(f"❌ POSITION MISSING FIELD: {position_key} missing {field}")
                    return False
            
            # Validate market structure
            market = position.get('market', {})
            if not isinstance(market, dict) or not market.get('question'):
                logger.error(f"❌ POSITION INVALID MARKET: {position_key} has invalid market data")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ POSITION VALIDATION ERROR: {position_key} - {e}")
            return False

    def get_position_count(self, user_id: int) -> int:
        """
        Get count of positions for a user

        Args:
            user_id: Telegram user ID

        Returns:
            Number of positions
        """
        positions = self.get_all_positions(user_id)
        return len(positions)

    def has_position(self, user_id: int, market_id: str, outcome: str) -> bool:
        """
        Check if user has a specific position

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: "yes" or "no"

        Returns:
            True if position exists
        """
        position = self.session_manager.get_position(user_id, market_id, outcome)
        return position is not None

    def add_position(self, user_id: int, market_id: str, outcome: str,
                    tokens: int, buy_price: float, total_cost: float,
                    token_id: str, market_data: dict) -> bool:
        """
        Add a new position for user

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: "yes" or "no"
            tokens: Number of tokens bought
            buy_price: Price per token
            total_cost: Total cost in USD
            token_id: Token contract ID
            market_data: Market data dictionary

        Returns:
            True if position added successfully
        """
        try:
            position = {
                'outcome': outcome,
                'tokens': tokens,
                'buy_price': buy_price,
                'total_cost': total_cost,
                'token_id': token_id,
                'market': market_data,
                'buy_time': time.time()
            }

            self.session_manager.set_position(user_id, market_id, outcome, position)
            logger.info(f"✅ Added position for user {user_id}: {tokens} {outcome} tokens in market {market_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error adding position: {e}")
            return False

    def remove_position(self, user_id: int, market_id: str, outcome: str) -> bool:
        """
        Remove a position after selling

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: "yes" or "no"

        Returns:
            True if position removed successfully
        """
        try:
            session = self.session_manager.get(user_id)
            positions = session.get('positions', {})
            position_key = f"{market_id}_{outcome.lower()}"

            if position_key in positions:
                del positions[position_key]
                logger.info(f"✅ Removed position for user {user_id}: {outcome} in market {market_id}")
                return True
            else:
                logger.warning(f"⚠️ Position not found for removal: {position_key}")
                return False

        except Exception as e:
            logger.error(f"❌ Error removing position: {e}")
            return False
    
    async def get_position_size(self, user_id: int, token_id: str) -> float:
        """
        Fetch actual position size from blockchain API
        Used for TP/SL validation before execution
        
        Args:
            user_id: Telegram user ID
            token_id: ERC-1155 token ID
            
        Returns:
            Token count (float) or 0 if position doesn't exist
        """
        try:
            # Get user's wallet
            wallet_data = self.session_manager.get_user_wallet(user_id)
            if not wallet_data:
                logger.error(f"No wallet found for user {user_id}")
                return 0.0
            
            wallet_address = wallet_data['address']
            
            # Fetch positions from blockchain
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON
            
            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON
            )
            
            positions = client.get_positions(wallet_address)
            
            # Find matching token
            for position in positions:
                if position.get('asset') == token_id:
                    return float(position.get('size', 0))
            
            # Token not found in positions
            return 0.0
            
        except Exception as e:
            logger.error(f"❌ GET POSITION SIZE ERROR: {e}")
            return 0.0


# Singleton instance
_position_service_instance = None


def get_position_service(session_manager=None) -> PositionService:
    """
    Get or create singleton PositionService instance
    
    Args:
        session_manager: SessionManager instance (required for first call)
    
    Returns:
        PositionService instance
    """
    global _position_service_instance
    
    if _position_service_instance is None:
        if session_manager is None:
            raise ValueError("session_manager required for first call to get_position_service")
        _position_service_instance = PositionService(session_manager)
    
    return _position_service_instance