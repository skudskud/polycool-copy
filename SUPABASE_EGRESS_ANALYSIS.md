# 🚨 Supabase Egress Analysis & Solutions

## Problem Summary

**Current Usage:** 1,591.7 GB egress in ~20 days (~79.6 GB/day)
**Pro Plan Quota:** 250 GB/month
**Overage:** 1,341.7 GB ($120.75)

## What is Egress?

**Egress = Data transferred OUT of Supabase** (outbound traffic):
- Database query responses (SELECT results)
- API responses
- Storage file downloads
- Realtime messages
- Edge Function responses

**Every byte of data you read from Supabase counts as egress!**

## Root Causes Identified

### 1. **Frequent Polling (Every 60 Seconds)**

Your poller runs every 60 seconds (`POLL_MS=60000`), and each cycle:

```12:66:apps/subsquid-silo-tests/data-ingestion/src/polling/poller.py
class PollerService:
    """Gamma API polling service - Hybrid approach"""

    def __init__(self):
        self.enabled = settings.POLLER_ENABLED
        self.client: Optional[httpx.AsyncClient] = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.backoff_seconds = 1.0
        self.max_backoff = settings.POLL_RATE_LIMIT_BACKOFF_MAX
        self.poll_count = 0
        self.market_count = 0
        self.upsert_count = 0
        self.last_poll_time = None
        self.last_sync = datetime.now(timezone.utc) - timedelta(hours=24)  # Track last sync

        # 🔥 EVENTS PRESERVATION MONITORING
        self.events_preserved_pass2 = 0

        # 🤖 AI CATEGORIZER - DISABLED (causing TIER 0 to never execute)
        # self.categorizer = MarketCategorizerService()
        # self.categorized_count = 0
        # self.max_categorizations_per_cycle = 50

    async def start(self):
        """Start the polling service"""
        if not self.enabled:
            logger.warning("⚠️ Poller service disabled (POLLER_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info("✅ Poller service starting...")

        self.client = httpx.AsyncClient(timeout=30.0)

        # Load last_sync from DB
        db = await get_db_client()
        self.last_sync = await db.get_poller_last_sync()
        logger.info(f"✅ Loaded last_sync from DB: {self.last_sync.isoformat()}")

        try:
            while True:
                await self.poll_cycle()
                await asyncio.sleep(settings.POLL_MS / 1000.0)
```

**Impact:** 
- 1,440 poll cycles per day (24 hours × 60 minutes)
- Each cycle queries the database multiple times

### 2. **Large Query Result Sets**

Each poll cycle executes `get_existing_market_ids()` which fetches ALL non-RESOLVED markets:

```907:929:apps/subsquid-silo-tests/data-ingestion/src/db/client.py
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
```

**Estimated Impact:**
- If you have 10,000 non-RESOLVED markets, this query returns ~10,000 rows
- Each market_id is ~50-100 bytes
- **Per query:** ~500KB - 1MB
- **Per day:** 500KB × 1,440 cycles = **720MB - 1.4GB just for market IDs!**

### 3. **Large Market Records with JSONB Data**

Each market record contains large JSONB fields:

```97:157:apps/subsquid-silo-tests/data-ingestion/src/db/client.py
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
                clob_token_ids = EXCLUDED.clob_token_ids,
                tokens = CASE
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
        """
```

**Each market record contains:**
- `events` (JSONB): Array of event objects - could be 1-5KB
- `tokens` (JSONB): Array of token objects - could be 1-3KB
- `clob_token_ids` (TEXT): JSON array - could be 500 bytes
- `title`, `description`, `slug`: Text fields - could be 1-2KB total
- Arrays: `outcomes`, `outcome_prices` - could be 500 bytes

**Estimated size per market:** 5-10KB
**If processing 500-1000 markets per cycle:** 2.5-10MB per cycle
**Per day:** 2.5MB × 1,440 cycles = **3.6GB - 14.4GB per day!**

### 4. **Multiple Services Running**

You have multiple services that might be querying Supabase:
- Poller service (every 60s)
- Copy trading monitor (every 60s-120s)
- Price updater service
- Telegram bot queries

**Combined impact:** Could easily reach 79.6 GB/day

## Solutions (Ranked by Impact)

### 🔥 **Solution 1: Increase Polling Interval** (HIGHEST IMPACT)

**Current:** `POLL_MS=60000` (60 seconds)
**Recommended:** `POLL_MS=300000` (5 minutes) or `POLL_MS=600000` (10 minutes)

**Impact:** Reduces egress by 5-10x
- 60s → 5min: 80% reduction (1,440 cycles → 288 cycles/day)
- 60s → 10min: 90% reduction (1,440 cycles → 144 cycles/day)

**How to implement:**
```bash
# In Railway/environment variables
POLL_MS=300000  # 5 minutes
```

### 🔥 **Solution 2: Optimize Query to Only Fetch IDs** (HIGH IMPACT)

Your `get_existing_market_ids()` already only fetches `market_id`, which is good. But ensure all queries only fetch what's needed.

**Current:** ✅ Already optimized (only fetches `market_id`)

