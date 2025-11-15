"""
Price Updater - Update position prices from various sources
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import select

from core.database.connection import get_db
from core.database.models import Position, Market
from infrastructure.logging.logger import get_logger
from .pnl_calculator import calculate_pnl
from .crud import get_active_positions
from .outcome_helper import find_outcome_index

logger = get_logger(__name__)


async def update_position_price(
    position_id: int,
    current_price: float
) -> Optional[Position]:
    """
    Update position current price and recalculate P&L

    Args:
        position_id: Position ID
        current_price: Current market price

    Returns:
        Updated Position object or None if error

    Raises:
        ValueError: If current_price is invalid
    """
    try:
        # Validate price range
        if not (0 <= current_price <= 1):
            raise ValueError(f"Invalid current_price {current_price}: Polymarket prices must be 0-1")

        async with get_db() as db:
            result = await db.execute(
                select(Position).where(Position.id == position_id)
            )
            position = result.scalar_one_or_none()

            if not position:
                return None

            # Update price
            position.current_price = current_price

            # Recalculate P&L
            pnl_amount, pnl_percentage = calculate_pnl(
                position.entry_price,
                current_price,
                position.amount,
                position.outcome
            )

            position.pnl_amount = pnl_amount
            position.pnl_percentage = pnl_percentage
            position.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.refresh(position)

            return position

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating position price {position_id}: {e}")
        return None


async def get_markets_prices_batch(market_ids: List[str]) -> Dict[str, Dict]:
    """
    Get current prices for multiple markets in batch
    Includes source field to determine price extraction strategy

    Args:
        market_ids: List of market IDs

    Returns:
        Dict mapping market_id to market price data (includes 'source', 'outcome_prices', 'last_mid_price')
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Market.id, Market.source, Market.outcome_prices, Market.last_mid_price, Market.outcomes)
                .where(Market.id.in_(market_ids))
            )

            markets_data = {}
            for row in result:
                market_id, source, outcome_prices, last_mid_price, outcomes = row
                logger.debug(f"Raw market data for {market_id}: source={source}, outcome_prices={outcome_prices}, last_mid_price={last_mid_price}")
                markets_data[market_id] = {
                    'source': source,
                    'outcome_prices': outcome_prices,
                    'last_mid_price': last_mid_price,
                    'outcomes': outcomes
                }

            return markets_data

    except Exception as e:
        logger.error(f"Error getting markets prices batch: {e}")
        return {}


def extract_position_price(market_data: Dict, outcome: str) -> Optional[float]:
    """
    Extract price for specific outcome from market data

    CRITICAL: When source='ws', use ONLY outcome_prices (no fallbacks)
    This ensures consistency with WebSocket-streamed prices from markets table

    Args:
        market_data: Market price data from DB (includes 'source', 'outcome_prices', 'outcomes')
        outcome: "YES" or "NO"

    Returns:
        Price for the outcome or None if not available

    Raises:
        ValueError: If price data is invalid
    """
    if not market_data:
        return None

    try:
        source = market_data.get('source', 'poll')
        outcome_prices = market_data.get('outcome_prices')
        outcomes = market_data.get('outcomes', ['YES', 'NO'])

        # CRITICAL: When source='ws', use ONLY outcome_prices (no fallbacks)
        if source == 'ws':
            if not outcome_prices:
                logger.warning(f"⚠️ Market has source='ws' but no outcome_prices available")
                return None

            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                try:
                    outcome_index = find_outcome_index(outcome, outcomes)
                    if outcome_index is not None and outcome_index < len(outcome_prices):
                        price = float(outcome_prices[outcome_index])
                        if 0 <= price <= 1:
                            logger.debug(f"Extracted {outcome} price from WebSocket: ${price:.4f}")
                            return price
                        else:
                            logger.warning(f"Invalid Polymarket price {price} for {outcome} - should be 0-1")
                            return None
                except (ValueError, IndexError, TypeError) as e:
                    logger.warning(f"⚠️ Error extracting price from outcome_prices list: {e}")
                    return None
            else:
                logger.warning(f"⚠️ Market has source='ws' but invalid outcome_prices format: {type(outcome_prices)}")
                return None

        # For source='poll' or other sources, try outcome_prices first, then fallbacks
        if outcome_prices and isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
            try:
                outcome_index = find_outcome_index(outcome, outcomes)
                if outcome_index is not None and outcome_index < len(outcome_prices):
                    price = float(outcome_prices[outcome_index])
                    if 0 <= price <= 1:
                        logger.debug(f"Extracted {outcome} price: ${price:.4f}")
                        return price
            except (ValueError, IndexError, TypeError) as e:
                logger.debug(f"⚠️ Error extracting price from outcome_prices list: {e}")

        # Fallback to last_mid_price (only for source='poll')
        last_mid_price = market_data.get('last_mid_price')
        if last_mid_price is not None:
            price = float(last_mid_price)
            logger.debug(f"Using last_mid_price: ${price:.4f}")
            return price

        # No price data available - return None
        logger.warning(f"No price data available for outcome {outcome}")
        return None

    except (ValueError, IndexError, TypeError) as e:
        logger.warning(f"Error extracting price for outcome {outcome}: {e}")
        return None


