#!/usr/bin/env python3
"""
Check Last Smart Wallet Trade
Simple script to check the most recent trade in smart_wallet_trades table
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_last_trade():
    """Check the most recent trade in smart_wallet_trades"""

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
        logger.error("❌ DATABASE_URL not found in environment or .env file")
        return False

    try:
        logger.info("🔌 Connecting to database...")
        conn = psycopg2.connect(database_url)

        cursor = conn.cursor()

        # Get the most recent trade
        cursor.execute("""
            SELECT
                MAX(timestamp) as last_trade_time,
                MAX(created_at) as last_sync_time,
                COUNT(*) as total_trades
            FROM smart_wallet_trades
        """)

        result = cursor.fetchone()
        last_trade_time, last_sync_time, total_trades = result

        print("\n📊 SMART WALLET TRADES STATUS")
        print("=" * 40)
        print(f"🕐 Last trade timestamp: {last_trade_time}")
        print(f"💾 Last sync timestamp: {last_sync_time}")
        print(f"📈 Total trades: {total_trades}")

        # Check if scheduler is working
        if last_sync_time:
            time_since_sync = datetime.now(timezone.utc) - last_sync_time.replace(tzinfo=timezone.utc)
            hours_since_sync = time_since_sync.total_seconds() / 3600

            print(f"\n⏱️ Time since last sync: {hours_since_sync:.1f} hours")

            if hours_since_sync < 0.2:  # Less than 12 minutes
                print("✅ Scheduler appears to be working (last sync < 12 min)")
            elif hours_since_sync < 1:  # Less than 1 hour
                print("⚠️ Scheduler may be running slowly")
            else:
                print("❌ Scheduler may be stopped")

        cursor.close()
        conn.close()

        return True

    except psycopg2.Error as e:
        logger.error(f"❌ Database error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error checking trades: {e}")
        return False

if __name__ == "__main__":
    success = check_last_trade()
    sys.exit(0 if success else 1)
