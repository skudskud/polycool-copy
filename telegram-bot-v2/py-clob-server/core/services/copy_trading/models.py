"""
Copy Trading Database Models (SQLAlchemy ORM)
Clean domain models with business logic methods
"""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, Index
from database import Base

# Import config
from .config import CopyMode, SubscriptionStatus, CopyTradeStatus


class CopyTradingSubscription(Base):
    """
    Model: copy_trading_subscriptions
    Tracks which user (follower) follows which leader and their copy trading configuration
    CONSTRAINT: Each user can only follow ONE leader at a time (unique follower_id)
    """
    __tablename__ = "copy_trading_subscriptions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign keys
    follower_id = Column(BigInteger, nullable=False, index=True)
    leader_id = Column(BigInteger, nullable=False, index=True)

    # Copy mode configuration
    copy_mode = Column(String(20), nullable=False, default=CopyMode.PROPORTIONAL.value)
    fixed_amount = Column(Numeric(20, 2), nullable=True)

    # Status
    status = Column(String(20), nullable=False, default=SubscriptionStatus.ACTIVE.value, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes for queries
    __table_args__ = (
        Index('idx_sub_follower_status', follower_id, status),
        Index('idx_sub_leader_status', leader_id, status),
    )

    def is_active(self) -> bool:
        """Check if subscription is active"""
        return self.status == SubscriptionStatus.ACTIVE.value

    def pause(self):
        """Pause this subscription"""
        self.status = SubscriptionStatus.PAUSED.value
        self.updated_at = datetime.utcnow()

    def activate(self):
        """Activate this subscription"""
        self.status = SubscriptionStatus.ACTIVE.value
        self.updated_at = datetime.utcnow()

    def cancel(self):
        """Cancel this subscription"""
        self.status = SubscriptionStatus.CANCELLED.value
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'follower_id': self.follower_id,
            'leader_id': self.leader_id,
            'copy_mode': self.copy_mode,
            'fixed_amount': float(self.fixed_amount) if self.fixed_amount else None,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CopyTradingBudget(Base):
    """
    Model: copy_trading_budgets
    Per-user budget allocation for copy trading
    Tracks max amount available for copying trades
    """
    __tablename__ = "copy_trading_budgets"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign key
    user_id = Column(BigInteger, nullable=False, unique=True, index=True)

    # Budget configuration
    allocation_percentage = Column(Numeric(5, 2), nullable=False, default=50.0)

    # Budget tracking
    total_wallet_balance = Column(Numeric(20, 2), nullable=False, default=0)
    allocated_budget = Column(Numeric(20, 2), nullable=False, default=0)
    budget_used = Column(Numeric(20, 2), nullable=False, default=0)
    budget_remaining = Column(Numeric(20, 2), nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_wallet_sync = Column(DateTime, nullable=True)

    def update_allocated_budget(self, wallet_balance: float):
        """
        Recalculate allocated budget based on CURRENT wallet balance

        FORMULA: available_budget = current_usdc_balance * (allocation_percentage / 100)

        Example:
        - User has $100 USDC.e
        - Allocation: 20%
        → Available for copy trading: $20

        Args:
            wallet_balance: Current USDC.e balance from blockchain
        """
        self.total_wallet_balance = wallet_balance
        allocation_pct = float(self.allocation_percentage) / 100.0
        self.allocated_budget = wallet_balance * allocation_pct

        # ✅ Budget remaining = allocated budget (always fresh from current balance)
        # ✅ IMPORTANT: Never allow negative budget remaining
        self.budget_remaining = max(0, self.allocated_budget)

        self.last_wallet_sync = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def use_budget(self, amount: float):
        """
        DEPRECATED: Legacy method - budget is now calculated from current balance

        Budget is NO LONGER tracked with used/remaining subtraction.
        Instead, it's recalculated fresh on every trade:

        available_budget = current_usdc_balance * allocation_percentage

        This method is kept for backwards compatibility but does nothing.
        """
        # ✅ No-op: Budget is calculated from current balance, not tracked
        pass

    def has_sufficient_budget(self, amount: float) -> bool:
        """Check if sufficient budget remains"""
        return float(self.budget_remaining) >= amount

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'allocation_percentage': float(self.allocation_percentage),
            'total_wallet_balance': float(self.total_wallet_balance),
            'allocated_budget': float(self.allocated_budget),
            'budget_used': float(self.budget_used),
            'budget_remaining': float(self.budget_remaining),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_wallet_sync': self.last_wallet_sync.isoformat() if self.last_wallet_sync else None,
        }


class CopyTradingHistory(Base):
    """
    Model: copy_trading_history
    Audit trail of all copied trades
    """
    __tablename__ = "copy_trading_history"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign keys
    follower_id = Column(BigInteger, nullable=False, index=True)
    leader_id = Column(BigInteger, nullable=False, index=True)
    leader_transaction_id = Column(String(255), nullable=True, index=True)
    follower_transaction_id = Column(String(255), nullable=True, index=True)

    # Trade details
    market_id = Column(String(100), nullable=False, index=True)
    outcome = Column(String(10), nullable=False)
    transaction_type = Column(String(10), nullable=False)

    # Amount details
    copy_mode = Column(String(20), nullable=False)
    leader_trade_amount = Column(Numeric(20, 2), nullable=False)
    leader_wallet_balance = Column(Numeric(20, 2), nullable=False)
    calculated_copy_amount = Column(Numeric(20, 2), nullable=False)
    actual_copy_amount = Column(Numeric(20, 2), nullable=True)

    # Execution status
    status = Column(String(20), nullable=False, default=CopyTradeStatus.PENDING.value, index=True)
    failure_reason = Column(String(255), nullable=True)

    # Fee tracking
    fee_from_copy = Column(Numeric(20, 2), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    executed_at = Column(DateTime, nullable=True, index=True)

    # Indexes
    __table_args__ = (
        Index('idx_hist_follower_status', follower_id, status),
        Index('idx_hist_leader_success', leader_id, status),
        Index('idx_hist_follower_leader_success', follower_id, leader_id, status),
    )

    def mark_success(self, actual_amount: float, executed_at: Optional[datetime] = None):
        """Mark trade as successfully executed"""
        self.status = CopyTradeStatus.SUCCESS.value
        self.actual_copy_amount = actual_amount
        self.executed_at = executed_at or datetime.utcnow()

    def mark_failed(self, reason: str):
        """Mark trade as failed with reason"""
        self.status = CopyTradeStatus.FAILED.value
        self.failure_reason = reason

    def mark_insufficient_budget(self):
        """Mark trade as skipped due to insufficient budget"""
        self.status = CopyTradeStatus.INSUFFICIENT_BUDGET.value
        self.failure_reason = "Insufficient copy trading budget"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'follower_id': self.follower_id,
            'leader_id': self.leader_id,
            'leader_transaction_id': self.leader_transaction_id,
            'follower_transaction_id': self.follower_transaction_id,
            'market_id': self.market_id,
            'outcome': self.outcome,
            'transaction_type': self.transaction_type,
            'copy_mode': self.copy_mode,
            'leader_trade_amount': float(self.leader_trade_amount),
            'leader_wallet_balance': float(self.leader_wallet_balance),
            'calculated_copy_amount': float(self.calculated_copy_amount),
            'actual_copy_amount': float(self.actual_copy_amount) if self.actual_copy_amount else None,
            'status': self.status,
            'failure_reason': self.failure_reason,
            'fee_from_copy': float(self.fee_from_copy) if self.fee_from_copy else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
        }


class CopyTradingStats(Base):
    """
    Model: copy_trading_stats
    Aggregated statistics for leaders (used for rewards and leaderboard)
    """
    __tablename__ = "copy_trading_stats"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign key
    leader_id = Column(BigInteger, nullable=False, unique=True, index=True)

    # Statistics
    total_active_followers = Column(Integer, nullable=False, default=0)
    total_trades_copied = Column(Integer, nullable=False, default=0)
    total_volume_copied = Column(Numeric(20, 2), nullable=False, default=0)
    total_fees_from_copies = Column(Numeric(20, 2), nullable=False, default=0)

    # PnL statistics
    total_pnl_followers = Column(Numeric(20, 2), nullable=True)
    avg_follower_pnl = Column(Numeric(20, 2), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_calculated = Column(DateTime, nullable=True)

    # Indexes for queries
    __table_args__ = (
        Index('idx_stats_fees', 'total_fees_from_copies'),
        Index('idx_stats_followers', 'total_active_followers'),
    )

    def add_successful_copy(self, volume: float, fee: float = 0):
        """Record a successful copy trade"""
        self.total_trades_copied = self.total_trades_copied + 1
        self.total_volume_copied = float(self.total_volume_copied) + volume
        self.total_fees_from_copies = float(self.total_fees_from_copies) + fee
        self.updated_at = datetime.utcnow()

    def set_active_followers(self, count: int):
        """Update active follower count"""
        self.total_active_followers = count
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'leader_id': self.leader_id,
            'total_active_followers': self.total_active_followers,
            'total_trades_copied': self.total_trades_copied,
            'total_volume_copied': float(self.total_volume_copied),
            'total_fees_from_copies': float(self.total_fees_from_copies),
            'total_pnl_followers': float(self.total_pnl_followers) if self.total_pnl_followers else None,
            'avg_follower_pnl': float(self.avg_follower_pnl) if self.avg_follower_pnl else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_calculated': self.last_calculated.isoformat() if self.last_calculated else None,
        }
