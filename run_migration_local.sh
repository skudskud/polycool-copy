#!/bin/bash
set -e

echo "🚀 Running Migration via Railway..."

# Use relative path so it works for any user
cd "$(dirname "$0")/telegram-bot-v2/py-clob-server"

# Use Railway to get database URL and run migration
railway run bash << 'INNERSCRIPT'
cat migrations/2025-10-06_market_grouping_enhancement/add_market_metadata_clean.sql | psql "$DATABASE_URL"
echo "✅ Migration Complete!"
INNERSCRIPT
