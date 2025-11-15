#!/usr/bin/env python3
"""
Emergency Bot Recovery Script
Diagnoses and fixes silent crash issues after git revert
"""

import os
import sys
import redis
import asyncio
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def check_redis_lock():
    """Check if Redis lock is blocking the bot"""
    print("\n" + "="*60)
    print("🔍 CHECKING REDIS LOCK")
    print("="*60)

    try:
        # Try to connect to Redis
        redis_url = os.getenv('REDIS_URL')
        if not redis_url:
            print("⚠️  REDIS_URL not set - checking fallback...")
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            redis_password = os.getenv('REDIS_PASSWORD')

            r = redis.Redis(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)
        else:
            r = redis.from_url(redis_url, decode_responses=True)

        # Test connection
        r.ping()
        print("✅ Redis connection: OK")

        # Check the lock
        lock_key = "telegram_bot_instance_lock"
        existing_lock = r.get(lock_key)

        if not existing_lock:
            print("✅ No lock found - bot should be able to start")
            return True, r

        print(f"🔒 LOCK FOUND: {existing_lock}")

        # Check TTL
        ttl = r.ttl(lock_key)
        if ttl == -1:
            print("⚠️  Lock has NO EXPIRATION - this is a problem!")
        elif ttl == -2:
            print("⚠️  Lock doesn't exist (race condition?)")
        else:
            print(f"⏰ Lock expires in: {ttl} seconds")

        # Analyze lock
        if existing_lock.startswith("instance_"):
            parts = existing_lock.split("_")
            if len(parts) >= 3:
                pid = parts[1]
                timestamp = "_".join(parts[2:])
                print(f"   PID: {pid}")
                print(f"   Timestamp: {timestamp}")

        print("\n🚨 THIS LOCK IS PREVENTING THE BOT FROM STARTING!")
        return False, r

    except redis.ConnectionError as e:
        print(f"❌ Cannot connect to Redis: {e}")
        print("   Bot cannot use Redis lock - may cause conflicts")
        return None, None
    except Exception as e:
        print(f"❌ Error checking Redis: {e}")
        return None, None

def force_clear_lock(redis_client):
    """Force clear the Redis lock"""
    print("\n" + "="*60)
    print("🗑️  CLEARING REDIS LOCK")
    print("="*60)

    try:
        lock_key = "telegram_bot_instance_lock"
        result = redis_client.delete(lock_key)

        if result:
            print("✅ Lock cleared successfully!")
            print("🚀 Bot should now be able to start")
            return True
        else:
            print("⚠️  Lock was already gone")
            return True
    except Exception as e:
        print(f"❌ Error clearing lock: {e}")
        return False

def check_railway_services():
    """Check if multiple Railway services are running"""
    print("\n" + "="*60)
    print("🚂 CHECKING RAILWAY SERVICES")
    print("="*60)

    is_railway = os.getenv('RAILWAY_ENVIRONMENT') or os.getenv('RAILWAY_PROJECT_ID')

    if not is_railway:
        print("⚠️  Not running on Railway - skipping")
        return

    print(f"✅ Railway environment detected: {os.getenv('RAILWAY_ENVIRONMENT', 'unknown')}")
    print(f"   Project ID: {os.getenv('RAILWAY_PROJECT_ID', 'unknown')}")
    print(f"   Service ID: {os.getenv('RAILWAY_SERVICE_ID', 'unknown')}")

    print("\n💡 To check all running services:")
    print("   railway service list")
    print("   railway ps")

def check_telegram_api():
    """Test Telegram API connectivity"""
    print("\n" + "="*60)
    print("📱 CHECKING TELEGRAM API")
    print("="*60)

    try:
        bot_token = os.getenv('TELEGRAM_BOT') or os.getenv('BOT_TOKEN')
        if not bot_token:
            print("❌ No bot token found!")
            return False

        print(f"✅ Bot token found: {bot_token[:10]}...{bot_token[-5:]}")

        # Try to make a simple API call
        import requests
        response = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5)

        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                bot_info = data.get('result', {})
                print(f"✅ Telegram API: OK")
                print(f"   Bot username: @{bot_info.get('username')}")
                print(f"   Bot ID: {bot_info.get('id')}")
                return True
            else:
                print(f"❌ Telegram API error: {data}")
                return False
        else:
            print(f"❌ Telegram API HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Error checking Telegram API: {e}")
        return False

