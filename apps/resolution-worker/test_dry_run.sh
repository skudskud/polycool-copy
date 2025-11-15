#!/bin/bash
# Test script for resolution worker in DRY RUN mode
# This will query the database and log what it would do, without making any changes

set -e

echo "🧪 Testing Resolution Worker (DRY RUN mode)"
echo "============================================"
echo ""

# Check if environment variables are set
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL environment variable not set"
    echo "Please set it with: export DATABASE_URL='postgresql://...'"
    exit 1
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ ERROR: TELEGRAM_BOT_TOKEN environment variable not set"
    echo "Please set it with: export TELEGRAM_BOT_TOKEN='...'"
    exit 1
fi

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
else
    source venv/bin/activate
fi

# Run in dry-run mode
echo "🚀 Running worker in DRY RUN mode..."
echo "   (This will NOT insert records or send notifications)"
echo ""

export DRY_RUN="true"
export LOOKBACK_HOURS="${LOOKBACK_HOURS:-24}"  # Default to 24h for testing
export MAX_API_CALLS_PER_CYCLE="${MAX_API_CALLS_PER_CYCLE:-10}"  # Limit for testing

python main.py

echo ""
echo "✅ Test complete!"
