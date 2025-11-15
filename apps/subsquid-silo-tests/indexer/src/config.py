"""
Subsquid Silo Tests - Configuration Module
Manages feature flags, database connections, Redis clients, and environment variables.
"""

import os
import logging
from typing import Optional
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings from environment variables"""

    # ========================================
    # Feature Flag
    # ========================================
    EXPERIMENTAL_SUBSQUID: bool = False

    # ========================================
    # Database Configuration
    # ========================================
    DATABASE_URL: str = "postgresql://localhost:5432/postgres"
    DATABASE_SCHEMA: str = "public"

    # ========================================
    # Redis Configuration
    # ========================================
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PREFIX: str = "subsquid_silo:"
    REDIS_PREFIX_MARKET_STATUS: str = "market.status.*"
    REDIS_PREFIX_CLOB_TRADE: str = "clob.trade.*"
    REDIS_PREFIX_CLOB_ORDERBOOK: str = "clob.orderbook.*"
    REDIS_PREFIX_COPY_TRADE: str = "copy_trade:*"

    # ========================================
    # Polling Configuration (Gamma API)
    # ========================================
    POLL_MS: int = 60000  # 60 seconds (1 minute) for production
    GAMMA_API_URL: str = "https://gamma-api.polymarket.com/markets"
    POLL_LIMIT: int = 100
    POLL_OFFSET_START: int = 0
    POLL_RATE_LIMIT_BACKOFF_MAX: int = 300  # 5 minutes max backoff

    # ========================================
    # WebSocket Configuration (CLOB)
    # ========================================
    CLOB_WSS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    WS_RECONNECT_BACKOFF_MIN: float = 1.0  # 1 second
    WS_RECONNECT_BACKOFF_MAX: float = 8.0  # 8 seconds
    WS_RECONNECT_JITTER: bool = True
    WS_MESSAGE_TIMEOUT: int = 30  # 30 seconds
    WS_MAX_SUBSCRIPTIONS: int = 3000  # Max markets to subscribe via WS (increased for watched markets)

    # CLOB API Authentication (for authenticated WebSocket)
    CLOB_API_KEY: Optional[str] = "24a2ae09-454b-a816-d6bf-7e979c0deb4d"
    CLOB_API_SECRET: Optional[str] = "SmzxJyXAvOd8QQ69eYhJ+lg+0B5/7vmvTWmLPKOx/3jDSxl9K6xYSESr3tUeWuc6VAqtizoofwv/PeBQA4Vd7Rj8WK6z04Xm"
    CLOB_API_PASSPHRASE: Optional[str] = "08f9fe86b132933aaaa904d5b1dce99c44bdd0d01bbb964a4e8e5b06067fb8d8"

    # ========================================
    # Webhook Configuration
    # ========================================
    WEBHOOK_LISTEN_HOST: str = "0.0.0.0"
    WEBHOOK_LISTEN_PORT: int = 8081
    WEBHOOK_ENDPOINT: str = "/wh/market"

    # ========================================
    # DipDup Configuration (On-Chain)
    # ========================================
    POLYGON_RPC_URL: str = "https://polygon-rpc.com"
    DIPDUP_DATABASE_URL: Optional[str] = None  # Falls back to DATABASE_URL if not set
    DIPDUP_ENABLED: bool = False

    # ========================================
    # Service Flags
    # ========================================
    POLLER_ENABLED: bool = True
    STREAMER_ENABLED: bool = True
    WEBHOOK_ENABLED: bool = True
    BRIDGE_ENABLED: bool = True
    REDIS_BRIDGE_ENABLED: bool = True
    REDIS_BRIDGE_WEBHOOK_URL: str = "http://localhost:8081/wh/market"
    REDIS_BRIDGE_COPY_TRADE_WEBHOOK_URL: Optional[str] = None  # If None, uses REDIS_BRIDGE_WEBHOOK_URL with /wh/copy_trade

    # ========================================
    # Redis Publisher Configuration (Indexer)
    # ========================================
    REDIS_PUBLISHER_ENABLED: bool = True
    REDIS_PUBLISHER_MAX_RETRIES: int = 3
    REDIS_PUBLISHER_RETRY_DELAY: float = 1.0

    # ========================================
    # Logging Configuration
    # ========================================
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # ========================================
    # Testing Configuration
    # ========================================
    MOCK_EXTERNAL_APIS: bool = False
    TEST_MODE: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# ========================================
# Global Settings Instance
# ========================================
settings = Settings()


# ========================================
# Feature Flag Validation
# ========================================
def validate_experimental_subsquid():
    """
    Validate that EXPERIMENTAL_SUBSQUID flag is set before starting services.
    This prevents accidental production impact.
    """
    if not settings.EXPERIMENTAL_SUBSQUID:
        logger.error(
            "❌ EXPERIMENTAL_SUBSQUID not enabled. "
            "Set environment variable EXPERIMENTAL_SUBSQUID=true to proceed."
        )
        raise RuntimeError(
            "Silo tests require EXPERIMENTAL_SUBSQUID=true to prevent production impact."
        )
    logger.info("✅ EXPERIMENTAL_SUBSQUID enabled - silo tests active")


# ========================================
# Table Names (Mapped to Config)
# ========================================
TABLES = {
    "markets_poll": "subsquid_markets_poll",
    "markets_ws": "subsquid_markets_ws",
    "markets_wh": "subsquid_markets_wh",
    "events": "subsquid_events",
    "fills_onchain": "subsquid_fills_onchain",
    "user_transactions": "subsquid_user_transactions",
}


# ========================================
# Redis Channels (For Bridge & Pub/Sub)
# ========================================
REDIS_CHANNELS = {
    "market_status": "market.status.*",
    "clob_trade": "clob.trade.*",
    "clob_orderbook": "clob.orderbook.*",
    "copy_trade": "copy_trade:*",
}


# ========================================
# Database Client Factory
# ========================================
async def get_db_url() -> str:
    """Get database URL with schema"""
    base_url = settings.DATABASE_URL
    if "?" not in base_url:
        return f"{base_url}?schema={settings.DATABASE_SCHEMA}"
    return base_url


# ========================================
# Configuration Summary (for logging)
# ========================================
def log_configuration():
    """Log current configuration"""
    logger.info("=" * 50)
    logger.info("Subsquid Silo Tests Configuration")
    logger.info("=" * 50)
    logger.info(f"Feature Flag (EXPERIMENTAL_SUBSQUID): {settings.EXPERIMENTAL_SUBSQUID}")
    logger.info(f"Database URL: {settings.DATABASE_URL[:50]}...")
    logger.info(f"Redis URL: {settings.REDIS_URL}")
    logger.info(f"Polling Interval: {settings.POLL_MS}ms")
    logger.info(f"WebSocket URL: {settings.CLOB_WSS_URL}")
    logger.info(f"Webhook Port: {settings.WEBHOOK_LISTEN_PORT}")
    logger.info(f"Services - Poller: {settings.POLLER_ENABLED}, Streamer: {settings.STREAMER_ENABLED}, Webhook: {settings.WEBHOOK_ENABLED}, Bridge: {settings.BRIDGE_ENABLED}")
    logger.info("=" * 50)
