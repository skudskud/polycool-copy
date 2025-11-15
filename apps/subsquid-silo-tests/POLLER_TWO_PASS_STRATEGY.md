# Poller Two-Pass Strategy

## Problem: Markets Never Transitioned from ACTIVE → CLOSED

### Original Issue
```
SELECT COUNT(*) FROM subsquid_markets_poll WHERE status = 'ACTIVE';
Result: 21,106 (same count, NEVER changes!)

Reason: Poller only fetched markets with active=true
→ Never saw the closed/expired markets to update their status!
```

---

## Solution: Two-Pass Polling Strategy

### Architecture

```
PASS 1: Active Markets (price updates)
  ├─ Query: GET /markets?active=true
  ├─ Limit: 500 pages (50,000 markets)
  ├─ Purpose: Get latest prices for tradeable markets
  └─ Upsert: All active markets (overwrite)

PASS 2: Closed Markets (status updates)
  ├─ Query: GET /markets?active=false
  ├─ Limit: 50 pages (5,000 markets)
  ├─ Filter: Only recently updated (last 24h)
  ├─ Purpose: Mark expired markets as CLOSED
  └─ Upsert: Only recently changed markets (efficient)
```

---

## Flow Diagram

```
Polling Cycle Starts
    ↓
┌─────────────────────────────────┐
│ PASS 1: Active Markets          │
├─────────────────────────────────┤
│ fetch_markets(offset=0, active_only=true)
│   → GET /markets?active=true&offset=0
│   → 500 pages max
│   → Upsert all to DB
│     status = ACTIVE (if meets criteria)
│
│ Result: ~250-300 active markets updated
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│ PASS 2: Closed Markets          │
├─────────────────────────────────┤
│ fetch_markets(offset=0, active_only=false)
│   → GET /markets?active=false&offset=0
│   → 50 pages max (5000 markets)
│   → Filter: updatedAt < 24h
│   → Upsert only recent changes
│     status = CLOSED (if end_date < NOW)
│
│ Result: ~100-200 closed markets updated
└─────────────────────────────────┘
    ↓
Log: "[POLLER] Cycle #N - PASS1: 250 active, PASS2: 150 closed, Total: 400"
    ↓
Next cycle in 60 seconds
```

---

## Code Changes

### Updated `_fetch_markets()` Signature

```python
async def _fetch_markets(self, offset: int, active_only: bool = True) -> List[Dict[str, Any]]:
    """Fetch markets from Gamma API
    
    Args:
        offset: Pagination offset
        active_only: 
            True → GET /markets?active=true (PASS 1)
            False → GET /markets?active=false (PASS 2)
    """
    if active_only:
        url = f"...?active=true&offset={offset}..."
    else:
        url = f"...?active=false&offset={offset}..."
```

### Updated `poll_cycle()` Logic

```python
# PASS 1: Active markets
markets = await self._fetch_markets(offset, active_only=True)
# → Updates prices, keeps status correct

# PASS 2: Closed markets
markets = await self._fetch_markets(offset, active_only=False)
# → Filters to recently updated (last 24h)
# → Updates status = CLOSED for expired markets
```

---

## Performance Impact

### Timeline per Cycle (60 seconds)

```
T+0s:      poll_cycle() starts
T+0-15s:   PASS 1 - Fetch 500 pages of active markets
           (~250 markets typical)
T+15s:     PASS 1 - Upsert to DB (2-3s)
T+18s:     PASS 2 - Fetch 50 pages of closed markets
           (~1000-5000 markets)
T+23s:     PASS 2 - Filter to recently updated (24h)
           (~100-200 markets typical)
T+25s:     PASS 2 - Upsert to DB (1-2s)
T+27s:     Done! Wait 33 seconds until next cycle
────────────────────────────────
Total: ~27 seconds (well within 60s cycle)
```

### DB Query Performance

Both passes use indexed columns:
```
PASS 1: WHERE status = 'ACTIVE' AND tradeable = true
        → Uses idx_status, idx_tradeable

PASS 2: WHERE status = 'CLOSED' AND end_date < NOW
        → Condition evaluates in Python
        → Uses idx_status on upsert
```

**Result:** No performance degradation ✅

---

## Data Flow Example

### PASS 1: Active Market Updates

```json
{
  "id": "248905",
  "title": "Trump wins 2024?",
  "active": true,
  "closed": false,
  "endDate": "2024-11-06",
  "updatedAt": 1729608000,      // Just now
  "outcomePrices": [0.85, 0.15]  // Fresh prices!
}
↓
Parsed by poller:
- status = "ACTIVE" (end_date > NOW)
- tradeable = true (active && end_date > NOW)
- outcome_prices = [0.85, 0.15]

Upserted to DB ✅
```

