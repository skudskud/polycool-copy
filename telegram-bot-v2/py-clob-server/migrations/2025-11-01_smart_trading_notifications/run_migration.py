#!/usr/bin/env python3
"""
Smart Trading Notifications Migration Runner
Creates the smart_trade_notifications table for tracking sent notifications
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import database module
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def run_migration():
    """Execute smart trading notifications migration"""
    try:
        import psycopg2
        from dotenv import load_dotenv

        # Load .env file from project root
        env_path = Path(__file__).parent.parent.parent / '.env'
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ Loaded environment from {env_path}")

        # Get DATABASE_URL from environment
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("❌ ERROR: DATABASE_URL environment variable not set")
            print("   Set it with: export DATABASE_URL='postgresql://...'")
            return False

        print("🚀 Starting Smart Trading Notifications Migration")
        print(f"📊 Database: {database_url.split('@')[1] if '@' in database_url else 'localhost'}")
        print()

        # Connect to database
        conn = psycopg2.connect(database_url)
        conn.set_session(autocommit=False)
        cursor = conn.cursor()

        # Execute migration
        migration_file = Path(__file__).parent.parent / '2025-11-01_smart_trading_notifications.sql'
        print(f"📄 Reading migration file: {migration_file}")

        with open(migration_file, 'r') as f:
            migration_sql = f.read()

        print("⚡ Executing migration...")
        cursor.execute(migration_sql)
        conn.commit()

        print("✅ Migration completed successfully!")
        print()
        print("📋 Changes applied:")
        print("  - Created smart_trade_notifications table")
        print("  - Added indexes for performance")
        print("  - Created cleanup function for old notifications")

        cursor.close()
        conn.close()

        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
