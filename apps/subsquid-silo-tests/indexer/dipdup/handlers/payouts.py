"""
DipDup Handler for Conditional Tokens PayoutRedeemed Events
Tracks market settlement and user redemptions.
"""

import logging
from typing import Optional
from datetime import datetime, timezone

from dipdup import Context
from dipdup.models import Block, Transaction, Log
import asyncpg

logger = logging.getLogger(__name__)


class PayoutRedeemedEvent:
    """Parse PayoutRedeemed event"""

    @staticmethod
    def parse(log: Log) -> Optional[dict]:
        """
        PayoutRedeemed event signature:
        PayoutRedeemed(indexed address redeemer, indexed bytes32 conditionId, indexed uint256 indexSet, uint256 payout)
        """
        try:
            if len(log.topics) < 4 or len(log.data) < 32:
                return None

            # Topics: [signature, redeemer, conditionId, indexSet]
            redeemer = f"0x{log.topics[1][26:]}"
            condition_id = log.topics[2]
            index_set = log.topics[3]

            # Data: payout amount (32 bytes)
            payout = int(log.data[0:66], 16)

            return {
                "redeemer": redeemer,
                "condition_id": condition_id,
                "index_set": index_set,
                "payout": payout,
            }
        except Exception as e:
            logger.warning(f"Failed to parse PayoutRedeemed event: {e}")
            return None


async def on_payout_redeemed(
    ctx: Context,
    log: Log,
    block: Block,
    tx: Transaction,
) -> None:
    """
    Handler for PayoutRedeemed events.
    Records redemptions (settlements) for markets.
    """
    try:
        parsed = PayoutRedeemedEvent.parse(log)
        if not parsed:
            return

        timestamp = datetime.fromtimestamp(block.timestamp, tz=timezone.utc)

        # Get database connection from context
        db: asyncpg.Pool = ctx.get_database()

        # Insert settlement/redemption event
        await insert_payout_redeemed(
            db=db,
            event_id=f"{tx.hash}_{log.index}",
            user_address=parsed["redeemer"],
            condition_id=parsed["condition_id"],
            index_set=parsed["index_set"],
            payout=parsed["payout"],
            tx_hash=tx.hash,
            block_number=block.number,
            timestamp=timestamp,
        )

        logger.info(
            f"✅ Indexed PayoutRedeemed: {parsed['redeemer'][:6]}... "
            f"payout={parsed['payout']}, condition={parsed['condition_id'][:8]}..."
        )

    except Exception as e:
        logger.error(f"❌ Error in on_payout_redeemed handler: {e}")


async def insert_payout_redeemed(
    db: asyncpg.Pool,
    event_id: str,
    user_address: str,
    condition_id: str,
    index_set: str,
    payout: float,
    tx_hash: str,
    block_number: int,
    timestamp: datetime,
) -> bool:
    """Insert settlement event into subsquid_events"""
    try:
        query = """
            INSERT INTO subsquid_events
            (event_id, title, status, start_date, end_date)
            VALUES ($1, $2, 'SETTLED', $3, $4)
            ON CONFLICT (event_id) DO UPDATE SET
                status = 'SETTLED'
        """
        async with db.acquire() as conn:
            await conn.execute(
                query,
                event_id,
                f"Settlement: {user_address[:6]}... received {payout}",
                timestamp,
                timestamp,
            )
        return True
    except Exception as e:
        logger.error(f"❌ Failed to insert payout redeemed: {e}")
        return False
