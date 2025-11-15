#!/usr/bin/env python3
"""
Run Twitter Bot Migration
Executes SQL migrations to add tweeted_at column and mark historical trades
"""

import os
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.persistence.database import get_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Execute Twitter bot migration files"""
    try:
        logger.info("🔄 Starting Twitter bot migration...")
        
        # Get database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Migration directory
        migration_dir = Path(__file__).parent
        
        # Migration files in order
        migration_files = [
            "add_tweeted_at_column.sql",
            "mark_historical_as_tweeted.sql"
        ]
        
        for migration_file in migration_files:
            file_path = migration_dir / migration_file
            
            if not file_path.exists():
                logger.error(f"❌ Migration file not found: {migration_file}")
                continue
            
            logger.info(f"📄 Running {migration_file}...")
            
            with open(file_path, 'r') as f:
                sql = f.read()
            
            cursor.execute(sql)
            conn.commit()
            
            logger.info(f"✅ {migration_file} completed")
        
        cursor.close()
        conn.close()
        
        logger.info("✅ Twitter bot migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)

