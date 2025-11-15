"""
Pytest configuration and shared fixtures
Provides common test setup, database fixtures, and mock services
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_user_id():
    """Mock Telegram user ID"""
    return 12345678


@pytest.fixture
def mock_wallet_data():
    """Mock wallet data structure"""
    return {
        'address': '0x742d35Cc6634C0532925a3b844343636E46c7Dd5',
        'private_key': 'mock_private_key_encrypted',
        'username': 'test_user',
        'funded': True,
        'usdc_approved': True,
        'pol_approved': True,
        'polymarket_approved': True,
        'auto_approval_completed': True
    }


@pytest.fixture
def mock_user_service():
    """Mock user service"""
    mock_service = Mock()
    mock_service.get_user_wallet = Mock(return_value={
        'address': '0x742d35Cc6634C0532925a3b844343636E46c7Dd5',
        'private_key': 'mock_key'
    })
    mock_service.create_user = AsyncMock(return_value=True)
    mock_service.get_user = Mock(return_value={'id': 1, 'telegram_user_id': 12345})
    return mock_service


@pytest.fixture
def mock_balance_checker():
    """Mock balance checker service"""
    mock_service = Mock()
    mock_service.get_balance = AsyncMock(return_value={
        'usdc': 100.0,
        'pol': 50.0,
        'formatted': '100.00 USDC / 50.00 POL'
    })
    return mock_service


@pytest.fixture
def mock_trading_service():
    """Mock trading service"""
    mock_service = Mock()
    mock_service.execute_trade = AsyncMock(return_value={
        'success': True,
        'tx_hash': '0x123abc...',
        'amount': 10.0,
        'tokens': 100
    })
    return mock_service


@pytest.fixture
def mock_market_data():
    """Mock market data"""
    return {
        'market_id': 'test_market_123',
        'question': 'Will event X happen?',
        'outcomes': ['Yes', 'No'],
        'prices': [0.65, 0.35],
        'liquidity': 50000.0,
        'volume': 100000.0,
        'yes_price': 0.65,
        'no_price': 0.35
    }


@pytest.fixture
def mock_db_session():
    """Mock database session"""
    mock_session = Mock()
    mock_session.query = Mock()
    mock_session.add = Mock()
    mock_session.commit = Mock()
    mock_session.close = Mock()
    return mock_session


@pytest.fixture
def mock_telegram_update():
    """Mock Telegram Update object"""
    mock_update = Mock()
    mock_update.effective_user = Mock(id=12345678, username='testuser')
    mock_update.effective_chat = Mock(id=12345678)
    mock_update.message = Mock()
    mock_update.message.reply_text = AsyncMock()
    mock_update.message.edit_text = AsyncMock()
    mock_update.callback_query = Mock()
    mock_update.callback_query.answer = AsyncMock()
    return mock_update


@pytest.fixture
def mock_telegram_context():
    """Mock Telegram CallbackContext"""
    mock_context = Mock()
    mock_context.user_data = {}
    mock_context.bot_data = {}
    mock_context.chat_data = {}
    return mock_context


@pytest.fixture(autouse=True)
def cleanup_env():
    """Clean up environment variables after each test"""
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)


# Pytest plugins and configuration
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "async: mark test as async"
    )


@pytest.fixture
def sample_market_list():
    """Sample market list for testing"""
    return [
        {
            'market_id': 'market_1',
            'question': 'Will Bitcoin reach $100k?',
            'yes_price': 0.72,
            'no_price': 0.28,
            'volume': 150000.0
        },
        {
            'market_id': 'market_2',
            'question': 'Will Ethereum reach $5k?',
            'yes_price': 0.65,
            'no_price': 0.35,
            'volume': 100000.0
        },
        {
            'market_id': 'market_3',
            'question': 'Fed raises rates in next meeting?',
            'yes_price': 0.42,
            'no_price': 0.58,
            'volume': 50000.0
        }
    ]
