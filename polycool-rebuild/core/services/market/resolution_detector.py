"""
Market Resolution Detector Service
Detects resolved markets by checking closed_positions from Polymarket API
Runs periodically (every 20 minutes) to update markets that are resolved
"""
import os
import asyncio
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta, timezone
from infrastructure.logging.logger import get_logger
from core.services.cache_manager import CacheManager

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client
else:
    from core.database.connection import get_db
    from core.database.models import User, Position, Market
    from sqlalchemy import select, and_


class MarketResolutionDetector:
    """
    Detects resolved markets by checking closed_positions from Polymarket API

    Strategy:
    1. Get users with active positions (recent activity < 30 days)
    2. For each user, call /closed-positions endpoint
    3. Extract conditionIds from closed positions with realizedPnl > 0
    4. Check if corresponding markets are marked as resolved in DB
    5. Update markets via API endpoint if not already resolved

    Optimizations:
    - Batch limit: 50 users per cycle (20 min interval)
    - Rate limiting: 0.2s delay between API calls
    - Cache: Redis cache to avoid checking same users too frequently
    - Only check users with recent positions (< 30 days)
    """

    def __init__(self, check_interval: int = 120):  # 20 minutes default
        self.check_interval = check_interval
        self.running = False
        self.detector_task: Optional[asyncio.Task] = None
        self.cache_manager = CacheManager()
        self.cache_ttl = 3600  # 1 hour cache for user checks
        self.max_users_per_cycle = 50
        self.api_delay = 0.2  # 0.2s delay between API calls

    async def start(self) -> None:
        """Start the detection background task"""
        if self.running:
            logger.warning("⚠️ Market Resolution Detector already running")
            return

        self.running = True
        self.detector_task = asyncio.create_task(self._detection_loop())
        logger.info(f"🚀 Market Resolution Detector started (check interval: {self.check_interval}s)")

    async def stop(self) -> None:
        """Stop the detection background task"""
        if not self.running:
            return

        self.running = False
        if self.detector_task and not self.detector_task.done():
            self.detector_task.cancel()
            try:
                await self.detector_task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 Market Resolution Detector stopped")

    async def _detection_loop(self) -> None:
        """Main detection loop"""
        while self.running:
            try:
                await self._check_resolved_markets()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in resolution detection loop: {e}", exc_info=True)
                # Wait before retrying on error
                await asyncio.sleep(60)

    async def _check_resolved_markets(self) -> None:
        """Single check cycle - detect and update resolved markets"""
        try:
            logger.info("🔍 Starting market resolution detection cycle...")
            start_time = datetime.now(timezone.utc)

            # Get users with active positions
            users = await self._get_users_with_active_positions()
            if not users:
                logger.debug("No users with active positions found")
                return

            # Limit to max_users_per_cycle
            users_to_check = users[:self.max_users_per_cycle]
            logger.info(f"📊 Checking {len(users_to_check)} users (out of {len(users)} total)")

            resolved_markets: Set[str] = set()
            checked_count = 0

            for user in users_to_check:
                try:
                    # Check cache to avoid checking same user too frequently
                    cache_key = f"resolution_check:user:{user['id']}"
                    cached = await self.cache_manager.get(cache_key)
                    if cached:
                        logger.debug(f"⏭️ Skipping user {user['id']} (cached)")
                        continue

                    # Get closed positions for this user
                    wallet_address = user.get('polygon_address')
                    if not wallet_address:
                        logger.debug(f"⚠️ User {user['id']} has no wallet address, skipping")
                        continue

                    closed_positions = await self._get_closed_positions(wallet_address)
                    if not closed_positions:
                        # Cache empty result to avoid checking again soon
                        await self.cache_manager.set(cache_key, "checked", ttl=self.cache_ttl)
                        continue

                    # Extract conditionIds from closed positions with positive PnL
                    for pos in closed_positions:
                        condition_id = pos.get('conditionId')
                        realized_pnl = pos.get('realizedPnl', 0)

                        if condition_id and realized_pnl > 0:
                            # This indicates a resolved market with winning outcome
                            resolved_markets.add(condition_id)
                            logger.debug(
                                f"💰 Found resolved market: condition_id={condition_id[:20]}..., "
                                f"realizedPnl=${realized_pnl:.2f}, user={user['id']}"
                            )

                    # Cache this user check
                    await self.cache_manager.set(cache_key, "checked", ttl=self.cache_ttl)
                    checked_count += 1

                    # Rate limiting: delay between API calls
                    await asyncio.sleep(self.api_delay)

                except Exception as e:
                    logger.error(f"❌ Error checking user {user.get('id', 'unknown')}: {e}")
                    continue

            if not resolved_markets:
                logger.info(f"✅ Detection cycle completed: {checked_count} users checked, 0 resolved markets found")
                return

            # Update markets via API
            updated_count = await self._update_resolved_markets(list(resolved_markets))

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                f"✅ Detection cycle completed in {duration:.2f}s: "
                f"{checked_count} users checked, {len(resolved_markets)} resolved markets found, "
                f"{updated_count} markets updated"
            )

        except Exception as e:
            logger.error(f"❌ Error in resolution detection cycle: {e}", exc_info=True)

    async def _get_users_with_active_positions(self) -> List[Dict]:
        """
        Get users with active positions (recent activity < 30 days)

        Returns:
            List of user dicts with id and polygon_address
        """
        try:
            if SKIP_DB:
                # Use API to get users (workaround: get user 1 for now)
                # In production, this would query all users with active positions
                # Note: We need an endpoint to get all users with active positions
                # For now, we'll check user 1 (main user) as a workaround
                api_client = get_api_client()
                # Try to get user by internal ID (if endpoint exists) or by telegram_id
                # For now, we'll use a workaround: check if we can get user 1
                try:
                    # Try to get user via internal ID endpoint (may not exist)
                    # Fallback: we'll need to implement a proper endpoint or use DB query
                    # For now, return empty list and let the system work with existing users
                    logger.debug("⚠️ SKIP_DB mode: User list query not fully implemented, using workaround")
                    # In production, this should query all users with active positions
                    return []
                except Exception as e:
                    logger.debug(f"⚠️ Could not get users list: {e}")
                    return []
            else:
                # Use DB to get users with active positions
                thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
                async with get_db() as db:
                    result = await db.execute(
                        select(User.id, User.polygon_address)
                        .join(Position, User.id == Position.user_id)
                        .where(
                            and_(
                                Position.status == "active",
                                Position.amount > 0,
                                Position.updated_at >= thirty_days_ago
                            )
                        )
                        .distinct()
                        .limit(100)  # Limit to 100 users max
                    )
                    users = []
                    for row in result.fetchall():
                        if row[1]:  # polygon_address not None
                            users.append({
                                'id': row[0],
                                'polygon_address': row[1]
                            })
                    return users
        except Exception as e:
            logger.error(f"❌ Error getting users with active positions: {e}")
            return []

    async def _get_closed_positions(self, wallet_address: str) -> Optional[List[Dict]]:
        """
        Get closed positions from Polymarket API

        Args:
            wallet_address: User's Polygon wallet address

        Returns:
            List of closed position dicts or None on error
        """
        try:
            if SKIP_DB:
                api_client = get_api_client()
                return await api_client.get_closed_positions_from_polymarket(wallet_address)
            else:
                # Direct API call (same as SKIP_DB mode)
                from core.services.position.blockchain_sync import get_closed_positions_from_blockchain
                return await get_closed_positions_from_blockchain(wallet_address)
        except Exception as e:
            logger.error(f"❌ Error getting closed positions for {wallet_address[:10]}...: {e}")
            return None

    async def _update_resolved_markets(self, condition_ids: List[str]) -> int:
        """
        Update markets to mark them as resolved via API

        Args:
            condition_ids: List of condition IDs (market identifiers)

        Returns:
            Number of markets updated
        """
        updated_count = 0

        for condition_id in condition_ids:
            try:
                # Get market_id from condition_id
                market_id = await self._get_market_id_from_condition_id(condition_id)
                if not market_id:
                    logger.debug(f"⚠️ Market not found for condition_id: {condition_id[:20]}...")
                    continue

                # Check if market is already marked as resolved
                is_already_resolved = await self._is_market_resolved(market_id)
                if is_already_resolved:
                    logger.debug(f"⏭️ Market {market_id} already marked as resolved, skipping")
                    continue

                # Update market via API
                if SKIP_DB:
                    api_client = get_api_client()
                    # Call API endpoint to update market
                    result = await api_client.update_market(
                        market_id=market_id,
                        is_resolved=True,
                        resolved_outcome="YES"  # Default, will be updated by resolutions_poller with correct outcome
                    )
                    if result:
                        updated_count += 1
                        logger.info(f"✅ Updated market {market_id} as resolved via API (condition_id: {condition_id[:20]}...)")
                    else:
                        logger.warning(f"⚠️ Failed to update market {market_id} via API")
                else:
                    # Direct DB update
                    async with get_db() as db:
                        from sqlalchemy import update
                        await db.execute(
                            update(Market)
                            .where(Market.id == market_id)
                            .values(
                                is_resolved=True,
                                resolved_at=datetime.now(timezone.utc)
                            )
                        )
                        await db.commit()
                        updated_count += 1
                        logger.info(f"✅ Updated market {market_id} as resolved in DB")

            except Exception as e:
                logger.error(f"❌ Error updating market for condition_id {condition_id[:20]}...: {e}")
                continue

        return updated_count

    async def _get_market_id_from_condition_id(self, condition_id: str) -> Optional[str]:
        """
        Get market_id from condition_id

        Args:
            condition_id: Condition ID from Polymarket

        Returns:
            Market ID or None if not found
        """
        try:
            if SKIP_DB:
                api_client = get_api_client()
                # Try to get market by condition_id via API
                # Note: This might need a new API endpoint
                # For now, assume condition_id == market_id (common case)
                return condition_id
            else:
                async with get_db() as db:
                    result = await db.execute(
                        select(Market.id)
                        .where(Market.condition_id == condition_id)
                        .limit(1)
                    )
                    market = result.scalar_one_or_none()
                    return market if market else condition_id  # Fallback to condition_id
        except Exception as e:
            logger.error(f"❌ Error getting market_id for condition_id {condition_id[:20]}...: {e}")
            return None

    async def _is_market_resolved(self, market_id: str) -> bool:
        """
        Check if market is already marked as resolved

        Args:
            market_id: Market ID

        Returns:
            True if market is resolved, False otherwise
        """
        try:
            if SKIP_DB:
                api_client = get_api_client()
                market = await api_client.get_market(market_id)
                return market.get('is_resolved', False) if market else False
            else:
                async with get_db() as db:
                    result = await db.execute(
                        select(Market.is_resolved)
                        .where(Market.id == market_id)
                        .limit(1)
                    )
                    is_resolved = result.scalar_one_or_none()
                    return bool(is_resolved) if is_resolved is not None else False
        except Exception as e:
            logger.error(f"❌ Error checking if market {market_id} is resolved: {e}")
            return False


# Singleton instance
_detector = None


def get_resolution_detector() -> MarketResolutionDetector:
    """Get singleton instance"""
    global _detector
    if _detector is None:
        _detector = MarketResolutionDetector()
    return _detector
