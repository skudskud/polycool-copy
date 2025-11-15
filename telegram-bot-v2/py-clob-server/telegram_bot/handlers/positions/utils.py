#!/usr/bin/env python3
"""
Positions Handler Utilities
Helper functions for position management
"""

import logging

logger = logging.getLogger(__name__)


def is_timeout_error(exception: Exception) -> bool:
    """
    Detect if exception is a timeout (order likely submitted)
    vs real failure (order never submitted)

    Args:
        exception: The exception to check

    Returns:
        True if this appears to be a timeout error, False otherwise
    """
    error_str = str(exception).lower()

    timeout_indicators = [
        'timeout',
        'timed out',
        'connection timeout',
        'read timeout',
        'request timeout',
        'time out',
        'deadline exceeded',
        'timedout'
    ]

    return any(indicator in error_str for indicator in timeout_indicators)


def escape_markdown(text: str) -> str:
    """Escape markdown special characters for Telegram"""
    return text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`')


def format_pnl_indicator(pnl_value: float, pnl_pct: float) -> str:
    """Format P&L with emoji indicator"""
    if pnl_value >= 0:
        return f"🟢 +${pnl_value:.2f} (+{pnl_pct:.1f}%)"
    else:
        return f"🔴 ${pnl_value:.2f} ({pnl_pct:.1f}%)"
