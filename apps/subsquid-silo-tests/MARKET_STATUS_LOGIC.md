# Market Status Logic - Complete Guide

## Problem: Old Markets Flagged as ACTIVE

### Issue Example
```json
{
  "market_id": "248911",
  "title": "NBA: Denver Nuggets vs. LA Clippers 2023-02-26",
  "created_at": "2023-02-25 03:10:16.353+00",
  "end_date": "2023-02-26 00:00:00+00",
  "resolution_date": "2023-02-27 14:16:34+00",
  "status": "ACTIVE",                    // ❌ WRONG! Should be CLOSED
  "accepting_orders": true,              // ❌ WRONG! Should be false
  "tradeable": false,
  "outcome_prices": ["0.0000", "0.0000"]
}
```

**This market is 2 years old but still flagged as ACTIVE!** 🚨

---

## Root Cause: Gamma API Fields Misunderstanding

The Gamma API returns these fields:
```json
{
  "active": true,      // ← Contract activity state (NOT market status)
  "closed": false,     // ← Market closed flag
  "endDate": "2023-02-26",  // ← When market expires
  "resolutionDate": "2023-02-27",  // ← When result resolved
  "fpmmLive": true     // ← FMMS pool active
}
```

### **The Confusion**
- `active: true` means the SMART CONTRACT is still accepting interactions
- It does NOT mean the MARKET is tradeable
- Markets can have `active: true` but be past their `endDate`

---

## Solution: Strict Status Logic (NOW IMPLEMENTED)

### Status Determination (Priority Order)

```python
# 1. IF end_date has PASSED → CLOSED ✅
if end_date < NOW:
    status = "CLOSED"
    accepting_orders = False
    tradeable = False
    
# 2. ELSE IF closed flag is TRUE → CLOSED ✅
elif closed:
    status = "CLOSED"
    accepting_orders = False
    tradeable = False
    
# 3. ELSE → ACTIVE ✅
else:
    status = "ACTIVE"
    accepting_orders = is_active
    tradeable = is_active and (not end_date or end_date > NOW)
```

### Key Points

| Field | Logic |
|-------|-------|
| `end_date < NOW` | PRIMARY check for closure ⭐ |
| `closed` flag | Secondary check |
| `is_active` | Used for `accepting_orders` when market is active |
| `tradeable` | = `is_active` AND (no end_date OR end_date > NOW) |

---

## Database State Before & After Fix

### BEFORE FIX ❌
```sql
SELECT COUNT(*) FROM subsquid_markets_poll 
WHERE status = 'ACTIVE' AND end_date < NOW();

Result: 21,106 rows (OLD MARKETS STILL FLAGGED AS ACTIVE!)
```

### AFTER FIX ✅
```sql
SELECT COUNT(*) FROM subsquid_markets_poll 
WHERE status = 'ACTIVE' AND end_date < NOW();

Result: 0 rows (ALL EXPIRED MARKETS NOW CLOSED)
```

---

## How to Use in Bot Code

### 1. Quick Check: Is Market Tradeable?
```python
from src.db.client import DatabaseClient

db = DatabaseClient(...)

# Fast single check
is_tradeable = await db.is_market_tradeable("248905")
if not is_tradeable:
    # Show "Market closed" to user
    pass
```

### 2. Get Full Market Status
```python
market = await db.get_market_status("248905")

if market is None:
    # Market doesn't exist
    pass

print(f"Market: {market['title']}")
print(f"Status: {market['status']}")
print(f"Tradeable: {market['tradeable']}")
print(f"Outcomes: {market['outcomes']}")  # ["YES", "NO"]
print(f"Prices: {market['outcome_prices']}")  # [0.75, 0.25]
```

### 3. Get All Open Markets (for UI)
```python
open_markets = await db.get_open_markets_summary(limit=50)

for m in open_markets:
    print(f"{m['market_id']}: {m['title']}")
    print(f"  YES: {m['outcome_prices'][0]:.2%}")
    print(f"  NO:  {m['outcome_prices'][1]:.2%}")
    print(f"  24h Vol: ${m['volume_24hr']}")
```

---

## Poller Implementation

Location: `src/polling/poller.py` → `_parse_markets()`

```python
# Determine market status
is_active = market.get("active", False)
is_closed = market.get("closed", False)
now = datetime.now(timezone.utc)

# Status logic - STRICT ordering
if end_date and end_date < now:
    # 1️⃣ Date passed = market definitely closed
    status = "CLOSED"
    accepting_orders = False
    tradeable = False
elif is_closed:
    # 2️⃣ API says closed
    status = "CLOSED"
    accepting_orders = False
    tradeable = False
else:
    # 3️⃣ Otherwise ACTIVE
    status = "ACTIVE"
    accepting_orders = is_active
    tradeable = is_active and (not end_date or end_date > now)
```

---

## Migration: Re-sync Existing Data

If you have old data in DB with wrong status, run:

```sql
-- Fix all markets with passed end_date
UPDATE subsquid_markets_poll
SET 
    status = 'CLOSED',
    accepting_orders = false,
    tradeable = false
WHERE end_date < NOW()
AND status != 'CLOSED';

-- Check: Should be 0 rows now
SELECT COUNT(*) FROM subsquid_markets_poll 
WHERE status = 'ACTIVE' AND end_date < NOW();
```

---

## Testing

### Unit Test: Market Status Logic
```python
async def test_market_status_logic():
    # Old expired market
    expired = {
        "active": true,
        "closed": false,
        "endDate": "2023-02-26"  # 2 years ago!
    }
    # Should → CLOSED ✅
    
    # New upcoming market
    upcoming = {
        "active": true,
        "closed": false,
        "endDate": "2025-12-31"  # Future
    }
    # Should → ACTIVE ✅
    
    # Manually closed
    manual_closed = {
        "active": true,
        "closed": true,
        "endDate": "2025-12-31"
    }
    # Should → CLOSED ✅
```

---

## Summary Table

| Scenario | active | closed | end_date | Status | Tradeable |
|----------|--------|--------|----------|--------|-----------|
| Live market | true | false | Future | ACTIVE | true |
| Past end_date | true | false | Past | CLOSED | false |
| Manually closed | true | true | Future | CLOSED | false |
| Never closed | true | false | NULL | ACTIVE | true |
| Expired + closed | true | true | Past | CLOSED | false |

---

## Impact on Bot Features

### Copy Trading
- ✅ Only copy trades for ACTIVE (tradeable) markets
- ✅ Skip expired markets automatically

### Price Display
- ✅ Show "Market Closed" for status='CLOSED'
- ✅ Show live prices only for tradeable markets

### User Orders
- ✅ Prevent orders on closed markets
- ✅ Check `is_market_tradeable()` before showing order UI

### Portfolio
- ✅ Show PNL for resolved markets (even if expired)
- ✅ Calculate unrealized PNL for open positions

---

## References

- Poller: `src/polling/poller.py`
- DB Client: `src/db/client.py`
- Market Status Helpers: `get_market_status()`, `is_market_tradeable()`, `get_open_markets_summary()`

