"""
Copy Trading Service Package
Modular, clean architecture for copy trading functionality
"""

from .service import CopyTradingService, get_copy_trading_service
from .exceptions import (
    CopyTradingException,
    InsufficientBudgetException,
    InvalidConfigException,
    CopyExecutionException,
    SubscriptionException,
)
from .config import CopyMode, SubscriptionStatus, COPY_TRADING_CONFIG

__all__ = [
    "CopyTradingService",
    "get_copy_trading_service",
    "CopyTradingException",
    "InsufficientBudgetException",
    "InvalidConfigException",
    "CopyExecutionException",
    "SubscriptionException",
    "CopyMode",
    "SubscriptionStatus",
    "COPY_TRADING_CONFIG",
]
