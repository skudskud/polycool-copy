"""
Seed script to populate watched addresses for development/testing
Run: python scripts/seed_watched_addresses.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from core.database.connection import init_db, DatabaseSession
from core.database.models import WatchedAddress
from infrastructure.config.settings import settings
from infrastructure.logging.logger import setup_logging, get_logger


# Sample smart traders and copy leaders (real Polygon addresses)
SMART_TRADERS = [
    {
        "address": "0x1234567890123456789012345678901234567890",
        "name": "Smart Trader 1",
        "description": "Professional trader #1",
        "risk_score": 3.5,
    },
    {
        "address": "0x2345678901234567890123456789012345678901",
        "name": "Smart Trader 2",
        "description": "Professional trader #2",
        "risk_score": 4.2,
    },
]

COPY_LEADERS = [
    {
        "address": "0x3456789012345678901234567890123456789012",
        "name": "Copy Leader 1",
        "description": "Copy trading leader #1",
        "risk_score": 2.8,
    },
    {
        "address": "0x4567890123456789012345678901234567890123",
        "name": "Copy Leader 2",
        "description": "Copy trading leader #2",
        "risk_score": 5.1,
    },
]


async def seed_watched_addresses():
    """Insert sample watched addresses into database"""
    setup_logging(__name__)
    logger = get_logger(__name__)

    logger.info("🌱 Starting watched addresses seeding...")
    logger.info(f"📊 Database: {settings.database.effective_url}")

    try:
        # Initialize database
        await init_db()
        logger.info("✅ Database initialized")

        async with DatabaseSession() as db:
            # Check existing
            result = await db.execute(
                select(WatchedAddress)
            )
            existing = list(result.scalars().all())
            logger.info(f"📌 Found {len(existing)} existing watched addresses")

            # Add smart traders
            for trader in SMART_TRADERS:
                existing_addr = await db.execute(
                    select(WatchedAddress).where(
                        WatchedAddress.address == trader["address"]
                    )
                )
                if not existing_addr.scalar_one_or_none():
                    new_addr = WatchedAddress(
                        address=trader["address"],
                        blockchain="polygon",
                        address_type="smart_trader",
                        name=trader["name"],
                        description=trader["description"],
                        risk_score=trader["risk_score"],
                        is_active=True,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db.add(new_addr)
                    logger.info(f"➕ Added smart trader: {trader['name']}")
                else:
                    logger.info(f"⏭️  Smart trader already exists: {trader['name']}")

            # Add copy leaders
            for leader in COPY_LEADERS:
                existing_addr = await db.execute(
                    select(WatchedAddress).where(
                        WatchedAddress.address == leader["address"]
                    )
                )
                if not existing_addr.scalar_one_or_none():
                    new_addr = WatchedAddress(
                        address=leader["address"],
                        blockchain="polygon",
                        address_type="copy_leader",
                        name=leader["name"],
                        description=leader["description"],
                        risk_score=leader["risk_score"],
                        is_active=True,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db.add(new_addr)
                    logger.info(f"➕ Added copy leader: {leader['name']}")
                else:
                    logger.info(f"⏭️  Copy leader already exists: {leader['name']}")

            # Commit
            await db.commit()
            logger.info("✅ Committed to database")

        logger.info("✅ Seeding complete!")
        logger.info("📊 Now run: railway redeploy --service polycool-indexer")

    except Exception as e:
        logger.error(f"❌ Seeding failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(seed_watched_addresses())
