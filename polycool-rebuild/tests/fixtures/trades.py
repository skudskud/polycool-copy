"""
Trade fixtures for E2E tests
Provides realistic smart wallet trade data for copy trading and smart trading tests
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.models import Trade, WatchedAddress


@pytest.fixture
async def smart_wallet_addresses(db_session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fixture with smart wallet addresses for testing copy trading

    Includes both copy leaders and smart traders
    """
    addresses_data = [
        {
            "address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e1",
            "blockchain": "polygon",
            "address_type": "copy_leader",
            "name": "Pro Trader Alpha",
            "description": "Experienced crypto trader with 85% win rate",
            "risk_score": 7.5,
            "is_active": True,
            "total_trades": 150,
            "win_rate": 0.85,
            "total_volume": 50000.0,
            "created_at": datetime.now(timezone.utc) - timedelta(days=30),
            "updated_at": datetime.now(timezone.utc) - timedelta(hours=1)
        },
        {
            "address": "0x8ba1f109551bD432803012645ac136ddd64DBA72e",
            "blockchain": "polygon",
            "address_type": "copy_leader",
            "name": "Politics Expert",
            "description": "Political markets specialist",
            "risk_score": 8.2,
            "is_active": True,
            "total_trades": 89,
            "win_rate": 0.78,
            "total_volume": 25000.0,
            "created_at": datetime.now(timezone.utc) - timedelta(days=20),
            "updated_at": datetime.now(timezone.utc) - timedelta(hours=2)
        },
        {
            "address": "0x1234567890abcdef1234567890abcdef12345678",
            "blockchain": "polygon",
            "address_type": "smart_trader",
            "name": "AI Trading Bot",
            "description": "Algorithmic trading bot",
            "risk_score": 9.1,
            "is_active": True,
            "total_trades": 500,
            "win_rate": 0.92,
            "total_volume": 100000.0,
            "created_at": datetime.now(timezone.utc) - timedelta(days=60),
            "updated_at": datetime.now(timezone.utc) - timedelta(minutes=30)
        }
    ]

    # Insert addresses into database
    addresses = []
    for addr_data in addresses_data:
        address = WatchedAddress(**addr_data)
        db_session.add(address)
        addresses.append(address)

    await db_session.commit()

    # Refresh to get IDs
    for addr in addresses:
        await db_session.refresh(addr)

    return addresses


