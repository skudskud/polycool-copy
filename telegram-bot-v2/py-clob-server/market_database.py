"""
Market Database Compatibility Wrapper
Provides backwards compatibility for telegram_bot.py
Internally uses PostgreSQL instead of JSON
"""

import logging
from typing import Dict, List
from core.persistence import MarketRepository, get_db_session

logger = logging.getLogger(__name__)


class MarketDatabase:
    """
    Compatibility wrapper for telegram_bot.py
    Maintains same interface but uses PostgreSQL internally
    """

    def __init__(self):
        """Initialize with PostgreSQL repository"""
        self.session = get_db_session()
        self.repository = MarketRepository(self.session)
        logger.info("✅ MarketDatabase wrapper initialized (using PostgreSQL)")

    def get_high_volume_markets(self, limit: int = 50) -> List[Dict]:
        """Get markets sorted by volume (for telegram bot)"""
        try:
            markets = self.repository.get_all_active(limit=limit)
            # Convert to dict format for compatibility
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting high volume markets: {e}")
            return []

    def search_markets(self, query: str) -> List[Dict]:
        """Search markets by question text (for telegram bot)"""
        try:
            markets = self.repository.search_by_keyword(query, limit=100)
            # Convert to dict format for compatibility
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error searching markets: {e}")
            return []

    def get_markets_by_ids(self, market_ids: List[str]) -> List[Dict]:
        """
        Batch load multiple markets by IDs in ONE query
        
        Args:
            market_ids: List of market IDs to load
            
        Returns:
            List of market dictionaries (only markets that exist)
            
        PERFORMANCE: 100x faster than calling get_market_by_id() in a loop!
        """
        try:
            markets = self.repository.get_markets_by_ids(market_ids)
            # Convert to dict format for compatibility
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error batch loading markets: {e}")
            return []

    # ========================================
    # NEW: ENHANCED QUERY METHODS
    # ========================================

    def get_trending_markets(self, limit: int = 20, period: str = '24hr') -> List[Dict]:
        """Get trending markets by price change"""
        try:
            markets = self.repository.get_trending_markets(limit=limit, period=period)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting trending markets: {e}")
            return []

    def get_featured_markets(self, limit: int = 20) -> List[Dict]:
        """Get featured markets"""
        try:
            markets = self.repository.get_featured_markets(limit=limit)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting featured markets: {e}")
            return []

    def get_new_markets(self, limit: int = 20) -> List[Dict]:
        """Get newly created markets"""
        try:
            markets = self.repository.get_new_markets(limit=limit)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting new markets: {e}")
            return []

    def get_ending_soon_markets(self, hours: int = 24, limit: int = 20) -> List[Dict]:
        """Get markets ending soon"""
        try:
            markets = self.repository.get_ending_soon_markets(hours=hours, limit=limit)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting ending soon markets: {e}")
            return []

    def get_high_liquidity_markets(self, limit: int = 20) -> List[Dict]:
        """Get markets with highest liquidity"""
        try:
            markets = self.repository.get_high_liquidity_markets(limit=limit)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting high liquidity markets: {e}")
            return []

    def get_competitive_markets(self, limit: int = 20) -> List[Dict]:
        """Get markets with highest competitive rewards"""
        try:
            markets = self.repository.get_competitive_markets(limit=limit)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting competitive markets: {e}")
            return []

    def get_markets_by_category(self, category: str, limit: int = 20) -> List[Dict]:
        """Get markets by category"""
        try:
            markets = self.repository.get_markets_by_category(category, limit=limit)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting markets by category '{category}': {e}")
            return []

    def get_all_categories(self) -> List[tuple]:
        """Get all available categories with counts"""
        try:
            return self.repository.get_all_categories()
        except Exception as e:
            logger.error(f"Error getting categories: {e}")
            return []

    def get_parent_markets(self, limit: int = 20) -> List[Dict]:
        """Get parent markets (for grouped display)"""
        try:
            markets = self.repository.get_parent_markets_by_volume(limit=limit)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting parent markets: {e}")
            return []

    def get_sub_markets(self, market_group_id: int) -> List[Dict]:
        """Get sub-markets (children) of a parent market group"""
        try:
            markets = self.repository.get_sub_markets(market_group_id)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting sub-markets for group {market_group_id}: {e}")
            return []

    def get_market_groups(self, limit: int = 20) -> List[Dict]:
        """
        Get market groups sorted by total volume
        Returns list of tuples converted to dicts: [{group_id, markets}]
        """
        try:
            groups = self.repository.get_market_groups_by_volume(limit=limit)
            result = []
            for group_id, markets in groups:
                result.append({
                    'group_id': group_id,
                    'markets': [m.to_dict() for m in markets]
                })
            return result
        except Exception as e:
            logger.error(f"Error getting market groups: {e}")
            return []

    def get_markets_in_group(self, market_group_id: int) -> List[Dict]:
        """
        LEGACY: Get all markets in a specific market group
        Only returns active markets

        Use get_markets_in_event() for new code
        """
        try:
            markets = self.repository.get_markets_by_group(market_group_id)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting markets in group {market_group_id}: {e}")
            return []

    def get_markets_in_event(self, event_id: str, market_ids_cache: List[str] = None) -> List[Dict]:
        """
        Get all markets in a specific event (Polymarket Events API or slug-based group)

        Args:
            event_id: Event ID (real or slug-based like 'slug_will-in-the-2025')
            market_ids_cache: Optional list of market IDs for slug-based groups (from cache)

        Returns:
            List of market dictionaries (only active markets)
        """
        try:
            # Pass market_ids_cache to repository for optimized lookup
            markets = self.repository.get_markets_by_event(event_id, market_ids_cache)
            return [market.to_dict() for market in markets]
        except Exception as e:
            logger.error(f"Error getting markets in event {event_id}: {e}")
            return []

    def get_events(self, limit: int = 20) -> List[Dict]:
        """
        Get events sorted by total volume (Polymarket Events API)
        Returns list of events with their markets
        """
        try:
            events = self.repository.get_events_by_volume(limit=limit)
            result = []
            for event_id, markets in events:
                result.append({
                    'event_id': event_id,
                    'markets': [m.to_dict() for m in markets]
                })
            return result
        except Exception as e:
            logger.error(f"Error getting events: {e}")
            return []

    # ========================================
    # COMPATIBILITY METHODS
    # ========================================

    def load_database(self) -> Dict:
        """
        Load database (compatibility method)
        Returns format compatible with old JSON structure
        """
        try:
            all_markets = self.repository.get_all_active()
            markets_data = [market.to_dict() for market in all_markets]

            return {
                'metadata': {
                    'total_markets': len(markets_data),
                    'data_sources': ['PostgreSQL']
                },
                'markets': markets_data
            }
        except Exception as e:
            logger.error(f"Error loading database: {e}")
            return {'metadata': {'total_markets': 0}, 'markets': []}
