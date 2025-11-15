"""
Pytest configuration and shared fixtures
"""
import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.database.connection import Base
from core.database.models import User, Market, Position
from infrastructure.config.settings import settings


# Test database URL
TEST_DATABASE_URL = settings.database.test_url or "postgresql://polycool_test:polycool2025test@localhost:5433/polycool_test"

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    echo=False,  # Disable SQL logging in tests
)

# Create test session factory
test_session_factory = sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_db_engine():
    """Create and teardown test database."""
    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine

    # Drop all tables after tests
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session(test_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for each test."""
    async with test_session_factory() as session:
        yield session
        # Rollback any changes after test
        await session.rollback()


@pytest.fixture
async def sample_user(db_session: AsyncSession):
    """Create a sample user for testing."""
    user = User(
        telegram_user_id=123456789,
        username="testuser",
        polygon_address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        polygon_private_key="encrypted_polygon_key",
        solana_address="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        solana_private_key="encrypted_solana_key",
        stage="ready",
        funded=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def sample_market(db_session: AsyncSession):
    """Create a sample market for testing."""
    market = Market(
        id="test_market_123",
        source="poll",
        title="Will BTC reach $100k in 2025?",
        description="Test market description",
        category="crypto",
        outcomes=["Yes", "No"],
        outcome_prices=[0.6, 0.4],
        volume=10000.0,
        liquidity=5000.0,
        last_trade_price=0.55,
        is_active=True,
        is_resolved=False,
    )
    db_session.add(market)
    await db_session.commit()
    await db_session.refresh(market)
    return market


@pytest.fixture
async def sample_position(db_session: AsyncSession, sample_user: User, sample_market: Market):
    """Create a sample position for testing."""
    position = Position(
        user_id=sample_user.id,
        market_id=sample_market.id,
        outcome="Yes",
        amount=100.0,
        entry_price=0.6,
        pnl_amount=0.0,
        status="active",
    )
    db_session.add(position)
    await db_session.commit()
    await db_session.refresh(position)
    return position


@pytest.fixture
async def mock_cache():
    """Mock cache manager for testing."""
    class MockCache:
        def __init__(self):
            self.data = {}

        async def get(self, key: str, data_type: str = "default"):
            return self.data.get(key)

        async def set(self, key: str, value, data_type: str = "default", ttl: int = None):
            self.data[key] = value
            return True

        async def delete(self, key: str):
            return bool(self.data.pop(key, None))

        def get_stats(self):
            return {
                'hits': 0,
                'misses': 0,
                'sets': len(self.data),
                'invalidations': 0,
                'hit_rate': 0.0,
            }

    return MockCache()


@pytest.fixture
async def mock_redis():
    """Mock Redis client for testing."""
    class MockRedis:
        def __init__(self):
            self.data = {}

        def get(self, key):
            return self.data.get(key)

        def setex(self, key, ttl, value):
            self.data[key] = value
            return True

        def delete(self, *keys):
            deleted = 0
            for key in keys:
                if key in self.data:
                    del self.data[key]
                    deleted += 1
            return deleted

        def keys(self, pattern):
            return [k for k in self.data.keys() if pattern.replace('*', '') in k]

        def ping(self):
            return True

    return MockRedis()
