# Resolution Status: Complete Lifecycle

## 📊 Current State (Nov 3, 2025)

```
subsquid_markets_poll table:
├── PENDING (45,964 markets)
│   └── Markets still open OR just closed (<1h)
│       └── No winning_outcome yet
│
├── PROPOSED (7,635 markets)
│   └── Markets closed, outcome proposed
│       └── ⚠️ NO winning_outcome filled yet!
│           (This is the bug - poller doesn't fill it)
│
└── RESOLVED (0 markets)
    └── Will populate AFTER poller redeploy
        └── winning_outcome will be = 0 or 1
```

---

## 🔄 Market Lifecycle (After Redeploy)

### Timeline Example: "Will Bitcoin hit $100k?"

```
Day 1: Market Opens
┌─────────────────────────────┐
│ Market Created              │
│ status = "ACTIVE"           │
│ resolution_status = PENDING │
│ winning_outcome = NULL      │
│ end_date = 2025-12-31       │
└─────────────────────────────┘
        ↓ (60 sec polling)
┌─────────────────────────────┐
│ Price: $65k (ongoing)       │
│ Status unchanged            │
│ outcome_prices = [0.45, 0.55] │
└─────────────────────────────┘

Day 90: Market Expires (2025-12-31 expires)
┌─────────────────────────────────────────────┐
│ MOMENT: end_date < NOW() is TRUE            │
│ Poller detects: "Market expired!"           │
│ status = "CLOSED"                           │
│ resolution_status = "PROPOSED"              │
│ winning_outcome = NULL (not yet from API)   │
│ resolution_date = NOW()                     │
│                                             │
│ ⏳ Waiting for Polymarket to post outcome   │
└─────────────────────────────────────────────┘
        ↓ (API check in next cycle)
        ↓ (+1-2 hours typically)

┌─────────────────────────────────────────────┐
│ API Response:                               │
│ market.outcome = "No"  (Bitcoin didn't hit) │
│ market.outcomePrices = [0.99, 0.01]        │
│                                             │
│ Poller detects:                             │
│ resolution_status = "RESOLVED"              │
│ winning_outcome = 0  (NO won)               │
│ resolution_date = (when confirmed)          │
│                                             │
│ ✅ NOW ready for REDEEM!                    │
└─────────────────────────────────────────────┘
```

---

## 💎 How Redeem Connects

### For User Who Bet "YES" ($10 investment):

```
Step 1: Position Created
┌──────────────────────────────┐
│ resolved_positions           │
│ user_id = 123456             │
│ market_id = "654321"         │
│ outcome = "YES"              │
│ tokens_held = 10             │
│ total_cost = 10 USDC         │
│ status = "PENDING"           │
│ winning_outcome = (from API) │
│ is_winner = (YES == 0 ?) NO! │
└──────────────────────────────┘

Step 2: Market Resolves
┌────────────────────────────────────────────┐
│ subsquid_markets_poll.winning_outcome = 0  │
│                                            │
│ resolved_positions.is_winner = (           │
│   user_outcome="YES" AND                   │
│   market_winning_outcome=0  ← Does NOT match!
│ ) = FALSE  ❌                              │
│                                            │
│ → User loses position                      │
│ → gross_value = 0                          │
│ → net_value = 0                            │
│ → pnl = 0 - 10 = -10 USDC                 │
└────────────────────────────────────────────┘

Step 3: Redeem Execution
┌────────────────────────────────────────────┐
│ status = PENDING                           │
│   ↓ (Queue Filler finds it)                │
│ status = PROCESSING                        │
│   ↓ (Executor checks: is_winner = false)   │
│ Payout = 0                                 │
│ status = SUCCESS                           │
│ redeemed_at = NOW()                        │
│                                            │
│ Notification: "❌ Lost on Bitcoin market"   │
└────────────────────────────────────────────┘
```

### For User Who Bet "NO" ($10 investment):

```
Same flow, BUT:

is_winner = (
  user_outcome="NO" AND
  market_winning_outcome=0  ← MATCHES!
) = TRUE  ✅

→ User wins!
→ gross_value = 10 USDC
→ net_value = 10 * 0.99 = 9.90 USDC
→ pnl = 9.90 - 10 = -0.10 USDC (slight loss due to 1% fee)

Notification: "✅ Won! Redeemed 9.90 USDC"
```

---

## 🔗 The Connection Chain

