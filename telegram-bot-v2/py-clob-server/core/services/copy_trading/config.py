"""
Copy Trading Configuration
Centralized constants, enums, and configuration for copy trading
"""

from enum import Enum
from dataclasses import dataclass
from typing import Final


class CopyMode(str, Enum):
    """Copy trading modes"""
    PROPORTIONAL = "PROPORTIONAL"  # Based on % of leader's wallet
    FIXED = "FIXED"  # Fixed amount per trade


class SubscriptionStatus(str, Enum):
    """Copy trading subscription status"""
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CopyTradeStatus(str, Enum):
    """Status of copied trade execution"""
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INSUFFICIENT_BUDGET = "INSUFFICIENT_BUDGET"


@dataclass(frozen=True)
class CopyTradingConfig:
    """Immutable configuration for copy trading"""

    # Budget allocation constraints
    MIN_ALLOCATION_PERCENTAGE: Final[float] = 5.0  # Minimum % of wallet
    MAX_ALLOCATION_PERCENTAGE: Final[float] = 100.0  # Maximum % of wallet
    DEFAULT_ALLOCATION_PERCENTAGE: Final[float] = 50.0  # Default % allocated for copy trading

    # Trade amount constraints - BUY
    MIN_COPY_AMOUNT_USD: Final[float] = 1.0  # Minimum trade amount for follower BUY ($1)
    IGNORE_TRADE_THRESHOLD_USD: Final[float] = 2.0  # Ignore LEADER trades below this (BUY only)
    MAX_COPY_AMOUNT_USD: Final[float] = 10000.0  # Maximum trade amount (safety limit)

    # Trade amount constraints - SELL
    # ✅ LOGIC: Copy all leader SELL > $0.50, but follower minimum is $0.50
    # If remaining position < $0.50, liquidate everything
    MIN_LEADER_SELL_THRESHOLD_USD: Final[float] = 0.50  # Ignore leader SELL < $0.50
    MIN_FOLLOWER_SELL_AMOUNT_USD: Final[float] = 0.50   # Follower SELL minimum
    # Exception: If position value < $0.50 after SELL, liquidate entire position

    # Fixed mode constraints
    MIN_FIXED_AMOUNT: Final[float] = 2.0  # Minimum fixed amount
    MAX_FIXED_AMOUNT: Final[float] = 1000.0  # Maximum fixed amount

    # Budget refresh constraints
    BUDGET_REFRESH_INTERVAL_HOURS: Final[int] = 1  # Refresh wallet balance every hour

    # Fee tracking
    TRACK_COPY_FEES: Final[bool] = True  # Track fees for leader rewards

    # Retry configuration
    MAX_COPY_RETRY_ATTEMPTS: Final[int] = 3
    COPY_RETRY_DELAY_SECONDS: Final[int] = 5

    # Logging
    ENABLE_DETAILED_LOGGING: Final[bool] = True


# Global configuration instance
COPY_TRADING_CONFIG = CopyTradingConfig()
