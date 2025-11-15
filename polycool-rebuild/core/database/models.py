"""
SQLAlchemy models for Polycool database
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    BigInteger,
    String,
    Text,
    JSON,
    ForeignKey,
    Index,
    Numeric,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """User model"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255))

    # Onboarding stage
    stage = Column(String(50), nullable=False, default="onboarding")

    # Polygon Wallet (encrypted)
    polygon_address = Column(String(100), unique=True, nullable=False, index=True)
    polygon_private_key = Column(Text, nullable=False)  # AES-256-GCM encrypted

    # Solana Wallet (encrypted)
    solana_address = Column(String(100), unique=True, nullable=False, index=True)
    solana_private_key = Column(Text, nullable=False)  # AES-256-GCM encrypted

    # API Credentials (encrypted)
    api_key = Column(Text)
    api_secret = Column(Text)  # AES-256-GCM encrypted
    api_passphrase = Column(String(255))

    # Status flags
    funded = Column(Boolean, default=False)
    auto_approval_completed = Column(Boolean, default=False)

    # User stats (cached, updated periodically)
    usdc_balance = Column(Numeric(20, 2), default=0.0)  # Cached USDC balance
    total_profit = Column(Numeric(20, 2), default=0.0)  # Total realized P&L
    total_volume = Column(Numeric(20, 2), default=0.0)  # Total trading volume
    last_balance_sync = Column(DateTime)  # Last balance sync timestamp

    # Fees and Referral
    fees_enabled = Column(Boolean, default=True)  # Toggle fees on/off per user
    referral_code = Column(String(50), unique=True, nullable=True, index=True)  # Unique code for referral link

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    positions = relationship("Position", back_populates="user", cascade="all, delete-orphan")
    resolved_positions = relationship("ResolvedPosition", back_populates="user", cascade="all, delete-orphan")
    trade_fees = relationship("TradeFee", back_populates="user", cascade="all, delete-orphan")
    # Referral relationships will be set up after Referral class is defined (using backref)
    commissions = relationship("ReferralCommission", foreign_keys="ReferralCommission.referrer_user_id", back_populates="referrer")

    __table_args__ = (
        Index('idx_users_telegram_id', 'telegram_user_id'),
        Index('idx_users_polygon_address', 'polygon_address'),
        Index('idx_users_solana_address', 'solana_address'),
        Index('idx_users_stage', 'stage'),
    )


class Market(Base):
    """Market model - unified source of truth"""
    __tablename__ = "markets"

    id = Column(String(100), primary_key=True)  # market_id from Polymarket
    source = Column(String(20), nullable=False)  # 'poll', 'ws', 'api'

    # Market metadata
    title = Column(Text, nullable=False)
    description = Column(Text)
    category = Column(String(50), index=True)  # Normalized categories

    # Outcomes
    outcomes = Column(JSONB)  # ["YES", "NO"] or custom
    outcome_prices = Column(JSONB)  # [0.35, 0.65] or custom

    # Event grouping
    events = Column(JSONB)  # Event metadata
    is_event_market = Column(Boolean, default=False)
    parent_event_id = Column(String(100))

    # CORRIGÉ: Relations event->markets (from corrected poller)
    event_id = Column(String(100), index=True)  # Event ID from Gamma API
    event_slug = Column(String(255))  # Event slug for URLs
    event_title = Column(Text)  # Event title
    polymarket_url = Column(String(500))  # Polymarket URL for the market

    # Trading data
    volume = Column(Float, default=0.0)
    liquidity = Column(Float, default=0.0)
    last_trade_price = Column(Float)
    last_mid_price = Column(Float)

    # CLOB integration
    clob_token_ids = Column(JSONB)  # Token IDs for outcomes
    condition_id = Column(String(100), index=True)

    # Resolution
    is_resolved = Column(Boolean, default=False)
    resolved_outcome = Column(String(100))
    resolved_at = Column(DateTime)

    # Market lifecycle
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    positions = relationship("Position", back_populates="market", cascade="all, delete-orphan")
    resolved_positions = relationship("ResolvedPosition", back_populates="market", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_markets_category_active', 'category', 'is_active'),
        Index('idx_markets_volume_desc', 'volume'),
        Index('idx_markets_updated', 'updated_at'),
        Index('idx_markets_events_gin', 'events', postgresql_using='gin'),
        Index('idx_markets_clob_tokens_gin', 'clob_token_ids', postgresql_using='gin'),
        Index('idx_markets_parent_event', 'parent_event_id'),
        Index('idx_markets_event_id', 'event_id'),
    )


