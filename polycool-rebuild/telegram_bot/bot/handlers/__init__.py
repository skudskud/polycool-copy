"""
Bot handlers
"""
from . import start_handler, wallet_handler, markets_handler, positions_handler
from . import smart_trading_handler, referral_handler, admin_handler

__all__ = [
    "start_handler", "wallet_handler", "markets_handler", "positions_handler",
    "smart_trading_handler", "referral_handler", "admin_handler"
]
