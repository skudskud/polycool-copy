"""
Referral API Routes
Endpoints for referral system management
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.services.user.user_service import user_service
from core.services.referral.referral_service import get_referral_service
from core.services.referral.commission_service import get_commission_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class CreateReferralRequest(BaseModel):
    """Request model for creating referral"""
    referrer_code: str
    referred_telegram_user_id: int


class ReferralStatsResponse(BaseModel):
    """Response model for referral stats"""
    user_username: Optional[str] = None
    referral_code: Optional[str] = None
    referral_link: Optional[str] = None
    bot_username: str
    total_referrals: dict
    total_commissions: dict
    commission_breakdown: List[dict]


class CommissionResponse(BaseModel):
    """Response model for commission"""
    id: int
    level: int
    commission_rate: float
    commission_amount: float
    fee_amount: float
    status: str
    created_at: Optional[str]


@router.get("/stats/{user_id}", response_model=ReferralStatsResponse)
async def get_referral_stats(user_id: int):
    """
    Get referral statistics for a user

    Args:
        user_id: Internal database user ID

    Returns:
        Referral statistics including link, referrals count, and commissions
    """
    try:
        referral_service = get_referral_service()
        stats = await referral_service.get_user_referral_stats(user_id)

        return ReferralStatsResponse(**stats)

    except Exception as e:
        logger.error(f"Error getting referral stats for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")


@router.get("/stats/telegram/{telegram_user_id}", response_model=ReferralStatsResponse)
async def get_referral_stats_by_telegram_id(telegram_user_id: int):
    """
    Get referral statistics for a user by Telegram ID

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        Referral statistics
    """
    try:
        # Get user by Telegram ID
        user = await user_service.get_by_telegram_id(telegram_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        referral_service = get_referral_service()
        stats = await referral_service.get_user_referral_stats(user.id)

        return ReferralStatsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting referral stats for Telegram user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")


@router.post("/create")
async def create_referral(request: CreateReferralRequest):
    """
    Create referral relationship

    Args:
        request: Referral creation request with referrer code and referred user ID

    Returns:
        Success message
    """
    try:
        logger.info(f"🔗 API: Creating referral - referrer_code='{request.referrer_code}', referred_telegram_id={request.referred_telegram_user_id}")

        # Get referred user by Telegram ID
        referred_user = await user_service.get_by_telegram_id(request.referred_telegram_user_id)
        if not referred_user:
            logger.error(f"❌ API: Referred user {request.referred_telegram_user_id} not found")
            raise HTTPException(status_code=404, detail="Referred user not found")

        logger.info(f"✅ API: Found referred user - id={referred_user.id}, telegram_id={referred_user.telegram_user_id}")

        referral_service = get_referral_service()
        success, message = await referral_service.create_referral(
            referrer_code=request.referrer_code,
            referred_user_id=referred_user.id
        )

        if not success:
            logger.warning(f"⚠️ API: Referral creation failed - {message}")
            raise HTTPException(status_code=400, detail=message)

        logger.info(f"✅ API: Referral created successfully - {message}")
        return {
            "success": True,
            "message": message
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating referral: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating referral: {str(e)}")


@router.get("/link/{user_id}")
async def get_referral_link(user_id: int):
    """
    Get referral link for a user

    Args:
        user_id: Internal database user ID

    Returns:
        Referral link
    """
    try:
        referral_service = get_referral_service()
        link = await referral_service.get_referral_link(user_id)

        if not link:
            raise HTTPException(status_code=404, detail="User not found or link generation failed")

        return {
            "referral_link": link,
            "user_id": user_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting referral link for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting link: {str(e)}")


@router.get("/link/telegram/{telegram_user_id}")
async def get_referral_link_by_telegram_id(telegram_user_id: int):
    """
    Get referral link for a user by Telegram ID

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        Referral link
    """
    try:
        user = await user_service.get_by_telegram_id(telegram_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        referral_service = get_referral_service()
        link = await referral_service.get_referral_link(user.id)

        if not link:
            raise HTTPException(status_code=500, detail="Link generation failed")

        return {
            "referral_link": link,
            "telegram_user_id": telegram_user_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting referral link for Telegram user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting link: {str(e)}")


@router.get("/commissions/{user_id}", response_model=List[CommissionResponse])
async def get_commissions(user_id: int, status: Optional[str] = None):
    """
    Get commissions for a user

    Args:
        user_id: Internal database user ID
        status: Optional status filter ('pending', 'paid', 'claimed')

    Returns:
        List of commissions
    """
    try:
        commission_service = get_commission_service()

        if status == 'pending':
            commissions = await commission_service.get_pending_commissions(user_id)
        else:
            # Get all commissions (implement full list if needed)
            commissions = await commission_service.get_pending_commissions(user_id)

        return [CommissionResponse(**c) for c in commissions]

    except Exception as e:
        logger.error(f"Error getting commissions for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting commissions: {str(e)}")


@router.get("/commissions/telegram/{telegram_user_id}", response_model=List[CommissionResponse])
async def get_commissions_by_telegram_id(telegram_user_id: int, status: Optional[str] = None):
    """
    Get commissions for a user by Telegram ID

    Args:
        telegram_user_id: Telegram user ID
        status: Optional status filter

    Returns:
        List of commissions
    """
    try:
        user = await user_service.get_by_telegram_id(telegram_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return await get_commissions(user.id, status)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting commissions for Telegram user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting commissions: {str(e)}")


@router.get("/commissions/pending/total/{user_id}")
async def get_total_pending_commission(user_id: int):
    """
    Get total pending commission amount for a user

    Args:
        user_id: Internal database user ID

    Returns:
        Total pending commission amount
    """
    try:
        commission_service = get_commission_service()
        total = await commission_service.get_total_pending_commission(user_id)

        return {
            "user_id": user_id,
            "total_pending_commission": total
        }

    except Exception as e:
        logger.error(f"Error getting total pending commission for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting total: {str(e)}")


@router.get("/referrals/{user_id}")
async def get_referrals_list(user_id: int, level: Optional[int] = None):
    """
    Get list of referrals for a user

    Args:
        user_id: Internal database user ID
        level: Optional level filter (1, 2, or 3)

    Returns:
        List of referrals
    """
    try:
        referral_service = get_referral_service()
        referrals = await referral_service.get_referrals_list(user_id, level)

        return {
            "user_id": user_id,
            "level": level,
            "referrals": referrals,
            "count": len(referrals)
        }

    except Exception as e:
        logger.error(f"Error getting referrals list for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting referrals: {str(e)}")


@router.post("/claim/{user_id}")
async def claim_commissions(user_id: int):
    """
    Claim pending commissions for a user

    Args:
        user_id: Internal database user ID

    Returns:
        Claim result with transaction hash
    """
    try:
        commission_service = get_commission_service()

        # Claim commissions (includes validation and payment)
        success, message, amount_paid, tx_hash = await commission_service.claim_commissions(user_id)

        if not success:
            # Check if it's a minimum amount error
            if "Minimum payout" in message:
                raise HTTPException(
                    status_code=400,
                    detail=message
                )
            # Check if treasury not configured
            elif "not yet available" in message or "not configured" in message:
                raise HTTPException(
                    status_code=503,
                    detail=message
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=message
                )

        return {
            "success": True,
            "message": message,
            "amount_paid": amount_paid,
            "tx_hash": tx_hash
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error claiming commissions for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error claiming commissions: {str(e)}")
