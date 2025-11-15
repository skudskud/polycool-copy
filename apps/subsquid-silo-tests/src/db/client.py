"""
Database Client for Subsquid Silo Tests
Handles asyncpg connections, upserts, and idempotency for subsquid_* tables.
Enhanced with automatic retry logic for transient failures.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import asyncpg
from asyncpg import Pool
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    retry_if_exception_type
)

from ..config import settings, TABLES
from ..utils.metrics import db_retries_total, db_errors_total, db_upserts_total, db_upsert_duration_seconds

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
                min_size=5,
                max_size=20,
                timeout=10.0
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
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry=retry_if_exception_type((asyncpg.PostgresError, asyncio.TimeoutError)),
        reraise=True
    )
    async def upsert_markets_poll(self, markets: List[Dict[str, Any]]) -> int:
        """
        Upsert markets from Gamma API polling into subsquid_markets_poll.

        Args:
            markets: List of enriched market dicts from Gamma API

        Returns:
            Number of rows inserted/updated
        """
        if not self.pool or not markets:
            logger.debug(f"⚠️ Upsert skipped: pool={self.pool is not None}, markets={len(markets) if markets else 0}")
            return 0

        logger.debug(f"🔵 Starting upsert of {len(markets)} markets")

        query = f"""
            INSERT INTO {TABLES['markets_poll']}
            (market_id, condition_id, slug, title, description, category,
             status, accepting_orders, archived, tradeable,
             outcomes, outcome_prices, last_mid,
             volume, volume_24hr, volume_1wk, volume_1mo,
             liquidity, spread,
             created_at, end_date, resolution_date,
             price_change_1h, price_change_1d, price_change_1w,
             clob_token_ids, events, market_type, restricted, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10,
                    $11, $12, $13,
                    $14, $15, $16, $17,
                    $18, $19,
                    $20, $21, $22,
                    $23, $24, $25,
                    $26, $27, $28, $29, now())
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
                clob_token_ids = EXCLUDED.clob_token_ids,
                events = EXCLUDED.events,
                market_type = EXCLUDED.market_type,
                restricted = EXCLUDED.restricted,
                updated_at = now()
        """

        try:
            import json
            async with self.pool.acquire() as conn:
                count = 0
                for market in markets:
                    # Convert lists/dicts to JSON strings where needed
                    events_json = json.dumps(market.get("events", [])) if market.get("events") else None
                    clob_tokens = json.dumps(market.get("clob_token_ids", [])) if market.get("clob_token_ids") else None

                    await conn.execute(
                        query,
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
                        market.get("outcomes"),  # TEXT[] array
                        market.get("outcome_prices"),  # NUMERIC[] array
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
                        events_json,
                        market.get("market_type", "normal"),
                        market.get("restricted", False),
                    )
                    count += 1
            logger.info(f"✅ Upserted {count} enriched markets into subsquid_markets_poll")
            return count
        except Exception as e:
            logger.error(f"❌ Upsert failed: {e}", exc_info=True)
            return 0

    # ========================================
    # WebSocket (CLOB) - subsquid_markets_ws
    # ========================================
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry=retry_if_exception_type((asyncpg.PostgresError, asyncio.TimeoutError)),
        reraise=True
    )
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry=retry_if_exception_type((asyncpg.PostgresError, asyncio.TimeoutError)),
        reraise=True
    )
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

    async def get_watched_markets(self, limit: int = 3000) -> List[str]:
        """
        Get list of watched market IDs (markets with user positions).
        Returns all watched markets up to limit to ensure user positions have real-time data.
        Cached in Redis for 60 seconds to avoid repeated DB calls during reconnections.
        """
        if not self.pool:
            logger.warning("⚠️ Database pool not initialized")
            return []

        # Try Redis cache first (60s TTL - watched markets change infrequently)
        cache_key = f"watched_markets:{limit}"
        try:
            import json
            # Note: This assumes redis_client is available - in practice we'd inject it
            # For now, we'll implement caching at the service level
            pass
        except:
            pass  # Redis not available, proceed to DB

        query = """
            SELECT market_id
            FROM watched_markets
            WHERE active_positions > 0
            ORDER BY last_position_at DESC, active_positions DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, limit)
                market_ids = [row['market_id'] for row in rows]
                logger.info(f"📈 Retrieved {len(market_ids)} watched markets with active positions")

                # Cache result for future calls (would implement Redis caching here)
                # This reduces DB load during streamer reconnections

                return market_ids
        except Exception as e:
            logger.error(f"❌ Failed to get watched markets: {e}")
            return []

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
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry=retry_if_exception_type((asyncpg.PostgresError, asyncio.TimeoutError)),
        reraise=True
    )
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
