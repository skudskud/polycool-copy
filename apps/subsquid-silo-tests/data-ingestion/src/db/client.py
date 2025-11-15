"""
Database Client for Subsquid Silo Tests
Handles asyncpg connections, upserts, and idempotency for subsquid_* tables.
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import asyncpg
from asyncpg import Pool

from ..config import settings, TABLES

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Async database client for subsquid silo operations"""

    def __init__(self):
        self.pool: Optional[Pool] = None

    async def connect(self):
        """Initialize connection pool"""
        try:
            self.pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=1,  # Reduced from 5 to 1 to avoid exhausting Supabase pooler
                max_size=3,  # Reduced from 20 to 3 for lighter services like Streamer
                timeout=30.0,  # Increased from 10s to 30s for Railway/Supabase
                command_timeout=60.0,  # Set command timeout as well
                statement_cache_size=0  # ✅ FIX: Disable prepared statements for PgBouncer compatibility
            )
            logger.info("✅ Database connection pool established")
        except Exception as e:
            logger.error(f"❌ Failed to connect to database: {e}")
            raise

    async def disconnect(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("✅ Database connection pool closed")

    # ========================================
    # Polling (Gamma API) - subsquid_markets_poll
    # ========================================
    async def upsert_markets_poll(self, markets: List[Dict[str, Any]], skip_filter: bool = False, skip_locked: bool = False) -> int:
        """
        Upsert markets from Gamma API polling into subsquid_markets_poll.

        OPT 5: Filters markets BEFORE upsert to reduce DB write load

        Args:
            markets: List of enriched market dicts from Gamma API
            skip_filter: If True, bypass OPT 5 filter (used for PASS 3 closed markets)
            skip_locked: If True, use FOR UPDATE SKIP LOCKED to avoid blocking bot queries

        Returns:
            Number of rows inserted/updated
        """
        if not self.pool or not markets:
            logger.debug(f"⚠️ Upsert skipped: pool={self.pool is not None}, markets={len(markets) if markets else 0}")
            return 0

        # OPT 5: FILTER markets BEFORE upsert (reduce 77k → 10k markets)
        # BYPASS when skip_filter=True (PASS 3 lifecycle management)
        if not skip_filter:
            original_count = len(markets)
            filtered_markets = []

            for market in markets:
                status = market.get('status', '')
                volume = float(market.get('volume', 0) or 0)
                volume_24hr = float(market.get('volume_24hr', 0) or 0)

                # Keep market if:
                # 1. ACTIVE (always keep active markets)
                # 2. Has any volume (historical data)
                # 3. Has 24hr volume (recently traded)
                if status == 'ACTIVE' or volume > 0 or volume_24hr > 0:
                    filtered_markets.append(market)

            if len(filtered_markets) < original_count:
                logger.info(f"🔥 OPT 5: Filtered {original_count} → {len(filtered_markets)} markets ({original_count - len(filtered_markets)} low-value markets skipped)")

            markets = filtered_markets

            if not markets:
                logger.debug(f"⚠️ No markets left after filtering")
                return 0
        else:
            logger.debug(f"⚠️ OPT 5 filter bypassed (skip_filter=True)")

        logger.debug(f"🔵 Starting upsert of {len(markets)} markets")

        # Add SKIP LOCKED clause if requested (non-blocking upserts)
        lock_clause = "FOR UPDATE SKIP LOCKED" if skip_locked else ""

        query = f"""
            INSERT INTO {TABLES['markets_poll']}
            (market_id, condition_id, slug, title, description, category,
             status, accepting_orders, archived, tradeable,
             outcomes, outcome_prices, last_mid,
             volume, volume_24hr, volume_1wk, volume_1mo,
             liquidity, spread,
             created_at, end_date, resolution_date,
             price_change_1h, price_change_1d, price_change_1w,
             clob_token_ids, tokens, events, market_type, restricted,
             resolution_status, winning_outcome, polymarket_url, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10,
                    $11, $12, $13,
                    $14, $15, $16, $17,
                    $18, $19,
                    $20, $21, $22,
                    $23, $24, $25,
                    $26, $27, $28, $29, $30,
                    $31, $32, $33, now())
            ON CONFLICT (market_id) DO UPDATE SET
                condition_id = EXCLUDED.condition_id,
                slug = EXCLUDED.slug,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                status = EXCLUDED.status,
                accepting_orders = EXCLUDED.accepting_orders,
                archived = EXCLUDED.archived,
                tradeable = EXCLUDED.tradeable,
                outcomes = EXCLUDED.outcomes,
                outcome_prices = EXCLUDED.outcome_prices,
                last_mid = EXCLUDED.last_mid,
                volume = EXCLUDED.volume,
                volume_24hr = EXCLUDED.volume_24hr,
                volume_1wk = EXCLUDED.volume_1wk,
                volume_1mo = EXCLUDED.volume_1mo,
                liquidity = EXCLUDED.liquidity,
                spread = EXCLUDED.spread,
                created_at = EXCLUDED.created_at,
                end_date = EXCLUDED.end_date,
                resolution_date = EXCLUDED.resolution_date,
                price_change_1h = EXCLUDED.price_change_1h,
                price_change_1d = EXCLUDED.price_change_1d,
                price_change_1w = EXCLUDED.price_change_1w,
                clob_token_ids = CASE
                    WHEN EXCLUDED.clob_token_ids IS NOT NULL
                         AND array_length(EXCLUDED.clob_token_ids, 1) > 0
                    THEN EXCLUDED.clob_token_ids
                    ELSE subsquid_markets_poll.clob_token_ids
                END,  -- 🔥 CRITICAL: Preserve existing clob_token_ids if new data is empty!
                tokens = CASE
                    WHEN EXCLUDED.tokens IS NOT NULL
                         AND array_length(EXCLUDED.tokens, 1) > 0
                    THEN EXCLUDED.tokens
                    ELSE subsquid_markets_poll.tokens
                END,  -- 🔥 CRITICAL: Preserve existing tokens if new data is empty!
                events = CASE
                    WHEN EXCLUDED.events IS NOT NULL
                         AND EXCLUDED.events::text != '[]'::text
                         AND EXCLUDED.events::text != 'null'::text
                    THEN EXCLUDED.events
                    ELSE subsquid_markets_poll.events
                END,  -- CRITICAL: Preserve existing events if new data doesn't have it!
                market_type = EXCLUDED.market_type,
                restricted = EXCLUDED.restricted,
                resolution_status = EXCLUDED.resolution_status,
                winning_outcome = EXCLUDED.winning_outcome,
                polymarket_url = EXCLUDED.polymarket_url,
                updated_at = now()
            {lock_clause}
        """

        try:
            import json

            def _as_array(value):
                if isinstance(value, list):
                    return value
                if isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            return parsed
                        return [parsed]
                    except Exception:
                        return [value]
                if value is None:
                    return []
                return list(value) if isinstance(value, (tuple, set)) else [value]

            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    count = 0
                    batch: List[tuple] = []

                    async def flush_batch(records: List[tuple]):
                        nonlocal count
                        if not records:
                            return
                        try:
                            await conn.executemany(
                                query,
                                records,
                                timeout=settings.DB_UPSERT_TIMEOUT_SECONDS
                            )
                            count += len(records)
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"⚠️ Upsert batch timed out (size={len(records)}); retrying row by row"
                            )
                            for record in records:
                                try:
                                    await conn.execute(
                                        query,
                                        *record,
                                        timeout=settings.DB_UPSERT_TIMEOUT_SECONDS
                                    )
                                    count += 1
                                except Exception as row_err:
                                    logger.error(f"❌ Upsert failed for market {record[0]}: {row_err}", exc_info=True)

                    for market in markets:
                        # ✅ FIX: Normalize events before JSON encoding to prevent double-escaping
                        # If events is already a JSON string (from DB corruption), parse it first
                        # This prevents the poller from re-encoding strings and creating nested escaping
                        events_data = market.get("events", [])

                        # Defensive: Only normalize if it's actually a string (corrupted data)
                        # If it's already a list/dict, keep it as-is (good data)
                        if isinstance(events_data, str):
                            try:
                                # Try to parse the over-escaped string
                                events_data = json.loads(events_data)
                                logger.debug(f"🔧 Normalized over-escaped events string for market {market.get('market_id')}")
                            except (json.JSONDecodeError, TypeError):
                                logger.warning(f"⚠️ Failed to parse events string for market {market.get('market_id')}, using empty array")
                                events_data = []

                        # Final validation: Ensure events_data is a list of dicts
                        if not isinstance(events_data, list):
                            events_data = []

                        events_json = json.dumps(events_data) if events_data else json.dumps([])

                        # ✅ FIX: Normalize clob_token_ids before JSON encoding to prevent double-escaping
                        # If clob_token_ids is already a JSON string (from DB corruption), parse it first
                        clob_data = market.get("clob_token_ids", [])
                        if isinstance(clob_data, str):
                            try:
                                # Try to parse the over-escaped string
                                clob_data = json.loads(clob_data)
                                logger.debug(f"🔧 Normalized over-escaped clob_token_ids string for market {market.get('market_id')}")
                            except (json.JSONDecodeError, TypeError):
                                logger.warning(f"⚠️ Failed to parse clob_token_ids string for market {market.get('market_id')}, using empty array")
                                clob_data = []
                        clob_tokens = json.dumps(clob_data) if clob_data else None

                        # ✅ FIX: Normalize tokens before JSON encoding to prevent double-escaping
                        tokens_data = market.get("tokens", [])
                        if isinstance(tokens_data, str):
                            try:
                                # Try to parse the over-escaped string
                                tokens_data = json.loads(tokens_data)
                                logger.debug(f"🔧 Normalized over-escaped tokens string for market {market.get('market_id')}")
                            except (json.JSONDecodeError, TypeError):
                                logger.warning(f"⚠️ Failed to parse tokens string for market {market.get('market_id')}, using empty array")
                                tokens_data = []
                        tokens_json = json.dumps(tokens_data) if tokens_data else None

                        # Removed verbose per-market logging to prevent Railway rate limiting

                        batch.append((
                            market.get("market_id"),
                            market.get("condition_id"),
                            market.get("slug"),
                            market.get("title"),
                            market.get("description"),
                            market.get("category"),
                            market.get("status"),
                            market.get("accepting_orders", False),
                            market.get("archived", False),
                            market.get("tradeable", False),
                            _as_array(market.get("outcomes")),  # TEXT[] array
                            _as_array(market.get("outcome_prices")),  # NUMERIC[] array
                            market.get("last_mid"),
                            market.get("volume"),
                            market.get("volume_24hr"),
                            market.get("volume_1wk"),
                            market.get("volume_1mo"),
                            market.get("liquidity"),
                            market.get("spread"),
                            market.get("created_at"),
                            market.get("end_date"),
                            market.get("resolution_date"),
                            market.get("price_change_1h"),
                            market.get("price_change_1d"),
                            market.get("price_change_1w"),
                            clob_tokens,
                            tokens_json,  # 🔥 NOUVEAU: Champ tokens pour token lookup
                            events_json,
                            market.get("market_type", "normal"),
                            market.get("restricted", False),
                            market.get("resolution_status", "PENDING"),  # NEW
                            market.get("winning_outcome"),  # NEW
                            market.get("polymarket_url", ""),  # NEW
                        ))

                        if len(batch) >= settings.DB_UPSERT_BATCH_SIZE:
                            await flush_batch(batch)
                            batch = []

                    if batch:
                        await flush_batch(batch)

            logger.info(f"✅ Upserted {count} enriched markets into subsquid_markets_poll")
            return count
        except Exception as e:
            logger.error(f"❌ Upsert failed: {e}", exc_info=True)
            return 0

    # ========================================
    # WebSocket (CLOB) - subsquid_markets_ws
    # ========================================
    async def upsert_market_ws(self, market_id: str, data: Dict[str, Any]) -> bool:
        """
        Upsert market data from WebSocket streaming (prices, bid/ask).
        Used by Streamer to update real-time orderbook data.
        """
        if not self.pool:
            return False

        # Build dynamic UPDATE SET clause from data keys
        set_clauses = []
        values = [market_id]
        param_idx = 2

        for key, value in data.items():
            set_clauses.append(f"{key} = ${param_idx}")
            # Handle JSONB columns specially - convert dicts to JSON
            if isinstance(value, dict):
                import json
                values.append(json.dumps(value))
            else:
                values.append(value)
            param_idx += 1

        set_clause = ", ".join(set_clauses)
        values.append(datetime.now(timezone.utc))  # updated_at

        query = f"""
            INSERT INTO {TABLES['markets_ws']} (market_id, {', '.join(data.keys())}, updated_at)
            VALUES ($1, {', '.join([f'${i}' for i in range(2, param_idx)])}, ${param_idx})
            ON CONFLICT (market_id) DO UPDATE SET
                {set_clause},
                updated_at = ${param_idx}
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *values)
                return True
        except Exception as e:
            logger.error(f"❌ Failed to upsert market_ws for {market_id}: {e}")
            return False

    async def upsert_market_ws_trade(self, market_id: str, trade_data: Dict[str, Any]) -> bool:
        """
        Upsert trade data from WebSocket (last_trade_price, etc).
        Used by Streamer to track trades.
        """
        if not self.pool:
            return False

        trade_data['market_id'] = market_id
        trade_data['updated_at'] = datetime.now(timezone.utc)

        keys = list(trade_data.keys())
        values = list(trade_data.values())
        placeholders = ", ".join([f"${i+1}" for i in range(len(keys))])
        set_clause = ", ".join([f"{k} = EXCLUDED.{k}" for k in keys if k != 'market_id'])

        query = f"""
            INSERT INTO {TABLES['markets_ws']} ({', '.join(keys)})
            VALUES ({placeholders})
            ON CONFLICT (market_id) DO UPDATE SET {set_clause}
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *values)
                return True
        except Exception as e:
            logger.error(f"❌ Failed to upsert trade for {market_id}: {e}")
            return False

    async def get_active_markets(self, limit: int = 100) -> List[str]:
        """
        Get list of active market IDs for Streamer subscription.
        Returns top markets by volume to avoid overwhelming WebSocket.
        """
        if not self.pool:
            logger.warning("⚠️ Database pool not initialized")
            return []

        query = f"""
            SELECT market_id
            FROM {TABLES['markets_poll']}
            WHERE status = 'ACTIVE' AND tradeable = true
            ORDER BY volume DESC, liquidity DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, limit)
                market_ids = [row['market_id'] for row in rows]
                logger.info(f"✅ Retrieved {len(market_ids)} active markets for Streamer subscription")
                return market_ids
        except Exception as e:
            logger.error(f"❌ Failed to get active markets: {e}")
            return []

    async def get_market_token_ids(self, limit: int = 10) -> List[str]:
        """
        Get CLOB token IDs for active markets (for WebSocket subscription).
        Returns flattened list of all token IDs from user positions only.

        ✅ OPTIMIZED: Focus only on user positions + smart traders (no top markets)
        This reduces WebSocket subscriptions by ~80% while keeping real-time data for user positions.
        """
        if not self.pool:
            logger.warning("⚠️ Database pool not initialized")
            return []

        # Get watched markets (user positions)
        # ✅ FIX: Use condition_id for join (watched_markets stores condition_id, not market_id)
        watched_query = """
            SELECT wm.market_id, sp.clob_token_ids
            FROM watched_markets wm
            JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id
            WHERE wm.active_positions > 0
                AND sp.status = 'ACTIVE'
                AND sp.tradeable = true
                AND sp.accepting_orders = true
                AND sp.clob_token_ids IS NOT NULL
                AND sp.clob_token_ids != ''
        """

        # Third: get smart trader markets (last 24h)
        # ✅ NEW: Track markets where smart wallets are actively trading
        smart_traders_query = """
            SELECT DISTINCT sp.market_id, sp.clob_token_ids
            FROM smart_wallet_trades swt
            JOIN subsquid_markets_poll sp ON swt.market_id = sp.condition_id
            WHERE swt.timestamp > NOW() - INTERVAL '24 hours'
                AND sp.status = 'ACTIVE'
                AND sp.tradeable = true
                AND sp.accepting_orders = true
                AND sp.clob_token_ids IS NOT NULL
                AND sp.clob_token_ids != ''
        """

        # Fourth: get ALL user position markets (even unwatched ones)
        # ✅ CRITICAL FIX: Cover ALL markets where users have positions, even if not in watched_markets
        # This fixes the issue where markets bought by users aren't streamed if watched_markets insert failed
        user_positions_query = """
            SELECT DISTINCT sp.market_id, sp.clob_token_ids
            FROM transactions t
            JOIN subsquid_markets_poll sp ON t.market_id = sp.condition_id
            WHERE t.executed_at > NOW() - INTERVAL '30 days'
                AND t.transaction_type IN ('BUY', 'SELL')
                AND t.token_id IS NOT NULL
                AND sp.status = 'ACTIVE'
                AND sp.tradeable = true
                AND sp.accepting_orders = true
                AND sp.clob_token_ids IS NOT NULL
                AND sp.clob_token_ids != ''
        """

        try:
            async with self.pool.acquire() as conn:
                # Get watched markets
                watched_rows = await conn.fetch(watched_query)

                # Get smart trader markets
                smart_rows = await conn.fetch(smart_traders_query)

                # Get user position markets (ALL user positions, even unwatched)
                user_position_rows = await conn.fetch(user_positions_query)

                # ✅ OPTIMIZED: Only user positions, no top markets background refresh
                all_rows = watched_rows + smart_rows + user_position_rows
                all_token_ids = []

                for row in all_rows:
                    token_ids_raw = row['clob_token_ids']
                    if token_ids_raw:
                        # Parse heavily escaped JSON: "\"[\\\"token1\\\", \\\"token2\\\"]\""
                        try:
                            import json
                            # Strategy: Keep unescaping until we get valid JSON array
                            cleaned = token_ids_raw

                            # Remove outer quotes if present
                            if cleaned.startswith('"') and cleaned.endswith('"'):
                                cleaned = cleaned[1:-1]

                            # Replace escaped backslashes and quotes
                            cleaned = cleaned.replace('\\\\', '\\')
                            cleaned = cleaned.replace('\\"', '"')

                            # Parse the JSON array
                            token_array = json.loads(cleaned)

                            if isinstance(token_array, list):
                                all_token_ids.extend(token_array)
                                logger.debug(f"✅ Parsed {len(token_array)} tokens from market {row['market_id']}")
                            else:
                                logger.warning(f"⚠️ Unexpected token format for market {row['market_id']}: {type(token_array)}")

                        except Exception as parse_err:
                            logger.warning(f"⚠️ Failed to parse token IDs for market {row['market_id']}: {parse_err}")
                            logger.debug(f"Raw value: {token_ids_raw[:100]}")
                            continue

                # Remove duplicates while preserving order
                seen = set()
                unique_token_ids = []
                for token_id in all_token_ids:
                    if token_id not in seen:
                        seen.add(token_id)
                        unique_token_ids.append(token_id)

                # Enhanced logging to track coverage
                logger.info(f"✅ Retrieved {len(unique_token_ids)} unique token IDs from {len(all_rows)} total markets")
                logger.info(f"   📊 Sources: {len(watched_rows)} watched + {len(smart_rows)} smart traders + {len(user_position_rows)} user positions")

                # Count unique markets (dedupe across sources)
                unique_markets = len(set([row['market_id'] for row in all_rows if 'market_id' in row]))
                logger.info(f"   🎯 Monitoring {unique_markets} unique markets with active user positions")

                return unique_token_ids
        except Exception as e:
            logger.error(f"❌ Failed to fetch market token IDs: {e}")
            return []

    async def add_watched_market(self, market_id: str, condition_id: str = None, title: str = None) -> bool:
        """
        Add a market to the watched list (for user positions).
        Called when users have positions on markets not in top 1000.
        """
        if not self.pool:
            return False

        query = """
            INSERT INTO watched_markets (market_id, condition_id, title, active_positions, last_position_at, updated_at)
            VALUES ($1, $2, $3, 1, NOW(), NOW())
            ON CONFLICT (market_id) DO UPDATE SET
                active_positions = watched_markets.active_positions + 1,
                last_position_at = NOW(),
                updated_at = NOW(),
                condition_id = COALESCE(EXCLUDED.condition_id, watched_markets.condition_id),
                title = COALESCE(EXCLUDED.title, watched_markets.title)
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, market_id, condition_id, title)
                logger.info(f"✅ Added/updated watched market: {market_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Failed to add watched market {market_id}: {e}")
            return False

    async def remove_watched_market(self, market_id: str) -> bool:
        """
        Remove a market from watched list when no more active positions.
        """
        if not self.pool:
            return False

        query = "DELETE FROM watched_markets WHERE market_id = $1"

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, market_id)
                logger.info(f"✅ Removed watched market: {market_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Failed to remove watched market {market_id}: {e}")
            return False

    async def update_watched_market_positions(self, market_id: str, position_count: int) -> bool:
        """
        Update position count for a watched market.
        """
        if not self.pool:
            return False

        if position_count <= 0:
            return await self.remove_watched_market(market_id)

        query = """
            UPDATE watched_markets
            SET active_positions = $2, last_position_at = NOW(), updated_at = NOW()
            WHERE market_id = $1
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, market_id, position_count)
                logger.debug(f"✅ Updated watched market {market_id}: {position_count} positions")
                return True
        except Exception as e:
            logger.error(f"❌ Failed to update watched market {market_id}: {e}")
            return False

    async def get_markets_ws(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent WebSocket market data (streaming prices)"""
        if not self.pool:
            return []

        query = f"""
            SELECT market_id, last_bb, last_ba, last_mid, last_trade_price, updated_at
            FROM {TABLES['markets_ws']}
            ORDER BY updated_at DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Failed to fetch markets_ws: {e}")
            return []

    async def calculate_freshness_ws(self) -> Dict[str, Any]:
        """Calculate freshness stats for WebSocket table"""
        if not self.pool:
            return {}

        query = f"""
            SELECT
                COUNT(*) as total_records,
                MAX(updated_at) as latest_update,
                EXTRACT(EPOCH FROM (now() - MAX(updated_at))) as freshness_seconds,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (now() - updated_at))) as p95_freshness
            FROM {TABLES['markets_ws']}
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query)
                return {
                    "total_records": row['total_records'],
                    "latest_update": row['latest_update'],
                    "freshness_seconds": row['freshness_seconds'],
                    "p95_freshness_seconds": row['p95_freshness'],
                }
        except Exception as e:
            logger.error(f"❌ Failed to calculate freshness WS: {e}")
            return {}

    # ========================================
    # Webhook (Redis Bridge) - subsquid_markets_wh
    # ========================================
    async def insert_webhook_event(self, market_id: str, event: str, payload: Dict[str, Any], timestamp: datetime = None) -> Optional[int]:
        """
        Insert webhook event into subsquid_markets_wh.

        Args:
            market_id: Market identifier
            event: Event type (e.g., 'market.status.active', 'clob.trade')
            payload: Event payload as dict
            timestamp: Optional timestamp (defaults to now)

        Returns:
            Event ID if successful, None otherwise
        """
        if not self.pool:
            return None

        query = f"""
            INSERT INTO {TABLES['markets_wh']}
            (market_id, event, payload, updated_at)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                import json
                event_id = await conn.fetchval(
                    query,
                    market_id,
                    event,
                    json.dumps(payload) if payload else None,
                    timestamp or datetime.now(timezone.utc)
                )
            return event_id
        except Exception as e:
            logger.error(f"❌ Insert webhook event failed: {e}")
            return None

    # ========================================
    # Read Operations (for CLI scripts)
    # ========================================
    async def get_markets_poll(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent markets from polling table"""
        if not self.pool:
            return []

        query = f"""
            SELECT market_id, title, status, expiry, last_mid, updated_at
            FROM {TABLES['markets_poll']}
            ORDER BY updated_at DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Failed to fetch markets_poll: {e}")
            return []

    async def get_markets_poll_without_events(self, limit: int = 50000) -> List[Dict[str, Any]]:
        """Get all ACTIVE markets that don't have events data (for enrichment)"""
        if not self.pool:
            return []

        query = f"""
            SELECT
                market_id,
                title,
                status,
                volume,
                liquidity,
                outcome_prices,
                last_mid,
                created_at,
                updated_at,
                end_date,
                condition_id,
                slug,
                tradeable,
                accepting_orders,
                events
            FROM {TABLES['markets_poll']}
            WHERE status = 'ACTIVE'
            AND (events IS NULL OR jsonb_array_length(events) = 0)
            ORDER BY volume DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Failed to fetch markets_poll_without_events: {e}")
            return []

    async def get_user_position_market_ids(self) -> List[str]:
        """Get market_ids from user_positions with active positions

        ✅ NEW: Uses user_positions table instead of watched_markets
        Returns markets where users have active positions (<50 typically).
        These markets are polled every cycle for fast resolution detection (<3min).

        Returns:
            List of market IDs that have active user positions and are not RESOLVED
        """
        if not self.pool:
            return []

        query = """
            SELECT DISTINCT up.market_id, smp.end_date
            FROM user_positions up
            JOIN subsquid_markets_poll smp ON up.market_id = smp.market_id
            WHERE (smp.resolution_status != 'RESOLVED' OR smp.resolution_status IS NULL)
            ORDER BY smp.end_date ASC NULLS LAST
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)

            market_ids = [row['market_id'] for row in rows]

            logger.info(f"✅ [NEW] get_user_position_market_ids() from user_positions: {len(market_ids)} markets")
            logger.debug(f"Market IDs: {market_ids}")

            return market_ids
        except Exception as e:
            logger.error(f"❌ Failed to get user position market IDs: {e}")
            return []

    async def get_active_position_token_ids(self, limit: int = 500) -> List[str]:
        """Get token IDs from active user positions for WebSocket subscriptions

        ✅ NEW: Uses user_positions table instead of watched_markets
        Returns token IDs for markets where users have active positions.
        Prioritizes markets with recent activity.

        Args:
            limit: Maximum number of token IDs to return

        Returns:
            List of unique token IDs for active position markets
        """
        if not self.pool:
            return []

        query = """
            SELECT DISTINCT
                json_array_elements_text(smp.clob_token_ids::json) as token_id,
                smp.updated_at
            FROM user_positions up
            JOIN subsquid_markets_poll smp ON up.market_id = smp.market_id
            WHERE smp.clob_token_ids IS NOT NULL
              AND json_array_length(smp.clob_token_ids::json) > 0
              AND (smp.resolution_status != 'RESOLVED' OR smp.resolution_status IS NULL)
            ORDER BY smp.updated_at DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, limit)

            token_ids = [row['token_id'] for row in rows if row['token_id']]

            logger.info(f"✅ [NEW] get_active_position_token_ids(): {len(token_ids)} token IDs from user positions")
            logger.debug(f"Token IDs: {token_ids[:10]}...")  # Log first 10

            return token_ids
        except Exception as e:
            logger.error(f"❌ Failed to get active position token IDs: {e}")
            return []

    async def get_urgent_expiry_markets(self, minutes: int = 10) -> List[str]:
        """Get market IDs that are expiring soon (within ±minutes of end_date)

        Args:
            minutes: Time window in minutes (default: 10)

        Returns:
            List of market IDs that are near expiry and not RESOLVED
        """
        if not self.pool:
            return []

        query = f"""
            SELECT market_id
            FROM subsquid_markets_poll
            WHERE end_date IS NOT NULL
              AND end_date > NOW()
              AND end_date <= NOW() + INTERVAL '{minutes} minutes'
              AND (resolution_status != 'RESOLVED' OR resolution_status IS NULL)
            LIMIT 100
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)

            market_ids = [row['market_id'] for row in rows]
            logger.debug(f"🕐 [URGENT EXPIRY] Found {len(market_ids)} markets within ±{minutes}min of end_date")
            return market_ids
        except Exception as e:
            logger.error(f"❌ Failed to get urgent expiry markets: {e}")
            return []

    async def get_markets_by_volume_tier(
        self,
        min_volume: Optional[float] = None,
        max_volume: Optional[float] = None,
        limit: int = 1000,
        include_recently_closed: bool = False
    ) -> List[str]:
        """Get market IDs filtered by volume tier (non-RESOLVED markets only)

        Args:
            min_volume: Minimum volume threshold (inclusive)
            max_volume: Maximum volume threshold (exclusive)
            limit: Maximum number of market IDs to return
            include_recently_closed: DEPRECATED - Kept for backward compatibility.
                                    Now included automatically if resolution_status != 'RESOLVED'

        Returns:
            List of market IDs sorted by volume DESC (includes PENDING and PROPOSED markets)
        """
        if not self.pool:
            return []

        # NEW LOGIC: Include markets that are NOT RESOLVED (PENDING and PROPOSED)
        # This ensures we continue fetching markets until they are RESOLVED
        query = """
            SELECT market_id
            FROM subsquid_markets_poll
            WHERE (resolution_status != 'RESOLVED' OR resolution_status IS NULL)
        """
        params = []

        if min_volume is not None:
            query += f" AND volume >= ${len(params) + 1}"
            params.append(min_volume)

        if max_volume is not None:
            query += f" AND volume < ${len(params) + 1}"
            params.append(max_volume)

        # CRITICAL FIX: Prioritize recently expired PROPOSED markets for faster resolution
        # This ensures markets that just expired (like Bitcoin Up/Down) are polled quickly
        # Priority order:
        # 1. PROPOSED markets with end_date < 24h ago (recently expired, need resolution)
        # 2. Then by volume DESC (high volume markets)
        query += f"""
            ORDER BY
                CASE
                    WHEN resolution_status = 'PROPOSED'
                         AND end_date IS NOT NULL
                         AND end_date > NOW() - INTERVAL '24 hours'
                    THEN 0  -- Highest priority
                    ELSE 1  -- Lower priority
                END,
                volume DESC
            LIMIT ${len(params) + 1}
        """
        params.append(limit)

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [row['market_id'] for row in rows]
        except Exception as e:
            logger.error(f"❌ Failed to get markets by volume tier: {e}")
            return []

    async def get_markets_by_expiry_tier(self, hours: int = 2, limit: int = 50) -> List[str]:
        """Get market IDs that expire within specified hours (URGENT_EXPIRY tier)

        Args:
            hours: Number of hours before expiry to consider urgent (default: 2)
            limit: Maximum number of market IDs to return (default: 50)

        Returns:
            List of market IDs sorted by end_date ASC (most urgent first)
        """
        if not self.pool:
            return []

        query = """
            SELECT market_id
            FROM subsquid_markets_poll
            WHERE (resolution_status != 'RESOLVED' OR resolution_status IS NULL)
              AND end_date IS NOT NULL
              AND end_date > NOW()
              AND end_date < NOW() + INTERVAL '1 hour' * $1
            ORDER BY end_date ASC
            LIMIT $2
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, hours, limit)

            return [row['market_id'] for row in rows]
        except Exception as e:
            logger.error(f"❌ Failed to get markets by expiry tier: {e}")
            return []

    async def get_existing_market_ids(self, active_only: bool = True, include_recently_closed: bool = False) -> set:
        """Get existing market IDs from DB for efficient filtering

        OPT 3: Uses Redis cache to avoid 1739 DB queries per poll cycle

        Args:
            active_only: DEPRECATED - Kept for backward compatibility.
                        Now filters by resolution_status != 'RESOLVED' instead.
            include_recently_closed: DEPRECATED - Kept for backward compatibility.
                                    Now included automatically if resolution_status != 'RESOLVED'

        Returns:
            Set of market IDs that are not yet RESOLVED (includes PENDING and PROPOSED)
        """
        if not self.pool:
            return set()

        # OPT 3: Try Redis cache first (avoids 1739 DB queries!)
        # Note: Cache still uses "active" name but now includes non-RESOLVED markets
        try:
            import os
            redis_url = os.getenv('REDIS_URL')
            if redis_url:
                from core.services.redis_price_cache import get_redis_cache
                redis_cache = get_redis_cache()

                if active_only and redis_cache.enabled:
                    cached_ids = redis_cache.get_active_market_ids()
                    if cached_ids is not None:
                        logger.debug(f"🚀 CACHE HIT: {len(cached_ids)} market IDs from Redis (instant!)")
                        return cached_ids
        except Exception as cache_err:
            # Cache failure is non-fatal, fallback to DB
            logger.debug(f"Cache lookup failed, using DB: {cache_err}")

        # NEW LOGIC: Fetch markets that are NOT RESOLVED (includes PENDING and PROPOSED)
        # This ensures we continue fetching markets until they are RESOLVED
        query = f"""
            SELECT market_id
            FROM {TABLES['markets_poll']}
            WHERE resolution_status != 'RESOLVED' OR resolution_status IS NULL
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
                market_ids = {row['market_id'] for row in rows}

                # OPT 3: Cache the result for next time
                if active_only:
                    try:
                        from core.services.redis_price_cache import get_redis_cache
                        redis_cache = get_redis_cache()
                        if redis_cache.enabled:
                            redis_cache.cache_active_market_ids(list(market_ids), ttl=300)
                            logger.info(f"💾 Cached {len(market_ids)} non-RESOLVED market IDs to Redis (TTL: 5min)")
                    except Exception as cache_err:
                        logger.debug(f"Cache write failed (non-fatal): {cache_err}")

                return market_ids
        except Exception as e:
            logger.error(f"❌ Failed to fetch existing market IDs: {e}")
            return set()

    async def get_poller_last_sync(self) -> datetime:
        """Get last sync timestamp from poller_state table"""
        if not self.pool:
            return datetime.now(timezone.utc) - timedelta(hours=24)

        query = "SELECT last_sync FROM poller_state ORDER BY updated_at DESC LIMIT 1"

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query)
                if row and row['last_sync']:
                    return row['last_sync']
        except Exception as e:
            logger.error(f"⚠️ Failed to fetch poller last_sync: {e}")

        # Default to 24 hours ago if not found
        return datetime.now(timezone.utc) - timedelta(hours=24)

    async def update_poller_last_sync(self, last_sync: datetime) -> bool:
        """Update last_sync timestamp in poller_state table"""
        if not self.pool:
            return False

        query = """
            UPDATE poller_state
            SET last_sync = $1, updated_at = NOW()
            WHERE id = (SELECT id FROM poller_state ORDER BY id DESC LIMIT 1)
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, last_sync)
                logger.debug(f"✅ Updated poller last_sync to {last_sync.isoformat()}")
                return True
        except Exception as e:
            logger.error(f"❌ Failed to update poller last_sync: {e}")
            return False

    async def get_webhook_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent webhook events"""
        if not self.pool:
            return []

        query = f"""
            SELECT id, market_id, event, payload, updated_at
            FROM {TABLES['markets_wh']}
            ORDER BY updated_at DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Failed to fetch webhook events: {e}")
            return []

    async def calculate_freshness_poll(self) -> Dict[str, Any]:
        """Calculate freshness stats for polling table"""
        if not self.pool:
            return {}

        query = f"""
            SELECT
                COUNT(*) as total_records,
                MAX(updated_at) as latest_update,
                EXTRACT(EPOCH FROM (now() - MAX(updated_at))) as freshness_seconds,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (now() - updated_at))) as p95_freshness
            FROM {TABLES['markets_poll']}
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query)
                return {
                    "total_records": row['total_records'],
                    "latest_update": row['latest_update'],
                    "freshness_seconds": row['freshness_seconds'],
                    "p95_freshness_seconds": row['p95_freshness'],
                }
        except Exception as e:
            logger.error(f"❌ Failed to calculate freshness: {e}")
            return {}

    # ========================================
    # Market Status Helpers
    # ========================================

    async def is_market_tradeable(self, market_id: str) -> bool:
        """
        Check if a market is currently tradeable (fast check).

        A market is tradeable if:
        - status = "ACTIVE"
        - accepting_orders = true
        - tradeable = true
        """
        query = """
            SELECT tradeable
            FROM subsquid_markets_poll
            WHERE market_id::text = $1
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, market_id)
        return result is True

    async def get_market_status(self, market_id: str) -> dict:
        """
        Get comprehensive market status for bot.

        Returns:
            {
                market_id: str,
                title: str,
                status: "ACTIVE" | "CLOSED",
                tradeable: bool,
                accepting_orders: bool,
                last_mid: float,
                end_date: datetime,
                outcomes: [str],
                outcome_prices: [float],
                volume_24hr: float
            }
        """
        query = """
            SELECT
                market_id,
                title,
                status,
                tradeable,
                accepting_orders,
                last_mid,
                end_date,
                outcomes,
                outcome_prices,
                volume_24hr
            FROM subsquid_markets_poll
            WHERE market_id::text = $1
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, market_id)

        if not row:
            return None

        return {
            "market_id": row["market_id"],
            "title": row["title"],
            "status": row["status"],
            "tradeable": row["tradeable"],
            "accepting_orders": row["accepting_orders"],
            "last_mid": float(row["last_mid"]) if row["last_mid"] else 0.0,
            "end_date": row["end_date"],
            "outcomes": row["outcomes"] or [],
            "outcome_prices": [float(p) if p else 0.0 for p in (row["outcome_prices"] or [])],
            "volume_24hr": float(row["volume_24hr"]) if row["volume_24hr"] else 0.0,
        }

    async def get_open_markets_summary(self, limit: int = 50) -> List[dict]:
        """
        Get summary of currently OPEN/TRADEABLE markets for display to users.

        Sorted by volume_24hr DESC (most active first).
        """
        query = """
            SELECT
                market_id,
                title,
                status,
                tradeable,
                outcome_prices,
                last_mid,
                volume_24hr,
                end_date,
                outcomes
            FROM subsquid_markets_poll
            WHERE status = 'ACTIVE'
            AND tradeable = true
            AND accepting_orders = true
            ORDER BY volume_24hr DESC
            LIMIT $1
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, limit)

        return [
            {
                "market_id": row["market_id"],
                "title": row["title"],
                "outcomes": row["outcomes"] or [],
                "outcome_prices": [float(p) if p else 0.0 for p in (row["outcome_prices"] or [])],
                "volume_24hr": float(row["volume_24hr"]) if row["volume_24hr"] else 0.0,
                "end_date": row["end_date"],
            }
            for row in rows
        ]


# ========================================
# Database Triggers
# ========================================

# Trigger pour marquer automatiquement les positions comme redeemable
async def setup_redeemable_trigger():
    """Setup trigger to automatically mark positions as redeemable when markets resolve"""
    db = await get_db_client()

    trigger_sql = """
    CREATE OR REPLACE FUNCTION mark_redeemable_positions()
    RETURNS TRIGGER AS $$
    BEGIN
        -- Quand un marché devient RESOLVED, marquer ses positions comme redeemable
        IF NEW.resolution_status = 'RESOLVED' AND (OLD.resolution_status IS NULL OR OLD.resolution_status != 'RESOLVED') THEN
            UPDATE user_positions
            SET redeemable = true, updated_at = NOW()
            WHERE market_id = NEW.market_id;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER IF NOT EXISTS trigger_mark_redeemable_positions
        AFTER UPDATE ON subsquid_markets_poll
        FOR EACH ROW
        EXECUTE FUNCTION mark_redeemable_positions();
    """

    try:
        async with db.pool.acquire() as conn:
            await conn.execute(trigger_sql)
        logger.info("✅ Redeemable positions trigger setup complete")
    except Exception as e:
        logger.error(f"❌ Failed to setup redeemable trigger: {e}")

# ========================================
# Global Database Client Instance
# ========================================
_db_client: Optional[DatabaseClient] = None


async def get_db_client() -> DatabaseClient:
    """Get or create global database client"""
    global _db_client
    if _db_client is None:
        _db_client = DatabaseClient()
        await _db_client.connect()
    return _db_client


async def close_db_client():
    """Close global database client"""
    global _db_client
    if _db_client:
        await _db_client.disconnect()
        _db_client = None
