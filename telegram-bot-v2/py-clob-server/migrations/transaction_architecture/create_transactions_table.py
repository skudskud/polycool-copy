#!/usr/bin/env python3
"""
DATABASE MIGRATION: ADD TRANSACTIONS TABLE
Creates the new transactions table for enterprise-grade trade logging
"""

import os
import sys
import logging
from sqlalchemy import create_engine, text
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base, engine, Transaction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_transactions_table():
    """Create the transactions table"""
    
    logger.info("🚀 STARTING DATABASE MIGRATION: CREATE TRANSACTIONS TABLE")
    
    try:
        # Create all tables (this will create the transactions table)
        Base.metadata.create_all(bind=engine)
        
        logger.info("✅ TRANSACTIONS TABLE CREATED SUCCESSFULLY!")
        
        # Verify table exists
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'transactions'
            """))
            
            if result.fetchone():
                logger.info("✅ VERIFICATION: Transactions table exists in database")
                
                # Check table structure
                result = conn.execute(text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'transactions'
                    ORDER BY ordinal_position
                """))
                
                logger.info("📋 TRANSACTIONS TABLE STRUCTURE:")
                for row in result:
                    logger.info(f"   • {row.column_name}: {row.data_type} ({'NULL' if row.is_nullable == 'YES' else 'NOT NULL'})")
                
                # Check indexes
                result = conn.execute(text("""
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE tablename = 'transactions'
                """))
                
                logger.info("🔍 TRANSACTIONS TABLE INDEXES:")
                for row in result:
                    logger.info(f"   • {row.indexname}: {row.indexdef}")
                
            else:
                logger.error("❌ VERIFICATION FAILED: Transactions table not found")
                return False
        
        logger.info("🎉 MIGRATION COMPLETE: Ready for enterprise-grade transaction logging!")
        return True
        
    except Exception as e:
        logger.error(f"❌ MIGRATION FAILED: {e}")
        return False

def rollback_transactions_table():
    """Rollback: Drop the transactions table"""
    
    logger.warning("⚠️ ROLLBACK: DROPPING TRANSACTIONS TABLE")
    
    try:
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS transactions CASCADE"))
            conn.commit()
            
        logger.info("✅ ROLLBACK COMPLETE: Transactions table dropped")
        return True
        
    except Exception as e:
        logger.error(f"❌ ROLLBACK FAILED: {e}")
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback_transactions_table()
    else:
        create_transactions_table()
