"""
Batch enrich subsquid_user_transactions by decoding position_id into market_id and outcome.

TokenID encoding in CLOB:
  - position_id = marketId * 2 + outcome
  - market_id = position_id // 2
  - outcome = position_id % 2

This script processes 4.4M transactions in batches to avoid DB overload.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv
import asyncpg

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

load_dotenv()


async def enrich_transactions_batch(conn: asyncpg.Connection, batch_size: int = 10000) -> int:
    """
    Enrich subsquid_user_transactions by decoding position_id.
    
    Processes in batches to avoid query timeouts.
    
    Returns: Total number of rows updated
    """
    
    # Count rows needing enrichment
    count_query = """
    SELECT COUNT(*) as cnt
    FROM subsquid_user_transactions
    WHERE market_id IS NULL
      AND position_id IS NOT NULL
    """
    
    count_result = await conn.fetchrow(count_query)
    rows_to_enrich = count_result["cnt"]
    
    if rows_to_enrich == 0:
        logger.info("✅ No transactions to enrich")
        return 0
    
    logger.info(f"📊 Found {rows_to_enrich:,} transactions to enrich")
    
    total_updated = 0
    batch_num = 0
    
    while True:
        batch_num += 1
        
        # Fetch batch of IDs to update
        fetch_query = """
        SELECT tx_id, position_id
        FROM subsquid_user_transactions
        WHERE market_id IS NULL
          AND position_id IS NOT NULL
        ORDER BY created_at ASC
        LIMIT $1
        """
        
        rows = await conn.fetch(fetch_query, batch_size)
        
        if not rows:
            break
        
        logger.info(f"🔄 [Batch {batch_num}] Processing {len(rows):,} rows...")
        
        # Prepare batch data
        updates = []
        for row in rows:
            tx_id = row['tx_id']
            position_id_str = row['position_id']
            
            try:
                # Decode position_id (256-bit number)
                position_id = int(position_id_str)
                market_id = position_id // 2
                outcome = position_id % 2
                
                updates.append({
                    'tx_id': tx_id,
                    'market_id': str(market_id),  # Keep as string for consistency
                    'outcome': outcome
                })
            except (ValueError, OverflowError) as e:
                logger.warning(f"⚠️  Failed to decode position_id for {tx_id}: {e}")
                continue
        
        if not updates:
            logger.warning(f"⚠️  [Batch {batch_num}] No valid rows to update after decoding")
            continue
        
        # Batch update
        update_query = """
        UPDATE subsquid_user_transactions
        SET market_id = $2, outcome = $3
        WHERE tx_id = $1
        """
        
        async with conn.transaction():
            for update in updates:
                await conn.execute(
                    update_query,
                    update['tx_id'],
                    update['market_id'],
                    update['outcome']
                )
        
        batch_updated = len(updates)
        total_updated += batch_updated
        progress_pct = (total_updated / rows_to_enrich) * 100
        
        logger.info(f"✅ [Batch {batch_num}] Updated {batch_updated:,} rows (total: {total_updated:,}/{rows_to_enrich:,} - {progress_pct:.1f}%)")
        
        # Small delay to avoid overwhelming DB
        await asyncio.sleep(0.5)
    
    logger.info(f"🎉 Enrichment completed: {total_updated:,} transactions updated")
    return total_updated


async def main():
    """Main entry point"""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        logger.error("❌ DATABASE_URL not set in environment")
        return
    
    logger.info(f"🔌 Connecting to database...")
    
    try:
        conn = await asyncpg.connect(database_url)
        logger.info("✅ Connected to database")
        
        # Run enrichment
        total = await enrich_transactions_batch(conn, batch_size=10000)
        
        logger.info(f"✨ Final result: {total:,} rows enriched")
        
    except Exception as e:
        logger.error(f"❌ Error during enrichment: {e}", exc_info=True)
    finally:
        if conn:
            await conn.close()
            logger.info("✅ Database connection closed")


if __name__ == "__main__":
    asyncio.run(main())
