"""
User Service - CRUD operations for users
Manages user data: stage, wallets, API credentials
"""
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import User
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class UserService:
    """
    User Service - CRUD operations for users
    - User lookup by telegram_id
    - Stage management (onboarding → ready)
    - User creation and updates
    """

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """
        Get user by internal database ID

        Args:
            user_id: Internal database user ID

        Returns:
            User object or None if not found
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(User).where(User.id == user_id)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"❌ Error getting user by ID {user_id}: {e}\n{error_details}")
            return None

    async def get_by_telegram_id(self, telegram_user_id: int) -> Optional[User]:
        """
        Get user by Telegram user ID

        Args:
            telegram_user_id: Telegram user ID

        Returns:
            User object or None if not found
        """
        try:
            logger.debug(f"🔍 Querying database for user {telegram_user_id}")
            async with get_db() as db:
                result = await db.execute(
                    select(User).where(User.telegram_user_id == telegram_user_id)
                )
                user = result.scalar_one_or_none()
                if user:
                    logger.debug(f"✅ User {telegram_user_id} found in database (id={user.id})")
                else:
                    logger.warning(f"⚠️ User {telegram_user_id} not found in database")
                return user
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"❌ Error getting user {telegram_user_id}: {e}\n{error_details}")
            return None

    async def user_exists(self, telegram_user_id: int) -> bool:
        """
        Check if user exists

        Args:
            telegram_user_id: Telegram user ID

        Returns:
            True if user exists, False otherwise
        """
        user = await self.get_by_telegram_id(telegram_user_id)
        return user is not None

    async def create_user(
        self,
        telegram_user_id: int,
        username: Optional[str] = None,
        polygon_address: str = None,
        polygon_private_key: str = None,
        solana_address: str = None,
        solana_private_key: str = None,
        stage: str = "onboarding"
    ) -> Optional[User]:
        """
        Create a new user

        Args:
            telegram_user_id: Telegram user ID
            username: Telegram username (optional)
            polygon_address: Polygon wallet address (encrypted)
            polygon_private_key: Polygon private key (encrypted)
            solana_address: Solana wallet address (encrypted)
            solana_private_key: Solana private key (encrypted)
            stage: User stage (default: "onboarding")

        Returns:
            Created User object or None if error
        """
        try:
            # Check if user already exists
            existing = await self.get_by_telegram_id(telegram_user_id)
            if existing:
                logger.info(f"ℹ️ User {telegram_user_id} already exists")
                return existing

            async with get_db() as db:
                user = User(
                    telegram_user_id=telegram_user_id,
                    username=username,
                    polygon_address=polygon_address or "",
                    polygon_private_key=polygon_private_key or "",
                    solana_address=solana_address or "",
                    solana_private_key=solana_private_key or "",
                    stage=stage,
                    funded=False,
                    auto_approval_completed=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    last_active_at=datetime.now(timezone.utc)
                )

                db.add(user)
                await db.commit()
                await db.refresh(user)

                logger.info(f"✅ Created user {telegram_user_id} at stage {stage}")
                return user

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"❌ Error creating user {telegram_user_id}: {e}\n{error_details}")

            # Re-raise to let caller handle it with more context
            raise

    async def update_user(
        self,
        telegram_user_id: int,
        **kwargs
    ) -> Optional[User]:
        """
        Update user fields

        Args:
            telegram_user_id: Telegram user ID
            **kwargs: Fields to update (stage, funded, auto_approval_completed, etc.)

        Returns:
            Updated User object or None if error
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(User).where(User.telegram_user_id == telegram_user_id)
                )
                user = result.scalar_one_or_none()

                if not user:
                    logger.warning(f"⚠️ User {telegram_user_id} not found for update")
                    return None

                # Update fields
                for key, value in kwargs.items():
                    if hasattr(user, key):
                        setattr(user, key, value)

                user.updated_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(user)

                logger.info(f"✅ Updated user {telegram_user_id}")
                return user

        except Exception as e:
            logger.error(f"❌ Error updating user {telegram_user_id}: {e}")
            return None

    async def update_stage(self, telegram_user_id: int, stage: str) -> bool:
        """
        Update user stage

        Args:
            telegram_user_id: Telegram user ID
            stage: New stage ("onboarding" or "ready")

        Returns:
            True if successful, False otherwise
        """
        user = await self.update_user(telegram_user_id, stage=stage)
        return user is not None

    async def update_last_active(self, telegram_user_id: int) -> None:
        """
        Update user's last active timestamp

        Args:
            telegram_user_id: Telegram user ID
        """
        await self.update_user(telegram_user_id, last_active_at=datetime.now(timezone.utc))

    async def set_funded(self, telegram_user_id: int, funded: bool = True) -> bool:
        """
        Set user funded status

        Args:
            telegram_user_id: Telegram user ID
            funded: Funded status

        Returns:
            True if successful, False otherwise
        """
        user = await self.update_user(telegram_user_id, funded=funded)
        return user is not None

    async def set_auto_approval_completed(self, telegram_user_id: int, completed: bool = True) -> bool:
        """
        Set auto-approval completed status

        Args:
            telegram_user_id: Telegram user ID
            completed: Auto-approval completed status

        Returns:
            True if successful, False otherwise
        """
        user = await self.update_user(telegram_user_id, auto_approval_completed=completed)
        return user is not None

    async def set_api_credentials(
        self,
        telegram_user_id: int,
        api_key: str,
        api_secret: str,
        api_passphrase: str
    ) -> bool:
        """
        Set API credentials for user

        Args:
            telegram_user_id: Telegram user ID
            api_key: CLOB API key
            api_secret: CLOB API secret (encrypted)
            api_passphrase: CLOB API passphrase

        Returns:
            True if successful, False otherwise
        """
        user = await self.update_user(
            telegram_user_id,
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase
        )
        return user is not None


# Global instance
user_service = UserService()
