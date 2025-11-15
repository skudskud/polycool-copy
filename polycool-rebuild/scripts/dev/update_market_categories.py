"""
Script to update market categories by fetching tags from Polymarket API
"""
import asyncio
from typing import List, Dict
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller, extract_category
from core.database.connection import get_db
from sqlalchemy import text

logger = get_logger(__name__)


class CategoryUpdater(BaseGammaAPIPoller):
    """Updates market categories by fetching tags from API"""

    def __init__(self):
        super().__init__(poll_interval=0)

    async def update_all_categories(self) -> int:
        """Update categories for all markets in DB that don't have one"""
        logger.info("🏷️ Starting category update...")

        # Get markets without category
        markets_to_update = await self._get_markets_without_category()
        logger.info(f"📊 Found {len(markets_to_update)} markets without category")

        updated_count = 0

        for i, (market_id, title) in enumerate(markets_to_update):
            try:
                # Fetch tags for this market
                tags = await self._fetch_api(f"/markets/{market_id}/tags")

                if tags and isinstance(tags, list):
                    # Create market dict for category extraction
                    market_data = {'tags': tags}
                    category = extract_category(market_data)

                    if category:
                        # Update DB
                        await self._update_market_category(market_id, category)
                        updated_count += 1

                        if updated_count % 50 == 0:
                            logger.info(f"✅ Updated {updated_count}/{len(markets_to_update)} markets")

                # Progress log
                if i % 100 == 0:
                    logger.info(f"📦 Processed {i}/{len(markets_to_update)} markets")

            except Exception as e:
                logger.debug(f"Failed to update category for market {market_id}: {e}")

            # Rate limiting
            await asyncio.sleep(0.05)

        logger.info(f"✅ Category update completed: {updated_count} markets updated")
        return updated_count

    async def _get_markets_without_category(self) -> List[tuple]:
        """Get markets that don't have a category"""
        async with get_db() as db:
            result = await db.execute(text("""
                SELECT id, title
                FROM markets
                WHERE (category IS NULL OR category = '')
                AND id IS NOT NULL
                ORDER BY volume DESC NULLS LAST
            """))
            return [(row[0], row[1]) for row in result.fetchall()]

    async def _update_market_category(self, market_id: str, category: str) -> None:
        """Update category for a market"""
        async with get_db() as db:
            await db.execute(text("""
                UPDATE markets
                SET category = :category, updated_at = now()
                WHERE id = :market_id
            """), {'market_id': market_id, 'category': category})


async def main():
    """Main function"""
    # Initialize database
    from core.database.connection import init_db
    await init_db()

    updater = CategoryUpdater()
    await updater.update_all_categories()


if __name__ == "__main__":
    asyncio.run(main())
