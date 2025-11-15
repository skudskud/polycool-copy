# Verify Market Status Fix

## Quick Check After Deployment

### 1. Query the Database (Should Show 0 Old Markets as ACTIVE)

```sql
-- ✅ THIS SHOULD RETURN 0 ROWS (if fix works)
SELECT COUNT(*) as old_active_markets
FROM subsquid_markets_poll
WHERE status = 'ACTIVE' 
AND end_date < NOW();
```

**Expected:** `{ old_active_markets: 0 }`

If you get any rows, the fix didn't work. ❌

---

### 2. Check Specific Old Market (248911 from example)

```sql
SELECT
  market_id,
  title,
  status,
  accepting_orders,
  tradeable,
  end_date,
  NOW() as current_time
FROM subsquid_markets_poll
WHERE market_id = '248911';
```

**Expected:**
```
market_id    | 248911
title        | NBA: Denver Nuggets vs. LA Clippers 2023-02-26
status       | CLOSED          ✅ (was ACTIVE before)
accepting_orders | false        ✅ (was true before)
tradeable    | false           ✅ (correct)
end_date     | 2023-02-26      (2 years ago)
```

---

### 3. Check Recent/Live Markets (Should Be ACTIVE)

```sql
SELECT
  market_id,
  title,
  status,
  accepting_orders,
  tradeable,
  end_date,
  NOW() as current_time
FROM subsquid_markets_poll
WHERE status = 'ACTIVE'
AND tradeable = true
ORDER BY end_date DESC
LIMIT 10;
```

**Expected:** Markets with `end_date` > NOW should all have:
- `status = ACTIVE` ✅
- `accepting_orders = true` ✅ (if active flag was true)
- `tradeable = true` ✅

---

### 4. Statistics Check

```sql
-- Compare status distribution
SELECT
  status,
  COUNT(*) as count,
  MAX(end_date) as newest_in_status,
  MIN(end_date) as oldest_in_status
FROM subsquid_markets_poll
GROUP BY status
ORDER BY status;
```

**Expected Output (Example):**
```
status  | count | newest_in_status | oldest_in_status
ACTIVE  | 250   | 2025-12-31       | 2025-10-23
CLOSED  | 21356 | 2025-08-15       | 2023-01-01
```

Key Points:
- ACTIVE markets should have end_dates MOSTLY in the future
- CLOSED markets should include old ones from 2023, 2024

---

## After Next Poller Run

### Expected Behavior

✅ **Poller runs every 60 seconds (1 minute)**

Each cycle should:
1. Fetch markets from Gamma API
2. Parse status with NEW strict logic:
   - Check `end_date < NOW` first
   - Then check `closed` flag
   - Otherwise mark ACTIVE
3. Upsert to DB with correct status/tradeable flags

### Logs to Look For

```
2025-10-22 14:30:00 - ✅ Market 248905 ACTIVE: end_date=2025-12-31, active=true
2025-10-22 14:30:00 - ✅ Market 248911 CLOSED: end_date passed (2023-02-26)
2025-10-22 14:30:00 - ✅ Market 248912 CLOSED: closed flag true
```

If you see `❌` errors in logs, check the Poller logs on Railway.

---

## Rollback (If Needed)

If the fix causes issues:

1. **Revert the commit:**
```bash
git revert b7c8ace  # Revert poller fix
git push
```

2. **Fix will re-run Poller on Railway** (auto-redeploy)

3. **Manual fix if needed:**
```sql
-- Restore old status logic (not recommended)
-- Contact for manual SQL fix
```

---

## Timeline

- **T+0**: Code pushed to GitHub
- **T+1-2min**: Railway detects new code
- **T+3-5min**: Railway rebuilds & redeploys Poller
- **T+6min**: Poller starts with new logic
- **T+7min**: First polls with NEW status logic arrive
- **T+8-10min**: Check DB with queries above

**Total:** ~10 minutes from push to live fix ✅

---

## Success Indicators

| Check | Before | After |
|-------|--------|-------|
| Old markets ACTIVE | 21,106 ❌ | 0 ✅ |
| New markets ACTIVE | ~250 | ~250 ✅ |
| Upsert logs | Parse errors | Clean logs ✅ |
| `tradeable` field | Wrong on expired | Correct ✅ |
| Bot can check status | Unreliable | `is_market_tradeable()` works ✅ |

