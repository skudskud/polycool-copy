"""
Position Verification Helper for Copy Trading
Checks if follower has enough tokens before copying a SELL trade
"""

import logging
import requests
from typing import Optional, Dict, Tuple
from decimal import Decimal

logger = logging.getLogger(__name__)

# Cache to avoid hitting API multiple times per second
_position_cache = {}  # wallet_address -> (positions, timestamp)
_CACHE_TTL = 5  # 5 seconds (very short for real-time accuracy)


async def get_follower_position_size(
    wallet_address: str,
    token_id: str,
    market_id: str = None,
    outcome: int = None
) -> Tuple[float, Optional[Dict]]:
    """
    Get real-time token balance for a specific position

    Args:
        wallet_address: Follower's Polygon address
        token_id: ERC-1155 token ID
        market_id: Optional market ID for logging
        outcome: Optional outcome (0 or 1) for logging

    Returns:
        Tuple of (token_count, position_data)
        - token_count: Number of tokens held (0 if none)
        - position_data: Full position dict from API or None
    """
    import time

    try:
        # Check cache first (5 second TTL)
        cache_key = wallet_address.lower()
        now = time.time()

        if cache_key in _position_cache:
            cached_positions, cached_at = _position_cache[cache_key]
            if (now - cached_at) < _CACHE_TTL:
                logger.debug(f"[POSITION_CHECK] Cache hit for {wallet_address[:10]}...")
                positions = cached_positions
            else:
                # Cache expired
                positions = None
        else:
            positions = None

        # Fetch from API if not cached
        if positions is None:
            logger.info(f"[POSITION_CHECK] Fetching positions for {wallet_address[:10]}...")
            url = f"https://data-api.polymarket.com/positions?user={wallet_address}"

            response = requests.get(url, timeout=5)  # Short timeout

            if response.status_code != 200:
                logger.error(f"❌ [POSITION_CHECK] API error {response.status_code}")
                return 0.0, None

            positions = response.json()

            # Update cache
            _position_cache[cache_key] = (positions, now)
            logger.debug(f"[POSITION_CHECK] Cached {len(positions)} positions")

        # Find matching token
        for position in positions:
            if position.get('asset') == token_id:
                size = float(position.get('size', 0))
                logger.info(
                    f"✅ [POSITION_CHECK] Found position: "
                    f"market={market_id}, outcome={outcome}, size={size} tokens"
                )
                return size, position

        # Token not found
        logger.warning(
            f"⚠️ [POSITION_CHECK] No position found: "
            f"wallet={wallet_address[:10]}..., token={token_id[:20]}..."
        )
        return 0.0, None

    except requests.Timeout:
        logger.error(f"❌ [POSITION_CHECK] API timeout (5s)")
        return 0.0, None
    except Exception as e:
        logger.error(f"❌ [POSITION_CHECK] Error: {e}")
        return 0.0, None


def should_skip_sell_copy(
    follower_token_count: float,
    required_token_count: float,
    min_ratio: float = 0.95
) -> Tuple[bool, str]:
    """
    Determine if a SELL copy should be skipped

    Args:
        follower_token_count: Tokens available in follower's wallet
        required_token_count: Tokens needed for the copy trade
        min_ratio: Minimum ratio of available/required (default 95%)

    Returns:
        Tuple of (should_skip, reason)
    """
    if follower_token_count == 0:
        return True, "FOLLOWER_HAS_NO_POSITION"

    if follower_token_count < required_token_count * min_ratio:
        return True, f"INSUFFICIENT_TOKENS (has {follower_token_count:.2f}, needs {required_token_count:.2f})"

    return False, ""


def calculate_adjusted_sell_amount(
    follower_token_count: float,
    required_token_count: float,
    current_price: float,
    allow_partial: bool = False
) -> Optional[float]:
    """
    Calculate adjusted sell amount if partial fill is allowed

    Args:
        follower_token_count: Tokens available
        required_token_count: Tokens originally needed
        current_price: Current market price per token
        allow_partial: Whether to allow selling less tokens

    Returns:
        Adjusted USD amount to sell, or None if should skip
    """
    if follower_token_count == 0:
        return None

    if follower_token_count >= required_token_count:
        # Has enough tokens - use original amount
        return required_token_count * current_price

    if allow_partial:
        # Partial fill - sell all available tokens
        logger.warning(
            f"⚠️ [PARTIAL_FILL] Selling {follower_token_count} tokens "
            f"instead of {required_token_count}"
        )
        return follower_token_count * current_price

    # Not enough tokens and partial not allowed
    return None


async def get_leader_position_size(
    leader_user_id: int,
    token_id: str,
    market_id: str = None,
    outcome: int = None
) -> Tuple[float, Optional[Dict]]:
    """
    Get leader's position size for a specific token

    This is used for position-based SELL copy trading.
    We need to know how many tokens the leader had BEFORE selling.

    Args:
        leader_user_id: Leader's telegram user ID
        token_id: ERC-1155 token ID
        market_id: Optional market ID for logging
        outcome: Optional outcome (0 or 1) for logging

    Returns:
        Tuple of (token_count, position_data)
        - token_count: Number of tokens leader has (0 if none)
        - position_data: Full position dict from API or None
    """
    try:
        from core.services import user_service

        # Get leader's wallet address
        leader_user = user_service.get_user(leader_user_id)
        if not leader_user or not leader_user.polygon_address:
            logger.warning(f"[LEADER_POSITION] No wallet found for leader {leader_user_id}")
            return 0.0, None

        # Use the same function as for followers, but with leader's address
        return await get_follower_position_size(
            wallet_address=leader_user.polygon_address,
            token_id=token_id,
            market_id=market_id,
            outcome=outcome
        )

    except Exception as e:
        logger.error(f"❌ [LEADER_POSITION] Error getting leader position: {e}")
        return 0.0, None


def clear_position_cache(wallet_address: str = None):
    """Clear position cache for a specific wallet or all wallets"""
    if wallet_address:
        _position_cache.pop(wallet_address.lower(), None)
    else:
        _position_cache.clear()
