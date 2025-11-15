# Deployment Guide - Resolution Worker

## Railway Deployment (Recommended)

### Step 1: Create New Railway Service

```bash
cd apps/resolution-worker
railway login
railway init
```

Select:
- Create new project: "resolution-worker"
- Environment: "production"

### Step 2: Configure Environment Variables

In Railway dashboard, add these variables:

```
DATABASE_URL=postgresql://postgres.fkksycggxaaohlfdwfle:[PASSWORD]@aws-0-us-east-1.pooler.supabase.com:6543/postgres
TELEGRAM_BOT_TOKEN=<your_bot_token>
LOOKBACK_HOURS=2
MAX_API_CALLS_PER_CYCLE=200
DRY_RUN=false
```

**Get DATABASE_URL from Supabase:**
1. Go to Supabase Dashboard → Project Settings → Database
2. Copy "Connection string" (Transaction mode for long-running queries)
3. Replace `[YOUR-PASSWORD]` with your database password

**Get TELEGRAM_BOT_TOKEN:**
- Same token used by your main telegram bot

### Step 3: Set Up Cron Schedule

Railway supports cron jobs natively. Configure in `railway.json`:

```json
{
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python main.py"
  }
}
```

Then configure cron in Railway dashboard:
- Go to Service Settings → Cron
- Schedule: `0 * * * *` (every hour at :00)
- Command: `python main.py`

**OR** use Railway CLI:

```bash
railway run --cron "0 * * * *" python main.py
```

### Step 4: Deploy

```bash
railway up
```

### Step 5: Monitor First Run

```bash
railway logs
```

Expected output:
```
🚀 Starting resolution worker cycle
⚙️ Config: LOOKBACK_HOURS=2, MAX_API_CALLS=200, DRY_RUN=false
📊 Found 3 resolved markets with 12 user-market pairs to process
✅ Processed user 12345678... market 660159...: PnL $55.23
📨 Sent notification to user 12345678
✅ Cycle complete in 45.2s
📈 Stats: {'markets_found': 3, 'positions_created': 12, ...}
```

## Testing Before Full Deployment

### Phase 1: Dry Run (24h lookback)

```bash
# Set in Railway dashboard
DRY_RUN=true
LOOKBACK_HOURS=24
MAX_API_CALLS_PER_CYCLE=10

# Deploy and check logs
railway logs --follow
```

Verify:
- Query finds correct markets
- API calls succeed
- No errors in logs

### Phase 2: Small Scale Production

```bash
# Update variables
DRY_RUN=false
LOOKBACK_HOURS=2
MAX_API_CALLS_PER_CYCLE=10  # Only process first 10 users

# Monitor for 24 hours
railway logs --follow
```

Verify:
- Users receive notifications
- No duplicate records
- P&L values are correct

### Phase 3: Full Production

```bash
# Remove limits
MAX_API_CALLS_PER_CYCLE=200
```

## Alternative: Always-On Service

If you prefer a service that runs 24/7 with internal scheduling:

1. Modify `main.py` to add a loop:

```python
if __name__ == "__main__":
    while True:
        asyncio.run(main())
        time.sleep(3600)  # 1 hour
```

2. Deploy as regular service (no cron)

**Cost comparison:**
- Cron: ~$0.50/month (2 min/hour)
- Always-on: ~$5/month (24/7)

## Monitoring

### Key Metrics

Monitor these in Railway logs:

```
✅ markets_found: 15          # Should be > 0 occasionally
✅ positions_created: 45      # Should match user_market_pairs (minus duplicates)
✅ notifications_sent: 45     # Should match positions_created
⚠️ api_errors: 2             # Should be < 5%
⏱️ cycle_duration: 125.3s    # Should be < 300s (5 min)
```

### Alerts

Set up Railway notifications for:
- Service crashes
- High error rate
- Long execution time

## Rollback Plan

If issues occur:

1. **Pause service**
   ```bash
   railway service pause
   ```

2. **Check logs**
   ```bash
   railway logs --tail 100
   ```

3. **Fix and redeploy**
   - No data corruption (only inserts, no updates)
   - Idempotent (safe to re-run)
   - Next cycle will catch missed markets

## Cost Estimate

**Cron-based (recommended):**
- Execution: ~2 min/hour = 48 min/day
- Cost: $0.50/month

**Always-on service:**
- Running: 24/7
- Cost: $5/month

## Troubleshooting

### No markets found

Check:
```sql
SELECT COUNT(*)
FROM subsquid_markets_poll
WHERE resolution_status = 'RESOLVED'
  AND resolution_date > NOW() - INTERVAL '2 hours';
```

If 0, increase `LOOKBACK_HOURS` or wait for markets to resolve.

### API errors

- Check Polymarket API status
- Verify rate limiting (200ms delay between calls)
- Check if MAX_API_CALLS_PER_CYCLE is too high

### Telegram notifications not sent

- Verify TELEGRAM_BOT_TOKEN is correct
- Check bot has permission to message users
- Verify users have started the bot (`/start`)

### Database connection errors

- Verify DATABASE_URL is correct
- Check Supabase connection pooling settings
- Ensure IP whitelisting if enabled
