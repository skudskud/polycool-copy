"""
Copy Trading Service
Main orchestration layer for copy trading operations
Uses LeaderResolver to avoid polluting users table
"""
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import CopyTradingAllocation, WatchedAddress, User, CopyTradingHistory
from core.services.copy_trading.leader_resolver import LeaderResolver, LeaderInfo, get_leader_resolver
from core.services.copy_trading.budget_calculator import get_budget_calculator
from core.services.user.user_service import user_service
from core.services.user.user_helper import get_user_data
from core.services.clob.clob_service import get_clob_service
from core.services.api_client.api_client import get_api_client
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"


class CopyTradingService:
    """
    Copy Trading Service
    Manages copy trading subscriptions and execution
    """

    def __init__(self):
        """Initialize CopyTradingService"""
        self.leader_resolver = get_leader_resolver()
        self.clob_service = get_clob_service()
        self.budget_calculator = get_budget_calculator()

    async def subscribe_to_leader(
        self,
        follower_user_id: int,
        leader_address: str,
        allocation_type: str = 'percentage',
        allocation_value: float = 50.0,
        mode: str = 'proportional',
        fixed_amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Subscribe follower to a leader

        Args:
            follower_user_id: Telegram user ID of follower
            leader_address: Polygon address of leader
            allocation_type: 'percentage' or 'fixed_amount'
            allocation_value: Percentage (0-100) or fixed amount in USD
            mode: 'proportional' or 'fixed_amount'
            fixed_amount: Fixed USD amount for copy trading (optional)

        Returns:
            Dict with subscription details
        """
        try:
            # Resolve leader using LeaderResolver (3-tier system)
            leader_info = await self.leader_resolver.resolve_leader_by_address(leader_address)

            # Get user data (via API or DB)
            user_data = await get_user_data(follower_user_id)
            if not user_data:
                raise ValueError(f"User {follower_user_id} not found")

            internal_user_id = user_data.get('id')
            if not internal_user_id:
                raise ValueError(f"User {follower_user_id} missing internal ID")

            # Get current balance for budget initialization
            balance_info = await self.clob_service.get_balance(follower_user_id)
            current_balance = balance_info.get('balance', 0.0) if balance_info else 0.0

            # Check if already subscribed and update/create in same session
            async with get_db() as db:
                # Check for existing allocation in this session
                result = await db.execute(
                    select(CopyTradingAllocation).where(
                        and_(
                            CopyTradingAllocation.user_id == internal_user_id,
                            CopyTradingAllocation.is_active == True
                        )
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing allocation
                    existing.allocation_type = allocation_type
                    existing.allocation_value = allocation_value
                    existing.mode = mode
                    existing.fixed_amount = fixed_amount
                    existing.leader_address_id = leader_info.watched_address_id
                    existing.is_active = True
                    existing.updated_at = datetime.now(timezone.utc)

                    # Synchronize allocation_percentage with allocation_value (always percentage now)
                    existing.allocation_percentage = allocation_value
                    existing.update_budget_from_wallet(current_balance)

                    await db.commit()
                    await db.refresh(existing)

                    logger.info(
                        f"✅ Updated subscription: follower {follower_user_id} → leader {leader_address[:10]}..."
                    )
                else:
                    # Create new allocation
                    allocation = CopyTradingAllocation(
                            user_id=internal_user_id,
                            leader_address_id=leader_info.watched_address_id,
                            allocation_type=allocation_type,
                            allocation_value=allocation_value,
                            mode=mode,
                            fixed_amount=fixed_amount,
                            sell_mode='proportional',  # Always proportional for sells
                            is_active=True,
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc)
                        )

                    # Synchronize allocation_percentage with allocation_value (always percentage now)
                    allocation.allocation_percentage = allocation_value
                    allocation.update_budget_from_wallet(current_balance)

                    db.add(allocation)
                    await db.commit()
                    await db.refresh(allocation)

                    logger.info(
                        f"✅ Created subscription: follower {follower_user_id} → leader {leader_address[:10]}... "
                        f"(budget: ${allocation.allocated_budget:.2f} from {allocation_value}% of ${current_balance:.2f})"
                    )

                # Get leader details for response
                result = await db.execute(
                    select(WatchedAddress).where(WatchedAddress.id == leader_info.watched_address_id)
                )
                watched_addr = result.scalar_one_or_none()

            return {
                'success': True,
                'follower_id': follower_user_id,
                'leader_address': leader_address,
                'leader_name': watched_addr.name if watched_addr else None,
                'watched_address_id': leader_info.watched_address_id,
                'allocation_type': allocation_type,
                'allocation_value': allocation_value,
                'mode': mode
            }

        except Exception as e:
            logger.error(f"❌ Error subscribing to leader: {e}")
            raise

    async def unsubscribe_from_leader(self, follower_user_id: int) -> bool:
        """
        Unsubscribe follower from current leader

        Args:
            follower_user_id: Telegram user ID of follower

        Returns:
            True if successful
        """
        try:
            # Get user data (via API or DB)
            user_data = await get_user_data(follower_user_id)
            if not user_data:
                logger.warning(f"⚠️ User {follower_user_id} not found")
                return False

            internal_user_id = user_data.get('id')
            if not internal_user_id:
                logger.error(f"❌ User {follower_user_id} missing internal ID")
                return False

            async with get_db() as db:
                result = await db.execute(
                    select(CopyTradingAllocation).where(
                        and_(
                            CopyTradingAllocation.user_id == internal_user_id,
                            CopyTradingAllocation.is_active == True
                        )
                    )
                )
                allocation = result.scalar_one_or_none()

                if not allocation:
                    logger.warning(f"⚠️ No active allocation found for follower {follower_user_id}")
                    return False

                allocation.is_active = False
                allocation.updated_at = datetime.now(timezone.utc)
                await db.commit()

                logger.info(f"✅ Unsubscribed follower {follower_user_id}")
                return True

        except Exception as e:
            logger.error(f"❌ Error unsubscribing: {e}")
            return False

    async def get_active_allocation(self, follower_user_id: int) -> Optional[CopyTradingAllocation]:
        """
        Get active allocation for follower

        Args:
            follower_user_id: Telegram user ID

        Returns:
            CopyTradingAllocation or None
        """
        try:
            if SKIP_DB:
                # In SKIP_DB mode, get allocation via API
                api_client = get_api_client()
                allocation_data = await api_client.get_follower_allocation(follower_user_id)
                if not allocation_data:
                    return None

                # Convert API response to CopyTradingAllocation-like object
                # For SKIP_DB mode, we create a mock object with the data we need
                class MockAllocation:
                    def __init__(self, data):
                        self.id = data.get('allocation_id')
                        self.user_id = data.get('user_id')
                        self.allocation_type = data.get('allocation_type')
                        self.allocation_value = data.get('allocation_value')
                        self.allocation_percentage = data.get('allocation_percentage', data.get('allocation_value'))
                        self.mode = data.get('mode')
                        self.fixed_amount = data.get('fixed_amount')
                        self.total_wallet_balance = data.get('total_wallet_balance', 0)
                        self.allocated_budget = data.get('allocated_budget', 0)
                        self.budget_remaining = data.get('budget_remaining', 0)
                        self.is_active = True
                        # Stats attributes
                        self.total_copied_trades = data.get('total_copied_trades', 0)
                        self.total_invested = data.get('total_invested', 0.0)
                        self.total_pnl = data.get('total_pnl', 0.0)
                        # Parse last_wallet_sync from ISO string if present
                        last_sync_str = data.get('last_wallet_sync')
                        if last_sync_str:
                            from datetime import datetime, timezone
                            try:
                                # Parse ISO string and ensure timezone-aware
                                dt = datetime.fromisoformat(last_sync_str.replace('Z', '+00:00'))
                                # Ensure timezone-aware (if naive, assume UTC)
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                self.last_wallet_sync = dt
                            except (ValueError, AttributeError):
                                self.last_wallet_sync = None
                        else:
                            self.last_wallet_sync = None

                    def update_budget_from_wallet(self, wallet_balance: float):
                        """Mock method for SKIP_DB mode"""
                        self.total_wallet_balance = wallet_balance
                        if self.allocation_percentage:
                            self.allocated_budget = wallet_balance * (float(self.allocation_percentage) / 100.0)
                        self.budget_remaining = self.allocated_budget
                        # Update last_wallet_sync
                        from datetime import datetime, timezone
                        self.last_wallet_sync = datetime.now(timezone.utc)

                return MockAllocation(allocation_data)
            else:
                # Direct DB access
                # Get user data (via API or DB)
                user_data = await get_user_data(follower_user_id)
                if not user_data:
                    return None

                internal_user_id = user_data.get('id')
                if not internal_user_id:
                    logger.error(f"❌ User data missing internal ID for telegram_user_id {follower_user_id}")
                    return None

                async with get_db() as db:
                    result = await db.execute(
                        select(CopyTradingAllocation).where(
                            and_(
                                CopyTradingAllocation.user_id == internal_user_id,
                                CopyTradingAllocation.is_active == True
                            )
                        )
                    )
                    return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"❌ Error getting active allocation: {e}")
            return None

    async def get_leader_info_for_follower(self, follower_user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get leader info for follower

        Args:
            follower_user_id: Telegram user ID

        Returns:
            Dict with leader info or None
        """
        try:
            allocation = await self.get_active_allocation(follower_user_id)
            if not allocation:
                return None

            if SKIP_DB:
                # In SKIP_DB mode, get leader info via API
                api_client = get_api_client()
                allocation_data = await api_client.get_follower_allocation(follower_user_id)
                if not allocation_data:
                    return None

                # Use leader_resolver to get full leader info
                leader_address = allocation_data.get('leader_address')
                if not leader_address:
                    return None

                leader_info = await self.leader_resolver.resolve_leader_by_address(leader_address)
                if not leader_info:
                    return None

                # Try to get name from watched address via API
                watched_address_data = await api_client.get_watched_address(leader_info.watched_address_id)
                leader_name = None
                if watched_address_data:
                    leader_name = watched_address_data.get('name')

                # Fallback to truncated address if no name
                if not leader_name:
                    leader_name = f"External Trader {leader_address[:10]}..."

                return {
                    'address': leader_address,
                    'name': leader_name,
                    'type': leader_info.leader_type,
                    'watched_address_id': leader_info.watched_address_id,
                    'user_id': None  # Not available in SKIP_DB mode
                }
            else:
                # Direct DB access
                async with get_db() as db:
                    result = await db.execute(
                        select(WatchedAddress).where(WatchedAddress.id == allocation.leader_address_id)
                    )
                    watched_addr = result.scalar_one_or_none()

                    if not watched_addr:
                        return None

                    return {
                        'address': watched_addr.address,
                        'name': watched_addr.name,
                        'type': watched_addr.address_type,
                        'watched_address_id': watched_addr.id,
                        'user_id': watched_addr.user_id  # If bot_user
                    }

        except Exception as e:
            logger.error(f"❌ Error getting leader info: {e}")
            return None

    async def get_follower_stats(self, follower_user_id: int) -> Dict[str, Any]:
        """
        Get copy trading stats for follower

        Args:
            follower_user_id: Telegram user ID

        Returns:
            Dict with stats
        """
        try:
            allocation = await self.get_active_allocation(follower_user_id)
            if not allocation:
                return {
                    'trades_copied': 0,
                    'total_invested': 0.0,
                    'total_pnl': 0.0
                }

            return {
                'trades_copied': allocation.total_copied_trades or 0,
                'total_invested': float(allocation.total_invested or 0.0),
                'total_pnl': float(allocation.total_pnl or 0.0)
            }

        except Exception as e:
            logger.error(f"❌ Error getting follower stats: {e}")
            return {
                'trades_copied': 0,
                'total_invested': 0.0,
                'total_pnl': 0.0
            }

    async def refresh_allocation_budget(self, follower_user_id: int) -> bool:
        """
        Refresh allocation budget from current wallet balance
        Adapted from old system's budget refresh logic

        Args:
            follower_user_id: Telegram user ID

        Returns:
            True if budget was refreshed, False otherwise
        """
        try:
            allocation = await self.get_active_allocation(follower_user_id)
            if not allocation:
                return False

            # Check if refresh is needed (every 1 hour)
            if not self.budget_calculator.get_budget_refresh_needed(allocation.last_wallet_sync):
                return False

            # Get current USDC balance with fallback
            balance_info = await self.clob_service.get_balance(follower_user_id)
            if not balance_info:
                # Try fallback: get balance by address
                user_data = await get_user_data(follower_user_id)
                if user_data:
                    polygon_address = user_data.get('polygon_address')
                    if polygon_address:
                        balance_info = await self.clob_service.get_balance_by_address(polygon_address)

            current_balance = balance_info.get('balance', 0.0) if balance_info else 0.0

            if current_balance <= 0:
                logger.warning(f"⚠️ No USDC balance for user {follower_user_id}")
                return False

            # Update budget using allocation percentage
            allocation_percentage = float(allocation.allocation_percentage or allocation.allocation_value)
            allocation.update_budget_from_wallet(current_balance)

            # Save to database or API
            if SKIP_DB:
                # In SKIP_DB mode, update via API
                api_client = get_api_client()
                await api_client.update_allocation(
                    user_id=follower_user_id,
                    allocation_value=allocation.allocation_value,
                    allocation_type=allocation.allocation_type
                )
            else:
                # Direct DB access
                async with get_db() as db:
                    db.add(allocation)
                    await db.commit()

            logger.info(
                f"✅ Budget refreshed for user {follower_user_id}: "
                f"balance=${current_balance:.2f}, allocated=${allocation.allocated_budget:.2f} "
                f"({allocation_percentage:.1f}%)"
            )

            return True

        except Exception as e:
            logger.error(f"❌ Error refreshing allocation budget: {e}")
            return False

    async def get_budget_info(self, follower_user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get budget info for follower
        Always recalculates budget dynamically from current balance

        Args:
            follower_user_id: Telegram user ID

        Returns:
            Dict with budget info
        """
        try:
            allocation = await self.get_active_allocation(follower_user_id)
            if not allocation:
                return None

            # Get current balance for display with fallback
            balance_info = await self.clob_service.get_balance(follower_user_id)
            if not balance_info:
                # Try fallback: get balance by address
                user_data = await get_user_data(follower_user_id)
                if user_data:
                    polygon_address = user_data.get('polygon_address')
                    if polygon_address:
                        balance_info = await self.clob_service.get_balance_by_address(polygon_address)

            current_balance = balance_info.get('balance', 0.0) if balance_info else 0.0

            # Always recalculate budget dynamically from current balance
            allocation_percentage = float(allocation.allocation_percentage or allocation.allocation_value)
            allocated_budget = current_balance * (allocation_percentage / 100.0)
            budget_remaining = allocated_budget  # Budget remaining equals allocated (always recalculated)

            return {
                'allocation_type': allocation.allocation_type,
                'allocation_value': allocation.allocation_value,
                'allocation_percentage': allocation_percentage,
                'current_balance': current_balance,
                'allocated_budget': allocated_budget,
                'budget_remaining': budget_remaining,
                'last_wallet_sync': allocation.last_wallet_sync.isoformat() if allocation.last_wallet_sync else None,
            }

        except Exception as e:
            logger.error(f"❌ Error getting budget info: {e}")
            return None

    async def update_allocation_settings(
        self,
        follower_user_id: int,
        allocation_type: Optional[str] = None,
        allocation_value: Optional[float] = None,
        mode: Optional[str] = None,
        is_active: Optional[bool] = None,
        fixed_amount: Optional[float] = None
    ) -> bool:
        """
        Update allocation settings

        Args:
            follower_user_id: Telegram user ID
            allocation_type: New allocation type (optional)
            allocation_value: New allocation value (optional)
            mode: New mode (optional)
            is_active: New active status (optional, for pause/resume)
            fixed_amount: Fixed USD amount for copy trading (optional)

        Returns:
            True if successful
        """
        try:
            if SKIP_DB:
                # In SKIP_DB mode, update via API
                api_client = get_api_client()
                result = await api_client.update_allocation(
                    user_id=follower_user_id,
                    allocation_type=allocation_type,
                    allocation_value=allocation_value,
                    fixed_amount=fixed_amount,
                    mode=mode
                )
                if result:
                    logger.info(f"✅ Updated allocation settings for follower {follower_user_id}")
                    return True
                else:
                    return False
            else:
                # Direct DB access - get allocation within the same DB session
                async with get_db() as db:
                    # Get user data to map telegram_user_id to internal user_id
                    user_data = await get_user_data(follower_user_id)
                    if not user_data:
                        logger.error(f"❌ User {follower_user_id} not found")
                        return False

                    internal_user_id = user_data.get('id')
                    if not internal_user_id:
                        logger.error(f"❌ User {follower_user_id} missing internal ID")
                        return False

                    # Get allocation within this DB session
                    result = await db.execute(
                        select(CopyTradingAllocation).where(
                            and_(
                                CopyTradingAllocation.user_id == internal_user_id,
                                CopyTradingAllocation.is_active == True
                            )
                        )
                    )
                    allocation = result.scalar_one_or_none()

                    if not allocation:
                        logger.error(f"❌ No active allocation found for follower {follower_user_id}")
                        return False

                    if allocation_type:
                        allocation.allocation_type = allocation_type
                    if allocation_value is not None:
                        allocation.allocation_value = allocation_value
                        # Synchronize allocation_percentage with allocation_value when it's a percentage
                        if allocation_type == 'percentage' or (allocation_type is None and allocation.allocation_type == 'percentage'):
                            allocation.allocation_percentage = allocation_value
                    if mode:
                        allocation.mode = mode
                        logger.info(f"🔄 Updating mode to: {mode}")
                    if is_active is not None:
                        allocation.is_active = is_active
                    if fixed_amount is not None:
                        allocation.fixed_amount = fixed_amount

                    # Recalculate budget with current balance after any changes
                    balance_info = await self.clob_service.get_balance(follower_user_id)
                    if not balance_info:
                        user_data = await get_user_data(follower_user_id)
                        if user_data:
                            polygon_address = user_data.get('polygon_address')
                            if polygon_address:
                                balance_info = await self.clob_service.get_balance_by_address(polygon_address)

                    current_balance = balance_info.get('balance', 0.0) if balance_info else 0.0
                    if current_balance > 0:
                        allocation.update_budget_from_wallet(current_balance)

                    allocation.updated_at = datetime.now(timezone.utc)
                    await db.commit()

                    logger.info(f"✅ Updated allocation settings for follower {follower_user_id}")
                    return True

        except Exception as e:
            logger.error(f"❌ Error updating allocation settings: {e}")
            return False

    async def calculate_copy_amount(
        self,
        follower_user_id: int,
        leader_trade_amount_usdc: float,
        leader_wallet_balance: float = None,
        trade_type: str = "BUY"
    ) -> Dict[str, Any]:
        """
        Calculate copy trade amount using sophisticated budget logic
        Adapted from old system's CopyAmountCalculator

        Args:
            follower_user_id: Telegram user ID
            leader_trade_amount_usdc: Leader's trade amount in USDC
            leader_wallet_balance: Leader's wallet balance (for proportional mode)
            trade_type: "BUY" or "SELL"

        Returns:
            Dict with calculation results and metadata
        """
        try:
            allocation = await self.get_active_allocation(follower_user_id)
            if not allocation:
                return {
                    'copy_amount': 0.0,
                    'ignored': True,
                    'ignore_reason': 'No active allocation found'
                }

            # Refresh budget if needed
            await self.refresh_allocation_budget(follower_user_id)

            # Prepare allocation data for calculator
            follower_allocation = {
                'allocation_type': allocation.allocation_type,
                'allocation_value': allocation.allocation_value,
                'allocated_budget': float(allocation.allocated_budget or 0),
                'mode': allocation.mode,  # Include mode to determine fixed_amount vs proportional
            }

            # Calculate copy amount using budget calculator
            calculation_result = self.budget_calculator.calculate_copy_amount(
                leader_trade_amount=leader_trade_amount_usdc,
                leader_wallet_balance=leader_wallet_balance,
                follower_allocation=follower_allocation,
                trade_type=trade_type
            )

            # Check if we have sufficient budget
            if not calculation_result['ignored'] and calculation_result['actual_amount'] > float(allocation.budget_remaining or 0):
                calculation_result['ignored'] = True
                calculation_result['ignore_reason'] = (
                    f"Insufficient budget: need ${calculation_result['actual_amount']:.2f}, "
                    f"have ${allocation.budget_remaining:.2f}"
                )
                calculation_result['actual_amount'] = 0.0

            return {
                'copy_amount': calculation_result['actual_amount'],
                'calculated_amount': calculation_result['calculated_amount'],
                'copy_mode': calculation_result['copy_mode'],
                'explanation': calculation_result['explanation'],
                'ignored': calculation_result['ignored'],
                'ignore_reason': calculation_result.get('ignore_reason'),
                'allocation_budget': float(allocation.allocated_budget or 0),
                'budget_remaining': float(allocation.budget_remaining or 0),
            }

        except Exception as e:
            logger.error(f"❌ Error calculating copy amount: {e}")
            return {
                'copy_amount': 0.0,
                'ignored': True,
                'ignore_reason': f'Calculation error: {str(e)}'
            }


# Global instance
_copy_trading_service: Optional[CopyTradingService] = None


def get_copy_trading_service() -> CopyTradingService:
    """Get global CopyTradingService instance"""
    global _copy_trading_service
    if _copy_trading_service is None:
        _copy_trading_service = CopyTradingService()
    return _copy_trading_service
