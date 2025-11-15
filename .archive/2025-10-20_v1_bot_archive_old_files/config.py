"""
Trading Bot Configuration
"""

# API Configuration
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"

# ❌ REMOVED HARDCODED CREDENTIALS FOR SECURITY
# V2 Bot uses dynamically generated wallets and API keys per user
# PRIVATE_KEY = 'REMOVED_FOR_SECURITY'
# API_CREDENTIALS = { 'REMOVED': 'FOR_SECURITY' }
# 
# 🎯 V2 Bot Features:
# - Each user gets their own auto-generated wallet
# - Each user generates their own API keys
# - No shared credentials = better security

# Trading Configuration - ULTRA AGGRESSIVE for INSTANT FILLS
AGGRESSIVE_BUY_PREMIUM = 0.02    # +2¢ for guaranteed instant buy
AGGRESSIVE_SELL_DISCOUNT = 0.03  # -3¢ for guaranteed instant sell
MINIMUM_VOLUME = 10000           # $10K minimum volume
MINIMUM_LIQUIDITY = 1000         # $1K minimum liquidity

# Database Configuration
DATABASE_CONFIG = {
    'type': 'json',  # Start with JSON, upgrade to PostgreSQL later
    'file': 'markets_database.json',
    'update_interval': 300,  # Update every 5 minutes
    'backup_count': 10       # Keep 10 backups
}

# Blockchain Configuration
CHAIN_ID = 137  # Polygon Mainnet

# Telegram Bot Configuration - V2 with Wallet Generation
BOT_TOKEN = "8483038224:AAFg8OGxlRvGNFDZmATFGB4dWcAiAdCrL-M"
BOT_USERNAME = "newnewtestv2bot"

# Wallet Generation Configuration
WALLET_STORAGE_FILE = "user_wallets.json"

# Contract Addresses (Polygon Mainnet)
USDC_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
POLYMARKET_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # Polymarket Exchange
POLYMARKET_CONDITIONAL_TOKEN_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # Conditional Tokens
