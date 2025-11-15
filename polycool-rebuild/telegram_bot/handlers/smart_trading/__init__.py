"""
Smart Trading Handlers
Modular handlers for smart trading functionality
"""

from .view_handler import handle_smart_trading_command
from .callbacks import handle_smart_callback

__all__ = ['handle_smart_trading_command', 'handle_smart_callback']
