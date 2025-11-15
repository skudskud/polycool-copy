#!/usr/bin/env python3
"""
Diagnostic script to check Poller and Streamer status
Verifies environment variables and service configurations
"""

import os
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_environment_variables():
    """Check critical environment variables"""
    print("\n" + "="*60)
    print("🔍 CHECKING ENVIRONMENT VARIABLES")
    print("="*60)

    critical_vars = [
        'DATABASE_URL',
        'REDIS_URL',
        'BOT_TOKEN',
        'TELEGRAM_BOT',
        'USE_SUBSQUID_MARKETS',
        'POLLER_ENABLED',
        'STREAMER_ENABLED',
        'EXPERIMENTAL_SUBSQUID',
    ]

    for var in critical_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if 'TOKEN' in var or 'SECRET' in var or 'PASSWORD' in var or 'KEY' in var:
                display_value = f"{value[:10]}...{value[-5:]}" if len(value) > 15 else "***"
            elif 'URL' in var and '@' in value:
                # Mask database URLs
                parts = value.split('@')
                if len(parts) == 2:
                    display_value = f"{parts[0].split('://')[0]}://***@{parts[1]}"
                else:
                    display_value = value
            else:
                display_value = value
            print(f"✅ {var}: {display_value}")
        else:
            print(f"⚠️  {var}: NOT SET")

    return True

def check_poller_config():
    """Check Poller service configuration"""
    print("\n" + "="*60)
    print("🔍 CHECKING POLLER CONFIGURATION")
    print("="*60)

    try:
        # Try to import poller config
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'apps' / 'subsquid-silo-tests' / 'src'))
        from config import settings

        print(f"✅ POLLER_ENABLED: {settings.POLLER_ENABLED}")
        print(f"✅ POLL_MS: {settings.POLL_MS}ms ({settings.POLL_MS/1000:.0f}s)")
        print(f"✅ GAMMA_API_URL: {settings.GAMMA_API_URL}")
        print(f"✅ EXPERIMENTAL_SUBSQUID: {settings.EXPERIMENTAL_SUBSQUID}")

        if settings.POLLER_ENABLED:
            print("\n⚠️  POLLER IS ENABLED")
            print(f"   - Polls every {settings.POLL_MS/1000:.0f} seconds")
            print(f"   - This could generate significant database load")
        else:
            print("\n✅ POLLER IS DISABLED")

        return settings.POLLER_ENABLED
    except ImportError as e:
        print(f"⚠️  Could not import poller config: {e}")
        print("   Poller service may not be available in this environment")
        return None
    except Exception as e:
        print(f"❌ Error checking poller config: {e}")
        return None

def check_streamer_config():
    """Check Streamer service configuration"""
    print("\n" + "="*60)
    print("🔍 CHECKING STREAMER CONFIGURATION")
    print("="*60)

    try:
        # Try to import streamer config
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'apps' / 'subsquid-silo-tests' / 'src'))
        from config import settings

        print(f"✅ STREAMER_ENABLED: {settings.STREAMER_ENABLED}")
        print(f"✅ CLOB_WSS_URL: {settings.CLOB_WSS_URL}")
        print(f"✅ WS_MAX_SUBSCRIPTIONS: {settings.WS_MAX_SUBSCRIPTIONS}")
        print(f"✅ WS_MESSAGE_TIMEOUT: {settings.WS_MESSAGE_TIMEOUT}s")
        print(f"✅ EXPERIMENTAL_SUBSQUID: {settings.EXPERIMENTAL_SUBSQUID}")

        if settings.STREAMER_ENABLED:
            print("\n⚠️  STREAMER IS ENABLED")
            print(f"   - WebSocket connection active")
            print(f"   - Max subscriptions: {settings.WS_MAX_SUBSCRIPTIONS}")
            print(f"   - This could generate significant database writes")
        else:
            print("\n✅ STREAMER IS DISABLED")

        return settings.STREAMER_ENABLED
    except ImportError as e:
        print(f"⚠️  Could not import streamer config: {e}")
        print("   Streamer service may not be available in this environment")
        return None
    except Exception as e:
        print(f"❌ Error checking streamer config: {e}")
        return None

