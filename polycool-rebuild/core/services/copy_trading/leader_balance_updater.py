"""
Leader Balance Updater Service
Updates USDC balances for copy trading leaders via blockchain API
Runs hourly to keep balances fresh for proportional copy trading calculations
"""
import asyncio
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import WatchedAddress
from core.services.balance.balance_service import BalanceService
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class LeaderBalanceUpdater:
    """
    Service to update USDC balances for copy trading leaders
    Fetches balances from blockchain API and stores in DB for fast access
    """

    def __init__(self):
        self.balance_service = BalanceService()
        self._update_stats = {
            'total_leaders': 0,
            'successful_updates': 0,
            'failed_updates': 0,
            'last_run': None,
        }

    async def update_all_leader_balances(self) -> dict:
        """
        Update USDC balances for all active copy leaders

        Returns:
            Dict with update statistics
        """
        logger.info("🔄 Starting leader balance update cycle...")
        start_time = datetime.now(timezone.utc)

        try:
            # Get all active copy leaders
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(
                        and_(
                            WatchedAddress.address_type == 'copy_leader',
                            WatchedAddress.is_active == True
                        )
                    )
                )
                leaders = list(result.scalars().all())

            self._update_stats['total_leaders'] = len(leaders)
            self._update_stats['successful_updates'] = 0
            self._update_stats['failed_updates'] = 0

            if not leaders:
                logger.info("⏭️ No active copy leaders found")
                self._update_stats['last_run'] = start_time
                return self._update_stats.copy()

            logger.info(f"📊 Found {len(leaders)} active copy leaders to update")

            # Update balances in parallel (with rate limiting)
            # Process in batches to avoid overwhelming the blockchain API
            batch_size = 10
            for i in range(0, len(leaders), batch_size):
                batch = leaders[i:i + batch_size]
                tasks = [self._update_leader_balance(leader) for leader in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Count successes and failures
                for result in results:
                    if isinstance(result, Exception):
                        self._update_stats['failed_updates'] += 1
                        logger.error(f"❌ Error updating leader balance: {result}")
                    elif result:
                        self._update_stats['successful_updates'] += 1
                    else:
                        self._update_stats['failed_updates'] += 1

                # Small delay between batches to avoid rate limiting
                if i + batch_size < len(leaders):
                    await asyncio.sleep(1)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            self._update_stats['last_run'] = start_time

            logger.info(
                f"✅ Balance update cycle completed: "
                f"{self._update_stats['successful_updates']}/{self._update_stats['total_leaders']} successful, "
                f"{self._update_stats['failed_updates']} failed "
                f"(took {duration:.2f}s)"
            )

            return self._update_stats.copy()

        except Exception as e:
            logger.error(f"❌ Error in balance update cycle: {e}", exc_info=True)
            self._update_stats['last_run'] = start_time
            return self._update_stats.copy()

    async def _update_leader_balance(self, leader: WatchedAddress) -> bool:
        """
        Update balance for a single leader

        Args:
            leader: WatchedAddress object

        Returns:
            True if successful, False otherwise
        """
        try:
            # Skip if not a polygon address
            if leader.blockchain != 'polygon':
                logger.debug(f"⏭️ Skipping {leader.address[:10]}... (not polygon)")
                return False

            # Fetch balance from blockchain
            balance = await self.balance_service.get_usdc_balance(leader.address)

            if balance is None:
                logger.warning(
                    f"⚠️ Could not fetch balance for leader {leader.address[:10]}... "
                    f"(watched_address_id={leader.id})"
                )
                return False

            # Update in DB - reload leader in new session to avoid session issues
            async with get_db() as db:
                # Reload leader from DB in current session
                result = await db.execute(
                    select(WatchedAddress).where(WatchedAddress.id == leader.id)
                )
                leader_db = result.scalar_one_or_none()

                if not leader_db:
                    logger.warning(
                        f"⚠️ Leader not found in DB: watched_address_id={leader.id}"
                    )
                    return False

                # Update balance
                leader_db.update_balance(balance)
                await db.commit()

            logger.debug(
                f"✅ Updated balance for {leader.address[:10]}...: "
                f"${balance:.2f} (watched_address_id={leader.id})"
            )

            return True

        except Exception as e:
            logger.error(
                f"❌ Error updating balance for leader {leader.address[:10]}... "
                f"(watched_address_id={leader.id}): {e}",
                exc_info=True
            )
            return False

    async def get_leader_balance(
        self,
        watched_address_id: int,
        use_cache: bool = True,
        max_age_hours: int = 2
    ) -> Optional[float]:
        """
        Get leader balance from DB (cached) or API (fallback)

        Args:
            watched_address_id: WatchedAddress ID
            use_cache: If True, use cached balance if fresh enough
            max_age_hours: Maximum age of cached balance in hours (default 2h)

        Returns:
            USDC balance or None if not found/error
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.id == watched_address_id)
                )
                leader = result.scalar_one_or_none()

            if not leader:
                logger.warning(f"⚠️ Leader not found: watched_address_id={watched_address_id}")
                return None

            # Check if cached balance is fresh enough
            if use_cache and leader.usdc_balance is not None and leader.last_balance_sync:
                age = datetime.now(timezone.utc) - leader.last_balance_sync.replace(tzinfo=timezone.utc)
                if age < timedelta(hours=max_age_hours):
                    logger.debug(
                        f"✅ Using cached balance for {leader.address[:10]}...: "
                        f"${leader.usdc_balance:.2f} (age: {age.total_seconds()/3600:.1f}h)"
                    )
                    return float(leader.usdc_balance)

            # Fallback: fetch from API
            logger.info(
                f"🔄 Fetching fresh balance from API for {leader.address[:10]}... "
                f"(cache too old or missing)"
            )
            balance = await self.balance_service.get_usdc_balance(leader.address)

            if balance is not None:
                # Update cache - reload leader in new session
                async with get_db() as db:
                    result = await db.execute(
                        select(WatchedAddress).where(WatchedAddress.id == watched_address_id)
                    )
                    leader_db = result.scalar_one_or_none()

                    if leader_db:
                        leader_db.update_balance(balance)
                        await db.commit()

            return balance

        except Exception as e:
            logger.error(f"❌ Error getting leader balance: {e}", exc_info=True)
            return None

    def get_stats(self) -> dict:
        """Get update statistics"""
        return self._update_stats.copy()


# Global instance
_leader_balance_updater: Optional[LeaderBalanceUpdater] = None


def get_leader_balance_updater() -> LeaderBalanceUpdater:
    """Get global LeaderBalanceUpdater instance"""
    global _leader_balance_updater
    if _leader_balance_updater is None:
        _leader_balance_updater = LeaderBalanceUpdater()
    return _leader_balance_updater
