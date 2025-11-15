#!/usr/bin/env python3
"""
Script pour fermer les positions duplicatas
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database.connection import get_db, init_db
from core.database.models import Position, Market
from sqlalchemy import select, func
from core.services.position.crud import close_position
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


async def find_and_close_duplicates(user_id: int = 1):
    """Find and close duplicate positions for the same market"""
    await init_db()

    async with get_db() as db:
        # Get all active positions for user
        positions_query = select(Position).where(
            Position.user_id == user_id,
            Position.status == 'active',
            Position.amount > 0
        ).order_by(Position.created_at.desc())

        result = await db.execute(positions_query)
        positions = result.scalars().all()

        logger.info(f"📊 Found {len(positions)} active positions for user {user_id}")

        # Group positions by market_id
        positions_by_market = {}
        for pos in positions:
            if pos.market_id not in positions_by_market:
                positions_by_market[pos.market_id] = []
            positions_by_market[pos.market_id].append(pos)

        # Find markets with multiple positions
        duplicates_found = []
        for market_id, market_positions in positions_by_market.items():
            if len(market_positions) > 1:
                logger.info(f"⚠️ Market {market_id} has {len(market_positions)} positions:")
                for pos in market_positions:
                    logger.info(f"   - ID {pos.id}: outcome={pos.outcome}, amount={pos.amount}, created={pos.created_at}")

                # Get market info
                market_query = select(Market).where(Market.id == market_id)
                market_result = await db.execute(market_query)
                market = market_result.scalar_one_or_none()

                if market:
                    logger.info(f"   Market: {market.title}")
                    logger.info(f"   Condition ID: {market.condition_id}")
                    logger.info(f"   Outcomes: {market.outcomes}")

                duplicates_found.append((market_id, market_positions))

        if not duplicates_found:
            logger.info("✅ No duplicates found")
            return

        # For each duplicate group, keep the most recent one and close the others
        for market_id, market_positions in duplicates_found:
            # Sort by created_at (most recent first)
            market_positions.sort(key=lambda p: p.created_at, reverse=True)

            # Keep the first (most recent)
            keep_position = market_positions[0]
            logger.info(f"✅ Keeping position {keep_position.id} (most recent)")

            # Close the others
            for pos in market_positions[1:]:
                logger.info(f"🗑️ Closing duplicate position {pos.id} (outcome={pos.outcome}, amount={pos.amount})")

                # Use current_price if available, otherwise entry_price
                exit_price = pos.current_price if pos.current_price else pos.entry_price

                try:
                    await close_position(pos.id, exit_price)
                    logger.info(f"✅ Closed position {pos.id}")
                except Exception as e:
                    logger.error(f"❌ Error closing position {pos.id}: {e}")

        await db.commit()
        logger.info("✅ Duplicate cleanup completed")


async def main():
    """Main function"""
    user_id = 1

    logger.info(f"🔍 Starting duplicate position cleanup for user {user_id}")

    try:
        await find_and_close_duplicates(user_id)
        logger.info("✅ Script completed successfully")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    asyncio.run(main())
