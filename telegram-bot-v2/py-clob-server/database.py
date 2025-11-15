"""
PostgreSQL Database Models and Connection V2
Clean schema with unified users table
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Text, DateTime, Boolean, Float, JSON, Index, Numeric, ForeignKey, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import JSONB
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Database URL from environment (.env or Railway)
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    # Fallback for local development
    DATABASE_URL = "postgresql://localhost:5432/trading_bot"
    logger.warning("⚠️ Using local database URL - DATABASE_URL not found in environment")

# Create SQLAlchemy engine with Supabase-optimized settings
engine = create_engine(
    DATABASE_URL,
    pool_size=5,  # Reduced for Supabase pooler limits
    max_overflow=10,  # Reduced for Supabase pooler limits
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=300,  # Recycle connections every 5 minutes (Supabase closes idle connections)
    connect_args={
        'connect_timeout': 10  # 10 second connection timeout
    },
    echo=False  # Set to True for SQL logging
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """
    Unified User Model with Encrypted Private Keys

    SECURITY:
    - Private keys encrypted at rest using AES-256-GCM
    - Decryption happens transparently via @property getters
    - Encryption happens transparently via @property setters
    - Stored columns: polygon_private_key, solana_private_key, api_secret (encrypted in DB)

    Primary Key: telegram_user_id (source of truth)
    """
    __tablename__ = "users"

    # Primary key: Telegram user ID (immutable, source of truth)
    telegram_user_id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String(100), nullable=True)

    # Polygon wallet - ENCRYPTED at rest in database
    polygon_address = Column(String(42), nullable=False)
    _polygon_private_key_encrypted = Column("polygon_private_key", Text, nullable=False)  # Encrypted in DB

    # Solana wallet (for bridge operations) - ENCRYPTED at rest in database
    solana_address = Column(String(44), nullable=True)
    _solana_private_key_encrypted = Column("solana_private_key", Text, nullable=True)  # Encrypted in DB

    # API credentials (Polymarket API) - ENCRYPTED at rest in database
    api_key = Column(String(100), nullable=True)
    _api_secret_encrypted = Column("api_secret", Text, nullable=True)  # Encrypted in DB
    api_passphrase = Column(String(100), nullable=True)

    # Funding status
    funded = Column(Boolean, default=False)

    # Contract approvals (3 separate Polygon contracts)
    usdc_approved = Column(Boolean, default=False)  # USDC contract approval
    pol_approved = Column(Boolean, default=False)   # POL contract approval
    polymarket_approved = Column(Boolean, default=False)  # Polymarket CTF Exchange approval

    # Auto-approval tracking
    auto_approval_completed = Column(Boolean, default=False)
    auto_approval_last_check = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, nullable=True)

    # For /restart command
    wallet_generation_count = Column(Integer, default=1)
    last_restart = Column(DateTime, nullable=True)

    # Relationship to transactions only (positions removed)
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")

    # =========================================================================
    # TRANSPARENT ENCRYPTION/DECRYPTION PROPERTIES
    # =========================================================================
    # These properties provide transparent encryption/decryption
    # Code using user.polygon_private_key automatically gets decrypted data
    # Setting user.polygon_private_key automatically encrypts before storing

    @property
    def polygon_private_key(self) -> Optional[str]:
        """Get Polygon private key (decrypted transparently)"""
        if not self._polygon_private_key_encrypted:
            return None

        try:
            from core.services.encryption_service import encryption_service
            return encryption_service.decrypt(self._polygon_private_key_encrypted, context="polygon_key_read")
        except Exception as e:
            logger.error(f"Failed to decrypt Polygon key for user {self.telegram_user_id}: {e}")
            raise ValueError("Cannot decrypt Polygon private key - possible data corruption")

    @polygon_private_key.setter
    def polygon_private_key(self, value: Optional[str]):
        """Set Polygon private key (encrypted transparently)"""
        if value is None:
            self._polygon_private_key_encrypted = None
        else:
            try:
                from core.services.encryption_service import encryption_service
                self._polygon_private_key_encrypted = encryption_service.encrypt(value, context="polygon_key_write")
            except Exception as e:
                logger.error(f"Failed to encrypt Polygon key for user {self.telegram_user_id}: {e}")
                raise ValueError("Cannot encrypt Polygon private key")

    @property
    def solana_private_key(self) -> Optional[str]:
        """Get Solana private key (decrypted transparently)"""
        if not self._solana_private_key_encrypted:
            return None

        try:
            from core.services.encryption_service import encryption_service
            return encryption_service.decrypt(self._solana_private_key_encrypted, context="solana_key_read")
        except Exception as e:
            logger.error(f"Failed to decrypt Solana key for user {self.telegram_user_id}: {e}")
            raise ValueError("Cannot decrypt Solana private key - possible data corruption")

    @solana_private_key.setter
    def solana_private_key(self, value: Optional[str]):
        """Set Solana private key (encrypted transparently)"""
        if value is None:
            self._solana_private_key_encrypted = None
        else:
            try:
                from core.services.encryption_service import encryption_service
                self._solana_private_key_encrypted = encryption_service.encrypt(value, context="solana_key_write")
            except Exception as e:
                logger.error(f"Failed to encrypt Solana key for user {self.telegram_user_id}: {e}")
                raise ValueError("Cannot encrypt Solana private key")

    @property
    def api_secret(self) -> Optional[str]:
        """Get API secret (decrypted transparently)"""
        if not self._api_secret_encrypted:
            return None

        try:
            from core.services.encryption_service import encryption_service
            return encryption_service.decrypt(self._api_secret_encrypted, context="api_secret_read")
        except Exception as e:
            logger.error(f"Failed to decrypt API secret for user {self.telegram_user_id}: {e}")
            raise ValueError("Cannot decrypt API secret - possible data corruption")

    @api_secret.setter
    def api_secret(self, value: Optional[str]):
        """Set API secret (encrypted transparently)"""
        if value is None:
            self._api_secret_encrypted = None
        else:
            try:
                from core.services.encryption_service import encryption_service
                self._api_secret_encrypted = encryption_service.encrypt(value, context="api_secret_write")
            except Exception as e:
                logger.error(f"Failed to encrypt API secret for user {self.telegram_user_id}: {e}")
                raise ValueError("Cannot encrypt API secret")

    def to_dict(self) -> Dict:
        """Convert to dictionary format for compatibility with existing code"""
        return {
            'telegram_user_id': self.telegram_user_id,
            'username': self.username,
            'polygon_address': self.polygon_address,
            'polygon_private_key': self.polygon_private_key,
            'solana_address': self.solana_address,
            'solana_private_key': self.solana_private_key,
            'api_key': self.api_key,
            'api_secret': self.api_secret,
            'api_passphrase': self.api_passphrase,
            'funded': self.funded,
            'usdc_approved': self.usdc_approved,
            'pol_approved': self.pol_approved,
            'polymarket_approved': self.polymarket_approved,
            'auto_approval_completed': self.auto_approval_completed,
            'auto_approval_last_check': self.auto_approval_last_check.timestamp() if self.auto_approval_last_check else None,
            'created_at': self.created_at.timestamp() if self.created_at else None,
            'last_active': self.last_active.timestamp() if self.last_active else None,
            'wallet_generation_count': self.wallet_generation_count,
            'last_restart': self.last_restart.timestamp() if self.last_restart else None
        }

    def is_ready_to_trade(self) -> bool:
        """Check if user has completed all setup steps"""
        return (
            self.funded and
            self.usdc_approved and
            self.pol_approved and
            self.polymarket_approved and
            self.api_key is not None
        )


class Transaction(Base):
    """
    ENTERPRISE-GRADE TRANSACTION LOG
    Records every buy/sell trade for complete audit trail and P&L calculation
    """
    __tablename__ = "transactions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # User reference
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True)

    # Transaction type
    transaction_type = Column(String(10), nullable=False, index=True)  # 'BUY', 'SELL'

    # Market and position details
    market_id = Column(String(100), nullable=False, index=True)
    outcome = Column(String(10), nullable=False)  # 'yes', 'no'

    # Trade details
    tokens = Column(Float, nullable=False)  # Number of tokens traded
    price_per_token = Column(Float, nullable=False)  # Price per token in USD
    total_amount = Column(Float, nullable=False)  # Total USD amount

    # Polymarket references
    token_id = Column(String(100), nullable=False)  # ERC-1155 token ID
    order_id = Column(String(100), nullable=True)  # Polymarket order ID
    transaction_hash = Column(String(66), nullable=True)  # Blockchain tx hash

    # Market data snapshot (for historical reference)
    market_data = Column(JSONB, nullable=True)  # Full market data at time of trade

    # Timestamps
    executed_at = Column(DateTime, nullable=False)  # When trade was executed
    created_at = Column(DateTime, default=datetime.utcnow)  # When record was created

    # Relationship to user
    user = relationship("User", back_populates="transactions")

    # Indexes for fast queries
    __table_args__ = (
        Index('idx_user_market_outcome', 'user_id', 'market_id', 'outcome'),
        Index('idx_user_executed_at', 'user_id', 'executed_at'),
        Index('idx_market_executed_at', 'market_id', 'executed_at'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'transaction_type': self.transaction_type,
            'market_id': self.market_id,
            'outcome': self.outcome,
            'tokens': self.tokens,
            'price_per_token': self.price_per_token,
            'total_amount': self.total_amount,
            'token_id': self.token_id,
            'order_id': self.order_id,
            'transaction_hash': self.transaction_hash,
            'market_data': self.market_data,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# POSITION TABLE REMOVED - Using transaction-based architecture + direct blockchain API


class Fee(Base):
    """
    Trading Fees Table
    Records all fees collected from trades (BUY and SELL)
    Linked to transactions for audit trail
    """
    __tablename__ = "fees"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # User reference
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True)

    # Link to transaction
    transaction_id = Column(Integer, ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True, index=True)

    # Fee details
    trade_amount = Column(Numeric(20, 2), nullable=False)  # Amount of trade
    fee_percentage = Column(Numeric(5, 2), nullable=False)  # Fee percentage
    fee_amount = Column(Numeric(20, 2), nullable=False)  # Fee amount in USD
    minimum_fee_applied = Column(Boolean, default=False)  # Whether minimum fee was applied

    # Commission tracking (for referral system)
    total_commission_paid = Column(Numeric(20, 2), default=0)
    level1_commission = Column(Numeric(20, 2), default=0)
    level2_commission = Column(Numeric(20, 2), default=0)
    level3_commission = Column(Numeric(20, 2), default=0)

    # Blockchain references
    fee_transaction_hash = Column(Text, nullable=True)  # TX hash of fee payment
    trade_transaction_hash = Column(Text, nullable=True)  # TX hash of original trade

    # Status tracking
    status = Column(String(20), default='pending', index=True)  # 'pending', 'collected', 'failed'

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    collected_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Indexes for fast queries
    __table_args__ = (
        Index('idx_fees_user', 'user_id', 'created_at'),
        Index('idx_fees_transaction', 'transaction_id'),
        Index('idx_fees_status', 'status'),
        Index('idx_fees_created', 'created_at'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'transaction_id': self.transaction_id,
            'trade_amount': float(self.trade_amount) if self.trade_amount else 0,
            'fee_percentage': float(self.fee_percentage) if self.fee_percentage else 0,
            'fee_amount': float(self.fee_amount) if self.fee_amount else 0,
            'minimum_fee_applied': self.minimum_fee_applied,
            'total_commission_paid': float(self.total_commission_paid) if self.total_commission_paid else 0,
            'level1_commission': float(self.level1_commission) if self.level1_commission else 0,
            'level2_commission': float(self.level2_commission) if self.level2_commission else 0,
            'level3_commission': float(self.level3_commission) if self.level3_commission else 0,
            'fee_transaction_hash': self.fee_transaction_hash,
            'trade_transaction_hash': self.trade_transaction_hash,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'collected_at': self.collected_at.isoformat() if self.collected_at else None,
            'failed_at': self.failed_at.isoformat() if self.failed_at else None,
            'error_message': self.error_message,
        }


class TPSLOrder(Base):
    """
    Take Profit & Stop Loss Orders
    Monitors positions and automatically sells when price targets are hit
    """
    __tablename__ = "tpsl_orders"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # User reference
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True)

    # Position reference
    market_id = Column(String(100), nullable=False, index=True)
    outcome = Column(String(10), nullable=False)  # 'yes', 'no'
    token_id = Column(String(100), nullable=False)

    # TP/SL Configuration
    take_profit_price = Column(Numeric(10, 4), nullable=True)  # NULL if not set
    stop_loss_price = Column(Numeric(10, 4), nullable=True)    # NULL if not set

    # Position tracking
    monitored_tokens = Column(Numeric(20, 4), nullable=False)  # Tokens being monitored
    entry_price = Column(Numeric(10, 4), nullable=False)       # Position entry price

    # Status tracking
    status = Column(String(20), default='active', nullable=False)  # 'active', 'triggered', 'cancelled'
    triggered_type = Column(String(15), nullable=True)             # 'take_profit', 'stop_loss', NULL
    execution_price = Column(Numeric(10, 4), nullable=True)        # Price at which it was triggered
    cancelled_reason = Column(String(50), nullable=True)           # Why it was cancelled (user_cancelled, market_closed, etc.)

    # Transaction link (Phase 9)
    entry_transaction_id = Column(Integer, ForeignKey('transactions.id', ondelete='SET NULL'), nullable=True, index=True)  # Links to the BUY transaction that created this position

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    triggered_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    last_price_check = Column(DateTime, nullable=True)

    # Market data snapshot (for display purposes)
    market_data = Column(JSONB, nullable=True)

    # Relationships
    user = relationship("User", backref="tpsl_orders")
    entry_transaction = relationship("Transaction", foreign_keys=[entry_transaction_id], backref="tpsl_orders")

    # Indexes for fast queries
    __table_args__ = (
        Index('idx_tpsl_user_market_outcome', 'user_id', 'market_id', 'outcome'),
        Index('idx_tpsl_active', 'status', 'user_id'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'market_id': self.market_id,
            'outcome': self.outcome,
            'token_id': self.token_id,
            'take_profit_price': float(self.take_profit_price) if self.take_profit_price else None,
            'stop_loss_price': float(self.stop_loss_price) if self.stop_loss_price else None,
            'monitored_tokens': float(self.monitored_tokens),
            'entry_price': float(self.entry_price),
            'status': self.status,
            'triggered_type': self.triggered_type,
            'execution_price': float(self.execution_price) if self.execution_price else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None,
            'last_price_check': self.last_price_check.isoformat() if self.last_price_check else None,
            'market_data': self.market_data
        }


class Withdrawal(Base):
    """
    Withdrawal Transaction Log
    Records all SOL and USDC withdrawals for audit trail and rate limiting
    """
    __tablename__ = "withdrawals"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # User reference
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True)

    # Network and token
    network = Column(String(10), nullable=False, index=True)  # 'SOL' or 'POLYGON'
    token = Column(String(10), nullable=False)  # 'SOL', 'USDC', 'USDC.e'

    # Amount details
    amount = Column(Numeric(20, 8), nullable=False)
    gas_cost = Column(Numeric(20, 8), nullable=True)

    # Addresses
    from_address = Column(Text, nullable=False)
    destination_address = Column(Text, nullable=False)

    # Transaction details
    tx_hash = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default='pending', index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # Metadata
    estimated_usd_value = Column(Numeric(10, 2), nullable=True)

    # Relationship to user
    user = relationship("User", backref="withdrawals")

    # Indexes
    __table_args__ = (
        Index('idx_withdrawals_user_recent', 'user_id', 'created_at'),
        Index('idx_withdrawals_network_status', 'network', 'status'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'network': self.network,
            'token': self.token,
            'amount': float(self.amount) if self.amount else 0,
            'gas_cost': float(self.gas_cost) if self.gas_cost else None,
            'from_address': self.from_address,
            'destination_address': self.destination_address,
            'tx_hash': self.tx_hash,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None,
            'failed_at': self.failed_at.isoformat() if self.failed_at else None,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'estimated_usd_value': float(self.estimated_usd_value) if self.estimated_usd_value else None
        }




class LeaderboardEntry(Base):
    """
    Current Leaderboard Rankings
    Stores both weekly and all-time rankings for users
    """
    __tablename__ = "leaderboard_entries"

    id = Column(Integer, primary_key=True, index=True)

    # User reference
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True)

    # Period type: 'weekly' or 'all-time'
    period = Column(String(20), nullable=False, index=True)

    # Ranking
    rank = Column(Integer, nullable=False)

    # P&L Calculations
    pnl_amount = Column(Numeric(20, 2), nullable=False)           # Sells - Buys
    pnl_percentage = Column(Numeric(10, 4), nullable=False)       # (PNL / Buys) * 100

    # Volume Information
    total_volume_traded = Column(Numeric(20, 2), nullable=False)  # Buys + Sells
    total_buy_volume = Column(Numeric(20, 2), nullable=False)     # Sum of buys
    total_sell_volume = Column(Numeric(20, 2), nullable=False)    # Sum of sells

    # Trade Statistics
    total_trades = Column(Integer, nullable=False)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Numeric(5, 2), default=0)

    # Weekly metadata
    week_start_date = Column(DateTime, nullable=True)
    week_end_date = Column(DateTime, nullable=True)

    # Cached user data
    username = Column(String(100), nullable=True)
    telegram_user_id = Column(BigInteger, nullable=True)

    # Timestamps
    calculated_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", backref="leaderboard_entries")

    # Indexes for performance
    __table_args__ = (
        Index('idx_leaderboard_entries_period', 'period'),
        Index('idx_leaderboard_entries_rank', 'period', 'rank'),
        Index('idx_leaderboard_entries_user', 'user_id'),
        Index('idx_leaderboard_entries_week', 'week_start_date', 'period'),
        Index('idx_leaderboard_entries_pnl', 'pnl_percentage'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'period': self.period,
            'rank': self.rank,
            'pnl_amount': float(self.pnl_amount) if self.pnl_amount else 0,
            'pnl_percentage': float(self.pnl_percentage) if self.pnl_percentage else 0,
            'total_volume_traded': float(self.total_volume_traded) if self.total_volume_traded else 0,
            'total_buy_volume': float(self.total_buy_volume) if self.total_buy_volume else 0,
            'total_sell_volume': float(self.total_sell_volume) if self.total_sell_volume else 0,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': float(self.win_rate) if self.win_rate else 0,
            'username': self.username,
            'telegram_user_id': self.telegram_user_id,
            'week_start_date': self.week_start_date.isoformat() if self.week_start_date else None,
            'week_end_date': self.week_end_date.isoformat() if self.week_end_date else None,
        }


class LeaderboardHistory(Base):
    """
    Historical Leaderboard Records
    Archives past leaderboards for trend analysis
    """
    __tablename__ = "leaderboard_history"

    id = Column(Integer, primary_key=True, index=True)

    # User reference
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True)

    # Period information
    period = Column(String(20), nullable=False)
    week_number = Column(Integer, nullable=False)
    week_year = Column(Integer, nullable=False)
    week_start_date = Column(DateTime, nullable=False)
    week_end_date = Column(DateTime, nullable=False)

    # Ranking snapshot
    rank = Column(Integer, nullable=False)
    rank_change = Column(Integer, nullable=True)  # Change from previous week

    # P&L snapshot
    pnl_amount = Column(Numeric(20, 2), nullable=False)
    pnl_percentage = Column(Numeric(10, 4), nullable=False)
    pnl_change = Column(Numeric(10, 4), nullable=True)

    # Volume snapshot
    total_volume_traded = Column(Numeric(20, 2), nullable=False)
    total_buy_volume = Column(Numeric(20, 2), nullable=False)
    total_sell_volume = Column(Numeric(20, 2), nullable=False)

    # Trade statistics snapshot
    total_trades = Column(Integer, nullable=False)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Numeric(5, 2), default=0)

    # Cached user data
    username = Column(String(100), nullable=True)
    telegram_user_id = Column(BigInteger, nullable=True)

    # Timestamps
    recorded_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", backref="leaderboard_history")

    # Indexes
    __table_args__ = (
        Index('idx_leaderboard_history_user', 'user_id'),
        Index('idx_leaderboard_history_week', 'week_start_date', 'period'),
        Index('idx_leaderboard_history_rank', 'week_start_date', 'rank'),
        Index('idx_leaderboard_history_recorded', 'recorded_at'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'period': self.period,
            'week_number': self.week_number,
            'week_year': self.week_year,
            'rank': self.rank,
            'rank_change': self.rank_change,
            'pnl_amount': float(self.pnl_amount) if self.pnl_amount else 0,
            'pnl_percentage': float(self.pnl_percentage) if self.pnl_percentage else 0,
            'pnl_change': float(self.pnl_change) if self.pnl_change else None,
            'total_volume_traded': float(self.total_volume_traded) if self.total_volume_traded else 0,
            'total_buy_volume': float(self.total_buy_volume) if self.total_buy_volume else 0,
            'total_sell_volume': float(self.total_sell_volume) if self.total_sell_volume else 0,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': float(self.win_rate) if self.win_rate else 0,
            'username': self.username,
            'telegram_user_id': self.telegram_user_id,
        }


class UserStats(Base):
    """
    User Statistics Cache
    Caches calculated stats to avoid recalculation on every query
    """
    __tablename__ = "user_stats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True, unique=True)

    # All-time aggregates
    total_buy_volume = Column(Numeric(20, 2), default=0)
    total_sell_volume = Column(Numeric(20, 2), default=0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)

    # Weekly statistics
    weekly_buy_volume = Column(Numeric(20, 2), default=0)
    weekly_sell_volume = Column(Numeric(20, 2), default=0)
    weekly_trades = Column(Integer, default=0)

    # P&L tracking
    total_pnl = Column(Numeric(20, 2), default=0)
    weekly_pnl = Column(Numeric(20, 2), default=0)

    # Last calculation time
    last_calculated = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", backref="user_stats", uselist=False)

    # Indexes
    __table_args__ = (
        Index('idx_user_stats_user', 'user_id'),
        Index('idx_user_stats_updated', 'updated_at'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'total_buy_volume': float(self.total_buy_volume) if self.total_buy_volume else 0,
            'total_sell_volume': float(self.total_sell_volume) if self.total_sell_volume else 0,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'weekly_buy_volume': float(self.weekly_buy_volume) if self.weekly_buy_volume else 0,
            'weekly_sell_volume': float(self.weekly_sell_volume) if self.weekly_sell_volume else 0,
            'weekly_trades': self.weekly_trades,
            'total_pnl': float(self.total_pnl) if self.total_pnl else 0,
            'weekly_pnl': float(self.weekly_pnl) if self.weekly_pnl else 0,
        }


class Market(Base):
    """
    Markets Table - Populated from Gamma API
    No JSON file dependency
    """
    __tablename__ = "markets"

    # Primary identifiers
    id = Column(String(50), primary_key=True, index=True)
    condition_id = Column(String(100), unique=True, nullable=True, index=True)
    question = Column(Text, nullable=False)
    slug = Column(String(200), nullable=True, index=True)

    # Market status
    status = Column(String(20), nullable=False, default='active', index=True)
    active = Column(Boolean, default=True, index=True)
    closed = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    accepting_orders = Column(Boolean, default=True)

    # Resolution data
    resolved_at = Column(DateTime, nullable=True)
    winner = Column(String(10), nullable=True)
    resolution_source = Column(String(100), nullable=True)

    # Trading data
    volume = Column(Numeric(20, 2), default=0)
    liquidity = Column(Numeric(20, 2), default=0)
    outcomes = Column(JSONB, nullable=True)
    outcome_prices = Column(JSONB, nullable=True)
    clob_token_ids = Column(JSONB, nullable=True)
    tokens = Column(JSONB, nullable=True)  # NEW: Store full tokens array with outcome matching

    # Dates
    end_date = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_fetched = Column(DateTime, default=datetime.utcnow)

    # Trading eligibility
    tradeable = Column(Boolean, default=False, index=True)
    enable_order_book = Column(Boolean, default=False)

    # Event grouping (Polymarket Events API - multi-outcome markets)
    event_id = Column(String(50), nullable=True, index=True)
    event_slug = Column(String(200), nullable=True)
    event_title = Column(String(500), nullable=True)

    # Legacy fields (kept for backward compatibility, but event_id is preferred)
    market_group = Column(Integer, nullable=True, index=True)
    group_item_title = Column(String(100), nullable=True)
    group_item_threshold = Column(String(50), nullable=True)
    group_item_range = Column(String(50), nullable=True)

    # Performance indexes
    __table_args__ = (
        Index('idx_markets_status_updated', 'status', 'last_updated'),
        Index('idx_markets_tradeable_volume', 'status', 'tradeable', 'volume'),
        Index('idx_markets_end_date_status', 'end_date', 'status'),
        Index('idx_markets_resolved', 'status', 'resolved_at'),
        Index('idx_markets_event', 'event_id', 'active'),  # Primary index for events
        Index('idx_markets_group', 'market_group', 'active'),  # Legacy index
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary format"""
        import json

        # Parse JSON strings if needed
        outcomes = self.outcomes
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except:
                outcomes = []

        outcome_prices = self.outcome_prices
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except:
                outcome_prices = []

        clob_token_ids = self.clob_token_ids
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except:
                clob_token_ids = []

        tokens = self.tokens
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except:
                tokens = []

        # FIXED: Always use the actual market question for 'question' field
        # event_title should only be used for grouping/display logic, not for the market's question
        # This ensures individual markets show their specific title, not the event title

        return {
            'id': self.id,
            'condition_id': self.condition_id,
            'question': self.question,  # Always use the specific market question
            'title': self.question,  # Alias for consistency with subsquid tables
            'slug': self.slug,
            'status': self.status,
            'active': self.active,
            'closed': self.closed,
            'archived': self.archived,
            'accepting_orders': self.accepting_orders,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'winner': self.winner,
            'resolution_source': self.resolution_source,
            'volume': float(self.volume) if self.volume else 0.0,
            'liquidity': float(self.liquidity) if self.liquidity else 0.0,
            'outcomes': outcomes,
            'outcome_prices': outcome_prices,
            'clob_token_ids': clob_token_ids,
            'tokens': tokens,  # NEW: Include tokens array for outcome-based matching
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'last_fetched': self.last_fetched.isoformat() if self.last_fetched else None,
            'tradeable': self.tradeable,
            'enable_order_book': self.enable_order_book,
            'event_id': self.event_id,
            'event_slug': self.event_slug,
            'event_title': self.event_title,
            'market_group': self.market_group,
            'group_item_title': self.group_item_title,
            'group_item_threshold': self.group_item_threshold,
            'group_item_range': self.group_item_range,
        }