async def update_all_positions_prices(user_id: int) -> int:
    """
    Update prices for all user's active positions from markets table
    Called when user views positions or clicks refresh
    Optimized to use batch update for better performance

    Args:
        user_id: User ID

    Returns:
        Number of positions updated
    """
    try:
        # Get all active positions for user
        positions = await get_active_positions(user_id)
        if not positions:
            return 0

        # Get unique market IDs to batch fetch market data
        market_ids = list(set(pos.market_id for pos in positions))

        # Get market prices in batch for better performance
        market_prices = await get_markets_prices_batch(market_ids)

        # Collect all position updates for batch processing
        position_updates = []
        for position in positions:
            market_price = extract_position_price(
                market_prices.get(position.market_id),
                position.outcome
            )

            # Only update if we have a valid price and it's different
            if market_price is not None and market_price != position.current_price:
                position_updates.append({
                    'position_id': position.id,
                    'current_price': market_price,
                    'outcome': position.outcome
                })
                logger.debug(f"Queued position {position.id} for batch update: {position.current_price} → {market_price}")

        # Use batch update for all positions in a single transaction
        if position_updates:
            updated_count = await batch_update_positions_prices(position_updates)
            logger.info(f"✅ Batch updated prices for {updated_count}/{len(positions)} positions for user {user_id}")
            return updated_count
        else:
            logger.info(f"No positions to update for user {user_id}")
            return 0

    except Exception as e:
        logger.error(f"Error updating all positions prices for user {user_id}: {e}")
        return 0


async def batch_update_positions_prices(
    position_updates: List[Dict[str, Any]]
) -> int:
    """
    Batch update position prices in a single transaction (optimized)
    More efficient than individual updates - uses single DB transaction

    Args:
        position_updates: List of dicts with 'position_id', 'current_price', and optionally 'outcome'

    Returns:
        Number of positions updated
    """
    if not position_updates:
        return 0

    try:
        async with get_db() as db:
            # First, fetch all positions in a single query
            position_ids = [
                update_data.get('position_id')
                for update_data in position_updates
                if update_data.get('position_id') and update_data.get('current_price') is not None
            ]

            if not position_ids:
                return 0

            # Fetch all positions at once
            result = await db.execute(
                select(Position).where(Position.id.in_(position_ids))
            )
            positions = {pos.id: pos for pos in result.scalars().all()}

            # Create update mapping for efficient lookup
            updates_map = {
                update_data.get('position_id'): update_data
                for update_data in position_updates
                if update_data.get('position_id') and update_data.get('current_price') is not None
            }

            updated_count = 0
            now = datetime.now(timezone.utc)

            # Update all positions in memory
            for position_id, position in positions.items():
                update_data = updates_map.get(position_id)
                if not update_data:
                    continue

                current_price = update_data.get('current_price')
                outcome = update_data.get('outcome')

                # Validate price range
                if not (0 <= current_price <= 1):
                    logger.warning(f"Invalid price {current_price} for position {position_id}, skipping")
                    continue

                # Update price
                position.current_price = current_price

                # Recalculate P&L
                pnl_amount, pnl_percentage = calculate_pnl(
                    position.entry_price,
                    current_price,
                    position.amount,
                    outcome or position.outcome
                )

                position.pnl_amount = pnl_amount
                position.pnl_percentage = pnl_percentage
                position.updated_at = now
                updated_count += 1

            # Commit all updates in a single transaction
            await db.commit()
            logger.debug(f"✅ Batch updated {updated_count} positions in single transaction")
            return updated_count

    except Exception as e:
        logger.error(f"❌ Error batch updating positions: {e}")
        return 0


