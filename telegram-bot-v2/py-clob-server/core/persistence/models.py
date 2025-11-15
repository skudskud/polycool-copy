"""
PostgreSQL Database Models
ENHANCED: Now captures ALL Gamma API fields for parent/child markets, categories, and rich metadata
"""

from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Numeric, Text, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from .db_config import Base


class Market(Base):
    """
    Enhanced Market model with complete Gamma API data
    Supports parent/child market grouping, categories, and rich filtering
    """
    __tablename__ = "markets"

    # ========================================
    # PRIMARY IDENTIFIERS
    # ========================================
    id = Column(String(50), primary_key=True, index=True)
    condition_id = Column(String(100), unique=True, nullable=True, index=True)
    question = Column(Text, nullable=False)
    slug = Column(String(200), nullable=True, index=True)
    question_id = Column(String(100), nullable=True)  # NEW

    # ========================================
    # EVENT GROUPING (Polymarket Events API - multi-outcome markets)
    # ========================================
    event_id = Column(String(50), nullable=True, index=True)    # Event ID from Polymarket
    event_slug = Column(String(200), nullable=True)             # Event slug
    event_title = Column(String(500), nullable=True)            # Event title

    # ========================================
    # PARENT/CHILD MARKET GROUPING (LEGACY)
    # ========================================
    market_group = Column(Integer, nullable=True, index=True)  # Parent group ID
    group_item_title = Column(String(200), nullable=True)      # Sub-market title
    group_item_threshold = Column(String(100), nullable=True)  # Threshold value
    group_item_range = Column(String(100), nullable=True)      # Range value

    # ========================================
    # CATEGORIZATION & ORGANIZATION
    # ========================================
    category = Column(String(100), nullable=True, index=True)  # Politics, Sports, Crypto, etc.
    tags = Column(JSONB, nullable=True)                        # Array of tag objects
    events = Column(JSONB, nullable=True)                      # Array of event objects

    # ========================================
    # VISUAL & RICH CONTENT
    # ========================================
    image = Column(Text, nullable=True)                        # Market image URL
    icon = Column(Text, nullable=True)                         # Market icon URL
    description = Column(Text, nullable=True)                  # Full description
    twitter_card_image = Column(Text, nullable=True)          # Social media image

    # ========================================
    # MARKET CLASSIFICATION
    # ========================================
    market_type = Column(String(50), nullable=True)           # Type classification
    format_type = Column(String(50), nullable=True)           # Format type
    featured = Column(Boolean, default=False, index=True)     # Featured markets
    new = Column(Boolean, default=False)                      # New markets flag

    # ========================================
    # MARKET STATUS (EXISTING)
    # ========================================
    status = Column(String(20), nullable=False, default='active', index=True)
    active = Column(Boolean, default=True, index=True)
    closed = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    accepting_orders = Column(Boolean, default=True)
    restricted = Column(Boolean, default=False, nullable=True)  # NEW

    # ========================================
    # RESOLUTION DATA (EXISTING + ENHANCED)
    # ========================================
    resolved_at = Column(DateTime, nullable=True)
    winner = Column(String(10), nullable=True)
    resolution_source = Column(String(100), nullable=True)
    resolved_by = Column(String(100), nullable=True)          # NEW: Who resolved it

    # ========================================
    # TRADING DATA - BASE (EXISTING)
    # ========================================
    volume = Column(Numeric(20, 2), default=0, index=True)
    liquidity = Column(Numeric(20, 2), default=0)
    outcomes = Column(JSONB, nullable=True)
    outcome_prices = Column(JSONB, nullable=True)
    clob_token_ids = Column(JSONB, nullable=True)

    # ========================================
    # TRADING DATA - VOLUME BREAKDOWN (NEW)
    # ========================================
    volume_24hr = Column(Numeric(20, 2), nullable=True)       # 24 hour volume
    volume_1wk = Column(Numeric(20, 2), nullable=True)        # 1 week volume
    volume_1mo = Column(Numeric(20, 2), nullable=True)        # 1 month volume
    volume_1yr = Column(Numeric(20, 2), nullable=True)        # 1 year volume

    # ========================================
    # PRICE MOVEMENT & TRENDING (NEW)
    # ========================================
    one_hour_price_change = Column(Numeric(10, 6), nullable=True)   # 1hr price Δ
    one_day_price_change = Column(Numeric(10, 6), nullable=True)    # 24hr price Δ
    one_week_price_change = Column(Numeric(10, 6), nullable=True)   # 7d price Δ
    one_month_price_change = Column(Numeric(10, 6), nullable=True)  # 30d price Δ
    one_year_price_change = Column(Numeric(10, 6), nullable=True)   # 365d price Δ

    # ========================================
    # CURRENT MARKET STATE (NEW)
    # ========================================
    last_trade_price = Column(Numeric(10, 6), nullable=True)  # Last executed price
    best_bid = Column(Numeric(10, 6), nullable=True)          # Highest buy order
    best_ask = Column(Numeric(10, 6), nullable=True)          # Lowest sell order
    spread = Column(Numeric(10, 6), nullable=True)            # Bid-ask spread

    # ========================================
    # COMPETITION & REWARDS (NEW)
    # ========================================
    competitive = Column(Numeric(10, 2), nullable=True)       # Competitive score
    rewards_min_size = Column(Numeric(10, 2), nullable=True)  # Min reward size
    rewards_max_spread = Column(Numeric(10, 6), nullable=True) # Max reward spread

    # ========================================
    # SPORTS MARKETS (NEW)
    # ========================================
    game_id = Column(String(100), nullable=True)              # Game identifier
    game_start_time = Column(DateTime, nullable=True)         # Game start time
    sports_market_type = Column(String(50), nullable=True)    # Sports type

    # ========================================
    # DATES (EXISTING)
    # ========================================
    end_date = Column(DateTime, nullable=True, index=True)
    start_date = Column(DateTime, nullable=True)              # NEW
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_fetched = Column(DateTime, default=datetime.utcnow)

    # ========================================
    # TRADING ELIGIBILITY (EXISTING)
    # ========================================
    tradeable = Column(Boolean, default=False, index=True)
    enable_order_book = Column(Boolean, default=False)

    # ========================================
    # PERFORMANCE INDEXES (ENHANCED)
    # ========================================
    __table_args__ = (
        # Existing indexes
        Index('idx_markets_status_updated', 'status', 'last_updated'),
        Index('idx_markets_tradeable_volume', 'status', 'tradeable', 'volume'),
        Index('idx_markets_end_date_status', 'end_date', 'status'),
        Index('idx_markets_resolved', 'status', 'resolved_at'),

        # NEW: Parent/child grouping indexes
        Index('idx_markets_market_group', 'market_group'),
        Index('idx_markets_group_volume', 'market_group', 'volume'),

        # NEW: Category filtering indexes
        Index('idx_markets_category', 'category'),
        Index('idx_markets_category_volume', 'category', 'volume'),

        # NEW: Featured markets index
        Index('idx_markets_featured', 'featured', 'volume'),

        # NEW: Trending markets index
        Index('idx_markets_trending', 'one_day_price_change'),
    )

    def to_dict(self):
        """Convert to dictionary format with ALL fields"""
        # Display logic: If event_title exists and is different from market question,
        # display the event_title (this is an outcome of a larger event)
        # Otherwise, display the market question (unique market)
        display_question = self.question
        if self.event_title and self.event_title != self.question:
            display_question = self.event_title

        return {
            # Primary identifiers
            'id': self.id,
            'condition_id': self.condition_id,
            'question': display_question,  # Use display logic for question
            'slug': self.slug,
            'question_id': self.question_id,

            # Event grouping (Polymarket Events API)
            'event_id': self.event_id,
            'event_slug': self.event_slug,
            'event_title': self.event_title,

            # Parent/child grouping (legacy)
            'market_group': self.market_group,
            'group_item_title': self.group_item_title,
            'group_item_threshold': self.group_item_threshold,
            'group_item_range': self.group_item_range,

            # Categorization
            'category': self.category,
            'tags': self.tags,
            'events': self.events,

            # Visual & rich content
            'image': self.image,
            'icon': self.icon,
            'description': self.description,
            'twitter_card_image': self.twitter_card_image,

            # Market classification
            'market_type': self.market_type,
            'format_type': self.format_type,
            'featured': self.featured,
            'new': self.new,

            # Market status
            'status': self.status,
            'active': self.active,
            'closed': self.closed,
            'archived': self.archived,
            'accepting_orders': self.accepting_orders,
            'restricted': self.restricted,

            # Resolution data
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'winner': self.winner,
            'resolution_source': self.resolution_source,
            'resolved_by': self.resolved_by,

            # Trading data - base
            'volume': float(self.volume) if self.volume else 0,
            'liquidity': float(self.liquidity) if self.liquidity else 0,
            'outcomes': self.outcomes,
            'outcome_prices': self.outcome_prices,
            'clob_token_ids': self.clob_token_ids,

            # Volume breakdown
            'volume_24hr': float(self.volume_24hr) if self.volume_24hr else None,
            'volume_1wk': float(self.volume_1wk) if self.volume_1wk else None,
            'volume_1mo': float(self.volume_1mo) if self.volume_1mo else None,
            'volume_1yr': float(self.volume_1yr) if self.volume_1yr else None,

            # Price movement
            'one_hour_price_change': float(self.one_hour_price_change) if self.one_hour_price_change else None,
            'one_day_price_change': float(self.one_day_price_change) if self.one_day_price_change else None,
            'one_week_price_change': float(self.one_week_price_change) if self.one_week_price_change else None,
            'one_month_price_change': float(self.one_month_price_change) if self.one_month_price_change else None,
            'one_year_price_change': float(self.one_year_price_change) if self.one_year_price_change else None,

            # Current market state
            'last_trade_price': float(self.last_trade_price) if self.last_trade_price else None,
            'best_bid': float(self.best_bid) if self.best_bid else None,
            'best_ask': float(self.best_ask) if self.best_ask else None,
            'spread': float(self.spread) if self.spread else None,

            # Competition & rewards
            'competitive': float(self.competitive) if self.competitive else None,
            'rewards_min_size': float(self.rewards_min_size) if self.rewards_min_size else None,
            'rewards_max_spread': float(self.rewards_max_spread) if self.rewards_max_spread else None,

            # Sports markets
            'game_id': self.game_id,
            'game_start_time': self.game_start_time.isoformat() if self.game_start_time else None,
            'sports_market_type': self.sports_market_type,

            # Dates
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'last_fetched': self.last_fetched.isoformat() if self.last_fetched else None,

            # Trading eligibility
            'tradeable': self.tradeable,
            'enable_order_book': self.enable_order_book
        }