# ============================================================================
# SUBSQUID MIGRATION MODELS
# ============================================================================

class TrackedLeaderTrade(Base):
    """
    Filtered trades from subsquid_user_transactions for watched addresses
    Full history retained for analytics and copy trading
    """
    __tablename__ = "tracked_leader_trades"

    id = Column(String(255), primary_key=True)
    tx_id = Column(String(255), unique=True, nullable=False, index=True)
    user_address = Column(String(255), nullable=False, index=True)
    market_id = Column(String(100), nullable=True, index=True)
    outcome = Column(Integer, nullable=True)  # 0 = NO, 1 = YES
    tx_type = Column(String(20), nullable=True)  # BUY, SELL
    amount = Column(Numeric(18, 8), nullable=True)
    price = Column(Numeric(18, 8), nullable=True)  # Increased precision to handle high market prices
    amount_usdc = Column(Numeric(18, 6), nullable=True)  # Exact USDC amount spent/received
    tx_hash = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    is_smart_wallet = Column(Boolean, default=False)
    is_external_leader = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Convert to dict format compatible with copy trading"""
        # Priority 1: Use amount_usdc if available (exact USDC from indexer)
        if self.amount_usdc is not None:
            total_amount = float(self.amount_usdc)
        # Priority 2: Fallback to price calculation (but amount is in microunits!)
        elif self.price is not None and self.price > 0 and self.amount is not None:
            # amount is in microunits (6 decimals), so divide by 1e6
            total_amount = float(self.price) * (float(self.amount) / 1e6)
            logger.warning(f"⚠️ Trade {self.id} using price*amount fallback: ${total_amount:.2f}")
        # Priority 3: Last resort (should not happen)
        else:
            logger.error(f"❌ Trade {self.id} missing both amount_usdc and price data")
            total_amount = 0

        return {
            'id': self.id,
            'user_id': None,  # Not applicable for external
            'transaction_type': self.tx_type,
            'market_id': self.market_id,
            'outcome': 'YES' if self.outcome == 1 else 'NO' if self.outcome == 0 else None,
            'tokens': float(self.amount) if self.amount else 0,
            'price_per_token': float(self.price) if self.price else 0,
            'total_amount': total_amount,  # From amount_usdc or fallback
            'amount_usdc': float(self.amount_usdc) if self.amount_usdc else None,
            'transaction_hash': self.tx_hash,
            'executed_at': self.timestamp,
            'created_at': self.created_at
        }


class SubsquidUserTransaction(Base):
    """Read-only model for subsquid_user_transactions (indexed by indexer-ts)"""
    __tablename__ = "subsquid_user_transactions"

    id = Column(String(255), primary_key=True)
    tx_id = Column(String(255), unique=True, nullable=False)
    user_address = Column(String(255), nullable=False, index=True)
    position_id = Column(String(255), nullable=True)
    market_id = Column(String(100), nullable=True)
    outcome = Column(Integer, nullable=True)
    tx_type = Column(String(20), nullable=False)  # BUY, SELL
    amount = Column(Numeric(18, 8), nullable=False)
    price = Column(Numeric(18, 8), nullable=True)  # Increased precision to handle high market prices
    tx_hash = Column(String(255), nullable=False)
    block_number = Column(BigInteger, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class SubsquidMarketPoll(Base):
    """
    Markets from Gamma API polling - NOW POINTS TO markets TABLE
    ✅ OPTIMIZED: Uses markets table with JSONB clob_token_ids and GIN index
    """
    __tablename__ = "markets"  # ✅ CHANGED: Point to unified markets table

    # ✅ MAPPED COLUMNS: Map markets table columns to SubsquidMarketPoll interface
    market_id = Column('id', String(100), primary_key=True)  # markets.id → market_id
    title = Column('title', String(500), nullable=False)
    # ✅ MAPPED: Use is_active Boolean and map to status string in to_dict() method
    is_active = Column('is_active', Boolean, default=True)
    status = Column('status', String(20), default='active')  # Keep status column for compatibility
    expiry = Column('end_date', DateTime(timezone=True))
    last_mid = Column('last_mid_price', Numeric(8, 4))
    updated_at = Column('updated_at', DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Enriched fields
    condition_id = Column('condition_id', String(255))
    slug = Column('slug', String(255), unique=True)
    description = Column('description', String)
    category = Column('category', String)
    accepting_orders = Column('accepting_orders', Boolean, default=False)
    archived = Column('archived', Boolean, default=False)
    tradeable = Column('tradeable', Boolean, default=False)

    volume = Column('volume', Numeric(12, 4))
    volume_24hr = Column(Numeric(12, 4))  # ⚠️ Not in markets table - will be None
    volume_1wk = Column(Numeric(12, 4))  # ⚠️ Not in markets table - will be None
    volume_1mo = Column(Numeric(12, 4))  # ⚠️ Not in markets table - will be None
    liquidity = Column('liquidity', Numeric(12, 4))
    spread = Column(Integer)  # ⚠️ Not in markets table - will be None
    created_at = Column('created_at', DateTime(timezone=True))
    end_date = Column('end_date', DateTime(timezone=True))
    resolution_date = Column('resolved_at', DateTime(timezone=True))  # ✅ MAPPED: resolved_at → resolution_date

    # Price changes
    price_change_1h = Column(Numeric(8, 4))  # ⚠️ Not in markets table - will be None
    price_change_1d = Column(Numeric(8, 4))  # ⚠️ Not in markets table - will be None
    price_change_1w = Column(Numeric(8, 4))  # ⚠️ Not in markets table - will be None

    # Outcome prices from Gamma API (ARRAY of numeric)
    outcome_prices = Column('outcome_prices', JSONB, nullable=True)  # ✅ CHANGED: JSONB instead of ARRAY
    outcomes = Column('outcomes', JSONB, nullable=True)  # ✅ CHANGED: JSONB instead of ARRAY
    clob_token_ids = Column('clob_token_ids', JSONB, nullable=True)  # ✅ CRITICAL: Changed from String to JSONB for GIN index

    # Events array from Gamma API (JSONB) - contains event_id, event_title, etc
    events = Column(JSONB, nullable=True)  # Array of {event_id, event_slug, event_title, event_category, event_volume}

    # Resolution fields
    resolution_status = Column(String(50), nullable=True)  # 'PENDING', 'PROPOSED', 'RESOLVED'
    winning_outcome = Column(Integer, nullable=True)  # 0 or 1 for binary markets
    polymarket_url = Column(String(500), nullable=True)  # URL to Polymarket market page

    market_type = Column(String, default='normal')
    restricted = Column(Boolean, default=False)

    def to_dict(self) -> Dict:
        """Convert to dict"""
        import json

        # Extract event_id from events array if available
        event_id = None

        if self.events and len(self.events) > 0:
            event_info = self.events[0]
            # ✅ SAFETY CHECK: Handle case where events contains strings instead of dicts
            if isinstance(event_info, dict):
                event_id = event_info.get('event_id')
            elif isinstance(event_info, str):
                # Try to parse JSON string
                try:
                    parsed = json.loads(event_info)
                    if isinstance(parsed, dict):
                        event_id = parsed.get('event_id')
                except (json.JSONDecodeError, TypeError):
                    pass  # Skip malformed events

        # Format outcome_prices: use actual data if available, else default to balanced [0.5, 0.5]
        # This is required to pass market validation (_is_market_valid checks for non-empty outcome_prices)
        outcome_prices = []
        if self.outcome_prices:
            outcome_prices = [float(p) for p in self.outcome_prices]
        else:
            # Default balanced prices when no data (common for subsquid data)
            outcome_prices = [0.5, 0.5]

        # Parse clob_token_ids from JSONB field
        # ✅ OPTIMIZED: Handle both array JSONB (new) and string JSONB (legacy)
        clob_token_ids = []
        if self.clob_token_ids:
            try:
                # If it's already a list (array JSONB), use directly
                if isinstance(self.clob_token_ids, list):
                    clob_token_ids = [str(token) for token in self.clob_token_ids if token]
                # If it's a string (string JSONB legacy format), parse it
                elif isinstance(self.clob_token_ids, str):
                    parsed = json.loads(self.clob_token_ids)
                    if isinstance(parsed, str):
                        # Doubly escaped, parse again
                        parsed = json.loads(parsed)
                    if isinstance(parsed, list):
                        clob_token_ids = [str(token) for token in parsed if token]
                # If it's dict/other JSONB type, try to extract
                else:
                    # JSONB might be stored as dict or other format
                    clob_token_ids = [str(token) for token in self.clob_token_ids if token]
            except (json.JSONDecodeError, TypeError, AttributeError):
                # If parsing fails, assume it's invalid
                pass

        # Parse outcomes from ARRAY field
        outcomes = []
        if self.outcomes:
            outcomes = list(self.outcomes)

        # ✅ SAFETY CHECK: Normalize events array to always contain dicts
        # Handle cases where DB contains strings instead of objects
        normalized_events = []
        if self.events:
            for event in self.events:
                if isinstance(event, dict):
                    normalized_events.append(event)
                elif isinstance(event, str):
                    try:
                        parsed = json.loads(event)
                        if isinstance(parsed, dict):
                            normalized_events.append(parsed)
                    except (json.JSONDecodeError, TypeError):
                        pass  # Skip malformed events

        return {
            'id': self.market_id,
            'market_id': self.market_id,
            'title': self.title,  # Always use the actual market title
            'question': self.title,  # Alias for compatibility
            'status': self.status,
            'category': self.category,  # ✅ FIX: Include category for filtering
            'volume': float(self.volume) if self.volume else 0,
            'liquidity': float(self.liquidity) if self.liquidity else 0,
            'last_mid': float(self.last_mid) if self.last_mid else None,
            'end_date': self.end_date,
            'event_id': event_id,  # Extracted from events[0].event_id
            'events': normalized_events,  # ✅ NORMALIZED: Always contains dicts, never strings
            'outcome_prices': outcome_prices,  # Use actual or default balanced prices
            'clob_token_ids': clob_token_ids,  # Parsed from TEXT field
            'outcomes': outcomes,  # From ARRAY field
            'updated_at': self.updated_at
        }


class SubsquidMarketWS(Base):
    """Markets from CLOB WebSocket (subsquid_markets_ws) - LIVE PRICES"""
    __tablename__ = "subsquid_markets_ws"

    market_id = Column(String(100), primary_key=True)
    title = Column(String(500))
    status = Column(String(50))
    expiry = Column(DateTime(timezone=True))
    last_bb = Column(Numeric(8, 4))  # best bid
    last_ba = Column(Numeric(8, 4))  # best ask
    last_mid = Column(Numeric(8, 4))  # mid price
    last_trade_price = Column(Numeric(8, 4))
    last_yes_price = Column(Numeric(8, 4))  # for binary markets
    last_no_price = Column(Numeric(8, 4))   # for binary markets
    outcome_prices = Column(JSONB)  # for multi-outcome markets (JSON)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Convert to dict"""
        return {
            'id': self.market_id,
            'market_id': self.market_id,
            'title': self.title,
            'status': self.status,
            'last_mid': float(self.last_mid) if self.last_mid else None,
            'last_bb': float(self.last_bb) if self.last_bb else None,
            'last_ba': float(self.last_ba) if self.last_ba else None,
            'last_trade_price': float(self.last_trade_price) if self.last_trade_price else None,
            'last_yes_price': float(self.last_yes_price) if self.last_yes_price else None,
            'last_no_price': float(self.last_no_price) if self.last_no_price else None,
            'outcome_prices': self.outcome_prices,
            'updated_at': self.updated_at
        }