class Position(Base):
    """Position model - active and closed positions"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    market_id = Column(String(100), ForeignKey('markets.id', ondelete='CASCADE'), nullable=False, index=True)

    # Position details
    outcome = Column(String(100), nullable=False)  # "YES", "NO", etc.
    amount = Column(Float, nullable=False)  # Position size
    entry_price = Column(Float, nullable=False)  # Price when entered
    current_price = Column(Float)  # Current market price

    # P&L calculation
    pnl_amount = Column(Float, default=0.0)
    pnl_percentage = Column(Float, default=0.0)

    # Status
    status = Column(String(20), nullable=False, default="active")  # 'active', 'closed', 'liquidated'

    # TP/SL orders (optional)
    take_profit_price = Column(Float)
    stop_loss_price = Column(Float)
    take_profit_amount = Column(Float)  # Amount to sell at TP
    stop_loss_amount = Column(Float)    # Amount to sell at SL

    # Copy trading flag
    is_copy_trade = Column(Boolean, default=False)  # True if created via copy trading

    # Total cost (SHARES - misleading name but kept for compatibility)
    total_cost = Column(Float, nullable=True, comment="Number of shares received (for BUY) or sold (for SELL). Note: Despite the name 'total_cost', this stores SHARES, not USD cost.")

    # Position ID (clob_token_id) - for precise position lookup
    position_id = Column(String(100), nullable=True, index=True, comment="Token ID from blockchain (clob_token_id) - for precise position lookup. Enables direct market resolution via clob_token_ids in markets table.")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="positions")
    market = relationship("Market", back_populates="positions")

    __table_args__ = (
        Index('idx_positions_user_market', 'user_id', 'market_id'),
        Index('idx_positions_status', 'status'),
        Index('idx_positions_created', 'created_at'),
        Index('idx_positions_is_copy_trade', 'is_copy_trade'),
        # Partial index for active positions with position_id (most common query pattern)
        Index('idx_positions_user_position_id_active', 'user_id', 'position_id',
              postgresql_where=text("status = 'active'")),
    )


class ResolvedPosition(Base):
    """Resolved position model - tracks positions redeemable after market resolution"""
    __tablename__ = "resolved_positions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    market_id = Column(String(100), ForeignKey('markets.id', ondelete='CASCADE'), nullable=False, index=True)
    condition_id = Column(String(100), nullable=False, index=True)  # For matching with blockchain positions

    # Position details
    position_id = Column(String(100), nullable=True)  # clob_token_id from blockchain
    outcome = Column(String(100), nullable=False)  # 'YES' or 'NO'
    tokens_held = Column(Numeric(20, 6), nullable=False)  # Quantity of tokens
    total_cost = Column(Numeric(20, 6), nullable=False)  # Total entry cost
    avg_buy_price = Column(Numeric(20, 6), nullable=False)  # Average buy price

    # Market resolution
    market_title = Column(Text, nullable=False)  # Market title for display
    winning_outcome = Column(String(100), nullable=False)  # 'YES' or 'NO'
    is_winner = Column(Boolean, nullable=False)  # True if user's outcome matches winning outcome
    resolved_at = Column(DateTime, nullable=False)  # When market was resolved

    # Redemption value calculation
    gross_value = Column(Numeric(20, 6), nullable=False, default=0)  # Value before fees (tokens * 1.0)
    fee_amount = Column(Numeric(20, 6), nullable=False, default=0)  # Redemption fee (1%)
    net_value = Column(Numeric(20, 6), nullable=False, default=0)  # Value after fees
    pnl = Column(Numeric(20, 6), nullable=False, default=0)  # Profit/loss
    pnl_percentage = Column(Numeric(10, 2), nullable=False, default=0)  # P&L percentage

    # Redemption status
    status = Column(String(20), nullable=False, default='PENDING')  # 'PENDING', 'PROCESSING', 'REDEEMED', 'FAILED'
    notified = Column(Boolean, nullable=False, default=False)  # If notification was sent

    # Transaction details
    redemption_tx_hash = Column(String(255), nullable=True)
    redemption_block_number = Column(Integer, nullable=True)
    redemption_gas_used = Column(Integer, nullable=True)
    redemption_gas_price = Column(Numeric(20, 6), nullable=True)
    redeemed_at = Column(DateTime, nullable=True)

    # Error handling
    last_redemption_error = Column(Text, nullable=True)
    redemption_attempt_count = Column(Integer, nullable=False, default=0)
    processing_started_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="resolved_positions")
    market = relationship("Market", back_populates="resolved_positions")

    __table_args__ = (
        Index('idx_resolved_positions_user_status', 'user_id', 'status'),
        Index('idx_resolved_positions_condition_id', 'condition_id'),
        Index('idx_resolved_positions_status', 'status'),
        Index('idx_resolved_positions_market_id', 'market_id'),
        Index('idx_resolved_positions_user_winner', 'user_id', 'is_winner',
              postgresql_where=text("is_winner = true")),
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'market_id': self.market_id,
            'condition_id': self.condition_id,
            'position_id': self.position_id,
            'outcome': self.outcome,
            'tokens_held': float(self.tokens_held) if self.tokens_held else 0.0,
            'total_cost': float(self.total_cost) if self.total_cost else 0.0,
            'avg_buy_price': float(self.avg_buy_price) if self.avg_buy_price else 0.0,
            'market_title': self.market_title,
            'winning_outcome': self.winning_outcome,
            'is_winner': self.is_winner,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'gross_value': float(self.gross_value) if self.gross_value else 0.0,
            'fee_amount': float(self.fee_amount) if self.fee_amount else 0.0,
            'net_value': float(self.net_value) if self.net_value else 0.0,
            'pnl': float(self.pnl) if self.pnl else 0.0,
            'pnl_percentage': float(self.pnl_percentage) if self.pnl_percentage else 0.0,
            'status': self.status,
            'notified': self.notified,
            'redemption_tx_hash': self.redemption_tx_hash,
            'redemption_block_number': self.redemption_block_number,
            'redemption_gas_used': self.redemption_gas_used,
            'redemption_gas_price': float(self.redemption_gas_price) if self.redemption_gas_price else None,
            'redeemed_at': self.redeemed_at.isoformat() if self.redeemed_at else None,
            'last_redemption_error': self.last_redemption_error,
            'redemption_attempt_count': self.redemption_attempt_count,
            'processing_started_at': self.processing_started_at.isoformat() if self.processing_started_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WatchedAddress(Base):
    """Addresses being tracked for smart/copy trading"""
    __tablename__ = "watched_addresses"

    id = Column(Integer, primary_key=True)
    address = Column(String(100), unique=True, nullable=False, index=True)
    blockchain = Column(String(20), nullable=False)  # 'polygon', 'solana'

    # Address type
    address_type = Column(String(20), nullable=False)  # 'smart_trader', 'copy_leader', 'bot_user'

    # Reference to users table (if bot_user)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)

    # Metadata
    name = Column(String(255))  # Display name
    description = Column(Text)
    risk_score = Column(Float)  # 1-10 risk assessment

    # Tracking status
    is_active = Column(Boolean, default=True)
    last_tracked_at = Column(DateTime)

    # Statistics
    total_trades = Column(Integer, default=0)
    win_rate = Column(Float)
    total_volume = Column(Float, default=0.0)

    # Leader balance tracking (for copy trading proportional mode)
    usdc_balance = Column(Numeric(20, 2), nullable=True)  # Cached USDC balance (updated hourly)
    last_balance_sync = Column(DateTime, nullable=True)  # Last balance sync timestamp

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index('idx_watched_addresses_type_active', 'address_type', 'is_active'),
        Index('idx_watched_addresses_blockchain', 'blockchain'),
        Index('idx_watched_addresses_user_id', 'user_id'),
    )

    def update_balance(self, balance: float) -> None:
        """Update USDC balance and sync timestamp"""
        from datetime import datetime, timezone
        self.usdc_balance = balance
        self.last_balance_sync = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class Trade(Base):
    """Individual trades from watched addresses"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    watched_address_id = Column(Integer, ForeignKey('watched_addresses.id', ondelete='CASCADE'), nullable=False)

    # Trade details
    market_id = Column(String(100), nullable=False, index=True)
    outcome = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    amount_usdc = Column(Numeric(18, 6), nullable=True)  # Exact USDC amount from indexer (taking_amount)

    # Transaction details
    tx_hash = Column(String(100), unique=True, nullable=False)
    block_number = Column(Integer)
    timestamp = Column(DateTime, nullable=False)

    # Trade type
    trade_type = Column(String(20), nullable=False)  # 'buy', 'sell'

    # Position ID from blockchain (clob_token_id)
    position_id = Column(String(100), nullable=True, index=True)

    # Status
    is_processed = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_trades_watched_address', 'watched_address_id'),
        Index('idx_trades_market_timestamp', 'market_id', 'timestamp'),
        Index('idx_trades_tx_hash', 'tx_hash'),
        Index('idx_trades_timestamp', 'timestamp'),
    )


