"""
Watched Addresses Manager
Syncs watched addresses to Redis cache for fast lookups
"""
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import WatchedAddress
from core.services.cache_manager import CacheManager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class WatchedAddressesManager:
    """
    Manages watched addresses for indexer and copy trading
    - Syncs addresses to Redis cache (5min TTL)
    - Used by indexer-ts for filtering (optional)
    - Used by webhook receiver for fast validation
    """

    def __init__(self):
        """Initialize WatchedAddressesManager"""
        self.cache_manager = CacheManager()
        self.cache_key = "watched_addresses:cache:v1"
        self.cache_ttl = 300  # 5 minutes

    async def refresh_cache(self) -> Dict[str, Any]:
        """
        Refresh Redis cache with watched addresses

        Returns:
            Cache data dictionary
        """
        try:
            # Fetch all active watched addresses from DB
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.is_active == True)
                )
                addresses = list(result.scalars().all())

            # Group by type
            smart_wallets = []
            copy_leaders = []
            bot_users = []

            for addr in addresses:
                if addr.address_type == 'smart_wallet':  # Fix: Use 'smart_wallet' to match DB
                    smart_wallets.append(addr.address.lower())
                elif addr.address_type == 'copy_leader':
                    copy_leaders.append(addr.address.lower())
                elif addr.address_type == 'bot_user':
                    bot_users.append(addr.address.lower())

            # Build cache data
            cache_data = {
                'smart_traders': smart_wallets,  # Renamed for consistency
                'copy_leaders': copy_leaders,
                'bot_users': bot_users,
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'total_count': len(addresses),
                'smart_traders_count': len(smart_wallets),  # Renamed for consistency
                'copy_leaders_count': len(copy_leaders),
                'bot_users_count': len(bot_users),
            }

            # Store in Redis
            await self.cache_manager.set(
                self.cache_key,
                cache_data,
                data_type='user_profile',  # Use longer TTL
                ttl=self.cache_ttl
            )

            logger.info(
                f"✅ Refreshed watched addresses cache: "
                f"{len(smart_wallets)} smart wallets, "
                f"{len(copy_leaders)} copy leaders, "
                f"{len(bot_users)} bot users"
            )

            return cache_data

        except Exception as e:
            logger.error(f"❌ Error refreshing watched addresses cache: {e}")
            return {
                'smart_traders': [],
                'copy_leaders': [],
                'bot_users': [],
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'total_count': 0,
                'smart_traders_count': 0,
                'copy_leaders_count': 0,
                'bot_users_count': 0,
            }

    async def get_cached_addresses(self) -> Dict[str, Any]:
        """
        Get cached watched addresses from Redis

        Returns:
            Cache data dictionary or empty dict if not found
        """
        try:
            cached = await self.cache_manager.get(self.cache_key, data_type='user_profile')
            if cached:
                return cached

            # Cache miss - refresh
            return await self.refresh_cache()

        except Exception as e:
            logger.error(f"❌ Error getting cached addresses: {e}")
            return {
                'smart_traders': [],
                'copy_leaders': [],
                'bot_users': [],
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'total_count': 0,
                'smart_traders_count': 0,
                'copy_leaders_count': 0,
                'bot_users_count': 0,
            }

    async def is_watched_address(self, address: str) -> Dict[str, Any]:
        """
        Check if address is being watched

        Args:
            address: Wallet address to check

        Returns:
            Dict with 'is_watched' (bool) and 'address_type' (str or None)
        """
        try:
            address_lower = address.lower()
            cached = await self.get_cached_addresses()

            # Check smart wallets
            if address_lower in cached.get('smart_traders', []):
                return {
                    'is_watched': True,
                    'address_type': 'smart_wallet'  # Fix: Return correct type
                }

            # Check copy leaders
            if address_lower in cached.get('copy_leaders', []):
                return {
                    'is_watched': True,
                    'address_type': 'copy_leader'
                }

            # Check bot users
            if address_lower in cached.get('bot_users', []):
                return {
                    'is_watched': True,
                    'address_type': 'bot_user'
                }

            return {
                'is_watched': False,
                'address_type': None
            }

        except Exception as e:
            logger.error(f"❌ Error checking watched address: {e}")
            return {
                'is_watched': False,
                'address_type': None
            }

    async def ensure_watched_address(
        self,
        address: str,
        address_type: str,
        user_id: Optional[int] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        risk_score: Optional[float] = None
    ) -> Optional[WatchedAddress]:
        """
        Ensure watched address exists (create if not exists, update if exists)

        Args:
            address: Wallet address
            address_type: 'smart_wallet', 'copy_leader', or 'bot_user'
            user_id: User ID if bot_user, None otherwise
            name: Optional display name
            description: Optional description
            risk_score: Optional risk score

        Returns:
            WatchedAddress object or None if error
        """
        try:
            async with get_db() as db:
                normalized_addr = address.lower()
                # Check if exists
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.address == normalized_addr)
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
                    logger.debug(f"✅ Updated watched address: {normalized_addr[:10]}... ({address_type})")
                    return existing
                else:
                    # Create new
                    watched_addr = WatchedAddress(
                        address=normalized_addr,
                        blockchain='polygon',
                        address_type=address_type,
                        user_id=user_id,
                        name=name or f"{address_type} {normalized_addr[:10]}...",
                        description=description,
                        risk_score=risk_score,
                        is_active=True,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    db.add(watched_addr)
                    await db.commit()
                    await db.refresh(watched_addr)
                    logger.debug(f"✅ Created watched address: {normalized_addr[:10]}... ({address_type})")
                    return watched_addr

        except Exception as e:
            logger.error(f"❌ Error ensuring watched address: {e}")
            return None

    async def add_address(
        self,
        address: str,
        address_type: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """
        Add address to watch list (deprecated - use ensure_watched_address)

        Args:
            address: Wallet address
            address_type: 'smart_wallet' or 'copy_leader'
            name: Optional display name
            description: Optional description

        Returns:
            True if added successfully
        """
        result = await self.ensure_watched_address(
            address=address,
            address_type=address_type,
            name=name,
            description=description
        )
        if result:
            # Refresh cache
            await self.refresh_cache()
            logger.info(f"✅ Added watched address: {address[:10]}... ({address_type})")
            return True
        return False

    async def remove_address(self, address: str) -> bool:
        """
        Remove address from watch list (set is_active=False)

        Args:
            address: Wallet address

        Returns:
            True if removed successfully
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.address == address.lower())
                )
                watched_addr = result.scalar_one_or_none()

                if watched_addr:
                    watched_addr.is_active = False
                    watched_addr.updated_at = datetime.now(timezone.utc)
                    await db.commit()

                    # Refresh cache
                    await self.refresh_cache()

                    logger.info(f"✅ Removed watched address: {address[:10]}...")
                    return True

            return False

        except Exception as e:
            logger.error(f"❌ Error removing watched address: {e}")
            return False

    async def get_all_active_addresses(self) -> List[WatchedAddress]:
        """
        Get all active watched addresses (for indexer)

        Returns:
            List of WatchedAddress objects
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.is_active == True)
                )
                return list(result.scalars().all())
        except Exception as e:
            logger.error(f"❌ Error getting all active addresses: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics"""
        # Note: This is synchronous, so we can't await get_cached_addresses
        # Return basic stats only
        return {
            "cache_key": self.cache_key,
            "cache_ttl": self.cache_ttl,
        }


# Global instance
_watched_addresses_manager: Optional[WatchedAddressesManager] = None


def get_watched_addresses_manager() -> WatchedAddressesManager:
    """Get global WatchedAddressesManager instance"""
    global _watched_addresses_manager
    if _watched_addresses_manager is None:
        _watched_addresses_manager = WatchedAddressesManager()
    return _watched_addresses_manager
