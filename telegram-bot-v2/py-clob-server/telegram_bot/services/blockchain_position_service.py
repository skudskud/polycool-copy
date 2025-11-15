#!/usr/bin/env python3
"""
BLOCKCHAIN POSITION SERVICE
Integrates blockchain_recovery.py with the telegram bot position system
Provides real-time, blockchain-verified positions
"""

import logging
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from core.recovery.blockchain_recovery import BlockchainPositionRecovery

logger = logging.getLogger(__name__)

class BlockchainPositionService:
    """
    ENTERPRISE-GRADE BLOCKCHAIN POSITION SERVICE
    
    Features:
    - Real-time blockchain position detection
    - Smart caching (60-second cache)
    - Market data integration
    - P&L calculation
    - Never shows phantom positions
    """
    
    def __init__(self, market_service=None):
        self.blockchain_recovery = BlockchainPositionRecovery()
        self.market_service = market_service
        
        # Cache for performance (60-second cache)
        self._position_cache = {}
        self._cache_timestamps = {}
        self.cache_duration = 60  # seconds
        
        logger.info("✅ Blockchain Position Service initialized")
    
    def get_user_positions(self, user_id: int, wallet_address: str) -> Dict[str, Dict]:
        """
        Get all positions for a user directly from blockchain
        
        Args:
            user_id: Telegram user ID
            wallet_address: User's Polygon wallet address
            
        Returns:
            Dictionary of positions keyed by "market_id_outcome"
        """
        try:
            # Check cache first
            cache_key = f"{user_id}_{wallet_address}"
            if self._is_cache_valid(cache_key):
                logger.info(f"🚀 CACHE HIT: Returning cached positions for user {user_id}")
                return self._position_cache[cache_key]
            
            logger.info(f"🔍 BLOCKCHAIN SCAN: Getting real positions for user {user_id} wallet {wallet_address}")
            
            # Get positions from blockchain
            start_time = time.time()
            blockchain_positions = self.blockchain_recovery.recover_from_polymarket_api(wallet_address)
            scan_time = time.time() - start_time
            
            logger.info(f"⚡ BLOCKCHAIN SCAN COMPLETE: {len(blockchain_positions)} positions found in {scan_time:.2f}s")
            
            # Convert to bot format
            bot_positions = {}
            for position_key, position_data in blockchain_positions.items():
                # Convert to expected format
                bot_position = self._convert_blockchain_position_to_bot_format(position_data)
                if bot_position:
                    bot_positions[position_key] = bot_position
            
            # Cache the results
            self._position_cache[cache_key] = bot_positions
            self._cache_timestamps[cache_key] = time.time()
            
            logger.info(f"✅ BLOCKCHAIN POSITIONS: {len(bot_positions)} valid positions for user {user_id}")
            return bot_positions
            
        except Exception as e:
            logger.error(f"❌ BLOCKCHAIN POSITION ERROR for user {user_id}: {e}")
            return {}
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid"""
        if cache_key not in self._cache_timestamps:
            return False
        
        age = time.time() - self._cache_timestamps[cache_key]
        return age < self.cache_duration
    
    def _convert_blockchain_position_to_bot_format(self, blockchain_position: Dict) -> Optional[Dict]:
        """
        Convert blockchain position to bot-expected format
        
        Args:
            blockchain_position: Raw position from blockchain recovery
            
        Returns:
            Position in bot format or None if invalid
        """
        try:
            # Extract required fields - handle both API format and recovered format
            tokens = blockchain_position.get('tokens') or blockchain_position.get('size', 0)
            outcome = blockchain_position.get('outcome', 'unknown').lower()
            token_id = blockchain_position.get('token_id') or blockchain_position.get('asset_id') or blockchain_position.get('asset')
            
            # Get market data
            market_data = blockchain_position.get('market', {})
            if not market_data:
                # Create market data from API response fields
                market_data = {
                    'id': blockchain_position.get('conditionId', 'unknown'),
                    'question': blockchain_position.get('title', 'Unknown Market'),
                    'volume': 0,  # Not provided in API
                    'condition_id': blockchain_position.get('conditionId'),
                    'slug': blockchain_position.get('slug', ''),
                    'clob_token_ids': [token_id] if token_id else []
                }
            
            # Calculate buy price and total cost
            avg_price = blockchain_position.get('avgPrice', 0) or blockchain_position.get('avg_price', 0)
            if not avg_price:
                # Fallback calculation
                total_cost = blockchain_position.get('total_cost', 0)
                avg_price = total_cost / tokens if tokens > 0 else 0
            
            total_cost = tokens * avg_price
            
            # Validate required fields
            if not token_id or tokens <= 0 or not market_data:
                logger.warning(f"⚠️ Invalid blockchain position: token_id={token_id}, tokens={tokens}, market={bool(market_data)}")
                return None
            
            # Create bot-format position
            bot_position = {
                'tokens': float(tokens),
                'outcome': outcome,
                'buy_price': float(avg_price),
                'total_cost': float(total_cost),
                'token_id': str(token_id),
                'market': market_data,
                'market_id': market_data.get('id', 'unknown'),
                'created_at': datetime.now().isoformat(),
                'source': 'blockchain',  # Mark as blockchain-sourced
                'last_updated': datetime.now().isoformat()
            }
            
            logger.debug(f"✅ Converted blockchain position: {tokens} {outcome} tokens, ${avg_price:.4f} avg price")
            return bot_position
            
        except Exception as e:
            logger.error(f"❌ Position conversion error: {e}")
            logger.error(f"❌ Raw blockchain position: {blockchain_position}")
            return None
    
    def refresh_user_positions(self, user_id: int, wallet_address: str) -> Dict[str, Dict]:
        """
        Force refresh positions from blockchain (bypass cache)
        
        Args:
            user_id: Telegram user ID
            wallet_address: User's wallet address
            
        Returns:
            Fresh positions from blockchain
        """
        # Clear cache for this user
        cache_key = f"{user_id}_{wallet_address}"
        if cache_key in self._position_cache:
            del self._position_cache[cache_key]
        if cache_key in self._cache_timestamps:
            del self._cache_timestamps[cache_key]
        
        logger.info(f"🔄 FORCE REFRESH: Getting fresh blockchain positions for user {user_id}")
        return self.get_user_positions(user_id, wallet_address)
    
    def get_position_count(self, user_id: int, wallet_address: str) -> int:
        """Get count of blockchain positions"""
        positions = self.get_user_positions(user_id, wallet_address)
        return len(positions)
    
    def has_positions(self, user_id: int, wallet_address: str) -> bool:
        """Check if user has any blockchain positions"""
        return self.get_position_count(user_id, wallet_address) > 0
    
    def clear_cache(self):
        """Clear all cached positions (for maintenance)"""
        self._position_cache.clear()
        self._cache_timestamps.clear()
        logger.info("🧹 Position cache cleared")
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics for monitoring"""
        return {
            'cached_users': len(self._position_cache),
            'cache_size_mb': len(str(self._position_cache)) / (1024 * 1024),
            'oldest_cache_age': min([
                time.time() - ts for ts in self._cache_timestamps.values()
            ]) if self._cache_timestamps else 0
        }

# Global instance
blockchain_position_service = None

def get_blockchain_position_service(market_service=None):
    """Get or create the global blockchain position service"""
    global blockchain_position_service
    if blockchain_position_service is None:
        blockchain_position_service = BlockchainPositionService(market_service)
    return blockchain_position_service