class SmartWallet(Base):
    """
    Smart Wallet model for tracking curated smart traders
    """
    __tablename__ = "smart_wallets"

    address = Column(String(42), primary_key=True)  # Ethereum address
    smartscore = Column(Numeric(20, 10), nullable=True)
    win_rate = Column(Numeric(10, 8), nullable=True)
    markets_count = Column(Integer, nullable=True)
    realized_pnl = Column(Numeric(20, 2), nullable=True)
    bucket_smart = Column(String(50), nullable=True)
    bucket_last_date = Column(String(50), nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'address': self.address,
            'smartscore': float(self.smartscore) if self.smartscore else None,
            'win_rate': float(self.win_rate) if self.win_rate else None,
            'markets_count': self.markets_count,
            'realized_pnl': float(self.realized_pnl) if self.realized_pnl else None,
            'bucket_smart': self.bucket_smart,
            'bucket_last_date': self.bucket_last_date,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class SmartWalletTrade(Base):
    """
    Smart Wallet Trade model for tracking trades from smart wallets
    """
    __tablename__ = "smart_wallet_trades"

    id = Column(String(100), primary_key=True)  # transactionHash (66 chars)
    wallet_address = Column(String(42), nullable=False, index=True)
    market_id = Column(String(100), nullable=False, index=True)  # token_id (large numeric string from subsquid)
    condition_id = Column(String(100), nullable=True, index=True)  # 0x... format (for joining with subsquid_markets_poll and callbacks)
    position_id = Column(String(100), nullable=True, index=True)  # ✅ Real clob_token_id - source of truth for outcome mapping
    side = Column(String(10), nullable=False)  # BUY or SELL
    outcome = Column(String(50), nullable=True)  # Outcome name (team names can be long)
    price = Column(Numeric(20, 10), nullable=False)
    size = Column(Numeric(20, 10), nullable=False)
    value = Column(Numeric(20, 2), nullable=False)  # price * size
    timestamp = Column(DateTime, nullable=False, index=True)
    is_first_time = Column(Boolean, default=False, index=True)  # First time on this market
    market_question = Column(Text, nullable=True)  # Cached for display
    created_at = Column(DateTime, default=datetime.utcnow)
    tweeted_at = Column(DateTime, nullable=True, index=True)  # When this trade was posted to Twitter

    __table_args__ = (
        Index('idx_wallet_timestamp', 'wallet_address', 'timestamp'),
        Index('idx_first_time_value', 'is_first_time', 'value'),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'wallet_address': self.wallet_address,
            'market_id': self.market_id,
            'condition_id': self.condition_id,
            'side': self.side,
            'outcome': self.outcome,
            'price': float(self.price) if self.price else None,
            'size': float(self.size) if self.size else None,
            'value': float(self.value) if self.value else None,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'is_first_time': self.is_first_time,
            'market_question': self.market_question,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'tweeted_at': self.tweeted_at.isoformat() if self.tweeted_at else None
        }


class SmartWalletTradesToShare(Base):
    """
    Unified Shareable Trades Table
    Single source of truth for ALL notification systems (Twitter, Alert, Push, /smart_trading)
    Contains ONLY qualified trades that meet sharing criteria
    """
    __tablename__ = "smart_wallet_trades_to_share"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(255), nullable=False, unique=True, index=True)  # References smart_wallet_trades.id

    # Denormalized wallet data (no JOINs needed)
    wallet_address = Column(String(42), nullable=False, index=True)
    wallet_bucket = Column(String(50), nullable=True)  # 'Very Smart', 'Smart', etc
    wallet_win_rate = Column(Numeric(5, 4), nullable=True)
    wallet_smartscore = Column(Numeric(10, 2), nullable=True)
    wallet_realized_pnl = Column(Numeric(20, 2), nullable=True)

    # Trade data
    side = Column(String(10), nullable=False)  # 'BUY' or 'SELL'
    outcome = Column(String(50), nullable=True)  # 'YES' or 'NO'
    price = Column(Numeric(20, 10), nullable=False)
    size = Column(Numeric(20, 10), nullable=False)
    value = Column(Numeric(20, 2), nullable=False)

    # Market data
    market_id = Column(String(100), nullable=True)  # token_id (numeric)
    condition_id = Column(String(100), nullable=True, index=True)  # 0x... format
    market_question = Column(Text, nullable=False)  # MUST have title

    # Metadata
    timestamp = Column(DateTime, nullable=False, index=True)
    is_first_time = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Tracking: which systems consumed this trade
    tweeted_at = Column(DateTime, nullable=True, index=True)
    alerted_at = Column(DateTime, nullable=True, index=True)
    push_notification_count = Column(Integer, default=0)
    last_push_notification_at = Column(DateTime, nullable=True)

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'wallet_address': self.wallet_address,
            'wallet_bucket': self.wallet_bucket,
            'wallet_win_rate': float(self.wallet_win_rate) if self.wallet_win_rate else None,
            'wallet_smartscore': float(self.wallet_smartscore) if self.wallet_smartscore else None,
            'wallet_realized_pnl': float(self.wallet_realized_pnl) if self.wallet_realized_pnl else None,
            'side': self.side,
            'outcome': self.outcome,
            'price': float(self.price) if self.price else None,
            'size': float(self.size) if self.size else None,
            'value': float(self.value) if self.value else None,
            'market_id': self.market_id,
            'condition_id': self.condition_id,
            'market_question': self.market_question,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'is_first_time': self.is_first_time,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'tweeted_at': self.tweeted_at.isoformat() if self.tweeted_at else None,
            'alerted_at': self.alerted_at.isoformat() if self.alerted_at else None,
            'push_notification_count': self.push_notification_count,
            'last_push_notification_at': self.last_push_notification_at.isoformat() if self.last_push_notification_at else None
        }


