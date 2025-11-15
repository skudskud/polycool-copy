"""
Leader Position Tracker
Tracks cumulative token quantities for leaders per market/outcome
Used for position-based SELL calculations in copy trading
"""
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import LeaderPosition
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class LeaderPositionTracker:
    """
    Tracks leader positions (token quantities) per market/outcome
    Cumulates BUY (+), subtracts SELL (-) for real-time position tracking
    """

    async def update_leader_position(
        self,
        watched_address_id: int,
        market_id: str,
        outcome: str,
        trade_type: str,
        token_amount: float,
        tx_hash: str,
        timestamp: Optional[datetime] = None,
        position_id: Optional[str] = None
    ) -> bool:
        """
        Update leader position based on trade

        Args:
            watched_address_id: ID of watched address (leader)
            market_id: Market ID
            outcome: 'YES' or 'NO'
            trade_type: 'BUY' or 'SELL'
            token_amount: Amount of tokens (positive value)
            tx_hash: Transaction hash
            timestamp: Trade timestamp (defaults to now)
            position_id: Optional position_id (clob_token_id) for precise tracking

        Returns:
            True if successful
        """
        try:
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)

            async with get_db() as db:
                # Normalize outcome for case-insensitive search
                outcome_normalized = outcome.upper().strip()

                # Try to find existing position by position_id first (if available)
                position = None
                if position_id:
                    result = await db.execute(
                        select(LeaderPosition).where(
                            and_(
                                LeaderPosition.watched_address_id == watched_address_id,
                                LeaderPosition.position_id == position_id
                            )
                        )
                    )
                    position = result.scalar_one_or_none()

                # If not found by position_id, try by market_id + outcome (case-insensitive)
                if not position:
                    from sqlalchemy import func
                    result = await db.execute(
                        select(LeaderPosition).where(
                            and_(
                                LeaderPosition.watched_address_id == watched_address_id,
                                LeaderPosition.market_id == market_id,
                                func.upper(LeaderPosition.outcome) == outcome_normalized
                            )
                        )
                    )
                    position = result.scalar_one_or_none()

                if not position:
                    # Create new position
                    position = LeaderPosition(
                        watched_address_id=watched_address_id,
                        market_id=market_id,
                        outcome=outcome_normalized,  # Store normalized outcome
                        position_id=position_id,  # Store position_id if available
                        token_quantity=0,
                        created_at=timestamp,
                        updated_at=timestamp
                    )
                    db.add(position)
                elif position_id and not position.position_id:
                    # Update position_id if not set (for existing positions)
                    position.position_id = position_id

                # Update based on trade type
                if trade_type.upper() == 'BUY':
                    position.add_tokens(token_amount, tx_hash, timestamp)
                    logger.debug(
                        f"✅ Leader position BUY: {watched_address_id} +{token_amount} tokens "
                        f"({market_id}/{outcome}) → {position.token_quantity:.6f} total"
                    )
                elif trade_type.upper() == 'SELL':
                    position.subtract_tokens(token_amount, tx_hash, timestamp)
                    logger.debug(
                        f"✅ Leader position SELL: {watched_address_id} -{token_amount} tokens "
                        f"({market_id}/{outcome}) → {position.token_quantity:.6f} total"
                    )
                else:
                    logger.warning(f"⚠️ Unknown trade type: {trade_type}")
                    return False

                await db.commit()
                return True

        except Exception as e:
            logger.error(f"❌ Error updating leader position: {e}", exc_info=True)
            return False

    async def get_leader_position(
        self,
        watched_address_id: int,
        market_id: str,
        outcome: str,
        position_id: Optional[str] = None
    ) -> Optional[float]:
        """
        Get current token quantity for leader position

        Args:
            watched_address_id: ID of watched address (leader)
            market_id: Market ID
            outcome: 'YES' or 'NO' (will be normalized for case-insensitive search)
            position_id: Optional position_id (clob_token_id) for more precise lookup

        Returns:
            Token quantity or None if not found
        """
        try:
            async with get_db() as db:
                # Normalize outcome for case-insensitive search
                outcome_normalized = outcome.upper().strip()

                # Priority 1: Use position_id if available (most precise)
                if position_id:
                    logger.info(
                        f"🔍 [LEADER_POSITION] Searching by position_id: {position_id[:20]}... "
                        f"(watched_address_id={watched_address_id})"
                    )
                    result = await db.execute(
                        select(LeaderPosition).where(
                            and_(
                                LeaderPosition.watched_address_id == watched_address_id,
                                LeaderPosition.position_id == position_id
                            )
                        )
                    )
                    position = result.scalar_one_or_none()
                    if position:
                        logger.info(
                            f"✅ [LEADER_POSITION] Found by position_id: {position_id[:20]}... "
                            f"(market_id={position.market_id[:20]}..., outcome={position.outcome}, quantity={position.token_quantity})"
                        )
                        return float(position.token_quantity or 0)
                    else:
                        logger.warning(
                            f"⚠️ [LEADER_POSITION] No position found by position_id: {position_id[:20]}... "
                            f"(watched_address_id={watched_address_id})"
                        )

                # Priority 2: Use market_id + normalized outcome (case-insensitive)
                # Use func.upper() for case-insensitive comparison
                from sqlalchemy import func
                logger.info(
                    f"🔍 [LEADER_POSITION] Searching by market_id+outcome: {market_id[:20]}.../{outcome_normalized} "
                    f"(watched_address_id={watched_address_id})"
                )
                result = await db.execute(
                    select(LeaderPosition).where(
                        and_(
                            LeaderPosition.watched_address_id == watched_address_id,
                            LeaderPosition.market_id == market_id,
                            func.upper(LeaderPosition.outcome) == outcome_normalized
                        )
                    )
                )
                position = result.scalar_one_or_none()

                if position:
                    logger.info(
                        f"✅ [LEADER_POSITION] Found by market_id+outcome: {market_id[:20]}.../{outcome_normalized} "
                        f"(quantity={position.token_quantity}, position_id={position.position_id[:20] if position.position_id else None}...)"
                    )
                    return float(position.token_quantity or 0)

                logger.warning(
                    f"⚠️ [LEADER_POSITION] No position found: watched_address_id={watched_address_id}, "
                    f"market_id={market_id[:20]}..., outcome={outcome_normalized}, position_id={position_id[:20] if position_id else None}..."
                )

                # Debug: Check if there are any positions for this watched_address_id and market_id (different outcome)
                debug_result = await db.execute(
                    select(LeaderPosition).where(
                        and_(
                            LeaderPosition.watched_address_id == watched_address_id,
                            LeaderPosition.market_id == market_id
                        )
                    )
                )
                debug_positions = list(debug_result.scalars().all())
                if debug_positions:
                    logger.warning(
                        f"🔍 [LEADER_POSITION] Found {len(debug_positions)} positions for this market_id but different outcome: "
                        f"{[(p.outcome, p.token_quantity) for p in debug_positions]}"
                    )

                return None

        except Exception as e:
            logger.error(f"❌ Error getting leader position: {e}", exc_info=True)
            return None

    async def calculate_position_based_sell_amount(
        self,
        leader_tokens_sold: float,
        leader_position_size: float,
        follower_position_size: float,
        current_price: float
    ) -> Optional[dict]:
        """
        Calculate SELL copy amount based on position percentage (TOKEN-BASED, more precise)

        Formula (token-based):
            leader_sell_pct = leader_tokens_sold / leader_position_size
            follower_tokens_to_sell = leader_sell_pct * follower_position_size
            copy_amount_usd = follower_tokens_to_sell * current_price

        Special rule: If leader sells > 95% of their position, follower sells 100%

        Args:
            leader_tokens_sold: Number of tokens/shares the leader sold (PRIMARY - most precise)
            leader_position_size: Number of tokens leader had BEFORE selling
            follower_position_size: Number of tokens follower has
            current_price: Current price per token (for USD conversion at the end)

        Returns:
            Dict with 'tokens' and 'usd' keys, or None if invalid
        """
        try:
            if leader_position_size <= 0:
                logger.warning(f"⚠️ Invalid leader position size: {leader_position_size}")
                return None

            if follower_position_size <= 0:
                logger.warning(f"⚠️ Invalid follower position size: {follower_position_size}")
                return None

            if current_price <= 0:
                logger.warning(f"⚠️ Invalid current price: {current_price}")
                return None

            if leader_tokens_sold <= 0:
                logger.warning(f"⚠️ Invalid leader tokens sold: {leader_tokens_sold}")
                return None

            # Calculate what % of position leader sold (TOKEN-BASED - most precise)
            leader_sell_pct = leader_tokens_sold / leader_position_size

            # Calculate normal proportional sell amount first
            follower_tokens_to_sell = leader_sell_pct * follower_position_size
            copy_amount_usd = follower_tokens_to_sell * current_price

            # RULE 1: If follower's remaining balance after sell would be < $0.50, sell everything
            remaining_tokens = follower_position_size - follower_tokens_to_sell
            remaining_value = remaining_tokens * current_price

            if remaining_value < 0.50:  # 0.5 dollars, not cents
                follower_tokens_to_sell = follower_position_size  # 100% of follower position
                copy_amount_usd = follower_tokens_to_sell * current_price
                logger.info(
                    f"🎯 [SELL_LOGIC] Follower remaining balance would be ${remaining_value:.2f} < $0.50 → "
                    f"Selling 100% ({follower_tokens_to_sell:.6f} tokens = ${copy_amount_usd:.2f})"
                )
                return {'tokens': follower_tokens_to_sell, 'usd': copy_amount_usd}

            # RULE 2: Special rule: If leader sells > 95% of their position, follower sells 100%
            if leader_sell_pct >= 0.95:
                follower_tokens_to_sell = follower_position_size  # 100% of follower position
                copy_amount_usd = follower_tokens_to_sell * current_price
                logger.info(
                    f"🎯 [SELL_LOGIC] Leader selling {leader_sell_pct*100:.1f}% of position "
                    f"({leader_tokens_sold:.6f} / {leader_position_size:.6f} tokens) → "
                    f"Follower sells 100% ({follower_tokens_to_sell:.6f} tokens = ${copy_amount_usd:.2f})"
                )
                return {'tokens': follower_tokens_to_sell, 'usd': copy_amount_usd}

            # Normal case: Apply same % to follower's position (TOKEN-BASED)
            # (already calculated above)

            logger.info(
                f"📊 [SELL_LOGIC] Token-based SELL calculation: "
                f"leader_sold={leader_tokens_sold:.6f} tokens ({leader_sell_pct*100:.1f}% of {leader_position_size:.6f}), "
                f"follower_selling={follower_tokens_to_sell:.6f} tokens ({leader_sell_pct*100:.1f}% of {follower_position_size:.6f}), "
                f"price=${current_price:.4f}, "
                f"copy_amount_usd=${copy_amount_usd:.2f}"
            )

            return {'tokens': follower_tokens_to_sell, 'usd': copy_amount_usd}

        except Exception as e:
            logger.error(f"❌ Error calculating position-based sell amount: {e}", exc_info=True)
            return None


# Global instance
_leader_position_tracker: Optional[LeaderPositionTracker] = None


def get_leader_position_tracker() -> LeaderPositionTracker:
    """Get global LeaderPositionTracker instance"""
    global _leader_position_tracker
    if _leader_position_tracker is None:
        _leader_position_tracker = LeaderPositionTracker()
    return _leader_position_tracker
