#!/bin/bash
# Emergency Railway Bot Fix Script
# Diagnoses and fixes silent crash issues

echo "================================================================================"
echo "🚨 RAILWAY BOT EMERGENCY DIAGNOSTIC"
echo "================================================================================"
echo ""

# Check if Railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI not found!"
    echo "   Install: curl -fsSL https://railway.app/install.sh | sh"
    exit 1
fi

echo "✅ Railway CLI found"
echo ""

# Step 1: Check Railway status
echo "================================================================================"
echo "📊 CHECKING RAILWAY STATUS"
echo "================================================================================"
railway status
echo ""

# Step 2: List all services
echo "================================================================================"
echo "🚂 RAILWAY SERVICES"
echo "================================================================================"
railway service list
echo ""

# Step 3: Check environment variables
echo "================================================================================"
echo "🔐 CRITICAL ENVIRONMENT VARIABLES"
echo "================================================================================"
echo "Checking bot service variables..."
railway variables | grep -E "BOT_TOKEN|DATABASE_URL|REDIS_URL|USE_SUBSQUID|POLLER_ENABLED|STREAMER_ENABLED"
echo ""

# Step 4: Check recent logs
echo "================================================================================"
echo "📋 RECENT LOGS (Last 50 lines)"
echo "================================================================================"
railway logs --tail 50
echo ""

# Step 5: Check for errors in logs
echo "================================================================================"
echo "❌ ERROR ANALYSIS"
echo "================================================================================"
echo "Searching for critical errors..."
railway logs --tail 200 | grep -i "error\|exception\|crash\|conflict\|lock" | head -20
echo ""

# Step 6: Recommendations
echo "================================================================================"
echo "💡 RECOMMENDATIONS"
echo "================================================================================"
echo "1. If you see 'Conflict: terminated by other getUpdates':"
echo "   → Multiple bot instances are running"
echo "   → Run: railway ps"
echo "   → Check for duplicate deployments"
echo ""
echo "2. If you see 'table does not exist' or 'relation does not exist':"
echo "   → Database migrations missing"
echo "   → Run: railway run python run_migration_public.sh"
echo ""
echo "3. If you see 'Redis lock' or 'lock conflict':"
echo "   → Redis lock is blocking startup"
echo "   → Connect to Redis and delete: telegram_bot_instance_lock"
echo ""
echo "4. If bot is completely silent (no logs):"
echo "   → Service might be paused"
echo "   → Check: railway service"
echo "   → Force restart: railway up --force"
echo ""
echo "================================================================================"
echo "🔧 QUICK FIXES"
echo "================================================================================"
echo "A. Force clear Redis lock:"
echo "   railway connect redis"
echo "   > DEL telegram_bot_instance_lock"
echo "   > QUIT"
echo ""
echo "B. Force redeploy:"
echo "   railway up --force"
echo ""
echo "C. Check database tables:"
echo "   railway connect postgres"
echo "   > \\dt"
echo "   > SELECT COUNT(*) FROM markets;"
echo ""
echo "D. View live logs:"
echo "   railway logs --follow"
echo ""
echo "================================================================================"
