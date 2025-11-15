"""
Market Service - Market data retrieval and management
Unified service for fetching markets from Supabase with caching
"""
import os
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func, or_, and_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.models import Market
from core.database.connection import get_db
from core.services.cache_manager import CacheManager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if service has DB access
# Note: Service API should have SKIP_DB=false, but we check anyway
SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"


def _normalize_category(raw_category: str) -> str:
    """
    Normalize Polymarket categories to our 5 simplified categories

    Args:
        raw_category: Raw category from Polymarket

    Returns:
        Normalized category: Geopolitics, Sports, Finance, Crypto, or Other
    """
    if not raw_category:
        return "Other"

    cat_lower = raw_category.lower()

    # Geopolitics mapping
    if any(keyword in cat_lower for keyword in [
        'politic', 'election', 'government', 'war', 'international',
        'geopolitic', 'trump', 'biden', 'congress', 'senate'
    ]):
        return "Geopolitics"

    # Sports mapping
    if any(keyword in cat_lower for keyword in [
        'sport', 'nba', 'nfl', 'mlb', 'nhl', 'soccer', 'football',
        'baseball', 'basketball', 'esport', 'olympics', 'championship'
    ]):
        return "Sports"

    # Crypto mapping
    if any(keyword in cat_lower for keyword in [
        'crypto', 'bitcoin', 'ethereum', 'blockchain', 'nft', 'defi', 'web3'
    ]):
        return "Crypto"

    # Finance mapping
    if any(keyword in cat_lower for keyword in [
        'business', 'finance', 'econom', 'stock', 'fed', 'market',
        'company', 'ipo', 'interest rate'
    ]):
        return "Finance"

    # Default to Other
    return "Other"


def _market_to_dict(market: Market) -> Dict:
    """Convert Market model to dictionary"""
    return {
        'id': market.id,
        'title': market.title,
        'description': market.description,
        'category': market.category,
        'outcomes': market.outcomes,
        'outcome_prices': market.outcome_prices,
        'events': market.events,
        'is_event_market': market.is_event_market,
        'parent_event_id': market.parent_event_id,
        'event_id': market.event_id,
        'event_slug': market.event_slug,
        'event_title': market.event_title,
        'polymarket_url': market.polymarket_url,
        'volume': float(market.volume) if market.volume else 0.0,
        'liquidity': float(market.liquidity) if market.liquidity else 0.0,
        'last_trade_price': float(market.last_trade_price) if market.last_trade_price else None,
        'last_mid_price': float(market.last_mid_price) if market.last_mid_price else None,
        'clob_token_ids': market.clob_token_ids,
        'condition_id': market.condition_id,
        'is_resolved': market.is_resolved,
        'resolved_outcome': market.resolved_outcome,
        'resolved_at': market.resolved_at.isoformat() if market.resolved_at else None,
        'start_date': market.start_date.isoformat() if market.start_date else None,
        'end_date': market.end_date.isoformat() if market.end_date else None,
        'is_active': market.is_active,
        'source': market.source,
    }


def _is_market_valid(market: Market) -> bool:
    """
    Validate market for display (filter out illiquid/resolved markets)

    Args:
        market: Market model instance

    Returns:
        True if market is valid for display
    """
    # Must be active
    if not market.is_active:
        return False

    # Must not be resolved
    if market.is_resolved:
        return False

    # Must have end date in future
    if market.end_date:
        # Note: end_date is stored as timestamp without time zone in UTC
        # Compare directly with UTC time (no offset needed as end_date is already in UTC)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if market.end_date < now:
            return False

    # Must have minimum liquidity (filter out dead markets)
    if market.liquidity and market.liquidity < 100:
        return False

    return True


class MarketService:
    """
    Market Service - Unified market data access
    Uses Supabase markets table directly with caching
    """

    def __init__(self, cache_manager: Optional[CacheManager] = None):
        """Initialize MarketService"""
        self.cache_manager = cache_manager
        logger.info("MarketService initialized")

    async def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """
        Get market by ID

        Args:
            market_id: Market identifier

        Returns:
            Market dictionary or None if not found
        """
        # Try cache first
        if self.cache_manager:
            cache_key = f"market_detail:{market_id}"
            cached = await self.cache_manager.get(cache_key, 'market_detail')
            if cached:
                logger.debug(f"Cache hit: market {market_id}")
                return cached

        # Fetch from database
        async with get_db() as db:
            result = await db.execute(
                select(Market).where(Market.id == market_id)
            )
            market = result.scalar_one_or_none()

            if not market:
                return None

            market_dict = _market_to_dict(market)

            # Cache result
            if self.cache_manager:
                cache_key = f"market_detail:{market_id}"
                await self.cache_manager.set(cache_key, market_dict, 'market_detail')

            return market_dict

    async def get_market_by_condition_id(self, condition_id: str) -> Optional[Dict]:
        """
        Get market by condition_id (used by WebSocket streamer)

        Args:
            condition_id: Condition ID (hash hex from Polymarket WebSocket)

        Returns:
            Market dictionary or None if not found
        """
        # Try cache first (using condition_id as key)
        if self.cache_manager:
            cache_key = f"market_by_condition:{condition_id}"
            cached = await self.cache_manager.get(cache_key, 'market_detail')
            if cached:
                logger.debug(f"Cache hit: market by condition_id {condition_id[:20]}...")
                return cached

        # Fetch from database
        logger.debug(f"Querying DB for condition_id: {condition_id[:30]}...")

        if SKIP_DB:
            logger.error(f"MarketService cannot access DB when SKIP_DB=true! Service API should have SKIP_DB=false")
            return None

        async with get_db() as db:
            result = await db.execute(
                select(Market).where(Market.condition_id == condition_id)
            )
            market = result.scalar_one_or_none()

            if not market:
                # Try case-insensitive search as fallback
                logger.debug(f"Market not found by condition_id (exact match), trying case-insensitive...")
                result = await db.execute(
                    select(Market).where(Market.condition_id.ilike(condition_id))
                )
                market = result.scalar_one_or_none()

                if not market:
                    logger.debug(f"Market not found by condition_id (case-insensitive): {condition_id[:30]}...")
                    return None

            market_dict = _market_to_dict(market)

            # Cache result (both by condition_id and market_id for faster lookups)
            if self.cache_manager:
                cache_key_condition = f"market_by_condition:{condition_id}"
                cache_key_id = f"market_detail:{market_dict['id']}"
                await self.cache_manager.set(cache_key_condition, market_dict, 'market_detail')
                await self.cache_manager.set(cache_key_id, market_dict, 'market_detail')

            return market_dict

    async def get_market_by_token_id(self, token_id: str) -> Optional[Dict]:
        """
        Get market by token_id (CLOB token ID)

        Args:
            token_id: CLOB token ID

        Returns:
            Market dictionary or None if not found
        """
        # Try cache first
        if self.cache_manager:
            cache_key = f"market_by_token:{token_id}"
            cached = await self.cache_manager.get(cache_key, 'market_detail')
            if cached:
                logger.debug(f"Cache hit: market by token_id {token_id[:20]}...")
                return cached

        # Fetch from database
        logger.debug(f"Querying DB for token_id: {token_id[:30]}...")

        if SKIP_DB:
            logger.error(f"MarketService cannot access DB when SKIP_DB=true! Service API should have SKIP_DB=false")
            return None

        async with get_db() as db:
            result = await db.execute(
                select(Market).where(
                    Market.clob_token_ids.contains([token_id])
                )
            )
            market = result.scalar_one_or_none()

            if not market:
                logger.debug(f"Market not found by token_id, trying with string token_id...")
                result = await db.execute(
                    select(Market).where(
                        Market.clob_token_ids.contains([str(token_id)])
                    )
                )
                market = result.scalar_one_or_none()

                if not market:
                    logger.debug(f"Market not found by token_id: {token_id[:30]}...")
                    return None

            market_dict = _market_to_dict(market)

            # Cache result
            if self.cache_manager:
                cache_key_token = f"market_by_token:{token_id}"
                cache_key_id = f"market_detail:{market_dict['id']}"
                await self.cache_manager.set(cache_key_token, market_dict, 'market_detail')
                await self.cache_manager.set(cache_key_id, market_dict, 'market_detail')

            return market_dict

    async def get_trending_markets(
        self,
        page: int = 0,
        page_size: int = 10,
        group_by_events: bool = True,
        filter_type: str = 'volume'
    ) -> Tuple[List[Dict], int]:
        """
        Get trending markets (high volume) with pagination

        Args:
            page: Page number (0-indexed)
            page_size: Markets per page
            group_by_events: If True, groups markets by events
            filter_type: Sort order ('volume', 'liquidity', 'newest', 'endingsoon')

        Returns:
            (markets_list, total_count) tuple
        """
        cache_key = f"trending_grouped:{page}" if group_by_events else f"trending:{page}"

        # Try cache first
        if self.cache_manager:
            cached = await self.cache_manager.get(cache_key, 'markets_list')
            if cached:
                logger.debug(f"Cache hit: trending page {page}")
                return cached, -1

        # Fetch from database
        async with get_db() as db:
            # Build query for active markets ordered by volume
            # Note: end_date is stored as timestamp without time zone in UTC
            # Compare directly with UTC time (no offset needed as end_date is already in UTC)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            query = select(Market).where(
                and_(
                    Market.is_active == True,
                    Market.is_resolved == False,
                    Market.end_date > now
                )
            )
            # Apply sorting based on filter_type
            if filter_type == 'volume':
                query = query.order_by(desc(Market.volume))
            elif filter_type == 'liquidity':
                query = query.order_by(desc(Market.liquidity))
            elif filter_type == 'newest':
                query = query.order_by(desc(Market.created_at))
            elif filter_type == 'endingsoon':
                query = query.order_by(asc(Market.end_date))
            else:
                # Default to volume
                query = query.order_by(desc(Market.volume))

            # For grouped events, fetch all markets once, group them, then paginate on groups
            # This ensures we can accurately detect if there are more pages
            if group_by_events:
                # Fetch a large batch to get all available groups
                # We'll cache the grouped results and paginate from cache
                cache_key_groups = "trending_all_groups"

                # Try to get cached groups first
                all_groups = None
                if self.cache_manager:
                    cached_groups = await self.cache_manager.get(cache_key_groups, 'markets_list')
                    if cached_groups:
                        logger.debug(f"Cache hit: all trending groups")
                        all_groups = cached_groups

                if all_groups is None:
                    # Fetch markets (enough to get all groups)
                    fetch_limit = 2000  # Fetch enough markets to get all groups
                    query_all = query.limit(fetch_limit)

                    result = await db.execute(query_all)
                    all_markets = result.scalars().all()

                    # Filter and convert to dicts
                    valid_markets = [m for m in all_markets if _is_market_valid(m)]
                    market_dicts = [_market_to_dict(m) for m in valid_markets]

                    # Group by events
                    all_groups = self._group_markets_by_events(market_dicts)

                    # Cache all groups for 5 minutes
                    if self.cache_manager:
                        await self.cache_manager.set(cache_key_groups, all_groups, 'markets_list', ttl=300)

                # Apply pagination on groups
                start_idx = page * page_size
                end_idx = start_idx + page_size
                display_items = all_groups[start_idx:end_idx]

                # Return total count for accurate pagination
                total_groups = len(all_groups)
            else:
                # For individual markets, use standard pagination
                query = query.limit(page_size).offset(page * page_size)
                result = await db.execute(query)
                all_markets = result.scalars().all()

                # Filter and convert to dicts
                valid_markets = [m for m in all_markets if _is_market_valid(m)]
                market_dicts = [_market_to_dict(m) for m in valid_markets]

                display_items = market_dicts
                total_groups = -1  # Unknown for individual markets

            # Cache result
            if self.cache_manager:
                await self.cache_manager.set(cache_key, display_items, 'markets_list')

            # Return total count if we have it (for grouped events)
            total_count = total_groups if group_by_events else -1
            return display_items, total_count

    async def get_category_markets(
        self,
        category: str,
        page: int = 0,
        page_size: int = 10,
        group_by_events: bool = True,
        filter_type: str = 'volume'
    ) -> Tuple[List[Dict], int]:
        """
        Get markets by category with pagination

        Args:
            category: Category name (Geopolitics, Sports, Finance, Crypto, Other)
            page: Page number (0-indexed)
            page_size: Markets per page
            group_by_events: If True, groups markets by events
            filter_type: Sort order ('volume', 'liquidity', 'newest', 'endingsoon')

        Returns:
            (markets_list, total_count) tuple
        """
        cache_key = f"category_{category.lower()}_by_title:{page}" if group_by_events else f"category_{category.lower()}:{page}"

        # Try cache first
        if self.cache_manager:
            cached = await self.cache_manager.get(cache_key, 'markets_list')
            if cached:
                logger.debug(f"Cache hit: category {category} page {page}")
                return cached, -1

        # Fetch from database
        async with get_db() as db:
            # Note: end_date is stored as timestamp without time zone in UTC
            # Compare directly with UTC time (no offset needed as end_date is already in UTC)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            query = select(Market).where(
                and_(
                    Market.is_active == True,
                    Market.is_resolved == False,
                    Market.end_date > now,
                    Market.category == category
                )
            )
            # Apply sorting based on filter_type
            if filter_type == 'volume':
                query = query.order_by(desc(Market.volume))
            elif filter_type == 'liquidity':
                query = query.order_by(desc(Market.liquidity))
            elif filter_type == 'newest':
                query = query.order_by(desc(Market.created_at))
            elif filter_type == 'endingsoon':
                query = query.order_by(asc(Market.end_date))
            else:
                # Default to volume
                query = query.order_by(desc(Market.volume))

            # For grouped events, we need more markets to ensure enough groups after pagination
            fetch_limit = page_size * 50 if group_by_events else page_size
            query = query.limit(fetch_limit)

            result = await db.execute(query)
            all_markets = result.scalars().all()

            # Filter and convert to dicts
            valid_markets = [m for m in all_markets if _is_market_valid(m)]
            market_dicts = [_market_to_dict(m) for m in valid_markets]

            # Group by events if requested
            if group_by_events:
                all_groups = self._group_markets_by_events(market_dicts)
                # Apply pagination on groups
                start_idx = page * page_size
                end_idx = start_idx + page_size
                display_items = all_groups[start_idx:end_idx]
            else:
                # Apply pagination on individual markets
                start_idx = page * page_size
                end_idx = start_idx + page_size
                display_items = market_dicts[start_idx:end_idx]

            # Cache result
            if self.cache_manager:
                await self.cache_manager.set(cache_key, display_items, 'markets_list')

            return display_items, -1

    async def search_markets(
        self,
        query_text: str,
        page: int = 0,
        page_size: int = 10,
        group_by_events: bool = True
    ) -> Tuple[List[Dict], int]:
        """
        Search markets by title (all terms must be in title)

        Args:
            query_text: Search query (supports multiple words with AND logic - all terms must be in title)
            page: Page number (0-indexed)
            page_size: Markets per page
            group_by_events: If True, groups markets by events

        Returns:
            (markets_list, total_count) tuple
        """
        cache_key = f"search:{query_text.lower()}:{page}:{group_by_events}"

        # Try cache first
        if self.cache_manager:
            cached = await self.cache_manager.get(cache_key, 'markets_list')
            if cached:
                logger.debug(f"Cache hit: search '{query_text}' page {page}")
                # Try to get total_count from separate cache key
                total_count_key = f"search_total:{query_text.lower()}:{group_by_events}"
                total_count_cached = await self.cache_manager.get(total_count_key, 'metadata')
                total_count = total_count_cached if total_count_cached is not None else -1
                return cached, total_count

        # Fetch from database
        async with get_db() as db:
            # Note: end_date is stored as timestamp without time zone in UTC
            # Compare directly with UTC time (no offset needed as end_date is already in UTC)
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            # Parse query for multiple words (AND logic)
            search_terms = self._parse_search_query(query_text)

            if not search_terms:
                return [], 0

            # Build WHERE conditions
            base_conditions = [
                Market.is_active == True,
                Market.is_resolved == False,
                Market.end_date > now
            ]

            # Add search conditions for each term - ALL terms must be in title
            # This ensures "Bitcoin 1" matches "Bitcoin Up or Down - November 14, 1PM ET"
            # but NOT "Will Bitcoin reach $200,000 in November?" (missing "1")
            search_conditions = []
            for term in search_terms:
                term_pattern = f"%{term}%"
                # All terms must be in the title (not description)
                search_conditions.append(Market.title.ilike(term_pattern))

            # Combine all conditions - ALL search terms must match
            base_query = select(Market).where(
                and_(
                    *base_conditions,
                    *search_conditions
                )
            ).order_by(desc(Market.volume))

            # For grouped events, we need to fetch all matching markets first, group them, then paginate
            if group_by_events:
                # Fetch a large batch to get all matching groups
                fetch_limit = 2000  # Fetch enough markets to get all groups
                query_all = base_query.limit(fetch_limit)

                result = await db.execute(query_all)
                all_markets = result.scalars().all()

                # Filter and convert to dicts
                valid_markets = [m for m in all_markets if _is_market_valid(m)]
                market_dicts = [_market_to_dict(m) for m in valid_markets]

                # Group by events
                all_groups = self._group_markets_by_events(market_dicts)

                # Cache all groups for 5 minutes
                cache_key_groups = f"search_all_groups:{query_text.lower()}:{group_by_events}"
                if self.cache_manager:
                    await self.cache_manager.set(cache_key_groups, all_groups, 'markets_list', ttl=300)

                # Apply pagination on groups
                start_idx = page * page_size
                end_idx = start_idx + page_size
                display_items = all_groups[start_idx:end_idx]

                # Return total count for accurate pagination
                total_groups = len(all_groups)

                # Cache total count separately
                if self.cache_manager:
                    total_count_key = f"search_total:{query_text.lower()}:{group_by_events}"
                    await self.cache_manager.set(total_count_key, total_groups, 'metadata', ttl=300)

                # Cache paginated result
                if self.cache_manager:
                    await self.cache_manager.set(cache_key, display_items, 'markets_list', ttl=300)

                return display_items, total_groups
            else:
                # For individual markets, use standard pagination
                query = base_query.limit(page_size).offset(page * page_size)
                result = await db.execute(query)
                markets = result.scalars().all()

                # Filter and convert to dicts
                valid_markets = [m for m in markets if _is_market_valid(m)]
                market_dicts = [_market_to_dict(m) for m in valid_markets]

                # Cache result (longer TTL for search to reduce DB load)
                if self.cache_manager:
                    await self.cache_manager.set(cache_key, market_dicts, 'markets_list', ttl=300)  # 5 minutes

                return market_dicts, -1

    def _parse_search_query(self, query_text: str) -> List[str]:
        """
        Parse search query into individual terms for AND search

        Args:
            query_text: Raw search query

        Returns:
            List of search terms (minimum 1 character each)
        """
        if not query_text:
            return []

        # Split by whitespace and filter out empty terms
        terms = [term.strip() for term in query_text.split() if term.strip()]

        # Filter terms that are too short (less than 1 character after stripping)
        valid_terms = [term for term in terms if len(term) >= 1]

        # Remove duplicates while preserving order
        seen = set()
        unique_terms = []
        for term in valid_terms:
            term_lower = term.lower()
            if term_lower not in seen:
                seen.add(term_lower)
                unique_terms.append(term)

        return unique_terms

    def _group_markets_by_events(self, markets: List[Dict]) -> List[Dict]:
        """
        Group markets by events (parent-enfant relationship)
        Groups by event_title since most markets have event_id=null but event_title set

        Args:
            markets: List of market dictionaries

        Returns:
            List of display items (event groups or individual markets)
        """
        # Group markets by event_title (much more reliable than event_id)
        event_groups = {}
        individual_markets = []

        for market in markets:
            event_title = market.get('event_title')

            if event_title:
                # Group all markets by event_title
                if event_title not in event_groups:
                    event_groups[event_title] = {
                        'type': 'event_group',
                        'event_title': event_title,
                        'event_id': market.get('event_id'),  # May be null, that's ok
                        'event_slug': market.get('event_slug'),  # May be null, that's ok
                        'markets': []
                    }
                event_groups[event_title]['markets'].append(market)
            else:
                # Market without event_title - treat as individual
                individual_markets.append({
                    'type': 'individual',
                    **market
                })

        # Convert event_groups to display items
        display_items = []

        for event_title, group in event_groups.items():
            if len(group['markets']) > 1:
                # Multi-market event - show as group
                display_items.append({
                    'type': 'event_group',
                    'event_title': event_title,
                    'event_id': group['event_id'],
                    'event_slug': group['event_slug'],
                    'markets': group['markets'],
                    'market_count': len(group['markets']),
                    # Aggregate stats
                    'total_volume': sum(m.get('volume', 0) for m in group['markets']),
                    'total_liquidity': sum(m.get('liquidity', 0) for m in group['markets']),
                })
            else:
                # Single market event - show as individual market
                market = group['markets'][0]
                display_items.append({
                    'type': 'individual',
                    **market
                })

        # Add markets without event_title as individual
        display_items.extend(individual_markets)

        # Sort by total volume (for event groups) or volume (for individuals)
        display_items.sort(
            key=lambda x: x.get('total_volume', x.get('volume', 0)),
            reverse=True
        )

        return display_items


# Global instance
_market_service: Optional[MarketService] = None


def get_market_service(cache_manager: Optional[CacheManager] = None) -> MarketService:
    """Get or create MarketService instance"""
    global _market_service
    if _market_service is None:
        _market_service = MarketService(cache_manager=cache_manager)
    return _market_service
