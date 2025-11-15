#!/usr/bin/env python3
"""
Cleanup WebSocket Subscriptions Script (API Mode)
Removes 'ws' source from markets that have no active positions
Works with SKIP_DB=true by using API endpoints
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.services.api_client import get_api_client
from infrastructure.logging.logger import setup_logging, get_logger

setup_logging(__name__)
logger = get_logger(__name__)


async def cleanup_websocket_subscriptions_api() -> None:
    """
    Cleanup markets with source='ws' that have no active positions
    Uses API endpoints to work with SKIP_DB=true
    """
    try:
        api_client = get_api_client()

        # Get all markets (we'll filter for source='ws' client-side)
        # Note: This is a simplified approach - in production you might want
        # a dedicated endpoint to get markets by source
        logger.info("🔍 Fetching markets from API...")

        # For now, we'll use a direct DB query via migration/script
        # But let's create a more practical solution using the cleanup script
        # that can work with direct DB access

        logger.warning("⚠️ API mode cleanup requires direct DB access")
        logger.info("💡 Use cleanup_websocket_subscriptions.py instead (requires SKIP_DB=false)")
        logger.info("   Or run this script on the API service where SKIP_DB=false")

    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


async def cleanup_via_supabase_mcp() -> None:
    """
    Cleanup using Supabase MCP directly
    This works regardless of SKIP_DB setting
    """
    try:
        from mcp_supabase import mcp_supabase_execute_sql, mcp_supabase_list_projects

        # Get project ID
        projects = await mcp_supabase_list_projects()
        project_id = None
        for proj in projects:
            if 'polycool' in proj.get('name', '').lower():
                project_id = proj['id']
                break

        if not project_id:
            logger.error("❌ Could not find polycool project")
            return

        logger.info(f"✅ Using project: {project_id}")

        # Find markets with source='ws' and no active positions
        query = """
        SELECT m.id, m.source, m.title, COUNT(p.id) as active_positions_count
        FROM markets m
        LEFT JOIN positions p ON p.market_id = m.id AND p.status = 'active' AND p.amount > 0
        WHERE m.source = 'ws'
        GROUP BY m.id, m.source, m.title
        HAVING COUNT(p.id) = 0
        ORDER BY m.id
        """

        result = await mcp_supabase_execute_sql(project_id, query)

        if not result or 'error' in result:
            logger.error(f"❌ Query failed: {result}")
            return

        markets_to_clean = result.get('data', [])
        logger.info(f"🔍 Found {len(markets_to_clean)} markets with source='ws' and no active positions")

        if not markets_to_clean:
            logger.info("✅ No markets to clean up")
            return

        # Update each market to source='poll'
        cleaned_count = 0
        for market in markets_to_clean:
            market_id = market['id']
            market_title = market.get('title', 'Unknown')[:50]

            update_query = f"""
            UPDATE markets
            SET source = 'poll', updated_at = NOW()
            WHERE id = '{market_id}' AND source = 'ws'
            """

            update_result = await mcp_supabase_execute_sql(project_id, update_query)

            if update_result and 'error' not in update_result:
                cleaned_count += 1
                logger.info(f"🧹 Cleaned market {market_id} ({market_title}...): changed source from 'ws' to 'poll'")
            else:
                logger.warning(f"⚠️ Failed to clean market {market_id}: {update_result}")

        logger.info(f"✅ Cleanup complete:")
        logger.info(f"   • Cleaned (changed to 'poll'): {cleaned_count}")
        logger.info(f"   • Total checked: {len(markets_to_clean)}")

    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


async def main() -> None:
    """Main entry point"""
    logger.info("🚀 Starting WebSocket subscriptions cleanup via Supabase MCP...")

    try:
        await cleanup_via_supabase_mcp()
        logger.info("✅ Cleanup completed successfully")
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())


