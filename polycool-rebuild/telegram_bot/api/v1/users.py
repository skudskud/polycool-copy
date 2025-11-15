"""
Users API Routes
Endpoints for user management (creation, retrieval)
"""
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.services.user.user_service import user_service
from core.services.wallet.wallet_service import wallet_service
from core.services.encryption.encryption_service import encryption_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Rate limiting for private key endpoint
# Store: {telegram_user_id: [timestamps]}
_private_key_rate_limit: dict[int, list[datetime]] = defaultdict(list)
RATE_LIMIT_WINDOW = timedelta(minutes=1)
RATE_LIMIT_MAX_REQUESTS = 5


def _check_rate_limit(telegram_user_id: int) -> bool:
    """
    Check if user has exceeded rate limit for private key requests

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        True if within limit, False if exceeded
    """
    now = datetime.utcnow()
    user_requests = _private_key_rate_limit[telegram_user_id]

    # Remove old requests outside window
    user_requests[:] = [req_time for req_time in user_requests if now - req_time < RATE_LIMIT_WINDOW]

    # Check if limit exceeded
    if len(user_requests) >= RATE_LIMIT_MAX_REQUESTS:
        return False

    # Add current request
    user_requests.append(now)
    return True


class CreateUserRequest(BaseModel):
    """Request model for user creation"""
    telegram_user_id: int
    username: Optional[str] = None
    polygon_address: Optional[str] = None
    polygon_private_key: Optional[str] = None
    solana_address: Optional[str] = None
    solana_private_key: Optional[str] = None
    stage: str = "onboarding"


class UserResponse(BaseModel):
    """User response model"""
    id: int
    telegram_user_id: int
    username: Optional[str]
    stage: str
    polygon_address: str
    solana_address: str
    polygon_private_key: Optional[str]
    solana_private_key: Optional[str]
    funded: bool
    auto_approval_completed: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post("/", response_model=UserResponse)
async def create_user(request: CreateUserRequest):
    """
    Create a new user with wallets

    Args:
        request: User creation request with wallet data

    Returns:
        Created user data
    """
    try:
        logger.info(f"Creating user {request.telegram_user_id} via API")

        # Generate wallets if not provided
        if not request.polygon_address or not request.solana_address:
            wallets = wallet_service.generate_user_wallets()
            request.polygon_address = wallets['polygon_address']
            request.polygon_private_key = wallets['polygon_private_key']
            request.solana_address = wallets['solana_address']
            request.solana_private_key = wallets['solana_private_key']

        # Create user via service
        user = await user_service.create_user(
            telegram_user_id=request.telegram_user_id,
            username=request.username,
            polygon_address=request.polygon_address,
            polygon_private_key=request.polygon_private_key,
            solana_address=request.solana_address,
            solana_private_key=request.solana_private_key,
            stage=request.stage
        )

        if not user:
            raise HTTPException(status_code=500, detail="Failed to create user")

        # Convert to response model
        return UserResponse(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            stage=user.stage,
            polygon_address=user.polygon_address,
            solana_address=user.solana_address,
            funded=user.funded,
            auto_approval_completed=user.auto_approval_completed,
            created_at=user.created_at.isoformat() if user.created_at else "",
            updated_at=user.updated_at.isoformat() if user.updated_at else ""
        )

    except Exception as e:
        logger.error(f"Error creating user {request.telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")


