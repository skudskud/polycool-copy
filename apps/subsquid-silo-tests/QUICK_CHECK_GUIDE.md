# ⚡ Quick Check Guide - Market Data Fix Verification

## 🟢 Pre-Deployment Checklist (5 min)

### 1. Verify Code Changes
```bash
# Check that _validate_outcome_prices exists
grep -n "_validate_outcome_prices" src/polling/poller.py
# Should output: One match around line 320+

# Check API filter is updated
grep -n "active=true" src/polling/poller.py
# Should output: Line 137 contains "active=true" (not "closed=false")

# Verify no linting errors
pylint src/polling/poller.py
# Should output: "Your code has been rated at 10.00/10"
```

### 2. Verify Database Access
```bash
# Connect to Supabase and run a quick count
psql $DATABASE_URL -c "SELECT COUNT(*) FROM subsquid_markets_poll WHERE status='ACTIVE';"
# Current value: ~17,403 (WILL CHANGE AFTER DEPLOYMENT)
```

### 3. Document Baseline Metrics
Run these BEFORE deployment:
```sql
-- Save these values for comparison
SELECT 
  status,
  COUNT(*) as count
FROM subsquid_markets_poll 
GROUP BY status;

-- Expected BEFORE:
-- ACTIVE | 17403
-- CLOSED | 4813

SELECT 
  COUNT(*) FILTER (WHERE outcome_prices::text IN ('[0, 1]', '[1, 0]')) as placeholder_count
FROM subsquid_markets_poll;

-- Expected BEFORE: ~12,000+
```

---

## 🚀 Post-Deployment Verification (30 min)

### Step 1: Verify Deployment (after restart)
```bash
# Check service is running
docker ps | grep subsquid-poller
# Should show: UP status

# Check logs show new code
docker logs subsquid-poller | head -20
# Should show: "Poller service starting..."

# Verify method is loaded
docker logs subsquid-poller | grep "_validate_outcome_prices"
# OR manually trigger a request to check:
curl http://localhost:8000/health  # if there's a health endpoint
```

### Step 2: Monitor Polling Cycle (5-10 min)
```bash
# Watch for cycles to complete
docker logs -f subsquid-poller | grep "POLLER"

# You should see:
# [POLLER] Cycle #1 - Fetched XXX markets from 3 pages, upserted YYY, latency ~25000ms

# EXPECTED DIFFERENCES:
# - Fewer pages fetched (due to active=true filter)
# - Lower latency (~30s vs 45s)
# - Some markets might be marked CLOSED for first time
```

### Step 3: Verify Data Changes (after ~1-2 cycles, ~5 min)
```sql
-- Check ACTIVE count has decreased
SELECT COUNT(*) FROM subsquid_markets_poll WHERE status='ACTIVE';
-- Expected: 2,500-3,500 (was ~17,403)

-- Check CLOSED count has increased
SELECT COUNT(*) FROM subsquid_markets_poll WHERE status='CLOSED';
-- Expected: 19,000-20,000 (was ~4,813)

-- Check for remaining old markets marked ACTIVE
SELECT COUNT(*) FROM subsquid_markets_poll 
WHERE status='ACTIVE' AND created_at < '2024-01-01';
-- Expected: <50 (should be 0 for old markets)

-- Check outcome_prices validity improvement
SELECT 
  COUNT(*) FILTER (WHERE outcome_prices::text IN ('[0, 1]', '[1, 0]')) as placeholders_remaining
FROM subsquid_markets_poll;
-- Expected: <500 (was ~12,000)
```

### Step 4: Sample Market Inspection
```sql
-- Verify a few actual markets look correct
SELECT 
  market_id, 
  title,
  status,
  end_date,
  accepting_orders,
  tradeable,
  outcome_prices,
  EXTRACT(YEAR FROM created_at) as year
FROM subsquid_markets_poll 
WHERE status='ACTIVE'
LIMIT 5;

-- EXPECTED AFTER FIX:
-- - All should be recent (2025)
-- - All should have end_date in future
-- - accepting_orders should match status
-- - tradeable should be TRUE for ACTIVE
-- - outcome_prices should look like [0.35, 0.65], NOT [0, 1]
```

