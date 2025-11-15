# Poller Market Status Fix

**Date:** November 2, 2025
**Issue:** 10,833+ markets incorrectly marked `CLOSED` in database despite being `ACTIVE` in Gamma API

## Problem Analysis

### Root Cause
Markets were marked `CLOSED` in our database but Gamma API shows them as `closed: false, active: true`. This happened because:
- Stale data from old polling cycles (markets reopened but DB not updated)
- Markets marked CLOSED over 7 days ago never re-verified

### Examples
- Market `623604`: "Will the Government shutdown end November 16 or later?" - DB shows CLOSED, API shows ACTIVE
- Market `540236`: "Will the Tennessee Titans win Super Bowl 2026?" - DB shows CLOSED, API shows ACTIVE

## Solution Implemented

### 1. Enhanced Status Logic (poller.py)
**Location:** `_parse_standalone_market()` and `_enrich_market_from_event()`

```python
# BEFORE (line 1132 & 1231)
status = "CLOSED" if market.get("closed") else "ACTIVE"

# AFTER - Hybrid approach
is_closed = market.get("closed", False)
is_expired = False
if end_date:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    is_expired = end_date < cutoff

status = "CLOSED" if (is_closed or is_expired) else "ACTIVE"
```

**Benefits:**
- Trusts Gamma API `closed` field (primary source of truth)
- Auto-closes expired markets with 1-hour grace period
- Prevents future stale status issues

### 2. PASS 2.75: Re-verification Pass
**Location:** `poller.py` line 137-145

New polling pass that:
- Queries `CLOSED` markets with `end_date > NOW()` and `updated_at < NOW() - 7 days`
- Re-fetches from API to verify current status
- Updates DB if status changed (CLOSED → ACTIVE)
- Processes 200 markets per cycle (rate-limited)
- Preserves `events` data for grouping

**Logging:**
```
📊 [PASS 2.75] Re-verifying 200 stale CLOSED markets (>7 days old)
✅ [PASS 2.75] Market 623604 REOPENED (was CLOSED, now ACTIVE)
✅ [PASS 2.75] Re-verified 200 markets: 15 reopened, 185 still closed
```

### 3. Bulk Re-verification Script
**Location:** `scripts/reverify_closed_markets.py`

One-time script for immediate fix of all stale CLOSED markets.

## Usage

### Option A: Let PASS 2.75 Fix Gradually (Recommended)
Simply deploy the updated poller - it will automatically re-verify stale CLOSED markets over time.

**Timeline:** All 10,833 markets will be re-verified within ~54 cycles (~54 hours at 200/cycle)

**No action needed** - just monitor logs for:
```
✅ [PASS 2.75] Market XXXXX REOPENED (was CLOSED, now ACTIVE)
```

### Option B: Immediate Bulk Fix (Aggressive)
Run the bulk re-verification script for immediate correction:

```bash
# Dry run first (no changes)
cd apps/subsquid-silo-tests/data-ingestion
python scripts/reverify_closed_markets.py --dry-run --limit 100

# Full re-verification (all 10,833+ markets)
python scripts/reverify_closed_markets.py

# Or with limit
python scripts/reverify_closed_markets.py --limit 5000
```

**Timeline:** ~30-60 minutes for all 10,833 markets (rate-limited to 5 req/s)

## Monitoring

### Check Progress
```sql
-- Count incorrectly-closed markets (should decrease over time)
SELECT COUNT(*)
FROM subsquid_markets_poll
WHERE status = 'CLOSED' AND end_date > NOW();

-- Markets by status
SELECT
  status,
  COUNT(*) as count,
  COUNT(*) FILTER (WHERE end_date > NOW()) as with_future_end_date
FROM subsquid_markets_poll
GROUP BY status;
```

### Expected Results
- **Before fix:** ~10,833 CLOSED markets with future end_dates
- **After fix:** Should drop to near 0 (only legitimately closed markets remain)

