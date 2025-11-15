"""
Trading Bot Configuration
"""

import os
from dotenv import load_dotenv

# Charger les variables d'environnement
# Note: load_dotenv() should be called before this module is imported
# But we call it here too as a safety measure
load_dotenv()

# Debug: Log which token source is being used
if os.getenv("TELEGRAM_BOT"):
    print(f"✅ [CONFIG] Using TELEGRAM_BOT from environment: {os.getenv('TELEGRAM_BOT')[:20]}...")
else:
    print("⚠️ [CONFIG] TELEGRAM_BOT not in environment, using fallback token")

# API Configuration
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://clob.polymarket.com/markets"
POLYMARKET_HOST = "https://clob.polymarket.com"  # Same as CLOB_API_URL
POLYGON_RPC_URL = os.getenv("AUTO_APPROVAL_RPC_HTTP", "https://polygon-mainnet.g.alchemy.com/v2/demo")

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

# Custom USD Amount Configuration
MIN_TRADE_AMOUNT_USD = 0.25          # $0.25 minimum (reduced for dust position cleanup)
MAX_TRADE_AMOUNT_USD = 1000.00       # Safety limit for single trades
CUSTOM_AMOUNT_ONLY = True            # Use custom input only (no preset buttons)

# User Warning Messages
TRADE_WARNING_MESSAGE = """⚠️ **POLYMARKET API REQUIREMENTS**
• Minimum order: $0.25 (reduced for dust cleanup)
• Current price: ${price:.4f} per token
• Recommended: $5+ for better execution"""

BUY_INPUT_MESSAGE = """💰 **Enter USD amount to buy {outcome}**

{warning}

💡 **Example**: $5.00 = ~{example_tokens} tokens"""

SELL_INPUT_MESSAGE = """💰 **Enter USD amount to sell**

📊 **Your Position**: ${position_value:.2f} ({tokens} tokens)
🔢 **MAXIMUM AVAILABLE**: ${position_value:.2f}
⚠️ **MINIMUM ORDER**: $0.25

💡 **Example**: $2.00 = ~{example_tokens} tokens"""

# Database Configuration (PostgreSQL Only)
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://localhost:5432/trading_bot')

# Market Update Settings
MARKET_UPDATE_INTERVAL = 600  # seconds (10 minutes) - Reduced frequency to avoid overload
MARKET_DISPLAY_WINDOW_DAYS = 30  # Show markets from last 30 days

# Legacy config for compatibility (not used)
DATABASE_CONFIG = {
    'type': 'json',
    'file': 'markets_database.json',
    'update_interval': 300,
    'backup_count': 10
}

# Blockchain Configuration
CHAIN_ID = 137  # Polygon Mainnet

# Telegram Bot Configuration - V2 with Wallet Generation
# Utilise BOT_TOKEN ou TELEGRAM_BOT du .env
# SECURITY: No hardcoded fallback - require .env variable
# Priority: BOT_TOKEN first, then TELEGRAM_BOT (for backward compatibility)
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT")  # Check BOT_TOKEN first!
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN or TELEGRAM_BOT must be set in environment variables or .env file!")
BOT_USERNAME = os.getenv("BOT_USERNAME", "polycoolbot")

# Debug: Show which token is being used
print(f"🔍 [CONFIG] BOT_TOKEN loaded: {BOT_TOKEN[:20]}...{BOT_TOKEN[-10:] if len(BOT_TOKEN) > 30 else ''}")

# Wallet Generation Configuration
WALLET_STORAGE_FILE = "user_wallets.json"

# Contract Addresses (Polygon Mainnet)
USDC_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e
POLYMARKET_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # Polymarket Exchange
POLYMARKET_CONDITIONAL_TOKEN_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # Conditional Tokens
CTF_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # CTF Exchange (same as Polymarket Exchange)
COLLATERAL_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e (same as USDC)
NEG_RISK_CTF_EXCHANGE_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"  # Neg Risk CTF Exchange

# Auto-Approval Configuration
AUTO_APPROVAL_ENABLED = True
AUTO_API_GENERATION_ENABLED = True
WALLET_CHECK_INTERVAL_SECONDS = 30
AUTO_APPROVAL_RPC_HTTP = os.getenv("AUTO_APPROVAL_RPC_HTTP", "https://polygon-mainnet.g.alchemy.com/v2/demo")

# Auto-Approval Settings
MIN_POL_BALANCE_FOR_APPROVAL = 0.01  # Minimum POL needed for gas fees
MIN_USDC_BALANCE_FOR_APPROVAL = 0.0  # Skip USDC requirement for now
MAX_AUTO_APPROVAL_ATTEMPTS = 3  # Max retry attempts per wallet

# Fee System Configuration
FEE_ENABLED = True
BASE_FEE_PERCENTAGE = 1.00  # 1%
MINIMUM_FEE_USD = 0.10  # $0.10 minimum
TREASURY_WALLET_ADDRESS = "0xaEF1Da195Dd057c9252A6C03081B70f38453038c"

# Referral Commission Rates
REFERRAL_LEVEL_1_COMMISSION = 25.00  # 25% of fee
REFERRAL_LEVEL_2_COMMISSION = 5.00   # 5% of fee
REFERRAL_LEVEL_3_COMMISSION = 3.00   # 3% of fee

