"""
Fast enrichment using 10k batches via direct SQL.
No Python-side computation - all done in PostgreSQL.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv
import asyncpg

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()


async def fast_enrich():
    """Enrich 4.4M rows using 10k batches"""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("❌ DATABASE_URL not set")
        return

    logger.info("🔌 Connecting...")
    conn = await asyncpg.connect(database_url)

    try:
        # Get total count
        count_result = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM subsquid_user_transactions WHERE market_id IS NULL AND position_id IS NOT NULL"
        )
        total = count_result["cnt"]
        logger.info(f"📊 {total:,} rows to enrich")

        if total == 0:
            logger.info("✅ Already enriched!")
            return

        total_updated = 0
        batch_num = 0

        while total > 0:
            batch_num += 1

            # Run 10k batch
            update_query = """
            WITH enriched AS (
              SELECT
                tx_id,
                CAST(CAST(position_id AS numeric) / 2 AS text) as new_market_id,
                CAST(CAST(position_id AS numeric) % 2 AS INTEGER) as new_outcome
              FROM subsquid_user_transactions
              WHERE market_id IS NULL
                AND position_id IS NOT NULL
              ORDER BY created_at ASC
              LIMIT 10000
            )
            UPDATE subsquid_user_transactions t
            SET
              market_id = e.new_market_id,
              outcome = e.new_outcome
            FROM enriched e
            WHERE t.tx_id = e.tx_id;
            """

            result = await conn.execute(update_query)
            rows_updated = int(result.split()[-1]) if result else 0

            total_updated += rows_updated
            pct = (total_updated / (total_updated + total)) * 100 if (total_updated + total) > 0 else 0

            logger.info(f"✅ Batch {batch_num}: +{rows_updated:,} (total: {total_updated:,} - {pct:.1f}%)")

            if rows_updated < 10000:
                logger.info("🎉 Done!")
                break

            # Refresh remaining count
            count_result = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM subsquid_user_transactions WHERE market_id IS NULL AND position_id IS NOT NULL"
            )
            total = count_result["cnt"]

            await asyncio.sleep(0.5)

        logger.info(f"✨ Enrichment complete: {total_updated:,} rows updated")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(fast_enrich())
