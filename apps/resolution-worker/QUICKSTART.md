# Quick Start Guide

## 1. Verify Data Availability

Before deploying, check if there are resolved markets to process:

```bash
export DATABASE_URL="postgresql://..."
python check_resolved_markets.py
```

Expected output:
```
📊 Markets resolved in last 24 hours: 15
📊 Total resolved markets: 674
👥 Users with positions in recently resolved markets: 47
✅ System ready! There are markets to process.
```

## 2. Test Locally (Dry Run)

```bash
# Set environment variables
export DATABASE_URL="postgresql://..."
export TELEGRAM_BOT_TOKEN="..."

# Run test script
./test_dry_run.sh
```

This will:
- Query database for resolved markets
- Call Polymarket API
- Log what it would do
- NOT insert records or send notifications

## 3. Deploy to Railway

```bash
# Login to Railway
railway login

# Link to project (or create new one)
railway init

# Set environment variables in Railway dashboard:
# - DATABASE_URL
# - TELEGRAM_BOT_TOKEN
# - LOOKBACK_HOURS=2
# - MAX_API_CALLS_PER_CYCLE=200

# Deploy
railway up

# Set up cron (in Railway dashboard):
# Schedule: 0 * * * *  (every hour)
# Command: python main.py
```

## 4. Monitor First Run

```bash
railway logs --follow
```

Expected output:
```
🚀 Starting resolution worker cycle
📊 Found 3 resolved markets with 12 user-market pairs to process
✅ Processed user 12345... market 660159...: PnL $55.23
📨 Sent notification to user 12345
✅ Cycle complete in 45.2s
```

## 5. Verify Success

Check database:

```sql
SELECT COUNT(*) FROM resolved_positions WHERE created_at > NOW() - INTERVAL '1 hour';
```

Check Telegram:
- Users should receive notifications like:
  ```
  🎉 Market Resolved!

  📊 Vikings vs. Lions: 1H O/U 25.5

  ✅ Outcome: Yes
  💰 You WON: $55.23

  🎁 Profit: +$55.23
  💵 Position auto-closed

  📈 View history: /positions
  ```

## Troubleshooting

### No markets found

- Increase `LOOKBACK_HOURS` to 24 for testing
- Check Poller is running and updating `resolution_status`

### API errors

- Verify Polymarket API is accessible
- Check rate limiting settings

### Database errors

- Verify DATABASE_URL is correct
- Check indexes are created (see DEPLOYMENT.md)

## Next Steps

After successful deployment:

1. **Monitor for 24 hours** to ensure stability
2. **Remove API limits** if all is working (`MAX_API_CALLS_PER_CYCLE=200`)
3. **Set up alerts** in Railway for crashes/errors
4. **Schedule regular checks** of resolved_positions table

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `LOOKBACK_HOURS` | 2 | How far back to check for resolved markets |
| `MAX_API_CALLS_PER_CYCLE` | 200 | Max API calls per hour |
| `DRY_RUN` | false | If true, logs only (no DB writes) |

## Cost

- **Cron job**: ~$0.50/month (2 min execution/hour)
- **Always-on**: ~$5/month (24/7 service)

Railway bills by execution time, so cron is much cheaper for this use case.