class CopyTradingAllocation(Base):
    """Copy trading allocations per user with budget management"""
    __tablename__ = "copy_trading_allocations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    leader_address_id = Column(Integer, ForeignKey('watched_addresses.id', ondelete='CASCADE'), nullable=False)

    # Allocation settings
    allocation_type = Column(String(20), nullable=False)  # 'percentage', 'fixed_amount'
    allocation_value = Column(Float, nullable=False)  # 50.0 for 50%, or fixed amount

    # Budget management (added from old system)
    allocation_percentage = Column(Numeric(5, 2), default=50.0)  # 5-100% of wallet
    total_wallet_balance = Column(Numeric(20, 2), default=0)  # Current USDC balance
    allocated_budget = Column(Numeric(20, 2), default=0)  # Calculated budget
    budget_remaining = Column(Numeric(20, 2), default=0)  # Available for copying
    last_wallet_sync = Column(DateTime)  # Last balance sync timestamp

    # Mode settings
    mode = Column(String(20), nullable=False)  # 'proportional', 'fixed_amount'
    sell_mode = Column(String(20), nullable=False, default="proportional")  # Always proportional for sells

    # Fixed amount for copy trading (when mode = 'fixed_amount')
    fixed_amount = Column(Numeric(20, 2), nullable=True)  # USD amount to copy per trade

    # Status
    is_active = Column(Boolean, default=True)

    # Statistics
    total_copied_trades = Column(Integer, default=0)
    total_invested = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", backref="copy_trading_allocations")
    leader_address = relationship("WatchedAddress", backref="copy_trading_allocations")

    __table_args__ = (
        Index('idx_copy_allocations_user_leader', 'user_id', 'leader_address_id'),
        Index('idx_copy_allocations_active', 'is_active'),
        Index('idx_copy_allocations_budget_sync', 'last_wallet_sync'),
    )

    def calculate_allocated_budget(self):
        """Calculate allocated budget from wallet balance and percentage"""
        if self.total_wallet_balance is None or self.allocation_percentage is None:
            return 0
        return float(self.total_wallet_balance) * (float(self.allocation_percentage) / 100.0)

    def update_budget_from_wallet(self, wallet_balance: float):
        """Update budget based on current wallet balance"""
        self.total_wallet_balance = wallet_balance
        self.allocated_budget = self.calculate_allocated_budget()
        self.budget_remaining = self.allocated_budget  # Always equal in new logic
        self.last_wallet_sync = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class CopyTradingHistory(Base):
    """Audit trail for copied trades execution"""
    __tablename__ = "copy_trading_history"

    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    leader_address_id = Column(Integer, ForeignKey('watched_addresses.id'), nullable=False)

    # Link to original leader trade (from indexer)
    leader_transaction_id = Column(String(255))
    leader_trade_tx_hash = Column(String(255))

    # Trade details
    market_id = Column(String(100), nullable=False)
    outcome = Column(String(10), nullable=False)
    transaction_type = Column(String(10), nullable=False)  # 'BUY' or 'SELL'

    # Copy mode and calculation
    copy_mode = Column(String(20), nullable=False)  # 'PROPORTIONAL' or 'FIXED'
    leader_trade_amount = Column(Numeric(20, 2), nullable=False)
    leader_wallet_balance = Column(Numeric(20, 2))
    calculated_copy_amount = Column(Numeric(20, 2), nullable=False)
    actual_copy_amount = Column(Numeric(20, 2))

    # Follower wallet state at time of copy
    follower_wallet_balance = Column(Numeric(20, 2))
    follower_allocated_budget = Column(Numeric(20, 2))

    # Execution status
    status = Column(String(20), nullable=False, default='PENDING')  # PENDING, SUCCESS, FAILED, INSUFFICIENT_BUDGET
    failure_reason = Column(String(255))

    # Fee tracking (for leader rewards)
    fee_from_copy = Column(Numeric(20, 2))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime)

    # Link to follower's executed trade (when successful)
    follower_transaction_id = Column(String(255))
    follower_trade_tx_hash = Column(String(255))

    # Relationships
    follower = relationship("User", backref="copy_trading_history")
    leader_address = relationship("WatchedAddress", backref="copy_trading_history")

    __table_args__ = (
        Index('idx_copy_history_follower_status', 'follower_id', 'status'),
        Index('idx_copy_history_leader_success', 'leader_address_id', 'status'),
        Index('idx_copy_history_market', 'market_id'),
        Index('idx_copy_history_created', 'created_at'),
        Index('idx_copy_history_executed', 'executed_at'),
    )

    def mark_success(self, actual_amount: float, executed_at: Optional[datetime] = None):
        """Mark trade as successfully executed"""
        self.status = 'SUCCESS'
        self.actual_copy_amount = actual_amount
        self.executed_at = executed_at or datetime.utcnow()

    def mark_failed(self, reason: str):
        """Mark trade as failed with reason"""
        self.status = 'FAILED'
        self.failure_reason = reason

    def mark_insufficient_budget(self):
        """Mark trade as skipped due to insufficient budget"""
        self.status = 'INSUFFICIENT_BUDGET'
        self.failure_reason = "Insufficient copy trading budget"


