#!/usr/bin/env python3
"""
Force Smart Wallet Sync
Script pour forcer une synchronisation manuelle des smart wallets
Utile après un déploiement ou si le scheduler a des problèmes
"""

import asyncio
import sys
import os
import logging
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.persistence import get_db_session
from core.persistence.smart_wallet_repository import SmartWalletRepository
from core.persistence.smart_wallet_trade_repository import SmartWalletTradeRepository
from core.services.smart_wallet_monitor_service import SmartWalletMonitorService

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def force_sync(since_minutes: int = 10):
    """Force a manual sync of smart wallet trades"""

    print("\n" + "="*80)
    print("🔄 FORCE SYNC SMART WALLETS")
    print("="*80 + "\n")

    try:
        # Initialize database and repositories
        logger.info("📊 Initializing database connection...")
        db_session = get_db_session()

        smart_wallet_repo = SmartWalletRepository(db_session)
        smart_trade_repo = SmartWalletTradeRepository(db_session)

        # Initialize service
        logger.info("📊 Initializing smart wallet monitor service...")
        smart_monitor = SmartWalletMonitorService(
            smart_wallet_repo,
            smart_trade_repo,
            "https://data-api.polymarket.com"
        )

        # Check current state
        total_trades_before = smart_trade_repo.count_trades()
        first_time_before = smart_trade_repo.count_first_time_trades()

        logger.info(f"📊 Current database state:")
        logger.info(f"   Total trades: {total_trades_before:,}")
        logger.info(f"   First-time trades: {first_time_before:,}")

        # Execute sync
        start_time = datetime.now(timezone.utc)
        logger.info(f"\n🔄 Starting manual sync (looking back {since_minutes} minutes)...")
        logger.info(f"   Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

        await smart_monitor.sync_all_wallets(since_minutes=since_minutes)

        # Check results
        total_trades_after = smart_trade_repo.count_trades()
        first_time_after = smart_trade_repo.count_first_time_trades()

        new_trades = total_trades_after - total_trades_before
        new_first_time = first_time_after - first_time_before

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        print("\n" + "="*80)
        print("✅ SYNC COMPLETE")
        print("="*80)
        print(f"\nBefore sync:")
        print(f"  Total trades:      {total_trades_before:,}")
        print(f"  First-time trades: {first_time_before:,}")
        print(f"\nAfter sync:")
        print(f"  Total trades:      {total_trades_after:,} (+{new_trades})")
        print(f"  First-time trades: {first_time_after:,} (+{new_first_time})")
        print(f"\nDuration: {duration:.1f} seconds")
        print(f"Completed at: {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

        if new_trades == 0:
            print("ℹ️  No new trades found in the last {} minutes".format(since_minutes))
            print("   This is normal if:")
            print("   - The scheduler is working correctly")
            print("   - Smart wallets haven't traded recently")
            print("   - You're running this shortly after the last scheduled sync\n")
        else:
            print(f"✅ Successfully added {new_trades} new trades ({new_first_time} first-time)\n")

        # Close HTTP client
        await smart_monitor.close()

        return 0

    except Exception as e:
        logger.error(f"\n❌ Error during force sync: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Force a manual sync of smart wallet trades')
    parser.add_argument(
        '--since-minutes',
        type=int,
        default=10,
        help='Number of minutes to look back for trades (default: 10)'
    )
    parser.add_argument(
        '--since-hours',
        type=int,
        help='Number of hours to look back (shortcut for large backfills)'
    )

    args = parser.parse_args()

    # Calculate since_minutes
    if args.since_hours:
        since_minutes = args.since_hours * 60
    else:
        since_minutes = args.since_minutes

    # Run async sync
    exit_code = asyncio.run(force_sync(since_minutes=since_minutes))
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
