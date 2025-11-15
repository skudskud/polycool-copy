"""
Configuration settings for Polycool Alert Bot
"""

import os
from typing import Dict, Any

# =====================================================================
# BOT CONFIGURATION
# =====================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8306437331:AAGdsKk3Ntr9wYR_EoMTTMEP1fQ-Fn2b6dE")
BOT_USERNAME = os.getenv("BOT_USERNAME", "@PolycoolAlertBot")
BOT_VERSION = "v1.0.0"

# =====================================================================
# DATABASE CONFIGURATION
# =====================================================================
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Build DATABASE_URL from Supabase credentials
# Format: postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres
DATABASE_URL = os.getenv("DATABASE_URL", "")

# =====================================================================
# TELEGRAM CONFIGURATION
# =====================================================================
# Target channel/group to send alerts (set via environment variable)
# Use channel username (e.g., "@polycool_alerts") or chat ID
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", None)

# Link to main copy trading bot (CTA in messages)
MAIN_BOT_LINK = os.getenv("MAIN_BOT_LINK", "https://t.me/YourMainBotUsername")

# =====================================================================
# FILTER CONFIGURATION (AGGRESSIVE MODE)
# =====================================================================
FILTERS: Dict[str, Any] = {
    # Only first-time market entries
    'is_first_time': True,
    
    # Minimum trade value in USD (standardized to $400 across all systems)
    'min_value': 400,
    
    # Only "Very Smart" bucket traders
    'bucket_smart': 'Very Smart',
    
    # Must have market question
    'require_market_question': True,
    
    # Exclude high-frequency traders (disabled for now)
    'exclude_high_frequency': False,
    
    # Minimum win rate (optional, currently disabled)
    'min_win_rate': None,  # e.g., 0.55 for 55%
    
    # Exclude crypto price markets (short-term price predictions)
    'exclude_crypto_price_markets': True,
}

# =====================================================================
# RATE LIMITING
# =====================================================================
RATE_LIMITS: Dict[str, int] = {
    # Maximum alerts per hour
    'max_per_hour': 10,
    
    # Minimum seconds between alerts (prevents spam)
    'min_interval_seconds': 60,
}

# =====================================================================
# POLLING CONFIGURATION
# =====================================================================
# How often to check for new trades (seconds)
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))

# Maximum trades to fetch per poll
MAX_TRADES_PER_POLL = int(os.getenv("MAX_TRADES_PER_POLL", "20"))

# =====================================================================
# LOGGING CONFIGURATION
# =====================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# =====================================================================
# DEVELOPMENT FLAGS
# =====================================================================
# Dry run mode (don't actually send alerts, just log)
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# Debug mode (more verbose logging)
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# =====================================================================
# EMOJIS
# =====================================================================
EMOJIS = {
    'fire': '🔥',
    'diamond': '💎',
    'money': '💰',
    'chart': '📊',
    'check': '✅',
    'star': '⭐',
    'link': '🔗',
    'search': '🔍',
    'arrow_right': '👉',
    'buy': '🟢',
    'sell': '🔴',
    'yes': '✅',
    'no': '❌',
}

# =====================================================================
# VALIDATION
# =====================================================================
def validate_config() -> bool:
    """
    Validate required configuration is present
    Returns True if valid, raises ValueError if not
    """
    errors = []
    
    if not BOT_TOKEN or BOT_TOKEN == "":
        errors.append("BOT_TOKEN is required")
    
    if not DATABASE_URL or DATABASE_URL == "":
        errors.append("DATABASE_URL is required")
    
    if TELEGRAM_CHANNEL_ID is None:
        errors.append("TELEGRAM_CHANNEL_ID is required (set to channel username or chat ID)")
    
    if errors:
        raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    return True


if __name__ == "__main__":
    # Test configuration
    try:
        validate_config()
        print("✅ Configuration valid")
        print(f"Bot: {BOT_USERNAME}")
        print(f"Poll interval: {POLL_INTERVAL_SECONDS}s")
        print(f"Rate limit: {RATE_LIMITS['max_per_hour']}/hour")
        print(f"Min value: ${FILTERS['min_value']}")
        print(f"Dry run: {DRY_RUN}")
    except ValueError as e:
        print(f"❌ {e}")