class LeaderPosition(Base):
    """Leader position tracking - cumulative token quantities per market/outcome"""
    __tablename__ = "leader_positions"

    id = Column(Integer, primary_key=True)
    watched_address_id = Column(Integer, ForeignKey('watched_addresses.id', ondelete='CASCADE'), nullable=False)
    market_id = Column(String(100), nullable=False)
    outcome = Column(String(10), nullable=False)  # 'YES' or 'NO'

    # Position ID from blockchain (clob_token_id)
    position_id = Column(String(100), nullable=True, index=True)

    # Token quantity tracking (cumulative: BUY adds, SELL subtracts)
    token_quantity = Column(Numeric(20, 6), nullable=False, default=0)

    # Last trade reference
    last_trade_tx_hash = Column(String(255))
    last_trade_timestamp = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    watched_address = relationship("WatchedAddress", backref="leader_positions")

    __table_args__ = (
        Index('idx_leader_positions_watched_market', 'watched_address_id', 'market_id'),
        Index('idx_leader_positions_market', 'market_id'),
        Index('idx_leader_positions_updated', 'updated_at'),
        # Unique constraint: one position per leader/market/outcome
        Index('unique_leader_market_outcome', 'watched_address_id', 'market_id', 'outcome', unique=True),
    )

    def add_tokens(self, amount: float, tx_hash: str, timestamp: datetime = None):
        """Add tokens (BUY)"""
        self.token_quantity = float(self.token_quantity or 0) + amount
        self.last_trade_tx_hash = tx_hash
        self.last_trade_timestamp = timestamp or datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def subtract_tokens(self, amount: float, tx_hash: str, timestamp: datetime = None):
        """Subtract tokens (SELL)"""
        current = float(self.token_quantity or 0)
        self.token_quantity = max(0, current - amount)  # Never go negative
        self.last_trade_tx_hash = tx_hash
        self.last_trade_timestamp = timestamp or datetime.utcnow()
        self.updated_at = datetime.utcnow()


