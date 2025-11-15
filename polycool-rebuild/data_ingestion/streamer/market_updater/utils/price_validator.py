"""
Price Validator - Validate prices before updating markets
Ensures prices are reasonable and consistent
"""
from typing import List, Optional, Dict, Any
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def validate_prices(
    prices: List[float],
    market_data: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Validate that prices are reasonable and consistent

    Args:
        prices: List of prices
        market_data: Optional market data for context

    Returns:
        True if prices are valid, False otherwise
    """
    if not prices or len(prices) == 0:
        logger.debug(f"⚠️ Empty prices list")
        return False

    # Get expected number of outcomes from market_data
    expected_count = None
    if market_data:
        outcomes = market_data.get("outcomes")
        if outcomes and isinstance(outcomes, list):
            expected_count = len(outcomes)

    # For binary markets, require both prices (don't accept partial updates)
    if expected_count == 2:
        if len(prices) < 2:
            logger.warning(
                f"⚠️ Partial prices for binary market: got {len(prices)} prices, "
                f"expected 2"
            )
            return False

    # Check all prices are in valid range (0-1 for Polymarket)
    for price in prices:
        if price < 0 or price > 1:
            logger.warning(f"⚠️ Price {price} out of range [0, 1]")
            return False

    # For binary markets (2 outcomes), validate YES + NO ≈ 1.0
    if len(prices) == 2:
        return validate_binary_market_prices(prices)

    return True


def validate_binary_market_prices(prices: List[float]) -> bool:
    """
    Validate binary market prices (outcome1 + outcome2 should sum to ~1.0)

    Works for any binary market outcomes: YES/NO, Up/Down, etc.

    According to Polymarket: prices should sum to ~1.0 (with small tolerance for rounding/arbitrage)
    However, we use stricter validation to catch invalid data from WebSocket

    Args:
        prices: List of exactly 2 prices [outcome1_price, outcome2_price]

    Returns:
        True if prices are valid, False otherwise
    """
    if len(prices) != 2:
        return False

    price1 = prices[0]
    price2 = prices[1]

    # Check individual prices are reasonable
    if price1 < 0 or price1 > 1 or price2 < 0 or price2 > 1:
        logger.warning(f"⚠️ Individual prices out of range: outcome1={price1:.4f}, outcome2={price2:.4f}")
        return False

    total = price1 + price2
    # Stricter tolerance: 0.98 to 1.02 (was 0.95-1.05)
    # This catches most invalid data while allowing for small rounding/arbitrage
    if total < 0.98 or total > 1.02:
        logger.warning(
            f"⚠️ Price sum {total:.4f} not close to 1.0 (prices: outcome1={price1:.4f}, outcome2={price2:.4f})"
        )
        return False

    return True
