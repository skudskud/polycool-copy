"""
Mock services for E2E tests
Provides mocked external services to avoid real API calls and transactions
"""

import pytest
from unittest.mock import Mock, AsyncMock
from typing import Dict, Any, Optional


@pytest.fixture
def mock_clob_service():
    """
    Mock CLOBService for avoiding real Polymarket API calls

    Provides realistic responses for:
    - Balance queries (returns 100 USDC)
    - Order placement (returns mock order ID)
    - Order cancellation (success)
    - Market data (mock orderbook)
    """
    mock_service = Mock()

    # Mock balance method
    mock_service.get_balance = AsyncMock(return_value={
        "balance": 100.0,
        "available_balance": 95.0,
        "locked_balance": 5.0
    })

    # Mock place_order method
    mock_service.place_order = AsyncMock(return_value={
        "order_id": "test-order-12345",
        "status": "placed",
        "amount": 10.0,
        "price": 0.65,
        "outcome": "Yes"
    })

    # Mock cancel_order method
    mock_service.cancel_order = AsyncMock(return_value={
        "success": True,
        "order_id": "test-order-12345"
    })

    # Mock get_order method
    mock_service.get_order = AsyncMock(return_value={
        "order_id": "test-order-12345",
        "status": "filled",
        "amount": 10.0,
        "price": 0.65,
        "outcome": "Yes",
        "filled_amount": 10.0
    })

    # Mock get_orders method
    mock_service.get_orders = AsyncMock(return_value=[
        {
            "order_id": "test-order-12345",
            "status": "filled",
            "amount": 10.0,
            "price": 0.65,
            "outcome": "Yes",
            "timestamp": "2024-01-01T12:00:00Z"
        }
    ])

    # Mock get_orderbook method
    mock_service.get_orderbook = AsyncMock(return_value={
        "market_id": "test-market-1",
        "bids": [
            {"price": 0.64, "size": 100.0},
            {"price": 0.63, "size": 200.0}
        ],
        "asks": [
            {"price": 0.66, "size": 150.0},
            {"price": 0.67, "size": 250.0}
        ]
    })

    return mock_service


@pytest.fixture
def mock_bridge_service():
    """
    Mock BridgeService for avoiding real bridge transactions

    Provides realistic responses for SOL → USDC bridging
    """
    mock_service = Mock()

    # Mock bridge_sol_to_usdc method
    mock_service.bridge_sol_to_usdc = AsyncMock(return_value={
        "success": True,
        "tx_hash": "test-bridge-tx-12345",
        "amount_sol": 0.1,
        "expected_usdc": 20.0,
        "fee": 0.001,
        "status": "pending"
    })

    # Mock get_bridge_status method
    mock_service.get_bridge_status = AsyncMock(return_value={
        "tx_hash": "test-bridge-tx-12345",
        "status": "completed",
        "usdc_received": 19.8,  # After fees
        "timestamp": "2024-01-01T12:00:00Z"
    })

    return mock_service


@pytest.fixture
def mock_telegram_bot():
    """
    Mock Telegram bot for testing bot responses

    Captures all sent messages for verification
    """
    mock_bot = Mock()

    # Mock send_message
    mock_bot.send_message = AsyncMock()

    # Mock edit_message_text
    mock_bot.edit_message_text = AsyncMock()

    # Mock answer_callback_query
    mock_bot.answer_callback_query = AsyncMock()

    # Mock delete_message
    mock_bot.delete_message = AsyncMock()

    return mock_bot


@pytest.fixture
def mock_redis():
    """
    Mock Redis client for testing cache operations

    Provides realistic cache behavior without real Redis
    """
    mock_redis = Mock()

    # Mock cache operations
    mock_redis.get = AsyncMock(return_value=None)  # Cache miss by default
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.exists = AsyncMock(return_value=0)

    # Mock pipeline for batch operations
    mock_pipeline = Mock()
    mock_pipeline.get = Mock(return_value=mock_pipeline)
    mock_pipeline.set = Mock(return_value=mock_pipeline)
    mock_pipeline.execute = AsyncMock(return_value=[None, True])
    mock_redis.pipeline = Mock(return_value=mock_pipeline)

    return mock_redis


@pytest.fixture
def mock_web3_provider():
    """
    Mock Web3 provider for blockchain interactions

    Provides realistic blockchain responses
    """
    mock_provider = Mock()

    # Mock eth.get_balance
    mock_provider.eth.get_balance = AsyncMock(return_value=1000000000000000000)  # 1 ETH in wei

    # Mock eth.get_transaction_count
    mock_provider.eth.get_transaction_count = AsyncMock(return_value=5)

    # Mock eth.estimate_gas
    mock_provider.eth.estimate_gas = AsyncMock(return_value=21000)

    # Mock eth.gas_price
    mock_provider.eth.gas_price = AsyncMock(return_value=20000000000)  # 20 gwei

    # Mock send_raw_transaction
    mock_provider.eth.send_raw_transaction = AsyncMock(return_value=b"test_tx_hash")

    # Mock get_transaction_receipt
    mock_provider.eth.get_transaction_receipt = AsyncMock(return_value={
        "status": 1,
        "blockNumber": 12345678,
        "gasUsed": 21000,
        "effectiveGasPrice": 20000000000
    })

    return mock_provider


@pytest.fixture
def mock_position_sync():
    """
    Mock position synchronization from blockchain

    Simulates fetching positions from CLOB API
    """
    mock_sync = Mock()

    # Mock sync_positions_from_blockchain method
    mock_sync.sync_positions_from_blockchain = AsyncMock(return_value=[
        {
            "market_id": "test-market-1",
            "outcome": "Yes",
            "amount": 50.0,
            "entry_price": 0.65,
            "current_price": 0.67,
            "pnl": 1.0
        },
        {
            "market_id": "test-market-2",
            "outcome": "No",
            "amount": 25.0,
            "entry_price": 0.45,
            "current_price": 0.52,
            "pnl": 1.75
        }
    ])

    return mock_sync


@pytest.fixture
def mock_market_data():
    """
    Mock market data updates from WebSocket/streamer

    Provides realistic price updates
    """
    mock_data = Mock()

    # Mock price update
    mock_data.price_update = {
        "market_id": "test-market-1",
        "outcome_prices": {
            "Yes": 0.67,
            "No": 0.33
        },
        "volume": 1250000.50,
        "timestamp": "2024-01-01T12:00:00Z"
    }

    # Mock orderbook update
    mock_data.orderbook_update = {
        "market_id": "test-market-1",
        "bids": [
            {"price": 0.66, "size": 1000.0},
            {"price": 0.65, "size": 2000.0}
        ],
        "asks": [
            {"price": 0.68, "size": 1500.0},
            {"price": 0.69, "size": 2500.0}
        ]
    }

    return mock_data


@pytest.fixture
def mock_openai_client():
    """
    Mock OpenAI client for smart trading AI features

    Provides realistic AI responses
    """
    mock_client = Mock()

    # Mock chat completions
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = "Based on market analysis, BTC has strong momentum. Consider buying Yes with 25% allocation."
    mock_response.usage = {"total_tokens": 150}

    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    return mock_client
