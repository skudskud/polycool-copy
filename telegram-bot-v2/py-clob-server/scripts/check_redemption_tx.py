#!/usr/bin/env python3
"""
Script to check status of a redemption transaction and recover if needed
Usage: python scripts/check_redemption_tx.py <tx_hash>
"""

import sys
import asyncio
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SessionLocal, ResolvedPosition
from core.services.redemption_service import get_redemption_service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def check_transaction(tx_hash: str):
    """Check a specific redemption transaction"""
    try:
        with SessionLocal() as session:
            # Find position with this tx_hash
            position = session.query(ResolvedPosition).filter(
                ResolvedPosition.redemption_tx_hash == tx_hash
            ).first()

            if not position:
                logger.error(f"❌ No position found with tx_hash: {tx_hash}")
                logger.info("💡 Searching for positions stuck in PROCESSING...")

                # Check for stuck positions
                stuck = session.query(ResolvedPosition).filter(
                    ResolvedPosition.status == 'PROCESSING'
                ).all()

                if stuck:
                    logger.info(f"Found {len(stuck)} positions stuck in PROCESSING:")
                    for pos in stuck:
                        logger.info(f"  - Position ID: {pos.id}, Market: {pos.market_title[:50]}..., Tx: {pos.redemption_tx_hash or 'None'}")
                else:
                    logger.info("No stuck positions found.")
                return

            logger.info(f"✅ Found position ID: {position.id}")
            logger.info(f"   Market: {position.market_title}")
            logger.info(f"   Status: {position.status}")
            logger.info(f"   Tx Hash: {position.redemption_tx_hash}")
            logger.info(f"   Processing started: {position.processing_started_at}")
            logger.info(f"   Attempt count: {position.redemption_attempt_count}")

            # Check transaction status
            redemption_service = get_redemption_service()

            if position.status == 'PROCESSING':
                logger.info(f"🔍 Checking transaction status on blockchain...")
                check_result = await redemption_service._check_existing_transaction(position)

                if check_result:
                    if check_result.get('already_completed'):
                        logger.info(f"✅ Transaction succeeded! Recovering...")
                        receipt = check_result['receipt']

                        position.status = 'REDEEMED'
                        position.redemption_block_number = receipt.blockNumber
                        position.redemption_gas_used = receipt.gasUsed
                        position.redemption_gas_price = receipt.effectiveGasPrice
                        from datetime import datetime
                        position.redeemed_at = datetime.utcnow()
                        if hasattr(position, 'last_redemption_error'):
                            position.last_redemption_error = None
                        session.commit()

                        logger.info(f"🎉 Position recovered! Status updated to REDEEMED")
                        logger.info(f"   Block: {receipt.blockNumber}")
                        logger.info(f"   Gas used: {receipt.gasUsed}")
                    elif check_result.get('already_failed'):
                        logger.warning(f"⚠️ Transaction failed on-chain")
                        logger.info(f"   Marking as PENDING for retry...")
                        position.status = 'PENDING'
                        if hasattr(position, 'last_redemption_error'):
                            position.last_redemption_error = check_result.get('error', 'Transaction reverted')
                        session.commit()
                        logger.info(f"✅ Status updated to PENDING - can retry now")
                    elif check_result.get('pending'):
                        logger.info(f"⏳ Transaction still pending on blockchain")
                        logger.info(f"   Will check again later...")
                else:
                    logger.warning(f"⚠️ Could not check transaction status")
            elif position.status == 'REDEEMED':
                logger.info(f"✅ Position already redeemed!")
            elif position.status == 'PENDING':
                logger.info(f"⏳ Position is PENDING - ready for redemption")

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)


async def cleanup_stuck():
    """Clean up all stuck transactions"""
    logger.info("🧹 Running cleanup for stuck transactions...")
    redemption_service = get_redemption_service()
    result = await redemption_service.cleanup_stuck_transactions(max_age_minutes=10)

    if result.get('success'):
        stats = result.get('stats', {})
        logger.info(f"✅ Cleanup complete:")
        logger.info(f"   Checked: {stats.get('checked', 0)}")
        logger.info(f"   Recovered: {stats.get('recovered', 0)}")
        logger.info(f"   Failed: {stats.get('failed', 0)}")
        logger.info(f"   Still pending: {stats.get('pending', 0)}")
        logger.info(f"   Errors: {stats.get('errors', 0)}")
    else:
        logger.error(f"❌ Cleanup failed: {result.get('error')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.info("Usage: python scripts/check_redemption_tx.py <tx_hash>")
        logger.info("   Or: python scripts/check_redemption_tx.py --cleanup")
        sys.exit(1)

    tx_hash = sys.argv[1]

    if tx_hash == "--cleanup":
        asyncio.run(cleanup_stuck())
    else:
        asyncio.run(check_transaction(tx_hash))
