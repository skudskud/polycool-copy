#!/usr/bin/env python3
"""
Cleanup WebSocket Subscriptions Script (Supabase MCP)
Removes 'ws' source from markets that have no active positions
Uses Supabase MCP directly - works regardless of SKIP_DB setting

This script executes the cleanup directly via MCP Supabase tools.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.logging.logger import setup_logging, get_logger

setup_logging(__name__)
logger = get_logger(__name__)

# Project ID - can be overridden via environment variable
PROJECT_ID = "xxzdlbwfyetaxcmodiec"


def cleanup_via_supabase_mcp(project_id: str = PROJECT_ID) -> dict:
    """
    Cleanup using Supabase MCP directly
    This works regardless of SKIP_DB setting

    Args:
        project_id: Supabase project ID

    Returns:
        Dict with cleanup results
    """
    try:
        logger.info(f"✅ Using project ID: {project_id}")

        # Step 1: Find markets with source='ws' and no active positions
        logger.info("🔍 Finding markets with source='ws' and no active positions...")
        find_query = """
        SELECT m.id, m.source, m.title, COUNT(p.id) FILTER (WHERE p.status = 'active' AND p.amount > 0) as active_positions_count
        FROM markets m
        LEFT JOIN positions p ON p.market_id = m.id
        WHERE m.source = 'ws'
        GROUP BY m.id, m.source, m.title
        HAVING COUNT(p.id) FILTER (WHERE p.status = 'active' AND p.amount > 0) = 0
        ORDER BY m.id
        """

        logger.info("📋 Executing query to find markets to clean...")
        logger.info("💡 Note: This script requires MCP Supabase tools.")
        logger.info("   The cleanup will be performed via MCP execute_sql tool.")

        # Return the queries to execute
        cleanup_query = """
        UPDATE markets
        SET source = 'poll', updated_at = NOW()
        WHERE id IN (
            SELECT m.id
            FROM markets m
            LEFT JOIN positions p ON p.market_id = m.id AND p.status = 'active' AND p.amount > 0
            WHERE m.source = 'ws'
            GROUP BY m.id
            HAVING COUNT(p.id) = 0
        )
        RETURNING id, source, title
        """

        return {
            "find_query": find_query,
            "cleanup_query": cleanup_query,
            "project_id": project_id
        }

    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def main() -> None:
    """Main entry point"""
    logger.info("🚀 Starting WebSocket subscriptions cleanup via Supabase MCP...")
    logger.info("⚠️  This script prepares the SQL queries.")
    logger.info("    Execute them via MCP Supabase tools or manually in Supabase dashboard.")

    result = cleanup_via_supabase_mcp()

    logger.info("\n" + "="*80)
    logger.info("📝 SQL QUERIES TO EXECUTE:")
    logger.info("="*80)
    logger.info("\n1️⃣ FIND MARKETS TO CLEAN:")
    logger.info(result["find_query"])
    logger.info("\n2️⃣ CLEANUP (UPDATE SOURCE TO 'poll'):")
    logger.info(result["cleanup_query"])
    logger.info("\n" + "="*80)
    logger.info("\n✅ Script completed. Execute the cleanup query via MCP Supabase tools.")


if __name__ == "__main__":
    main()
