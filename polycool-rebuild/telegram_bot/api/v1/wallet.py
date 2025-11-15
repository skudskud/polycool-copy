"""
Wallet API Routes
"""
from typing import Optional
from fastapi import APIRouter, HTTPException

from core.services.user.user_service import user_service
from core.services.balance.balance_service import balance_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/balance/{user_id}")
async def get_wallet_balance(user_id: int):
    """
    Get wallet balance for user

    Args:
        user_id: Internal user ID (not Telegram ID)

    Returns:
        Balance data with USDC.e, POL balances and wallet addresses
    """
    try:
        # Get user by internal ID
        user = await user_service.get_by_id(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.polygon_address:
            return {
                "user_id": user_id,
                "telegram_user_id": user.telegram_user_id,
                "polygon_address": None,
                "solana_address": user.solana_address,
                "polygon_balance": None,
                "solana_balance": None,
                "usdc_balance": None,
                "pol_balance": None,
                "stage": user.stage
            }

        # Get balances
        balances = await balance_service.get_balances(user.polygon_address)

        return {
            "user_id": user_id,
            "telegram_user_id": user.telegram_user_id,
            "polygon_address": user.polygon_address,
            "solana_address": user.solana_address,
            "polygon_balance": balances.get('usdc', 0.0),  # USDC on Polygon
            "solana_balance": 0.0,  # TODO: Implement Solana balance check
            "usdc_balance": balances.get('usdc', 0.0),
            "pol_balance": balances.get('pol', 0.0),
            "stage": user.stage
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting wallet balance for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting balance: {str(e)}")


@router.get("/balance/telegram/{telegram_user_id}")
async def get_wallet_balance_by_telegram_id(telegram_user_id: int):
    """
    Get wallet balance for user by Telegram ID

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        Balance data with USDC.e, POL balances and wallet addresses
    """
    try:
        # Get user by Telegram ID
        user = await user_service.get_by_telegram_id(telegram_user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.polygon_address:
            return {
                "user_id": user.id,
                "telegram_user_id": user.telegram_user_id,
                "polygon_address": None,
                "solana_address": user.solana_address,
                "polygon_balance": None,
                "solana_balance": None,
                "usdc_balance": None,
                "pol_balance": None,
                "stage": user.stage
            }

        # Get balances
        balances = await balance_service.get_balances(user.polygon_address)

        return {
            "user_id": user.id,
            "telegram_user_id": user.telegram_user_id,
            "polygon_address": user.polygon_address,
            "solana_address": user.solana_address,
            "polygon_balance": balances.get('usdc', 0.0),  # USDC on Polygon
            "solana_balance": 0.0,  # TODO: Implement Solana balance check
            "usdc_balance": balances.get('usdc', 0.0),
            "pol_balance": balances.get('pol', 0.0),
            "stage": user.stage
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting wallet balance for Telegram user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting balance: {str(e)}")
