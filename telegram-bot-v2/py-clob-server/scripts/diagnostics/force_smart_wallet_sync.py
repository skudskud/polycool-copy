#!/usr/bin/env python3
"""
Force Smart Wallet Sync
Manually trigger sync to test if the code works
"""

import asyncio
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.services.smart_wallet_monitor_service import SmartWalletMonitorService
from core.persistence.smart_wallet_repository import SmartWalletRepository
from core.persistence.smart_wallet_trade_repository import SmartWalletTradeRepository
from core.persistence import get_db_session
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def force_sync():
    """Force a manual sync to test the smart wallet monitor"""

    try:
        logger.info("🚀 Starting manual smart wallet sync...")

        # Initialize repositories
        db_session_instance = get_db_session()
        smart_wallet_repo = SmartWalletRepository(db_session_instance)
        smart_trade_repo = SmartWalletTradeRepository(db_session_instance)

        # Initialize monitor service
        smart_monitor = SmartWalletMonitorService(
            smart_wallet_repo,
            smart_trade_repo,
            "https://data-api.polymarket.com"
        )

        # Load wallets from CSV
        csv_path = "insider_smart/curated active smart traders  - Feuille 1.csv"
        logger.info(f"📊 Loading wallets from {csv_path}...")
        await smart_monitor.sync_smart_wallets_from_csv(csv_path)

        # Get wallet count
        wallets = smart_wallet_repo.get_all_wallets()
        logger.info(f"👥 Found {len(wallets)} wallets to sync")

        # Force sync
        logger.info("🔄 Forcing sync_all_wallets()...")
        await smart_monitor.sync_all_wallets()

        logger.info("✅ Manual sync complete!")

    except Exception as e:
        logger.error(f"❌ Error during manual sync: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(force_sync())
