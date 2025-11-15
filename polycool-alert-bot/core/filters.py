"""
Filters for trade quality and rate limiting
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from config import FILTERS, RATE_LIMITS
from utils.logger import logger
from core.database import db


class TradeFilters:
    """
    Quality filters for trades
    Determines which trades should be alerted
    """
    
    @staticmethod
    def is_crypto_price_market(question: str) -> bool:
        """
        Check if market is a crypto price prediction
        
        Excludes short-term crypto price markets like:
        - "Bitcoin Up or Down"
        - "Price of Ethereum above X"
        - Quick timeframe predictions (15min, 30min, 1h)
        
        Allows:
        - Long-term predictions ("Bitcoin $100k by 2025")
        - Policy/adoption ("Trump to announce Bitcoin reserve")
        - Non-price crypto events
        
        Args:
            question: Market question text
            
        Returns:
            True if it's a crypto price market to exclude
        """
        if not question:
            return False
        
        question_lower = question.lower()
        
        # Keywords that indicate short-term price prediction markets
        crypto_price_keywords = [
            # Directional predictions
            "up or down",
            "higher or lower",
            
            # Price levels
            "price of bitcoin",
            "price of ethereum",
            "price of eth",
            "price of solana",
            "price of sol",
            "price of xrp",
            "price of bnb",
            "price of cardano",
            "price of ada",
            "price of dogecoin",
            "price of doge",
            
            # Crypto names with "above" or "below"
            "bitcoin above",
            "bitcoin below",
            "ethereum above",
            "ethereum below",
            "eth above",
            "eth below",
            "solana above",
            "solana below",
            "sol above",
            "sol below",
            "xrp above",
            "xrp below",
            "bnb above",
            "bnb below",
            
            # Quick timeframes (very short-term markets)
            "next 15 minutes",
            "next 30 minutes",
            "next hour",
            "next 4 hours",
            "in the next hour",
            "in the next 4 hours",
        ]
        
        return any(keyword in question_lower for keyword in crypto_price_keywords)
    
    @staticmethod
    def passes_filters(trade: Dict[str, Any]) -> tuple[bool, str]:
        """
        Check if trade passes all quality filters
        
        UNIFIED SYSTEM: The FilterProcessor in main bot already filtered all trades
        before adding to smart_wallet_trades_to_share table. Alert Bot should
        TRUST THE TABLE and send ALL trades without re-filtering.
        
        This ensures all 4 systems (Twitter, Push, Alert, /smart_trading) see SAME trades.
        
        Args:
            trade: Trade dictionary from smart_wallet_trades_to_share
            
        Returns:
            (passes: bool, reason: str) - Always returns (True, "passed") to trust the table
        """
        # NO FILTERING - Trust the unified table!
        # FilterProcessor already checked:
        # - First-time trades only
        # - Minimum value ($100+)
        # - Very Smart wallets
        # - Has market question  
        # - Exclude crypto price markets
        # - Freshness (< 5 minutes)
        
        # All trades in smart_wallet_trades_to_share are pre-qualified
        return True, "passed"
    
    @staticmethod
    def log_filter_result(trade: Dict[str, Any], passed: bool, reason: str):
        """Log filter result for debugging"""
        trade_id = trade.get('id', 'unknown')[:10]
        value = trade.get('value', 0)
        
        if passed:
            logger.debug(f"✅ Trade {trade_id} passed filters (${value:.0f})")
        else:
            logger.debug(f"⏭️  Trade {trade_id} skipped: {reason} (${value:.0f})")


class RateLimiter:
    """
    Rate limiting for alerts
    Enforces max alerts per hour and minimum interval between alerts
    """
    
    def __init__(self):
        self.last_alert_time: Optional[datetime] = None
    
    def can_send_alert(self) -> tuple[bool, str]:
        """
        Check if we can send an alert now
        
        Returns:
            (can_send: bool, reason: str)
        """
        # Check 1: Max alerts per hour
        current_hour_alerts = db.get_current_hour_alerts()
        max_per_hour = RATE_LIMITS['max_per_hour']
        
        if current_hour_alerts >= max_per_hour:
            return False, f"hourly_limit_reached ({current_hour_alerts}/{max_per_hour})"
        
        # Check 2: Minimum interval between alerts
        min_interval = RATE_LIMITS['min_interval_seconds']
        if self.last_alert_time:
            elapsed = (datetime.now() - self.last_alert_time).total_seconds()
            if elapsed < min_interval:
                remaining = min_interval - elapsed
                return False, f"interval_too_soon ({remaining:.0f}s remaining)"
        
        # Can send
        return True, "ok"
    
    def record_alert_sent(self):
        """Record that an alert was sent"""
        self.last_alert_time = datetime.now()
        db.increment_hour_alerts()
    
    def record_alert_skipped(self):
        """Record that an alert was skipped due to rate limit"""
        db.increment_hour_skipped()
    
    def get_current_rate(self) -> Dict[str, Any]:
        """
        Get current rate limit status
        
        Returns:
            Dictionary with rate limit info
        """
        current_hour_alerts = db.get_current_hour_alerts()
        max_per_hour = RATE_LIMITS['max_per_hour']
        remaining = max_per_hour - current_hour_alerts
        
        return {
            'current_hour_alerts': current_hour_alerts,
            'max_per_hour': max_per_hour,
            'remaining': max(0, remaining),
            'percentage_used': (current_hour_alerts / max_per_hour) * 100 if max_per_hour > 0 else 0,
            'last_alert_time': self.last_alert_time,
        }
    
    def log_rate_status(self):
        """Log current rate limit status"""
        status = self.get_current_rate()
        logger.info(
            f"📊 Rate: {status['current_hour_alerts']}/{status['max_per_hour']} "
            f"({status['remaining']} remaining)"
        )


# Global rate limiter instance
rate_limiter = RateLimiter()

