"""
Build position_id_mapping table by computing positionIds for all markets.

This script:
1. Fetches all active markets from Polymarket Gamma API
2. Computes the ERC1155 positionIds using CTF math:
   - conditionId = hash(oracle, questionId, 2)
   - collectionId = hash(0x0, conditionId, indexSet)
   - positionId = hash(USDC, collectionId)
3. Inserts into position_id_mapping for later enrichment
"""

import asyncio
import hashlib
import logging
from typing import Optional
import httpx
from eth_utils import keccak
import asyncpg

logger = logging.getLogger(__name__)

# Hardcoded values for Polymarket
UMA_ORACLE = "0x60C4Cffbf7c9A7fd6B2dCD481D8f6fF8fAa8F8ff"  # UMA Oracle adapter V2 on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon
PARENT_COLLECTION_ID = "0x0000000000000000000000000000000000000000000000000000000000000000"

# Indexsets for binary outcomes
YES_INDEX_SET = 1  # 0b01
NO_INDEX_SET = 2   # 0b10


def compute_condition_id(oracle: str, question_id: bytes, outcome_slots: int = 2) -> bytes:
    """Compute conditionId = keccak256(oracle, questionId, outcomeSlotCount)"""
    # Remove '0x' prefix and pad to 20 bytes (address)
    oracle_bytes = bytes.fromhex(oracle.replace("0x", "").rjust(40, "0"))
    question_bytes = bytes.fromhex(question_id.replace("0x", "").rjust(64, "0"))
    outcome_bytes = outcome_slots.to_bytes(32, byteorder="big")

    combined = oracle_bytes + question_bytes + outcome_bytes
    return keccak(combined)


def compute_collection_id(parent_collection_id: bytes, condition_id: bytes, index_set: int) -> bytes:
    """Compute collectionId = keccak256(parentCollectionId, conditionId, indexSet)"""
    parent_bytes = bytes.fromhex(parent_collection_id.replace("0x", "").rjust(64, "0"))
    index_set_bytes = index_set.to_bytes(32, byteorder="big")

    combined = parent_bytes + condition_id + index_set_bytes
    return keccak(combined)


def compute_position_id(collateral: str, collection_id: bytes) -> bytes:
    """Compute positionId = keccak256(collateral, collectionId)"""
    collateral_bytes = bytes.fromhex(collateral.replace("0x", "").rjust(40, "0"))

    combined = collateral_bytes + collection_id
    return keccak(combined)


async def fetch_polymarket_markets(limit: int = 100) -> list[dict]:
    """Fetch active markets from Polymarket Gamma API"""
    logger.info(f"Fetching markets from Polymarket API (limit={limit})...")

    async with httpx.AsyncClient(timeout=30) as client:
        markets = []
        offset = 0

        while True:
            url = "https://gamma-api.polymarket.com/markets"
            params = {
                "limit": limit,
                "offset": offset,
                "active": True,
                "closed": False,
            }

            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                batch = resp.json()

                if not batch:
                    break

                markets.extend(batch)
                logger.info(f"Fetched {len(markets)} markets so far...")

                if len(batch) < limit:
                    break

                offset += limit
            except Exception as e:
                logger.error(f"Error fetching markets: {e}")
                break

        logger.info(f"Total markets fetched: {len(markets)}")
        return markets


async def build_position_mappings(markets: list[dict]) -> list[dict]:
    """Build position_id → (market_id, outcome) mappings"""
    mappings = []

    for market in markets:
        market_id = market.get("id")
        question_id = market.get("question_id")

        if not market_id or not question_id:
            logger.warning(f"Skipping market with missing data: {market_id}")
            continue

        try:
            # Compute base conditionId
            condition_id = compute_condition_id(UMA_ORACLE, question_id)

            # For each outcome (NO=0, YES=1)
            for outcome in [0, 1]:
                index_set = YES_INDEX_SET if outcome == 1 else NO_INDEX_SET

                # Compute collectionId
                collection_id = compute_collection_id(PARENT_COLLECTION_ID, condition_id, index_set)

                # Compute positionId
                position_id = compute_position_id(USDC_ADDRESS, collection_id)

                mappings.append({
                    "position_id": "0x" + position_id.hex(),
                    "market_id": market_id,
                    "outcome": outcome,
                    "oracle_address": UMA_ORACLE,
                    "question_id": question_id,
                    "collateral_address": USDC_ADDRESS,
                })

                logger.debug(f"Market {market_id}, outcome {outcome}: positionId={position_id.hex()[:16]}...")

        except Exception as e:
            logger.error(f"Error computing mappings for market {market_id}: {e}")
            continue

    logger.info(f"Built {len(mappings)} position_id mappings")
    return mappings


async def insert_mappings_to_db(conn: asyncpg.Connection, mappings: list[dict]) -> int:
    """Insert mappings into position_id_mapping table, upserting on conflict"""

    # Prepare batch insert with ON CONFLICT
    query = """
    INSERT INTO position_id_mapping (
        position_id, market_id, outcome, oracle_address, question_id, collateral_address
    ) VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (position_id) DO UPDATE SET
        market_id = EXCLUDED.market_id,
        outcome = EXCLUDED.outcome,
        updated_at = NOW()
    """

    rows_inserted = 0
    for mapping in mappings:
        try:
            await conn.execute(
                query,
                mapping["position_id"],
                mapping["market_id"],
                mapping["outcome"],
                mapping["oracle_address"],
                mapping["question_id"],
                mapping["collateral_address"],
            )
            rows_inserted += 1
        except Exception as e:
            logger.error(f"Error inserting mapping {mapping['position_id']}: {e}")

    logger.info(f"Inserted {rows_inserted}/{len(mappings)} mappings to DB")
    return rows_inserted


async def main():
    """Main entry point"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(asctime)s - %(levelname)s - %(message)s"
    )

    # Get database URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set!")
        return

    logger.info("Starting position_id mapping builder...")

    try:
        # Connect to database
        conn = await asyncpg.connect(database_url)
        logger.info("✅ Connected to database")

        # Fetch markets
        markets = await fetch_polymarket_markets(limit=100)

        if not markets:
            logger.error("No markets fetched!")
            return

        # Build mappings
        mappings = await build_position_mappings(markets)

        if not mappings:
            logger.error("No mappings built!")
            return

        # Insert to database
        rows_inserted = await insert_mappings_to_db(conn, mappings)

        # Update job status
        await conn.execute(
            """
            UPDATE enrichment_job_status
            SET status = 'completed', last_run_at = NOW(), rows_processed = $1
            WHERE job_name = 'position_id_mapping_builder'
            """,
            rows_inserted
        )

        logger.info("✅ Position ID mapping builder completed successfully!")

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        # Update job status with error
        try:
            await conn.execute(
                """
                UPDATE enrichment_job_status
                SET status = 'failed', error_message = $1, updated_at = NOW()
                WHERE job_name = 'position_id_mapping_builder'
                """,
                str(e)
            )
        except:
            pass
    finally:
        if conn:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
