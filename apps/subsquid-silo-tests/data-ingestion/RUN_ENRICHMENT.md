# Full Market Enrichment - Restore Events Data

## What This Does

Fetches ALL events from Gamma API (~900k events) and restores `events` data for all markets in the database. This fixes the parent/children grouping in the Telegram bot.

## When to Run

Run this enrichment when:
- Markets are showing as individual instead of grouped
- High-volume markets are missing event data
- After major Poller changes that might have corrupted events data

## How to Run (Railway - RECOMMENDED)

### Option 1: Via Railway CLI (Best - Uses Railway Environment)

```bash
# Navigate to data-ingestion directory
cd apps/subsquid-silo-tests/data-ingestion

# Run enrichment on Railway (uses Railway's DATABASE_URL automatically)
railway run python -m scripts.enrich_markets_events
```

### Option 2: Deploy as One-Time Service

Create a new Railway service with this configuration:
- **Start Command:** `python -m scripts.enrich_markets_events`
- **Restart Policy:** NEVER (one-time job)
- **Root Directory:** `/apps/subsquid-silo-tests/data-ingestion`

After completion, delete the service.

## Expected Timeline

- **Total events:** ~900,000
- **Fetch rate:** ~200 events/sec with rate limiting
- **Batch updates:** Every 500 markets
- **Total time:** 90-120 minutes

## Progress Monitoring

The script logs:
```
📋 Fetched 200 events (offset=0)
✅ Upserted 500 markets to DB
...
✅ ENRICHMENT COMPLETE
   Events Fetched:  900000
   Markets Enriched: 13500
```

## What Gets Fixed

**Before Enrichment:**
- Markets missing events: ~1,800 (13%)
- High-volume grouping: 5.6%
- Individual markets shown instead of groups

**After Enrichment:**
- Markets with events: ~13,800 (99%+)
- High-volume grouping: 95%+
- Proper parent/children grouping everywhere

## Important Notes

1. **Run ONCE** - The Poller will maintain events data after enrichment
2. **Safe to run multiple times** - Upserts are idempotent
3. **Doesn't affect live bot** - Only updates database, no downtime
4. **Preserves all data** - Only updates the `events` field

## Verification

After enrichment completes, check database:

```sql
SELECT 
    COUNT(*) as total_active,
    COUNT(*) FILTER (WHERE events IS NOT NULL AND jsonb_array_length(events) > 0) as with_events,
    ROUND(100.0 * COUNT(*) FILTER (WHERE events IS NOT NULL AND jsonb_array_length(events) > 0) / COUNT(*), 1) as percent
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';
```

Should show 99%+ with events!