async def update_all_positions_prices_with_priority(user_id: int) -> int:
    """
    Update prices for all active positions of a user
    Priority: WebSocket prices (markets.outcome_prices) > CLOB API > market.last_mid_price
    NO fallback to entry_price - raises error if no price available

    Args:
        user_id: User ID

    Returns:
        Number of positions updated

    Raises:
        ValueError: If no price source is available for a position
    """
    try:
        positions = await get_active_positions(user_id)
        if not positions:
            return 0

        # Get markets for positions
        market_ids = [p.market_id for p in positions]

        # Get current prices - prioritize WebSocket prices
        from core.services.clob.clob_service import get_clob_service

        clob_service = get_clob_service()

        updated_count = 0

        async with get_db() as db:
            for position in positions:
                # Get market
                market_result = await db.execute(
                    select(Market).where(Market.id == position.market_id)
                )
                market = market_result.scalar_one_or_none()

                if not market:
                    logger.warning(f"Market {position.market_id} not found for position {position.id}")
                    continue

                # CRITICAL: When source='ws', use ONLY outcome_prices (no CLOB API fallback)
                current_price = None
                outcomes = market.outcomes or ['YES', 'NO']

                if market.source == 'ws':
                    # For WebSocket markets, use ONLY outcome_prices
                    if market.outcome_prices and isinstance(market.outcome_prices, list) and len(market.outcome_prices) >= 2:
                        try:
                            outcome_index = find_outcome_index(position.outcome, outcomes)
                            if outcome_index is not None and outcome_index < len(market.outcome_prices):
                                ws_price = market.outcome_prices[outcome_index]
                                if ws_price is not None and 0 <= float(ws_price) <= 1:
                                    current_price = float(ws_price)
                                    logger.debug(f"✅ Using WebSocket price for position {position.id}: {current_price}")
                                else:
                                    logger.warning(f"⚠️ Invalid WebSocket price {ws_price} for position {position.id}")
                            else:
                                logger.warning(f"⚠️ Outcome index {outcome_index} out of range for market {market.id}")
                        except (ValueError, IndexError, TypeError) as e:
                            logger.warning(f"⚠️ Error extracting WebSocket price for position {position.id}: {e}")
                    else:
                        logger.warning(f"⚠️ Market {market.id} has source='ws' but no valid outcome_prices")
                else:
                    # For source='poll', try outcome_prices first, then CLOB API
                    if market.outcome_prices and isinstance(market.outcome_prices, list) and len(market.outcome_prices) >= 2:
                        try:
                            outcome_index = find_outcome_index(position.outcome, outcomes)
                            if outcome_index is not None and outcome_index < len(market.outcome_prices):
                                poll_price = market.outcome_prices[outcome_index]
                                if poll_price is not None and 0 <= float(poll_price) <= 1:
                                    current_price = float(poll_price)
                                    logger.debug(f"✅ Using poll outcome_prices for position {position.id}: {current_price}")
                        except (ValueError, IndexError, TypeError) as e:
                            logger.debug(f"⚠️ Error extracting poll price: {e}")

                # Priority 2: Fallback to CLOB API if WebSocket/poll price not available (only for source='poll')
                # CRITICAL: When source='ws', NEVER use CLOB API or last_mid_price fallback
                if current_price is None and market.source != 'ws':
                    clob_token_ids = market.clob_token_ids or []
                    try:
                        outcome_index = find_outcome_index(position.outcome, outcomes)
                        token_id = clob_token_ids[outcome_index] if outcome_index is not None and outcome_index < len(clob_token_ids) else None
                    except (IndexError, ValueError):
                        token_id = None

                    if token_id:
                        try:
                            prices = await clob_service.get_market_prices([token_id])
                            current_price = prices.get(token_id)
                            if current_price is not None:
                                logger.debug(f"✅ Using CLOB API price for position {position.id}: {current_price}")
                        except Exception as e:
                            logger.debug(f"⚠️ CLOB API error for position {position.id}: {e}")

                # Priority 3: Fallback to market.last_mid_price (only for source='poll', NOT for source='ws')
                # CRITICAL: When source='ws', NEVER use last_mid_price fallback - must use outcome_prices only
                if current_price is None and market.source != 'ws':
                    current_price = market.last_mid_price
                    if current_price is not None:
                        logger.debug(f"✅ Using market.last_mid_price for position {position.id}: {current_price}")

                # NO FALLBACK to entry_price - raise error if no price available
                if current_price is None:
                    raise ValueError(
                        f"No price data available for position {position.id} "
                        f"(market: {position.market_id}, outcome: {position.outcome}). "
                        f"Cannot update position without valid price source."
                    )

                # Validate price range (Polymarket prices should be 0-1)
                if not (0 <= current_price <= 1):
                    raise ValueError(
                        f"Invalid price {current_price} for position {position.id}: "
                        f"Polymarket prices must be 0-1"
                    )

                # Only update if price changed significantly (> 0.1%) or if current_price was None
                price_changed = False
                if position.current_price is None:
                    price_changed = True
                elif current_price is not None:
                    price_change_pct = abs((current_price - position.current_price) / position.current_price) * 100
                    if price_change_pct >= 0.1:
                        price_changed = True

                if price_changed:
                    # Update position
                    position.current_price = current_price

                    # Recalculate P&L
                    pnl_amount, pnl_percentage = calculate_pnl(
                        position.entry_price,
                        current_price,
                        position.amount,
                        position.outcome
                    )

                    position.pnl_amount = pnl_amount
                    position.pnl_percentage = pnl_percentage
                    position.updated_at = datetime.now(timezone.utc)

                    updated_count += 1

            await db.commit()

        logger.info(f"✅ Updated prices for {updated_count} positions for user {user_id} (prioritized WebSocket prices)")
        return updated_count

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating positions prices: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise
