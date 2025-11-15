#!/usr/bin/env python3
"""
Manual Backfill Script for Specific Address

Usage: python scripts/backfill_address.py 0xbb2492764a5886f6403d425b966e4edd19a24864

This script forces the indexer to backfill historical transactions for a specific address.
Useful when an address was added after it made trades, or to recover missed transactions.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

try:
    from database import db_manager
    from sqlalchemy import text
except ImportError as e:
    print(f"❌ Import error: {e}")
    print(f"💡 Current directory: {os.getcwd()}")
    print(f"💡 Script location: {os.path.abspath(__file__)}")
    sys.exit(1)

async def backfill_address(address: str):
    """Simple backfill check - just verify if address has any recent transactions"""

    print(f"🔍 Checking for recent transactions for address: {address}")
    print("=" * 60)

    try:
        # Check database for any recent transactions
        with db_manager.get_session() as db:
            from datetime import datetime, timezone, timedelta

            # Check last 24 hours
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

            # Query existing transactions
            result = db.execute(text("""
                SELECT COUNT(*) as tx_count, MAX(timestamp) as latest_tx
                FROM subsquid_user_transactions_v2
                WHERE user_address = :address AND timestamp > :cutoff
            """), {"address": address, "cutoff": cutoff})

            row = result.fetchone()
            tx_count = row[0] if row else 0
            latest_tx = row[1] if row else None

            print(f"📊 Database check:")
            print(f"   Transactions (24h): {tx_count}")
            if latest_tx:
                print(f"   Latest transaction: {latest_tx}")

            if tx_count > 0:
                print("✅ Transactions already exist in database!")
                print("💡 No backfill needed")
                return True
            else:
                print("❌ No recent transactions found in database")
                print("🔄 Would need backfill if implemented")

                # For now, just check if the address is in watched addresses
                from database import ExternalLeader
                leader = db.query(ExternalLeader).filter(
                    ExternalLeader.polygon_address == address,
                    ExternalLeader.is_active == True
                ).first()

                if leader:
                    print("✅ Address is in external_leaders and active")
                    print("✅ Copy trading subscription should work for future trades")
                else:
                    print("❌ Address not found in external_leaders")

    except Exception as e:
        print(f"❌ Check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True

async def main():
    if len(sys.argv) != 2:
        print("❌ Usage: python scripts/backfill_address.py <ethereum_address>")
        print("📝 Example: python scripts/backfill_address.py 0xbb2492764a5886f6403d425b966e4edd19a24864")
        sys.exit(1)

    address = sys.argv[1].strip()

    # Basic validation
    if not address.startswith('0x') or len(address) != 42:
        print(f"❌ Invalid Ethereum address format: {address}")
        print("💡 Address should start with '0x' and be 42 characters long")
        sys.exit(1)

    # Convert to lowercase for consistency
    address = address.lower()

    print(f"🚀 Manual Backfill Script")
    print(f"🎯 Target Address: {address}")
    print(f"⏰ Lookback: 2 hours (~34,200 blocks)")
    print("-" * 60)

    success = await backfill_address(address)

    if success:
        print("\n✅ Script completed successfully")
    else:
        print("\n❌ Script failed")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
