# 🔍 TIER 0 Poller Audit Report
**Date:** November 5, 2025
**Issue:** TIER 0 not appearing in logs; user position market not being polled

---

## 🔴 ROOT CAUSE

You have **TWO different pollers** in your codebase, and you're likely running the **WRONG one**:

### ❌ Simple Poller (Currently Shown)
**Path:** `apps/subsquid-silo-tests/indexer/src/polling/poller.py`

**Issues:**
- ❌ NO TIER 0 logic
- ❌ NO user positions tracking
- ❌ NO `get_user_position_market_ids()` integration
- ❌ NO multi-tier volume distribution
- ✅ Only has PASS 1 (active) + PASS 2 (closed) basic polling

**Used By:** DipDup on-chain indexer service

---

### ✅ Advanced Poller (SHOULD BE RUNNING)
**Path:** `apps/subsquid-silo-tests/data-ingestion/src/polling/poller.py`

**Features:**
- ✅ **TIER 0: USER_POSITIONS** - Polls markets with active positions every cycle
- ✅ **TIER 1: URGENT_EXPIRY** - Polls markets expiring within 2 hours
- ✅ **TIER 2-4: Volume-based** - High/Medium/Small market distribution
- ✅ Debug logging: `🚨🚨🚨 [TIER 0 DEBUG]`
- ✅ Watches `watched_markets` table for active positions

**Used By:** Data Ingestion service (Poller + Streamer + Webhook + Redis Bridge)

---

## 📊 DATABASE VERIFICATION ✅

### Your Market EXISTS and IS TRACKED:

```sql
SELECT
    sp.market_id,
    sp.condition_id,
    sp.title,
    sp.status,
    sp.resolution_status,
    wm.active_positions
FROM watched_markets wm
JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id
WHERE sp.title LIKE '%Bitcoin Up or Down - November 5, 8:00AM-8:15AM ET%';
```

**Result:**
```json
{
  "market_id": "665974",
  "condition_id": "0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7",
  "title": "Bitcoin Up or Down - November 5, 8:00AM-8:15AM ET",
  "status": "CLOSED",
  "resolution_status": "PROPOSED",  ← Not yet RESOLVED, so it SHOULD be polled
  "active_positions": 1  ← TRACKED by watched_markets
}
```

### TIER 0 Query DOES Return Your Market:

The query in `get_user_position_market_ids()` returns:

```python
[
    "628803",  # Ukraine Tomahawk
    "619189",  # Funding bill vote
    "665974",  # ← YOUR MARKET (Bitcoin Up or Down)
    "623602",
    "623604",
    "541621",
    "621018",
    "571891",
    "576927",
    "566331"
]
```

✅ **Your market (665974) is at position #3 in the TIER 0 list!**

---

## 🔍 TIER 0 LOGIC ANALYSIS

### How TIER 0 Works (Advanced Poller)

```python
# Line 304-330 in data-ingestion/src/polling/poller.py
user_position_ids = await db.get_user_position_market_ids()

# 🚨🚨🚨 DEBUG LOG - ALWAYS VISIBLE
logger.info(f"🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned {len(user_position_ids)} markets: {user_position_ids}")

if user_position_ids:
    logger.info(f"🎯 [TIER 0: USER_POSITIONS] Polling {len(user_position_ids)} markets with active positions")

    # Fetch via /markets bulk (need full metadata for resolution status)
    markets = await self._fetch_markets_bulk(user_position_ids)

    if markets:
        # Enrich with tokens
        markets = await self._enrich_markets_with_tokens(markets)

        # Parse and preserve data
        for market in markets:
            enriched = await self._parse_standalone_market(market)
            all_markets.append(enriched)

        logger.info(f"✅ [TIER 0] Updated {len(markets)} user position markets for fast resolution detection")
```

### Expected Log Output:
```
🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned 10 markets: ['628803', '619189', '665974', ...]
🎯 [TIER 0: USER_POSITIONS] Polling 10 markets with active positions
✅ [TIER 0] Updated 10 user position markets for fast resolution detection
```

---

## 🛠️ DIAGNOSIS

### Issue 1: Wrong Poller Running
**Symptom:** No TIER 0 logs appearing
**Cause:** Simple poller (`indexer/src/polling/poller.py`) doesn't have TIER 0 logic
**Fix:** Deploy/run the advanced poller (`data-ingestion/src/polling/poller.py`)