async def check_database():
    """Check database connectivity"""
    print("\n" + "="*60)
    print("🗄️  CHECKING DATABASE")
    print("="*60)

    try:
        from database import db_manager, engine
        from sqlalchemy import text

        # Try to connect
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Database connection: OK")

            # Check critical tables
            from sqlalchemy import inspect
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            critical_tables = [
                'users',
                'markets',
                'user_positions',
                'smart_wallets'
            ]

            missing = []
            for table in critical_tables:
                if table in tables:
                    print(f"   ✅ {table}")
                else:
                    print(f"   ❌ {table} - MISSING!")
                    missing.append(table)

            if missing:
                print(f"\n⚠️  Missing tables: {missing}")
                print("   Run migrations to fix this")
                return False

            return True

    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

def main():
    """Run all diagnostics and propose fixes"""
    print("\n" + "="*80)
    print("🚨 EMERGENCY BOT RECOVERY DIAGNOSTIC")
    print("="*80)
    print("This script diagnoses why the bot is not starting after git revert")
    print("="*80)

    # Step 1: Check Redis lock (most likely culprit)
    lock_status, redis_client = check_redis_lock()

    # Step 2: Check Railway services
    check_railway_services()

    # Step 3: Check Telegram API
    telegram_ok = check_telegram_api()

    # Step 4: Check Database
    try:
        db_ok = asyncio.run(check_database())
    except Exception as e:
        print(f"❌ Could not check database: {e}")
        db_ok = False

    # Summary and recommendations
    print("\n" + "="*80)
    print("📊 DIAGNOSTIC SUMMARY")
    print("="*80)

    issues = []
    fixes = []

    if lock_status is False:
        issues.append("🔒 Redis lock is BLOCKING the bot from starting")
        fixes.append("Clear the Redis lock (option below)")

    if not telegram_ok:
        issues.append("📱 Telegram API connectivity issue")
        fixes.append("Check bot token in environment variables")

    if not db_ok:
        issues.append("🗄️  Database issue detected")
        fixes.append("Run migrations or check DATABASE_URL")

    if issues:
        print("\n⚠️  ISSUES DETECTED:")
        for issue in issues:
            print(f"   {issue}")

        print("\n🔧 RECOMMENDED FIXES:")
        for i, fix in enumerate(fixes, 1):
            print(f"   {i}. {fix}")
    else:
        print("\n✅ No obvious issues detected")
        print("   The bot should be able to start")

    # Offer to clear the lock
    if lock_status is False and redis_client:
        print("\n" + "="*80)
        print("💡 AUTOMATIC FIX AVAILABLE")
        print("="*80)
        response = input("Do you want to clear the Redis lock now? (yes/no): ").strip().lower()

        if response in ['yes', 'y']:
            if force_clear_lock(redis_client):
                print("\n✅ Lock cleared! Try restarting the bot now:")
                print("   railway up (if on Railway)")
                print("   or restart your local server")
            else:
                print("\n❌ Could not clear lock automatically")
                print("   Manual intervention required")
        else:
            print("\n⚠️  Lock not cleared. To clear manually:")
            print("   redis-cli DEL telegram_bot_instance_lock")
            print("   or use Railway Redis CLI")

    print("\n" + "="*80)
    print("🔍 ADDITIONAL DEBUGGING STEPS")
    print("="*80)
    print("1. Check Railway logs:")
    print("   railway logs --tail 100")
    print("\n2. Check for multiple deployments:")
    print("   railway service list")
    print("   railway ps")
    print("\n3. Force redeploy:")
    print("   railway up --force")
    print("\n4. Check environment variables:")
    print("   railway variables")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
