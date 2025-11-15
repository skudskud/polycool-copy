#!/usr/bin/env python3
"""
Diagnose Scheduler Issues
Check if the APScheduler is running and why smart wallet sync might not be working
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def diagnose_scheduler():
    """Diagnose scheduler issues"""

    # Get DATABASE_URL from environment or .env file
    database_url = os.getenv('DATABASE_URL')

    if not database_url:
        # Try to load from .env file
        env_file = Path(__file__).parent / '.env'
        if env_file.exists():
            with open(env_file, 'r') as f:
                for line in f:
                    if line.startswith('DATABASE_URL='):
                        database_url = line.split('=', 1)[1].strip()
                        break

    if not database_url:
        logger.error("❌ DATABASE_URL not found")
        return False

    try:
        logger.info("🔌 Connecting to database...")
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        print("\n🔍 SCHEDULER DIAGNOSTIC")
        print("=" * 50)

        # Check if smart_wallet_trades table exists and has data
        cursor.execute("""
            SELECT COUNT(*) as total_trades,
                   MAX(timestamp) as last_trade_time,
                   MAX(created_at) as last_sync_time
            FROM smart_wallet_trades
        """)

        result = cursor.fetchone()
        total_trades, last_trade_time, last_sync_time = result

        print(f"📊 Smart wallet trades: {total_trades}")
        print(f"🕐 Last trade: {last_trade_time}")
        print(f"💾 Last sync: {last_sync_time}")

        if last_sync_time:
            time_since_sync = datetime.now(timezone.utc) - last_sync_time.replace(tzinfo=timezone.utc)
            hours_since_sync = time_since_sync.total_seconds() / 3600
            print(f"⏱️ Time since last sync: {hours_since_sync:.1f} hours")

            if hours_since_sync > 0.5:  # More than 30 minutes
                print("❌ Scheduler may be stopped or failing")
            else:
                print("✅ Scheduler appears to be working")

        # Check if smart_wallets table exists and has data
        cursor.execute("""
            SELECT COUNT(*) as total_wallets,
                   MAX(updated_at) as last_wallet_update
            FROM smart_wallets
        """)

        wallet_result = cursor.fetchone()
        total_wallets, last_wallet_update = wallet_result

        print(f"👥 Smart wallets tracked: {total_wallets}")
        print(f"🔄 Last wallet update: {last_wallet_update}")

        # Check recent API errors or issues
        cursor.execute("""
            SELECT wallet_address, market_question, timestamp, is_first_time, value
            FROM smart_wallet_trades
            WHERE timestamp > NOW() - INTERVAL '1 hour'
            ORDER BY timestamp DESC
            LIMIT 5
        """)

        recent_trades = cursor.fetchall()

        if recent_trades:
            print("\n✅ Recent trades found (last hour):")
            for trade in recent_trades:
                wallet, market, timestamp, is_first, value = trade
                print(f"   • {wallet[:10]}... | {market[:30]}... | ${value:.2f} | {'FIRST' if is_first else 'REPEAT'} | {timestamp}")
        else:
            print("\n❌ No trades in the last hour")

        cursor.close()
        conn.close()

        # Check scheduler configuration in code
        print("\n📋 SCHEDULER CONFIGURATION:")
        print("   • Should run every 10 minutes")
        print("   • Should sync trades for all smart wallets")
        print("   • Should log: '🔄 Starting smart wallet trades sync...'")
        print("   • Should log: '✅ Sync complete: X wallets synced'")
        print("   • Final stats should show recent sync time")
        return True

    except psycopg2.Error as e:
        logger.error(f"❌ Database error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error diagnosing scheduler: {e}")
        return False

if __name__ == "__main__":
    success = diagnose_scheduler()
    sys.exit(0 if success else 1)
