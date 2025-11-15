"""
Cleanup Script for Leaderboard Duplicates
Removes duplicate entries that were created during refresh operations
"""

import logging
from sqlalchemy import text
from database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_cleanup():
    """Clean up duplicate leaderboard entries"""
    try:
        with engine.connect() as conn:
            # Get duplicates count before cleanup
            result = conn.execute(text("""
                SELECT user_id, period, week_start_date, COUNT(*) as count
                FROM leaderboard_entries
                GROUP BY user_id, period, week_start_date
                HAVING COUNT(*) > 1
            """))
            
            duplicates = result.fetchall()
            if duplicates:
                logger.info(f"Found {len(duplicates)} duplicate entries:")
                for dup in duplicates:
                    logger.info(f"  User {dup[0]}: {dup[1]} ({dup[2]}) - {dup[3]} entries")
            else:
                logger.info("No duplicates found")
                return True
            
            # Delete duplicates, keeping most recent
            logger.info("Cleaning up duplicates...")
            conn.execute(text("""
                DELETE FROM leaderboard_entries
                WHERE id NOT IN (
                    SELECT DISTINCT ON (user_id, period, week_start_date) id
                    FROM leaderboard_entries
                    ORDER BY user_id, period, week_start_date, calculated_at DESC NULLS LAST
                )
            """))
            conn.commit()
            
            # Verify cleanup
            result = conn.execute(text("""
                SELECT period, COUNT(*) as total, COUNT(DISTINCT user_id) as users
                FROM leaderboard_entries
                GROUP BY period
            """))
            
            logger.info("✅ Cleanup complete. Final state:")
            for row in result.fetchall():
                logger.info(f"  {row[0]}: {row[1]} entries, {row[2]} unique users")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Cleanup error: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = run_cleanup()
    exit(0 if success else 1)
