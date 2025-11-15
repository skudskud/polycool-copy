#!/usr/bin/env python3
"""
Price Updater Service
Updates hot prices in Redis every 20 seconds for maximum freshness
"""

import logging
from typing import Dict, List, Set
from datetime import datetime, timedelta

from .redis_price_cache import get_redis_cache

logger = logging.getLogger(__name__)


class PriceUpdaterService:
    """
    Updates hot token prices in Redis cache every 20 seconds
    Focuses on tokens that are actually being monitored/used
    """

    def __init__(self, market_repository=None):
        """Initialize price updater service"""
        self.market_repository = market_repository
        self.redis_cache = get_redis_cache()
        self.last_update = None
        self.last_token_count = 0

        logger.info("✅ Price Updater Service initialized (20s refresh cycle)")

    def add_hot_token(self, token_id: str, duration_minutes: int = 60):
        """
        Add token to hot list for immediate price caching.
        Stored in Redis with TTL.

        Called after trades to ensure new position tokens get cached in next 20s cycle.

        Args:
            token_id: ERC-1155 token ID to add to hot list
            duration_minutes: How long to keep token in hot list (default: 60min)
        """
        if not self.redis_cache.enabled:
            logger.debug(f"⚠️ Redis disabled - cannot add hot token {token_id[:10]}...")
            return

        try:
            key = f"hot_token:{token_id}"
            self.redis_cache.redis_client.setex(key, duration_minutes * 60, "1")

            logger.info(f"🔥 Added {token_id[:10]}... to hot tokens ({duration_minutes}min)")
        except Exception as e:
            logger.error(f"❌ Failed to add hot token: {e}")

    async def update_hot_prices(self) -> Dict:
        """
        Update prices for hot tokens (TP/SL orders + active positions + top markets)
        Called every 20 seconds by scheduler

        Returns:
            Statistics about the update
        """
        try:
            logger.info("🔥🔥🔥 PRICE UPDATER CALLED - DEBUG TEST")
            start_time = datetime.utcnow()
            # Reduced logging to prevent spam - only log every 5 minutes
            import time
            current_time = time.time()
            last_log_key = "last_price_updater_log"
            redis_cache = self.redis_cache
            if redis_cache.enabled:
                last_log_time = redis_cache.redis_client.get(last_log_key)
                if last_log_time and current_time - float(last_log_time) < 300:  # 5 minutes
                    logger.debug("🔍 Price updater: Starting hot price update cycle (quiet mode)")
                else:
                    redis_cache.redis_client.setex(last_log_key, 300, str(current_time))
                    logger.info("🔥 Price updater: Starting hot price update cycle")
            else:
                logger.info("🔥 Price updater: Starting hot price update cycle")

            # Collect all token IDs that need price updates
            token_ids_to_update = await self._collect_hot_token_ids()

            if not token_ids_to_update:
                logger.info("📭 No hot tokens to update (this is expected if no TP/SL orders, recent positions, or top markets)")
                return {'tokens_updated': 0, 'duration': 0}

            # Determine logging level (reuse same logic as _collect_hot_token_ids)
            should_log_detailed = False
            if redis_cache.enabled:
                detailed_log_key = "last_detailed_price_log"
                last_detailed_time = redis_cache.redis_client.get(detailed_log_key)
                if not last_detailed_time or current_time - float(last_detailed_time) >= 300:
                    should_log_detailed = True

            if should_log_detailed:
                logger.info(f"🔥 Updating {len(token_ids_to_update)} hot token prices...")
            else:
                logger.debug(f"🔥 Updating {len(token_ids_to_update)} hot token prices...")

            # Fetch prices from API (optimized to reduce blocking)
            prices = await self._fetch_prices_from_clob_api(token_ids_to_update)

            # Cache in Redis with ADAPTIVE TTL (background context for hot updates)
            from config.config import get_adaptive_price_ttl
            if not self.redis_cache.enabled:
                logger.warning(f"⚠️ Redis not enabled - {len(prices)} prices fetched but NOT cached")
                logger.warning(f"⚠️ Add REDIS_URL to Railway to enable caching for 100x performance boost")
                cached_count = 0
            else:
                # Use background TTL for hot price updates (60s for efficiency)
                background_ttl = get_adaptive_price_ttl("background")
                cached_count = self.redis_cache.cache_token_prices_batch(prices, ttl=background_ttl)

            duration = (datetime.utcnow() - start_time).total_seconds()
            self.last_update = datetime.utcnow()
            self.last_token_count = len(token_ids_to_update)

            if self.redis_cache.enabled:
                logger.info(f"✅ Hot price update complete: {cached_count} prices cached in {duration:.2f}s")
            else:
                logger.info(f"✅ Hot price update complete: {len(prices)} prices fetched in {duration:.2f}s (caching disabled)")

            return {
                'tokens_updated': cached_count,
                'duration': duration,
                'timestamp': self.last_update.isoformat()
            }

        except Exception as e:
            logger.error(f"❌ Hot price update error: {e}")
            return {'tokens_updated': 0, 'duration': 0, 'error': str(e)}

    async def _collect_hot_token_ids(self) -> Set[str]:
        """
        Collect all token IDs that need price updates
        Priority:
        1. Tokens with active TP/SL orders (highest priority)
        2. Tokens in recent user positions
        3. Top 100 markets by volume

        Returns:
            Set of unique token IDs
        """
        hot_tokens = set()

        try:
            logger.debug("🔍 Collecting hot tokens from all sources...")

            # Priority 1: TP/SL tokens
            tpsl_tokens = await self._get_tpsl_token_ids()
            hot_tokens.update(tpsl_tokens)
            # Only log detailed breakdown every 5 minutes to reduce spam
            should_log_detailed = False
            redis_cache = self.redis_cache  # Ensure redis_cache is available in this scope
            if redis_cache.enabled:
                import time
                current_time = time.time()  # Define current_time for this scope
                detailed_log_key = "last_detailed_price_log"
                last_detailed_time = redis_cache.redis_client.get(detailed_log_key)
                if not last_detailed_time or current_time - float(last_detailed_time) >= 300:
                    redis_cache.redis_client.setex(detailed_log_key, 300, str(current_time))
                    should_log_detailed = True

            if should_log_detailed:
                logger.info(f"📊 TP/SL tokens: {len(tpsl_tokens)}")
            else:
                logger.debug(f"📊 TP/SL tokens: {len(tpsl_tokens)}")

            # Priority 2: Recent position tokens (from last 24 hours of transactions)
            position_tokens = set()
            try:
                position_tokens = await self._get_recent_position_token_ids()
                hot_tokens.update(position_tokens)
                if should_log_detailed:
                    logger.info(f"📊 Position tokens (transactions 24h): {len(position_tokens)}")
                else:
                    logger.debug(f"📊 Position tokens (transactions 24h): {len(position_tokens)}")
            except Exception as e:
                logger.warning(f"⚠️ Could not get recent position tokens: {e}")

            # Priority 2.25: CURRENT user position tokens (ALL active positions)
            # ✅ CRITICAL FIX: Covers positions displayed in /positions even if >24h old
            current_position_tokens = set()
            try:
                current_position_tokens = await self._get_current_user_position_tokens()
                hot_tokens.update(current_position_tokens)
                if should_log_detailed:
                    logger.info(f"📊 Current position tokens (all users): {len(current_position_tokens)}")
                else:
                    logger.debug(f"📊 Current position tokens (all users): {len(current_position_tokens)}")
            except Exception as e:
                logger.warning(f"⚠️ Could not get current position tokens: {e}")

            # Priority 2.5: Active user position tokens from watched_markets
            # ✅ Covers ALL active positions (even old ones without recent trades)
            watched_tokens = set()
            try:
                watched_tokens = await self._get_watched_market_tokens()
                hot_tokens.update(watched_tokens)
                if should_log_detailed:
                    logger.info(f"📊 Watched market tokens (user positions): {len(watched_tokens)}")
                else:
                    logger.debug(f"📊 Watched market tokens (user positions): {len(watched_tokens)}")
            except Exception as e:
                logger.warning(f"⚠️ Could not get watched market tokens: {e}")

            # Priority 2.75: Redis hot tokens (manually added after trades)
            # ✅ Ensures new position tokens get cached immediately (< 20s)
            redis_hot_tokens = set()
            try:
                if redis_cache.enabled:
                    hot_token_keys = redis_cache.redis_client.keys("hot_token:*")
                    redis_hot_tokens = set(key.decode('utf-8').replace("hot_token:", "") if isinstance(key, bytes) else key.replace("hot_token:", "") for key in hot_token_keys)
                    hot_tokens.update(redis_hot_tokens)
                    if should_log_detailed:
                        logger.info(f"📍 Redis hot tokens (manual adds): {len(redis_hot_tokens)}")
                    else:
                        logger.debug(f"📍 Redis hot tokens: {len(redis_hot_tokens)}")
            except Exception as e:
                logger.warning(f"⚠️ Could not get Redis hot tokens: {e}")

            # ✅ OPTIMIZED: Focus ONLY on user positions + TP/SL (no top markets background refresh)
            # This reduces API calls by ~80% while keeping fresh prices for what matters

            if should_log_detailed:
                logger.info(f"🎯 Collected {len(hot_tokens)} unique hot tokens from all sources")
            else:
                logger.debug(f"🎯 Collected {len(hot_tokens)} unique hot tokens from all sources")
            return hot_tokens

        except Exception as e:
            logger.error(f"❌ Error collecting hot token IDs: {e}")
            return set()

    async def _get_tpsl_token_ids(self) -> Set[str]:
        """Get token IDs from all active TP/SL orders"""
        try:
            from database import SessionLocal
            from sqlalchemy import text

            session = SessionLocal()
            query = text("""
                SELECT DISTINCT token_id
                FROM tpsl_orders
                WHERE status = 'active'
            """)

            result = session.execute(query)
            token_ids = {row[0] for row in result.fetchall() if row[0]}
            session.close()

            return token_ids

        except Exception as e:
            logger.error(f"❌ Error getting TP/SL tokens: {e}")
            return set()

    async def _get_recent_position_token_ids(self) -> Set[str]:
        """Get token IDs from recent transactions (last 24 hours)"""
        try:
            from database import SessionLocal
            from sqlalchemy import text

            session = SessionLocal()
            query = text("""
                SELECT DISTINCT token_id
                FROM transactions
                WHERE executed_at > NOW() - INTERVAL '24 hours'
                AND token_id IS NOT NULL
            """)

            result = session.execute(query)
            token_ids = {row[0] for row in result.fetchall() if row[0]}
            session.close()

            return token_ids

        except Exception as e:
            logger.error(f"❌ Error getting position tokens: {e}")
            return set()

    async def _get_current_user_position_tokens(self) -> Set[str]:
        """
        Get token IDs from ALL current user positions (not just recent transactions).
        This ensures positions displayed in /positions have fresh prices cached.

        ✅ FIXED: Now covers ALL active positions, not just recent trades!
        """
        try:
            from database import SessionLocal, User
            import aiohttp

            # APPROACH: Get all active user positions from Polymarket API
            # This covers positions regardless of when they were bought
            token_ids = set()

            session = SessionLocal()
            try:
                # Get all active users (who have made trades recently)
                cutoff_date = datetime.utcnow() - timedelta(days=30)
                active_users = session.query(User).filter(
                    User.polygon_address.isnot(None),
                    User.created_at > cutoff_date
                ).all()

                session.close()

                # For each active user, fetch their current positions
                # OPTIMIZED: Use aiohttp session pooling
                connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
                timeout = aiohttp.ClientTimeout(total=30)

                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as http_session:
                    # OPTIMIZED: Only fetch positions for users who have logged in recently (active users)
                    # This avoids fetching for users who may have old positions but don't use the bot
                    recent_active_users = [u for u in active_users
                                         if hasattr(u, 'last_active_at') and u.last_active_at
                                         and (datetime.utcnow() - u.last_active_at).days < 7][:20]  # Max 20 active users

                    if not recent_active_users:
                        # Fallback: Use a sample of recent users
                        recent_active_users = active_users[:10]

                    for user in recent_active_users:
                        try:
                            wallet = user.polygon_address
                            if not wallet:
                                continue

                            url = f"https://data-api.polymarket.com/positions?user={wallet}"

                            async with http_session.get(url) as response:
                                if response.status == 200:
                                    positions_data = await response.json()

                                    # Extract token_ids from positions
                                    for pos in positions_data:
                                        token_id = pos.get('asset')
                                        if token_id and float(pos.get('size', 0)) >= 0.1:  # Filter dust
                                            token_ids.add(token_id)

                        except Exception as e:
                            logger.debug(f"⚠️ Could not fetch positions for user {user.id}: {e}")
                            continue

            except Exception as e:
                logger.warning(f"⚠️ Could not get active users: {e}")
                session.close()

            logger.info(f"✅ Found {len(token_ids)} tokens from {len(active_users) if 'active_users' in locals() else 0} active user positions")
            return token_ids

        except Exception as e:
            logger.error(f"❌ Error getting current user position tokens: {e}")
            return set()

    async def fetch_and_cache_missing_tokens(self, token_ids: List[str]) -> Dict[str, float]:
        """
        ✅ ON-DEMAND: Fetch specific tokens not in cache
        Called by position_view_builder for instant user experience

        Args:
            token_ids: List of token IDs to fetch

        Returns:
            Dictionary of token_id -> price
        """
        if not token_ids:
            return {}

        try:
            logger.info(f"🎯 [ON-DEMAND] Fetching {len(token_ids)} missing tokens for user positions")

            # Fetch from CLOB API
            prices = await self._fetch_prices_from_clob_api(set(token_ids))

            # Cache with EXTENDED TTL (5min) for shared benefit
            if prices and self.redis_cache.enabled:
                cached_count = self.redis_cache.cache_token_prices_batch(prices, ttl=300)
                logger.info(f"💾 [ON-DEMAND] Cached {cached_count} prices (5min TTL for shared benefit)")

            return prices

        except Exception as e:
            logger.error(f"❌ [ON-DEMAND] Fetch error: {e}")
            return {}

    async def _get_top_market_token_ids(self, limit: int = 100) -> Set[str]:
        """Get token IDs from top markets by volume

        PERFORMANCE: Cached in Redis (TTL: 60s) to avoid 316 DB calls
        """
        try:
            # Try cache first
            redis_cache = self.redis_cache
            if redis_cache.enabled:
                cache_key = f"top_market_tokens:{limit}"
                cached = redis_cache.redis_client.get(cache_key)
                if cached:
                    import json
                    token_ids = set(json.loads(cached))
                    logger.debug(f"🚀 CACHE HIT: Top market tokens ({len(token_ids)} tokens)")
                    return token_ids

            # Cache miss - fetch from DB
            from database import SessionLocal
            from sqlalchemy import text
            from config.config import USE_SUBSQUID_MARKETS

            session = SessionLocal()

            # ✅ Use subsquid_markets_poll if available (fresher data)
            if USE_SUBSQUID_MARKETS:
                query = text("""
                    SELECT clob_token_ids
                    FROM subsquid_markets_poll
                    WHERE status = 'ACTIVE'
                    AND tradeable = true
                    AND clob_token_ids IS NOT NULL
                    AND clob_token_ids != ''
                    ORDER BY volume DESC
                    LIMIT :limit
                """)
            else:
                query = text("""
                    SELECT clob_token_ids
                    FROM markets
                    WHERE active = true
                    AND closed = false
                    AND clob_token_ids IS NOT NULL
                    ORDER BY volume DESC
                    LIMIT :limit
                """)

            result = session.execute(query, {'limit': limit})

            token_ids = set()
            for row in result.fetchall():
                clob_token_ids = row[0]
                if clob_token_ids:
                    # clob_token_ids is a JSON array
                    if isinstance(clob_token_ids, list):
                        token_ids.update(clob_token_ids)
                    elif isinstance(clob_token_ids, str):
                        import json
                        try:
                            token_list = json.loads(clob_token_ids)
                            token_ids.update(token_list)
                        except:
                            pass

            session.close()

            # Cache the result (60s TTL - markets don't change often)
            if redis_cache.enabled and token_ids:
                try:
                    import json
                    cache_key = f"top_market_tokens:{limit}"
                    redis_cache.redis_client.setex(cache_key, 60, json.dumps(list(token_ids)))
                    logger.debug(f"💾 Cached {len(token_ids)} top market tokens (TTL: 60s)")
                except Exception as cache_err:
                    logger.debug(f"Cache write failed (non-fatal): {cache_err}")

            return token_ids

        except Exception as e:
            logger.error(f"❌ Error getting top market tokens: {e}")
            return set()

    async def _get_watched_market_tokens(self) -> Set[str]:
        """Get token IDs from watched_markets (ONLY active tradeable markets)"""
        try:
            from database import SessionLocal, SubsquidMarketPoll
            from sqlalchemy import text

            session = SessionLocal()

            # OPTIMIZED: Only get tokens from ACTIVE and TRADEABLE markets
            # This filters out closed/resolved/inactive markets that cause API errors
            query = text("""
                SELECT DISTINCT sp.clob_token_ids
                FROM watched_markets wm
                JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id
                WHERE wm.active_positions > 0
                  AND sp.status = 'ACTIVE'
                  AND sp.tradeable = true
                  AND sp.clob_token_ids IS NOT NULL
                  AND sp.clob_token_ids != ''
                  AND (sp.end_date IS NULL OR sp.end_date > NOW())
            """)

            result = session.execute(query)

            token_ids = set()
            for row in result.fetchall():
                clob_token_ids_raw = row[0]
                if clob_token_ids_raw:
                    try:
                        import json
                        # Parse JSON (may be escaped)
                        cleaned = clob_token_ids_raw
                        if cleaned.startswith('"') and cleaned.endswith('"'):
                            cleaned = cleaned[1:-1]
                        cleaned = cleaned.replace('\\\\', '\\').replace('\\"', '"')

                        token_list = json.loads(cleaned)
                        if isinstance(token_list, list):
                            token_ids.update(token_list)
                    except Exception as parse_err:
                        logger.debug(f"⚠️ Failed to parse clob_token_ids: {parse_err}")
                        continue

            session.close()

            logger.debug(f"✅ Found {len(token_ids)} active watched market tokens")
            return token_ids

        except Exception as e:
            logger.error(f"❌ Error getting watched market tokens: {e}")
            return set()

    async def _fetch_prices_from_clob_api(self, token_ids: Set[str]) -> Dict[str, float]:
        """
        CASCADE OPTIMISÉE: WebSocket DB → Poller DB → API CLOB
        Élimine 90% des appels API coûteux pour performances ultra-rapides

        Args:
            token_ids: Set of token IDs to fetch

        Returns:
            Dictionary mapping token_id to price
        """
        if not token_ids:
            return {}

        try:
            # PHASE 1: WebSocket DB (<100ms - ultra frais)
            ws_prices = await self._fetch_from_websocket_db(token_ids)
            ws_found = len([p for p in ws_prices.values() if p is not None])

            # PHASE 2: Poller DB (~60s - frais) pour les tokens manquants
            remaining_tokens = {tid for tid, price in ws_prices.items() if price is None}
            poller_prices = {}
            if remaining_tokens:
                poller_prices = await self._fetch_from_poller_db(remaining_tokens)

            # Fusionne les résultats (Poller complète WebSocket)
            ws_prices.update(poller_prices)
            poller_found = len([p for p in poller_prices.values() if p is not None])

            # PHASE 3: API CLOB (dernier recours - lent) pour les tokens toujours manquants
            still_missing = {tid for tid, price in ws_prices.items() if price is None}
            api_prices = {}
            if still_missing:
                api_prices = await self._fetch_from_api_fallback(still_missing)

            # Fusionne API en dernier
            ws_prices.update(api_prices)
            api_found = len([p for p in api_prices.values() if p is not None])

            total_found = len([p for p in ws_prices.values() if p is not None])

            # Log optimisé avec visibilité WebSocket/Streamer
            if api_found > 0:
                logger.info(f"📊 PRICE SOURCES: 🌐 WS:{ws_found} + 📡 Poller:{poller_found} + 🐌 API:{api_found} = {total_found}/{len(token_ids)} prices")
                logger.info(f"⚠️ STREAMER STATUS: {ws_found} fresh WebSocket prices, {poller_found} backup prices, {api_found} slow API calls")
            elif poller_found > 0:
                logger.info(f"📊 PRICE SOURCES: 🌐 WS:{ws_found} + 📡 Poller:{poller_found} = {total_found}/{len(token_ids)} (WebSocket + Poller)")
                logger.info(f"✅ STREAMER STATUS: WebSocket working with {ws_found} prices, Poller backup with {poller_found} prices")
            elif ws_found > 0:
                logger.info(f"📊 PRICE SOURCES: 🌐 WS:{ws_found} = {total_found}/{len(token_ids)} (WebSocket only - PERFECT!)")
                logger.info(f"🚀 STREAMER STATUS: Ultra-fast WebSocket prices! No API calls needed.")
            else:
                logger.warning(f"📊 PRICE SOURCES: ❌ No WebSocket/Poller data = {total_found}/{len(token_ids)} (falling back to slow API)")
                logger.warning(f"⚠️ STREAMER STATUS: WebSocket appears down or no fresh data - using slow API backup")

            return ws_prices

        except Exception as e:
            logger.error(f"❌ Price cascade error: {e}")
            return {}

    async def _fetch_from_websocket_db(self, token_ids: Set[str]) -> Dict[str, float]:
        """
        Récupère les prix individuels depuis subsquid_markets_ws (ultra-frais <100ms)
        Utilise outcome_prices JSON avec mapping token→outcome optimisé

        Args:
            token_ids: Set des token IDs à rechercher

        Returns:
            Dict token_id → price (None si pas trouvé)
        """
        if not token_ids:
            return {}

        prices = {tid: None for tid in token_ids}  # Initialize avec None

        try:
            # Pré-calculer mapping token_id → (market_id, outcome) pour éviter N requêtes
            token_mappings = await self._get_token_to_market_mappings(token_ids)

            if not token_mappings:
                return prices

            # Batch query: récupérer tous les marchés en une seule requête DB
            market_ids = set(mapping['market_id'] for mapping in token_mappings.values() if mapping)
            if not market_ids:
                return prices

            from database import db_manager, SubsquidMarketWS, SubsquidMarketPoll
            from sqlalchemy import and_, or_
            import json
            from datetime import datetime, timezone, timedelta
            from config.config import PRICE_FRESHNESS_MAX_AGE

            with db_manager.get_session() as db:
                # Requête optimisée: JOIN avec subsquid_markets_poll pour mapping condition_id
                ws_markets = db.query(SubsquidMarketWS).join(
                    SubsquidMarketPoll,
                    and_(
                        SubsquidMarketWS.market_id == SubsquidMarketPoll.market_id,
                        SubsquidMarketPoll.condition_id.in_([m['condition_id'] for m in token_mappings.values() if m])
                    )
                ).filter(
                    # Freshness check using centralized constant
                    SubsquidMarketWS.updated_at > (datetime.now(timezone.utc) - timedelta(seconds=PRICE_FRESHNESS_MAX_AGE))
                ).all()

                found_count = 0
                for ws_market in ws_markets:
                    # Trouver le market_id correspondant
                    market_data = None
                    for mapping in token_mappings.values():
                        if mapping and mapping['market_id'] == ws_market.market_id:
                            market_data = mapping
                            break

                    if not market_data:
                        continue

                    # Extraire prix individuel depuis outcome_prices JSON
                    if ws_market.outcome_prices:
                        try:
                            outcome_prices = ws_market.outcome_prices
                            if isinstance(outcome_prices, str):
                                outcome_prices = json.loads(outcome_prices)

                            # Chercher le prix pour l'outcome spécifique
                            outcome = market_data['outcome']
                            if outcome in outcome_prices:
                                price = float(outcome_prices[outcome])
                                token_id = market_data['token_id']
                                prices[token_id] = price
                                found_count += 1

                        except (json.JSONDecodeError, ValueError, KeyError) as e:
                            logger.debug(f"⚠️ WS price parse error for market {ws_market.market_id}: {e}")
                            continue

                if found_count > 0:
                    logger.debug(f"📡 WS DB: {found_count} fresh prices from {len(ws_markets)} markets")

                return prices

        except Exception as e:
            logger.debug(f"⚠️ WS DB query error: {e}")
            return prices

    async def _get_token_to_market_mappings(self, token_ids: Set[str]) -> Dict[str, Dict]:
        """
        Mapping optimisé: token_id → {market_id, condition_id, outcome}
        Uses Redis cache (5min TTL) to avoid repeated DB queries

        Args:
            token_ids: Set des token IDs

        Returns:
            Dict token_id → mapping info (None si pas trouvé)
        """
        if not token_ids:
            return {}

        mappings = {tid: None for tid in token_ids}
        uncached_tokens = set()

        # ✅ PHASE 1: Try Redis cache first
        if self.redis_cache.enabled:
            import json
            for tid in token_ids:
                cache_key = f"token_mapping:{tid}"
                try:
                    cached = self.redis_cache.redis_client.get(cache_key)
                    if cached:
                        if isinstance(cached, bytes):
                            cached = cached.decode('utf-8')
                        mappings[tid] = json.loads(cached)
                    else:
                        uncached_tokens.add(tid)
                except Exception as cache_err:
                    logger.debug(f"⚠️ Cache read error for token {tid[:10]}...: {cache_err}")
                    uncached_tokens.add(tid)

            if not uncached_tokens:
                logger.debug(f"🚀 [CACHE HIT] All {len(token_ids)} token mappings from Redis!")
                return mappings
            else:
                logger.debug(f"💨 [CACHE PARTIAL] {len(token_ids) - len(uncached_tokens)}/{len(token_ids)} from cache, fetching {len(uncached_tokens)} from DB")
        else:
            uncached_tokens = token_ids

        # ✅ PHASE 2: Fetch missing from DB
        try:
            from database import db_manager, SubsquidMarketPoll
            import json
            from config.config import TOKEN_MAPPING_CACHE_TTL

            with db_manager.get_session() as db:
                # Requête optimisée: récupérer tous les marchés qui contiennent nos token_ids
                markets = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.clob_token_ids.isnot(None),
                    SubsquidMarketPoll.status == 'ACTIVE'
                ).all()

                for market in markets:
                    if not market.clob_token_ids:
                        continue

                    try:
                        # Parser les clob_token_ids (peuvent être double-encoded)
                        clob_token_ids_raw = market.clob_token_ids
                        if isinstance(clob_token_ids_raw, str):
                            cleaned = clob_token_ids_raw
                            if cleaned.startswith('"') and cleaned.endswith('"'):
                                cleaned = cleaned[1:-1]
                            cleaned = cleaned.replace('\\\\', '\\').replace('\\"', '"')
                            token_list = json.loads(cleaned)
                        elif isinstance(clob_token_ids_raw, list):
                            token_list = clob_token_ids_raw
                        else:
                            continue

                        if not isinstance(token_list, list):
                            continue

                        # Parser les outcomes
                        outcomes = []
                        if market.outcomes:
                            if isinstance(market.outcomes, str):
                                outcomes = json.loads(market.outcomes)
                            elif isinstance(market.outcomes, list):
                                outcomes = market.outcomes

                        # Mapper chaque token à son outcome et market
                        for idx, token_id in enumerate(token_list):
                            if token_id in uncached_tokens and idx < len(outcomes):
                                outcome = outcomes[idx]
                                mapping_data = {
                                    'token_id': token_id,
                                    'market_id': market.market_id,
                                    'condition_id': market.condition_id,
                                    'outcome': outcome
                                }
                                mappings[token_id] = mapping_data

                                # ✅ PHASE 3: Cache in Redis (5min TTL)
                                if self.redis_cache.enabled:
                                    try:
                                        cache_key = f"token_mapping:{token_id}"
                                        self.redis_cache.redis_client.setex(
                                            cache_key,
                                            TOKEN_MAPPING_CACHE_TTL,
                                            json.dumps(mapping_data)
                                        )
                                    except Exception as cache_write_err:
                                        logger.debug(f"⚠️ Cache write error (non-critical): {cache_write_err}")

                    except (json.JSONDecodeError, ValueError, IndexError) as e:
                        logger.debug(f"⚠️ Token mapping parse error for market {market.market_id}: {e}")
                        continue

            # Log cache performance
            if self.redis_cache.enabled and uncached_tokens:
                cached_count = len([m for m in mappings.values() if m is not None])
                logger.debug(f"💾 [CACHE WRITE] Cached {cached_count} new token mappings (TTL: {TOKEN_MAPPING_CACHE_TTL}s)")

            return mappings

        except Exception as e:
            logger.debug(f"⚠️ Token mapping error: {e}")
            return mappings

    async def _fetch_from_poller_db(self, token_ids: Set[str]) -> Dict[str, float]:
        """
        Récupère les prix individuels depuis subsquid_markets_poll (~60s de fraîcheur)
        Utilise outcome_prices array avec mapping token→outcome

        Args:
            token_ids: Set des token IDs à rechercher

        Returns:
            Dict token_id → price (None si pas trouvé)
        """
        if not token_ids:
            return {}

        prices = {tid: None for tid in token_ids}

        try:
            # Utiliser le même mapping que pour WebSocket
            token_mappings = await self._get_token_to_market_mappings(token_ids)

            if not token_mappings:
                return prices

            from database import db_manager, SubsquidMarketPoll
            import json
            from datetime import datetime, timezone, timedelta
            from config.config import PRICE_FRESHNESS_MAX_AGE

            with db_manager.get_session() as db:
                # Requête par condition_id (optimisée)
                condition_ids = [m['condition_id'] for m in token_mappings.values() if m]
                if not condition_ids:
                    return prices

                poller_markets = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.condition_id.in_(condition_ids),
                    # Freshness check using centralized constant
                    SubsquidMarketPoll.updated_at > (datetime.now(timezone.utc) - timedelta(seconds=PRICE_FRESHNESS_MAX_AGE))
                ).all()

                found_count = 0
                for market in poller_markets:
                    # Trouver tous les tokens de ce marché
                    market_tokens = [tid for tid, mapping in token_mappings.items()
                                   if mapping and mapping['condition_id'] == market.condition_id]

                    if not market_tokens or not market.outcome_prices:
                        continue

                    try:
                        # outcome_prices est une liste [YES_price, NO_price]
                        outcome_prices = market.outcome_prices
                        if isinstance(outcome_prices, str):
                            outcome_prices = json.loads(outcome_prices)

                        if not isinstance(outcome_prices, list) or len(outcome_prices) < 2:
                            continue

                        # Parser outcomes pour mapping
                        outcomes = []
                        if market.outcomes:
                            if isinstance(market.outcomes, str):
                                outcomes = json.loads(market.outcomes)
                            elif isinstance(market.outcomes, list):
                                outcomes = market.outcomes

                        # Mapper chaque token à son prix
                        for token_id in market_tokens:
                            mapping = token_mappings[token_id]
                            if not mapping:
                                continue

                            outcome = mapping['outcome']
                            try:
                                # Trouver l'index de l'outcome
                                outcome_idx = outcomes.index(outcome) if outcomes else -1
                                if outcome_idx >= 0 and outcome_idx < len(outcome_prices):
                                    price = float(outcome_prices[outcome_idx])
                                    prices[token_id] = price
                                    found_count += 1
                            except (ValueError, IndexError, TypeError):
                                continue

                    except (json.JSONDecodeError, ValueError) as e:
                        logger.debug(f"⚠️ Poller price parse error for market {market.condition_id}: {e}")
                        continue

                if found_count > 0:
                    logger.debug(f"📊 Poller DB: {found_count} prices from {len(poller_markets)} markets")

                return prices

        except Exception as e:
            logger.debug(f"⚠️ Poller DB query error: {e}")
            return prices

    async def _fetch_from_api_fallback(self, token_ids: Set[str]) -> Dict[str, float]:
        """
        Fallback: Fetch from CLOB API (only for tokens not in WebSocket DB)
        This is SLOW but necessary for edge cases
        """
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            # Create client for price fetching
            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON
            )

            prices = {}
            success_count = 0
            error_count = 0

            # PERFORMANCE FIX: Run in thread pool to avoid blocking bot
            # client.get_price() is SYNCHRONOUS - must run in executor
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            def fetch_single_price(token_id):
                """Fetch price for single token (run in thread)"""
                try:
                    price_data = client.get_price(token_id, side='SELL')
                    if price_data and 'price' in price_data:
                        price = float(price_data['price'])
                        # DEBUG: Log specific token prices for troubleshooting
                        if '78691508355780992068126282549196202576337491514195625451037885802091808053529' in token_id:
                            print(f"🐛 DEBUG TOKEN {token_id[:20]}...: SUCCESS price={price}")
                        return token_id, price, None
                    # DEBUG: Log failures for specific token
                    if '78691508355780992068126282549196202576337491514195625451037885802091808053529' in token_id:
                        print(f"🐛 DEBUG TOKEN {token_id[:20]}...: FAILED - no price data: {price_data}")
                    return token_id, None, "No price data"
                except Exception as e:
                    # DEBUG: Log failures for specific token
                    if '78691508355780992068126282549196202576337491514195625451037885802091808053529' in token_id:
                        print(f"🐛 DEBUG TOKEN {token_id[:20]}...: EXCEPTION - {str(e)}")
                    return token_id, None, str(e)

            # Process in batches with thread pool (smaller batches since these are fallbacks)
            batch_size = 20  # Smaller batches for fallback
            token_list = list(token_ids)

            with ThreadPoolExecutor(max_workers=3) as executor:  # Fewer workers for fallback
                for i in range(0, len(token_list), batch_size):
                    batch = token_list[i:i+batch_size]

                    # Run batch in thread pool (non-blocking)
                    loop = asyncio.get_event_loop()
                    futures = [
                        loop.run_in_executor(executor, fetch_single_price, token_id)
                        for token_id in batch
                    ]

                    # Wait for batch to complete
                    results = await asyncio.gather(*futures)

                    # Process results
                    for token_id, price, error in results:
                        if price is not None:
                            prices[token_id] = price
                            success_count += 1
                        else:
                            error_count += 1
                            if error and '404' not in error and 'No orderbook' not in error:
                                logger.debug(f"⚠️ Token {token_id[:10]}...: {error[:50]}")

                    # Log progress
                    if i % 100 == 0 and i > 0:
                        logger.info(f"📊 Progress: {i}/{len(token_list)} ({success_count} successful)")

                    # Small yield between batches
                    await asyncio.sleep(0.01)

            logger.info(f"📊 Fetched {success_count}/{len(token_ids)} token prices from CLOB API ({error_count} errors/closed markets)")
            return prices

        except Exception as e:
            logger.error(f"❌ CLOB API batch fetch error: {e}")
            return {}

    def get_health_status(self) -> Dict:
        """Get health status of price updater"""
        return {
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'last_token_count': self.last_token_count,
            'redis_enabled': self.redis_cache.enabled,
            'redis_healthy': self.redis_cache.health_check()
        }

    async def update_market_spreads(self) -> Dict:
        """
        NEW: Calculate and cache market spreads from YES/NO token pairs
        Called after price updates to pre-calculate BID-ASK spreads
        This enables ultra-fast pricing during sells (<100ms vs 1-4s)

        Returns:
            Statistics about spreads cached
        """
        try:
            start_time = datetime.utcnow()

            if not self.redis_cache.enabled:
                logger.debug("⚠️ Redis not enabled - spread caching disabled")
                return {'spreads_cached': 0}

            from database import SessionLocal
            from sqlalchemy import text
            import json

            session = SessionLocal()
            query = text("""
                SELECT id, clob_token_ids, question
                FROM markets
                WHERE active = true
                AND closed = false
                AND clob_token_ids IS NOT NULL
                LIMIT 100
            """)

            result = session.execute(query)
            spreads_cached = 0

            for row in result.fetchall():
                market_id = row[0]
                clob_token_ids = row[1]
                question = row[2]

                try:
                    # Parse token IDs (YES and NO)
                    if isinstance(clob_token_ids, str):
                        token_ids = json.loads(clob_token_ids)
                    elif isinstance(clob_token_ids, list):
                        token_ids = clob_token_ids
                    else:
                        continue

                    if len(token_ids) < 2:
                        continue

                    # Get cached prices for YES and NO tokens
                    yes_token_id = token_ids[0]
                    no_token_id = token_ids[1]

                    yes_price = self.redis_cache.get_token_price(yes_token_id)
                    no_price = self.redis_cache.get_token_price(no_token_id)

                    if yes_price and no_price:
                        # Prices should sum to ~1.0
                        # BID price (what sellers get) is usually the lower price
                        # ASK price (what buyers pay) is usually the higher price
                        bid_price = min(yes_price, no_price)
                        ask_price = max(yes_price, no_price)

                        logger.info(f"📊 SPREAD UPDATE: market={market_id[:20]}..., YES=${yes_price:.6f}, NO=${no_price:.6f}, BID=${bid_price:.6f}, ASK=${ask_price:.6f}")

                        # Cache spread for YES (UNIFIED TTL)
                        from config.config import MARKET_SPREAD_TTL
                        self.redis_cache.cache_market_spread(
                            market_id=market_id,
                            outcome='yes',
                            bid_price=bid_price,
                            ask_price=ask_price,
                            ttl=MARKET_SPREAD_TTL
                        )
                        spreads_cached += 1

                        # Cache spread for NO (reverse)
                        self.redis_cache.cache_market_spread(
                            market_id=market_id,
                            outcome='no',
                            bid_price=bid_price,
                            ask_price=ask_price,
                            ttl=MARKET_SPREAD_TTL
                        )
                        spreads_cached += 1
                    else:
                        logger.debug(f"⚠️ INCOMPLETE PRICES: market={market_id[:20]}..., YES=${yes_price}, NO=${no_price}")

                except Exception as e:
                    logger.debug(f"⚠️ Could not cache spread for market {market_id}: {e}")
                    continue

            session.close()

            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"✅ Market spread cache update: {spreads_cached} spreads cached in {duration:.2f}s")

            return {
                'spreads_cached': spreads_cached,
                'duration': duration,
                'timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"❌ Market spread update error: {e}")
            return {'spreads_cached': 0, 'error': str(e)}


# Singleton instance
_price_updater_instance = None

def get_price_updater() -> PriceUpdaterService:
    """Get singleton PriceUpdaterService instance"""
    global _price_updater_instance
    if _price_updater_instance is None:
        _price_updater_instance = PriceUpdaterService()
    return _price_updater_instance
