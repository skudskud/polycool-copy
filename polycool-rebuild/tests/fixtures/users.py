"""
User fixtures for E2E tests
Provides realistic user data including funded users ready for trading
"""

import pytest
import asyncio
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.user.user_service import user_service
from core.services.wallet.wallet_service import wallet_service
from infrastructure.config.settings import settings


@pytest.fixture
async def funded_user(db_session: AsyncSession) -> Dict[str, Any]:
    """
    User fixture: User onboarding READY avec wallets funded et API credentials

    - stage: "ready" (pas onboarding)
    - funded: True
    - auto_approval_completed: True
    - Wallets Polygon + Solana générés et encryptés
    - API credentials Polymarket configurés
    - Balance mockée (100 USDC)

    Utilisation: Tests nécessitant user prêt à trader
    """
    # Créer user avec wallets et API keys
    user_data = {
        "telegram_user_id": 123456789,
        "username": "test_trader",
        "stage": "ready",
        "funded": True,
        "auto_approval_completed": True,
        "api_key": settings.clob.api_key if hasattr(settings.clob, 'api_key') else "test_api_key",
        "api_secret": settings.clob.api_secret if hasattr(settings.clob, 'api_secret') else "test_api_secret",
        "api_passphrase": settings.clob.api_passphrase if hasattr(settings.clob, 'api_passphrase') else "test_passphrase"
    }

    user = await user_service.create_user(**user_data)

    # Vérifier que les wallets sont générés
    assert user.polygon_address is not None
    assert user.solana_address is not None
    assert user.polygon_private_key is not None  # Encrypted
    assert user.solana_private_key is not None   # Encrypted

    return user


@pytest.fixture
async def onboarding_user(db_session: AsyncSession) -> Dict[str, Any]:
    """
    User fixture: User en phase onboarding (wallets créés mais pas funded)

    - stage: "onboarding"
    - funded: False
    - auto_approval_completed: False
    - Wallets générés mais pas de fonds

    Utilisation: Tests onboarding flow
    """
    user_data = {
        "telegram_user_id": 987654321,
        "username": "new_user",
        "stage": "onboarding",
        "funded": False,
        "auto_approval_completed": False
    }

    user = await user_service.create_user(**user_data)
    return user


@pytest.fixture
async def multiple_users(db_session: AsyncSession) -> Dict[str, Any]:
    """
    Fixture with multiple users for isolation testing

    Returns dict with user_a, user_b, user_c
    """
    users = {}

    # User A - funded trader
    users['user_a'] = await user_service.create_user(
        telegram_user_id=111111111,
        username="trader_a",
        stage="ready",
        funded=True,
        auto_approval_completed=True
    )

    # User B - onboarding
    users['user_b'] = await user_service.create_user(
        telegram_user_id=222222222,
        username="trader_b",
        stage="onboarding",
        funded=False,
        auto_approval_completed=False
    )

    # User C - funded but no API keys
    users['user_c'] = await user_service.create_user(
        telegram_user_id=333333333,
        username="trader_c",
        stage="ready",
        funded=True,
        auto_approval_completed=True
    )

    return users


@pytest.fixture
def mock_clob_balance(mocker):
    """
    Mock CLOB balance response for funded users

    Returns 100 USDC balance for realistic trading tests
    """
    mock_response = {
        "balance": 100.0,
        "available_balance": 95.0,
        "locked_balance": 5.0
    }

    # Mock the CLOB service balance method
    mock_clob = mocker.patch('core.services.clob.clob_service.CLOBService')
    mock_clob.get_balance.return_value = mock_response

    return mock_clob