@pytest.fixture
async def recent_smart_trades(smart_wallet_addresses, test_markets, db_session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fixture with recent trades from smart wallets

    Used for smart trading recommendations and copy trading tests
    """
    base_time = datetime.now(timezone.utc)

    trades_data = [
        # Recent BTC trade by Pro Trader Alpha
        {
            "watched_address_id": smart_wallet_addresses[0].id,
            "market_id": test_markets[0].id,  # BTC market
            "outcome": "Yes",
            "amount": 1000.0,
            "price": 0.65,
            "tx_hash": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "block_number": 12345678,
            "timestamp": base_time - timedelta(minutes=15),
            "trade_type": "BUY",
            "is_processed": True,
            "created_at": base_time - timedelta(minutes=15)
        },
        # Politics trade by Politics Expert
        {
            "watched_address_id": smart_wallet_addresses[1].id,
            "market_id": test_markets[1].id,  # Trump election market
            "outcome": "Yes",
            "amount": 500.0,
            "price": 0.55,
            "tx_hash": "0xfedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321",
            "block_number": 12345679,
            "timestamp": base_time - timedelta(minutes=30),
            "trade_type": "BUY",
            "is_processed": True,
            "created_at": base_time - timedelta(minutes=30)
        },
        # ETH trade by AI Trading Bot
        {
            "watched_address_id": smart_wallet_addresses[2].id,
            "market_id": test_markets[3].id,  # ETH market
            "outcome": "Yes",
            "amount": 750.0,
            "price": 0.75,
            "tx_hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "block_number": 12345680,
            "timestamp": base_time - timedelta(minutes=45),
            "trade_type": "BUY",
            "is_processed": True,
            "created_at": base_time - timedelta(minutes=45)
        },
        # Super Bowl trade by Pro Trader Alpha (older)
        {
            "watched_address_id": smart_wallet_addresses[0].id,
            "market_id": test_markets[2].id,  # Super Bowl market
            "outcome": "Yes",
            "amount": 250.0,
            "price": 0.60,
            "tx_hash": "0x987654321fedcba987654321fedcba987654321fedcba987654321fedcba",
            "block_number": 12345677,
            "timestamp": base_time - timedelta(hours=1),
            "trade_type": "BUY",
            "is_processed": True,
            "created_at": base_time - timedelta(hours=1)
        },
        # SELL trade (for testing sell logic)
        {
            "watched_address_id": smart_wallet_addresses[2].id,
            "market_id": test_markets[0].id,  # BTC market (SELL)
            "outcome": "No",
            "amount": 300.0,
            "price": 0.35,
            "tx_hash": "0x1111111111111111111111111111111111111111111111111111111111111111",
            "block_number": 12345681,
            "timestamp": base_time - timedelta(hours=2),
            "trade_type": "SELL",
            "is_processed": True,
            "created_at": base_time - timedelta(hours=2)
        }
    ]

    # Insert trades into database
    trades = []
    for trade_data in trades_data:
        trade = Trade(**trade_data)
        db_session.add(trade)
        trades.append(trade)

    await db_session.commit()

    # Refresh to get IDs
    for trade in trades:
        await db_session.refresh(trade)

    return trades


@pytest.fixture
async def copy_trading_allocations(funded_user, smart_wallet_addresses, db_session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fixture with copy trading allocations for testing copy trading flow

    Includes different allocation types and modes
    """
    from core.database.models import CopyTradingAllocation

    allocations_data = [
        {
            "user_id": funded_user.id,
            "leader_address_id": smart_wallet_addresses[0].id,  # Pro Trader Alpha
            "allocation_type": "percentage",
            "allocation_value": 50.0,  # 50%
            "mode": "proportional",
            "sell_mode": "proportional",
            "is_active": True,
            "total_copied_trades": 3,
            "total_invested": 150.0,
            "total_pnl": 7.5,
            "created_at": datetime.now(timezone.utc) - timedelta(days=5),
            "updated_at": datetime.now(timezone.utc) - timedelta(hours=1)
        },
        {
            "user_id": funded_user.id,
            "leader_address_id": smart_wallet_addresses[1].id,  # Politics Expert
            "allocation_type": "fixed_amount",
            "allocation_value": 25.0,  # $25 per trade
            "mode": "fixed_amount",
            "sell_mode": "proportional",
            "is_active": True,
            "total_copied_trades": 1,
            "total_invested": 25.0,
            "total_pnl": 1.25,
            "created_at": datetime.now(timezone.utc) - timedelta(days=3),
            "updated_at": datetime.now(timezone.utc) - timedelta(hours=2)
        },
        {
            "user_id": funded_user.id,
            "leader_address_id": smart_wallet_addresses[2].id,  # AI Trading Bot
            "allocation_type": "percentage",
            "allocation_value": 25.0,  # 25%
            "mode": "proportional",
            "sell_mode": "proportional",
            "is_active": False,  # Paused
            "total_copied_trades": 2,
            "total_invested": 50.0,
            "total_pnl": -2.5,
            "created_at": datetime.now(timezone.utc) - timedelta(days=7),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=1)
        }
    ]

    # Insert allocations into database
    allocations = []
    for alloc_data in allocations_data:
        allocation = CopyTradingAllocation(**alloc_data)
        db_session.add(allocation)
        allocations.append(allocation)

    await db_session.commit()

    # Refresh to get IDs
    for alloc in allocations:
        await db_session.refresh(alloc)

    return allocations


@pytest.fixture
async def large_volume_trades(smart_wallet_addresses, test_markets, db_session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fixture with large volume trades (> $1000)

    Used for testing smart trading filters
    """
    base_time = datetime.now(timezone.utc)

    large_trades_data = [
        {
            "watched_address_id": smart_wallet_addresses[0].id,
            "market_id": test_markets[0].id,
            "outcome": "Yes",
            "amount": 5000.0,  # Large trade
            "price": 0.65,
            "tx_hash": "0xlarge_trade_11111111111111111111111111111111111111111111111111111111",
            "block_number": 12345682,
            "timestamp": base_time - timedelta(minutes=10),
            "trade_type": "BUY",
            "is_processed": True,
            "created_at": base_time - timedelta(minutes=10)
        },
        {
            "watched_address_id": smart_wallet_addresses[2].id,
            "market_id": test_markets[1].id,
            "outcome": "No",
            "amount": 2500.0,  # Large trade
            "price": 0.45,
            "tx_hash": "0xlarge_trade_22222222222222222222222222222222222222222222222222222222",
            "block_number": 12345683,
            "timestamp": base_time - timedelta(minutes=20),
            "trade_type": "BUY",
            "is_processed": True,
            "created_at": base_time - timedelta(minutes=20)
        }
    ]

    # Insert large trades
    trades = []
    for trade_data in large_trades_data:
        trade = Trade(**trade_data)
        db_session.add(trade)
        trades.append(trade)

    await db_session.commit()

    # Refresh to get IDs
    for trade in trades:
        await db_session.refresh(trade)

    return trades
