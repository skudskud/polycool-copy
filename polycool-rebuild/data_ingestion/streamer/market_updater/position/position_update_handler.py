"""
Position Update Handler - Update positions when market prices change
Delegates to PositionService for position updates
"""
import os
from typing import List, Optional, Dict, Any
from sqlalchemy import select

from core.database.connection import get_db
from core.database.models import Market as MarketModel
from core.services.cache_manager import CacheManager
from core.services.position.outcome_helper import find_outcome_index
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"

cache_manager = CacheManager()


class PositionUpdateHandler:
    """
    Handle position updates when market prices change
    Delegates to PositionService for actual updates
    """

    def __init__(self, position_service=None):
        """
        Initialize PositionUpdateHandler

        Args:
            position_service: Optional PositionService instance
        """
        self.position_service = position_service
        if not self.position_service:
            from core.services.position.position_service import position_service
            self.position_service = position_service

    async def update_positions_for_market(
        self,
        market_id: str,
        prices: List[float]
    ) -> List[Any]:
        """
        Update all active positions for a market when prices change
        Uses batch updates for efficiency

        Args:
            market_id: Market ID
            prices: List of prices [YES_price, NO_price]
        """
        try:
            # Skip position updates if SKIP_DB=true (positions should be updated by API service)
            # The API service will handle position price updates when markets are updated
            if SKIP_DB:
                logger.debug(
                    f"⚠️ Skipping position updates for market {market_id} "
                    f"(SKIP_DB=true - API service handles this)"
                )
                return

            # Get market to determine outcome mapping
            async with get_db() as db:
                result = await db.execute(
                    select(MarketModel).where(MarketModel.id == market_id)
                )
                market = result.scalar_one_or_none()

            if not market:
                logger.debug(f"⚠️ Market {market_id} not found for position updates")
                return

            # Get outcomes
            outcomes = market.outcomes or ['YES', 'NO']
            if len(prices) != len(outcomes):
                logger.warning(
                    f"⚠️ Price count ({len(prices)}) != outcome count ({len(outcomes)})"
                )
                return

            # Get all active positions for this market
            positions = await self.position_service.get_positions_by_market(market_id)

            if not positions:
                return []

            # Prepare batch updates
            position_updates = []
            user_ids_to_invalidate = set()

            for position in positions:
                try:
                    # Find price for this outcome using intelligent normalization
                    outcome_index = find_outcome_index(position.outcome, outcomes)
                    if outcome_index is None or outcome_index >= len(prices):
                        logger.debug(
                            f"⚠️ Could not find outcome index for position {position.id}: "
                            f"outcome='{position.outcome}', market outcomes={outcomes}"
                        )
                        continue

                    current_price = float(prices[outcome_index])  # Ensure it's a float

                    # Always update if current_price is None or 0 (initial state)
                    # Otherwise, only update if price changed significantly (> 0.1%)
                    if position.current_price and position.current_price > 0:
                        price_change_pct = abs(
                            (current_price - position.current_price) /
                            position.current_price
                        ) * 100
                        if price_change_pct < 0.1:
                            logger.debug(
                                f"⏭️ Skipping position {position.id} update: "
                                f"price change {price_change_pct:.2f}% < 0.1% threshold "
                                f"({position.current_price} → {current_price})"
                            )
                            continue  # Skip if change is too small
                    else:
                        # Initial price update or price was None/0
                        logger.debug(
                            f"✅ Updating position {position.id} initial price: "
                            f"{position.current_price} → {current_price}"
                        )

                    position_updates.append({
                        'position_id': position.id,
                        'current_price': current_price,
                        'outcome': position.outcome
                    })
                    user_ids_to_invalidate.add(position.user_id)

                except (ValueError, IndexError) as e:
                    logger.debug(f"⚠️ Error processing position {position.id}: {e}")
                    continue

            # Batch update positions
            if position_updates:
                updated_count = await self.position_service.batch_update_positions_prices(
                    position_updates
                )
                logger.debug(f"✅ Updated {updated_count} positions for market {market_id}")

                # Invalidate cache for affected users
                for user_id in user_ids_to_invalidate:
                    await cache_manager.invalidate_pattern(f"api:positions:{user_id}*")

            # Return positions for TP/SL checking (even if no updates were made)
            return positions

        except Exception as e:
            logger.error(f"⚠️ Error updating positions for market {market_id}: {e}")
            return []
