"""
Outcome Helper - Utilities for finding and normalizing outcomes
Handles multiple outcome formats (YES/NO, UP/DOWN, OVER/UNDER, etc.)
"""
from typing import List, Optional
from infrastructure.logging.logger import get_logger
from .pnl_calculator import normalize_outcome

logger = get_logger(__name__)


def find_outcome_index(outcome: str, outcomes: List[str]) -> Optional[int]:
    """
    Find the index of an outcome in a list of outcomes with intelligent normalization

    Handles cases where:
    - Market has ["UP", "DOWN"] but position has "YES" (normalized)
    - Market has ["YES", "NO"] but position has "UP" (needs normalization)
    - Direct match (case-insensitive)

    Args:
        outcome: Outcome string from position (e.g., "YES", "UP", "DOWN", etc.)
        outcomes: List of outcomes from market (e.g., ["YES", "NO"] or ["UP", "DOWN"])

    Returns:
        Index of the outcome in the list, or None if not found
    """
    if not outcome or not outcomes:
        logger.warning(f"⚠️ Empty outcome or outcomes list: outcome={outcome}, outcomes={outcomes}")
        return None

    outcome_upper = outcome.upper().strip()
    outcomes_upper = [o.upper().strip() if isinstance(o, str) else str(o).upper().strip() for o in outcomes]

    # Strategy 1: Direct match (case-insensitive)
    try:
        direct_index = outcomes_upper.index(outcome_upper)
        logger.debug(f"✅ Direct match found: '{outcome}' at index {direct_index} in {outcomes}")
        return direct_index
    except ValueError:
        pass

    # Strategy 2: Normalize outcome and try to match
    # Normalize the position outcome to YES/NO
    normalized_outcome = normalize_outcome(outcome)

    # Try to find normalized outcome in the list
    try:
        normalized_index = outcomes_upper.index(normalized_outcome)
        logger.debug(f"✅ Normalized match found: '{outcome}' -> '{normalized_outcome}' at index {normalized_index} in {outcomes}")
        return normalized_index
    except ValueError:
        pass

    # Strategy 3: Normalize all market outcomes and try to match
    # This handles cases where market has ["UP", "DOWN"] and position has "YES"
    normalized_outcomes = [normalize_outcome(o) for o in outcomes]
    try:
        normalized_index = normalized_outcomes.index(normalized_outcome)
        logger.debug(f"✅ Cross-normalized match found: '{outcome}' -> '{normalized_outcome}' at index {normalized_index} in {outcomes} (normalized: {normalized_outcomes})")
        return normalized_index
    except ValueError:
        pass

    # Strategy 4: Fallback to position-based logic (YES=0, NO=1)
    # Only use this if we have exactly 2 outcomes (binary market)
    if len(outcomes) == 2:
        if normalized_outcome == 'YES':
            logger.debug(f"⚠️ Fallback: Using index 0 for '{outcome}' (normalized to YES) in binary market {outcomes}")
            return 0
        elif normalized_outcome == 'NO':
            logger.debug(f"⚠️ Fallback: Using index 1 for '{outcome}' (normalized to NO) in binary market {outcomes}")
            return 1

    # No match found
    logger.warning(
        f"⚠️ Could not find outcome '{outcome}' (normalized: '{normalized_outcome}') "
        f"in outcomes list {outcomes}. Available outcomes: {outcomes_upper}"
    )
    return None


def normalize_outcome_for_market(outcome: str, outcomes: List[str]) -> Optional[str]:
    """
    Normalize an outcome to match the format used in the market's outcomes list

    If market has ["UP", "DOWN"], returns "UP" or "DOWN" (not "YES"/"NO")
    If market has ["YES", "NO"], returns "YES" or "NO"

    Args:
        outcome: Outcome string from position
        outcomes: List of outcomes from market

    Returns:
        Normalized outcome matching market format, or None if not found
    """
    if not outcome or not outcomes:
        return None

    index = find_outcome_index(outcome, outcomes)
    if index is not None and index < len(outcomes):
        return outcomes[index]

    return None
