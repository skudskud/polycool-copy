# Resolution Worker - DISABLED

**Status:** DISABLED - Manual redeem system implemented

**Date Disabled:** January 2025

## Reason

The resolution-worker cron job has been replaced by an on-demand detection system in the `/positions` command.

## What Changed

- **Before:** Resolution-worker ran hourly, auto-detected resolved markets, created `resolved_positions` records, and sent notifications
- **After:** Redeemable positions are detected on-demand when users call `/positions` command

## Action Required

**IMPORTANT:** Disable the resolution-worker cron job in Railway:

1. Go to Railway Dashboard → resolution-worker service
2. Navigate to Settings → Cron
3. Disable or remove the cron schedule (`0 * * * *`)
4. Optionally pause/delete the service entirely

## New Flow

1. User buys position → Position tracked on blockchain
2. Market resolves → Poller updates `subsquid_markets_poll.resolution_status = 'RESOLVED'`
3. User calls `/positions` → System detects redeemable positions
4. System creates `resolved_positions` record lazily (if not exists)
5. Position appears in "Claimable Winnings" section with redeem button
6. User clicks redeem → Executes redemption transaction

## Benefits

- No cron job overhead
- Real-time detection when user needs it
- No unnecessary notifications (user-driven)
- Reduced API calls (only when user checks positions)
- Better user experience (immediate feedback)

## Migration Notes

- Existing `resolved_positions` records remain valid
- New records are created automatically when detected
- No data migration needed
