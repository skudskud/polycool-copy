#!/bin/bash
# Railway Bot Cleanup Script
# Forces a clean restart and clears any blocking locks

set -e

echo "================================================================================"
echo "🧹 RAILWAY BOT CLEANUP SCRIPT"
echo "================================================================================"
echo ""

# Check if railway CLI is available
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI not found"
    echo "   Install: curl -fsSL https://railway.app/install.sh | sh"
    exit 1
fi

echo "✅ Railway CLI found"
echo ""

# Step 1: Clear Redis lock
echo "================================================================================"
echo "🔓 CLEARING REDIS LOCK"
echo "================================================================================"
echo ""
echo "Attempting to clear telegram_bot_instance_lock..."
echo ""

# Try to clear the lock via Railway
railway run bash -c 'python3 << EOF
import redis
import os

try:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        r = redis.from_url(redis_url, decode_responses=True)
        r.ping()
        result = r.delete("telegram_bot_instance_lock")
        if result:
            print("✅ Redis lock cleared successfully")
        else:
            print("ℹ️  No lock found (already clear)")
    else:
        print("⚠️  REDIS_URL not found")
except Exception as e:
    print(f"❌ Error: {e}")
EOF
' || echo "⚠️  Could not clear Redis lock automatically"

echo ""

# Step 2: Force redeploy
echo "================================================================================"
echo "🚀 FORCE REDEPLOYING BOT"
echo "================================================================================"
echo ""
echo "This will trigger a fresh deployment with the latest code..."
echo ""

read -p "Continue with force redeploy? (yes/no): " -r
echo ""

if [[ $REPLY =~ ^[Yy]es$ ]]; then
    railway up --force
    echo ""
    echo "✅ Deployment triggered"
    echo ""
    echo "Waiting 10 seconds for startup..."
    sleep 10
    echo ""

    # Step 3: Check logs
    echo "================================================================================"
    echo "📋 CHECKING DEPLOYMENT LOGS"
    echo "================================================================================"
    echo ""
    railway logs --tail 50
    echo ""

    echo "================================================================================"
    echo "✅ CLEANUP COMPLETE"
    echo "================================================================================"
    echo ""
    echo "Next steps:"
    echo "  1. Monitor logs: railway logs --follow"
    echo "  2. Check bot status in Telegram"
    echo "  3. If still issues, check: railway service list"
    echo ""
else
    echo "⚠️  Deployment cancelled"
    echo ""
    echo "To manually redeploy later:"
    echo "  railway up --force"
fi

echo "================================================================================"
