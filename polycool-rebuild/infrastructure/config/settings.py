"""
Polycool Application Settings
Centralized configuration management using Pydantic
"""
import os
import secrets
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field, validator
from pydantic_settings import BaseSettings

# CRITICAL: Load environment variables BEFORE defining Pydantic classes
# Pydantic loads env vars at class definition time, not at instantiation
# Railway injects env vars directly - don't try to load files
if not os.getenv('RAILWAY_ENVIRONMENT'):
    # Local development: load from .env files
    load_dotenv('.env.local')  # Development env first
    load_dotenv('.env', override=False)  # Fallback env (no override)
    print('[CONFIG] 🏠 Local mode: loaded .env.local')
else:
    # Railway: use environment variables directly
    print('[CONFIG] 🚀 Railway mode: using environment variables')


class DatabaseSettings(BaseSettings):
    """Database configuration"""

    url: str = Field("", env="DATABASE_URL")
    test_url: Optional[str] = Field(None, env="DATABASE_TEST_URL")

    @property
    def effective_url(self) -> str:
        """Return test_url if available, otherwise url"""
        # Use os.getenv directly as Pydantic may not load Railway env vars correctly
        import os
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
        base_url = os.getenv("DATABASE_TEST_URL") or os.getenv("DATABASE_URL", "")
        if not base_url:
            # Fallback: try to get from Railway environment
            base_url = os.getenv("DATABASE_URL", "")
        # Clean up any whitespace and newlines (Railway stores multiline vars with \n)
        base_url = base_url.strip().replace('\n', '').replace('\r', '')

        if not base_url:
            return base_url

        # Parse URL to preserve query parameters
        parsed = urlparse(base_url)
        query_params = parse_qs(parsed.query)

        # Normalize scheme: handle both postgres:// and postgresql://
        scheme = parsed.scheme
        if scheme == "postgres":
            scheme = "postgresql"

        # Add psycopg driver if not already present (better PgBouncer compatibility)
        # SQLAlchemy will automatically use async version when using create_async_engine
        if not scheme.startswith("postgresql+"):
            scheme = "postgresql+psycopg"

        # Check if this is a Supabase pooler connection (port 6543 = transaction pooling)
        is_supabase_pooler = (
            "pooler.supabase.com" in parsed.netloc or
            (parsed.hostname and "pooler.supabase.com" in parsed.hostname)
        )
        is_transaction_pooling = ":6543" in parsed.netloc

        # Add pgbouncer=true parameter for Supabase transaction pooling if missing
        if is_supabase_pooler and is_transaction_pooling:
            if "pgbouncer" not in query_params:
                query_params["pgbouncer"] = ["true"]

        # Reconstruct URL with preserved query parameters
        new_query = urlencode(query_params, doseq=True)
        new_parsed = parsed._replace(scheme=scheme, query=new_query)
        final_url = urlunparse(new_parsed)

        return final_url
    pool_size: int = Field(3, env="DB_POOL_SIZE")      # Further reduced for PgBouncer compatibility
    max_overflow: int = Field(5, env="DB_MAX_OVERFLOW")  # Further reduced for PgBouncer compatibility
    pool_timeout: int = Field(30, env="DB_POOL_TIMEOUT")
    pool_recycle: int = Field(3600, env="DB_POOL_RECYCLE")


class RedisSettings(BaseSettings):
    """Redis cache configuration"""

    url: str = Field(default="redis://localhost:6379", env="REDIS_URL")
    ttl_prices: int = Field(20, env="CACHE_TTL_PRICES")  # 20 seconds
    ttl_positions: int = Field(30, env="CACHE_TTL_POSITIONS")  # 30 seconds (reduced from 3min for fresher data)
    ttl_markets: int = Field(300, env="CACHE_TTL_MARKETS")  # 5 minutes
    ttl_user_data: int = Field(3600, env="CACHE_TTL_USER_DATA")  # 1 hour
    pubsub_enabled: bool = Field(True, env="REDIS_PUBSUB_ENABLED")  # Enable Pub/Sub

    def __init__(self, **data):
        """Override to force loading REDIS_URL from environment"""
        import os
        if not data.get('url'):
            # Force load from environment, don't use default
            env_url = os.getenv('REDIS_URL')
            if env_url:
                # Clean up any whitespace and newlines (Railway stores multiline vars with \n)
                env_url = env_url.strip().replace('\n', '').replace('\r', '')
                data['url'] = env_url
        super().__init__(**data)


class TelegramSettings(BaseSettings):
    """Telegram bot configuration"""

    token: Optional[str] = Field(None)  # Required only for bot service
    webhook_url: Optional[str] = Field(None, env="WEBHOOK_URL")
    webhook_secret: str = Field("polycool_webhook_secret_2025_secure_key", env="WEBHOOK_SECRET")

    def __init__(self, **data):
        """Override to support both TELEGRAM_BOT_TOKEN and BOT_TOKEN"""
        import os
        # Try TELEGRAM_BOT_TOKEN first, then BOT_TOKEN as fallback
        if 'token' not in data:
            token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('BOT_TOKEN')
            if token:
                data['token'] = token.strip()
        super().__init__(**data)


class PolymarketSettings(BaseSettings):
    """Polymarket API configuration"""

    clob_api_key: str = Field("your_clob_api_key", env="CLOB_API_KEY")
    clob_api_secret: str = Field("your_clob_api_secret", env="CLOB_API_SECRET")
    clob_api_passphrase: str = Field("your_clob_passphrase", env="CLOB_API_PASSPHRASE")
    clob_wss_url: str = Field("wss://ws-subscriptions-clob.polymarket.com/ws/market", env="CLOB_WSS_URL")

    gamma_api_base: str = "https://gamma-api.polymarket.com"


