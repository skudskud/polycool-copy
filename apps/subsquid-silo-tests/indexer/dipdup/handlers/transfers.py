"""
DipDup Handlers for Conditional Tokens Transfer Events
Indexes fills and user transactions on Polygon.

Market ID format: NUMERIC (248905, not 0x...)
Token ID structure: market_id * 2 + outcome (0=NO, 1=YES)
"""

import logging
from typing import Optional
from datetime import datetime, timezone

from dipdup import Context
from dipdup.models import Block, Transaction, Log
import asyncpg

logger = logging.getLogger(__name__)

# Contract addresses
CONDITIONAL_TOKENS = "0xd5524179cb7ae012f5b642c1d6d700a289d07fb3"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class TransferEvent:
    """Parse Transfer event (ERC1155 single transfer)"""

    @staticmethod
    def parse(log: Log) -> Optional[dict]:
        """
        Transfer event signature:
        Transfer(indexed address operator, indexed address from, indexed address to, uint256 id, uint256 value)

        Returns:
            Dict with operator, from, to, token_id, amount
        """
        try:
            if len(log.topics) < 4 or len(log.data) < 64:
                logger.warning(f"⚠️ Invalid Transfer event structure: topics={len(log.topics)}, data len={len(log.data)}")
                return None

            # Topics: [signature, operator, from, to]
            # Remove padding: take last 40 hex chars (20 bytes)
            operator = f"0x{log.topics[1][-40:]}"
            from_addr = f"0x{log.topics[2][-40:]}"
            to_addr = f"0x{log.topics[3][-40:]}"

            # Data: token_id (32 bytes), value (32 bytes)
            token_id = int(log.data[0:66], 16)
            amount = int(log.data[66:130], 16)

            return {
                "operator": operator,
                "from": from_addr,
                "to": to_addr,
                "token_id": token_id,
                "amount": amount,
            }
        except Exception as e:
            logger.warning(f"❌ Failed to parse Transfer event: {e}")
            return None


class TransferBatchEvent:
    """Parse TransferBatch event (ERC1155 batch transfer)"""

    @staticmethod
    def parse(log: Log) -> Optional[dict]:
        """
        TransferBatch event signature:
        TransferBatch(indexed address operator, indexed address from, indexed address to, uint256[] ids, uint256[] values)
        """
        try:
            if len(log.topics) < 4:
                logger.warning(f"⚠️ Invalid TransferBatch event structure: topics={len(log.topics)}")
                return None

            # Topics: [signature, operator, from, to]
            operator = f"0x{log.topics[1][-40:]}"
            from_addr = f"0x{log.topics[2][-40:]}"
            to_addr = f"0x{log.topics[3][-40:]}"

            # Data is ABI-encoded array offsets and values
            # For now, track batch without full decoding
            return {
                "operator": operator,
                "from": from_addr,
                "to": to_addr,
                "is_batch": True,
            }
        except Exception as e:
            logger.warning(f"❌ Failed to parse TransferBatch event: {e}")
            return None


