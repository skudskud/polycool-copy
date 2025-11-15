"""
Copy Trading Handlers - Refactored Module
Handles copy trading functionality with modular architecture
"""

from .dashboard import handle_copy_trading, _get_user_allocations, _build_copy_trading_dashboard, _handle_refresh_dashboard
from .allocations import _handle_set_allocation_type, _handle_set_mode, _handle_set_allocation_value, _handle_allocation_value_input
from .leaders import _handle_add_leader, _handle_settings, _handle_leader_address_input
from .callbacks import handle_copy_callback, _handle_pause_resume, _handle_stop_following, _handle_confirm_stop_following, handle_copy_trading_message

__all__ = [
    # Dashboard functions
    'handle_copy_trading',
    '_get_user_allocations',
    '_build_copy_trading_dashboard',
    '_handle_refresh_dashboard',

    # Allocations functions
    '_handle_set_allocation_type',
    '_handle_set_mode',
    '_handle_set_allocation_value',
    '_handle_allocation_value_input',

    # Leaders functions
    '_handle_add_leader',
    '_handle_settings',
    '_handle_leader_address_input',

    # Callbacks functions
    'handle_copy_callback',
    '_handle_pause_resume',
    '_handle_stop_following',
    '_handle_confirm_stop_following',
    'handle_copy_trading_message',
]
