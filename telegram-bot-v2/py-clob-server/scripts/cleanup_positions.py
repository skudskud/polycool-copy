#!/usr/bin/env python3
"""
PHASE 1: EMERGENCY CLEANUP SCRIPT
Wipes the positions table to prepare for blockchain-based architecture
"""

import os
import sys
import logging
from sqlalchemy import text
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal  # Position removed - table no longer exists

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_positions():
    """Execute the positions table cleanup"""
    
    logger.info("🚨 STARTING PHASE 1: EMERGENCY CLEANUP")
    logger.info("🗑️  WIPING POSITIONS TABLE FOR BLOCKCHAIN ARCHITECTURE OVERHAUL")
    
    try:
        # Create database session
        session = SessionLocal()
        
        try:
            # First, count what we're about to delete
            result = session.execute(text("SELECT COUNT(*) as total FROM positions WHERE is_active = true"))
            total_positions = result.fetchone()[0]
            
            result = session.execute(text("SELECT COUNT(DISTINCT user_id) as users FROM positions WHERE is_active = true"))
            affected_users = result.fetchone()[0]
            
            logger.info(f"📊 CLEANUP SCOPE:")
            logger.info(f"   • Total positions to delete: {total_positions}")
            logger.info(f"   • Users affected: {affected_users}")
            
            if total_positions == 0:
                logger.info("✅ No positions to clean up - table already empty")
                return
            
            # Show sample of what we're deleting
            logger.info("📋 SAMPLE POSITIONS BEING DELETED:")
            result = session.execute(text("""
                SELECT user_id, market_id, outcome, tokens, buy_price, created_at 
                FROM positions 
                WHERE is_active = true 
                ORDER BY created_at DESC 
                LIMIT 5
            """))
            
            for row in result:
                logger.info(f"   • User {row.user_id}: {row.tokens} {row.outcome} tokens in {row.market_id[:20]}...")
            
            # NUCLEAR OPTION: Wipe everything
            logger.warning("⚠️  EXECUTING NUCLEAR CLEANUP IN 3 SECONDS...")
            import time
            time.sleep(3)
            
            # Delete all positions
            session.execute(text("TRUNCATE TABLE positions RESTART IDENTITY CASCADE"))
            session.commit()
            
            # Verify cleanup
            result = session.execute(text("SELECT COUNT(*) as remaining FROM positions"))
            remaining = result.fetchone()[0]
            
            logger.info(f"✅ CLEANUP COMPLETE!")
            logger.info(f"   • Positions deleted: {total_positions}")
            logger.info(f"   • Remaining positions: {remaining}")
            logger.info(f"   • Users affected: {affected_users}")
            
            if remaining == 0:
                logger.info("🎉 POSITIONS TABLE SUCCESSFULLY WIPED!")
                logger.info("🔧 Ready for blockchain-based position detection!")
            else:
                logger.error(f"❌ CLEANUP INCOMPLETE - {remaining} positions remain")
                
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"❌ CLEANUP FAILED: {e}")
        raise

if __name__ == "__main__":
    cleanup_positions()
