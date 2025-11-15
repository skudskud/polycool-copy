#!/usr/bin/env python3
"""
Script to clear the markets table
⚠️ WARNING: This will DELETE ALL markets from the database

USAGE:
- Production: python scripts/dev/clear_markets_table.py --force
- Development: python scripts/dev/clear_markets_table.py --force
- Interactive: python scripts/dev/clear_markets_table.py

Before running:
1. Check if positions table has FK constraint to markets
2. If yes, either delete positions first or disable FK temporarily
"""

import asyncio
import os
import sys
from sqlalchemy import text
from core.database.connection import get_db

# Check for --force flag
FORCE_MODE = '--force' in sys.argv


async def check_positions_count():
    """Check how many positions exist"""
    try:
        async with get_db() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM positions"))
            count = result.scalar()
            print(f"📊 Found {count} positions in database")
            return count
    except Exception as e:
        print(f"❌ Error checking positions: {e}")
        return None


async def check_foreign_key_constraint():
    """Check if positions table has FK to markets"""
    try:
        async with get_db() as db:
            result = await db.execute(text("""
                SELECT constraint_name, constraint_type
                FROM information_schema.table_constraints
                WHERE table_name = 'positions'
                AND constraint_type = 'FOREIGN KEY'
            """))
            constraints = result.fetchall()
            if constraints:
                print(f"⚠️ Found {len(constraints)} foreign key constraints on positions table:")
                for constraint in constraints:
                    print(f"   - {constraint[0]}")
                return True
            else:
                print("✅ No foreign key constraints found on positions table")
                return False
    except Exception as e:
        print(f"❌ Error checking constraints: {e}")
        return None


async def clear_markets_table():
    """Clear all markets from the markets table"""
    print("🔧 Starting markets table cleanup...")
    print("⚠️  This will DELETE ALL markets from the database")

    # Check positions first
    positions_count = await check_positions_count()
    if positions_count is None:
        print("❌ Could not check positions count. Aborting.")
        return False

    if positions_count > 0:
        print(f"⚠️  WARNING: {positions_count} positions exist in the database")
        print("⚠️  If positions.market_id has FK to markets.id, DELETE will fail")
        print("⚠️  Options:")
        print("   1. Delete positions first: DELETE FROM positions;")
        print("   2. Disable FK temporarily")
        print("   3. Use CASCADE DELETE if FK is configured")

        if FORCE_MODE:
            print("🔧 Force mode: continuing automatically")
            response = 'yes'
        else:
            response = input("\n❓ Do you want to continue? (yes/no): ")

        if response.lower() != 'yes':
            print("❌ Aborted by user")
            return False

    # Check FK constraints
    has_fk = await check_foreign_key_constraint()
    if has_fk:
        print("\n⚠️  Foreign key constraints detected. DELETE may fail.")
        if FORCE_MODE:
            print("🔧 Force mode: continuing automatically")
            response = 'yes'
        else:
            response = input("❓ Continue anyway? (yes/no): ")

        if response.lower() != 'yes':
            print("❌ Aborted by user")
            return False

    try:
        async with get_db() as db:
            # Count markets before deletion
            result = await db.execute(text("SELECT COUNT(*) FROM markets"))
            markets_count = result.scalar()
            print(f"\n📊 Found {markets_count} markets to delete")

            if markets_count == 0:
                print("✅ Markets table is already empty")
                return True

            # Delete all markets
            print("🗑️  Deleting all markets...")
            await db.execute(text("DELETE FROM markets"))
            await db.commit()

            # Verify deletion
            result = await db.execute(text("SELECT COUNT(*) FROM markets"))
            remaining = result.scalar()

            if remaining == 0:
                print(f"✅ Successfully deleted {markets_count} markets")
                print("✅ Markets table is now empty")
                return True
            else:
                print(f"⚠️  Warning: {remaining} markets still remain (may be due to FK constraints)")
                return False

    except Exception as e:
        print(f"❌ Error clearing markets table: {e}")
        return False


async def main():
    """Main function"""
    print("🚀 Starting markets table cleanup")
    print("=" * 60)

    # Initialize database
    from core.database.connection import init_db
    await init_db()
    print("✅ Database initialized")

    # Check environment
    db_url = os.getenv('DATABASE_URL', '')
    if 'prod' in db_url.lower() or 'production' in db_url.lower():
        print("⚠️  WARNING: This appears to be a PRODUCTION database!")
        if FORCE_MODE:
            print("🔧 Force mode: continuing automatically (PRODUCTION DATABASE!)")
            response = 'yes'
        else:
            response = input("❓ Are you sure you want to continue? (yes/no): ")

        if response.lower() != 'yes':
            print("❌ Aborted by user")
            return

    success = await clear_markets_table()

    if success:
        print("\n🎉 Cleanup successful!")
        print("\nNext steps:")
        print("1. Run the poller to repopulate markets")
        print("2. Verify markets are being inserted correctly")
    else:
        print("\n❌ Cleanup failed!")
        print("Please check the errors above and try again")


if __name__ == "__main__":
    asyncio.run(main())