class TradeFee(Base):
    """Trade fees tracking - 1% or $0.1 minimum per trade"""
    __tablename__ = "trade_fees"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    trade_id = Column(Integer, nullable=True)  # Reference to trade (can be NULL if external trade)
    market_id = Column(String(100), index=True)

    # Fee details
    trade_amount = Column(Numeric(20, 6), nullable=False)  # Trade amount in USDC
    fee_rate = Column(Numeric(5, 4), nullable=False, default=0.01)  # 1% = 0.01
    fee_amount = Column(Numeric(20, 6), nullable=False)  # Calculated fee (1% of trade)
    minimum_fee = Column(Numeric(20, 6), default=0.1)  # $0.1 minimum
    final_fee_amount = Column(Numeric(20, 6), nullable=False)  # Final fee (max between 1% and $0.1)

    # Discount
    has_referral_discount = Column(Boolean, default=False)
    discount_percentage = Column(Numeric(5, 2), default=0.0)  # 10% = 10.0
    discount_amount = Column(Numeric(20, 6), default=0.0)
    final_fee_after_discount = Column(Numeric(20, 6), nullable=False)  # Fee after discount

    # Trade type
    trade_type = Column(String(10), nullable=False)  # 'BUY' or 'SELL'

    # Status
    is_paid = Column(Boolean, default=False)
    paid_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="trade_fees")
    commissions = relationship("ReferralCommission", back_populates="trade_fee")

    __table_args__ = (
        Index('idx_trade_fees_user', 'user_id'),
        Index('idx_trade_fees_trade', 'trade_id'),
        Index('idx_trade_fees_created', 'created_at'),
        Index('idx_trade_fees_market', 'market_id'),
    )


