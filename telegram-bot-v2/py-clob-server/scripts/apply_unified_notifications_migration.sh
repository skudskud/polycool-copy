#!/bin/bash
# Apply unified notifications migration to Railway EU database
# Run this with: bash telegram-bot-v2/py-clob-server/scripts/apply_unified_notifications_migration.sh

set -e

echo "🚀 Applying Unified Smart Trading Notifications Migration..."
echo ""

# Get Railway database URL for EU project
echo "📡 Connecting to Railway EU database..."

# Apply migration SQL
railway run --service telegram-poller psql -c "
-- Add condition_id column
ALTER TABLE smart_wallet_trades 
ADD COLUMN IF NOT EXISTS condition_id TEXT;
"

echo "✅ Column added"

# Backfill in batches (to avoid timeout)
echo "📊 Backfilling condition_id (this may take a minute)..."

railway run --service telegram-poller psql -c "
-- Backfill condition_id from tracked_leader_trades
UPDATE smart_wallet_trades swt
SET condition_id = tlt.market_id
FROM tracked_leader_trades tlt
WHERE swt.id = tlt.tx_id
  AND swt.condition_id IS NULL
  AND tlt.market_id IS NOT NULL
  AND swt.created_at >= NOW() - INTERVAL '7 days';
"

echo "✅ Recent trades backfilled (last 7 days)"

# Add index
echo "🔍 Creating index..."

railway run --service telegram-poller psql -c "
CREATE INDEX IF NOT EXISTS idx_smart_wallet_trades_condition_id 
ON smart_wallet_trades(condition_id);
"

echo "✅ Index created"

# Update view to 5-min window
echo "📋 Updating alert_bot_pending_trades view to 5-min window..."

railway run --service telegram-poller psql -c "
CREATE OR REPLACE VIEW alert_bot_pending_trades AS
SELECT 
    swt.id,
    swt.wallet_address,
    sw.bucket_smart,
    sw.smartscore,
    sw.win_rate,
    swt.side,
    swt.outcome,
    swt.price,
    swt.size,
    swt.value,
    swt.market_id,
    swt.condition_id,
    swt.market_question,
    swt.timestamp,
    swt.is_first_time,
    swt.created_at
FROM smart_wallet_trades swt
INNER JOIN smart_wallets sw ON swt.wallet_address = sw.address
WHERE 
    swt.is_first_time = TRUE
    AND swt.value >= 400
    AND swt.timestamp >= NOW() - INTERVAL '5 minutes'
    AND sw.bucket_smart = 'Very Smart'
    AND swt.market_question IS NOT NULL
    AND swt.market_question != ''
    AND NOT (
        LOWER(swt.market_question) LIKE '%up or down%'
        OR LOWER(swt.market_question) LIKE '%higher or lower%'
        OR LOWER(swt.market_question) LIKE '%price of bitcoin%'
        OR LOWER(swt.market_question) LIKE '%price of ethereum%'
        OR LOWER(swt.market_question) LIKE '%next 15 minutes%'
        OR LOWER(swt.market_question) LIKE '%next 30 minutes%'
    )
    AND NOT EXISTS (
        SELECT 1 FROM alert_bot_sent abs 
        WHERE abs.trade_id = swt.id
    )
ORDER BY swt.timestamp DESC;
"

echo "✅ View updated"

# Verify
echo ""
echo "🔍 Verifying migration..."

railway run --service telegram-poller psql -c "
SELECT 
    COUNT(*) as total_trades,
    COUNT(condition_id) as with_condition_id,
    ROUND(100.0 * COUNT(condition_id) / NULLIF(COUNT(*), 0), 2) as coverage_pct
FROM smart_wallet_trades
WHERE created_at >= NOW() - INTERVAL '24 hours';
"

echo ""
echo "✅ Migration complete!"
echo ""
echo "Next steps:"
echo "  1. Deploy updated code to Railway"
echo "  2. Monitor logs for notification behavior"
echo "  3. Test Quick Buy buttons"

