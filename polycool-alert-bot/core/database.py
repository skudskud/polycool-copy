"""
Database layer for Polycool Alert Bot
Handles all database operations
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from config import DATABASE_URL, BOT_VERSION
from utils.logger import logger


class Database:
    """Database connection and query manager"""
    
    def __init__(self):
        self.connection_string = DATABASE_URL
        self.conn = None
    
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(
                self.connection_string,
                cursor_factory=RealDictCursor
            )
            logger.info("✅ Database connected")
            return True
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            raise
    
    def disconnect(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("🔒 Database disconnected")
    
    def get_cursor(self):
        """Get database cursor"""
        if not self.conn or self.conn.closed:
            self.connect()
        return self.conn.cursor()
    
    # =====================================================================
    # PENDING TRADES QUERIES
    # =====================================================================
    
    def fetch_pending_trades(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fetch pending trades from smart_wallet_trades_to_share (UNIFIED TABLE)
        
        NOW READS FROM: smart_wallet_trades_to_share instead of alert_bot_pending_trades view
        All filtering logic is centralized in the filter processor.
        
        Args:
            limit: Maximum number of trades to fetch
            
        Returns:
            List of trade dictionaries
        """
        try:
            with self.get_cursor() as cur:
                query = """
                    SELECT 
                        trade_id as id,
                        wallet_address,
                        wallet_win_rate as win_rate,
                        wallet_smartscore as smartscore,
                        wallet_bucket as bucket_smart,
                        market_question,
                        value,
                        timestamp,
                        side,
                        outcome,
                        price,
                        is_first_time,
                        condition_id
                    FROM smart_wallet_trades_to_share
                    WHERE alerted_at IS NULL
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                cur.execute(query, (limit,))
                trades = cur.fetchall()
                return [dict(trade) for trade in trades]
        except Exception as e:
            logger.error(f"❌ Error fetching pending trades: {e}")
            return []
    
    # =====================================================================
    # SENT ALERTS TRACKING
    # =====================================================================
    
    def mark_trade_alerted(
        self,
        trade_id: str,
        wallet_address: str,
        market_question: str,
        value: float,
        telegram_message_id: int,
        telegram_chat_id: int
    ) -> bool:
        """
        Mark a trade as alerted in smart_wallet_trades_to_share table
        
        Args:
            trade_id: Trade ID
            wallet_address: Wallet address
            market_question: Market question
            value: Trade value
            telegram_message_id: Telegram message ID
            telegram_chat_id: Telegram chat ID
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.get_cursor() as cur:
                # Update alerted_at timestamp in smart_wallet_trades_to_share
                query = """
                    UPDATE smart_wallet_trades_to_share
                    SET alerted_at = NOW()
                    WHERE trade_id = %s
                """
                cur.execute(query, (trade_id,))
                self.conn.commit()
                logger.debug(f"✅ Marked trade {trade_id[:16]}... as alerted in smart_wallet_trades_to_share")
                return True
        except Exception as e:
            logger.error(f"❌ Error marking trade alerted: {e}")
            try:
                self.conn.rollback()
            except:
                pass
            return False
    
    # =====================================================================
    # RATE LIMITING
    # =====================================================================
    
    def is_trade_alerted(self, trade_id: str) -> bool:
        """
        Check if a trade has already been alerted (checks smart_wallet_trades_to_share.alerted_at)
        
        Args:
            trade_id: Transaction hash
            
        Returns:
            True if already alerted
        """
        try:
            with self.get_cursor() as cur:
                query = "SELECT 1 FROM smart_wallet_trades_to_share WHERE trade_id = %s AND alerted_at IS NOT NULL"
                cur.execute(query, (trade_id,))
                return cur.fetchone() is not None
        except Exception as e:
            logger.error(f"❌ Error checking if trade alerted: {e}")
            return False
    
    # =====================================================================
    # RATE LIMITING
    # =====================================================================
    
    def get_current_hour_alerts(self) -> int:
        """
        Get number of alerts sent in current hour
        
        Returns:
            Number of alerts sent this hour
        """
        try:
            current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
            
            with self.get_cursor() as cur:
                query = """
                    SELECT alerts_sent FROM alert_bot_rate_limit
                    WHERE hour_bucket = %s
                """
                cur.execute(query, (current_hour,))
                result = cur.fetchone()
                return result['alerts_sent'] if result else 0
        except Exception as e:
            logger.error(f"❌ Error getting current hour alerts: {e}")
            return 0
    
    def increment_hour_alerts(self) -> bool:
        """
        Increment alerts sent for current hour
        
        Returns:
            True if successful
        """
        try:
            current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
            
            with self.get_cursor() as cur:
                query = """
                    INSERT INTO alert_bot_rate_limit (hour_bucket, alerts_sent, updated_at)
                    VALUES (%s, 1, NOW())
                    ON CONFLICT (hour_bucket) 
                    DO UPDATE SET 
                        alerts_sent = alert_bot_rate_limit.alerts_sent + 1,
                        updated_at = NOW()
                """
                cur.execute(query, (current_hour,))
                self.conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Error incrementing hour alerts: {e}")
            self.conn.rollback()
            return False
    
    def increment_hour_skipped(self) -> bool:
        """
        Increment skipped alerts for current hour
        
        Returns:
            True if successful
        """
        try:
            current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
            
            with self.get_cursor() as cur:
                query = """
                    INSERT INTO alert_bot_rate_limit (hour_bucket, alerts_skipped, updated_at)
                    VALUES (%s, 1, NOW())
                    ON CONFLICT (hour_bucket)
                    DO UPDATE SET 
                        alerts_skipped = alert_bot_rate_limit.alerts_skipped + 1,
                        updated_at = NOW()
                """
                cur.execute(query, (current_hour,))
                self.conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Error incrementing hour skipped: {e}")
            self.conn.rollback()
            return False
    
    # =====================================================================
    # STATISTICS
    # =====================================================================
    
    def update_daily_stats(
        self,
        trades_checked: int = 0,
        alerts_sent: int = 0,
        skipped_rate_limit: int = 0,
        skipped_filters: int = 0
    ) -> bool:
        """
        Update today's statistics
        
        Args:
            trades_checked: Trades checked
            alerts_sent: Alerts sent
            skipped_rate_limit: Skipped due to rate limit
            skipped_filters: Skipped due to filters
            
        Returns:
            True if successful
        """
        try:
            today = date.today()
            
            with self.get_cursor() as cur:
                query = """
                    INSERT INTO alert_bot_stats 
                        (date, total_trades_checked, alerts_sent, 
                         alerts_skipped_rate_limit, alerts_skipped_filters, last_checked_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (date)
                    DO UPDATE SET
                        total_trades_checked = alert_bot_stats.total_trades_checked + %s,
                        alerts_sent = alert_bot_stats.alerts_sent + %s,
                        alerts_skipped_rate_limit = alert_bot_stats.alerts_skipped_rate_limit + %s,
                        alerts_skipped_filters = alert_bot_stats.alerts_skipped_filters + %s,
                        last_checked_at = NOW()
                """
                cur.execute(query, (
                    today, trades_checked, alerts_sent, skipped_rate_limit, skipped_filters,
                    trades_checked, alerts_sent, skipped_rate_limit, skipped_filters
                ))
                self.conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Error updating daily stats: {e}")
            self.conn.rollback()
            return False
    
    # =====================================================================
    # HEALTH MONITORING
    # =====================================================================
    
    def update_health_status(
        self,
        status: str,
        last_poll_at: Optional[datetime] = None,
        last_alert_at: Optional[datetime] = None,
        errors_last_hour: int = 0,
        uptime_seconds: int = 0
    ) -> bool:
        """
        Update bot health status
        
        Args:
            status: running, stopped, error
            last_poll_at: Last poll timestamp
            last_alert_at: Last alert timestamp
            errors_last_hour: Errors in last hour
            uptime_seconds: Uptime in seconds
            
        Returns:
            True if successful
        """
        try:
            with self.get_cursor() as cur:
                query = """
                    UPDATE alert_bot_health SET
                        status = %s,
                        last_poll_at = COALESCE(%s, last_poll_at),
                        last_alert_at = COALESCE(%s, last_alert_at),
                        errors_last_hour = %s,
                        uptime_seconds = %s,
                        version = %s,
                        updated_at = NOW()
                """
                cur.execute(query, (
                    status, last_poll_at, last_alert_at,
                    errors_last_hour, uptime_seconds, BOT_VERSION
                ))
                self.conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Error updating health status: {e}")
            self.conn.rollback()
            return False
    
    def get_health_status(self) -> Optional[Dict[str, Any]]:
        """
        Get current health status
        
        Returns:
            Health status dictionary
        """
        try:
            with self.get_cursor() as cur:
                query = "SELECT * FROM alert_bot_health LIMIT 1"
                cur.execute(query)
                result = cur.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Error getting health status: {e}")
            return None


# Global database instance
db = Database()

