"""
DISABLED - Position table removed, using transaction-based architecture
All position persistence operations are now handled by:
1. Transaction table for audit trail
2. Direct blockchain API for real-time positions
"""

import logging

logger = logging.getLogger(__name__)

class PostgreSQLPositionPersistence:
    """DISABLED - Position table removed"""
    
    def __init__(self):
        logger.info("⚠️ PostgreSQL Position Persistence DISABLED - Using transaction-based architecture")
    
    def save_positions(self, user_sessions):
        """DISABLED - No position table"""
        return True
    
    def load_positions(self):
        """DISABLED - No position table"""
        return {}
    
    def get_user_position_count(self, user_id: int) -> int:
        """DISABLED - No position table"""
        return 0
    
    def clear_user_positions(self, user_id: int) -> bool:
        """DISABLED - No position table"""
        return True

# Global instance
postgresql_persistence = PostgreSQLPositionPersistence()