**Additional optimization:** Use `LIMIT` if you only need recent markets:
```sql
SELECT market_id
FROM subsquid_markets_poll
WHERE resolution_status != 'RESOLVED' 
  AND updated_at > NOW() - INTERVAL '7 days'  -- Only recent markets
LIMIT 5000
```

### 🔥 **Solution 3: Use Redis Cache Aggressively** (HIGH IMPACT)

Your code already has Redis caching, but ensure it's working:

```896:900:apps/subsquid-silo-tests/data-ingestion/src/db/client.py
                if active_only and redis_cache.enabled:
                    cached_ids = redis_cache.get_active_market_ids()
                    if cached_ids is not None:
                        logger.debug(f"🚀 CACHE HIT: {len(cached_ids)} market IDs from Redis (instant!)")
                        return cached_ids
```

**Check:**
1. Is Redis enabled and connected?
2. Is cache TTL appropriate? (Currently 5 minutes = 300s)
3. Increase cache TTL to 10-15 minutes if data freshness allows

**Impact:** Reduces database queries by 90%+ if cache hit rate is high

### 🔥 **Solution 4: Reduce Market Record Size** (MEDIUM IMPACT)

**Option A: Remove unnecessary fields from queries**
- Only fetch `market_id`, `status`, `resolution_status` when possible
- Don't fetch full market records unless needed

**Option B: Compress JSONB fields**
- Store only essential data in `events` and `tokens`
- Remove redundant data

**Option C: Use separate tables for large data**
- Move `events` and `tokens` to separate tables
- Only fetch when needed

### 🔥 **Solution 5: Batch Processing Optimization** (MEDIUM IMPACT)

Currently processing in chunks of 500:

```95:103:apps/subsquid-silo-tests/data-ingestion/src/polling/poller.py
                # Process in chunks to avoid DB timeouts with full coverage
                chunk_size = 500
                for i in range(0, len(events_markets), chunk_size):
                    chunk = events_markets[i:i + chunk_size]
                    chunk = await self._enrich_markets_with_tokens(chunk)
                    db = await get_db_client()
                    upserted = await db.upsert_markets_poll(chunk)
                    total_upserted += upserted
                    await asyncio.sleep(0.1)  # Rate limiting between chunks
```

**Optimization:** 
- Reduce chunk size if markets are large
- Only upsert markets that actually changed (compare `updated_at`)
- Use `ON CONFLICT DO NOTHING` if no changes detected

### 🔥 **Solution 6: Add Query Filters** (LOW-MEDIUM IMPACT)

Only fetch markets that need updating:

```sql
SELECT market_id
FROM subsquid_markets_poll
WHERE resolution_status != 'RESOLVED' 
  AND (
    updated_at < NOW() - INTERVAL '5 minutes'  -- Stale data
    OR status = 'ACTIVE'  -- Active markets need frequent updates
  )
```

**Impact:** Reduces query result size by 50-70%

### 🔥 **Solution 7: Monitor and Alert** (CRITICAL)

Set up monitoring to track egress usage:

1. **Supabase Dashboard:** Check egress usage daily
2. **Application Logs:** Log query sizes and frequencies
3. **Alerts:** Set up alerts at 50%, 75%, 90% of quota

## Immediate Action Plan

### Step 1: Reduce Polling Frequency (Do This First!)
```bash
# Set in Railway environment variables
POLL_MS=300000  # 5 minutes (was 60 seconds)
```

### Step 2: Verify Redis Cache is Working
Check logs for cache hit rates:
```bash
# Look for: "🚀 CACHE HIT" vs cache misses
```

### Step 3: Add Query Logging
Temporarily add logging to see actual query sizes:
```python
logger.info(f"📊 Query returned {len(rows))} rows, ~{len(rows) * 100} bytes")
```

### Step 4: Review All Services
Check all services that query Supabase:
- Poller: Every 60s → Change to 5min
- Copy trading: Every 60-120s → Increase to 5min
- Price updater: Check frequency
- Telegram bot: Check query patterns

## Expected Impact

**After implementing Solutions 1-3:**
- **Current:** 79.6 GB/day
- **After:** ~8-15 GB/day (80-90% reduction)
- **Monthly:** ~240-450 GB (still over quota, but much better)

**To get under 250 GB/month:**
- Need to reduce to ~8.3 GB/day
- Requires: 5-10 minute polling + aggressive caching + query optimization

## Cost Comparison

**Current monthly cost:** $120.75 in overages
**With optimizations:** $0-30/month in overages (if under 400 GB total)

**Savings:** $90-120/month

## Next Steps

1. ✅ **Immediately:** Increase `POLL_MS` to 300000 (5 minutes)
2. ✅ **Verify:** Redis cache is working and has high hit rate
3. ✅ **Monitor:** Check Supabase usage after 24 hours
4. ✅ **Optimize:** Implement query filters if still over quota
5. ✅ **Consider:** Move to dedicated PostgreSQL if egress continues to be high

## Questions to Answer

1. How many markets are currently non-RESOLVED? (Check: `SELECT COUNT(*) FROM subsquid_markets_poll WHERE resolution_status != 'RESOLVED'`)
2. Is Redis cache working? (Check logs for cache hits)
3. What's the average market record size? (Check: `SELECT pg_size_pretty(pg_total_relation_size('subsquid_markets_poll'))`)
4. How many services are querying Supabase concurrently?

