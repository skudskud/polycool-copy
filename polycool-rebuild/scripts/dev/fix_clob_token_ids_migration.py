#!/usr/bin/env python3
"""
Migration script to fix clob_token_ids triple JSON encoding issue

This script converts malformed clob_token_ids from triple-encoded JSON strings
to proper JSONB arrays.

Before: "\"[\\\"123...\\\", \\\"456...\\\"]\""
After:  "[\"123...\", \"456...\"]"

USAGE:
- Production: python scripts/dev/fix_clob_token_ids_migration.py
- Development: python scripts/dev/fix_clob_token_ids_migration.py
"""

import asyncio
import json
import os
from sqlalchemy import text, select
from core.database.connection import get_db
from core.database.models import Market


async def fix_clob_token_ids():
    """Fix all malformed clob_token_ids in the markets table"""

    print("🔧 Starting clob_token_ids migration...")
    print("This will fix triple-encoded JSON strings to proper JSONB arrays")

    fixed_count = 0
    error_count = 0

    try:
        async with get_db() as db:
            # Get all markets with clob_token_ids
            result = await db.execute(
                select(Market.id, Market.clob_token_ids)
                .where(Market.clob_token_ids.isnot(None))
            )

            markets = result.all()

            print(f"📊 Found {len(markets)} markets with clob_token_ids to check")

            for market_id, clob_token_ids_raw in markets:
                try:
                    fixed_value = None

                    # Check if it's a malformed string
                    if isinstance(clob_token_ids_raw, str):
                        # Try to detect and fix triple encoding
                        if clob_token_ids_raw.startswith('"[') and clob_token_ids_raw.endswith(']"'):
                            # This looks like triple encoding: "\"[...]\""
                            try:
                                # First decode: remove outer quotes
                                first_decode = json.loads(clob_token_ids_raw)
                                if isinstance(first_decode, str) and first_decode.startswith('['):
                                    # Second decode: parse the array string
                                    second_decode = json.loads(first_decode)
                                    if isinstance(second_decode, list):
                                        # Success! We have a proper array
                                        fixed_value = second_decode
                                        print(f"✅ Fixed market {market_id[:8]}...: {clob_token_ids_raw[:50]}... → {fixed_value}")
                                    else:
                                        print(f"⚠️ Unexpected second decode type for market {market_id[:8]}...: {type(second_decode)}")
                                else:
                                    print(f"⚠️ Unexpected first decode for market {market_id[:8]}...: {first_decode[:50]}...")
                            except json.JSONDecodeError as e:
                                print(f"❌ JSON decode failed for market {market_id[:8]}...: {e}")
                                error_count += 1
                                continue
                        elif not clob_token_ids_raw.startswith('['):
                            # Single encoded string, try to decode
                            try:
                                decoded = json.loads(clob_token_ids_raw)
                                if isinstance(decoded, list):
                                    fixed_value = decoded
                                    print(f"✅ Fixed single-encoded market {market_id[:8]}...: {clob_token_ids_raw[:30]}... → {fixed_value}")
                            except json.JSONDecodeError:
                                print(f"❌ Could not decode market {market_id[:8]}...: {clob_token_ids_raw[:30]}...")
                                error_count += 1
                                continue
                        else:
                            # Already looks like a proper JSON array string
                            try:
                                test_parse = json.loads(clob_token_ids_raw)
                                if isinstance(test_parse, list):
                                    print(f"ℹ️ Market {market_id[:8]}... already properly formatted")
                                    continue
                            except json.JSONDecodeError:
                                print(f"❌ Malformed JSON for market {market_id[:8]}...: {clob_token_ids_raw[:30]}...")
                                error_count += 1
                                continue

                    elif isinstance(clob_token_ids_raw, list):
                        # Already a proper list
                        print(f"ℹ️ Market {market_id[:8]}... already a list: {clob_token_ids_raw}")
                        continue

                    else:
                        print(f"⚠️ Unexpected type for market {market_id[:8]}...: {type(clob_token_ids_raw)}")
                        continue

                    # Apply the fix
                    if fixed_value is not None:
                        await db.execute(
                            text("""
                                UPDATE markets
                                SET clob_token_ids = :fixed_value,
                                    updated_at = now()
                                WHERE id = :market_id
                            """),
                            {
                                'fixed_value': fixed_value,
                                'market_id': market_id
                            }
                        )
                        fixed_count += 1

                        # Commit every 100 fixes
                        if fixed_count % 100 == 0:
                            await db.commit()
                            print(f"💾 Committed {fixed_count} fixes so far...")

            # Final commit
            await db.commit()

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

    print("
✅ Migration completed!"    print(f"📊 Fixed: {fixed_count} markets")
    print(f"❌ Errors: {error_count} markets")
    print(f"📈 Success rate: {(fixed_count / (fixed_count + error_count) * 100):.1f}%" if (fixed_count + error_count) > 0 else "100%")

    return True


async def verify_fix():
    """Verify that the migration worked correctly"""

    print("\n🔍 Verifying migration results...")

    try:
        async with get_db() as db:
            # Check a few samples
            result = await db.execute(
                select(Market.id, Market.clob_token_ids)
                .where(Market.clob_token_ids.isnot(None))
                .limit(5)
            )

            samples = result.all()

            print("📋 Sample results after migration:")
            for market_id, clob_token_ids in samples:
                if isinstance(clob_token_ids, list):
                    print(f"✅ {market_id[:8]}...: {clob_token_ids} (type: list, length: {len(clob_token_ids)})")
                elif isinstance(clob_token_ids, str):
                    try:
                        parsed = json.loads(clob_token_ids)
                        if isinstance(parsed, list):
                            print(f"✅ {market_id[:8]}...: {clob_token_ids} (valid JSON array string)")
                        else:
                            print(f"⚠️ {market_id[:8]}...: {clob_token_ids} (JSON but not array)")
                    except json.JSONDecodeError:
                        print(f"❌ {market_id[:8]}...: {clob_token_ids} (invalid JSON)")
                else:
                    print(f"⚠️ {market_id[:8]}...: {clob_token_ids} (type: {type(clob_token_ids)})")

    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

    print("✅ Verification completed")
    return True


async def main():
    """Main migration function"""

    print("🚀 Starting clob_token_ids migration")
    print("=" * 60)

    # Run the migration
    success = await fix_clob_token_ids()

    if success:
        # Verify the results
        await verify_fix()

        print("\n🎉 Migration successful!")
        print("\nNext steps:")
        print("1. Test your trading functionality")
        print("2. Monitor for any remaining JSON parsing errors")
        print("3. The poller will now store data correctly going forward")

    else:
        print("\n❌ Migration failed!")
        print("Please check the errors above and try again")


if __name__ == "__main__":
    # Use environment variables (production or development)
    # For production: will use Railway DATABASE_URL
    # For development: will use .env files

    asyncio.run(main())
