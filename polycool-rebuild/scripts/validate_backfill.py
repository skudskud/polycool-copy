#!/usr/bin/env python3
"""
Backfill Validation Script - Quick checks to verify backfill integrity
"""
import asyncio
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.database.connection import get_db, init_db
from sqlalchemy import text
from infrastructure.logging.logger import get_logger
import os

logger = get_logger(__name__)


async def validate_backfill():
    """Run comprehensive validation checks on the backfill"""
    print("🔍 Starting Backfill Validation...")

    try:
        print("🗄️ Initializing database...")
        if os.getenv("SKIP_DB", "false").lower() != "true":
            await init_db()
            print("✅ Database initialized")
        else:
            print("⚠️ Database initialization skipped (SKIP_DB=true)")
            raise RuntimeError("Cannot validate without database. Set SKIP_DB=false")
        async with get_db() as db:
            # Check 1: Total market count
            result = await db.execute(text("SELECT COUNT(*) FROM markets"))
            total_markets = result.fetchone()[0]
            print(f"📊 Total markets in DB: {total_markets}")

            # Check 2: Orphan detection (markets without event_title)
            result = await db.execute(text("""
                SELECT COUNT(*) FROM markets
                WHERE event_title IS NULL OR event_title = ''
            """))
            orphan_count = result.fetchone()[0]
            print(f"👻 Orphan markets (no event_title): {orphan_count}")

            if orphan_count > 0:
                print("❌ ORPHANS DETECTED! These markets have no event_title:")
                result = await db.execute(text("""
                    SELECT id, title, event_id
                    FROM markets
                    WHERE event_title IS NULL OR event_title = ''
                    LIMIT 10
                """))
                orphans = result.fetchall()
                for orphan in orphans:
                    print(f"  - ID: {orphan[0]}, Title: {orphan[1]}, Event ID: {orphan[2]}")

            # Check 3: Event market distribution
            result = await db.execute(text("""
                SELECT
                    COUNT(CASE WHEN event_id IS NOT NULL THEN 1 END) as event_markets,
                    COUNT(CASE WHEN event_id IS NULL THEN 1 END) as standalone_markets
                FROM markets
            """))
            row = result.fetchone()
            event_markets = row[0]
            standalone_markets = row[1]
            print(f"🏛️ Event markets: {event_markets}")
            print(f"🏠 Standalone markets: {standalone_markets}")

            # Check 4: Category distribution
            result = await db.execute(text("""
                SELECT category, COUNT(*) as count
                FROM markets
                WHERE category IS NOT NULL
                GROUP BY category
                ORDER BY count DESC
                LIMIT 10
            """))
            categories = result.fetchall()
            print("🏷️ Top categories:")
            for category, count in categories:
                print(f"  - {category}: {count}")

            # Check 5: Sample markets with good data
            result = await db.execute(text("""
                SELECT id, title, event_title, category, end_date, is_active
                FROM markets
                WHERE event_title IS NOT NULL
                AND category IS NOT NULL
                AND end_date IS NOT NULL
                LIMIT 5
            """))
            sample_markets = result.fetchall()
            print("✅ Sample markets with complete data:")
            for market in sample_markets:
                id, title, event_title, category, end_date, is_active = market
                print(f"  - {id}: '{title[:50]}...' | Event: '{event_title[:30]}...' | Cat: {category} | Active: {is_active}")

            # Check 6: Resolution status
            result = await db.execute(text("""
                SELECT
                    COUNT(CASE WHEN is_resolved = true THEN 1 END) as resolved,
                    COUNT(CASE WHEN is_resolved = false OR is_resolved IS NULL THEN 1 END) as active
                FROM markets
            """))
            row = result.fetchone()
            resolved_count = row[0]
            active_count = row[1]
            print(f"🔍 Market status: {active_count} active, {resolved_count} resolved")

            # Overall assessment
            print("\n" + "="*50)
            print("📋 BACKFILL VALIDATION RESULTS")
            print("="*50)

            issues = []

            if total_markets == 0:
                issues.append("❌ No markets found in database!")
            elif total_markets < 100:
                issues.append(f"⚠️ Very low market count: {total_markets}")

            if orphan_count > 0:
                issues.append(f"❌ {orphan_count} orphan markets detected (should be 0)")

            if event_markets == 0:
                issues.append("❌ No event markets found")

            if standalone_markets == 0:
                issues.append("⚠️ No standalone markets found (might be normal)")

            if not issues:
                print("✅ EXCELLENT: Backfill looks perfect!")
                print("🎯 Zero orphans, good data distribution, complete metadata")
                return True
            else:
                print("⚠️ ISSUES FOUND:")
                for issue in issues:
                    print(f"  {issue}")
                return False

    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        print(f"❌ Validation error: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(validate_backfill())
    sys.exit(0 if success else 1)
