"""
User Helper Functions
Shared utilities for getting user data that work with both SKIP_DB=true and SKIP_DB=false
"""
import os
from typing import Optional, Dict, Any

from core.services.user.user_service import user_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def get_user_data(telegram_user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get user data - uses API client if SKIP_DB=true, otherwise direct DB access

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        User dict with 'id' (internal ID) and other fields, or None if not found
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.get_user(telegram_user_id)
    else:
        user = await user_service.get_by_telegram_id(telegram_user_id)
        if not user:
            return None
        # Convert User model to dict
        return {
            "id": user.id,
            "telegram_user_id": user.telegram_user_id,
            "username": user.username,
            "stage": user.stage,
            "polygon_address": user.polygon_address,
            "solana_address": user.solana_address,
            "funded": user.funded,
            "auto_approval_completed": user.auto_approval_completed,
            "created_at": user.created_at.isoformat() if user.created_at else "",
            "updated_at": user.updated_at.isoformat() if user.updated_at else ""
        }


async def get_user_internal_id(telegram_user_id: int) -> Optional[int]:
    """
    Get user internal ID from Telegram ID

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        Internal user ID or None if not found
    """
    user_data = await get_user_data(telegram_user_id)
    if not user_data:
        return None
    return user_data.get("id")