class Referral(Base):
    """Referral relationships - 3-tier system"""
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True)
    referrer_user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    referred_user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    level = Column(Integer, nullable=False)  # 1, 2, or 3

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    referrer = relationship("User", foreign_keys=[referrer_user_id], backref="referrals_as_referrer")
    referred = relationship("User", foreign_keys=[referred_user_id], backref="referrals_as_referred")
    commissions = relationship("ReferralCommission", back_populates="referral")

    __table_args__ = (
        Index('idx_referrals_referrer', 'referrer_user_id'),
        Index('idx_referrals_referred', 'referred_user_id'),
        Index('idx_referrals_level', 'level'),
        Index('idx_referrals_referrer_level', 'referrer_user_id', 'level'),
        # Unique constraint: a user can only be referred once
        Index('unique_referred_user', 'referred_user_id', unique=True),
    )


class ReferralCommission(Base):
    """Referral commissions tracking - 25%/5%/3% of fees"""
    __tablename__ = "referral_commissions"

    id = Column(Integer, primary_key=True)
    referral_id = Column(Integer, ForeignKey('referrals.id', ondelete='CASCADE'), nullable=True)
    referrer_user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    referred_user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    level = Column(Integer, nullable=False)  # 1, 2, or 3

    # Commission details
    trade_fee_id = Column(Integer, ForeignKey('trade_fees.id', ondelete='CASCADE'), nullable=False)
    fee_amount = Column(Numeric(20, 6), nullable=False)  # Fee generated by the trade
    commission_rate = Column(Numeric(5, 2), nullable=False)  # 25.00, 5.00, 3.00
    commission_amount = Column(Numeric(20, 6), nullable=False)  # Calculated commission

    # Status
    status = Column(String(20), nullable=False, default='pending')  # 'pending', 'paid', 'claimed'
    paid_at = Column(DateTime)
    claim_tx_hash = Column(String(100))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    referral = relationship("Referral", back_populates="commissions")
    referrer = relationship("User", foreign_keys=[referrer_user_id], back_populates="commissions")
    trade_fee = relationship("TradeFee", back_populates="commissions")

    __table_args__ = (
        Index('idx_commissions_referrer', 'referrer_user_id', 'status'),
        Index('idx_commissions_referred', 'referred_user_id'),
        Index('idx_commissions_status', 'status'),
        Index('idx_commissions_trade_fee', 'trade_fee_id'),
        Index('idx_commissions_level', 'level'),
    )


class SmartTraderPosition(Base):
    """Smart trader positions for recommendation system"""
    __tablename__ = "smart_traders_positions"

    id = Column(Integer, primary_key=True)
    market_id = Column(String(100), nullable=False)
    smart_wallet_address = Column(String(100), nullable=False)
    outcome = Column(String(100), nullable=False)
    entry_price = Column(Numeric(8, 4), nullable=False)
    size = Column(Numeric(18, 8), nullable=False)
    amount_usdc = Column(Numeric(18, 6), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Position ID from blockchain (clob_token_id)
    position_id = Column(String(100), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_smart_positions_market', 'market_id'),
        Index('idx_smart_positions_wallet', 'smart_wallet_address'),
        Index('idx_smart_positions_timestamp', 'timestamp'),
        Index('idx_smart_positions_active', 'is_active', 'timestamp'),
        Index('idx_smart_positions_wallet_market', 'smart_wallet_address', 'market_id', 'outcome'),
        Index('idx_smart_positions_position_id', 'position_id'),
    )
