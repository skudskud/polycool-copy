#!/usr/bin/env python3
"""
Fix Telegram bot instance conflicts
"""
import redis
import os
from datetime import datetime

def force_clear_lock():
    """Force clear the Redis lock - USE WITH CAUTION"""

    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    redis_password = os.getenv('REDIS_PASSWORD')

    try:
        r = redis.Redis(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)
        r.ping()

        lock_key = "telegram_bot_instance_lock"
        existing_lock = r.get(lock_key)

        if existing_lock:
            print(f"🔒 Found existing lock: {existing_lock}")
            print("🗑️ Clearing lock...")

            r.delete(lock_key)
            print("✅ Lock cleared successfully")
            print("🚀 You can now restart the bot safely")
        else:
            print("🔓 No lock found - already clear")

    except Exception as e:
        print(f"❌ Error clearing lock: {e}")

def check_railway_processes():
    """Check Railway processes (if Railway CLI is available)"""

    print("🔍 Checking Railway processes...")
    print("Note: This requires Railway CLI to be installed and authenticated")
    print()
    print("Run these commands manually:")
    print("1. railway status")
    print("2. railway logs --service telegram-bot")
    print("3. railway ps")
    print()
    print("If you see multiple instances:")
    print("1. railway stop --service telegram-bot")
    print("2. Wait 30 seconds")
    print("3. railway up --service telegram-bot")

if __name__ == "__main__":
    print("🛠️ Telegram Bot Conflict Resolution Tool")
    print("=" * 50)
    print()

    print("Option 1: Force clear Redis lock (RISKY)")
    response = input("Do you want to force clear the Redis lock? (y/N): ").strip().lower()

    if response == 'y':
        force_clear_lock()
    else:
        print("Lock not cleared")

    print()
    print("Option 2: Check Railway processes")
    check_railway_processes()
