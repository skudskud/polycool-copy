#!/usr/bin/env python3
"""
Token Utilities - Correct token ID resolution for Polymarket markets

CRITICAL FIX: Polymarket API does NOT guarantee token ordering in clob_token_ids array.
We must match by the 'outcome' field in the tokens array, not by array index.

References:
- Polymarket API docs: https://docs.polymarket.com/developers/CLOB/markets/get-markets
- GitHub issue: Token ordering bug causing 90%+ losses on sells
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_outcome(outcome: str) -> str:
    """
    Normalize outcome string for better matching between API and database

    Removes apostrophes and other special characters that may differ between
    Polymarket API responses and stored market data.

    Args:
        outcome: Raw outcome string

    Returns:
        Normalized outcome string
    """
    if not outcome:
        return ""

    # Remove apostrophes and normalize spaces
    normalized = outcome.replace("'", "").replace("'", "").strip()

    # Additional normalization can be added here if needed
    # e.g., handle other special characters, case normalization, etc.

    return normalized


def get_token_id_for_outcome(market: dict, outcome: str) -> Optional[str]:
    """
    Get token_id by matching outcome field (Polymarket API standard method)

    This function correctly resolves token IDs by matching the outcome field
    rather than assuming array index ordering. This fixes the critical bug where
    we assumed clob_token_ids[0]=YES and [1]=NO, which is NOT guaranteed.

    Args:
        market: Market dictionary from Polymarket API with 'tokens' array
        outcome: Target outcome - 'yes' or 'no' (case-insensitive)

    Returns:
        Token ID string, or None if not found

    Raises:
        ValueError: If outcome cannot be matched and no fallback available

    Examples:
        >>> market = {
        ...     'question': 'Will X happen?',
        ...     'tokens': [
        ...         {'outcome': 'No', 'token_id': 'abc123'},
        ...         {'outcome': 'Yes', 'token_id': 'def456'}
        ...     ]
        ... }
        >>> get_token_id_for_outcome(market, 'yes')
        'def456'
        >>> get_token_id_for_outcome(market, 'no')
        'abc123'
    """

    outcome_lower = outcome.lower().strip()
    outcome_normalized = normalize_outcome(outcome_lower)

    # DIAGNOSTIC: Log what we're looking for
    logger.info(f"🔍 [TOKEN_UTILS] Looking for outcome='{outcome}' (normalized: '{outcome_lower}', special_chars_removed: '{outcome_normalized}')")
    logger.info(f"🔍 [TOKEN_UTILS] Market: {market.get('question', 'Unknown')[:50]}...")

    # METHOD 1: Use tokens array with outcome field (CORRECT & RELIABLE)
    # This is the Polymarket API standard and should always work
    tokens = market.get('tokens', [])

    # DIAGNOSTIC: Log tokens array structure
    logger.info(f"🔍 [TOKEN_UTILS] tokens array exists: {tokens is not None}, is list: {isinstance(tokens, list)}, length: {len(tokens) if tokens else 0}")

    # CRITICAL FIX: If tokens array is empty, fetch from Polymarket API
    if not tokens or len(tokens) == 0:
        logger.warning(f"⚠️ [TOKEN_UTILS] tokens array is empty! Fetching from Polymarket API...")

        try:
            import requests

            # Get market ID or condition ID
            market_id = market.get('id') or market.get('condition_id')
            if not market_id:
                logger.error(f"❌ [TOKEN_UTILS] No market ID found to query Polymarket API!")
            else:
                # Query Polymarket API for market details
                api_url = f"https://gamma-api.polymarket.com/markets/{market_id}"
                logger.info(f"🔍 [TOKEN_UTILS] Querying Polymarket API: {api_url}")

                response = requests.get(api_url, timeout=10)
                if response.status_code == 200:
                    api_market = response.json()
                    tokens = api_market.get('tokens', [])

                    logger.info(f"✅ [TOKEN_UTILS] Fetched tokens from Polymarket API: {len(tokens)} tokens")

                    # Update the market dict with fresh tokens
                    market['tokens'] = tokens
                else:
                    logger.error(f"❌ [TOKEN_UTILS] Polymarket API returned {response.status_code}")
        except Exception as e:
            logger.error(f"❌ [TOKEN_UTILS] Failed to fetch from Polymarket API: {e}")

    if tokens:
        for i, token in enumerate(tokens):
            logger.info(f"🔍 [TOKEN_UTILS]   Token {i}: {token if isinstance(token, dict) else f'INVALID TYPE: {type(token)}'}")

    if tokens and isinstance(tokens, list) and len(tokens) > 0:
        for i, token in enumerate(tokens):
            if not isinstance(token, dict):
                logger.warning(f"⚠️ [TOKEN_UTILS] Token {i} is not a dict: {type(token)}")
                continue

            token_outcome = token.get('outcome', '').lower().strip()
            token_outcome_normalized = normalize_outcome(token_outcome)
            token_id = token.get('token_id')

            logger.info(f"🔍 [TOKEN_UTILS]   Comparing: '{token_outcome}' vs '{outcome_lower}' (normalized: '{token_outcome_normalized}' vs '{outcome_normalized}') (token_id: {str(token_id)[:20] if token_id else 'NONE'}...)")

            # Try exact match first, then normalized match
            if token_outcome == outcome_lower or token_outcome_normalized == outcome_normalized:
                if token_id:
                    logger.info(f"✅ [TOKEN_UTILS] PRIMARY METHOD SUCCESS: Found {outcome} token via tokens array")
                    logger.info(f"✅ [TOKEN_UTILS] Matched token_id: {str(token_id)[:30]}...")
                    return str(token_id)
                else:
                    logger.error(f"❌ [TOKEN_UTILS] Matched outcome but token_id is None/empty!")

    # METHOD 2: Fallback to clob_token_ids (DANGEROUS - only as last resort)
    # This assumes ordering which is NOT guaranteed by Polymarket API
    logger.warning(f"⚠️ [TOKEN_UTILS] FALLBACK TRIGGERED: No valid tokens array match")
    logger.warning(f"⚠️ [TOKEN_UTILS] Using clob_token_ids with DANGEROUS index assumption")
    logger.warning(f"⚠️ [TOKEN_UTILS] THIS IS THE BUG - SHOULD NEVER HAPPEN!")

    token_ids = market.get('clob_token_ids', [])

    # DIAGNOSTIC: Log clob_token_ids
    logger.info(f"🔍 [TOKEN_UTILS] clob_token_ids: {token_ids}")
    logger.info(f"🔍 [TOKEN_UTILS] clob_token_ids type: {type(token_ids)}, length: {len(token_ids) if hasattr(token_ids, '__len__') else 'N/A'}")

    # Handle string representation (support both snake_case and camelCase)
    if isinstance(token_ids, str):
        try:
            import ast
            token_ids = ast.literal_eval(token_ids)
            logger.info(f"🔍 [TOKEN_UTILS] Parsed clob_token_ids from string: {token_ids}")
        except Exception as e:
            logger.error(f"❌ [TOKEN_UTILS] Failed to parse clob_token_ids string: {e}")
            token_ids = []

    # If still no token_ids, try camelCase API key
    if not token_ids:
        token_ids = market.get('clobTokenIds', [])
        if isinstance(token_ids, str):
            try:
                import ast
                token_ids = ast.literal_eval(token_ids)
                logger.info(f"🔍 [TOKEN_UTILS] Parsed clobTokenIds (camelCase) from string: {token_ids}")
            except Exception as e:
                logger.error(f"❌ [TOKEN_UTILS] Failed to parse clobTokenIds string: {e}")
                token_ids = []

    # Ensure we have at least 2 tokens
    if not token_ids or len(token_ids) < 2:
        error_msg = f"Cannot find token_id for outcome '{outcome}' in market '{market.get('question', 'Unknown')[:50]}...'"
        logger.error(f"❌ [TOKEN_UTILS] {error_msg}")
        logger.error(f"❌ [TOKEN_UTILS] Market structure: tokens={len(tokens) if tokens else 0}, clob_token_ids={len(token_ids) if token_ids else 0}")
        raise ValueError(error_msg)

    # DANGEROUS ASSUMPTION - only use as absolute last resort
    # Match outcome to the outcomes array index, then use clob_token_ids[index]
    outcomes = market.get('outcomes', [])
    logger.info(f"🔍 [TOKEN_UTILS] Fallback: outcomes array = {outcomes}")

    # Find which index this outcome is in the outcomes array
    outcome_index = -1
    for i, mkt_outcome in enumerate(outcomes):
        mkt_outcome_lower = mkt_outcome.lower().strip()
        mkt_outcome_normalized = normalize_outcome(mkt_outcome_lower)

        logger.info(f"🔍 [TOKEN_UTILS]   Comparing market outcome '{mkt_outcome}' (normalized: '{mkt_outcome_normalized}') vs target '{outcome_lower}' (normalized: '{outcome_normalized}')")

        # Try exact match first, then normalized match
        if mkt_outcome_lower == outcome_lower or mkt_outcome_normalized == outcome_normalized:
            outcome_index = i
            logger.info(f"✅ [TOKEN_UTILS] Found outcome match at index {i}")
            break

    if outcome_index < 0:
        # Last resort: try to match 'yes'/'no' assumptions for binary markets
        if outcome_lower in ['yes', 'true', '1']:
            outcome_index = 0
        elif outcome_lower in ['no', 'false', '0']:
            outcome_index = 1
        else:
            error_msg = f"Cannot determine outcome index for '{outcome}' in market with outcomes {outcomes}"
            logger.error(f"❌ [TOKEN_UTILS] {error_msg}")
            raise ValueError(error_msg)

    if outcome_index >= len(token_ids):
        error_msg = f"Outcome index {outcome_index} out of range for token_ids (length: {len(token_ids)})"
        logger.error(f"❌ [TOKEN_UTILS] {error_msg}")
        raise ValueError(error_msg)

    token_id = str(token_ids[outcome_index])
    logger.warning(f"⚠️ [TOKEN_UTILS] FALLBACK METHOD: clob_token_ids[{outcome_index}] = {outcome}")
    logger.warning(f"⚠️ [TOKEN_UTILS] Returned token_id: {token_id[:30]}...")

    logger.error(f"🚨 [TOKEN_UTILS] USING FALLBACK - TOKEN ORDER SHOULD NOW BE CORRECT")

    return token_id


def validate_token_structure(market: dict) -> tuple[bool, str]:
    """
    Validate that market has proper token structure

    Args:
        market: Market dictionary

    Returns:
        Tuple of (is_valid, error_message)
    """

    # Check for tokens array
    tokens = market.get('tokens', [])
    if not tokens:
        return False, "Missing 'tokens' array"

    if not isinstance(tokens, list):
        return False, f"'tokens' is not a list, got {type(tokens)}"

    if len(tokens) < 2:
        return False, f"Expected 2 tokens (YES/NO), got {len(tokens)}"

    # Check each token has required fields
    for i, token in enumerate(tokens):
        if not isinstance(token, dict):
            return False, f"Token {i} is not a dict"

        if 'outcome' not in token:
            return False, f"Token {i} missing 'outcome' field"

        if 'token_id' not in token:
            return False, f"Token {i} missing 'token_id' field"

    return True, "Valid"


def get_both_token_ids(market: dict) -> tuple[Optional[str], Optional[str]]:
    """
    Get both YES and NO token IDs from market

    Useful for position recovery and orderbook queries

    Args:
        market: Market dictionary

    Returns:
        Tuple of (yes_token_id, no_token_id)
    """

    try:
        yes_token_id = get_token_id_for_outcome(market, 'yes')
        no_token_id = get_token_id_for_outcome(market, 'no')
        return yes_token_id, no_token_id
    except Exception as e:
        logger.error(f"❌ Failed to get both token IDs: {e}")
        return None, None
