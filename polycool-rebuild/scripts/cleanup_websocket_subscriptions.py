#!/usr/bin/env python3
"""
Cleanup WebSocket Subscriptions Script
Removes 'ws' source from markets that have no active positions
Works with both direct DB access and Supabase MCP
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select, update, func
from core.database.connection import get_db
from core.database.models import Market, Position
from infrastructure.logging.logger import setup_logging, get_logger

setup_logging(__name__)
logger = get_logger(__name__)

# Project ID for Supabase MCP
PROJECT_ID = "xxzdlbwfyetaxcmodiec"


async def cleanup_websocket_subscriptions() -> Dict[str, Any]:
    """
    Cleanup markets with source='ws' that have no active positions
    Changes their source back to 'poll'

    Returns:
        Dict with cleanup results
    """
    try:
        async with get_db() as db:
            # Find all markets with source='ws' and check their active positions
            result = await db.execute(
                select(
                    Market.id,
                    Market.title,
                    func.count(Position.id).filter(
                        Position.status == 'active',
                        Position.amount > 0
                    ).label('active_positions')
                )
                .outerjoin(Position, Market.id == Position.market_id)
                .where(Market.source == 'ws')
                .group_by(Market.id, Market.title)
            )
            ws_markets = result.all()

            logger.info(f"🔍 Found {len(ws_markets)} markets with source='ws'")

            if not ws_markets:
                logger.info("✅ No markets with source='ws' to clean up")
                return {
                    "cleaned_count": 0,
                    "kept_count": 0,
                    "total_checked": 0,
                    "markets_cleaned": []
                }

            cleaned_count = 0
            kept_count = 0
            markets_cleaned = []

            for market_id, market_title, active_positions in ws_markets:
                if active_positions == 0:
                    # No active positions - change source to 'poll'
                    await db.execute(
                        update(Market)
                        .where(Market.id == market_id)
                        .values(source='poll')
                    )
                    cleaned_count += 1
                    markets_cleaned.append({
                        "market_id": market_id,
                        "title": market_title[:50] if market_title else "Unknown"
                    })
                    logger.info(f"🧹 Cleaned market {market_id} ({market_title[:50] if market_title else 'Unknown'}...): {active_positions} active positions")
                else:
                    kept_count += 1
                    logger.debug(f"✅ Kept market {market_id} ({market_title[:50] if market_title else 'Unknown'}...): {active_positions} active positions")

            await db.commit()

            logger.info(f"✅ Cleanup complete:")
            logger.info(f"   • Cleaned (changed to 'poll'): {cleaned_count}")
            logger.info(f"   • Kept (still 'ws'): {kept_count}")
            logger.info(f"   • Total checked: {len(ws_markets)}")

            return {
                "cleaned_count": cleaned_count,
                "kept_count": kept_count,
                "total_checked": len(ws_markets),
                "markets_cleaned": markets_cleaned
            }

    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


async def cleanup_via_supabase_mcp(project_id: str = PROJECT_ID) -> Dict[str, Any]:
    """
    Cleanup using Supabase MCP directly
    This works regardless of SKIP_DB setting

    Args:
        project_id: Supabase project ID

    Returns:
        Dict with cleanup results
    """
    try:
        logger.info(f"✅ Using Supabase project ID: {project_id}")

        # Step 1: Find markets with source='ws' and no active positions
        logger.info("🔍 Finding markets with source='ws' and no active positions...")
        find_query = """
        SELECT
            m.id,
            m.source,
            m.title,
            COUNT(p.id) FILTER (WHERE p.status = 'active' AND p.amount > 0) as active_positions_count
        FROM markets m
        LEFT JOIN positions p ON p.market_id = m.id
        WHERE m.source = 'ws'
        GROUP BY m.id, m.source, m.title
        HAVING COUNT(p.id) FILTER (WHERE p.status = 'active' AND p.amount > 0) = 0
        ORDER BY m.id
        """

        logger.info("📋 Executing query via Supabase MCP...")
        logger.info("💡 Note: This requires MCP Supabase tools to be available.")
        logger.info("   If MCP is not available, use the direct DB cleanup instead.")

        # Note: This function should be called with MCP tools available
        # The actual execution will be done via the MCP tool in the calling context
        return {
            "find_query": find_query,
            "project_id": project_id,
            "method": "supabase_mcp"
        }

    except Exception as e:
        logger.error(f"❌ Error during Supabase MCP cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


async def cleanup_websocket_subscriptions_with_mcp(project_id: str = PROJECT_ID) -> Dict[str, Any]:
    """
    Cleanup websocket subscriptions using Supabase MCP
    This is the main function that executes the cleanup via MCP

    Args:
        project_id: Supabase project ID

    Returns:
        Dict with cleanup results
    """
    try:
        # First, find markets to clean
        find_query = """
        SELECT
            m.id,
            m.title,
            COUNT(p.id) FILTER (WHERE p.status = 'active' AND p.amount > 0) as active_positions_count
        FROM markets m
        LEFT JOIN positions p ON p.market_id = m.id
        WHERE m.source = 'ws'
        GROUP BY m.id, m.title
        HAVING COUNT(p.id) FILTER (WHERE p.status = 'active' AND p.amount > 0) = 0
        ORDER BY m.id
        """

        logger.info(f"🔍 Finding markets to clean via Supabase MCP (project: {project_id})...")

        # Execute find query via MCP (this will be called by the AI assistant)
        # For now, return the query to execute
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
        logger.error(f"❌ Error preparing Supabase MCP cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


async def cleanup_websocket_manager_subscriptions() -> Dict[str, Any]:
    """
    Cleanup subscriptions in WebSocketManager that have no active positions
    This removes subscriptions from the in-memory tracking

    Returns:
        Dict with cleanup results
    """
    try:
        from core.services.websocket_manager import websocket_manager

        if not websocket_manager.active_subscriptions:
            logger.info("✅ No active subscriptions in WebSocketManager to clean")
            return {
                "cleaned_count": 0,
                "kept_count": 0,
                "total_checked": 0
            }

        logger.info(f"🔍 Found {len(websocket_manager.active_subscriptions)} subscriptions in WebSocketManager")

        cleaned_count = 0
        kept_count = 0

        # Get all active positions from DB
        async with get_db() as db:
            result = await db.execute(
                select(Position.user_id, Position.market_id)
                .where(Position.status == 'active', Position.amount > 0)
                .distinct()
            )
            active_positions = {(row[0], row[1]) for row in result.fetchall()}

        # Check each subscription
        subscriptions_to_remove = []
        for subscription_key in list(websocket_manager.active_subscriptions):
            try:
                user_id_str, market_id = subscription_key.split(":", 1)
                user_id = int(user_id_str)

                # Check if there's an active position for this user+market
                if (user_id, market_id) not in active_positions:
                    subscriptions_to_remove.append(subscription_key)
                    cleaned_count += 1
                else:
                    kept_count += 1
            except ValueError:
                logger.warning(f"⚠️ Invalid subscription key format: {subscription_key}")
                continue

        # Remove subscriptions without active positions
        for subscription_key in subscriptions_to_remove:
            websocket_manager.active_subscriptions.discard(subscription_key)
            logger.debug(f"🧹 Removed subscription {subscription_key} from WebSocketManager")

        logger.info(f"✅ WebSocketManager cleanup complete:")
        logger.info(f"   • Removed subscriptions: {cleaned_count}")
        logger.info(f"   • Kept subscriptions: {kept_count}")
        logger.info(f"   • Total checked: {len(websocket_manager.active_subscriptions) + cleaned_count}")

        return {
            "cleaned_count": cleaned_count,
            "kept_count": kept_count,
            "total_checked": len(websocket_manager.active_subscriptions) + cleaned_count
        }

    except Exception as e:
        logger.error(f"❌ Error cleaning WebSocketManager subscriptions: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "cleaned_count": 0,
            "kept_count": 0,
            "total_checked": 0,
            "error": str(e)
        }


async def main() -> None:
    """Main entry point"""
    logger.info("🚀 Starting WebSocket subscriptions cleanup...")

    # Check if SKIP_DB is set
    skip_db = os.getenv("SKIP_DB", "false").lower() == "true"

    try:
        if skip_db:
            logger.info("⚠️ SKIP_DB=true - Using Supabase MCP for cleanup")
            logger.info("💡 Note: This script will prepare queries for MCP execution.")
            logger.info("   Execute them via MCP Supabase tools or manually in Supabase dashboard.")

            result = await cleanup_websocket_subscriptions_with_mcp()

            logger.info("\n" + "="*80)
            logger.info("📝 SQL QUERIES TO EXECUTE:")
            logger.info("="*80)
            logger.info("\n1️⃣ FIND MARKETS TO CLEAN:")
            logger.info(result["find_query"])
            logger.info("\n2️⃣ CLEANUP (UPDATE SOURCE TO 'poll'):")
            logger.info(result["cleanup_query"])
            logger.info("\n" + "="*80)
            logger.info("\n✅ Script completed. Execute the cleanup query via MCP Supabase tools.")
        else:
            # Initialize database connection
            from core.database.connection import init_db
            await init_db()
            logger.info("✅ Database initialized")

            # Cleanup markets with source='ws' and no active positions
            result = await cleanup_websocket_subscriptions()

            # Also cleanup WebSocketManager subscriptions if available
            try:
                ws_result = await cleanup_websocket_manager_subscriptions()
                logger.info(f"✅ WebSocketManager cleanup: {ws_result}")
            except Exception as ws_error:
                logger.warning(f"⚠️ WebSocketManager cleanup skipped: {ws_error}")

            logger.info("✅ Cleanup completed successfully")
            logger.info(f"   Results: {result}")

    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
