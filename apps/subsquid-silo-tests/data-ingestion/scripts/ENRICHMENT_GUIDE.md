# Market Enrichment Guide

## Overview
The market enrichment script (`enrich_markets_events.py`) is a **one-time initialization** tool that:
- Fetches complete market details from Gamma API for **ACTIVE markets only**
- Enriches markets with `events`, `category`, `description`, and more
- Populates missing fields in `subsquid_markets_poll` table

## Why?
The bulk API endpoint (`/markets?limit=200&offset=...`) doesn't return the `events` array or other detailed fields. By fetching individual market details via `/markets/{market_id}`, we get the complete data including event groupings.

## Scope
- ✅ Enriches: ~12-13k **ACTIVE** markets
- ⏭️ Skips: Closed/expired markets
- 📊 Data source: Gamma API `/markets/{market_id}` endpoint

## When to Run?
- **Before deploying the poller** - Do this once to backfill all existing markets
- Run it during initial setup
- No need to run again (the poller maintains updates)

## How to Run?

### Via Docker (Production)
```bash
cd /path/to/project/apps/subsquid-silo-tests/data-ingestion
python -m scripts.enrich_markets_events
```

### Locally (Development)
```bash
# Navigate to the project
cd /Users/ulyssepiediscalzi/Documents/polycool_last2/py-clob-client-with-bots/apps/subsquid-silo-tests/data-ingestion

# Make sure Python environment is set up
python -m scripts.enrich_markets_events
```

### Complete Command
```bash
cd /Users/ulyssepiediscalzi/Documents/polycool_last2/py-clob-client-with-bots/apps/subsquid-silo-tests/data-ingestion && python -m scripts.enrich_markets_events
```

## What Gets Enriched?

For each active market without events, the script fetches from Gamma API:

| Field | Source | Purpose |
|-------|--------|---------|
| `events` | `/markets/{id}` | Event groupings (e.g., "Super Bowl 2026") |
| `category` | `/markets/{id}` | Market category |
| `description` | `/markets/{id}` | Detailed description |
| `outcomes` | `/markets/{id}` | Updated outcome names |
| `outcome_prices` | `/markets/{id}` | Real-time prices |
| `last_mid` | Calculated | Mid-price from outcomes |

## Performance Notes

- **Scope**: ~12-13k active markets
- **Batch processing**: Updates every 100 markets to avoid DB locking
- **Rate limiting**: Respects Gamma API rate limits (429 responses)
- **Timeout handling**: 10s per market fetch (async)
- **Progress tracking**: Logs every 100 markets processed
- **Estimated time**: ~2-3 hours for 13k markets (API rate limited)

## Expected Output

```
================================================================================
🚀 MARKET ENRICHMENT SERVICE
Fetching full market details from Gamma API...
================================================================================

📊 Starting market enrichment from Gamma API...
📋 Found 13450 markets to enrich
⏳ Processed 100/13450 markets...
⏳ Processed 200/13450 markets...
✅ Upserted 100 markets to DB
...
================================================================================
✅ ENRICHMENT COMPLETE
   Enriched:    13450
   Failed:      0
   Skipped:     0
================================================================================
```

## Monitoring

While running, check logs:
```bash
# In another terminal
tail -f logs/enrichment.log
```

Or query database progress:
```sql
SELECT
  COUNT(*) as total_active,
  COUNT(*) FILTER (WHERE events IS NOT NULL AND jsonb_array_length(events) > 0) as enriched,
  COUNT(*) FILTER (WHERE events IS NULL OR jsonb_array_length(events) = 0) as remaining
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';
```

## Integration with Poller

After enrichment completes:
1. Deploy the regular poller (`PollerService`)
2. Poller will maintain prices, volume, and status
3. **Events data remains unchanged** (no need to re-fetch)
4. Significant bandwidth savings vs. fetching each market every cycle

## Troubleshooting

### "No markets found needing enrichment"
- All active markets already have events - this is normal!
- Query: `SELECT COUNT(*) FROM subsquid_markets_poll WHERE status = 'ACTIVE' AND events IS NULL`

### High failure rate?
- Check Gamma API rate limiting (look for 429 responses)
- API may be under heavy load - script will retry
- Check `logs/enrichment.log` for details

### Database locks?
- Reduce batch size from 100 to 50 in the script
- Run during off-peak hours
