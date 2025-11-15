"""
Configuration Package
Application configuration and settings
"""

# Import everything from config.py in this directory
from .config import *

__all__ = [
    'GAMMA_API_URL',
    'CLOB_API_URL',
    'BOT_TOKEN',
    'MARKET_UPDATE_INTERVAL',
    'DATABASE_URL',
    'MARKET_DISPLAY_WINDOW_DAYS',
    'CHAIN_ID',
    'BOT_USERNAME',
    'AGGRESSIVE_BUY_PREMIUM',
    'AGGRESSIVE_SELL_DISCOUNT',
    'MINIMUM_VOLUME',
    'MINIMUM_LIQUIDITY'
]