### Issue 2: API Call Format
**Query Used:**
```python
url = f"https://gamma-api.polymarket.com/markets?id={ids_param}&limit=500"
# Example: ?id=665974,628803,619189
```

**Potential Issue:**
- The query returns numeric `market_id` (e.g., "665974")
- API might expect `conditionId` for some endpoints

**Verification Needed:**
```bash
# Test if numeric IDs work
curl "https://gamma-api.polymarket.com/markets?id=665974"

# Test if condition IDs work
curl "https://gamma-api.polymarket.com/markets?conditionId=0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7"
```

---

## ✅ SOLUTION

### Step 1: Verify Which Poller is Running

Check your Railway deployment or local environment:

```bash
# Check which service is running
railway status

# Check logs for TIER 0 debug messages
railway logs --service data-ingestion | grep "TIER 0"
```

### Step 2: Ensure Advanced Poller is Running

**Railway Deployment:**
- Service: **Data Ingestion** (not DipDup Indexer)
- Config: `apps/subsquid-silo-tests/data-ingestion/railway.json`
- Entry Point: `src/main.py` → calls `polling/poller.py` (the advanced one)

**Local Testing:**
```bash
cd apps/subsquid-silo-tests/data-ingestion
EXPERIMENTAL_SUBSQUID=true \
DATABASE_URL="your_supabase_url" \
REDIS_URL="your_redis_url" \
python3 -m src.main
```

### Step 3: Verify TIER 0 Logs Appear

You should see:
```
🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned 10 markets: [...]
🎯 [TIER 0: USER_POSITIONS] Polling 10 markets with active positions
✅ [TIER 0] Updated 10 user position markets for fast resolution detection
```

### Step 4: Fix API Call If Needed

If the API returns 0 markets despite the debug log showing IDs, modify the query to use `condition_id`:

**Current (line 746 in data-ingestion/src/db/client.py):**
```python
SELECT DISTINCT sp.market_id, sp.end_date  ← Returns numeric ID
```

**Fix:**
```python
SELECT DISTINCT sp.condition_id as market_id, sp.end_date  ← Returns hex condition_id
```

This ensures the API receives the correct ID format.

---

## 🧪 TEST QUERIES

### Verify Market is Tracked
```sql
SELECT
    wm.market_id,
    wm.active_positions,
    sp.market_id as poll_market_id,
    sp.condition_id,
    sp.title,
    sp.status,
    sp.resolution_status
FROM watched_markets wm
LEFT JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id
WHERE sp.title LIKE '%Bitcoin%8:00AM-8:15AM%';
```

### Verify TIER 0 Query Returns Market
```sql
SELECT market_id
FROM (
    SELECT DISTINCT sp.market_id, sp.end_date
    FROM watched_markets wm
    JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id
    WHERE wm.active_positions > 0
      AND (sp.resolution_status != 'RESOLVED' OR sp.resolution_status IS NULL)
) sub
ORDER BY
  CASE WHEN end_date IS NULL THEN 1 ELSE 0 END,
  end_date ASC;
```

Expected: Should include `665974`

### Check Resolution Status
```sql
SELECT market_id, condition_id, title, status, resolution_status, accepting_orders
FROM subsquid_markets_poll
WHERE market_id = '665974';
```

Expected:
- `status`: CLOSED
- `resolution_status`: PROPOSED (not RESOLVED, so should be polled)
- `accepting_orders`: false

---

## 📝 NEXT STEPS

1. ✅ **Verify which poller is running** (data-ingestion vs indexer)
2. ✅ **Check Railway logs** for TIER 0 debug messages
3. ✅ **If no TIER 0 logs:** Deploy/run the advanced poller
4. ✅ **If TIER 0 logs appear but no markets updated:** Check API call format (numeric vs condition ID)
5. ✅ **Monitor logs** for the 🚨🚨🚨 debug line to confirm TIER 0 is active

---

## 📌 KEY TAKEAWAY

Your market **IS correctly stored** and **IS correctly selected** by the TIER 0 query. The issue is that you're likely running the **simple poller** which doesn't have TIER 0 logic at all.

**Action Required:** Switch to the advanced poller in `data-ingestion/` directory.
