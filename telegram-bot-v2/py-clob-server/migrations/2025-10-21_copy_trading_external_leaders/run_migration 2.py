#!/usr/bin/env python3
"""
Migration Runner: Create External Leaders Table
Executes the migration.sql file to create external_leaders table
"""

import os
import logging
from pathlib import Path
from database import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Execute the external leaders migration"""
    try:
        # Get migration SQL file path
        migration_file = Path(__file__).parent / "migration.sql"
        
        if not migration_file.exists():
            logger.error(f"❌ Migration file not found: {migration_file}")
            return False
        
        # Read SQL
        with open(migration_file, 'r') as f:
            sql = f.read()
        
        # Execute migration
        session = SessionLocal()
        try:
            # Split by semicolon and execute each statement
            statements = [s.strip() for s in sql.split(';') if s.strip()]
            
            for statement in statements:
                logger.info(f"Executing: {statement[:80]}...")
                session.execute(statement)
            
            session.commit()
            logger.info("✅ External leaders table migration completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            session.rollback()
            return False
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"❌ Unexpected error during migration: {e}")
        return False


if __name__ == "__main__":
    success = run_migration()
    exit(0 if success else 1)