@router.get("/{telegram_user_id}", response_model=UserResponse)
async def get_user(telegram_user_id: int):
    """
    Get user by Telegram ID

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        User data or 404 if not found
    """
    try:
        logger.info(f"🔍 API endpoint: Getting user {telegram_user_id} from database")
        user = await user_service.get_by_telegram_id(telegram_user_id)

        if not user:
            logger.warning(f"⚠️ API endpoint: User {telegram_user_id} not found in database")
            logger.warning(f"   This may indicate:")
            logger.warning(f"   1. User doesn't exist in this database")
            logger.warning(f"   2. Database connection issue")
            logger.warning(f"   3. User was created in different database/service")
            raise HTTPException(status_code=404, detail="User not found")

        return UserResponse(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            stage=user.stage,
            polygon_address=user.polygon_address,
            solana_address=user.solana_address,
            polygon_private_key=user.polygon_private_key,
            solana_private_key=user.solana_private_key,
            funded=user.funded,
            auto_approval_completed=user.auto_approval_completed,
            created_at=user.created_at.isoformat() if user.created_at else "",
            updated_at=user.updated_at.isoformat() if user.updated_at else ""
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")


class PrivateKeyResponse(BaseModel):
    """Response model for private key"""
    private_key: str
    key_type: str
    retrieved_at: str


class ApiCredentialsResponse(BaseModel):
    """Response model for API credentials"""
    api_key: str
    api_secret: str
    api_passphrase: str


class UpdateUserRequest(BaseModel):
    """Request model for user updates"""
    stage: Optional[str] = None
    funded: Optional[bool] = None
    auto_approval_completed: Optional[bool] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    api_passphrase: Optional[str] = None


class UpdateUserResponse(BaseModel):
    """Response model for user updates (without private keys for security)"""
    id: int
    telegram_user_id: int
    username: Optional[str]
    stage: str
    polygon_address: str
    solana_address: str
    funded: bool
    auto_approval_completed: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.put("/{telegram_user_id}", response_model=UpdateUserResponse)
async def update_user(telegram_user_id: int, request: UpdateUserRequest):
    """
    Update user fields (stage, funded, auto_approval_completed)

    Args:
        telegram_user_id: Telegram user ID
        request: Update request with fields to update

    Returns:
        Updated user data
    """
    try:
        logger.info(f"Updating user {telegram_user_id} via API: {request.dict(exclude_none=True)}")

        # Build update dict (only include non-None fields)
        update_data = {}
        if request.stage is not None:
            update_data['stage'] = request.stage
        if request.funded is not None:
            update_data['funded'] = request.funded
        if request.auto_approval_completed is not None:
            update_data['auto_approval_completed'] = request.auto_approval_completed
        if request.api_key is not None:
            update_data['api_key'] = request.api_key
        if request.api_secret is not None:
            update_data['api_secret'] = request.api_secret
        if request.api_passphrase is not None:
            update_data['api_passphrase'] = request.api_passphrase

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Update user via service
        user = await user_service.update_user(telegram_user_id, **update_data)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Convert to response model (without private keys for security)
        # Private keys remain encrypted in DB and are never returned in PUT response
        return UpdateUserResponse(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            stage=user.stage,
            polygon_address=user.polygon_address,
            solana_address=user.solana_address,
            funded=user.funded,
            auto_approval_completed=user.auto_approval_completed,
            created_at=user.created_at.isoformat() if user.created_at else "",
            updated_at=user.updated_at.isoformat() if user.updated_at else ""
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating user: {str(e)}")


@router.get("/{telegram_user_id}/private-key/{key_type}", response_model=PrivateKeyResponse)
async def get_private_key(telegram_user_id: int, key_type: str):
    """
    Get decrypted private key for user (Polygon or Solana)

    SECURITY: This endpoint is rate-limited and audit-logged.
    Only returns keys for the requested Telegram user ID.

    Args:
        telegram_user_id: Telegram user ID
        key_type: "polygon" or "solana"

    Returns:
        Decrypted private key or 404/429 if error
    """
    # Validate key_type
    if key_type not in ["polygon", "solana"]:
        raise HTTPException(status_code=400, detail="key_type must be 'polygon' or 'solana'")

    # Rate limiting check
    if not _check_rate_limit(telegram_user_id):
        logger.warning(f"Rate limit exceeded for private key request: user={telegram_user_id}, type={key_type}")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {RATE_LIMIT_MAX_REQUESTS} requests per minute."
        )

    try:
        # Audit log - log all private key access attempts
        logger.info(f"🔑 [PRIVATE_KEY_ACCESS] user_id={telegram_user_id} key_type={key_type} timestamp={datetime.utcnow().isoformat()}")

        # Get user from database
        user = await user_service.get_by_telegram_id(telegram_user_id)

        if not user:
            logger.warning(f"Private key request for non-existent user: {telegram_user_id}")
            raise HTTPException(status_code=404, detail="User not found")

        # Get encrypted private key based on type
        encrypted_key = None
        if key_type == "polygon":
            encrypted_key = user.polygon_private_key
        elif key_type == "solana":
            encrypted_key = user.solana_private_key

        if not encrypted_key:
            logger.warning(f"Private key not found: user={telegram_user_id}, type={key_type}")
            raise HTTPException(status_code=404, detail=f"{key_type.capitalize()} private key not found")

        # Decrypt private key
        private_key = encryption_service.decrypt_private_key(encrypted_key)

        if not private_key:
            logger.error(f"Failed to decrypt private key: user={telegram_user_id}, type={key_type}")
            raise HTTPException(status_code=500, detail="Failed to decrypt private key")

        # Audit log success
        logger.info(f"✅ [PRIVATE_KEY_SUCCESS] user_id={telegram_user_id} key_type={key_type}")

        return PrivateKeyResponse(
            private_key=private_key,
            key_type=key_type,
            retrieved_at=datetime.utcnow().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting private key for user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving private key: {str(e)}")


@router.get("/{telegram_user_id}/api-credentials", response_model=ApiCredentialsResponse)
async def get_api_credentials(telegram_user_id: int):
    """
    Get Polymarket API credentials for user

    SECURITY: This endpoint does NOT cache credentials for security reasons.
    Returns decrypted API secret.

    Args:
        telegram_user_id: Telegram user ID

    Returns:
        API credentials (api_key, api_secret, api_passphrase) or 404 if not found
    """
    try:
        # Get user from database
        user = await user_service.get_by_telegram_id(telegram_user_id)

        if not user:
            logger.warning(f"API credentials request for non-existent user: {telegram_user_id}")
            raise HTTPException(status_code=404, detail="User not found")

        # Check if user has API credentials
        if not user.api_key or not user.api_secret or not user.api_passphrase:
            logger.warning(f"User {telegram_user_id} has no API credentials stored")
            raise HTTPException(status_code=404, detail="API credentials not found")

        # Decrypt API secret
        api_secret = encryption_service.decrypt_api_secret(user.api_secret)
        if not api_secret:
            logger.error(f"Failed to decrypt API secret for user {telegram_user_id}")
            raise HTTPException(status_code=500, detail="Failed to decrypt API secret")

        # Audit log success
        logger.info(f"✅ [API_CREDENTIALS_SUCCESS] user_id={telegram_user_id}")

        return ApiCredentialsResponse(
            api_key=user.api_key,
            api_secret=api_secret,
            api_passphrase=user.api_passphrase
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting API credentials for user {telegram_user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving API credentials: {str(e)}")
