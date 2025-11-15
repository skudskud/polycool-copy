#!/usr/bin/env python3
"""
Smart Wallet Enhancements Migration Runner
Adds market_numeric_id column to smart_wallet_trades table
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.persistence.db_config import get_db_connection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Execute the smart wallet enhancements migration"""
    migration_file = Path(__file__).parent / "add_market_numeric_id.sql"

    if not migration_file.exists():
        logger.error(f"❌ Migration file not found: {migration_file}")
        return False

    try:
        # Read migration SQL
        with open(migration_file, 'r') as f:
            migration_sql = f.read()

        logger.info("📊 Running smart wallet enhancements migration...")

        # Execute migration
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(migration_sql)
            conn.commit()
            logger.info("✅ Migration completed successfully")
            return True

        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Migration failed: {e}")
            return False

        finally:
            cursor.close()
            conn.close()

    except Exception as e:
        logger.error(f"❌ Error running migration: {e}")
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