# Referral System Configuration
REFERRAL_ENABLED = True
MIN_COMMISSION_PAYOUT = 1.00  # $1 minimum to claim
CLAIM_COOLDOWN_HOURS = 24  # 24h between claims
REFERRAL_LINK_FORMAT = "https://t.me/{bot_username}?start={referrer_code}"

# Redis Cache Configuration
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Webhook Configuration (Subsquid → Bot)
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', None)  # Optional security header
REDIS_ENABLED = True
REDIS_DEFAULT_TTL = 180  # seconds - Price cache duration (20 → 180 for better hit rate)

# Price Update Configuration - UNIFIED TTL FOR ALL PRICING
PRICE_UPDATE_INTERVAL = 120         # seconds (60 → 120 for better cache overlap)
HOT_PRICE_LIMIT = 100               # Increased from 50 for better coverage

# ADAPTIVE PRICE TTL: Context-aware caching for optimal UX vs performance
POSITION_CACHE_TTL = 180            # seconds - User positions
MARKET_LIST_TTL = 180               # seconds - Market lists
MARKET_SPREAD_TTL = 180             # seconds - Price spreads

# Legacy TTL for backward compatibility - DEPRECATED, use get_adaptive_price_ttl() instead
MARKET_PRICE_TTL = 30               # seconds - DO NOT USE directly, use adaptive TTL

# Adaptive Price TTL Configuration
PRICE_TTL_TRADING = 10              # seconds - Active trading (TP/SL, buy/sell actions)
PRICE_TTL_NAVIGATION = 30           # seconds - Market browsing, details view
PRICE_TTL_BACKGROUND = 60           # seconds - Background updates, monitoring

# Price Freshness Configuration - Centralized for all services
PRICE_FRESHNESS_MAX_AGE = 300       # seconds (5 minutes) - Max age for WebSocket/Poller prices
TOKEN_MAPPING_CACHE_TTL = 300       # seconds (5 minutes) - Token to market mapping cache


# ========================================
# ADAPTIVE PRICE TTL SYSTEM
# ========================================

def get_adaptive_price_ttl(context: str = "navigation") -> int:
    """
    Get context-aware TTL for price caching to balance UX vs performance.

    Args:
        context: Usage context
            - "trading": Active trading (TP/SL, buy/sell) - 10s for freshness
            - "navigation": Market browsing/details - 30s for performance
            - "background": Monitoring/updates - 60s for efficiency

    Returns:
        TTL in seconds optimized for the context
    """
    context_ttl_map = {
        "trading": PRICE_TTL_TRADING,      # 10s - Critical for active trading
        "navigation": PRICE_TTL_NAVIGATION, # 30s - Good UX/performance balance
        "background": PRICE_TTL_BACKGROUND, # 60s - Background efficiency
    }

    return context_ttl_map.get(context, PRICE_TTL_NAVIGATION)  # Default to navigation

# Legacy TTLs (deprecated - use unified 180s above)
REDIS_DEFAULT_TTL = 180  # seconds - All caches unified

# Search ForceReply Configuration
SEARCH_FORCEREPLY_TIMEOUT = 300  # 5 minutes - How long to wait for search reply
SEARCH_MIN_LENGTH = 2  # Minimum search query length
SEARCH_MAX_LENGTH = 100  # Maximum search query length

# ============================================================================
# SUBSQUID MIGRATION FEATURE FLAGS
# ============================================================================
# Gradual migration from old markets table to new subsquid_* tables
# All feature flags default to False for safe backward compatibility

# Enable subsquid_markets_poll/ws for market data queries
USE_SUBSQUID_MARKETS = os.getenv("USE_SUBSQUID_MARKETS", "true").lower() == "true"

# Enable tracked_leader_trades for copy trading (instead of transactions table)
USE_SUBSQUID_COPY_TRADING = os.getenv("USE_SUBSQUID_COPY_TRADING", "false").lower() == "true"

# Enable filter job (subsquid_user_transactions → tracked_leader_trades)
SUBSQUID_FILTER_ENABLED = os.getenv("SUBSQUID_FILTER_ENABLED", "true").lower() == "true"

# Enable cleanup job for subsquid_user_transactions (2 days retention)
SUBSQUID_CLEANUP_ENABLED = os.getenv("SUBSQUID_CLEANUP_ENABLED", "true").lower() == "true"

# Interval for filter job (seconds) - Changed from 60s to 10s for faster copy trading
SUBSQUID_FILTER_INTERVAL = int(os.getenv("SUBSQUID_FILTER_INTERVAL", "10"))

# Interval for cleanup job (seconds)
SUBSQUID_CLEANUP_INTERVAL = int(os.getenv("SUBSQUID_CLEANUP_INTERVAL", "21600"))  # 6 hours

# Log feature flag status
import logging
logger = logging.getLogger(__name__)
logger.info(f"✅ Feature flags loaded: USE_SUBSQUID_MARKETS={USE_SUBSQUID_MARKETS}, USE_SUBSQUID_COPY_TRADING={USE_SUBSQUID_COPY_TRADING}, SUBSQUID_FILTER_ENABLED={SUBSQUID_FILTER_ENABLED}")