### Logs to Watch
```bash
# In poller logs
grep "PASS 2.75" logs/poller.log
grep "REOPENED" logs/poller.log

# Count reopened markets per day
grep "REOPENED" logs/poller.log | grep "$(date +%Y-%m-%d)" | wc -l
```

## Deployment

### Railway Deployment
The poller will automatically deploy with the new PASS 2.75 logic.

**No config changes needed** - it's enabled by default.

To run bulk script on Railway:
```bash
# Via Railway CLI
railway run python scripts/reverify_closed_markets.py --dry-run
```

### Local Testing
```bash
cd apps/subsquid-silo-tests/data-ingestion

# Test dry run
python scripts/reverify_closed_markets.py --dry-run --limit 10

# Check poller picks up PASS 2.75
python -m src.main  # Watch for PASS 2.75 logs
```

## Verification

### Test Sample Markets
```bash
# Check if market 623604 is now ACTIVE in DB
psql $DATABASE_URL -c "SELECT market_id, title, status, end_date FROM subsquid_markets_poll WHERE market_id = '623604'"

# Verify against API
curl -s "https://gamma-api.polymarket.com/markets/623604" | jq '{id, closed, active, end_date: .endDate}'
```

### Health Check Query
```sql
-- Should show decreasing "incorrectly_closed" count
SELECT
  COUNT(*) FILTER (WHERE status = 'ACTIVE') as active_count,
  COUNT(*) FILTER (WHERE status = 'CLOSED') as closed_count,
  COUNT(*) FILTER (WHERE status = 'CLOSED' AND end_date > NOW()) as incorrectly_closed,
  COUNT(*) FILTER (WHERE status = 'ACTIVE' AND end_date < NOW()) as incorrectly_active
FROM subsquid_markets_poll;
```

## Files Changed

1. **poller.py** (main logic)
   - Enhanced status calculation in `_parse_standalone_market()` (line 1240-1249)
   - Enhanced status calculation in `_enrich_market_from_event()` (line 1132-1141)
   - Added `_reverify_stale_closed_markets()` method (line 525-611)
   - Added PASS 2.75 to poll cycle (line 137-145)

2. **scripts/reverify_closed_markets.py** (optional bulk fix)
   - New script for one-time bulk re-verification
   - 261 lines, fully documented with examples

## Performance Impact

### PASS 2.75 Impact
- **API calls:** 200 individual `/markets/{id}` requests per cycle (1 min)
- **DB queries:** 1 SELECT + up to 200 UPDATEs per cycle
- **Rate limiting:** 0.2s between requests (5 req/s max)
- **Cycle time:** +40-60 seconds per cycle (only when markets found)

### Bulk Script Impact
- **One-time:** 10,833 API requests over ~30-60 minutes
- **Rate limited:** 5 requests/second to avoid 429 errors
- **DB updates:** Batched every 50 markets

## Rollback Plan

If issues arise, revert with:
```bash
git revert <commit-hash>
```

The old logic will resume:
```python
# Reverts to simple status check
status = "CLOSED" if market.get("closed") else "ACTIVE"
```

**Note:** This will stop fixing stale markets but won't break existing functionality.

## Success Criteria

✅ PASS 2.75 runs every cycle without errors
✅ Incorrectly-closed count decreases over time
✅ Market 623604 shows as ACTIVE in DB (matches API)
✅ No increase in API rate limit errors
✅ Poller cycle time remains under 2 minutes

## Timeline

- **Day 1:** Deploy + optional bulk script → fix 100% of stale markets
- **Ongoing:** PASS 2.75 maintains correctness (prevents future staleness)
- **Week 1:** Monitor logs for reopened markets count
- **Week 2:** Verify incorrectly-closed count stays at ~0

## Support

**Logs:** `apps/subsquid-silo-tests/data-ingestion/logs/`
**Database:** Supabase project `fkksycggxaaohlfdwfle`
**API Docs:** https://docs.polymarket.com/developers/gamma-markets-api
