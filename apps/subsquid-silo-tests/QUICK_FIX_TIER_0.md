# 🚨 QUICK FIX: TIER 0 Not Appearing

## TL;DR - The Problem

You showed me the **WRONG poller file**. You have 2 pollers:

1. ❌ **Simple Poller** (the one you attached): `indexer/src/polling/poller.py` - NO TIER 0
2. ✅ **Advanced Poller** (the one you NEED): `data-ingestion/src/polling/poller.py` - HAS TIER 0

## ✅ Immediate Solution

### Option 1: Check Which Service is Running

```bash
# If using Railway
railway status
railway logs | grep "TIER 0"

# If using Docker
docker ps
docker logs <container_id> | grep "TIER 0"
```

**Expected Output (if correct poller is running):**
```
🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned 10 markets: ['628803', '619189', '665974', ...]
🎯 [TIER 0: USER_POSITIONS] Polling 10 markets with active positions
✅ [TIER 0] Updated 10 user position markets for fast resolution detection
```

**If you DON'T see this:** You're running the wrong poller.

---

### Option 2: Run the Correct Poller Locally

```bash
cd apps/subsquid-silo-tests/data-ingestion

# Set environment variables
export EXPERIMENTAL_SUBSQUID=true
export DATABASE_URL="postgresql://postgres:[PASSWORD]@db.fkksycggxaaohlfdwfle.supabase.co:5432/postgres"
export REDIS_URL="your_redis_url"
export POLL_MS=60000
export POLLER_ENABLED=true
export STREAMER_ENABLED=false
export WEBHOOK_ENABLED=false
export BRIDGE_ENABLED=false

# Run the poller
python3 -m src.main
```

You should immediately see:
```
✅ Poller service starting...
🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned X markets: [...]
```

---

## 🔍 Why Your Market Should Appear

### Database Check ✅
```sql
-- Your market IS tracked
SELECT market_id, active_positions
FROM watched_markets
WHERE market_id = '0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7';
-- Result: active_positions = 1 ✅
```

### TIER 0 Query ✅
```sql
-- Your market IS in the TIER 0 query results
SELECT market_id
FROM (
    SELECT DISTINCT sp.market_id, sp.end_date
    FROM watched_markets wm
    JOIN subsquid_markets_poll sp ON wm.market_id = sp.condition_id
    WHERE wm.active_positions > 0
      AND (sp.resolution_status != 'RESOLVED' OR sp.resolution_status IS NULL)
) sub;
-- Result: ['628803', '619189', '665974', ...] ✅
--                              ^^^^^^ Your market is here!
```

### Resolution Status ✅
```sql
-- Your market is NOT resolved yet, so it SHOULD be polled
SELECT resolution_status
FROM subsquid_markets_poll
WHERE market_id = '665974';
-- Result: 'PROPOSED' (not 'RESOLVED') ✅
```

**Everything is configured correctly in the database!**

---

## 🐛 Potential Issue: API ID Format

The TIER 0 query returns **numeric IDs** (e.g., `"665974"`), and the poller calls:

```python
url = f"https://gamma-api.polymarket.com/markets?id=665974,628803,619189&limit=500"
```

**Test if this works:**
```bash
# Test numeric ID
curl "https://gamma-api.polymarket.com/markets?id=665974"

# Test condition ID (if numeric fails)
curl "https://gamma-api.polymarket.com/markets?conditionId=0xb1d1305a0b81a27413068148539ef8d15d427cc835a70cb4ba78238ce4f6cca7"
```

### Fix if API Doesn't Accept Numeric IDs

Edit `data-ingestion/src/db/client.py`, line 744:

**Current:**
```python
SELECT DISTINCT sp.market_id, sp.end_date  ← Returns "665974"
```

**Fix:**
```python
SELECT DISTINCT sp.condition_id as market_id, sp.end_date  ← Returns "0xb1d1..."
```

Then update the API call in `poller.py` line 857:

**Current:**
```python
url = f"{settings.GAMMA_API_URL}?id={ids_param}&limit=500"
```

**Fix:**
```python
url = f"{settings.GAMMA_API_URL}?conditionId={ids_param}&limit=500"
```

---

## 📋 Checklist

- [ ] Verify you're running `data-ingestion/src/polling/poller.py` (not `indexer/src/polling/poller.py`)
- [ ] Check logs for `🚨🚨🚨 [TIER 0 DEBUG]` message
- [ ] Verify TIER 0 query returns your market ID (665974)
- [ ] Test if API accepts numeric IDs or condition IDs
- [ ] Update query/API call if needed

---

## 🎯 Expected Behavior (When Working)

Every 60 seconds, you should see:

```
[POLLER] Cycle #1
🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned 10 markets: ['628803', '619189', '665974', ...]
🎯 [TIER 0: USER_POSITIONS] Polling 10 markets with active positions
✅ [TIER 0] Updated 10 user position markets for fast resolution detection
[POLLER] Cycle #1 - PASS1: 5000 active markets, PASS2: 200 closed/expired markets, Total upserted: 5210, latency 2500ms
```

Your market should be updated **every single cycle** because it has `active_positions = 1`.

---

## 🆘 Still Not Working?

1. **Check which Python process is running:**
   ```bash
   ps aux | grep polling
   ```

2. **Check Railway deployment:**
   - Service name should be "Data Ingestion" (not "DipDup Indexer")
   - Entry point: `data-ingestion/src/main.py`

3. **Enable debug logging:**
   ```python
   # In data-ingestion/src/config.py
   LOG_LEVEL: str = "DEBUG"  # Change from INFO to DEBUG
   ```

4. **Share your logs:**
   ```bash
   railway logs --service data-ingestion > poller_logs.txt
   ```
   Then check for the TIER 0 debug messages.

---

## 📌 Summary

- ✅ Your market is correctly stored in the database
- ✅ Your market is correctly selected by TIER 0 query
- ✅ Your market has `active_positions = 1`
- ✅ Your market has `resolution_status = 'PROPOSED'` (not RESOLVED)
- ❌ You're likely running the wrong poller (simple version without TIER 0)

**Next Step:** Verify which poller is running and switch to the advanced one if needed.
