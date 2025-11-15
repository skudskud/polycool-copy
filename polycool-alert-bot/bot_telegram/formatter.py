"""
Message formatter for Telegram alerts
Creates beautiful, informative alert messages
"""

from typing import Dict, Any
from config import EMOJIS, MAIN_BOT_LINK
from utils.logger import logger


class MessageFormatter:
    """Format trade data into Telegram messages"""
    
    @staticmethod
    def format_alert(trade: Dict[str, Any]) -> str:
        """
        Format a trade into an alert message
        
        Args:
            trade: Trade dictionary
            
        Returns:
            Formatted message string
        """
        # Extract trade data
        side = trade.get('side', 'BUY')
        outcome = trade.get('outcome', 'Unknown')
        value = trade.get('value', 0)
        price = trade.get('price', 0)
        size = trade.get('size', 0)
        market_question = trade.get('market_question', 'Unknown Market')
        win_rate = trade.get('win_rate', 0)
        smartscore = trade.get('smartscore', 0)
        wallet_address = trade.get('wallet_address', '')
        trade_id = trade.get('id', '')
        market_id = trade.get('market_id', '')
        timestamp = trade.get('timestamp')
        
        # Format timestamp
        from datetime import datetime
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        trade_time = timestamp.strftime("%b %d, %Y at %H:%M UTC") if timestamp else "Unknown"
        
        # Shorten wallet address (first 6 + last 4 chars)
        shortened_wallet = f"{wallet_address[:6]}...{wallet_address[-4:]}" if len(wallet_address) >= 10 else wallet_address
        
        # URLs
        profile_url = f"https://polymarket.com/profile/{wallet_address}"
        
        # Calculate confidence score (1-10 based on win rate)
        confidence_score = MessageFormatter._calculate_confidence_score(win_rate)
        confidence_visual = MessageFormatter._format_confidence_visual(confidence_score)
        
        # Determine side emoji
        side_emoji = EMOJIS['buy'] if side == 'BUY' else EMOJIS['sell']
        
        # Format message
        message = f"{EMOJIS['fire']} **Smart Trader Alert**\n\n"
        message += f"📊 Market: {market_question}\n"
        message += f"🕐 Trade Time: {trade_time}\n\n"
        message += f"Smart wallet just entered:\n"
        message += f"👤 [{shortened_wallet}]({profile_url})\n"
        message += f"📊 Win Rate: {win_rate*100:.1f}% | Smart Score: {smartscore:.1f}\n"
        
        # Only show size if > 0 (defensive coding)
        try:
            size_value = float(size) if size else 0
            size_str = f" (Size: {size_value:,.0f})" if size_value > 0 else ""
            message += f"💰 Position: ${value:,.2f} @ ${price:.2f}{size_str}\n"
        except Exception as e:
            logger.error(f"Error formatting size field: {e}")
            # Fallback: show without size
            message += f"💰 Position: ${value:,.2f} @ ${price:.2f}\n"
        
        message += f"📈 Side: {side} {outcome}\n\n"
        message += f"🎯 Confidence Score: {confidence_visual} {confidence_score}/10"
        
        return message
    
    @staticmethod
    def _calculate_confidence_score(win_rate: float) -> int:
        """
        Calculate confidence score (1-10) based on win rate
        
        Args:
            win_rate: Win rate as decimal (0-1)
            
        Returns:
            Confidence score from 1-10
        """
        win_rate_pct = win_rate * 100
        
        if win_rate_pct >= 85:
            return 10
        elif win_rate_pct >= 80:
            return 9
        elif win_rate_pct >= 75:
            return 8
        elif win_rate_pct >= 70:
            return 7
        elif win_rate_pct >= 65:
            return 6
        elif win_rate_pct >= 60:
            return 5
        elif win_rate_pct >= 55:
            return 4
        elif win_rate_pct >= 50:
            return 3
        else:
            return 2
    
    @staticmethod
    def _format_confidence_visual(score: int) -> str:
        """
        Format confidence score as visual emoji representation
        
        Args:
            score: Confidence score (1-10)
            
        Returns:
            Visual representation with green and gray circles
        """
        filled = "🟢" * score
        empty = "⚫" * (10 - score)
        return filled + empty
    
    @staticmethod
    def format_compact_alert(trade: Dict[str, Any]) -> str:
        """
        Format a trade into a compact alert message (shorter version)
        
        Args:
            trade: Trade dictionary
            
        Returns:
            Formatted message string
        """
        side = trade.get('side', 'BUY')
        outcome = trade.get('outcome', 'Unknown')
        value = trade.get('value', 0)
        market_question = trade.get('market_question', 'Unknown Market')
        win_rate = trade.get('win_rate', 0)
        
        side_emoji = EMOJIS['buy'] if side == 'BUY' else EMOJIS['sell']
        
        message = f"{EMOJIS['fire']} **Smart Trader Alert**\n\n"
        message += f"{side_emoji} **{side} {outcome}** - ${value:,.0f}\n"
        message += f"{market_question}\n"
        message += f"Win Rate: {win_rate*100:.0f}% {EMOJIS['star']}\n\n"
        message += f"{EMOJIS['arrow_right']} [Copy This Trade]({MAIN_BOT_LINK})"
        
        return message
    
    @staticmethod
    def format_stats_message(stats: Dict[str, Any]) -> str:
        """
        Format daily statistics message
        
        Args:
            stats: Statistics dictionary
            
        Returns:
            Formatted message string
        """
        message = f"{EMOJIS['chart']} **Polycool Alert Bot Stats**\n\n"
        message += f"**Today's Activity:**\n"
        message += f"{EMOJIS['check']} Alerts Sent: {stats.get('alerts_sent', 0)}\n"
        message += f"{EMOJIS['search']} Trades Checked: {stats.get('total_trades_checked', 0)}\n"
        message += f"Skipped (Rate Limit): {stats.get('alerts_skipped_rate_limit', 0)}\n"
        message += f"Skipped (Filters): {stats.get('alerts_skipped_filters', 0)}\n\n"
        
        if stats.get('last_checked_at'):
            message += f"Last Checked: {stats['last_checked_at']}\n"
        
        return message
    
    @staticmethod
    def validate_message(message: str) -> bool:
        """
        Validate message length and content
        
        Args:
            message: Message to validate
            
        Returns:
            True if valid
        """
        # Telegram message limit is 4096 characters
        if len(message) > 4096:
            logger.warning(f"⚠️ Message too long: {len(message)} chars")
            return False
        
        if not message.strip():
            logger.warning("⚠️ Empty message")
            return False
        
        return True


# Global formatter instance
formatter = MessageFormatter()

