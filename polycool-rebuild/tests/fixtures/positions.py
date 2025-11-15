"""
Position fixtures for E2E tests
Provides realistic position data for trading and portfolio tests
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.models import Position
from core.services.position.position_service import position_service


@pytest.fixture
async def test_positions(funded_user, test_markets, db_session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fixture with realistic test positions for the funded user

    Includes active positions with P&L, take profit, stop loss
    """
    positions_data = [
        {
            "user_id": funded_user.id,
            "market_id": test_markets[0].id,  # BTC market
            "outcome": "Yes",
            "amount": 50.0,  # 50 USDC
            "entry_price": 0.65,
            "current_price": 0.67,  # Profit
            "pnl_amount": 1.0,  # 50 * (0.67 - 0.65) = 1.0
            "pnl_percentage": 3.08,  # 1.0 / 50 * 100
            "status": "active",
            "take_profit_price": 0.75,
            "stop_loss_price": 0.55,
            "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
            "updated_at": datetime.now(timezone.utc) - timedelta(minutes=30)
        },
        {
            "user_id": funded_user.id,
            "market_id": test_markets[1].id,  # Trump election market
            "outcome": "No",
            "amount": 25.0,  # 25 USDC
            "entry_price": 0.45,
            "current_price": 0.52,  # Profit
            "pnl_amount": 1.75,  # 25 * (0.52 - 0.45) = 1.75
            "pnl_percentage": 7.0,  # 1.75 / 25 * 100
            "status": "active",
            "take_profit_price": 0.60,
            "stop_loss_price": 0.35,
            "created_at": datetime.now(timezone.utc) - timedelta(hours=4),
            "updated_at": datetime.now(timezone.utc) - timedelta(minutes=15)
        },
        {
            "user_id": funded_user.id,
            "market_id": test_markets[2].id,  # Super Bowl market
            "outcome": "Yes",
            "amount": 10.0,  # 10 USDC
            "entry_price": 0.60,
            "current_price": 0.58,  # Loss
            "pnl_amount": -0.2,  # 10 * (0.58 - 0.60) = -0.2
            "pnl_percentage": -2.0,  # -0.2 / 10 * 100
            "status": "active",
            "take_profit_price": 0.70,
            "stop_loss_price": 0.50,
            "created_at": datetime.now(timezone.utc) - timedelta(hours=6),
            "updated_at": datetime.now(timezone.utc) - timedelta(hours=1)
        }
    ]

    # Insert positions into database
    positions = []
    for position_data in positions_data:
        position = Position(**position_data)
        db_session.add(position)
        positions.append(position)

    await db_session.commit()

    # Refresh to get IDs
    for position in positions:
        await db_session.refresh(position)

    return positions


@pytest.fixture
async def profitable_positions(test_positions) -> List[Dict[str, Any]]:
    """Filter positions with positive P&L"""
    return [p for p in test_positions if p.pnl_amount > 0]


@pytest.fixture
async def losing_positions(test_positions) -> List[Dict[str, Any]]:
    """Filter positions with negative P&L"""
    return [p for p in test_positions if p.pnl_amount < 0]


@pytest.fixture
async def closed_positions(funded_user, test_markets, db_session: AsyncSession) -> List[Dict[str, Any]]:
    """
    Fixture with closed positions (simulating completed trades)
    """
    closed_positions_data = [
        {
            "user_id": funded_user.id,
            "market_id": test_markets[3].id,  # ETH market
            "outcome": "Yes",
            "amount": 30.0,
            "entry_price": 0.70,
            "current_price": 0.75,  # Closed at profit
            "pnl_amount": 1.5,  # 30 * (0.75 - 0.70) = 1.5
            "pnl_percentage": 5.0,
            "status": "closed",
            "closed_at": datetime.now(timezone.utc) - timedelta(days=1),
            "created_at": datetime.now(timezone.utc) - timedelta(days=2),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=1)
        },
        {
            "user_id": funded_user.id,
            "market_id": test_markets[4].id,  # Resolved Olympics market
            "outcome": "Yes",
            "amount": 20.0,
            "entry_price": 0.90,
            "current_price": 1.0,  # Market resolved to Yes
            "pnl_amount": 2.0,  # 20 * (1.0 - 0.90) = 2.0
            "pnl_percentage": 10.0,
            "status": "closed",
            "closed_at": datetime.now(timezone.utc) - timedelta(days=7),
            "created_at": datetime.now(timezone.utc) - timedelta(days=30),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=7)
        }
    ]

    # Insert closed positions
    positions = []
    for position_data in closed_positions_data:
        position = Position(**position_data)
        db_session.add(position)
        positions.append(position)

    await db_session.commit()

    # Refresh to get IDs
    for position in positions:
        await db_session.refresh(position)

    return positions


@pytest.fixture
async def positions_with_tp_sl(test_positions) -> List[Dict[str, Any]]:
    """Filter positions that have take profit or stop loss set"""
    return [p for p in test_positions if p.take_profit_price or p.stop_loss_price]


@pytest.fixture
async def empty_portfolio_user(db_session: AsyncSession):
    """
    User fixture with no positions (empty portfolio)

    Useful for testing empty state UIs
    """
    from core.services.user.user_service import user_service

    user = await user_service.create_user(
        telegram_user_id=555555555,
        username="empty_portfolio",
        stage="ready",
        funded=True,
        auto_approval_completed=True
    )

    return user
