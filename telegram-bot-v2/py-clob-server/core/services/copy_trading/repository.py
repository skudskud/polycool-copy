"""
Copy Trading Repository
Data access layer using repository pattern
Pure DB operations, no business logic
"""

import logging
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import (
    CopyTradingSubscription,
    CopyTradingBudget,
    CopyTradingHistory,
    CopyTradingStats,
)
from .config import CopyMode, SubscriptionStatus, CopyTradeStatus
from .exceptions import (
    SubscriptionNotFoundError,
    MultipleSubscriptionsError,
)

logger = logging.getLogger(__name__)


class CopyTradingRepository:
    """Repository for all copy trading data access operations"""

    def __init__(self, db: Session):
        """
        Initialize repository with database session

        Args:
            db: SQLAlchemy Session instance
        """
        self.db = db

    # =========================================================================
    # HELPER METHODS - USER/LEADER LOOKUPS
    # =========================================================================

    def find_user_by_polygon_address(self, polygon_address: str) -> Optional['User']:
        """
        Find a user by their Polygon wallet address
        Used for Tier 1 address resolution in copy trading

        Args:
            polygon_address: Normalized Polygon address (lowercase)

        Returns:
            User object if found, None otherwise
        """
        try:
            from database import User
            return self.db.query(User).filter(
                User.polygon_address.ilike(polygon_address)
            ).first()
        except Exception as e:
            logger.error(f"Error finding user by address {polygon_address}: {e}")
            return None

    # =========================================================================
    # SUBSCRIPTION OPERATIONS
    # =========================================================================

    def get_subscription(self, follower_id: int, leader_id: int) -> Optional[CopyTradingSubscription]:
        """Get subscription between follower and leader"""
        return self.db.query(CopyTradingSubscription).filter(
            CopyTradingSubscription.follower_id == follower_id,
            CopyTradingSubscription.leader_id == leader_id,
        ).first()

    def get_active_subscription_for_follower(self, follower_id: int) -> Optional[CopyTradingSubscription]:
        """Get active subscription for a follower (can only have ONE)"""
        return self.db.query(CopyTradingSubscription).filter(
            CopyTradingSubscription.follower_id == follower_id,
            CopyTradingSubscription.status == SubscriptionStatus.ACTIVE.value,
        ).first()

    def get_all_active_copiers_for_leader(self, leader_id: int) -> List[CopyTradingSubscription]:
        """Get all active followers for a leader"""
        return self.db.query(CopyTradingSubscription).filter(
            CopyTradingSubscription.leader_id == leader_id,
            CopyTradingSubscription.status == SubscriptionStatus.ACTIVE.value,
        ).all()

    def create_subscription(
        self,
        follower_id: int,
        leader_id: int,
        copy_mode: str = CopyMode.PROPORTIONAL.value,
        fixed_amount: float = None,
    ) -> CopyTradingSubscription:
        """
        Create new subscription (follower starts following leader)

        Raises:
            MultipleSubscriptionsError: If follower already follows someone
        """
        # Check if follower already has an active subscription
        existing = self.get_active_subscription_for_follower(follower_id)
        if existing:
            raise MultipleSubscriptionsError(
                f"Follower {follower_id} already follows leader {existing.leader_id}"
            )

        subscription = CopyTradingSubscription(
            follower_id=follower_id,
            leader_id=leader_id,
            copy_mode=copy_mode,
            fixed_amount=fixed_amount,
            status=SubscriptionStatus.ACTIVE.value,
        )
        self.db.add(subscription)
        self.db.commit()
        logger.info(f"✅ Created subscription: {follower_id} follows {leader_id}")
        return subscription

    def cancel_subscription(self, follower_id: int, leader_id: int, commit: bool = True) -> bool:
        """Cancel subscription between follower and leader"""
        subscription = self.get_subscription(follower_id, leader_id)
        if not subscription:
            raise SubscriptionNotFoundError(f"No subscription found for {follower_id} -> {leader_id}")

        subscription.cancel()
        if commit:
            self.db.commit()
        logger.info(f"✅ Cancelled subscription: {follower_id} stopped following {leader_id}")
        return True

    def update_subscription_mode(
        self,
        follower_id: int,
        leader_id: int,
        copy_mode: str,
        fixed_amount: float = None,
    ) -> CopyTradingSubscription:
        """Update copy mode for subscription"""
        subscription = self.get_subscription(follower_id, leader_id)
        if not subscription:
            raise SubscriptionNotFoundError(f"No subscription found for {follower_id} -> {leader_id}")

        subscription.copy_mode = copy_mode
        subscription.fixed_amount = fixed_amount
        self.db.commit()
        logger.info(f"✅ Updated subscription mode: {follower_id} mode={copy_mode}")
        return subscription

    # =========================================================================
    # BUDGET OPERATIONS
    # =========================================================================

    def get_budget(self, user_id: int) -> Optional[CopyTradingBudget]:
        """Get budget allocation for user"""
        return self.db.query(CopyTradingBudget).filter(
            CopyTradingBudget.user_id == user_id
        ).first()

    def create_budget(
        self,
        user_id: int,
        allocation_percentage: float = 50.0,
        wallet_balance: float = 0,
    ) -> CopyTradingBudget:
        """Create budget allocation for user"""
        budget = CopyTradingBudget(
            user_id=user_id,
            allocation_percentage=allocation_percentage,
            total_wallet_balance=wallet_balance,
            allocated_budget=wallet_balance * (allocation_percentage / 100.0),
            budget_used=0,
            budget_remaining=wallet_balance * (allocation_percentage / 100.0),
        )
        self.db.add(budget)
        self.db.commit()
        logger.info(f"✅ Created budget for user {user_id}: {allocation_percentage}% allocated")
        return budget

    def update_budget_allocation_percentage(
        self,
        user_id: int,
        allocation_percentage: float,
    ) -> CopyTradingBudget:
        """Update allocation percentage for user"""
        budget = self.get_budget(user_id)
        if not budget:
            logger.warning(f"Budget not found for user {user_id}, creating default")
            budget = self.create_budget(user_id, allocation_percentage)
            return budget

        budget.allocation_percentage = allocation_percentage
        budget.update_allocated_budget(float(budget.total_wallet_balance))
        self.db.commit()
        logger.info(f"✅ Updated allocation for user {user_id}: {allocation_percentage}%")
        return budget

    def sync_wallet_balance(self, user_id: int, wallet_balance: float) -> CopyTradingBudget:
        """Sync wallet balance and recalculate allocated budget"""
        budget = self.get_budget(user_id)
        if not budget:
            logger.warning(f"Budget not found for user {user_id}, creating with new balance")
            budget = self.create_budget(user_id, 50.0, wallet_balance)
            return budget

        budget.update_allocated_budget(wallet_balance)
        self.db.commit()
        logger.debug(f"✅ Synced wallet for user {user_id}: balance={wallet_balance}")
        return budget

    def deduct_from_budget(self, user_id: int, amount: float):
        """Legacy method - budget is now calculated from current balance"""
        # ✅ NEW: No need to deduct from budget - it's calculated from current balance
        pass

    # =========================================================================
    # HISTORY OPERATIONS
    # =========================================================================

    def create_copy_history(
        self,
        follower_id: int,
        leader_id: int,
        leader_transaction_id: str,
        market_id: str,
        outcome: str,
        transaction_type: str,
        copy_mode: str,
        leader_trade_amount: float,
        leader_wallet_balance: float,
        calculated_copy_amount: float,
    ) -> CopyTradingHistory:
        """Create history record for a copy trade attempt"""
        # ✅ PREVENT DUPLICATES: Check if this combination already exists
        existing = self.db.query(CopyTradingHistory).filter(
            CopyTradingHistory.follower_id == follower_id,
            CopyTradingHistory.leader_transaction_id == leader_transaction_id
        ).first()

        if existing:
            logger.debug(f"⚠️ Skipping duplicate copy history: follower {follower_id} already processed transaction {leader_transaction_id}")
            return existing

        history = CopyTradingHistory(
            follower_id=follower_id,
            leader_id=leader_id,
            leader_transaction_id=leader_transaction_id,
            market_id=market_id,
            outcome=outcome,
            transaction_type=transaction_type,
            copy_mode=copy_mode,
            leader_trade_amount=leader_trade_amount,
            leader_wallet_balance=leader_wallet_balance,
            calculated_copy_amount=calculated_copy_amount,
            status=CopyTradeStatus.PENDING.value,
        )
        self.db.add(history)
        self.db.commit()
        return history

    def get_copy_history(self, history_id: int) -> Optional[CopyTradingHistory]:
        """Get specific history record"""
        return self.db.query(CopyTradingHistory).filter(
            CopyTradingHistory.id == history_id
        ).first()

    def list_copy_history_for_follower(
        self,
        follower_id: int,
        leader_id: int = None,
        status: str = None,
        limit: int = 50,
    ) -> List[CopyTradingHistory]:
        """List copy history for a follower, optionally filtered"""
        query = self.db.query(CopyTradingHistory).filter(
            CopyTradingHistory.follower_id == follower_id
        )

        if leader_id:
            query = query.filter(CopyTradingHistory.leader_id == leader_id)

        if status:
            query = query.filter(CopyTradingHistory.status == status)

        return query.order_by(CopyTradingHistory.created_at.desc()).limit(limit).all()

    def list_successful_copies_for_follower(
        self,
        follower_id: int,
        leader_id: int,
    ) -> List[CopyTradingHistory]:
        """List successful copies for a follower from a leader"""
        return self.db.query(CopyTradingHistory).filter(
            CopyTradingHistory.follower_id == follower_id,
            CopyTradingHistory.leader_id == leader_id,
            CopyTradingHistory.status == CopyTradeStatus.SUCCESS.value,
        ).order_by(CopyTradingHistory.executed_at.desc()).all()

    def update_history_success(
        self,
        history_id: int,
        follower_transaction_id: int,
        actual_amount: float,
        fee: float = None,
    ):
        """Mark history record as successfully executed"""
        history = self.get_copy_history(history_id)
        if not history:
            raise ValueError(f"History not found: {history_id}")

        history.mark_success(actual_amount)
        history.follower_transaction_id = follower_transaction_id
        history.fee_from_copy = fee
        self.db.commit()

    def update_history_failed(self, history_id: int, reason: str):
        """Mark history record as failed"""
        history = self.get_copy_history(history_id)
        if not history:
            raise ValueError(f"History not found: {history_id}")

        history.mark_failed(reason)
        self.db.commit()

    def update_history_insufficient_budget(self, history_id: int):
        """Mark history record as insufficient budget"""
        history = self.get_copy_history(history_id)
        if not history:
            raise ValueError(f"History not found: {history_id}")

        history.mark_insufficient_budget()
        self.db.commit()

    # =========================================================================
    # STATS OPERATIONS
    # =========================================================================

    def get_or_create_stats(self, leader_id: int) -> CopyTradingStats:
        """Get or create stats record for leader"""
        stats = self.db.query(CopyTradingStats).filter(
            CopyTradingStats.leader_id == leader_id
        ).first()

        if not stats:
            stats = CopyTradingStats(leader_id=leader_id)
            self.db.add(stats)
            self.db.commit()
            logger.info(f"✅ Created stats record for leader {leader_id}")

        return stats

    def update_leader_stats(self, leader_id: int):
        """Recalculate and update stats for leader"""
        stats = self.get_or_create_stats(leader_id)

        # Count active followers
        active_followers = self.db.query(func.count(CopyTradingSubscription.id)).filter(
            CopyTradingSubscription.leader_id == leader_id,
            CopyTradingSubscription.status == SubscriptionStatus.ACTIVE.value,
        ).scalar()
        stats.set_active_followers(active_followers or 0)

        # Count successful copies
        success_count = self.db.query(func.count(CopyTradingHistory.id)).filter(
            CopyTradingHistory.leader_id == leader_id,
            CopyTradingHistory.status == CopyTradeStatus.SUCCESS.value,
        ).scalar()
        stats.total_trades_copied = success_count or 0

        # Sum volume and fees
        volume_and_fees = self.db.query(
            func.sum(CopyTradingHistory.actual_copy_amount),
            func.sum(CopyTradingHistory.fee_from_copy),
        ).filter(
            CopyTradingHistory.leader_id == leader_id,
            CopyTradingHistory.status == CopyTradeStatus.SUCCESS.value,
        ).first()

        stats.total_volume_copied = volume_and_fees[0] or 0
        stats.total_fees_from_copies = volume_and_fees[1] or 0

        self.db.commit()
        logger.debug(f"✅ Updated stats for leader {leader_id}")
        return stats

    def get_leader_stats(self, leader_id: int) -> Optional[CopyTradingStats]:
        """Get stats for leader"""
        return self.db.query(CopyTradingStats).filter(
            CopyTradingStats.leader_id == leader_id
        ).first()

    def list_top_leaders_by_fees(self, limit: int = 10) -> List[CopyTradingStats]:
        """Get top leaders by fees earned from copies"""
        return self.db.query(CopyTradingStats).order_by(
            CopyTradingStats.total_fees_from_copies.desc()
        ).limit(limit).all()