def check_bot_config():
    """Check Telegram bot configuration"""
    print("\n" + "="*60)
    print("🔍 CHECKING TELEGRAM BOT CONFIGURATION")
    print("="*60)

    try:
        from config.config import USE_SUBSQUID_MARKETS, BOT_TOKEN

        print(f"✅ USE_SUBSQUID_MARKETS: {USE_SUBSQUID_MARKETS}")
        print(f"✅ BOT_TOKEN: {'SET' if BOT_TOKEN else 'NOT SET'}")

        if USE_SUBSQUID_MARKETS:
            print("\n⚠️  BOT USES SUBSQUID MARKETS")
            print("   - Relies on Poller/Streamer for market data")
            print("   - If Poller/Streamer are running separately, ensure they're not duplicating work")
        else:
            print("\n✅ BOT USES DIRECT API")
            print("   - Poller/Streamer should be disabled to avoid conflicts")

        return USE_SUBSQUID_MARKETS
    except Exception as e:
        print(f"❌ Error checking bot config: {e}")
        return None

def check_database_connection():
    """Check database connection"""
    print("\n" + "="*60)
    print("🔍 CHECKING DATABASE CONNECTION")
    print("="*60)

    try:
        from database import db_manager, engine

        # Try to connect
        with engine.connect() as conn:
            result = conn.execute("SELECT 1")
            print("✅ Database connection: OK")

            # Check for poller/streamer tables
            from sqlalchemy import inspect
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            poller_tables = [t for t in tables if 'subsquid' in t.lower() or 'poller' in t.lower()]
            streamer_tables = [t for t in tables if 'ws' in t.lower() or 'streamer' in t.lower()]

            if poller_tables:
                print(f"✅ Poller tables found: {len(poller_tables)}")
                for table in poller_tables[:5]:  # Show first 5
                    print(f"   - {table}")

            if streamer_tables:
                print(f"✅ Streamer tables found: {len(streamer_tables)}")
                for table in streamer_tables[:5]:  # Show first 5
                    print(f"   - {table}")

        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def main():
    """Run all checks"""
    print("\n" + "="*60)
    print("🚀 POLLER & STREAMER DIAGNOSTIC")
    print("="*60)

    # Check environment variables
    check_environment_variables()

    # Check configurations
    poller_enabled = check_poller_config()
    streamer_enabled = check_streamer_config()
    use_subsquid = check_bot_config()

    # Check database
    db_ok = check_database_connection()

    # Summary
    print("\n" + "="*60)
    print("📊 SUMMARY")
    print("="*60)

    issues = []
    if poller_enabled and not use_subsquid:
        issues.append("⚠️  POLLER enabled but bot doesn't use subsquid markets - potential conflict")

    if streamer_enabled and not use_subsquid:
        issues.append("⚠️  STREAMER enabled but bot doesn't use subsquid markets - potential conflict")

    if poller_enabled and streamer_enabled:
        issues.append("⚠️  Both POLLER and STREAMER enabled - ensure they're not competing")

    if not db_ok:
        issues.append("❌ Database connection failed - services cannot function")

    if issues:
        print("\n⚠️  POTENTIAL ISSUES:")
        for issue in issues:
            print(f"   {issue}")
    else:
        print("\n✅ No obvious configuration issues detected")

    print("\n" + "="*60)
    print("💡 RECOMMENDATIONS:")
    print("="*60)
    print("1. If Poller/Streamer run as separate Railway services, ensure:")
    print("   - They're not also running in the bot process")
    print("   - Database connection pool is sufficient")
    print("   - Redis is configured correctly")
    print("\n2. To disable Poller/Streamer:")
    print("   - Set POLLER_ENABLED=false")
    print("   - Set STREAMER_ENABLED=false")
    print("\n3. If bot is overwhelmed:")
    print("   - Check Railway logs: railway logs --service poller")
    print("   - Check Railway logs: railway logs --service streamer")
    print("   - Check database load: railway logs --service <bot-service>")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
