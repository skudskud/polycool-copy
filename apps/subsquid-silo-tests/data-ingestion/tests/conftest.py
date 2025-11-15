"""
Pytest Configuration and Global Fixtures
Sets up test environment and shared fixtures.
"""

import pytest
import os
import sys
from pathlib import Path
import redis.asyncio as redis

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file first if it exists
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ Loaded .env from {env_path}")

# Set up test environment variables (only defaults if not in .env)
os.environ.setdefault("EXPERIMENTAL_SUBSQUID", "true")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("POLL_MS", "5000")  # Fast polling for tests
os.environ.setdefault("WS_MAX_SUBSCRIPTIONS", "5")  # Limit for tests


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests"""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset metrics before each test"""
    from src.wh import webhook_worker

    # Reset webhook metrics
    webhook_worker.metrics.event_count = 0
    webhook_worker.metrics.success_count = 0
    webhook_worker.metrics.error_count = 0
    webhook_worker.metrics.last_event_time = None

    yield


@pytest.fixture
async def clean_test_tables():
    """Clean test tables before each test (optional - not autouse)"""
    from src.db.client import get_db_client

    db = await get_db_client()
    if db.pool:
        async with db.pool.acquire() as conn:
            try:
                await conn.execute("TRUNCATE subsquid_markets_poll CASCADE")
                await conn.execute("TRUNCATE subsquid_markets_ws CASCADE")
                await conn.execute("TRUNCATE subsquid_markets_wh CASCADE")
                print("\n✅ Test tables cleaned")
            except Exception as e:
                print(f"\n⚠️ Could not clean tables: {e}")
    yield
    # Keep data for debugging


@pytest.fixture
async def redis_client():
    """Redis client for tests"""
    client = await redis.from_url(
        "redis://localhost:6379/1",
        decode_responses=True
    )
    yield client
    await client.close()


@pytest.fixture
def webhook_client():
    """FastAPI test client for webhook"""
    from fastapi.testclient import TestClient
    from src.wh.webhook_worker import app
    return TestClient(app)


@pytest.fixture
async def db_client():
    """Database client fixture"""
    from src.db.client import get_db_client
    return await get_db_client()


@pytest.fixture
def mock_db_client():
    """Create a mock database client"""
    from unittest.mock import AsyncMock, MagicMock

    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.upsert_markets_poll = AsyncMock(return_value=10)
    client.upsert_market_ws = AsyncMock(return_value=True)
    client.insert_webhook_event = AsyncMock(return_value=1)
    client.get_markets_poll = AsyncMock(return_value=[])
    client.get_markets_ws = AsyncMock(return_value=[])
    client.get_webhook_events = AsyncMock(return_value=[])
    client.calculate_freshness_poll = AsyncMock(return_value={})
    client.calculate_freshness_ws = AsyncMock(return_value={})

    return client


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client"""
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.publish = AsyncMock(return_value=1)
    client.pubsub = AsyncMock()
    client.info = AsyncMock(return_value={"db0": {"keys": 100}})
    client.close = AsyncMock()

    return client


def pytest_configure(config):
    """Pytest hook to configure test session"""
    print("\n" + "=" * 80)
    print("🧪 PYTEST CONFIGURATION - Subsquid Silo Integration Tests")
    print("=" * 80)
    print(f"  EXPERIMENTAL_SUBSQUID: {os.environ.get('EXPERIMENTAL_SUBSQUID')}")
    print(f"  DATABASE_URL: {os.environ.get('DATABASE_URL', 'NOT SET')[:40]}...")
    print(f"  REDIS_URL: {os.environ.get('REDIS_URL', 'NOT SET')[:40]}...")
    print(f"  POLL_MS: {os.environ.get('POLL_MS', 'NOT SET')}")
    print(f"  WS_MAX_SUBSCRIPTIONS: {os.environ.get('WS_MAX_SUBSCRIPTIONS', 'NOT SET')}")
    print("=" * 80 + "\n")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to capture test results"""
    outcome = yield
    result = outcome.get_result()

    # Log test results
    if result.when == "call":
        if result.outcome == "passed":
            print(f"✅ {item.name}")
        elif result.outcome == "failed":
            print(f"❌ {item.name}")
        elif result.outcome == "skipped":
            print(f"⏭️ {item.name}")