### Step 5: Performance Metrics Check
```bash
# From logs, extract cycle times
docker logs subsquid-poller | grep "latency" | tail -5

# Expected pattern:
# Cycle #1 latency ~35000ms
# Cycle #2 latency ~28000ms
# Cycle #3 latency ~25000ms
# Average should be ~25-30s (down from ~45-60s)

# Note: First cycle might be slower due to data migration
```

---

## 🔴 Rollback Checklist (if needed, <5 min)

### If Any Issues Detected:
```bash
# 1. Revert code
git revert HEAD  # or checkout previous version

# 2. Restart service
docker restart subsquid-poller

# 3. Wait and verify old behavior restored
docker logs -f subsquid-poller | grep "POLLER"

# 4. Check database (should slowly revert to old state)
SELECT COUNT(*) FROM subsquid_markets_poll WHERE status='ACTIVE';
# Should slowly increase back to ~17,403 (won't happen immediately, takes several cycles)
```

---

## 📊 Success Criteria

### ✅ DEPLOYMENT IS SUCCESSFUL IF:

1. **Status Changes**
   - [ ] ACTIVE count: 17,403 → 2,500-3,500
   - [ ] CLOSED count: 4,813 → 19,000-20,000

2. **Data Quality**
   - [ ] Placeholder prices: 12,000+ → <500
   - [ ] Old markets (pre-2024) in ACTIVE: ~15,000 → ~0

3. **Performance**
   - [ ] Polling cycle time: 45-60s → 25-30s
   - [ ] API pages fetched per cycle: 50-100 → 10-20

4. **Market Details (spot check)**
   - [ ] All ACTIVE markets have future end_date
   - [ ] All ACTIVE markets have accepting_orders=true
   - [ ] All ACTIVE markets have valid outcome_prices

### ❌ DEPLOYMENT FAILED IF:

1. Any of these occur:
   - [ ] Service doesn't restart (Docker error)
   - [ ] ACTIVE count doesn't decrease by 80%+
   - [ ] Old markets (2023) still marked ACTIVE after 1 hour
   - [ ] Outcome prices still showing [0,1] placeholders
   - [ ] Polling cycle takes >60s (regression)
   - [ ] Database errors in logs

---

## 📝 Quick Queries Cheat Sheet

### Paste these one at a time:

```sql
-- 1. Current state
SELECT status, COUNT(*) FROM subsquid_markets_poll GROUP BY status;

-- 2. Data quality
SELECT 
  COUNT(*) total,
  COUNT(*) FILTER (WHERE outcome_prices::text IN ('[0, 1]', '[1, 0]')) placeholders,
  COUNT(*) FILTER (WHERE outcome_prices IS NULL) missing
FROM subsquid_markets_poll;

-- 3. Old markets check
SELECT COUNT(*) FROM subsquid_markets_poll 
WHERE status='ACTIVE' AND created_at < '2024-01-01';

-- 4. Recent markets check
SELECT COUNT(*) FROM subsquid_markets_poll 
WHERE status='ACTIVE' AND EXTRACT(YEAR FROM created_at) = 2025;

-- 5. Consistency check (should all be ACTIVE if status='ACTIVE')
SELECT COUNT(*) FROM subsquid_markets_poll 
WHERE status='ACTIVE' AND accepting_orders=false;
-- Should be 0

-- 6. Year distribution
SELECT 
  EXTRACT(YEAR FROM created_at) as year,
  COUNT(*) FILTER (WHERE status='ACTIVE') as active_count,
  COUNT(*) FILTER (WHERE status='CLOSED') as closed_count
FROM subsquid_markets_poll
GROUP BY year
ORDER BY year DESC;
```

---

## 🎯 Expected Outcome

After successful deployment, running this query:
```sql
SELECT 
  status,
  COUNT(*) count,
  COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM created_at)=2025) count_2025,
  COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM created_at)<=2024) count_old
FROM subsquid_markets_poll
GROUP BY status;
```

Should show:
```
ACTIVE | ~2500 | ~2400 | ~100
CLOSED | ~19700 | ~100 | ~19600
```

**Summary**: ✅ All 2025 markets in ACTIVE, ✅ Old markets in CLOSED, ✅ Clean separation

---

## 💬 Questions?

If anything doesn't match expectations:
1. Check `docker logs subsquid-poller` for errors
2. Run SQL validation query #1-10 from `SQL_VALIDATION_QUERIES.sql`
3. Verify code changes are deployed: `grep "_validate_outcome_prices" /path/to/poller.py`
4. Consider rollback if issues persist