async def on_transfer(
    ctx: Context,
    log: Log,
    block: Block,
    tx: Transaction,
) -> None:
    """
    Handler for Transfer events (single token transfer).

    Strategy:
    - Extract market_id from token_id using bit shift
    - Track BUY (from=0x0): user acquiring tokens
    - Track SELL (to!=0x0, from!=0x0): user selling tokens
    - Ignore burns (transfer to 0x0) per user requirements
    """
    try:
        parsed = TransferEvent.parse(log)
        if not parsed:
            return

        # Extract market_id and outcome from token_id
        token_id = parsed["token_id"]
        market_id_numeric = token_id >> 1  # Shift right = divide by 2
        outcome = token_id & 0x1  # Bit 0: 0=NO, 1=YES
        market_id_str = str(market_id_numeric)  # Store as numeric string

        from_addr = parsed["from"]
        to_addr = parsed["to"]
        amount = parsed["amount"]

        logger.debug(
            f"📦 Transfer: token_id={token_id}, market_id={market_id_str}, "
            f"outcome={outcome}, amount={amount}, from={from_addr[:8]}..., to={to_addr[:8]}..."
        )

        # Determine transaction type
        tx_type = None
        user_address = None

        # Type 1: BUY (mint from zero address)
        if from_addr.lower() == ZERO_ADDRESS:
            tx_type = "BUY"
            user_address = to_addr
            logger.debug(f"✅ BUY detected: {user_address[:8]}... acquiring {amount} tokens")

        # Type 2: SELL (transfer between non-zero addresses)
        elif to_addr.lower() != ZERO_ADDRESS:
            tx_type = "SELL"
            user_address = from_addr
            logger.debug(f"✅ SELL detected: {user_address[:8]}... selling {amount} tokens")

        # Type 3: BURN (transfer to zero address) - IGNORED per user requirement
        else:
            logger.debug(f"⏭️ BURN ignored: {from_addr[:8]}... → 0x0...")
            return

        # Get database connection
        db: asyncpg.Pool = ctx.get_database()
        timestamp = datetime.fromtimestamp(block.timestamp, tz=timezone.utc)

        # Insert transaction
        tx_id = f"{tx.hash}_{log.index}"
        await insert_user_transaction(
            db=db,
            tx_id=tx_id,
            user_address=user_address,
            market_id=market_id_str,
            outcome=outcome,
            tx_type=tx_type,
            amount=amount,
            price=None,  # Will be enriched later (Option C)
            tx_hash=tx.hash,
            block_number=block.number,
            timestamp=timestamp,
        )

        # Publish to Redis (non-blocking)
        try:
            # Import here to avoid circular dependencies
            import sys
            import os
            # Add parent directory to path for imports
            indexer_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if indexer_dir not in sys.path:
                sys.path.insert(0, indexer_dir)

            from src.redis.publisher import get_redis_publisher

            publisher = await get_redis_publisher()

            # Publish to market-level channel
            await publisher.publish_trade(
                market_id=market_id_str,
                tx_id=tx_id,
                outcome=outcome,
                tx_type=tx_type,
                amount=float(amount),
                price=None,
                tx_hash=tx.hash,
                timestamp=timestamp,
            )

            # Publish to wallet-level channel (for copy trading)
            await publisher.publish_copy_trade(
                user_address=user_address,
                market_id=market_id_str,
                token_id=token_id,
                outcome=outcome,
                tx_type=tx_type,
                amount=float(amount),
                price=None,
                tx_hash=tx.hash,
                timestamp=timestamp,
            )

        except Exception as e:
            # Non-blocking: log warning but don't fail the handler
            logger.warning(f"⚠️ Redis publish failed (non-blocking): {e}")

        logger.info(
            f"✅ Indexed {tx_type}: market={market_id_str}, user={user_address[:8]}..., "
            f"outcome={outcome}, amount={amount}, block={block.number}"
        )

    except Exception as e:
        logger.error(f"❌ Error in on_transfer handler: {e}", exc_info=True)


async def on_transfer_batch(
    ctx: Context,
    log: Log,
    block: Block,
    tx: Transaction,
) -> None:
    """
    Handler for TransferBatch events (multi-token transfer).

    Note: Full ABI decoding of batch arrays is complex.
    For MVP, we log the batch event but don't index individual transfers.
    """
    try:
        parsed = TransferBatchEvent.parse(log)
        if not parsed:
            return

        from_addr = parsed["from"]
        to_addr = parsed["to"]

        logger.debug(
            f"📦 TransferBatch: from={from_addr[:8]}..., to={to_addr[:8]}..., "
            f"tx_hash={tx.hash}"
        )

        # TODO: Implement full ABI decoding for batch arrays
        logger.info(
            f"⏭️ TransferBatch (unskipped but not yet indexed): "
            f"from={from_addr[:8]}..., to={to_addr[:8]}..., block={block.number}"
        )

    except Exception as e:
        logger.error(f"❌ Error in on_transfer_batch handler: {e}", exc_info=True)


# ========================================
# Database Insert Helpers
# ========================================

async def insert_user_transaction(
    db: asyncpg.Pool,
    tx_id: str,
    user_address: str,
    market_id: str,
    outcome: int,
    tx_type: str,
    amount: float,
    price: Optional[float],
    tx_hash: str,
    block_number: int,
    timestamp: datetime,
) -> bool:
    """
    Insert user transaction into subsquid_user_transactions

    Args:
        tx_id: Unique transaction ID (tx_hash_log_index)
        user_address: Trader's address
        market_id: Market ID (numeric string)
        outcome: 0=NO, 1=YES
        tx_type: "BUY" or "SELL"
        amount: Token amount
        price: Fill price (NULL initially, enriched later)
        tx_hash: Blockchain tx hash
        block_number: Block number
        timestamp: Block timestamp
    """
    try:
        query = """
            INSERT INTO subsquid_user_transactions
            (tx_id, user_id, user_address, market_id, outcome, amount, price, tx_hash, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (tx_id) DO UPDATE SET
                updated_at = now()
        """
        async with db.acquire() as conn:
            await conn.execute(
                query,
                tx_id,
                None,  # user_id: will be mapped later via user_address
                user_address,
                market_id,
                outcome,
                amount,
                price,
                tx_hash,
                timestamp,
            )
        return True
    except Exception as e:
        logger.error(f"❌ Failed to insert user transaction {tx_id}: {e}")
        return False


