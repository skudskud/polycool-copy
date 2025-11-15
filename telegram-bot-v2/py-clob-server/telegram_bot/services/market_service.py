#!/usr/bin/env python3
"""
Market Service - PostgreSQL Version
Handles market data retrieval, search, and validation
"""

import hashlib
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# SAFE IMPORTS: Wrap in try/except to prevent cascading failures
try:
    from database import db_manager, Market
    DB_AVAILABLE = True
    logger.info("✅ [MARKET_SERVICE] Database imports successful")
except Exception as e:
    logger.warning(f"⚠️ [MARKET_SERVICE] Database not available during import: {e}")
    DB_AVAILABLE = False
    db_manager = None
    Market = None


class MarketService:
    """
    Service for market-related operations
    Uses PostgreSQL for all market data
    Gracefully degrades if database unavailable
    """

    def __init__(self):
        """Initialize market service with PostgreSQL connection"""
        if not DB_AVAILABLE:
            logger.warning("⚠️ [MARKET_SERVICE] Initialized without database - read-only/fallback mode")
            self.db_available = False
        else:
            logger.info("🔧 [MARKET_SERVICE] Initialized with PostgreSQL")
            self.db_available = True

    def get_market_by_id(self, market_id: str, allow_closed: bool = False) -> Optional[Dict]:
        """
        Fetch market data by ID (Redis cache first, PostgreSQL fallback)
        Now uses SubsquidMarketPoll exclusively

        Args:
            market_id: Market identifier (can be market_id or condition_id)
            allow_closed: If True, also returns CLOSED markets (for selling existing positions)

        Returns:
            Market dictionary or None if not found
        """
        try:
            logger.debug(f"🔍 [MARKET_SERVICE] get_market_by_id: {market_id[:20]}... (allow_closed={allow_closed})")

            # Validation: Reject invalid market IDs
            if market_id.startswith('0x') and len(market_id) > 66:
                logger.warning(f"⚠️ [MARKET_SERVICE] Skipping legacy hash market_id: {market_id[:20]}...")
                return None

            # Layer 1: Try Redis cache first (5-10ms)
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()

            cached_market = redis_cache.get_market_data(market_id)
            if cached_market is not None:
                logger.debug(f"🚀 [MARKET_SERVICE] Cache hit for {market_id[:10]}...")
                return cached_market

            # Layer 2: Cache miss - query PostgreSQL (50-200ms)
            logger.debug(f"💨 [MARKET_SERVICE] Cache miss, querying DB for {market_id[:10]}...")

            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)

                # Build base filters
                if allow_closed:
                    # For selling positions: accept any market status
                    status_filter = SubsquidMarketPoll.status.in_(['ACTIVE', 'PENDING', 'CLOSED'])
                else:
                    # For buying: only active/pending markets
                    status_filter = SubsquidMarketPoll.status.in_(['ACTIVE', 'PENDING'])

                # Try SubsquidMarketPoll first (by market_id)
                query = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.market_id == market_id,
                    status_filter
                )

                # Add tradeable/date filters only for active markets
                if not allow_closed:
                    query = query.filter(
                        SubsquidMarketPoll.tradeable == True,
                        SubsquidMarketPoll.end_date.isnot(None),
                        SubsquidMarketPoll.end_date > now
                    )

                market = query.first()

                # FALLBACK 1: Try condition_id if market_id lookup failed
                if not market and market_id.startswith('0x'):
                    logger.debug(f"💨 Not found by market_id, trying condition_id...")
                    query = db.query(SubsquidMarketPoll).filter(
                        SubsquidMarketPoll.condition_id == market_id,
                        status_filter
                    )

                    if not allow_closed:
                        query = query.filter(
                            SubsquidMarketPoll.tradeable == True,
                            SubsquidMarketPoll.end_date.isnot(None),
                            SubsquidMarketPoll.end_date > now
                        )

                    market = query.first()

                if not market:
                    logger.debug(f"⚠️ [MARKET_SERVICE] Market {market_id[:10]}... not found (allow_closed={allow_closed})")
                    return None

                market_dict = market.to_dict()
                logger.info(f"🔍 [MARKET_SERVICE] market_dict keys: {list(market_dict.keys())}")
                logger.info(f"🔍 [MARKET_SERVICE] market_dict['title']: {market_dict.get('title')}")
                logger.info(f"🔍 [MARKET_SERVICE] Full market_dict: {market_dict}")

                # Cache for future requests (TTL: 60s)
                from config.config import MARKET_LIST_TTL
                redis_cache.cache_market_data(market_id, market_dict, ttl=MARKET_LIST_TTL)
                logger.debug(f"💾 [MARKET_SERVICE] Cached {market_id[:10]}...")

                return market_dict

        except Exception as e:
            logger.error(f"❌ [MARKET_SERVICE] Error fetching market {market_id[:10]}...: {e}")
            return None

    def get_short_market_id(self, market_id: str) -> str:
        """
        Create a short hash of market_id for Telegram callback data (64 byte limit)

        Args:
            market_id: Full market identifier

        Returns:
            12-character hash of the market ID
        """
        return hashlib.md5(market_id.encode()).hexdigest()[:12]

    def find_market_by_short_id(self, positions: Dict, short_id: str) -> Optional[str]:
        """
        Find the full market_id from a short hash by searching user positions

        Args:
            positions: User positions dictionary
            short_id: Short market hash

        Returns:
            Full market ID or None if not found
        """
        for position_key in positions.keys():
            # Extract market_id from position_key (format: market_id_outcome)
            if '_yes' in position_key:
                market_id = position_key.replace('_yes', '')
            elif '_no' in position_key:
                market_id = position_key.replace('_no', '')
            else:
                continue

            if self.get_short_market_id(market_id) == short_id:
                return market_id
        return None

    def search_markets(self, query: str) -> List[Dict]:
        """
        Search markets by title text

        Args:
            query: Search query string

        Returns:
            List of matching market dictionaries
        """
        try:
            search_term = f"%{query}%"

            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)

                markets = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.status.in_(['ACTIVE', 'PENDING']),
                    SubsquidMarketPoll.tradeable == True,
                    SubsquidMarketPoll.end_date.isnot(None),
                    SubsquidMarketPoll.end_date > now,
                    SubsquidMarketPoll.title.ilike(search_term)
                ).order_by(SubsquidMarketPoll.volume.desc()).limit(20).all()

                return [m.to_dict() for m in markets]

        except Exception as e:
            logger.error(f"Error searching markets: {e}")
            return []

    def get_all_markets(self) -> List[Dict]:
        """
        Get all active markets from PostgreSQL

        Returns:
            List of all active market dictionaries
        """
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)

                markets = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.status.in_(['ACTIVE', 'PENDING']),
                    SubsquidMarketPoll.end_date.isnot(None),
                    SubsquidMarketPoll.end_date > now
                ).order_by(SubsquidMarketPoll.volume.desc()).all()

                return [m.to_dict() for m in markets]

        except Exception as e:
            logger.error(f"Error loading all markets: {e}")
            return []

    def get_tradeable_markets(self, limit: int = 20) -> List[Dict]:
        """
        Get only tradeable markets from PostgreSQL

        Args:
            limit: Maximum number of markets to return

        Returns:
            List of tradeable market dictionaries
        """
        try:
            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)

                markets = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.status.in_(['ACTIVE', 'PENDING']),
                    SubsquidMarketPoll.tradeable == True,
                    SubsquidMarketPoll.end_date.isnot(None),
                    SubsquidMarketPoll.end_date > now
                ).order_by(SubsquidMarketPoll.volume.desc()).limit(limit).all()

                return [m.to_dict() for m in markets]

        except Exception as e:
            logger.error(f"Error loading tradeable markets: {e}")
            return []

    def search_by_title(self, title: str, fuzzy: bool = True) -> Optional[Dict]:
        """
        Search for a market by title
        Used as fallback when condition_id doesn't match

        Args:
            title: Market title to search for
            fuzzy: If True, use fuzzy matching (e.g., "Raiders vs. Broncos" matches "Raiders vs. Broncos: O/U 42.5")

        Returns:
            Market dictionary or None if not found
        """
        try:
            logger.debug(f"🔍 [MARKET_SERVICE] Searching by title: {title[:50]}...")

            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll
                from datetime import datetime, timezone
                from sqlalchemy import func

                now = datetime.now(timezone.utc)

                # Try exact match first (ALLOW EXPIRED MARKETS for smart trading view)
                logger.info(f"🔍 [MARKET_SERVICE] Trying exact match for: {title[:50]}...")
                market_orm = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.title == title,
                    SubsquidMarketPoll.status.in_(['ACTIVE', 'PENDING', 'CLOSED'])
                    # ✅ REMOVED: end_date > now filter to allow viewing expired markets
                ).first()

                logger.info(f"🔍 [MARKET_SERVICE] Exact match result: {'FOUND' if market_orm else 'NOT FOUND'}")

                # If no exact match and fuzzy enabled, try fuzzy matching
                if not market_orm and fuzzy:
                    # Remove common suffixes for matching
                    base_title = title
                    for suffix in [': O/U', ': 1H', 'Spread:', 'Moneyline', 'Total']:
                        if suffix in base_title:
                            base_title = base_title.split(suffix)[0].strip()

                    logger.info(f"🔍 [MARKET_SERVICE] Fuzzy search with base: '{base_title}'")

                    # Find markets that START with the base title (ALLOW EXPIRED)
                    market_orm = db.query(SubsquidMarketPoll).filter(
                        SubsquidMarketPoll.title.ilike(f"{base_title}%"),
                        SubsquidMarketPoll.status.in_(['ACTIVE', 'PENDING', 'CLOSED'])
                        # ✅ REMOVED: end_date > now filter
                    ).order_by(
                        # Prefer exact matches, then by volume
                        func.length(SubsquidMarketPoll.title).asc(),
                        SubsquidMarketPoll.volume.desc().nullslast()
                    ).first()

                    logger.info(f"🔍 [MARKET_SERVICE] Fuzzy match result: {'FOUND' if market_orm else 'NOT FOUND'}")
                    if market_orm:
                        logger.info(f"🔍 [MARKET_SERVICE] Fuzzy match found: {market_orm.title[:50]}")

                if market_orm:
                    logger.info(f"✅ [MARKET_SERVICE] Found market by title: {market_orm.title[:50]}...")
                    market_dict = market_orm.to_dict()

                    # ✅ ADD EXPIRY WARNING if market is expired
                    if market_orm.end_date and market_orm.end_date < now:
                        market_dict['is_expired'] = True
                        logger.warning(f"⚠️ [MARKET_SERVICE] Market expired on {market_orm.end_date}")
                    else:
                        market_dict['is_expired'] = False

                    return market_dict
                else:
                    logger.warning(f"❌ [MARKET_SERVICE] No market found for title: {title[:50]}...")
                    return None

        except Exception as e:
            logger.error(f"❌ [MARKET_SERVICE] Error searching by title: {e}")
            return None

    def validate_market(self, market_id: str) -> tuple[bool, Optional[str]]:
        """
        Validate if a market exists and is tradeable

        Args:
            market_id: Market identifier

        Returns:
            Tuple of (is_valid, error_message)
        """
        market = self.get_market_by_id(market_id)
        if not market:
            return False, "Market not found or inactive"

        if not market.get('active', False):
            return False, "Market is not active"

        if not market.get('accepting_orders', False):
            return False, "Market is not accepting orders"

        if market.get('closed', False):
            return False, "Market is closed"

        if market.get('archived', False):
            return False, "Market is archived"

        # Legacy check for tradeable (may not be reliable with API changes)
        if not market.get('tradeable', True):  # Default to True if not specified
            return False, "Market is not tradeable"

        return True, None

    def get_token_price(self, token_id: str, market_id: str = None) -> Optional[float]:
        """
        Get current price for a specific token from WebSocket/Redis cache (or API fallback)
        Used by TP/SL price monitor to check if targets are hit

        Priority:
        1. WebSocket (subsquid_markets_ws) - <100ms freshness
        2. Redis cache - 20s TTL
        3. API direct

        Args:
            token_id: ERC-1155 token ID
            market_id: Optional market_id for WebSocket lookup

        Returns:
            Current price in USD or None if failed
        """
        try:
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()

            # Priority 1: WebSocket (freshest data)
            if market_id:
                from telegram_bot.services.price_calculator import PriceCalculator
                ws_price = PriceCalculator.get_live_price_from_subsquid_ws(market_id)
                if ws_price is not None:
                    logger.debug(f"🌐 WS HIT: Token {token_id[:10]}... = ${ws_price:.4f}")
                    # Cache WS price for future quick lookups
                    from config.config import MARKET_PRICE_TTL
                    redis_cache.cache_token_price(token_id, ws_price, ttl=MARKET_PRICE_TTL)
                    return ws_price

            # Priority 2: Redis cache
            cached_price = redis_cache.get_token_price(token_id)
            if cached_price is not None:
                logger.debug(f"🚀 CACHE HIT: Token {token_id[:10]}... = ${cached_price:.4f}")
                return cached_price

            # Priority 3: API fallback
            logger.debug(f"💨 CACHE MISS: Fetching token {token_id[:10]}... from API")

            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            # Create a temporary client for price fetching (no wallet needed)
            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON
            )

            # Fetch SELL side price (bid price - what we can sell at)
            price_data = client.get_price(token_id, side='SELL')

            if price_data and 'price' in price_data:
                price = float(price_data['price'])
                logger.debug(f"📊 API Token {token_id[:10]}... price: ${price:.4f}")

                # Cache for future requests
                from config.config import MARKET_PRICE_TTL
                redis_cache.cache_token_price(token_id, price, ttl=MARKET_PRICE_TTL)

                return price

            logger.warning(f"⚠️ No price data returned for token {token_id}")
            return None

        except Exception as e:
            logger.error(f"❌ GET TOKEN PRICE ERROR for {token_id}: {e}")
            return None

    def get_token_price_with_audit(self, token_id: str, context: str = "navigation") -> tuple[Optional[float], bool, float, int]:
        """
        Get token price with audit information (for position display)

        Args:
            token_id: ERC-1155 token ID
            context: Usage context ("trading", "navigation", "background") for adaptive TTL

        Returns:
            Tuple of (price, cache_hit, fetch_time, ttl_remaining)
        """
        import time
        start_time = time.time()

        try:
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()

            # Try Redis cache first
            price, cache_hit, ttl = redis_cache.get_token_price_with_stats(token_id)

            if price is not None:
                fetch_time = time.time() - start_time
                logger.debug(f"🚀 CACHE HIT: Token {token_id[:10]}... = ${price:.4f} (TTL: {ttl}s, time: {fetch_time*1000:.1f}ms)")
                return price, cache_hit, fetch_time, ttl

            # Cache miss - fetch from API
            logger.debug(f"💨 CACHE MISS: Fetching token {token_id[:10]}... from API")

            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON
            )

            price_data = client.get_price(token_id, side='SELL')

            if price_data and 'price' in price_data:
                price = float(price_data['price'])
                fetch_time = time.time() - start_time

                logger.debug(f"📊 API Token {token_id[:10]}... price: ${price:.4f} (time: {fetch_time*1000:.1f}ms)")

                # Cache for future requests with ADAPTIVE TTL based on context
                from config.config import get_adaptive_price_ttl
                adaptive_ttl = get_adaptive_price_ttl(context)
                redis_cache.cache_token_price(token_id, price, ttl=adaptive_ttl)

                return price, False, fetch_time, adaptive_ttl

            fetch_time = time.time() - start_time
            logger.warning(f"⚠️ No price data returned for token {token_id} (time: {fetch_time*1000:.1f}ms)")
            return None, False, fetch_time, 0

        except Exception as e:
            fetch_time = time.time() - start_time
            logger.error(f"❌ GET TOKEN PRICE ERROR for {token_id}: {e} (time: {fetch_time*1000:.1f}ms)")
            return None, False, fetch_time, 0

    def get_prices_batch(self, token_ids: List[str]) -> Dict[str, Optional[float]]:
        """
        Get current prices for multiple tokens in batch (Redis cache → API fallback)
        TP/SL monitoring uses cached data for reliability, not raw WebSocket data

        Args:
            token_ids: List of ERC-1155 token IDs

        Returns:
            Dictionary mapping token_id to price (or None if failed)
        """
        try:
            # PHASE 1: Try Redis cache first (batch get - super efficient)
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()

            cached_prices = redis_cache.get_token_prices_batch(token_ids)

            # Find which tokens we still need (cache misses)
            missing_tokens = [tid for tid, price in cached_prices.items() if price is None]

            if not missing_tokens:
                # All tokens were cached!
                logger.debug(f"🚀 CACHE HIT: All {len(token_ids)} token prices from Redis")
                return cached_prices

            logger.debug(f"💨 CACHE PARTIAL: {len(token_ids) - len(missing_tokens)} hits, {len(missing_tokens)} misses")

            # PHASE 2: Fetch missing prices from API
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON
            )

            api_prices = {}

            for token_id in missing_tokens:
                try:
                    price_data = client.get_price(token_id, side='SELL')
                    if price_data and 'price' in price_data:
                        api_prices[token_id] = float(price_data['price'])
                    else:
                        api_prices[token_id] = None
                except Exception as e:
                    logger.error(f"❌ Error fetching price for {token_id[:10]}...: {e}")
                    api_prices[token_id] = None

            # Cache the newly fetched prices
            if api_prices:
                from config.config import MARKET_PRICE_TTL
                redis_cache.cache_token_prices_batch(api_prices, ttl=MARKET_PRICE_TTL)

            # Merge cached and API prices
            final_prices = {**cached_prices, **api_prices}

            logger.debug(f"📊 Batch complete: {len(final_prices)} total prices")
            return final_prices

        except Exception as e:
            logger.error(f"❌ GET PRICES BATCH ERROR: {e}")
            return {token_id: None for token_id in token_ids}

    def get_prices_for_tpsl_batch(self, orders: List['TPSLOrder']) -> Dict[int, Optional[float]]:
        """
        Get current prices for TP/SL orders with full context (market_id, outcome)
        This enables Poller fallback when API/cache fails

        Args:
            orders: List of TPSLOrder objects with token_id, market_id, outcome

        Returns:
            Dictionary mapping order.id to price (or None if failed)
        """
        try:
            from core.services.redis_price_cache import get_redis_cache
            from telegram_bot.services.price_calculator import PriceCalculator
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            if not orders:
                return {}

            # Create result dict and client
            redis_cache = get_redis_cache()
            client = ClobClient(host="https://clob.polymarket.com", chain_id=POLYGON)
            prices_by_order_id = {}

            # Get all token IDs for batch cache check
            token_ids = [order.token_id for order in orders]
            cached_prices = redis_cache.get_token_prices_batch(token_ids) if redis_cache else {}

            for order in orders:
                current_price = None

                try:
                    # Try 1: Redis cache (fastest)
                    if cached_prices and cached_prices.get(order.token_id):
                        current_price = cached_prices[order.token_id]
                        logger.debug(f"✅ TPSL price from Redis cache for order {order.id}: ${current_price:.4f}")
                    else:
                        # Try 2: Use PriceCalculator cascade (includes Poller fallback!)
                        # This is the KEY improvement - now includes Poller outcome_prices
                        fetched_price, source = PriceCalculator.get_price_for_position_display(
                            client=client,
                            token_id=order.token_id,
                            outcome=order.outcome.lower() if order.outcome else None,
                            fallback_price=float(order.entry_price) if order.entry_price else None,
                            market_id=order.market_id  # ✅ KEY: Pass market_id for Poller lookup
                        )

                        if fetched_price and fetched_price > 0:
                            current_price = fetched_price
                            logger.debug(f"✅ TPSL price for order {order.id} from {source}: ${current_price:.4f}")

                            # Cache this price
                            if redis_cache:
                                try:
                                    from config.config import MARKET_PRICE_TTL
                                    redis_cache.cache_token_price(order.token_id, current_price, ttl=MARKET_PRICE_TTL)
                                except Exception as cache_err:
                                    logger.warning(f"⚠️ Failed to cache price for TP/SL order {order.id}: {cache_err}")
                        else:
                            logger.warning(f"⚠️ No price found for TPSL order {order.id} (token_id={order.token_id[:10]}...)")

                except Exception as e:
                    logger.error(f"❌ Error fetching TPSL price for order {order.id}: {e}")
                    # Fallback to entry price if everything fails
                    current_price = float(order.entry_price) if order.entry_price else None

                prices_by_order_id[order.id] = current_price

            logger.debug(f"📊 TPSL batch complete: {sum(1 for p in prices_by_order_id.values() if p)} prices found out of {len(orders)}")
            return prices_by_order_id

        except Exception as e:
            logger.error(f"❌ GET PRICES FOR TPSL BATCH ERROR: {e}")
            return {order.id: None for order in orders}

    def get_market_display_data(self, market_id: str, user_context: str = "browsing") -> Optional[Dict]:
        """
        Get market data for display with context-aware pricing
        Integrates CLOB fresh pricing for detailed views

        Args:
            market_id: Market identifier
            user_context: 'browsing' (poller prices) or 'viewing_details' (CLOB fresh)

        Returns:
            Market dict with appropriate pricing data
        """
        try:
            # Get base market data (always from poller)
            market = self.get_market_by_id(market_id)
            if not market:
                return None

            # Add pricing based on context
            if user_context == "browsing":
                # Use poller prices (sufficient for list/discovery)
                market["price_source"] = "poller"
                market["price_freshness"] = "~60s"

            elif user_context == "viewing_details":
                # Get fresh CLOB prices for detailed market view
                fresh_prices = self._get_fresh_market_prices(market_id, market)
                if fresh_prices:
                    # Override outcome_prices with fresh data
                    market["outcome_prices"] = fresh_prices["midpoints"]
                    market["price_source"] = "clob_fresh"
                    market["price_freshness"] = "<5s"
                    market["spread"] = fresh_prices["spread"]
                    market["spread_pct"] = fresh_prices["spread_pct"]
                else:
                    # Fallback to poller if CLOB fails
                    market["price_source"] = "poller_fallback"
                    market["price_freshness"] = "~60s"
                    logger.warning(f"⚠️ CLOB fresh pricing failed for market {market_id}, using poller")

            else:
                # Unknown context - use poller
                market["price_source"] = "poller"
                market["price_freshness"] = "~60s"

            return market

        except Exception as e:
            logger.error(f"❌ Error getting display data for market {market_id}: {e}")
            return None

    def _get_fresh_market_prices(self, market_id: str, market: Dict) -> Optional[Dict]:
        """
        Get fresh prices from CLOB API for detailed market view
        Only called when user specifically views market details
        """
        try:
            from core.services.clob_pricing_service import get_clob_pricing_service

            # Extract token IDs from market data
            token_ids = market.get("clob_token_ids", [])
            if isinstance(token_ids, str):
                import json
                try:
                    token_ids = json.loads(token_ids)
                except:
                    token_ids = []

            if not token_ids or len(token_ids) < 2:
                logger.warning(f"⚠️ No valid token IDs for market {market_id}")
                return None

            # Get fresh prices (this method is sync, so we need to run async)
            clob_service = get_clob_pricing_service()
            return asyncio.run(clob_service.get_fresh_market_prices(market_id, token_ids))

        except Exception as e:
            logger.error(f"❌ Error getting fresh prices for market {market_id}: {e}")
            return None


# Global instance
market_service = MarketService()
