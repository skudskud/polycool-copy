"""
Smart Trading Services
Business logic for smart wallet recommendations and position tracking
"""

from .service import SmartTradingService
from .position_tracker import SmartWalletPositionTracker

__all__ = ['SmartTradingService', 'SmartWalletPositionTracker']
