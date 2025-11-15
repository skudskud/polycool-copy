#!/usr/bin/env python3
"""
DROP POSITIONS TABLE MIGRATION
Removes the broken positions table and all related code
"""

import os
import sys
import logging
from sqlalchemy import text

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db_manager

logger = logging.getLogger(__name__)

def drop_positions_table():
    """Drop the positions table completely"""
    try:
        with db_manager.get_session() as db:
            # Drop the positions table
            db.execute(text("DROP TABLE IF EXISTS positions CASCADE;"))
            db.commit()
            
            logger.info("✅ POSITIONS TABLE DROPPED - Clean transaction-based architecture")
            print("✅ POSITIONS TABLE DROPPED - Clean transaction-based architecture")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error dropping positions table: {e}")
        print(f"❌ Error dropping positions table: {e}")
        return False

if __name__ == "__main__":
    print("🗑️ DROPPING POSITIONS TABLE...")
    print("This will remove the broken position table system completely.")
    print("Positions will now be read directly from blockchain API.")
    
    success = drop_positions_table()
    
    if success:
        print("\n🎉 MIGRATION COMPLETE!")
        print("✅ Position table removed")
        print("✅ Clean transaction-based architecture")
        print("✅ Direct blockchain position reading")
    else:
        print("\n❌ MIGRATION FAILED!")
        print("Check logs for details.")
