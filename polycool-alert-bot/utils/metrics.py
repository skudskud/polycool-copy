"""
Metrics tracking for Polycool Alert Bot
"""

from datetime import datetime, date
from typing import Dict, Any, Optional
from utils.logger import logger


class Metrics:
    """
    In-memory metrics tracking for the current session
    These get persisted to database periodically
    """
    
    def __init__(self):
        self.session_start = datetime.now()
        self.trades_checked = 0
        self.alerts_sent = 0
        self.alerts_skipped_rate_limit = 0
        self.alerts_skipped_filters = 0
        self.errors = 0
        self.last_poll_at: Optional[datetime] = None
        self.last_alert_at: Optional[datetime] = None
    
    def increment_trades_checked(self, count: int = 1):
        """Increment trades checked counter"""
        self.trades_checked += count
    
    def increment_alerts_sent(self, count: int = 1):
        """Increment alerts sent counter"""
        self.alerts_sent += count
        self.last_alert_at = datetime.now()
    
    def increment_skipped_rate_limit(self, count: int = 1):
        """Increment rate limit skips counter"""
        self.alerts_skipped_rate_limit += count
    
    def increment_skipped_filters(self, count: int = 1):
        """Increment filter skips counter"""
        self.alerts_skipped_filters += count
    
    def increment_errors(self, count: int = 1):
        """Increment errors counter"""
        self.errors += count
    
    def update_last_poll(self):
        """Update last poll timestamp"""
        self.last_poll_at = datetime.now()
    
    def get_uptime_seconds(self) -> int:
        """Get uptime in seconds"""
        return int((datetime.now() - self.session_start).total_seconds())
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        return {
            'session_start': self.session_start,
            'uptime_seconds': self.get_uptime_seconds(),
            'trades_checked': self.trades_checked,
            'alerts_sent': self.alerts_sent,
            'alerts_skipped_rate_limit': self.alerts_skipped_rate_limit,
            'alerts_skipped_filters': self.alerts_skipped_filters,
            'errors': self.errors,
            'last_poll_at': self.last_poll_at,
            'last_alert_at': self.last_alert_at,
        }
    
    def log_summary(self):
        """Log metrics summary"""
        summary = self.get_summary()
        logger.info(f"📊 Metrics Summary:")
        logger.info(f"  Uptime: {summary['uptime_seconds']}s")
        logger.info(f"  Trades checked: {summary['trades_checked']}")
        logger.info(f"  Alerts sent: {summary['alerts_sent']}")
        logger.info(f"  Skipped (rate limit): {summary['alerts_skipped_rate_limit']}")
        logger.info(f"  Skipped (filters): {summary['alerts_skipped_filters']}")
        logger.info(f"  Errors: {summary['errors']}")
    
    def reset_daily(self):
        """Reset daily counters (called at midnight)"""
        logger.info("🔄 Resetting daily metrics")
        self.trades_checked = 0
        self.alerts_sent = 0
        self.alerts_skipped_rate_limit = 0
        self.alerts_skipped_filters = 0
        self.errors = 0


# Global metrics instance
metrics = Metrics()

