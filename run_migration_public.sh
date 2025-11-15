#!/bin/bash
set -e

echo "🚀 Running Migration via PUBLIC Railway Database..."
echo "📍 This uses mainline.proxy.rlwy.net:13288"
echo ""

# Use relative path so it works for any user
cd "$(dirname "$0")/telegram-bot-v2/py-clob-server"

# Get the public database URL from the py-clob-client service
# (it should have the public URL as DATABASE_URL)
railway link

# Now run migration using the service's DATABASE_URL
PGPASSWORD=$(railway run -s py-clob-client-with-bots bash -c 'echo $DATABASE_URL' | grep -o "://[^:]*:\([^@]*\)" | cut -d: -f3) \
  psql -h mainline.proxy.rlwy.net -p 13288 -U postgres -d railway \
  -f migrations/2025-10-06_market_grouping_enhancement/add_market_metadata_clean.sql

echo ""
echo "✅ Migration Complete! Check Railway logs for confirmation."
