"""
Message formatting for Alert Channel Bot
Includes smart_score and confidence_score calculations
"""
import logging
import re
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def calculate_confidence_score(win_rate: Optional[float]) -> int:
    """
    Calculate confidence score (1-10) based on win rate
    Same formula as old system
    
    Args:
        win_rate: Win rate as decimal (0-1) or None
        
    Returns:
        Confidence score from 1-10
    """
    try:
        if win_rate is None:
            return 5  # Neutral score if no data
        
        # Ensure win_rate is in valid range
        win_rate = max(0.0, min(1.0, float(win_rate)))
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
    except Exception as e:
        logger.warning(f"⚠️ Error calculating confidence score: {e}")
        return 5  # Default to neutral


def format_confidence_visual(score: int) -> str:
    """
    Format confidence score as visual emoji representation
    
    Args:
        score: Confidence score (1-10)
        
    Returns:
        Visual representation with green and gray circles
    """
    try:
        # Clamp score to valid range
        score = max(1, min(10, int(score)))
        filled = "🟢" * score
        empty = "⚫" * (10 - score)
        return filled + empty
    except Exception as e:
        logger.warning(f"⚠️ Error formatting confidence visual: {e}")
        return "🟢🟢🟢🟢🟢⚫⚫⚫⚫⚫"  # Default to 5/10


def shorten_wallet_address(address: Optional[str]) -> Optional[str]:
    """
    Shorten wallet address to "0xABCD...1234" format
    
    Args:
        address: Full wallet address or None
        
    Returns:
        Shortened address or None
    """
    try:
        if not address:
            return None
        
        address = str(address)
        if len(address) < 10:
            return address  # Too short to shorten
        
        return f"{address[:6]}...{address[-4:]}"
    except Exception as e:
        logger.warning(f"⚠️ Error shortening wallet address: {e}")
        return address


def format_timestamp(timestamp) -> str:
    """
    Format timestamp as "Nov 06, 2025 at 07:50 UTC"
    
    Args:
        timestamp: datetime object or ISO string
        
    Returns:
        Formatted timestamp string
    """
    try:
        if not timestamp:
            return "Recent"
        
        # Handle ISO string
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        # Ensure timezone-aware
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        return timestamp.strftime("%b %d, %Y at %H:%M UTC")
    except Exception as e:
        logger.warning(f"⚠️ Error formatting timestamp: {e}")
        return "Recent"


def escape_markdown(text: str) -> str:
    """
    Escape special markdown characters to prevent formatting issues
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text safe for Telegram Markdown
    """
    try:
        if not text:
            return ""
        # Escape special Markdown characters: * _ [ ] ( ) ~ ` > # + - = | { } . !
        return re.sub(r'([*_`\[\]()~>#+\-=|{}.!])', r'\\\1', str(text))
    except Exception as e:
        logger.error(f"❌ Error escaping markdown: {e}")
        return str(text)


def format_alert_message(trade_data: Dict[str, Any]) -> str:
    """
    Format trade alert message for Telegram channel
    Matches the old alert channel format exactly
    
    Args:
        trade_data: Dictionary with trade information
            - trade_id
            - market_id
            - market_title
            - wallet_address
            - wallet_name
            - win_rate (0-1 decimal)
            - risk_score (smart_score source)
            - outcome (YES/NO)
            - side (BUY/SELL)
            - price
            - value (amount_usdc)
            - timestamp
            
    Returns:
        Formatted message string
    """
    try:
        # Extract fields
        market_title = trade_data.get('market_title') or 'Unknown Market'
        if market_title and len(market_title) > 150:
            market_title = market_title[:147] + "..."
        market_title = escape_markdown(market_title) if market_title else 'Unknown Market'
        
        timestamp = trade_data.get('timestamp')
        timestamp_str = format_timestamp(timestamp)
        
        wallet_address = trade_data.get('wallet_address', 'Unknown')
        shortened_wallet = shorten_wallet_address(wallet_address)
        
        win_rate = trade_data.get('win_rate')
        win_rate_pct = win_rate * 100 if win_rate else None
        
        # Smart score from risk_score
        smart_score = trade_data.get('risk_score')  # This is the smart_score source
        
        # Calculate confidence score
        confidence_score = calculate_confidence_score(win_rate)
        confidence_visual = format_confidence_visual(confidence_score)
        
        value = trade_data.get('value') or trade_data.get('amount_usdc', 0)
        price = trade_data.get('price', 0.5)
        
        outcome = trade_data.get('outcome', 'Unknown')
        side = trade_data.get('side', 'BUY').upper()
        
        # Build message (matching old format exactly)
        message_parts = [
            "🔥 *Smart Trader Alert*\n\n",
            f"📊 Market: {market_title}\n",
            f"🕐 Trade Time: {timestamp_str}\n\n",
            "Smart wallet just entered:\n"
        ]
        
        # Add wallet address if available (with Polymarket profile link)
        if shortened_wallet and wallet_address:
            profile_url = f"https://polymarket.com/profile/{wallet_address}"
            message_parts.append(f"👤 [{shortened_wallet}]({profile_url})\n")
        elif shortened_wallet:
            message_parts.append(f"👤 {shortened_wallet}\n")
        
        # Win rate and smart score
        if win_rate_pct is not None and smart_score is not None:
            message_parts.append(f"📊 Win Rate: {win_rate_pct:.1f}% | Smart Score: {smart_score:.1f}\n")
        elif win_rate_pct is not None:
            message_parts.append(f"📊 Win Rate: {win_rate_pct:.1f}%\n")
        elif smart_score is not None:
            message_parts.append(f"📊 Smart Score: {smart_score:.1f}\n")
        
        # Position
        message_parts.append(f"💰 Position: ${value:,.2f} @ ${price:.2f}\n")
        
        # Side
        message_parts.append(f"📈 Side: {side} {outcome}\n\n")
        
        # Confidence score
        message_parts.append(f"🎯 Confidence Score: {confidence_visual} {confidence_score}/10")
        
        message = "".join(message_parts)
        
        # Check message length (Telegram limit is 4096)
        if len(message) > 4000:
            logger.warning(f"⚠️ Message too long ({len(message)} chars), truncating market title")
            market_title = (trade_data.get('market_title', 'Unknown Market')[:80] + "...")
            market_title = escape_markdown(market_title)
            message_parts[1] = f"📊 Market: {market_title}\n"
            message = "".join(message_parts)
        
        return message
        
    except Exception as e:
        logger.error(f"❌ Error formatting alert message: {e}")
        # Fallback minimal message
        return f"🔥 *Smart Trader Alert*\n\nNew trade detected: {trade_data.get('trade_id', 'unknown')[:20]}..."

