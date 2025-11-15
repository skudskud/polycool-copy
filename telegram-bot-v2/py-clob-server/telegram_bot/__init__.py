"""
Polymarket Telegram Trading Bot - Refactored Architecture
Modular structure with handlers, services, and utilities
"""

# Note: Import TelegramTradingBot directly from telegram_bot.bot when needed
# to avoid circular import issues during initialization

from .session_manager import SessionManager, session_manager, user_sessions

__all__ = [
    'SessionManager',
    'session_manager',
    'user_sessions',
]

# For backward compatibility, allow importing TelegramTradingBot
def __getattr__(name):
    if name == 'TelegramTradingBot':
        from .bot import TelegramTradingBot
        return TelegramTradingBot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
