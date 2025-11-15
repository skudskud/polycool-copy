#!/usr/bin/env python3
"""
Diagnose Redis lock for Telegram bot instances
"""
import redis
import os
from datetime import datetime

def diagnose_redis_lock():
    """Diagnose the current state of Redis and the bot instance lock"""

    print("🔍 Diagnosing Redis lock for Telegram bot instances...")
    print("=" * 60)

    # Check environment variables
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    redis_password = os.getenv('REDIS_PASSWORD')

    print(f"Redis config:")
    print(f"  Host: {redis_host}")
    print(f"  Port: {redis_port}")
    print(f"  Password: {'Set' if redis_password else 'Not set'}")
    print()

    try:
        # Test Redis connection
        r = redis.Redis(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)
        r.ping()
        print("✅ Redis connection: SUCCESS")

        # Check the lock
        lock_key = "telegram_bot_instance_lock"
        existing_lock = r.get(lock_key)

        if existing_lock:
            print(f"🔒 Lock exists: {existing_lock}")

            # Parse lock value
            try:
                lock_parts = existing_lock.split('_')
                if len(lock_parts) >= 3:
                    pid = lock_parts[1]
                    timestamp_str = '_'.join(lock_parts[2:])
                    print(f"  Process ID: {pid}")
                    print(f"  Timestamp: {timestamp_str}")

                    # Check if process is still running
                    import psutil
                    try:
                        if psutil.pid_exists(int(pid)):
                            print(f"  Status: 🟢 Process {pid} is still running")
                        else:
                            print(f"  Status: 🔴 Process {pid} is dead - lock is stale")
                            print("  Recommendation: Clear the stale lock")
                    except Exception as e:
                        print(f"  Status: ❓ Cannot check process status: {e}")
                else:
                    print("  Lock format seems corrupted")

            except Exception as e:
                print(f"  Error parsing lock: {e}")

        else:
            print("🔓 No lock exists - safe to start bot")

        print()
        print("Available actions:")
        if existing_lock:
            print("  - Kill existing process and clear lock")
            print("  - Wait for existing process to finish")
            print("  - Force clear lock (dangerous if process still runs)")
        print("  - Check if Redis is accessible from production")

    except redis.ConnectionError as e:
        print(f"❌ Redis connection: FAILED")
        print(f"  Error: {e}")
        print()
        print("🔧 Solutions:")
        print("  1. Check if Redis is running")
        print("  2. Verify REDIS_HOST, REDIS_PORT, REDIS_PASSWORD env vars")
        print("  3. Check network connectivity")
        print("  4. Without Redis, bot cannot prevent multiple instances")

    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    diagnose_redis_lock()
