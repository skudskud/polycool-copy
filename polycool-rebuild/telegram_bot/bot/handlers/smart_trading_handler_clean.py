"""
Smart Trading command handler
Displays recent trades from smart wallets (expert traders) for recommendations

This is the main entry point that delegates to the modular handlers.
"""
from telegram import Update
from telegram.ext import ContextTypes

from telegram_bot.handlers.smart_trading import handle_smart_trading_command, handle_smart_callback

# Re-export the main functions for backward compatibility
__all__ = ['handle_smart_trading', 'handle_smart_callback']


async def handle_smart_trading(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /smart_trading command - delegate to modular handler
    """
    await handle_smart_trading_command(update, context)


async def handle_smart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle smart trading callback queries - delegate to modular handler
    """
    await handle_smart_callback(update, context)