class Web3Settings(BaseSettings):
    """Web3 and blockchain configuration"""

    polygon_rpc_url: str = Field("https://polygon-rpc.com", env="POLYGON_RPC_URL")
    solana_rpc_url: str = Field("https://api.mainnet-beta.solana.com", env="SOLANA_RPC_URL")
    auto_approval_rpc: str = Field("https://polygon-rpc.com", env="AUTO_APPROVAL_RPC_HTTP")
    jupiter_api_key: str = Field("", env="JUPITER_API_KEY")
    debridge_api_key: str = Field("", env="DEBRIDGE_API_KEY")
    treasury_private_key: Optional[str] = Field(None, env="TREASURY_PRIVATE_KEY")


class SecuritySettings(BaseSettings):
    """Security and encryption configuration"""

    encryption_key: str = Field("NJK9ogOGZ8GRytlIcPflSEihiXaYWnux", env="ENCRYPTION_KEY")

    @validator("encryption_key")
    def validate_encryption_key(cls, v):
        """Ensure encryption key is 32 characters for AES-256"""
        if len(v) != 32:
            raise ValueError("Encryption key must be exactly 32 characters for AES-256")
        return v

    jwt_secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24


class AISettings(BaseSettings):
    """AI services configuration"""

    openai_api_key: str = Field("your_openai_api_key", env="OPENAI_API_KEY")


class DataIngestionSettings(BaseSettings):
    """Data ingestion configuration"""

    poll_interval_seconds: int = Field(60, env="POLL_INTERVAL_SECONDS")
    poller_enabled: bool = Field(True, env="POLLER_ENABLED")
    streamer_enabled: bool = Field(True, env="STREAMER_ENABLED")
    indexer_enabled: bool = Field(True, env="INDEXER_ENABLED")
    max_websocket_subscriptions: int = Field(3000, env="WS_MAX_SUBSCRIPTIONS")


class TradingSettings(BaseSettings):
    """Trading features configuration"""

    tpsl_monitoring_enabled: bool = Field(True, env="TPSL_MONITORING_ENABLED")
    tpsl_check_interval: int = Field(10, env="TPSL_CHECK_INTERVAL")  # seconds


class LoggingSettings(BaseSettings):
    """Logging configuration"""

    level: str = Field("INFO", env="LOG_LEVEL")
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    sentry_dsn: Optional[str] = Field(None, env="SENTRY_DSN")


class AppSettings(BaseSettings):
    """Main application settings"""

    # Environment
    debug: bool = Field(False, env="DEBUG")
    testing: bool = Field(False, env="TESTING")
    environment: str = Field("development", env="ENVIRONMENT")

    # Application
    name: str = "Polycool Telegram Bot"
    version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    api_url: str = Field("https://polycool-api-production.up.railway.app", env="API_URL")

    # Sub-settings
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    telegram: TelegramSettings = TelegramSettings()
    polymarket: PolymarketSettings = PolymarketSettings()
    web3: Web3Settings = Web3Settings()
    security: SecuritySettings = SecuritySettings()
    ai: AISettings = AISettings()
    data_ingestion: DataIngestionSettings = DataIngestionSettings()
    trading: TradingSettings = TradingSettings()
    logging: LoggingSettings = LoggingSettings()

    class Config:
        env_file = ".env.local"  # Load only .env.local for development
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields in env

    @property
    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.environment.lower() in ["development", "dev", "local"]

    @property
    def is_testing(self) -> bool:
        """Check if running in testing mode"""
        return self.testing or self.environment.lower() == "testing"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode"""
        return self.environment.lower() == "production"


def _validate_railway_settings():
    """Validate critical settings on Railway startup"""
    if os.getenv('RAILWAY_ENVIRONMENT'):
        print('\n[CONFIG VALIDATION] 🚀 Railway Startup Checks:\n')

        checks = {
            'DATABASE_URL': os.getenv('DATABASE_URL'),
            'REDIS_URL': os.getenv('REDIS_URL'),
            'TELEGRAM_BOT_TOKEN': os.getenv('TELEGRAM_BOT_TOKEN'),
            'CLOB_API_KEY': os.getenv('CLOB_API_KEY'),
            'ENCRYPTION_KEY': os.getenv('ENCRYPTION_KEY'),
        }

        missing = [k for k, v in checks.items() if not v]
        found = [k for k, v in checks.items() if v]

        if found:
            print(f'✅ Configured ({len(found)}): {", ".join(found)}')
        if missing:
            print(f'⚠️  Missing ({len(missing)}): {", ".join(missing)}')

        # Check database connectivity hints
        db_url = os.getenv('DATABASE_URL', '')
        if 'pooler.supabase.com' in db_url:
            # Check port (Pooler uses 6543 for transaction mode, 5432 for session mode)
            if ':6543' in db_url or ':5432' in db_url:
                print('✅ Using Supabase Pooler (correct)')
            else:
                print('⚠️  Using Supabase Pooler but check port (should be 6543 or 5432)')
        elif 'supabase.co' in db_url:
            print('❌ Using direct Supabase (should use Pooler)')

        print()


# Global settings instance
settings = AppSettings()

# Validate on startup if Railway
_validate_railway_settings()
