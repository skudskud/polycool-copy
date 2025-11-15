"""
Market fixtures for E2E tests
Provides realistic market data for trading tests
"""

import pytest
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.models import Market


@pytest.fixture
async def test_markets(db_session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fixture with realistic test markets for trading

    Includes various market types: crypto, politics, sports, etc.
    All markets are active and have realistic prices.
    """
    markets_data = [
        {
            "id": "test-market-1",
            "source": "gamma",
            "title": "Will Bitcoin reach $100k by EOY?",
            "description": "Will Bitcoin (BTC) reach $100,000 by December 31, 2024?",
            "category": "Crypto",
            "outcomes": ["Yes", "No"],
            "outcome_prices": [0.65, 0.35],
            "events": [{"id": "event-1", "title": "Bitcoin Price Prediction"}],
            "is_event_market": True,
            "parent_event_id": None,
            "volume": 1250000.50,
            "liquidity": 50000.00,
            "last_trade_price": 0.67,
            "last_mid_price": 0.65,
            "clob_token_ids": ["123456789", "987654321"],
            "condition_id": "0x1234567890abcdef",
            "is_resolved": False,
            "resolved_outcome": None,
            "resolved_at": None,
            "start_date": None,
            "end_date": "2024-12-31T23:59:59Z",
            "is_active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "event_id": "bitcoin-eoy-2024",
            "event_slug": "bitcoin-price-prediction",
            "event_title": "Bitcoin EOY Price Prediction",
            "polymarket_url": "https://polymarket.com/event/bitcoin-eoy-2024"
        },
        {
            "id": "test-market-2",
            "source": "gamma",
            "title": "Will Donald Trump win the 2024 US Presidential Election?",
            "description": "Will Donald Trump win the 2024 United States Presidential Election?",
            "category": "Politics",
            "outcomes": ["Yes", "No"],
            "outcome_prices": [0.55, 0.45],
            "events": [{"id": "event-2", "title": "2024 US Election"}],
            "is_event_market": True,
            "parent_event_id": None,
            "volume": 2500000.75,
            "liquidity": 100000.00,
            "last_trade_price": 0.52,
            "last_mid_price": 0.55,
            "clob_token_ids": ["1122334455", "5566778899"],
            "condition_id": "0xabcdef1234567890",
            "is_resolved": False,
            "resolved_outcome": None,
            "resolved_at": None,
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-11-05T23:59:59Z",
            "is_active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "event_id": "us-election-2024",
            "event_slug": "us-presidential-election-2024",
            "event_title": "2024 US Presidential Election",
            "polymarket_url": "https://polymarket.com/event/us-election-2024"
        },
        {
            "id": "test-market-3",
            "source": "gamma",
            "title": "Will the Kansas City Chiefs win Super Bowl 2025?",
            "description": "Will the Kansas City Chiefs win Super Bowl 2025 against their opponent?",
            "category": "Sports",
            "outcomes": ["Yes", "No"],
            "outcome_prices": [0.60, 0.40],
            "events": [{"id": "event-3", "title": "Super Bowl 2025"}],
            "is_event_market": True,
            "parent_event_id": None,
            "volume": 750000.25,
            "liquidity": 25000.00,
            "last_trade_price": 0.58,
            "last_mid_price": 0.60,
            "clob_token_ids": ["7788991122", "3344556677"],
            "condition_id": "0xfedcba0987654321",
            "is_resolved": False,
            "resolved_outcome": None,
            "resolved_at": None,
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-02-09T23:59:59Z",
            "is_active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "event_id": "super-bowl-2025",
            "event_slug": "super-bowl-lvix",
            "event_title": "Super Bowl LIX - Kansas City Chiefs",
            "polymarket_url": "https://polymarket.com/event/super-bowl-2025"
        },
        {
            "id": "test-market-4",
            "source": "gamma",
            "title": "Will Ethereum reach $5k by June 2025?",
            "description": "Will Ethereum (ETH) reach $5,000 by June 30, 2025?",
            "category": "Crypto",
            "outcomes": ["Yes", "No"],
            "outcome_prices": [0.75, 0.25],
            "events": [{"id": "event-4", "title": "Ethereum Price Target"}],
            "is_event_market": True,
            "parent_event_id": None,
            "volume": 500000.00,
            "liquidity": 15000.00,
            "last_trade_price": 0.73,
            "last_mid_price": 0.75,
            "clob_token_ids": ["9900112233", "4455667788"],
            "condition_id": "0x1122334455667788",
            "is_resolved": False,
            "resolved_outcome": None,
            "resolved_at": None,
            "start_date": None,
            "end_date": "2025-06-30T23:59:59Z",
            "is_active": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "event_id": "ethereum-5k-june-2025",
            "event_slug": "ethereum-price-target-5k",
            "event_title": "Ethereum $5k Price Target",
            "polymarket_url": "https://polymarket.com/event/ethereum-5k-june-2025"
        },
        {
            "id": "test-market-resolved",
            "source": "gamma",
            "title": "Will the 2024 Paris Olympics be held?",
            "description": "Will the 2024 Summer Olympics be held in Paris?",
            "category": "Sports",
            "outcomes": ["Yes", "No"],
            "outcome_prices": [1.0, 0.0],  # Resolved to Yes
            "events": [{"id": "event-resolved", "title": "2024 Paris Olympics"}],
            "is_event_market": True,
            "parent_event_id": None,
            "volume": 100000.00,
            "liquidity": 0.00,
            "last_trade_price": 1.0,
            "last_mid_price": 1.0,
            "clob_token_ids": ["123123123", "456456456"],
            "condition_id": "0x999888777666555",
            "is_resolved": True,
            "resolved_outcome": "Yes",
            "resolved_at": "2024-07-26T20:00:00Z",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-07-26T23:59:59Z",
            "is_active": False,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-07-26T20:00:00Z",
            "event_id": "paris-olympics-2024",
            "event_slug": "paris-olympics-2024-held",
            "event_title": "2024 Paris Olympics",
            "polymarket_url": "https://polymarket.com/event/paris-olympics-2024"
        }
    ]

    # Insert markets into database
    markets = []
    for market_data in markets_data:
        market = Market(**market_data)
        db_session.add(market)
        markets.append(market)

    await db_session.commit()

    # Refresh to get IDs
    for market in markets:
        await db_session.refresh(market)

    return markets


@pytest.fixture
async def active_crypto_markets(test_markets) -> List[Dict[str, Any]]:
    """Filter for active crypto markets only"""
    return [m for m in test_markets if m.category == "Crypto" and m.is_active]


@pytest.fixture
async def resolved_market(test_markets) -> Dict[str, Any]:
    """Single resolved market for testing resolution logic"""
    resolved_markets = [m for m in test_markets if m.is_resolved]
    return resolved_markets[0] if resolved_markets else None