class SmartTradeNotification(Base):
    """
    Smart Trade Notification tracking table
    Tracks which trades have been notified to which users for deduplication
    """
    __tablename__ = "smart_trade_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(255), nullable=False, index=True)  # SmartWalletTrade.id
    user_id = Column(Integer, nullable=False, index=True)  # User.telegram_user_id
    notified_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    clicked = Column(Boolean, default=False)  # User clicked any button
    action_taken = Column(String(50), nullable=True)  # 'view', 'quick_buy', 'custom_buy'

    __table_args__ = (
        Index('idx_notification_trade_user', 'trade_id', 'user_id', unique=True),
        Index('idx_notification_notified_at', 'notified_at'),
        Index('idx_notification_user_recent', 'user_id', 'notified_at'),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'user_id': self.user_id,
            'notified_at': self.notified_at.isoformat() if self.notified_at else None,
            'clicked': self.clicked,
            'action_taken': self.action_taken
        }


class TweetBot(Base):
    """
    Tweet Bot model for tracking all tweets posted to Twitter
    Provides visibility and monitoring of tweet activity
    """
    __tablename__ = "tweets_bot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(100), nullable=False, index=True)
    tweet_text = Column(Text, nullable=False)
    tweet_id = Column(String(50), nullable=True)  # Twitter's tweet ID
    status = Column(String(20), nullable=False, default='pending', index=True)  # pending/posted/failed
    character_count = Column(Integer, nullable=True)
    market_question = Column(Text, nullable=True)
    trade_value = Column(Numeric(20, 2), nullable=True)
    wallet_address = Column(String(42), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_tweets_bot_created_at_desc', 'created_at', postgresql_using='btree'),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'tweet_text': self.tweet_text,
            'tweet_id': self.tweet_id,
            'status': self.status,
            'character_count': self.character_count,
            'market_question': self.market_question,
            'trade_value': float(self.trade_value) if self.trade_value else None,
            'wallet_address': self.wallet_address,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