### PASS 2: Closed Market Updates

```json
{
  "id": "248911",
  "title": "NBA Game 2023-02-26",
  "active": true,
  "closed": false,
  "endDate": "2023-02-26",       // 2 YEARS AGO!
  "updatedAt": 1729608000,       // Recently updated metadata
  "outcomePrices": [0, 0]
}
↓
Filter: updatedAt < 24h?
Yes! (recently updated) → Include in PASS 2

Parsed by poller:
- status = "CLOSED" (end_date < NOW) ✅ FIX!
- tradeable = false
- accepting_orders = false

Upserted to DB ✅
```

---

## Verification Queries

### Check PASS 1 Working (Active Markets Updated)

```sql
SELECT COUNT(*) FROM subsquid_markets_poll
WHERE status = 'ACTIVE'
AND updated_at > NOW() - INTERVAL '5 minutes';

Expected: 200-400 rows (recently updated active markets)
```

### Check PASS 2 Working (Closed Markets Updated)

```sql
SELECT COUNT(*) FROM subsquid_markets_poll
WHERE status = 'CLOSED'
AND end_date < NOW()
AND updated_at > NOW() - INTERVAL '1 hour';

Expected: >0 rows (recently updated old markets now CLOSED)
```

### Verify No Anomalies

```sql
-- This should return 0 (no old markets flagged as ACTIVE)
SELECT COUNT(*) FROM subsquid_markets_poll
WHERE status = 'ACTIVE'
AND end_date < NOW();

Expected: 0 rows ✅
```

---

## Expected Log Output

```
2025-10-22 14:45:00 - INFO - 📊 [PASS 1] Fetching ACTIVE markets (limit=500 pages)...
2025-10-22 14:45:02 - INFO - HTTP Request: GET .../markets?active=true&offset=0
2025-10-22 14:45:03 - INFO - ✅ Upserted 100 enriched markets
2025-10-22 14:45:03 - INFO - ✅ Upserted 100 enriched markets
... (repeat for 500 pages)
2025-10-22 14:45:15 - INFO - ✅ [PASS 1] Fetched 250 active markets, upserted 250
2025-10-22 14:45:15 - INFO - 📊 [PASS 2] Fetching CLOSED/EXPIRED markets (recent only, limit=500)...
2025-10-22 14:45:16 - INFO - HTTP Request: GET .../markets?active=false&offset=0
2025-10-22 14:45:16 - INFO - ✅ Upserted 50 enriched markets
... (repeat for 50 pages)
2025-10-22 14:45:25 - INFO - ✅ [PASS 2] Fetched closed markets, upserted 150 recently updated
2025-10-22 14:45:25 - INFO - [POLLER] Cycle #123 - 
                               PASS1: 250 active markets, 
                               PASS2: 150 closed/expired markets, 
                               Total upserted: 400, 
                               latency 25000ms
```

---

## Edge Cases Handled

### 1. Market Expires During Trading Session
```
PASS 1: Market exists (still active according to API)
        → Gets upserted with current prices

60 seconds later...

PASS 2: Market now expired (end_date < NOW)
        → Gets upserted with status = CLOSED
```

### 2. No Recently Closed Markets
```
PASS 2 finds 0 markets updated in last 24h
→ Simply logs: "Upserted 0 recently updated"
→ No error, no problem
```

### 3. Market Transitions: ACTIVE → CLOSED → RESOLVED
```
Day 1:
  PASS 1: status = ACTIVE ✅
  
Day 2 (expiry date passed):
  PASS 1: Skip (not in active=true anymore)
  PASS 2: status = CLOSED ✅
  
Day 3 (resolved):
  PASS 2: status = CLOSED ✅ (same)
```

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| Active markets query | ✅ Works | ✅ Works (PASS 1) |
| Closed markets query | ❌ Never updated | ✅ Works (PASS 2) |
| Status transitions | ❌ Stuck | ✅ Dynamic |
| Cycle time | ~15s | ~27s |
| DB load | Low | Slightly higher (worth it) |
| Accuracy | ❌ Old markets ACTIVE | ✅ Correct status |

---

## Deployment

Railway will auto-redeploy when code is pushed:
- T+0: Git push
- T+3-5: Railway rebuilds
- T+6: Poller starts with NEW two-pass logic
- T+7: First PASS 1 + PASS 2 begins
- T+35: Check logs for both passes

