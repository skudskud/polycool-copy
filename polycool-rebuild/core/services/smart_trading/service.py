"""
Smart Trading Service
Business logic for smart wallet trade recommendations
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_, desc, func

from core.database.connection import get_db
from core.database.models import Trade, WatchedAddress, Market
from core.services.cache_manager import CacheManager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class SmartTradingService:
    """
    Service for managing smart trading recommendations
    """

    # Default settings
    DEFAULT_MAX_AGE_MINUTES = 60
    DEFAULT_MIN_TRADE_VALUE = 300.0
    DEFAULT_MIN_WIN_RATE = 0.55
    DEFAULT_TRADES_LIMIT = 50

    # Redis keys for smart trading
    # Note: Global deduplication removed for pagination support
    # Each user session will handle its own deduplication

    # Cache key for recommendations (shared between API and bot)
    RECOMMENDATIONS_CACHE_KEY = "smart_trading:recommendations"
    RECOMMENDATIONS_CACHE_TTL = 30  # 30 seconds - short cache for fresh data

    def __init__(self):
        """Initialize service with cache manager"""
        self.cache_manager = CacheManager()

    async def get_recent_recommendations_cached(
        self,
        max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
        min_trade_value: float = DEFAULT_MIN_TRADE_VALUE,
        min_win_rate: float = DEFAULT_MIN_WIN_RATE,
        limit: int = DEFAULT_TRADES_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Get recent smart wallet trades with Redis caching for optimal performance

        This method uses shared Redis cache between API and bot to avoid redundant DB queries.
        Cache TTL is short (30s) to keep data fresh while reducing DB load.

        Args:
            max_age_minutes: Maximum age of trades to consider
            min_trade_value: Minimum USDC value for trades
            min_win_rate: Minimum win rate for smart wallets
            limit: Maximum number of trades to return

        Returns:
            List of trade dictionaries with wallet and market info
        """
        # Create cache key with parameters
        cache_key = f"{self.RECOMMENDATIONS_CACHE_KEY}:{max_age_minutes}:{min_trade_value}:{min_win_rate}:{limit}"

        # Try to get from cache first
        cached_result = await self.cache_manager.get(cache_key)
        if cached_result:
            logger.info("✅ Retrieved smart trading recommendations from Redis cache")
            return cached_result

        # Cache miss - compute fresh data
        logger.info("🔄 Computing fresh smart trading recommendations")
        result = await self.get_recent_recommendations(
            max_age_minutes=max_age_minutes,
            min_trade_value=min_trade_value,
            min_win_rate=min_win_rate,
            limit=limit
        )

        # Cache the result (only if we have data)
        if result:
            await self.cache_manager.set(cache_key, result, ttl=self.RECOMMENDATIONS_CACHE_TTL)
            logger.info(f"💾 Cached {len(result)} smart trading recommendations for {self.RECOMMENDATIONS_CACHE_TTL}s")

        return result

    async def get_recent_recommendations(
        self,
        max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
        min_trade_value: float = DEFAULT_MIN_TRADE_VALUE,
        min_win_rate: float = DEFAULT_MIN_WIN_RATE,
        limit: int = DEFAULT_TRADES_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Get recent smart wallet trades that can serve as recommendations

        OPTIMIZED VERSION: Single query with JOIN to avoid N+1 problem

        Args:
            max_age_minutes: Maximum age of trades to consider
            min_trade_value: Minimum USDC value for trades
            min_win_rate: Minimum win rate for smart wallets
            limit: Maximum number of trades to return

        Returns:
            List of trade dictionaries with wallet and market info
        """
        try:
            async with get_db() as db:
                # Calculate cutoff time (convert to naive datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE)
                cutoff_time_aware = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
                cutoff_time = cutoff_time_aware.replace(tzinfo=None)

                # Single optimized query with JOIN - eliminates N+1 problem
                # No global deduplication - pagination will handle session-level deduplication
                result = await db.execute(
                    select(
                        Trade.id,
                        Trade.market_id,
                        Trade.position_id,  # ✅ Include position_id
                        Trade.outcome,
                        Trade.trade_type,  # ✅ Include trade_type (buy/sell) for side display
                        Trade.amount,
                        Trade.price,
                        Trade.amount_usdc,
                        Trade.timestamp,
                        WatchedAddress.address,
                        WatchedAddress.name,
                        WatchedAddress.win_rate,
                        WatchedAddress.total_trades,
                        WatchedAddress.risk_score
                    )
                    .join(WatchedAddress, Trade.watched_address_id == WatchedAddress.id)
                    .where(
                        and_(
                            WatchedAddress.address_type == 'smart_wallet',
                            WatchedAddress.is_active == True,
                            WatchedAddress.win_rate >= min_win_rate,
                            Trade.trade_type == 'buy',
                            Trade.timestamp >= cutoff_time,
                            Trade.amount_usdc >= min_trade_value
                        )
                    )
                    .order_by(desc(Trade.timestamp))
                    .limit(limit)
                )

                rows = result.all()

                # ⚡ OPTIMIZATION: Batch resolve all market titles and outcomes in one query
                position_ids = [row[2] for row in rows if row[2]]  # position_id is at index 2
                market_title_map = {}
                outcome_map = {}  # ✅ Map position_id -> resolved outcome
                if position_ids:
                    market_title_map = await self.batch_resolve_market_titles(position_ids)
                    # ✅ Batch resolve outcomes for all position_ids (position_id is source of truth)
                    outcome_map = await self.batch_resolve_outcomes(position_ids)

                # Convert to dictionaries with pre-resolved market titles and outcomes
                recommendations = []
                filtered_by_price = 0
                filtered_by_title = 0

                for row in rows:
                    trade_id, market_id, position_id, outcome, trade_type, amount, price, amount_usdc, timestamp, \
                    address, name, win_rate, total_trades, risk_score = row

                    # Skip trades with price > 0.985 (early filter)
                    if price and float(price) > 0.985:
                        filtered_by_price += 1
                        continue

                    # ✅ Use pre-resolved market title from batch query
                    market_title = market_title_map.get(position_id) if position_id else None

                    # Skip trades without proper market title (no fallback display)
                    if not market_title:
                        filtered_by_title += 1
                        continue

                    # ✅ Resolve outcome from position_id (source of truth)
                    # Always use resolved outcome from position_id if available, fallback to DB value
                    resolved_outcome = outcome_map.get(position_id, outcome) if position_id else outcome

                    recommendations.append({
                        'trade_id': trade_id,
                        'market_id': market_id,
                        'position_id': position_id,  # ✅ Include position_id
                        'outcome': resolved_outcome,  # ✅ Use resolved outcome
                        'side': trade_type.upper() if trade_type else 'BUY',  # ✅ Include side (BUY/SELL)
                        'amount': float(amount),
                        'price': float(price) if price else None,
                        'value': float(amount_usdc) if amount_usdc else None,
                        'timestamp': timestamp.isoformat() if timestamp else None,  # Convert datetime to string for JSON
                        'wallet_address': address,
                        'wallet_address_short': address[:8] if address else None,
                        'wallet_name': name or f"Smart Trader {address[:8] if address else 'Unknown'}",
                        'market_title': market_title,  # ✅ Resolved market title
                        'win_rate': float(win_rate) if win_rate is not None else None,
                        'total_trades': int(total_trades) if total_trades is not None else None,
                        'risk_score': float(risk_score) if risk_score is not None else None
                    })

                logger.info(
                    f"✅ Retrieved {len(recommendations)} smart trading recommendations "
                    f"(filtered {filtered_by_price} by price > 0.985, {filtered_by_title} by missing title, "
                    f"from {len(rows)} raw trades)"
                )
                return recommendations

        except Exception as e:
            logger.error(f"❌ Error getting smart trading recommendations: {e}")
            return []

    async def get_paginated_recommendations(
        self,
        page: int = 1,
        per_page: int = 5,
        max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
        min_trade_value: float = DEFAULT_MIN_TRADE_VALUE,
        min_win_rate: float = DEFAULT_MIN_WIN_RATE
    ) -> Dict[str, Any]:
        """
        Get paginated smart trading recommendations

        Args:
            page: Page number (1-indexed)
            per_page: Number of trades per page
            max_age_minutes: Maximum age of trades
            min_trade_value: Minimum USDC value
            min_win_rate: Minimum win rate

        Returns:
            Dictionary with trades, pagination info, and metadata
        """
        try:
            # Get all recommendations using cached version (limited to 50 max)
            all_trades = await self.get_recent_recommendations_cached(
                max_age_minutes=max_age_minutes,
                min_trade_value=min_trade_value,
                min_win_rate=min_win_rate,
                limit=50  # Max 50 trades (10 pages)
            )

            # Calculate pagination
            total_trades = len(all_trades)
            total_pages = (total_trades + per_page - 1) // per_page
            page = max(1, min(page, total_pages))

            # Get page data
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            page_trades = all_trades[start_idx:end_idx]

            return {
                'trades': page_trades,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_trades': total_trades,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1
                },
                'filters': {
                    'max_age_minutes': max_age_minutes,
                    'min_trade_value': min_trade_value,
                    'min_win_rate': min_win_rate
                }
            }

        except Exception as e:
            logger.error(f"❌ Error getting paginated recommendations: {e}")
            return {
                'trades': [],
                'pagination': {
                    'page': 1,
                    'per_page': per_page,
                    'total_trades': 0,
                    'total_pages': 0,
                    'has_next': False,
                    'has_prev': False
                },
                'filters': {
                    'max_age_minutes': max_age_minutes,
                    'min_trade_value': min_trade_value,
                    'min_win_rate': min_win_rate
                }
            }

    async def validate_smart_wallet(self, address: str) -> Dict[str, Any]:
        """
        Validate if an address is a valid smart wallet and get its stats

        Args:
            address: Wallet address to validate

        Returns:
            Dictionary with validation result and wallet stats
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress).where(
                        and_(
                            WatchedAddress.address == address.lower(),
                            WatchedAddress.address_type == 'smart_wallet',
                            WatchedAddress.is_active == True
                        )
                    )
                )
                wallet = result.scalar_one_or_none()

                if not wallet:
                    return {
                        'is_valid': False,
                        'reason': 'Address not found in smart wallets'
                    }

                return {
                    'is_valid': True,
                    'wallet': {
                        'address': wallet.address,
                        'name': wallet.name,
                        'win_rate': wallet.win_rate,
                        'total_trades': wallet.total_trades,
                        'risk_score': wallet.risk_score,
                        'is_active': wallet.is_active
                    }
                }

        except Exception as e:
            logger.error(f"❌ Error validating smart wallet {address}: {e}")
            return {
                'is_valid': False,
                'reason': f'Validation error: {str(e)}'
            }

    async def get_smart_wallet_stats(self) -> Dict[str, Any]:
        """
        Get overall statistics about smart wallets

        Returns:
            Dictionary with various statistics
        """
        try:
            async with get_db() as db:
                # Count active smart traders
                result = await db.execute(
                    select(func.count(WatchedAddress.id)).where(
                        and_(
                            WatchedAddress.address_type == 'smart_wallet',
                            WatchedAddress.is_active == True
                        )
                    )
                )
                total_wallets = result.scalar()

                # Average win rate
                result = await db.execute(
                    select(func.avg(WatchedAddress.win_rate)).where(
                        and_(
                            WatchedAddress.address_type == 'smart_wallet',
                            WatchedAddress.is_active == True,
                            WatchedAddress.win_rate.isnot(None)
                        )
                    )
                )
                avg_win_rate = result.scalar() or 0.0

                # Total trades in last 24h
                yesterday = datetime.now(timezone.utc) - timedelta(days=1)
                result = await db.execute(
                    select(func.count(Trade.id))
                    .join(WatchedAddress, Trade.watched_address_id == WatchedAddress.id)
                    .where(
                        and_(
                            WatchedAddress.address_type == 'smart_wallet',
                            WatchedAddress.is_active == True,
                            Trade.timestamp >= yesterday.replace(tzinfo=None)  # Convert to offset-naive
                        )
                    )
                )
                recent_trades = result.scalar()

                return {
                    'total_smart_wallets': total_wallets,
                    'average_win_rate': float(avg_win_rate),
                    'recent_trades_24h': recent_trades
                }

        except Exception as e:
            logger.error(f"❌ Error getting smart wallet stats: {e}")
            return {
                'total_smart_wallets': 0,
                'average_win_rate': 0.0,
                'recent_trades_24h': 0
            }

    async def batch_resolve_market_titles(self, position_ids: List[str]) -> Dict[str, str]:
        """
        Batch resolve market titles for multiple position_ids using individual queries

        Args:
            position_ids: List of position IDs to resolve

        Returns:
            Dictionary mapping position_id to market title
        """
        if not position_ids:
            return {}

        try:
            # Use individual queries to avoid complex OR conditions with JSONB
            title_map = {}

            async with get_db() as db:
                for position_id in position_ids:
                    try:
                        result = await db.execute(
                            select(Market.title).where(
                                Market.is_active == True,
                                Market.clob_token_ids.op('@>')([position_id])
                            ).limit(1)
                        )

                        market = result.first()
                        if market:
                            title_map[position_id] = market.title

                    except Exception as e:
                        logger.warning(f"Failed to resolve title for position_id {position_id}: {e}")
                        continue

            logger.debug(f"✅ Batch resolved {len(title_map)} market titles for {len(position_ids)} position_ids")
            return title_map

        except Exception as e:
            logger.error(f"❌ Error batch resolving market titles: {e}")
            return {}

    async def batch_resolve_outcomes(self, position_ids: List[str]) -> Dict[str, str]:
        """
        Batch resolve outcomes for multiple position_ids using clob_token_ids array in markets table

        Args:
            position_ids: List of position IDs (clob_token_ids) to resolve

        Returns:
            Dictionary mapping position_id to resolved outcome
        """
        if not position_ids:
            return {}

        try:
            outcome_map = {}

            async with get_db() as db:
                for position_id in position_ids:
                    try:
                        # Find market containing this position_id in clob_token_ids
                        result = await db.execute(
                            select(Market).where(
                                Market.is_active == True,
                                Market.clob_token_ids.op('@>')([position_id])
                            ).limit(1)
                        )

                        market = result.scalar_one_or_none()
                        if not market:
                            continue

                        # Find index of position_id in clob_token_ids array
                        clob_token_ids = market.clob_token_ids or []
                        outcomes = market.outcomes or []

                        if not clob_token_ids or not outcomes:
                            continue

                        # Find the index
                        try:
                            outcome_index = clob_token_ids.index(position_id)
                        except (ValueError, AttributeError):
                            # Try string comparison if index() fails
                            outcome_index = -1
                            for i, token_id in enumerate(clob_token_ids):
                                if str(token_id) == str(position_id):
                                    outcome_index = i
                                    break

                        if outcome_index >= 0 and outcome_index < len(outcomes):
                            outcome_map[position_id] = outcomes[outcome_index]

                    except Exception as e:
                        logger.warning(f"Failed to resolve outcome for position_id {position_id[:20]}...: {e}")
                        continue

            logger.debug(f"✅ Batch resolved {len(outcome_map)} outcomes for {len(position_ids)} position_ids")
            return outcome_map

        except Exception as e:
            logger.error(f"❌ Error batch resolving outcomes: {e}")
            return {}

    async def resolve_market_by_position_id(self, position_id: str) -> Optional[Dict[str, Any]]:
        """
        Resolve market information using position_id (clob_token_id)
        DEPRECATED: Use batch_resolve_market_titles for better performance

        Args:
            position_id: Token ID from blockchain

        Returns:
            Market information dict or None if not found
        """
        if not position_id:
            return None

        try:
            async with get_db() as db:
                # Query markets table for market containing this position_id in clob_token_ids
                # Use JSONB @> operator for array containment (more reliable than contains)
                from sqlalchemy import func
                from sqlalchemy.dialects.postgresql import JSONB

                result = await db.execute(
                    select(Market).where(
                        Market.is_active == True,
                        # Use @> operator for JSONB array containment
                        Market.clob_token_ids.op('@>')([position_id])
                    ).limit(1)
                )

                market = result.scalar_one_or_none()
                if not market:
                    logger.debug(f"❌ No market found for position_id {position_id[:20]}...")
                    return None

                # Find the outcome index for this position_id
                if not market.clob_token_ids or not isinstance(market.clob_token_ids, list):
                    logger.warning(f"⚠️ No clob_token_ids array in market {market.id}")
                    return None

                try:
                    # Find index of position_id in clob_token_ids array
                    outcome_index = market.clob_token_ids.index(position_id)
                except ValueError:
                    logger.warning(f"⚠️ position_id {position_id[:20]}... not found in market {market.id} clob_token_ids")
                    return None

                # Get outcome from outcomes array using the index
                outcomes = market.outcomes or []
                if outcome_index >= len(outcomes):
                    logger.warning(f"⚠️ outcome_index {outcome_index} out of range for market {market.id} outcomes (len={len(outcomes)})")
                    return None

                outcome_str = outcomes[outcome_index]

                return {
                    'id': market.id,
                    'title': market.title,
                    'outcome_index': outcome_index,
                    'outcome': outcome_str  # Use exact outcome from market's outcomes array
                }

        except Exception as e:
            logger.error(f"❌ Error resolving market by position_id {position_id[:20]}...: {e}")
            return None