class WatchedMarkets(Base):
    """Markets being watched by streamer due to user positions (beyond top 1000)"""
    __tablename__ = "watched_markets"

    market_id = Column(Text, primary_key=True, index=True)
    condition_id = Column(Text, index=True)
    title = Column(Text)
    added_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_position_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    active_positions = Column(Integer, default=0, index=True)
    total_volume = Column(Numeric(20, 8), default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def __repr__(self):
        return f"<WatchedMarkets(market_id='{self.market_id}', active_positions={self.active_positions})>"


class ResolvedPosition(Base):
    """Tracks resolved market positions and redemption status"""
    __tablename__ = "resolved_positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_user_id'), nullable=False, index=True)
    market_id = Column(String(100), nullable=False, index=True)
    condition_id = Column(String(100), nullable=False)
    market_title = Column(Text, nullable=False)
    market_slug = Column(String(200))
    outcome = Column(String(10), nullable=False)
    token_id = Column(String(100), nullable=False)
    tokens_held = Column(Numeric(20, 8), nullable=False)
    total_cost = Column(Numeric(20, 8), nullable=False)
    avg_buy_price = Column(Numeric(10, 8), nullable=False)
    transaction_count = Column(Integer, default=0)
    winning_outcome = Column(String(10), nullable=False)
    is_winner = Column(Boolean, nullable=False)
    resolved_at = Column(DateTime, nullable=False)
    gross_value = Column(Numeric(20, 8), default=0)
    fee_amount = Column(Numeric(20, 8), default=0)
    net_value = Column(Numeric(20, 8), default=0)
    pnl = Column(Numeric(20, 8), nullable=False)
    pnl_percentage = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), default='PENDING', index=True)
    redemption_tx_hash = Column(String(66))
    redemption_block_number = Column(BigInteger)
    redemption_gas_used = Column(BigInteger)
    redemption_gas_price = Column(BigInteger)
    redemption_attempt_count = Column(Integer, default=0)
    last_redemption_error = Column(Text)
    processing_started_at = Column(DateTime)
    notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    redeemed_at = Column(DateTime)
    expires_at = Column(DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'market_id': self.market_id,
            'condition_id': self.condition_id,
            'market_title': self.market_title,
            'market_slug': self.market_slug,
            'outcome': self.outcome,
            'token_id': self.token_id,
            'tokens_held': float(self.tokens_held),
            'total_cost': float(self.total_cost),
            'avg_buy_price': float(self.avg_buy_price),
            'transaction_count': self.transaction_count,
            'winning_outcome': self.winning_outcome,
            'net_value': float(self.net_value),
            'gross_value': float(self.gross_value),
            'fee_amount': float(self.fee_amount),
            'pnl': float(self.pnl),
            'pnl_percentage': float(self.pnl_percentage),
            'is_winner': self.is_winner,
            'status': self.status,
            'redemption_tx_hash': self.redemption_tx_hash,
            'redemption_attempt_count': self.redemption_attempt_count or 0,
            'notified': self.notified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'redeemed_at': self.redeemed_at.isoformat() if self.redeemed_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }


class ExternalLeader(Base):
    """
    External Leaders Cache
    Stores traders found via CLOB API (Tier 3 address resolution)
    Used for copy trading feature to cache external traders not in our users table
    """
    __tablename__ = "external_leaders"

    # Primary key - virtual_id is the primary key in Supabase
    virtual_id = Column(BigInteger, primary_key=True, index=True, comment="Unique ID for this external address")

    # Polygon wallet address
    polygon_address = Column(String(42), nullable=False, unique=True, index=True, comment="Blockchain address on Polygon (0x...)")

    # Last trade tracking
    last_trade_id = Column(String(255), nullable=True, default='')

    # Trade count
    trade_count = Column(Integer, default=0, nullable=True, comment="Number of trades indexed for this address")

    # Active status (whether they still have trades on CLOB)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Polling information
    last_poll_at = Column(DateTime, nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Indexes for performance
    __table_args__ = (
        Index('idx_external_leaders_address', 'polygon_address'),
        Index('idx_external_leaders_active', 'is_active'),
        Index('idx_external_leaders_last_poll', 'last_poll_at'),
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'virtual_id': self.virtual_id,
            'polygon_address': self.polygon_address,
            'last_trade_id': self.last_trade_id,
            'is_active': self.is_active,
            'last_poll_at': self.last_poll_at.isoformat() if self.last_poll_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class DatabaseManager:
    """Manages all database operations"""

    def __init__(self):
        self.engine = engine
        self.SessionLocal = SessionLocal
        logger.info("🔧 Database manager initialized with new unified schema")

    def create_tables(self):
        """Create all database tables (should already exist after migration)"""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("✅ Database tables verified/created")
        except Exception as e:
            logger.error(f"❌ Failed to create/verify tables: {e}")
            raise

    def get_session(self) -> Session:
        """Get database session"""
        return self.SessionLocal()

    # ============================================================================
    # User Operations
    # ============================================================================

    def get_user(self, telegram_user_id: int) -> Optional[User]:
        """Get user by telegram ID"""
        with self.get_session() as db:
            return db.query(User).filter(User.telegram_user_id == telegram_user_id).first()

    def create_user(self, telegram_user_id: int, username: str,
                   polygon_address: str, polygon_private_key: str) -> User:
        """Create a new user"""
        with self.get_session() as db:
            user = User(
                telegram_user_id=telegram_user_id,
                username=username,
                polygon_address=polygon_address,
                polygon_private_key=polygon_private_key
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

    def update_user_solana_wallet(self, telegram_user_id: int,
                                  solana_address: str, solana_private_key: str) -> bool:
        """Add/update Solana wallet for user"""
        try:
            with self.get_session() as db:
                user = db.query(User).filter(User.telegram_user_id == telegram_user_id).first()
                if user:
                    user.solana_address = solana_address
                    user.solana_private_key = solana_private_key
                    db.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"❌ Error updating Solana wallet: {e}")
            return False

    def update_user_api_keys(self, telegram_user_id: int,
                            api_key: str, api_secret: str, api_passphrase: str) -> bool:
        """Update API credentials for user"""
        try:
            with self.get_session() as db:
                user = db.query(User).filter(User.telegram_user_id == telegram_user_id).first()
                if user:
                    user.api_key = api_key
                    user.api_secret = api_secret
                    user.api_passphrase = api_passphrase
                    db.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"❌ Error updating API keys: {e}")
            return False

    def update_user_approvals(self, telegram_user_id: int, **kwargs) -> bool:
        """Update approval status for user (funded, usdc_approved, pol_approved, polymarket_approved)"""
        try:
            with self.get_session() as db:
                user = db.query(User).filter(User.telegram_user_id == telegram_user_id).first()
                if user:
                    for key, value in kwargs.items():
                        if hasattr(user, key):
                            setattr(user, key, value)
                    db.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"❌ Error updating approvals: {e}")
            return False

    # ============================================================================
    # POSITION OPERATIONS REMOVED - Using transaction-based architecture + direct blockchain API

    # ============================================================================
    # Market Operations
    # ============================================================================

    def get_market(self, market_id: str) -> Optional[Market]:
        """Get market by ID"""
        with self.get_session() as db:
            return db.query(Market).filter(Market.id == market_id).first()

    def get_tradeable_markets(self, limit: int = 20) -> List[Market]:
        """Get tradeable markets"""
        with self.get_session() as db:
            return db.query(Market).filter(
                Market.tradeable == True,
                Market.status == 'active'
            ).order_by(Market.volume.desc()).limit(limit).all()


# Global database manager instance
db_manager = DatabaseManager()


def get_db() -> Session:
    """Dependency to get database session"""
    db = db_manager.get_session()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """Initialize database on startup"""
    logger.info("🚀 Initializing PostgreSQL database with new schema...")

    try:
        # Verify tables exist
        db_manager.create_tables()
        logger.info("✅ Database initialization complete")

    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise
