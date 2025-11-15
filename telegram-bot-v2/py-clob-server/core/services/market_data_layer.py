"""
MarketDataLayer: Abstraction pour migrer progressivement vers subsquid_*
Feature flag: USE_SUBSQUID_MARKETS (default: False pour transition graduelle)

Priorité de données:
1. subsquid_markets_ws (WebSocket live prices) - FRESHEST
2. subsquid_markets_poll (Gamma API polling)
3. markets table (OLD fallback)
"""

import logging
from typing import List, Dict, Optional
from sqlalchemy import func, or_
from database import db_manager

logger = logging.getLogger(__name__)


def _normalize_polymarket_category(raw_category: str) -> str:
    """
    Normalize Polymarket categories to our 5 simplified categories

    Args:
        raw_category: Raw category from Polymarket (e.g., "Cryptocurrency", "US Politics")

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

    # Default to Other (Tech, Science, Entertainment, Culture, etc.)
    return "Other"


class MarketDataLayer:
    """
    Abstraction layer for market data
    Handles gradual migration from markets table to subsquid_markets_poll/ws
    """

    def __init__(self, use_subsquid: bool = False):
        self.use_subsquid = use_subsquid
        logger.info(f"MarketDataLayer initialized: USE_SUBSQUID_MARKETS={self.use_subsquid}")

    def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """
        Get market by ID
        Priority: subsquid_markets_ws (live) > subsquid_markets_poll > markets (fallback)
        """
        if self.use_subsquid:
            # Try WebSocket data first (freshest)
            market = self._get_from_subsquid_ws(market_id)
            if market:
                logger.debug(f"Market {market_id} found in subsquid_markets_ws")
                return market

            # Fallback to polling data
            market = self._get_from_subsquid_poll(market_id)
            if market:
                logger.debug(f"Market {market_id} found in subsquid_markets_poll")
                return market

            logger.warning(f"Market {market_id} not found in subsquid tables, falling back to OLD")

        # Fallback to old markets table
        return self._get_from_markets_table(market_id)

    def get_live_price(self, market_id: str) -> Optional[float]:
        """
        Get live price for market
        ALWAYS prefer subsquid_markets_ws (WebSocket) for freshest data
        """
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketWS

                ws_market = db.query(SubsquidMarketWS).filter(
                    SubsquidMarketWS.market_id == market_id
                ).first()

                if ws_market and ws_market.last_mid:
                    logger.debug(f"Price for {market_id} from WebSocket: {ws_market.last_mid}")
                    return float(ws_market.last_mid)

                # Fallback to polling
                return self._get_price_from_poll(market_id, db)
        except Exception as e:
            logger.error(f"Error getting live price for {market_id}: {e}")
            return None

    def get_high_volume_markets(self, limit: int = 500) -> List[Dict]:
        """Get markets sorted by volume"""
        if self.use_subsquid:
            markets = self._get_markets_subsquid_poll(
                order_by="volume",
                limit=limit
            )
            logger.info(f"📊 [DATA_SOURCE] SUBSQUID: Fetched {len(markets)} markets")
            # Debug: check first market
            if markets:
                logger.debug(f"📊 [SUBSQUID_CHECK] First market: id={markets[0].get('id')}, end_date={markets[0].get('end_date')}, status={markets[0].get('status')}")
            return markets

        markets = self._get_markets_old_table(order_by="volume", limit=limit)
        logger.warning(f"⚠️ [DATA_SOURCE] FALLBACK (OLD TABLE): Fetched {len(markets)} markets - USE_SUBSQUID_MARKETS=false or error occurred")
        # Debug: check first market
        if markets:
            logger.debug(f"⚠️ [OLD_TABLE_CHECK] First market: id={markets[0].get('id')}, end_date={markets[0].get('end_date')}, status={markets[0].get('status')}")
        return markets

    def get_high_volume_markets_page(self, page: int = 0, page_size: int = 10, group_by_events: bool = False) -> tuple[List[Dict], int]:
        """
        Get paginated high-volume markets with Redis caching
        Optionally groups markets by events

        Args:
            page: Page number (0-indexed)
            page_size: Markets per page
            group_by_events: If True, groups markets by event and returns display items

        Returns:
            (markets or display_items, total_count) tuple
        """
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        # Try cache first (only if Redis is enabled)
        if redis_cache.enabled:
            cache_key = "volume_grouped" if group_by_events else "volume"
            cached = redis_cache.get_markets_page(cache_key, page)
            if cached is not None and len(cached) > 0:  # ✅ FIX: Treat [] as cache miss
                logger.debug(f"✅ Cache HIT: {cache_key} page {page}")
                return cached, -1

            logger.debug(f"💨 [REDIS] Cache MISS: {cache_key} page {page}, fetching from DB...")
        else:
            cache_key = "volume_grouped" if group_by_events else "volume"
            logger.debug(f"📊 [NO REDIS] Fetching {cache_key} page {page} directly from DB (no caching)")

        # CRITICAL: When grouping by events, fetch MORE markets to account for grouping
        fetch_size = page_size * 5 if group_by_events else page_size  # Fetch 50 instead of 10 when grouping

        # Fetch raw markets
        page_markets = self._get_markets_subsquid_poll_page(
            order_by="volume",
            page=page,
            page_size=fetch_size
        )

        # If grouping by events, process the markets
        if group_by_events:
            display_items = self._group_markets_by_events(page_markets)
            # Limit to page_size items after grouping
            display_items = display_items[:page_size]
        else:
            display_items = page_markets

        # Cache the result
        from config.config import MARKET_LIST_TTL
        redis_cache.cache_markets_page(cache_key, page, display_items, ttl=MARKET_LIST_TTL)
        logger.debug(f"📦 Cached {len(display_items)} items: {cache_key} page {page}")

        return display_items, -1

    def get_high_liquidity_markets(self, limit: int = 500) -> List[Dict]:
        """Get markets sorted by liquidity"""
        if self.use_subsquid:
            return self._get_markets_subsquid_poll(
                order_by="liquidity",
                limit=limit
            )

        return self._get_markets_old_table(order_by="liquidity", limit=limit)

    def get_high_liquidity_markets_page(self, page: int = 0, page_size: int = 10, group_by_events: bool = False) -> tuple[List[Dict], int]:
        """Get paginated high-liquidity markets with caching"""
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        # Try cache first (only if Redis is enabled)
        if redis_cache.enabled:
            cache_key = "liquidity_grouped" if group_by_events else "liquidity"
            cached = redis_cache.get_markets_page(cache_key, page)
            if cached is not None and len(cached) > 0:  # ✅ FIX: Treat [] as cache miss
                logger.debug(f"✅ Cache HIT: {cache_key} page {page}")
                return cached, -1

            logger.debug(f"💨 [REDIS] Cache MISS: {cache_key} page {page}, fetching from DB...")
        else:
            cache_key = "liquidity_grouped" if group_by_events else "liquidity"
            logger.debug(f"📊 [NO REDIS] Fetching {cache_key} page {page} directly from DB (no caching)")

        # CRITICAL: When grouping by events, fetch MORE markets to account for grouping
        fetch_size = page_size * 5 if group_by_events else page_size

        page_markets = self._get_markets_subsquid_poll_page(
            order_by="liquidity",
            page=page,
            page_size=fetch_size
        )

        if group_by_events:
            display_items = self._group_markets_by_events(page_markets)
            display_items = display_items[:page_size]
        else:
            display_items = page_markets

        from config.config import MARKET_LIST_TTL
        redis_cache.cache_markets_page(cache_key, page, display_items, ttl=MARKET_LIST_TTL)
        logger.debug(f"📦 Cached {len(display_items)} items: {cache_key} page {page}")

        return display_items, -1

    def get_markets_by_category_page(
        self,
        category: str,
        page: int = 0,
        page_size: int = 10,
        group_by_events: bool = False
    ) -> tuple[List[Dict], int]:
        """
        Get paginated markets filtered by category with optional event grouping

        This is the OPTIMIZED approach for category filtering:
        - Queries DB directly with category filter (no over-fetching)
        - Applies validation to filtered results
        - Groups by events if requested
        - Caches results per category

        Args:
            category: Category name (e.g., 'Finance', 'Sports', 'Crypto')
            page: Page number (0-indexed)
            page_size: Items per page
            group_by_events: If True, groups markets by events

        Returns:
            (display_items, total_count) tuple
        """
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        # Try cache first (only if Redis is enabled)
        if redis_cache.enabled:
            # Cache key includes category to avoid cross-contamination
            cache_key = f"category_{category.lower()}_grouped" if group_by_events else f"category_{category.lower()}"
            cached = redis_cache.get_markets_page(cache_key, page)
            if cached is not None and len(cached) > 0:  # ✅ FIX: Treat [] as cache miss
                logger.info(f"✅ [REDIS] Category cache HIT: {cache_key} page {page} ({len(cached)} items)")
                return cached, -1

            logger.debug(f"💨 [REDIS] Category cache MISS: {cache_key} page {page}, fetching from DB...")
        else:
            cache_key = f"category_{category.lower()}_grouped" if group_by_events else f"category_{category.lower()}"
            logger.debug(f"📊 [NO REDIS] Fetching category {cache_key} page {page} directly from DB (no caching)")

        # CRITICAL: When grouping by events, fetch MORE markets to account for grouping
        # After grouping, we might have fewer display items than markets fetched
        fetch_size = page_size * 5 if group_by_events else page_size

        # Fetch markets filtered by category
        page_markets = self._get_markets_by_category_from_db(
            category=category,
            page=page,
            page_size=fetch_size,
            order_by="volume"
        )

        # If grouping by events, process the markets
        if group_by_events:
            display_items = self._group_markets_by_events(page_markets)
            # Limit to page_size items after grouping
            display_items = display_items[:page_size]
        else:
            display_items = page_markets

        # Cache the result
        from config.config import MARKET_LIST_TTL
        redis_cache.cache_markets_page(cache_key, page, display_items, ttl=MARKET_LIST_TTL)
        logger.debug(f"📦 Cached {len(display_items)} items for category '{category}': page {page}")

        return display_items, -1

    def _get_markets_by_category_from_db(
        self,
        category: str,
        page: int = 0,
        page_size: int = 10,
        order_by: str = "volume"
    ) -> List[Dict]:
        """
        Query markets from database filtered by category

        This query uses normalization to map Polymarket categories to our 5 categories.
        Since SQL can't call Python normalization function, we fetch more results and
        filter in memory.

        Args:
            category: Category to filter by (e.g., 'Geopolitics', 'Sports')
            page: Page number (0-indexed)
            page_size: Number of markets to return
            order_by: Column to sort by (volume, liquidity, created_at, end_date)

        Returns:
            List of validated market dicts
        """
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)

                # Build query WITHOUT category filter (we'll filter in Python)
                # Fetch 10x page_size to have enough after normalization filtering
                query = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.status == 'ACTIVE',
                    SubsquidMarketPoll.end_date > now
                )

                # Order by specified column
                if order_by == "volume":
                    column = SubsquidMarketPoll.volume
                elif order_by == "liquidity":
                    column = SubsquidMarketPoll.liquidity
                elif order_by == "created_at":
                    column = SubsquidMarketPoll.created_at
                elif order_by == "end_date":
                    column = SubsquidMarketPoll.end_date
                else:
                    column = SubsquidMarketPoll.volume

                # Always sort descending for category browsing (highest first)
                query = query.order_by(column.desc())

                # Fetch large batch to filter by normalized category
                # Start from offset calculated with page, but fetch more to account for filtering
                fetch_size = page_size * 10  # Fetch 10x to account for filtering
                offset = page * page_size
                all_markets = query.offset(offset).limit(fetch_size).all()

                logger.debug(f"📊 [CATEGORY] Fetched {len(all_markets)} markets from DB for category filtering")

                # Convert to dicts and validate
                market_dicts = [m.to_dict() for m in all_markets]
                validated_markets = [m for m in market_dicts if self._is_market_valid(m)]

                # Filter by normalized category
                category_lower = category.lower()
                filtered_markets = [
                    m for m in validated_markets
                    if _normalize_polymarket_category(m.get('category', '')).lower() == category_lower
                ]

                logger.info(f"📊 [CATEGORY] After normalization filter: {len(filtered_markets)} {category} markets (from {len(validated_markets)} validated)")

                # Apply pagination on filtered results
                # Note: This is approximate since we already offset at DB level
                # For exact pagination, we'd need to fetch ALL and then paginate
                # But that's too expensive. This is good enough.
                paginated = filtered_markets[:page_size]

                return paginated

        except Exception as e:
            logger.error(f"❌ Error querying {category} markets from DB: {e}")
            return []

    def get_new_markets(self, limit: int = 500) -> List[Dict]:
        """Get newest markets"""
        if self.use_subsquid:
            return self._get_markets_subsquid_poll(
                order_by="created_at",
                limit=limit,
                desc=True
            )

        return self._get_markets_old_table(order_by="created_at", limit=limit, desc=True)

    def get_new_markets_page(self, page: int = 0, page_size: int = 10, group_by_events: bool = False) -> tuple[List[Dict], int]:
        """Get paginated newest markets with caching"""
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        # Try cache first (only if Redis is enabled)
        if redis_cache.enabled:
            cache_key = "new_grouped" if group_by_events else "new"
            cached = redis_cache.get_markets_page(cache_key, page)
            if cached is not None and len(cached) > 0:  # ✅ FIX: Treat [] as cache miss
                logger.debug(f"✅ Cache HIT: {cache_key} page {page}")
                return cached, -1

            logger.debug(f"💨 [REDIS] Cache MISS: {cache_key} page {page}, fetching from DB...")
        else:
            cache_key = "new_grouped" if group_by_events else "new"
            logger.debug(f"📊 [NO REDIS] Fetching {cache_key} page {page} directly from DB (no caching)")

        # CRITICAL: When grouping by events, fetch MORE markets to account for grouping
        fetch_size = page_size * 5 if group_by_events else page_size

        page_markets = self._get_markets_subsquid_poll_page(
            order_by="created_at",
            page=page,
            page_size=fetch_size
        )

        if group_by_events:
            display_items = self._group_markets_by_events(page_markets)
            display_items = display_items[:page_size]
        else:
            display_items = page_markets

        from config.config import MARKET_LIST_TTL
        redis_cache.cache_markets_page(cache_key, page, display_items, ttl=MARKET_LIST_TTL)
        logger.debug(f"📦 Cached {len(display_items)} items: {cache_key} page {page}")

        return display_items, -1

    def get_ending_soon_markets(self, hours: int = 168, limit: int = 500) -> List[Dict]:
        """Get markets ending soon"""
        if self.use_subsquid:
            return self._get_markets_subsquid_poll(
                order_by="end_date",
                limit=limit,
                filter_ending_soon=hours
            )

        return self._get_markets_old_table(
            order_by="end_date",
            limit=limit,
            filter_ending_soon=hours
        )

    def get_ending_soon_markets_page(self, hours: int = 168, page: int = 0, page_size: int = 10, group_by_events: bool = False) -> tuple[List[Dict], int]:
        """Get paginated ending-soon markets (expiring within hours) with caching"""
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        # Try cache first (only if Redis is enabled)
        if redis_cache.enabled:
            cache_key = f"ending_{hours}h_grouped" if group_by_events else f"ending_{hours}h"
            cached = redis_cache.get_markets_page(cache_key, page)
            if cached is not None and len(cached) > 0:  # ✅ FIX: Treat [] as cache miss
                logger.debug(f"✅ Cache HIT: {cache_key} page {page}")
                return cached, -1

            logger.debug(f"💨 [REDIS] Cache MISS: {cache_key} page {page}, fetching from DB...")
        else:
            cache_key = f"ending_{hours}h_grouped" if group_by_events else f"ending_{hours}h"
            logger.debug(f"📊 [NO REDIS] Fetching {cache_key} page {page} directly from DB (no caching)")

        # CRITICAL: When grouping by events, fetch MORE markets to account for grouping
        fetch_size = page_size * 5 if group_by_events else page_size

        page_markets = self._get_markets_subsquid_poll_page(
            order_by="end_date",
            page=page,
            page_size=fetch_size,
            filter_ending_soon=hours
        )

        if group_by_events:
            display_items = self._group_markets_by_events(page_markets)
            display_items = display_items[:page_size]
        else:
            display_items = page_markets

        from config.config import MARKET_LIST_TTL
        redis_cache.cache_markets_page(cache_key, page, display_items, ttl=MARKET_LIST_TTL)
        logger.debug(f"📦 Cached {len(display_items)} items: {cache_key} page {page}")

        return display_items, -1

    def invalidate_markets_cache(self, filter_name: Optional[str] = None) -> None:
        """
        Invalidate markets cache when data updates from Poller/WebSocket
        Called when market status changes or prices update

        Args:
            filter_name: Specific filter to invalidate ('volume', 'liquidity', 'new', etc.)
                        or None to invalidate all
        """
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        if filter_name:
            redis_cache.invalidate_markets_cache(filter_name=filter_name)
            logger.info(f"🔄 Invalidated cache for filter: {filter_name}")
        else:
            redis_cache.invalidate_markets_cache(filter_name=None)
            logger.info(f"🔄 Invalidated ALL markets cache")

    # ========================================================================
    # Private methods for each data source
    # ========================================================================

    def _get_from_subsquid_ws(self, market_id: str) -> Optional[Dict]:
        """Query subsquid_markets_ws (WebSocket live data)"""
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketWS
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                market = db.query(SubsquidMarketWS).filter(
                    SubsquidMarketWS.market_id == market_id,
                    SubsquidMarketWS.status.notin_(['resolved', 'closed', 'archived']),
                    # Exclude expired markets
                    ~(
                        (SubsquidMarketWS.expiry.isnot(None)) &
                        (SubsquidMarketWS.expiry <= now)
                    )
                ).first()
                return market.to_dict() if market else None
        except Exception as e:
            logger.warning(f"Error querying subsquid_markets_ws for {market_id}: {e}")
            return None

    def _get_from_subsquid_poll(self, market_id: str) -> Optional[Dict]:
        """Query subsquid_markets_poll (Gamma API polling)"""
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                market = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.market_id == market_id,
                    SubsquidMarketPoll.status.notin_(['RESOLVED', 'CLOSED', 'ARCHIVED']),
                    # Only non-expired markets with valid end_date
                    SubsquidMarketPoll.end_date.isnot(None),
                    SubsquidMarketPoll.end_date > now
                ).first()
                return market.to_dict() if market else None
        except Exception as e:
            logger.warning(f"Error querying subsquid_markets_poll for {market_id}: {e}")
            return None

    def _get_from_markets_table(self, market_id: str) -> Optional[Dict]:
        """Query old markets table (fallback)"""
        try:
            with db_manager.get_session() as db:
                from database import Market
                market = db.query(Market).filter(Market.id == market_id).first()
                return market.to_dict() if market else None
        except Exception as e:
            logger.warning(f"Error querying markets table for {market_id}: {e}")
            return None

    def _get_price_from_poll(self, market_id: str, db) -> Optional[float]:
        """Get price from subsquid_markets_poll (fallback)"""
        try:
            from database import SubsquidMarketPoll
            market = db.query(SubsquidMarketPoll).filter(
                SubsquidMarketPoll.market_id == market_id
            ).first()

            if market and market.last_mid:
                logger.debug(f"Price for {market_id} from polling: {market.last_mid}")
                return float(market.last_mid)
        except Exception as e:
            logger.warning(f"Error getting price from poll for {market_id}: {e}")

        return None

    def _get_markets_subsquid_poll(
        self,
        order_by: str = "volume",
        limit: int = 500,
        desc: bool = True,
        filter_ending_soon: Optional[int] = None
    ) -> List[Dict]:
        """Query markets from subsquid_markets_poll"""
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone, timedelta

                query = db.query(SubsquidMarketPoll)

                now = datetime.now(timezone.utc)

                # ⚠️ IMPORTANT: Only show ACTIVE markets
                # NOTE: Status values in DB are UPPERCASE (ACTIVE, CLOSED, RESOLVED)
                # We intentionally DO NOT filter out markets with events == None so that
                # single markets (without event grouping) are also included.
                query = query.filter(
                    SubsquidMarketPoll.status == 'ACTIVE'
                )

                # Filter ending soon if specified
                if filter_ending_soon:
                    cutoff = datetime.now(timezone.utc) + timedelta(hours=filter_ending_soon)
                    query = query.filter(
                        SubsquidMarketPoll.end_date.isnot(None),
                        SubsquidMarketPoll.end_date < cutoff
                    )

                # Order by
                if order_by == "volume":
                    column = SubsquidMarketPoll.volume
                elif order_by == "liquidity":
                    column = SubsquidMarketPoll.liquidity
                elif order_by == "created_at":
                    column = SubsquidMarketPoll.created_at
                elif order_by == "end_date":
                    column = SubsquidMarketPoll.end_date
                else:
                    column = SubsquidMarketPoll.volume

                if desc:
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column.asc())

                markets = query.limit(limit).all()
                logger.debug(f"📊 Loaded {len(markets)} active (non-expired) markets from subsquid_markets_poll")

                # Apply validation with error handling
                validated_markets = []
                for m in markets:
                    try:
                        market_dict = m.to_dict()
                        if not isinstance(market_dict, dict):
                            logger.error(f"❌ to_dict() returned {type(market_dict)} instead of dict")
                            continue
                        if self._is_market_valid(market_dict):
                            validated_markets.append(market_dict)
                    except Exception as e:
                        logger.error(f"❌ Error processing market: {e} (market_id: {getattr(m, 'market_id', 'unknown')})")
                        continue

                logger.debug(f"📊 After validation: {len(validated_markets)} valid markets (excluded {len(markets) - len(validated_markets)} illiquid)")

                return validated_markets

        except Exception as e:
            logger.error(f"Error querying subsquid_markets_poll: {e}", exc_info=True)
            return []

    def _get_markets_subsquid_poll_page(
        self,
        order_by: str = "volume",
        page: int = 0,
        page_size: int = 10,
        desc: bool = True,
        filter_ending_soon: Optional[int] = None
    ) -> List[Dict]:
        """Query markets from subsquid_markets_poll with DIRECT PAGINATION (OPTIMIZED)"""
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone, timedelta

                query = db.query(SubsquidMarketPoll)
                now = datetime.now(timezone.utc)

                # ⚡ OPTIMIZATION: Only show ACTIVE markets
                query = query.filter(
                    SubsquidMarketPoll.status == 'ACTIVE'
                )

                # Filter ending soon if specified
                if filter_ending_soon:
                    cutoff = datetime.now(timezone.utc) + timedelta(hours=filter_ending_soon)
                    query = query.filter(
                        SubsquidMarketPoll.end_date.isnot(None),
                        SubsquidMarketPoll.end_date < cutoff
                    )

                # Order by
                if order_by == "volume":
                    column = SubsquidMarketPoll.volume
                elif order_by == "liquidity":
                    column = SubsquidMarketPoll.liquidity
                elif order_by == "created_at":
                    column = SubsquidMarketPoll.created_at
                elif order_by == "end_date":
                    column = SubsquidMarketPoll.end_date
                else:
                    column = SubsquidMarketPoll.volume

                if desc:
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column.asc())

                # ⚡ CRITICAL OPTIMIZATION: Direct pagination with OFFSET/LIMIT
                offset = page * page_size
                markets = query.offset(offset).limit(page_size).all()

                logger.debug(f"📊 [OPTIMIZED] Loaded {len(markets)} markets from subsquid_markets_poll (page {page}, offset {offset})")

                # Convert to dicts ONCE, then validate
                market_dicts = []
                for m in markets:
                    try:
                        market_dict = m.to_dict()
                        # ✅ SAFETY CHECK: Ensure to_dict() returns a dict, not a string
                        if not isinstance(market_dict, dict):
                            logger.error(f"❌ to_dict() returned {type(market_dict)} instead of dict for market {getattr(m, 'market_id', 'unknown')}")
                            continue
                        market_dicts.append(market_dict)
                    except Exception as e:
                        logger.error(f"❌ Error converting market to dict: {e} (market_id: {getattr(m, 'market_id', 'unknown')})")
                        continue

                # Validate markets
                validated_markets = []
                for m in market_dicts:
                    try:
                        if self._is_market_valid(m):
                            validated_markets.append(m)
                    except Exception as e:
                        logger.error(f"❌ Error validating market: {e} (market type: {type(m)}, market_id: {m.get('market_id', 'unknown') if isinstance(m, dict) else 'NOT_A_DICT'})")
                        continue

                logger.info(f"📊 [OPTIMIZED] After validation: {len(validated_markets)} valid markets (from {len(market_dicts)})")

                return validated_markets

        except Exception as e:
            logger.error(f"Error querying subsquid_markets_poll with pagination: {e}", exc_info=True)
            return []

    def _get_markets_old_table(
        self,
        order_by: str = "volume",
        limit: int = 500,
        desc: bool = True,
        filter_ending_soon: Optional[int] = None
    ) -> List[Dict]:
        """Query markets from old markets table"""
        try:
            with db_manager.get_session() as db:
                from database import Market
                from datetime import datetime, timezone, timedelta

                now = datetime.now(timezone.utc)

                # Filter for active markets that haven't ended
                query = db.query(Market).filter(
                    Market.status == 'active',
                    Market.active == True,
                    Market.closed == False,
                    # Only markets with valid end_date AND not yet expired
                    Market.end_date.isnot(None),
                    Market.end_date > now
                )

                # Filter ending soon if specified
                if filter_ending_soon:
                    cutoff = datetime.now(timezone.utc) + timedelta(hours=filter_ending_soon)
                    query = query.filter(
                        Market.end_date.isnot(None),
                        Market.end_date < cutoff
                    )

                # Order by
                if order_by == "volume":
                    column = Market.volume
                elif order_by == "liquidity":
                    column = Market.liquidity
                elif order_by == "created_at":
                    column = Market.created_at
                elif order_by == "end_date":
                    column = Market.end_date
                else:
                    column = Market.volume

                if desc:
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column.asc())

                markets = query.limit(limit).all()
                logger.debug(f"📊 Loaded {len(markets)} active markets from OLD markets table (fallback)")

                # ⚠️ CRITICAL: Enrich OLD markets with event_id synthetic
                # The old markets table doesn't have event_id or events, so we create synthetic ones
                # This prevents grouping issues when MarketDataLayer falls back to old table
                enriched_markets = []
                for m in markets:
                    market_dict = m.to_dict()

                    # Add synthetic event_id if not present (prevents ungrouped market collapse)
                    if not market_dict.get('event_id'):
                        # Use market ID as synthetic event_id for individual display
                        # This keeps each market from being grouped with others
                        market_dict['event_id'] = None  # Explicitly set to None so grouping treats as individual

                    # Add empty events array if not present (required for event extraction logic)
                    if 'events' not in market_dict:
                        market_dict['events'] = []

                    # Apply validation: filter out illiquid markets
                    if self._is_market_valid(market_dict):
                        enriched_markets.append(market_dict)

                logger.debug(f"📊 After validation: {len(enriched_markets)} valid markets (excluded {len(markets) - len(enriched_markets)} illiquid)")
                return enriched_markets

        except Exception as e:
            logger.error(f"Error querying markets table: {e}")
            return []

    def _is_market_valid(self, market: Dict) -> bool:
        """
        Validate market before displaying
        Excludes ONLY markets with empty pricing (illiquid/closed markets)

        REMOVED: Price range checks (0.001/0.999 are valid for high-confidence markets!)

        Args:
            market: Market dictionary

        Returns:
            True if market should be displayed, False if should be hidden
        """
        # Check outcome_prices for empty/null values
        outcome_prices = market.get('outcome_prices', [])

        if isinstance(outcome_prices, str):
            try:
                import json
                outcome_prices = json.loads(outcome_prices)
            except:
                outcome_prices = []

        # ✅ ONLY check: prices exist and not empty
        # Empty prices = market not actively traded
        if not outcome_prices or len(outcome_prices) == 0:
            logger.debug(f"⚠️ Market {market.get('id')} excluded: no outcome prices (treat as illiquid/closed)")
            return False

        # ✅ REMOVED: Extreme price checks (0.001/0.999 are VALID for high-confidence markets!)
        # Example: Bitcoin Up/Down markets often have 0.01/0.99 prices near expiration
        # Example: Lewis Hamilton F1 had 0.001/0.999 before being closed

        return True

    def _group_markets_by_events(self, markets: List[Dict]) -> List[Dict]:
        """
        Group markets by event_title and return display items

        Grouping Logic:
        - A market is grouped ONLY if event_title != market title
        - If event_title == market title, it's a standalone market
        - This prevents false positives like "Blue Jays vs Dodgers" from being grouped

        CRITICAL FIX: When we find markets belonging to an event, we fetch ALL markets
        from that event (not just the ones in the current page) to show accurate counts
        """
        event_groups = {}
        individual_markets = []
        event_ids_to_fetch = set()

        # Helper: safely get event info (handles both dict and string cases)
        def get_event_info(event_obj):
            """Safely extract event info, handling both dict and string formats"""
            if isinstance(event_obj, dict):
                return event_obj
            elif isinstance(event_obj, str):
                try:
                    import json
                    return json.loads(event_obj)
                except:
                    return None
            return None

        # PASS 1: Identify all event IDs we need to fetch complete data for
        for market in markets:
            events = market.get('events', [])
            market_title = market.get('title', '')

            if events and len(events) > 0:
                event_info = get_event_info(events[0])
                if event_info and event_info.get('event_title'):
                    event_title = event_info.get('event_title')
                    if event_title != market_title:
                        event_id = event_info.get('event_id')
                        if event_id:
                            event_ids_to_fetch.add(event_id)

        # PASS 2: Fetch ALL markets for ALL event_ids in ONE batch query (OPTIMIZED)
        all_event_markets = {}
        if event_ids_to_fetch:
            try:
                with db_manager.get_session() as db:
                    from database import SubsquidMarketPoll
                    from datetime import datetime, timezone
                    from sqlalchemy import or_

                    now = datetime.now(timezone.utc)

                    # PERFORMANCE FIX: Batch query instead of loop (1 query instead of N)
                    # Build OR conditions for all event_ids at once
                    event_conditions = [
                        SubsquidMarketPoll.events.op('@>')(f'[{{"event_id": "{event_id}"}}]')
                        for event_id in event_ids_to_fetch
                    ]

                    # Single batch query for ALL events
                    all_markets = db.query(SubsquidMarketPoll).filter(
                        SubsquidMarketPoll.status == 'ACTIVE',
                        SubsquidMarketPoll.end_date > now,
                        or_(*event_conditions)
                    ).all()

                    # Group results by event_id
                    for market in all_markets:
                        market_dict = market.to_dict()
                        events = market_dict.get('events', [])
                        if events and len(events) > 0:
                            event_info = get_event_info(events[0])
                            if event_info:
                                event_id = event_info.get('event_id')
                                if event_id:
                                    if event_id not in all_event_markets:
                                        all_event_markets[event_id] = []
                                    all_event_markets[event_id].append(market_dict)

                    logger.debug(f"📊 Batch fetched markets for {len(all_event_markets)} events in 1 query (was {len(event_ids_to_fetch)} queries)")

            except Exception as e:
                logger.error(f"❌ Error fetching complete event markets: {e}")

        # PASS 3: Group markets using complete event data
        for market in markets:
            events = market.get('events', [])
            market_title = market.get('title', '')

            # CRITICAL FIX: Only group if event_title is DIFFERENT from market title
            if events and len(events) > 0:
                event_info = get_event_info(events[0])
                if event_info and event_info.get('event_title') and event_info.get('event_title') != market_title:
                    # Market belongs to an event - group it
                    event_id = event_info.get('event_id')
                    event_title = event_info.get('event_title')

                    if event_id and event_id not in event_groups:
                        # Use complete event data if available, otherwise just this market
                        complete_markets = all_event_markets.get(event_id, [market])

                        # Calculate total volume and liquidity from ALL markets in event
                        total_volume = sum(float(m.get('volume', 0)) for m in complete_markets)
                        total_liquidity = sum(float(m.get('liquidity', 0)) for m in complete_markets)

                        event_groups[event_id] = {
                            'event_id': event_id,
                            'event_title': event_title,
                            'type': 'event_group',
                            'markets': complete_markets,
                            'total_volume': total_volume,
                            'total_liquidity': total_liquidity,
                            'end_date': market.get('end_date'),
                            'title': event_title  # For UI consistency
                        }
                else:
                    # Individual market (event_title == market_title)
                    market['type'] = 'individual'
                    individual_markets.append(market)
            else:
                # Individual market (no event grouping)
                market['type'] = 'individual'
                individual_markets.append(market)

        # Add event groups to display (sorted by volume)
        display_items = []
        event_list = sorted(event_groups.values(), key=lambda x: x['total_volume'], reverse=True)
        for event_data in event_list:
            event_data['count'] = len(event_data['markets'])
            event_data['volume'] = event_data['total_volume']
            display_items.append(event_data)

        # Add individual markets (sorted by volume)
        individual_markets.sort(key=lambda x: float(x.get('volume', 0)), reverse=True)
        display_items.extend(individual_markets)

        logger.info(f"📊 Grouped into {len(event_groups)} events + {len(individual_markets)} individual markets = {len(display_items)} items")
        return display_items


# Singleton pattern
_market_data_layer: Optional[MarketDataLayer] = None


def get_market_data_layer() -> MarketDataLayer:
    """Get or create singleton instance of MarketDataLayer"""
    global _market_data_layer
    if _market_data_layer is None:
        from config.config import USE_SUBSQUID_MARKETS
        _market_data_layer = MarketDataLayer(use_subsquid=USE_SUBSQUID_MARKETS)
    return _market_data_layer
