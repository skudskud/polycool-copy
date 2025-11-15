#!/usr/bin/env python3
"""
Run TP/SL Enhancements Migration
Adds cancelled_reason column to tpsl_orders table
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database import SessionLocal
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Execute the migration SQL file"""
    try:
        # Get the SQL file path
        sql_file = Path(__file__).parent / "001_add_cancellation_reason.sql"
        
        if not sql_file.exists():
            logger.error(f"❌ Migration file not found: {sql_file}")
            return False
        
        # Read SQL file
        with open(sql_file, 'r') as f:
            sql_content = f.read()
        
        logger.info("📋 Running TP/SL enhancements migration...")
        
        # Execute migration
        with SessionLocal() as session:
            # Split by semicolon to execute each statement separately
            statements = [s.strip() for s in sql_content.split(';') if s.strip()]
            
            for statement in statements:
                if statement:
                    logger.info(f"Executing: {statement[:100]}...")
                    session.execute(text(statement))
            
            session.commit()
            logger.info("✅ Migration completed successfully!")
            return True
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)