# ========================================
# Price Enrichment (Option C - Background Job)
# ========================================

async def enrich_prices_batch(db: asyncpg.Pool, limit: int = 100) -> int:
    """
    Background job: Enrich NULL prices from subsquid_markets_poll
    Runs every 60s, synced with Poller cycle

    Args:
        db: Database connection pool
        limit: Max rows to update per run

    Returns:
        Number of rows updated
    """
    try:
        query = """
            UPDATE subsquid_user_transactions_v2
            SET price = (
                SELECT last_mid FROM subsquid_markets_poll
                WHERE subsquid_markets_poll.market_id::text = subsquid_user_transactions_v2.market_id
            )
            WHERE price IS NULL
            AND market_id IS NOT NULL
            AND tx_id IN (
                SELECT tx_id FROM subsquid_user_transactions_v2
                WHERE price IS NULL
                LIMIT $1
            )
        """

        async with db.acquire() as conn:
            result = await conn.execute(query, limit)
            # Parse result to get affected rows count
            rows_updated = int(result.split()[-1]) if "UPDATE" in result else 0

        if rows_updated > 0:
            logger.info(f"✅ Price enrichment: Updated {rows_updated} transactions with prices (v2 table)")

        return rows_updated

    except Exception as e:
        logger.error(f"❌ Price enrichment failed: {e}")
        return 0


# ========================================
# Copy Trading Integration
# ========================================
# These functions bridge DipDup → Copy Trading system
# When a transaction is detected, we can find who's following this trader

async def find_copy_traders_for_address(
    db: asyncpg.Pool,
    leader_address: str,
) -> list:
    """
    Find all users who are copy trading this blockchain address

    Lookup fallback chain:
    1. Check if leader_address is in copy_trading_subscriptions.leader_address
    2. Check if leader_address maps to a Telegram user in users table

    Returns:
        List of follower_ids that should copy trade this address
    """
    try:
        query = """
            SELECT DISTINCT follower_id
            FROM copy_trading_subscriptions
            WHERE (
                leader_address = $1
                OR leader_id IN (
                    SELECT telegram_user_id FROM users
                    WHERE polygon_address = $1
                )
            )
            AND status = 'ACTIVE'
        """

        async with db.acquire() as conn:
            followers = await conn.fetch(query, leader_address)

        follower_ids = [row['follower_id'] for row in followers]

        if follower_ids:
            logger.info(
                f"✅ Found {len(follower_ids)} copy traders following {leader_address[:8]}..."
            )

        return follower_ids

    except Exception as e:
        logger.error(f"❌ Failed to find copy traders for {leader_address}: {e}")
        return []


async def track_external_leader(
    db: asyncpg.Pool,
    polygon_address: str,
    trade_id: str,
) -> bool:
    """
    Track an external blockchain address in external_leaders table
    Useful for analytics and future copy trading decisions

    Args:
        db: Database connection pool
        polygon_address: Blockchain address (0x...)
        trade_id: Transaction ID (for tracking)
    """
    try:
        query = """
            INSERT INTO external_leaders (virtual_id, polygon_address, last_trade_id, trade_count)
            VALUES (
                CAST(CAST(substr($1, 3, 16) as hex) as BIGINT),  -- Generate virtual_id from address
                $1,
                $2,
                1
            )
            ON CONFLICT (polygon_address) DO UPDATE SET
                last_trade_id = $2,
                trade_count = trade_count + 1,
                last_poll_at = NOW(),
                updated_at = NOW()
        """

        async with db.acquire() as conn:
            await conn.execute(query, polygon_address, trade_id)

        logger.debug(f"✅ Tracked external leader: {polygon_address[:8]}...")
        return True

    except Exception as e:
        logger.debug(f"⚠️ Failed to track external leader {polygon_address}: {e}")
        return False


# ========================================
# Future: Webhook to copy trading service
# ========================================
# TODO: Implement webhook to notify bot when a copy trade should be executed
# This would be called after on_transfer completes:
#
# async def notify_copy_traders(
#     webhook_url: str,
#     market_id: str,
#     leader_address: str,
#     follower_ids: list,
#     amount: float,
#     outcome: int,
# ):
#     """Notify bot service to execute copy trades for followers"""
#     pass
