#!/usr/bin/env python3
"""
Session Manager
Manages user sessions and state for the Telegram bot
"""

import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages user sessions including trading state, pending trades, and positions
    Provides a clean interface to the global user_sessions dictionary
    """

    def __init__(self):
        """Initialize session manager with empty sessions dictionary"""
        self._sessions: Dict[int, Dict] = {}
        # Position mappings for callback data (avoid 64-byte Telegram limit)
        self._position_mappings: Dict[int, Dict[int, Dict]] = {}  # {user_id: {index: position_data}}

    def get(self, user_id: int) -> Dict:
        """
        Get user session, creating it if it doesn't exist

        Args:
            user_id: Telegram user ID

        Returns:
            User session dictionary
        """
        if user_id not in self._sessions:
            self.init_user(user_id)
        return self._sessions[user_id]

    def set(self, user_id: int, session: Dict):
        """
        Set complete user session

        Args:
            user_id: Telegram user ID
            session: Complete session dictionary
        """
        self._sessions[user_id] = session

    def init_user(self, user_id: int):
        """
        Initialize user session with default structure

        Args:
            user_id: Telegram user ID
        """
        if user_id not in self._sessions:
            self._sessions[user_id] = {}

        session = self._sessions[user_id]
        if 'state' not in session:
            session['state'] = 'idle'
        if 'pending_trade' not in session:
            session['pending_trade'] = {}
        if 'positions' not in session:
            session['positions'] = {}
        if 'current_market' not in session:
            session['current_market'] = None

        # NEW: Filter state for markets
        if 'market_filter' not in session:
            session['market_filter'] = 'volume'  # Default filter for /markets
        if 'market_filter_page' not in session:
            session['market_filter_page'] = 0  # Current page in /markets
        if 'category_filter' not in session:
            session['category_filter'] = 'volume'  # Default filter for /category
        if 'category_filter_page' not in session:
            session['category_filter_page'] = 0  # Current page in category view
        if 'return_filter' not in session:
            session['return_filter'] = 'volume'  # Filter to return to from market details
        if 'return_page' not in session:
            session['return_page'] = 0  # Page to return to

    def clear_pending_trade(self, user_id: int):
        """
        Clear user's pending trade state

        Args:
            user_id: Telegram user ID
        """
        if user_id in self._sessions:
            self._sessions[user_id]['state'] = 'idle'
            self._sessions[user_id]['pending_trade'] = {}

    def get_all_sessions(self) -> Dict[int, Dict]:
        """
        Get all user sessions (for persistence/recovery)

        Returns:
            Dictionary of all user sessions
        """
        return self._sessions

    def set_all_sessions(self, sessions: Dict[int, Dict]):
        """
        Set all user sessions (for loading from persistence)

        Args:
            sessions: Dictionary of all user sessions
        """
        self._sessions = sessions

    def clear_all(self):
        """Clear all user sessions"""
        self._sessions.clear()

    def user_exists(self, user_id: int) -> bool:
        """
        Check if user session exists

        Args:
            user_id: Telegram user ID

        Returns:
            True if user session exists
        """
        return user_id in self._sessions

    def get_position(self, user_id: int, market_id: str, outcome: str) -> Optional[Dict]:
        """
        Get specific position for user

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: "yes" or "no"

        Returns:
            Position dictionary or None if not found
        """
        session = self.get(user_id)
        positions = session.get('positions', {})
        position_key = f"{market_id}_{outcome.lower()}"
        return positions.get(position_key)

    def set_position(self, user_id: int, market_id: str, outcome: str, position: Dict):
        """
        Set specific position for user

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: "yes" or "no"
            position: Position dictionary
        """
        session = self.get(user_id)
        if 'positions' not in session:
            session['positions'] = {}
        position_key = f"{market_id}_{outcome.lower()}"
        session['positions'][position_key] = position

    def store_position_mapping(self, user_id: int, index: int, position_data: Dict):
        """
        Store position mapping for callback data (solves 64-byte Telegram limit)

        Args:
            user_id: Telegram user ID
            index: Position index (short integer)
            position_data: Position data including token_id, market_id, outcome
        """
        if user_id not in self._position_mappings:
            self._position_mappings[user_id] = {}
        self._position_mappings[user_id][index] = position_data
        logger.debug(f"📍 Stored position mapping for user {user_id}, index {index}: {position_data.get('token_id', 'unknown')[:20]}...")

    def get_position_mapping(self, user_id: int, index: int) -> Optional[Dict]:
        """
        Get position data by index

        Args:
            user_id: Telegram user ID
            index: Position index

        Returns:
            Position data dictionary or None
        """
        if user_id not in self._position_mappings:
            logger.warning(f"⚠️ No position mappings for user {user_id}")
            return None
        return self._position_mappings[user_id].get(index)

    def clear_position_mappings(self, user_id: int):
        """
        Clear all position mappings for a user

        Args:
            user_id: Telegram user ID
        """
        if user_id in self._position_mappings:
            del self._position_mappings[user_id]
            logger.debug(f"🗑️ Cleared position mappings for user {user_id}")

    def set_search_state(self, user_id: int, message_id: int):
        """
        Set user state to awaiting search input via ForceReply

        Args:
            user_id: Telegram user ID
            message_id: Message ID of the ForceReply prompt
        """
        session = self.get(user_id)
        session['search_state'] = {
            'action': 'search:awaiting_input',
            'reply_to_message_id': message_id,
            'timestamp': datetime.now().isoformat()
        }
        logger.debug(f"🔍 Set search state for user {user_id}, message {message_id}")

    def get_search_state(self, user_id: int) -> Optional[Dict]:
        """
        Get user's search state

        Args:
            user_id: Telegram user ID

        Returns:
            Search state dictionary or None
        """
        session = self.get(user_id)
        return session.get('search_state')

    def is_awaiting_search_input(self, user_id: int) -> bool:
        """
        Check if user is awaiting search input

        Args:
            user_id: Telegram user ID

        Returns:
            True if user is awaiting search input
        """
        search_state = self.get_search_state(user_id)
        if not search_state:
            return False

        # Check if state is valid and not expired
        action = search_state.get('action')
        if action != 'search:awaiting_input':
            return False

        # Check timeout (5 minutes)
        try:
            timestamp = datetime.fromisoformat(search_state.get('timestamp', ''))
            age_seconds = (datetime.now() - timestamp).total_seconds()
            if age_seconds > 300:  # 5 minutes timeout
                self.clear_search_state(user_id)
                logger.debug(f"⏰ Search state expired for user {user_id}")
                return False
        except (ValueError, TypeError):
            # Invalid timestamp, clear state
            self.clear_search_state(user_id)
            return False

        return True

    def clear_search_state(self, user_id: int):
        """
        Clear user's search state

        Args:
            user_id: Telegram user ID
        """
        session = self.get(user_id)
        if 'search_state' in session:
            del session['search_state']
            logger.debug(f"🗑️ Cleared search state for user {user_id}")

    def save_all_positions(self) -> bool:
        """
        Save all positions to PostgreSQL database

        Returns:
            True if save successful
        """
        try:
            # Position persistence is DISABLED - using transaction-based architecture
            # Positions are fetched from blockchain API in real-time
            logger.debug("✅ Position persistence skipped (using transaction-based architecture)")
            return True
        except Exception as e:
            logger.error(f"❌ Error during position save check: {e}")
            return False

    def load_all_positions(self) -> bool:
        """
        Load all positions from PostgreSQL database

        Returns:
            True if load successful
        """
        try:
            from core.persistence import postgresql_persistence

            loaded_positions = postgresql_persistence.load_positions()
            if loaded_positions:
                self._sessions.clear()
                self._sessions.update(loaded_positions)

                position_count = sum(len(session.get('positions', {})) for session in loaded_positions.values())
                user_count = len(loaded_positions)

                logger.info(f"✅ Loaded {position_count} positions for {user_count} users from PostgreSQL")
                return True
            else:
                logger.warning("⚠️ No positions found in PostgreSQL")
                return False

        except Exception as e:
            logger.error(f"❌ Error loading positions: {e}")
            return False


# Global session manager instance (for backward compatibility with existing code)
session_manager = SessionManager()

# Global user_sessions for backward compatibility
# This points to the internal sessions of the SessionManager
user_sessions = session_manager._sessions