```
Poller Cycle (every 60s)
│
├─ Fetch ALL markets from API
│
├─ PASS 1: Groupes events
│  └─ events field populated
│
├─ PASS 2: All active markets
│  └─ Preserved events from PASS 1
│
└─ PASS 3: Detect resolution
   │
   ├─ Check: end_date < NOW()?
   │  └─ Yes → status = CLOSED
   │          resolution_status = PROPOSED
   │
   ├─ Check: API.outcome available?
   │  └─ Yes → resolution_status = RESOLVED
   │          winning_outcome = 0 or 1 ← ✅ THIS IS POPULATED HERE
   │
   └─ Update subsquid_markets_poll
      │
      ↓
Queue Filler (every 5 min)  ← NEW SERVICE TO BUILD
│
└─ Query:
   SELECT * FROM resolved_positions rp
   JOIN subsquid_markets_poll mp USING (market_id)
   WHERE rp.status = 'PENDING'
     AND mp.resolution_status = 'RESOLVED'  ← Finds resolved markets!
     AND mp.winning_outcome IS NOT NULL     ← Has winner!
   │
   ↓
   Push to Redis queue
   Update resolved_positions.status = PROCESSING
      │
      ↓
Redeem Executor (continuous worker)  ← NEW SERVICE TO BUILD
│
├─ Pop from queue
├─ Calculate: is_winner = (position.outcome == market.winning_outcome)?
├─ Calculate: payout = is_winner ? tokens * 0.99 : 0
├─ Execute Polymarket redeem API
├─ Update resolved_positions.status = SUCCESS
└─ Send Telegram notification
```

---

## ⚡ Why This Is Efficient

### 1. **Single Source of Truth**
```
subsquid_markets_poll.winning_outcome
   ↓ (shared by)
resolved_positions.winning_outcome (calculated from above)
```

No duplication, no sync issues.

### 2. **Event-Driven, Not Polling**
```
❌ BAD:  Every 1 min check: "Is this user's market resolved?"
        → 50,000 positions × 50k markets = 2.5B DB queries/day!

✅ GOOD: Query only markets that are RESOLVED
         ~ 100-500 positions/day that need redeem
         → ~10 DB queries/day
```

### 3. **Retry Mechanism Built-In**
```
If Polymarket API fails:
- Status = PROCESSING stays
- Add to retry queue
- Exponential backoff: 5min, 15min, 1h, 6h
- Max 8 attempts before FAILED
```

### 4. **Fee Handling Automatic**
```
1% fee already calculated in resolved_positions:
net_value = gross_value * 0.99

No extra logic needed in redeem bot!
```

---

## 🚨 Current Blocker

```
resolution_status = PROPOSED (7,635 markets)
  ↓
winning_outcome = NULL  ⚠️ ← BLOCKER!
  ↓
Queue Filler can't identify winners
  ↓
Redeem can't execute
```

**Fix:** Poller must run 1+ cycles to populate `winning_outcome` for PROPOSED markets.

---

## ✅ After Redeploy (What You'll See)

```sql
-- Query 1: Check RESOLVED markets appearing
SELECT COUNT(*) FROM subsquid_markets_poll
WHERE resolution_status = 'RESOLVED';
-- Should go from 0 → 100-500 within 1 hour

-- Query 2: Check winning_outcome filled
SELECT COUNT(*) FROM subsquid_markets_poll
WHERE resolution_status = 'RESOLVED'
  AND winning_outcome IS NOT NULL;
-- Should match Query 1 count

-- Query 3: Positions ready for redeem
SELECT COUNT(*) FROM resolved_positions rp
JOIN subsquid_markets_poll mp USING (market_id)
WHERE rp.status = 'PENDING'
  AND mp.resolution_status = 'RESOLVED'
  AND mp.winning_outcome IS NOT NULL;
-- Should be > 0 and growing
```

---

## 🎯 Implementation Roadmap

```
CURRENT (Nov 3):
├─ Poller: ✅ Implemented resolution detection
├─ DB: ✅ Columns exist
└─ Query: ✅ Can identify ready positions

IMMEDIATE (Next 1h):
├─ Redeploy poller
└─ Monitor: winning_outcome populated? ✅

WEEK 1:
├─ Build Queue Filler Service
├─ Build Redeem Executor Worker
├─ Test with 1-2 positions manually
└─ Monitor for failures

WEEK 2:
├─ Add Retry Handler
├─ Add admin alerts
└─ Go live for all users

PRODUCTION:
├─ Monitor:
│  ├─ Success rate (target >95%)
│  ├─ Average time to redeem (target <5 min)
│  └─ Failed count (alert if >1% daily)
└─ Optimize as needed
```

---

**Key Insight:** Everything is in place. We just need to:
1. ✅ Deploy poller with resolution logic
2. ⏳ Build 2 services: Queue Filler + Executor
3. 🚀 Go live!
