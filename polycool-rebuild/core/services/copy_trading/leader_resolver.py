"""
Leader Resolver Service
Resolves Polygon addresses to leader information using 3-tier system:
1. Bot users (from users table)
2. Smart traders (from watched_addresses with type='smart_trader')
3. Copy leaders (from watched_addresses with type='copy_leader' or create new)

Avoids polluting users table with external traders.
Supports SKIP_DB mode for bot service.
"""
import os
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import User, WatchedAddress
from core.services.user.user_service import user_service
from core.services.api_client.api_client import get_api_client
from data_ingestion.indexer.watched_addresses.manager import get_watched_addresses_manager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LeaderInfo:
    """
    Leader information result
    """
    leader_type: str  # 'bot_user' | 'smart_trader' | 'copy_leader'
    leader_id: Optional[int]  # user_id if bot_user, None otherwise
    watched_address_id: int  # Always present - ID in watched_addresses table
    address: str  # Normalized address (lowercase)

    def __str__(self) -> str:
        return f"LeaderInfo(type={self.leader_type}, leader_id={self.leader_id}, watched_id={self.watched_address_id})"


class LeaderResolver:
    """
    Resolves Polygon addresses to leader information
    Uses 3-tier resolution system to avoid polluting users table
    Supports SKIP_DB mode for bot service
    """

    def __init__(self):
        """Initialize LeaderResolver"""
        self.watched_manager = get_watched_addresses_manager()

        # Check if bot has DB access
        self.skip_db = os.getenv("SKIP_DB", "true").lower() == "true"
        self.api_client = get_api_client() if self.skip_db else None

    async def resolve_leader_by_address(self, polygon_address: str) -> LeaderInfo:
        """
        Resolve a Polygon address to leader information

        Uses 3-tier resolution:
        1. Bot User (from users table) → creates watched_address with user_id
        2. Smart Trader (from watched_addresses with type='smart_trader')
        3. Copy Leader (from watched_addresses with type='copy_leader' or create new)

        Args:
            polygon_address: Polygon wallet address (case-insensitive)

        Returns:
            LeaderInfo with leader_type, leader_id, watched_address_id

        Raises:
            ValueError: If address format is invalid
        """
        if not polygon_address or not polygon_address.startswith('0x'):
            raise ValueError(f"Invalid Polygon address format: {polygon_address}")

        normalized_addr = polygon_address.lower().strip()

        # Use API client if SKIP_DB=true, otherwise use DB directly
        if self.skip_db and self.api_client:
            logger.debug(f"🔄 Using API client to resolve leader (SKIP_DB=true)")
            result = await self.api_client.resolve_leader_by_address(normalized_addr)
            if result:
                return LeaderInfo(
                    leader_type=result['leader_type'],
                    leader_id=result.get('leader_id'),
                    watched_address_id=result['watched_address_id'],
                    address=result['address']
                )
            else:
                raise ValueError(f"Failed to resolve leader via API: {normalized_addr}")
        else:
            logger.debug(f"🔄 Using DB directly to resolve leader (SKIP_DB=false)")
            return await self._resolve_leader_db(normalized_addr)

    async def _resolve_leader_db(self, normalized_addr: str) -> LeaderInfo:
        """
        Resolve leader using database directly (when SKIP_DB=false)
        """
        # Tier 1: Check if it's a bot user
        user = await self._find_user_by_polygon_address(normalized_addr)
        if user:
            logger.info(f"✅ Resolved {normalized_addr[:10]}... to bot user {user.id}")
            # Ensure watched_address exists for this bot user
            watched_addr = await self._ensure_watched_address(
                address=normalized_addr,
                address_type='bot_user',
                user_id=user.id,
                name=f"Bot User {user.telegram_user_id}"
            )
            return LeaderInfo(
                leader_type='bot_user',
                leader_id=user.id,
                watched_address_id=watched_addr.id,
                address=normalized_addr
            )

        # Tier 2: Check if it's a smart trader
        watched_addr = await self._find_watched_address(normalized_addr, 'smart_trader')
        if watched_addr:
            logger.info(f"✅ Resolved {normalized_addr[:10]}... to smart trader (watched_id={watched_addr.id})")
            return LeaderInfo(
                leader_type='smart_trader',
                leader_id=None,
                watched_address_id=watched_addr.id,
                address=normalized_addr
            )

        # Tier 3: Check if it's already a copy leader
        watched_addr = await self._find_watched_address(normalized_addr, 'copy_leader')
        if watched_addr:
            logger.info(f"✅ Resolved {normalized_addr[:10]}... to copy leader (watched_id={watched_addr.id})")
            return LeaderInfo(
                leader_type='copy_leader',
                leader_id=None,
                watched_address_id=watched_addr.id,
                address=normalized_addr
            )

        # Not found in any tier - create as copy_leader (external trader)
        logger.info(f"🆕 Creating new copy leader for {normalized_addr[:10]}...")
        watched_addr = await self._ensure_watched_address(
            address=normalized_addr,
            address_type='copy_leader',
            user_id=None,
            name=f"External Trader {normalized_addr[:10]}..."
        )
        return LeaderInfo(
            leader_type='copy_leader',
            leader_id=None,
            watched_address_id=watched_addr.id,
            address=normalized_addr
        )

    async def _find_user_by_polygon_address(self, polygon_address: str) -> Optional[User]:
        """
        Find user by Polygon address

        Args:
            polygon_address: Normalized Polygon address

        Returns:
            User object or None if not found
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(User).where(User.polygon_address == polygon_address)
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"❌ Error finding user by address {polygon_address[:10]}...: {e}")
            return None

    async def _find_watched_address(
        self,
        address: str,
        address_type: str
    ) -> Optional[WatchedAddress]:
        """
        Find watched address by address and type

        Args:
            address: Normalized address
            address_type: 'smart_trader', 'copy_leader', or 'bot_user'

        Returns:
            WatchedAddress or None if not found
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress).where(
                        and_(
                            WatchedAddress.address == address,
                            WatchedAddress.address_type == address_type,
                            WatchedAddress.is_active == True
                        )
                    )
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"❌ Error finding watched address {address[:10]}... ({address_type}): {e}")
            return None

    async def _ensure_watched_address(
        self,
        address: str,
        address_type: str,
        user_id: Optional[int] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        risk_score: Optional[float] = None
    ) -> WatchedAddress:
        """
        Ensure watched address exists (create if not exists, update if exists)

        Args:
            address: Normalized address
            address_type: 'smart_trader', 'copy_leader', or 'bot_user'
            user_id: User ID if bot_user, None otherwise
            name: Display name (optional)
            description: Description (optional)
            risk_score: Risk score (optional)

        Returns:
            WatchedAddress object (created or updated)
        """
        try:
            async with get_db() as db:
                # Check if exists
                result = await db.execute(
                    select(WatchedAddress).where(WatchedAddress.address == address)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing
                    existing.address_type = address_type
                    existing.user_id = user_id
                    existing.is_active = True
                    if name:
                        existing.name = name
                    if description:
                        existing.description = description
                    if risk_score is not None:
                        existing.risk_score = risk_score
                    existing.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    await db.refresh(existing)
                    logger.debug(f"✅ Updated watched address {address[:10]}... ({address_type})")
                    return existing
                else:
                    # Create new
                    watched_addr = WatchedAddress(
                        address=address,
                        blockchain='polygon',
                        address_type=address_type,
                        user_id=user_id,
                        name=name or f"{address_type} {address[:10]}...",
                        description=description,
                        risk_score=risk_score,
                        is_active=True,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    db.add(watched_addr)
                    await db.commit()
                    await db.refresh(watched_addr)
                    logger.debug(f"✅ Created watched address {address[:10]}... ({address_type})")
                    return watched_addr

        except Exception as e:
            logger.error(f"❌ Error ensuring watched address {address[:10]}...: {e}")
            raise

    async def get_leader_info(self, watched_address_id: int) -> Optional[LeaderInfo]:
        """
        Get leader info from watched_address_id

        Args:
            watched_address_id: ID in watched_addresses table

        Returns:
            LeaderInfo or None if not found
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress).where(WatchedAddress.id == watched_address_id)
                )
                watched_addr = result.scalar_one_or_none()

                if not watched_addr:
                    return None

                leader_id = watched_addr.user_id if watched_addr.address_type == 'bot_user' else None

                return LeaderInfo(
                    leader_type=watched_addr.address_type,
                    leader_id=leader_id,
                    watched_address_id=watched_addr.id,
                    address=watched_addr.address
                )
        except Exception as e:
            logger.error(f"❌ Error getting leader info for watched_id {watched_address_id}: {e}")
            return None


# Global instance
_leader_resolver: Optional[LeaderResolver] = None


def get_leader_resolver() -> LeaderResolver:
    """Get global LeaderResolver instance"""
    global _leader_resolver
    if _leader_resolver is None:
        _leader_resolver = LeaderResolver()
    return _leader_resolver
