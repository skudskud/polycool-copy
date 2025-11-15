"""
Database operations for Alert Channel Bot
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from config import settings

logger = logging.getLogger(__name__)

# Create async engine for database operations
_async_engine = None
_async_session_maker = None


def get_async_engine():
    """Get or create async database engine"""
    global _async_engine
    if _async_engine is None:
        # Convert postgresql:// to postgresql+asyncpg:// for async operations
        db_url = settings.database_url
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        _async_engine = create_async_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=False
        )
        logger.info("✅ Database async engine created")
    return _async_engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Get or create async session maker"""
    global _async_session_maker
    if _async_session_maker is None:
        engine = get_async_engine()
        _async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    return _async_session_maker


async def check_trade_sent(trade_id: str) -> bool:
    """
    Check if a trade has already been sent to alert channel
    
    Args:
        trade_id: Trade ID from trades table
        
    Returns:
        True if already sent, False otherwise
    """
    try:
        session_maker = get_async_session()
        async with session_maker() as session:
            result = await session.execute(
                text("SELECT 1 FROM alert_channel_sent WHERE trade_id = :trade_id LIMIT 1"),
                {"trade_id": trade_id}
            )
            return result.fetchone() is not None
    except Exception as e:
        logger.error(f"❌ Error checking if trade sent: {e}")
        return False


async def mark_trade_sent(trade_id: str) -> bool:
    """
    Mark a trade as sent to alert channel
    
    Args:
        trade_id: Trade ID from trades table
        
    Returns:
        True if successful, False otherwise
    """
    try:
        session_maker = get_async_session()
        async with session_maker() as session:
            await session.execute(
                text("""
                    INSERT INTO alert_channel_sent (trade_id, sent_at, created_at)
                    VALUES (:trade_id, :sent_at, :created_at)
                    ON CONFLICT (trade_id) DO NOTHING
                """),
                {
                    "trade_id": trade_id,
                    "sent_at": datetime.now(timezone.utc),
                    "created_at": datetime.now(timezone.utc)
                }
            )
            await session.commit()
            logger.debug(f"✅ Marked trade {trade_id[:20]}... as sent")
            return True
    except Exception as e:
        logger.error(f"❌ Error marking trade as sent: {e}")
        return False


async def save_alert_history(
    trade_id: str,
    market_id: Optional[str],
    market_title: Optional[str],
    wallet_address: Optional[str],
    wallet_name: Optional[str],
    win_rate: Optional[float],
    smart_score: Optional[float],
    confidence_score: Optional[int],
    outcome: Optional[str],
    side: Optional[str],
    price: Optional[float],
    value: Optional[float],
    amount_usdc: Optional[float],
    message_text: Optional[str]
) -> bool:
    """
    Save alert history to database
    
    Args:
        All trade and message details
        
    Returns:
        True if successful, False otherwise
    """
    try:
        session_maker = get_async_session()
        async with session_maker() as session:
            await session.execute(
                text("""
                    INSERT INTO alert_channel_history (
                        trade_id, market_id, market_title, wallet_address, wallet_name,
                        win_rate, smart_score, confidence_score, outcome, side,
                        price, value, amount_usdc, message_text, sent_at, created_at
                    )
                    VALUES (
                        :trade_id, :market_id, :market_title, :wallet_address, :wallet_name,
                        :win_rate, :smart_score, :confidence_score, :outcome, :side,
                        :price, :value, :amount_usdc, :message_text, :sent_at, :created_at
                    )
                """),
                {
                    "trade_id": trade_id,
                    "market_id": market_id,
                    "market_title": market_title,
                    "wallet_address": wallet_address,
                    "wallet_name": wallet_name,
                    "win_rate": win_rate,
                    "smart_score": smart_score,
                    "confidence_score": confidence_score,
                    "outcome": outcome,
                    "side": side,
                    "price": price,
                    "value": value,
                    "amount_usdc": amount_usdc,
                    "message_text": message_text,
                    "sent_at": datetime.now(timezone.utc),
                    "created_at": datetime.now(timezone.utc)
                }
            )
            await session.commit()
            logger.debug(f"✅ Saved alert history for trade {trade_id[:20]}...")
            return True
    except Exception as e:
        logger.error(f"❌ Error saving alert history: {e}")
        return False


async def get_recent_qualified_trades(max_age_minutes: int = 5) -> List[Dict[str, Any]]:
    """
    Get recent qualified trades from database (for polling fallback)
    
    Args:
        max_age_minutes: Maximum age of trades to consider
        
    Returns:
        List of trade dictionaries
    """
    try:
        session_maker = get_async_session()
        async with session_maker() as session:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
            
            result = await session.execute(
                text("""
                    SELECT 
                        t.id as trade_id,
                        t.market_id,
                        t.position_id,
                        t.outcome,
                        t.trade_type,
                        t.amount,
                        t.price,
                        t.amount_usdc,
                        t.timestamp,
                        wa.address as wallet_address,
                        wa.name as wallet_name,
                        wa.win_rate,
                        wa.risk_score,
                        m.title as market_title
                    FROM trades t
                    INNER JOIN watched_addresses wa ON t.watched_address_id = wa.id
                    LEFT JOIN markets m ON t.market_id = m.id
                    WHERE 
                        wa.address_type = 'smart_wallet'
                        AND wa.is_active = true
                        AND wa.win_rate >= :min_win_rate
                        AND t.trade_type = 'buy'
                        AND t.timestamp >= :cutoff_time
                        AND t.amount_usdc >= :min_trade_value
                        AND NOT EXISTS (
                            SELECT 1 FROM alert_channel_sent acs WHERE acs.trade_id = t.id
                        )
                    ORDER BY t.timestamp DESC
                    LIMIT 50
                """),
                {
                    "min_win_rate": settings.min_win_rate,
                    "cutoff_time": cutoff_time,
                    "min_trade_value": settings.min_trade_value
                }
            )
            
            rows = result.fetchall()
            trades = []
            for row in rows:
                trades.append({
                    "trade_id": row[0],
                    "market_id": row[1],
                    "position_id": row[2],
                    "outcome": row[3],
                    "side": row[4],
                    "amount": float(row[5]) if row[5] else None,
                    "price": float(row[6]) if row[6] else None,
                    "value": float(row[7]) if row[7] else None,
                    "timestamp": row[8],
                    "wallet_address": row[9],
                    "wallet_name": row[10],
                    "win_rate": float(row[11]) if row[11] else None,
                    "risk_score": float(row[12]) if row[12] else None,
                    "market_title": row[13]
                })
            
            logger.info(f"✅ Retrieved {len(trades)} qualified trades from database")
            return trades
            
    except Exception as e:
        logger.error(f"❌ Error getting recent qualified trades: {e}")
        return []

