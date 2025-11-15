"""
Health monitoring for the bot
"""

from datetime import datetime
from typing import Dict, Any
from utils.logger import logger
from core.database import db


class HealthMonitor:
    """Monitor bot health and report issues"""
    
    @staticmethod
    def check_health() -> Dict[str, Any]:
        """
        Check overall bot health
        
        Returns:
            Health check results
        """
        health = {
            'timestamp': datetime.now(),
            'database': HealthMonitor._check_database(),
            'telegram': HealthMonitor._check_telegram(),
            'overall_status': 'healthy'
        }
        
        # Determine overall status
        if not health['database']['connected'] or not health['telegram']['configured']:
            health['overall_status'] = 'unhealthy'
        
        return health
    
    @staticmethod
    def _check_database() -> Dict[str, Any]:
        """Check database connectivity"""
        try:
            db.connect()
            # Try a simple query
            health = db.get_health_status()
            return {
                'connected': True,
                'last_poll': health.get('last_poll_at') if health else None,
                'status': 'ok'
            }
        except Exception as e:
            logger.error(f"❌ Database health check failed: {e}")
            return {
                'connected': False,
                'error': str(e),
                'status': 'error'
            }
    
    @staticmethod
    def _check_telegram() -> Dict[str, Any]:
        """Check Telegram bot configuration"""
        from config import BOT_TOKEN, TELEGRAM_CHANNEL_ID
        
        configured = bool(BOT_TOKEN and TELEGRAM_CHANNEL_ID)
        
        return {
            'configured': configured,
            'channel_id': TELEGRAM_CHANNEL_ID,
            'status': 'ok' if configured else 'not_configured'
        }
    
    @staticmethod
    def log_health():
        """Log current health status"""
        health = HealthMonitor.check_health()
        
        if health['overall_status'] == 'healthy':
            logger.info("✅ Health check: All systems operational")
        else:
            logger.warning("⚠️ Health check: Issues detected")
            if not health['database']['connected']:
                logger.error("  - Database: disconnected")
            if not health['telegram']['configured']:
                logger.error("  - Telegram: not configured")


# Create global instance
health_monitor = HealthMonitor()

