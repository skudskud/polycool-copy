"""
Alert Channel Bot Configuration
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # Telegram Bot Configuration
    bot_token: str = os.getenv("BOT_TOKEN", "")
    bot_username: str = os.getenv("BOT_USERNAME", "@PolycoolAlertBot")
    telegram_channel_id: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    main_bot_link: str = os.getenv("MAIN_BOT_LINK", "https://t.me/polycool_alerts")
    
    # Database Configuration
    database_url: str = os.getenv("DATABASE_URL", "")
    
    # Service Configuration
    # Railway sets $PORT automatically - use it if available, otherwise fallback to 8000
    alert_webhook_port: int = int(os.getenv("PORT", os.getenv("ALERT_WEBHOOK_PORT", "8000")))
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    
    # Rate Limiting
    # Telegram channels allow up to 30 messages/second, but we use conservative limits
    # to avoid hitting Telegram's spam detection. 100/hour = ~1 every 36 seconds
    rate_limit_max_per_hour: int = int(os.getenv("RATE_LIMIT_MAX_PER_HOUR", "100"))
    # Minimum 5 seconds between alerts to avoid spam detection
    rate_limit_min_interval_seconds: int = int(os.getenv("RATE_LIMIT_MIN_INTERVAL_SECONDS", "5"))
    
    # Filtering Criteria (same as /smart_trading)
    min_trade_value: float = float(os.getenv("MIN_TRADE_VALUE", "1000.0"))
    min_win_rate: float = float(os.getenv("MIN_WIN_RATE", "0.55"))
    max_age_minutes: int = int(os.getenv("MAX_AGE_MINUTES", "5"))
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()

