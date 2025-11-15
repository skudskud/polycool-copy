#!/usr/bin/env python3
"""
Analytics Callbacks Module
Handles all analytics-related inline button callbacks (PnL, stats, history)
"""

import logging
import os
import sys

# Temporary: Import from parent callback_handlers.py
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ..callback_handlers import (
    handle_detailed_pnl,
    handle_trading_stats,
    handle_refresh_pnl,
    handle_show_pnl,
    handle_refresh_history,
    handle_export_history,
    handle_show_history,
    handle_stats_period,
    handle_refresh_performance
)

logger = logging.getLogger(__name__)

__all__ = [
    'handle_detailed_pnl',
    'handle_trading_stats',
    'handle_refresh_pnl',
    'handle_show_pnl',
    'handle_refresh_history',
    'handle_export_history',
    'handle_show_history',
    'handle_stats_period',
    'handle_refresh_performance'
]

