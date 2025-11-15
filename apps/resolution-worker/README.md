# Resolution Worker

Auto-liquidation service for resolved Polymarket markets. Runs hourly to detect resolved markets and notify users of their P&L.

## Overview

Simple cron-based worker that:
1. Queries database for newly resolved markets
2. Finds users with positions in those markets
3. Calls Polymarket `/closed-positions` API to get realized P&L
4. Creates `resolved_positions` records
5. Sends Telegram notifications to users

## Architecture

```
Railway Cron (every hour)
    ↓
DB Query: Find users with positions in resolved markets
    ↓
For each (user, market): Call /closed-positions API
    ↓
Insert resolved_positions record
    ↓
Send Telegram notification
```

## Environment Variables

Required:
- `DATABASE_URL` - Supabase PostgreSQL connection string
- `TELEGRAM_BOT_TOKEN` - Telegram bot token from BotFather

Optional:
- `LOOKBACK_HOURS` - How far back to check for resolved markets (default: 2)
- `MAX_API_CALLS_PER_CYCLE` - Max API calls per cycle (default: 200)
- `DRY_RUN` - If true, logs actions without DB inserts/notifications (default: false)

## Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://..."
export TELEGRAM_BOT_TOKEN="..."
export DRY_RUN="true"

# Run worker
python main.py
```

## Railway Deployment

### Option 1: Manual Cron (Recommended)

1. Create new Railway service
2. Link to this directory: `apps/resolution-worker`
3. Add environment variables
4. Set up Railway Cron:
   - Schedule: `0 * * * *` (every hour)
   - Command: `python main.py`

### Option 2: Always-On Service with Internal Scheduler

```python
# Add to main.py:
while True:
    await worker.run()
    await asyncio.sleep(3600)  # 1 hour
```

Deploy as regular service (costs ~$5/month vs ~$0.50/month for cron).

## Monitoring

Worker logs key metrics after each cycle:

```
✅ Cycle complete in 125.3s
📈 Stats: {
  'markets_found': 15,
  'user_market_pairs': 47,
  'positions_created': 45,
  'notifications_sent': 45,
  'api_errors': 2,
  'no_position_found': 2
}
```

### Success Criteria
- API errors < 5%
- Cycle completes in < 5 minutes
- All users receive notifications within 1 hour

### Alerts
Watch for:
- API errors > 10%
- Cycle duration > 10 minutes
- Zero markets processed for 3+ consecutive cycles

## Database Indexes

For optimal performance, add these indexes to Supabase:

```sql
-- Speed up main query
CREATE INDEX IF NOT EXISTS idx_markets_resolution
ON subsquid_markets_poll(resolution_status, resolution_date DESC)
WHERE resolution_status = 'RESOLVED';

-- Speed up duplicate check
CREATE INDEX IF NOT EXISTS idx_resolved_positions_lookup
ON resolved_positions(user_id, market_id);

-- Speed up user transactions join
CREATE INDEX IF NOT EXISTS idx_user_transactions_market
ON subsquid_user_transactions_v2(market_id, user_address);
```

## Edge Cases Handled

- **User has no closed position**: Skipped silently (may have sold already)
- **API rate limit (429)**: 5s backoff, continues to next user
- **API timeout**: Logged, continues to next user
- **Telegram notification fails**: Logged as warning, doesn't block other users
- **Market resolved twice**: `NOT EXISTS` prevents duplicate records
- **Worker crashes mid-cycle**: Next cycle picks up remaining (2h lookback)

## Cost Estimate

**Railway Cron (recommended):**
- Runs: 1-2 min/hour = 24-48 min/day
- Cost: ~$0.50/month

**Always-on service:**
- Runs: 24/7
- Cost: ~$5/month

## Future Enhancements

- Add health check endpoint
- Webhook trigger for immediate processing
- Dashboard for monitoring stats
- Auto-redemption via CTF Exchange contract
