# Manual Redeem System - Implementation

**Date:** January 2025
**Status:** ✅ Implemented

## Overview

The redeem system has been migrated from an automated cron-based approach to an on-demand manual detection system integrated into the `/positions` command.

## Architecture

### Flow

```
User calls /positions
    ↓
Fetch positions from blockchain API
    ↓
Detect redeemable positions (RESOLVED markets + winning tokens)
    ↓
Create resolved_positions records lazily (if not exists)
    ↓
Filter redeemable from active positions
    ↓
Display: Active positions + Claimable Winnings section
    ↓
User clicks "Redeem" button → Execute redemption
```

### Key Components

1. **RedeemablePositionDetector** (`core/services/redeemable_position_detector.py`)
   - Detects positions in RESOLVED markets
   - Checks if user's outcome matches winning_outcome
   - Creates `resolved_positions` records lazily
   - Uses Redis caching (5min TTL) for performance

2. **Positions Handler** (`telegram_bot/handlers/positions/core.py`)
   - Calls detector before displaying positions
   - Filters redeemable positions from active display
   - Ensures claimable positions appear in separate section

3. **Position View Builder** (`telegram_bot/services/position_view_builder.py`)
   - Reads existing `resolved_positions` records
   - Displays in "Claimable Winnings" section
   - Shows redeem button for each claimable position

## Detection Logic

### Market Resolution Status

Uses `subsquid_markets_poll` table:
- `resolution_status = 'RESOLVED'` (market fully resolved)
- `winning_outcome IS NOT NULL` (0 for NO, 1 for YES)

### Position Redeemability

A position is redeemable if:
1. Market is RESOLVED (`resolution_status = 'RESOLVED'`)
2. User has tokens (`size >= 0.1` to filter dust)
3. User's outcome matches winning outcome:
   - YES tokens + `winning_outcome = 1` → redeemable
   - NO tokens + `winning_outcome = 0` → redeemable

### Lazy Creation

`resolved_positions` records are created automatically when:
- Position is detected as redeemable
- Record doesn't already exist for this user+market
- Calculates all fields: `net_value`, `fee_amount`, `pnl`, etc.

## Performance Optimizations

1. **Batch DB Queries**
   - Single query for all condition_ids at once
   - Avoids N+1 query problem

2. **Redis Caching**
   - Cache key: `redeemable_check:{user_id}:{condition_id}`
   - TTL: 5 minutes
   - Reduces DB queries for repeated `/positions` calls

3. **Minimal Logging**
   - DEBUG level for individual checks
   - INFO level only when redeemable found
   - No log spam

4. **No Additional API Calls**
   - Reuses position data already fetched
   - No extra blockchain queries

## Edge Cases Handled

- **Dust positions** (< 0.1 tokens): Filtered out
- **Losing positions**: Not shown (not redeemable)
- **Missing market data**: Gracefully skipped
- **DB errors**: Logged but don't break flow
- **Duplicate records**: Checks before creating

## Migration from Resolution Worker

### What Changed

- **Before:** Cron job ran hourly, auto-detected and notified users
- **After:** Detection happens on-demand when user checks positions

### Benefits

- ✅ No cron job overhead
- ✅ Real-time detection when needed
- ✅ User-driven (no spam notifications)
- ✅ Reduced API calls
- ✅ Better UX (immediate feedback)

### Action Required

**IMPORTANT:** Disable resolution-worker cron job in Railway:
1. Railway Dashboard → resolution-worker service
2. Settings → Cron → Disable/Remove schedule
3. See `apps/resolution-worker/DISABLED.md` for details

## Testing

### Manual Test Flow

1. Buy position in a market
2. Wait for market to resolve (poller updates `resolution_status`)
3. Call `/positions` command
4. Verify position appears in "Claimable Winnings" section
5. Click "Redeem" button
6. Verify redemption executes successfully

### Expected Behavior

- Redeemable positions appear in "Claimable Winnings" (not active positions)
- Redeem button is present for each claimable position
- After redemption, position status changes to REDEEMED
- Position no longer appears in claimable section

## Monitoring

### Key Metrics

- Detection success rate (should be ~100% for RESOLVED markets)
- Redis cache hit rate (should improve with repeated calls)
- DB query performance (should be <100ms for batch queries)
- Log volume (should be minimal, mostly DEBUG)

### Logs to Watch

- `💰 [REDEEM] Detected redeemable position` - Successful detection
- `✅ [REDEEM] Created resolved_position` - Lazy creation success
- `❌ [REDEEM] Error` - Any errors (should be rare)

## Future Improvements

- Add admin endpoint to manually trigger detection
- Add metrics/analytics for redemption rates
- Consider batch redemption (redeem multiple at once)
- Add expiration warnings (if positions expire before redeem)
