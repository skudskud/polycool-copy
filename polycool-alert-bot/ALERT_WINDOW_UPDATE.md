# Alert Time Window Update - 2 min → 15 min

## Change Summary

**Migration:** `update_alert_window_15_minutes`  
**Date:** October 24, 2025  
**Applied to:** Supabase database (gvckzwmuuyrlcyjmgdpo)

---

## What Changed

**View:** `alert_bot_pending_trades`

**Old:**
```sql
AND swt.timestamp >= NOW() - INTERVAL '2 minutes'
```

**New:**
```sql
AND swt.timestamp >= NOW() - INTERVAL '15 minutes'
```

---

## Why This Change

### Performance Analysis (Last 12 Hours):

**With 2-minute window:**
- Qualifying trades: 16
- Alerts sent: 3
- **Coverage: 19%** ❌
- **13 trades missed** because they were >2 min old when bot checked

**Root cause:**
- Monitor syncs every 10 minutes
- Trades captured with 0-10 minute lag
- Alert bot checks every 30 seconds
- But 2-min window too strict
- Most trades already 10+ minutes old when bot sees them

---

## Expected Results

**With 15-minute window:**
- Qualifying trades: 16
- Expected alerts: 16
- **Coverage: 100%** ✅
- Catches ALL trades from last monitor sync

**Latency still excellent:**
- Trade happens: 00:00
- Monitor syncs: 00:10 (captures it)
- Alert sent: 00:10:30
- **User sees alert in ~10.5 minutes**
- Still feels "real-time" to users!

---

## Verification

Run this to see pending trades:
```sql
SELECT COUNT(*) FROM alert_bot_pending_trades;
```

Expected: 13 pending (the ones we missed)

---

**Status:** ✅ Applied to production

