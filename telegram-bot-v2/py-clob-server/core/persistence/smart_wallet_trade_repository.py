"""
Smart Wallet Trade Repository
Handles database operations for smart_wallet_trades table
"""

import logging
from typing import List, Dict, Optional, Set
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import and_, desc
from datetime import datetime, timedelta, timezone

from .models import SmartWalletTrade, SmartWallet

logger = logging.getLogger(__name__)


class SmartWalletTradeRepository:
    """Repository for smart wallet trade operations"""

    def __init__(self, db_session):
        self.session = db_session

    def trade_exists(self, trade_id: str) -> bool:
        """
        Check if a trade already exists in database

        Args:
            trade_id: Trade ID from API

        Returns:
            True if trade exists, False otherwise
        """
        try:
            exists = self.session.query(SmartWalletTrade).filter(
                SmartWalletTrade.id == trade_id
            ).first() is not None
            return exists
        except SQLAlchemyError as e:
            logger.error(f"Error checking if trade {trade_id} exists: {e}")
            self.session.rollback()
            return False

    def add_trade(self, trade_data: Dict) -> Optional[SmartWalletTrade]:
        """
        Add a new trade to database

        Args:
            trade_data: Dictionary with trade data

        Returns:
            SmartWalletTrade object or None on error
        """
        try:
            trade = SmartWalletTrade(
                id=trade_data['id'],
                wallet_address=trade_data['wallet_address'],
                market_id=trade_data['market_id'],
                side=trade_data['side'],
                outcome=trade_data.get('outcome'),
                price=trade_data['price'],
                size=trade_data['size'],
                value=trade_data['value'],
                timestamp=trade_data['timestamp'],
                is_first_time=trade_data.get('is_first_time', False),
                market_question=trade_data.get('market_question'),
                created_at=datetime.utcnow()
            )

            self.session.add(trade)
            self.session.commit()

            logger.debug(f"Added trade {trade.id} for wallet {trade.wallet_address}")
            return trade

        except SQLAlchemyError as e:
            logger.error(f"Error adding trade {trade_data.get('id')}: {e}")
            self.session.rollback()
            return None

    def bulk_add_trades(self, trades: List[Dict]) -> int:
        """
        Bulk add trades to database

        Args:
            trades: List of trade data dictionaries

        Returns:
            Number of trades added
        """
        if not trades:
            return 0

        try:
            # Prepare values for bulk insert
            values_list = []
            for trade_data in trades:
                values_list.append({
                    'id': trade_data['id'],
                    'wallet_address': trade_data['wallet_address'],
                    'market_id': trade_data['market_id'],
                    'side': trade_data['side'],
                    'outcome': trade_data.get('outcome'),
                    'price': trade_data['price'],
                    'size': trade_data['size'],
                    'value': trade_data['value'],
                    'timestamp': trade_data['timestamp'],
                    'is_first_time': trade_data.get('is_first_time', False),
                    'market_question': trade_data.get('market_question'),
                    'created_at': datetime.utcnow()
                })

            # Use PostgreSQL INSERT ... ON CONFLICT DO NOTHING to skip duplicates
            stmt = insert(SmartWalletTrade).values(values_list)
            stmt = stmt.on_conflict_do_nothing(index_elements=['id'])

            result = self.session.execute(stmt)
            self.session.commit()

            inserted_count = result.rowcount if result.rowcount else 0
            logger.info(f"✅ Bulk added {inserted_count} new trades (skipped {len(values_list) - inserted_count} duplicates)")
            return inserted_count

        except SQLAlchemyError as e:
            logger.error(f"Error bulk adding trades: {e}")
            self.session.rollback()
            return 0

    def get_wallet_market_history(self, wallet_address: str) -> Set[str]:
        """
        Get set of market IDs that a wallet has traded on

        Args:
            wallet_address: Ethereum wallet address

        Returns:
            Set of market IDs
        """
        try:
            # Query distinct market IDs for this wallet
            market_ids = self.session.query(SmartWalletTrade.market_id).filter(
                SmartWalletTrade.wallet_address == wallet_address
            ).distinct().all()

            # Convert to set
            market_set = {market_id[0] for market_id in market_ids}
            logger.debug(f"Wallet {wallet_address} has traded on {len(market_set)} markets")
            return market_set

        except SQLAlchemyError as e:
            logger.error(f"Error getting market history for {wallet_address}: {e}")
            self.session.rollback()
            return set()

    def get_recent_first_time_trades(
        self,
        limit: int = 10,
        min_value: float = 400.0,
        max_age_minutes: int = None  # None = no time limit, get all
    ) -> List:
        """
        Get recent first-time trades - NOW READS FROM smart_wallet_trades_to_share (UNIFIED TABLE)
        
        All filtering is done by filter processor. This simply returns recent qualified trades.
        
        Args:
            limit: Maximum number of trades to return
            min_value: Minimum trade value in USD (legacy, table already filtered at $400)
            max_age_minutes: Maximum age of trades in minutes (default: None = unlimited)
        
        Returns:
            List of SmartWalletTradesToShare objects, sorted by timestamp DESC (newest → oldest)
        """
        try:
            from core.persistence.models import SmartWalletTradesToShare
            
            # Build query from unified table
            query = self.session.query(SmartWalletTradesToShare)
            
            # Optional: apply freshness filter if specified
            if max_age_minutes is not None:
                cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
                query = query.filter(SmartWalletTradesToShare.timestamp >= cutoff_time)
                logger.debug(f"Applying freshness filter: trades within last {max_age_minutes} minutes")
            else:
                logger.debug("No freshness filter - fetching all qualified trades from smart_wallet_trades_to_share")
            
            # Execute query
            trades = query.order_by(
                desc(SmartWalletTradesToShare.timestamp)  # Newest first
            ).limit(limit).all()
            
            time_info = f"<{max_age_minutes}min" if max_age_minutes else "all time"
            logger.info(f"📊 [REPOSITORY] Retrieved {len(trades)} qualified trades from smart_wallet_trades_to_share ({time_info})")
            return trades
        
        except SQLAlchemyError as e:
            logger.error(f"Error getting recent trades from smart_wallet_trades_to_share: {e}")
            self.session.rollback()
            return []

    def get_first_trade_on_market(self, wallet_address: str, market_id: str) -> Optional[SmartWalletTrade]:
        """
        Get the first trade for a wallet on a specific market

        Args:
            wallet_address: Ethereum wallet address
            market_id: Market ID

        Returns:
            SmartWalletTrade object or None if not found
        """
        try:
            first_trade = self.session.query(SmartWalletTrade).filter(
                and_(
                    SmartWalletTrade.wallet_address == wallet_address,
                    SmartWalletTrade.market_id == market_id
                )
            ).order_by(
                SmartWalletTrade.timestamp.asc()
            ).first()

            return first_trade

        except SQLAlchemyError as e:
            logger.error(f"Error getting first trade for {wallet_address} on {market_id}: {e}")
            self.session.rollback()
            return None

    def count_trades(self, wallet_address: Optional[str] = None) -> int:
        """
        Count trades, optionally filtered by wallet

        Args:
            wallet_address: Optional wallet address filter

        Returns:
            Count of trades
        """
        try:
            # PERFORMANCE FIX: Use raw SQL COUNT instead of SQLAlchemy count() (faster)
            # Also handles transaction errors more gracefully
            from sqlalchemy import text

            # First check if session is in failed transaction state
            if self.session.is_active and self.session.in_transaction():
                try:
                    # Try to ping the database to detect failed transaction
                    self.session.execute(text("SELECT 1"))
                except Exception:
                    # Failed transaction detected - rollback and retry
                    logger.warning("⚠️ Detected failed transaction, rolling back...")
                    self.session.rollback()

            if wallet_address:
                query = text("SELECT COUNT(*) FROM smart_wallet_trades WHERE wallet_address = :addr")
                result = self.session.execute(query, {"addr": wallet_address})
            else:
                query = text("SELECT COUNT(*) FROM smart_wallet_trades")
                result = self.session.execute(query)

            count = result.scalar()
            return count or 0

        except Exception as e:
            logger.error(f"Error counting trades: {e}")
            try:
                self.session.rollback()
            except Exception as rollback_err:
                logger.error(f"Rollback failed: {rollback_err}")
            return 0

    def count_first_time_trades(self) -> int:
        """
        Count trades marked as first-time

        Returns:
            Count of first-time trades
        """
        try:
            # PERFORMANCE FIX: Use raw SQL COUNT for better performance
            from sqlalchemy import text
            query = text("SELECT COUNT(*) FROM smart_wallet_trades WHERE is_first_time = true")
            result = self.session.execute(query)
            count = result.scalar()
            return count or 0

        except SQLAlchemyError as e:
            logger.error(f"Error counting first-time trades: {e}")
            try:
                self.session.rollback()
            except Exception as rollback_err:
                logger.error(f"Rollback failed: {rollback_err}")
            return 0

    def get_untweeted_qualifying_trades(self, limit: int = 10, min_value: float = 300.0) -> List:
        """
        Get trades that haven't been tweeted yet and meet qualifying criteria
        
        NOW READS FROM: smart_wallet_trades_to_share (UNIFIED TABLE)
        
        Criteria (already filtered by smart_wallet_trades_to_share table):
        - BUY only
        - First-time entry
        - >= $400
        - Has market title
        - Very Smart wallet
        - Not crypto price market
        - < 5 minutes old
        
        This method now simply queries pre-filtered qualified trades.
        
        Args:
            limit: Maximum number of trades to return
            min_value: Minimum trade value in USD (legacy parameter, table already filtered at $400)
        
        Returns:
            List of SmartWalletTradesToShare objects ordered by timestamp DESC
        """
        try:
            from core.persistence.models import SmartWalletTradesToShare
            
            # Simple query - all filtering done by filter processor!
            trades = self.session.query(SmartWalletTradesToShare).filter(
                SmartWalletTradesToShare.tweeted_at == None
            ).order_by(
                desc(SmartWalletTradesToShare.timestamp)
            ).limit(limit).all()
            
            logger.debug(f"Retrieved {len(trades)} untweeted qualified trades from smart_wallet_trades_to_share")
            return trades
        
        except SQLAlchemyError as e:
            logger.error(f"Error getting untweeted qualifying trades: {e}")
            self.session.rollback()
            return []

    def mark_as_tweeted(self, trade_id: str, timestamp: Optional[datetime] = None) -> bool:
        """
        Mark a trade as tweeted in smart_wallet_trades_to_share table
        
        Args:
            trade_id: Trade ID to mark
            timestamp: Timestamp when tweeted (default: now)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            from core.persistence.models import SmartWalletTradesToShare
            
            if timestamp is None:
                timestamp = datetime.utcnow()
            
            # Update in smart_wallet_trades_to_share table
            trade = self.session.query(SmartWalletTradesToShare).filter(
                SmartWalletTradesToShare.trade_id == trade_id
            ).first()
            
            if not trade:
                logger.warning(f"Trade {trade_id} not found in smart_wallet_trades_to_share when marking as tweeted")
                return False
            
            trade.tweeted_at = timestamp
            self.session.commit()
            
            logger.debug(f"Marked trade {trade_id} as tweeted at {timestamp} in smart_wallet_trades_to_share")
            return True
        
        except SQLAlchemyError as e:
            logger.error(f"Error marking trade as tweeted: {e}")
            self.session.rollback()
            return False

    def count_untweeted_trades(self, min_value: float = 300.0) -> int:
        """
        Count trades that haven't been tweeted yet

        Args:
            min_value: Minimum trade value to count

        Returns:
            Count of untweeted qualifying trades
        """
        try:
            count = self.session.query(SmartWalletTrade).filter(
                and_(
                    SmartWalletTrade.is_first_time == True,
                    SmartWalletTrade.side == 'BUY',
                    SmartWalletTrade.value >= min_value,
                    SmartWalletTrade.tweeted_at == None
                )
            ).count()
            return count
        except SQLAlchemyError as e:
            logger.error(f"Error counting untweeted trades: {e}")
            self.session.rollback()
            return 0

    def get_untweeted_addon_trades(self, limit: int = 10, min_value: float = 1000.0) -> List[SmartWalletTrade]:
        """
        Get add-on trades (not first-time) that haven't been tweeted yet

        These are "doubling down" trades where wallets add to existing positions.

        Criteria:
        - is_first_time = FALSE (adding to existing position)
        - side = 'BUY' (adding to position, not exiting)
        - value >= min_value (e.g., $1000+ for significant add-ons)
        - tweeted_at IS NULL (not yet tweeted)
        - timestamp within last 5 minutes (FRESH trades for copy trading)
        - NOT crypto price markets (excludes "up or down", price levels, etc.)

        Args:
            limit: Maximum number of trades to return
            min_value: Minimum trade value in USD (default $1000)

        Returns:
            List of SmartWalletTrade objects ordered by timestamp DESC
        """
        try:
            # Only tweet trades from last 5 minutes (FRESH trades for copy trading)
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)

            trades = self.session.query(SmartWalletTrade).filter(
                and_(
                    SmartWalletTrade.is_first_time == False,
                    SmartWalletTrade.side == 'BUY',
                    SmartWalletTrade.value >= min_value,
                    SmartWalletTrade.tweeted_at == None,
                    SmartWalletTrade.timestamp >= cutoff_time,  # FRESH TRADES ONLY (5min)

                    # CRYPTO PRICE MARKET EXCLUSIONS
                    # Exclude short-term crypto price prediction markets
                    ~SmartWalletTrade.market_question.ilike('%up or down%'),
                    ~SmartWalletTrade.market_question.ilike('%higher or lower%'),
                    ~SmartWalletTrade.market_question.ilike('%price of bitcoin%'),
                    ~SmartWalletTrade.market_question.ilike('%price of ethereum%'),
                    ~SmartWalletTrade.market_question.ilike('%price of eth %'),
                    ~SmartWalletTrade.market_question.ilike('%price of solana%'),
                    ~SmartWalletTrade.market_question.ilike('%price of sol %'),
                    ~SmartWalletTrade.market_question.ilike('%price of xrp%'),
                    ~SmartWalletTrade.market_question.ilike('%price of bnb%'),
                    ~SmartWalletTrade.market_question.ilike('%price of cardano%'),
                    ~SmartWalletTrade.market_question.ilike('%price of dogecoin%'),
                    ~SmartWalletTrade.market_question.ilike('%bitcoin above%'),
                    ~SmartWalletTrade.market_question.ilike('%bitcoin below%'),
                    ~SmartWalletTrade.market_question.ilike('%ethereum above%'),
                    ~SmartWalletTrade.market_question.ilike('%ethereum below%'),
                    ~SmartWalletTrade.market_question.ilike('%eth above%'),
                    ~SmartWalletTrade.market_question.ilike('%eth below%'),
                    ~SmartWalletTrade.market_question.ilike('%solana above%'),
                    ~SmartWalletTrade.market_question.ilike('%solana below%'),
                    ~SmartWalletTrade.market_question.ilike('%sol above%'),
                    ~SmartWalletTrade.market_question.ilike('%sol below%'),
                    ~SmartWalletTrade.market_question.ilike('%xrp above%'),
                    ~SmartWalletTrade.market_question.ilike('%xrp below%'),
                    ~SmartWalletTrade.market_question.ilike('%next 15 minutes%'),
                    ~SmartWalletTrade.market_question.ilike('%next 30 minutes%'),
                    ~SmartWalletTrade.market_question.ilike('%next hour%'),
                    ~SmartWalletTrade.market_question.ilike('%next 4 hours%'),
                    ~SmartWalletTrade.market_question.ilike('%in the next hour%'),
                )
            ).order_by(
                desc(SmartWalletTrade.timestamp)
            ).limit(limit).all()

            logger.debug(f"Retrieved {len(trades)} untweeted add-on FRESH trades (>= ${min_value}, <5min old, no crypto price markets)")
            return trades

        except SQLAlchemyError as e:
            logger.error(f"Error getting untweeted add-on trades: {e}")
            self.session.rollback()
            return []

    def count_untweeted_addon_trades(self, min_value: float = 1000.0) -> int:
        """
        Count add-on trades that haven't been tweeted yet

        Args:
            min_value: Minimum trade value to count

        Returns:
            Count of untweeted add-on trades
        """
        try:
            count = self.session.query(SmartWalletTrade).filter(
                and_(
                    SmartWalletTrade.is_first_time == False,
                    SmartWalletTrade.side == 'BUY',
                    SmartWalletTrade.value >= min_value,
                    SmartWalletTrade.tweeted_at == None
                )
            ).count()
            return count
        except SQLAlchemyError as e:
            logger.error(f"Error counting untweeted add-on trades: {e}")
            self.session.rollback()
            return 0
