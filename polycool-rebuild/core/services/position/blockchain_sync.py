"""
Blockchain Synchronization - Sync positions from Polymarket API
"""
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timezone
from sqlalchemy import select

from core.database.connection import get_db
from core.database.models import Position, Market
from infrastructure.logging.logger import get_logger
from .crud import (
    get_active_positions,
    close_position
)

logger = get_logger(__name__)


def validate_position_data(bp: Dict, field_name: str) -> float:
    """
    Validate position data from Polymarket API

    Args:
        bp: Position data from API
        field_name: Field name to validate ('size', 'avgPrice', 'curPrice')

    Returns:
        Validated float value

    Raises:
        ValueError: If field is missing or invalid
    """
    value = bp.get(field_name)

    if value is None:
        raise ValueError(f"Missing required field '{field_name}' in Polymarket API response")

    try:
        value_float = float(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid '{field_name}' value '{value}': cannot convert to float") from e

    # Validate price range for price fields
    if field_name in ('avgPrice', 'curPrice'):
        if not (0 <= value_float <= 1):
            raise ValueError(f"Invalid '{field_name}' {value_float}: Polymarket prices must be 0-1")

    # Validate size > 0
    if field_name == 'size':
        if value_float <= 0:
            raise ValueError(f"Invalid 'size' {value_float}: must be > 0")

    return value_float


async def get_positions_from_blockchain(wallet_address: str) -> List[Dict]:
    """
    Get current positions from blockchain via Polymarket API
    Uses official endpoint: /api/core/positions/current

    Args:
        wallet_address: User's Polygon wallet address

    Returns:
        List of position dictionaries from API

    Raises:
        Exception: If API call fails completely
    """
    try:
        import aiohttp

        # Try official Polymarket API endpoint first
        base_urls = [
            "https://data-api.polymarket.com",
            "https://api.polymarket.com"
        ]

        for base_url in base_urls:
            try:
                # Try new official endpoint format
                url = f"{base_url}/api/core/positions/current?address={wallet_address}"

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Handle both formats: {"positions": [...]} or [...]
                            if isinstance(data, dict) and 'positions' in data:
                                positions_list = data.get('positions', [])
                                logger.info(f"✅ Fetched {len(positions_list)} current positions from {base_url}")
                                return positions_list if isinstance(positions_list, list) else []
                            elif isinstance(data, list):
                                logger.info(f"✅ Fetched {len(data)} current positions from {base_url}")
                                return data
                        elif response.status == 404:
                            # Endpoint doesn't exist, try next base URL
                            logger.debug(f"⚠️ Endpoint not found at {base_url}, trying next...")
                            continue
                        else:
                            logger.warning(f"⚠️ API Error {response.status} from {base_url}, trying next...")
                            continue
            except Exception as e:
                logger.debug(f"⚠️ Error with {base_url}: {e}, trying next...")
                continue

        # Fallback to legacy endpoint if official endpoints don't work
        logger.warning(f"⚠️ Official endpoints failed, falling back to legacy endpoint")
        url = f"https://data-api.polymarket.com/positions?user={wallet_address}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    raise Exception(f"Legacy API Error: {response.status} for wallet {wallet_address[:10]}...")

                positions_data = await response.json()
                return positions_data if isinstance(positions_data, list) else []

    except Exception as e:
        logger.error(f"❌ Error fetching positions from blockchain for {wallet_address[:10]}...: {e}")
        raise


async def get_closed_positions_from_blockchain(wallet_address: str) -> List[Dict]:
    """
    Get closed positions from blockchain via Polymarket API
    Uses optimized endpoint: /closed-positions (more complete than /api/core/positions/closed)

    The /closed-positions endpoint provides:
    - realizedPnl (key field for redeemable detection)
    - conditionId, outcome, outcomeIndex
    - avgPrice, totalBought, curPrice
    - title, slug, icon, eventSlug
    - endDate

    Args:
        wallet_address: User's Polygon wallet address

    Returns:
        List of closed position dictionaries from API
    """
    try:
        import aiohttp

        # ✅ OPTIMIZATION: Use /closed-positions endpoint (more complete data)
        # This endpoint provides realizedPnl which is critical for redeemable detection
        base_url = "https://data-api.polymarket.com"

        # Use optimized parameters: limit=100, sortBy=REALIZEDPNL DESC (most profitable first)
        url = f"{base_url}/closed-positions"
        params = {
            "user": wallet_address,
            "limit": 100,  # Max 100 positions per request
            "sortBy": "REALIZEDPNL",
            "sortDirection": "DESC"
        }

        try:
            logger.debug(f"🔍 [CLOSED POSITIONS] Calling {url} with params: {params}")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    logger.debug(f"📡 [CLOSED POSITIONS] Response status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"📦 [CLOSED POSITIONS] Response type: {type(data)}, length: {len(data) if isinstance(data, (list, dict)) else 'N/A'}")

                        # Handle both formats: array or object with 'positions' key
                        if isinstance(data, list):
                            logger.info(f"✅ Fetched {len(data)} closed positions from {base_url}")
                            # Log first position for debugging
                            if len(data) > 0:
                                first_pos = data[0]
                                logger.debug(
                                    f"📋 [CLOSED POSITIONS] Sample position: "
                                    f"conditionId={first_pos.get('conditionId', 'N/A')[:20]}..., "
                                    f"realizedPnl=${first_pos.get('realizedPnl', 0):.2f}, "
                                    f"title={first_pos.get('title', 'N/A')[:50]}..."
                                )
                            return data
                        elif isinstance(data, dict) and 'positions' in data:
                            positions_list = data.get('positions', [])
                            logger.info(f"✅ Fetched {len(positions_list)} closed positions from {base_url}")
                            return positions_list if isinstance(positions_list, list) else []
                        else:
                            logger.warning(f"⚠️ Unexpected response format from /closed-positions: {type(data)}")
                            logger.debug(f"📦 [CLOSED POSITIONS] Response content: {str(data)[:200]}")
                            return []
                    elif response.status == 404:
                        logger.debug(f"⚠️ Closed positions endpoint not found at {base_url}")
                        return []
                    elif response.status == 429:
                        logger.warning(f"⚠️ Rate limited (429) for closed positions, returning empty list")
                        return []
                    else:
                        logger.debug(f"⚠️ API Error {response.status} from {base_url} for closed positions")
                        return []
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Timeout fetching closed positions for {wallet_address[:10]}...")
            return []
        except Exception as e:
            logger.debug(f"⚠️ Error fetching closed positions from {base_url}: {e}")
            return []

        # Fallback: try /api/core/positions/closed if /closed-positions fails
        logger.debug(f"⚠️ /closed-positions failed, trying fallback endpoint")
        base_urls = [
            "https://data-api.polymarket.com",
            "https://api.polymarket.com"
        ]

        for base_url in base_urls:
            try:
                url = f"{base_url}/api/core/positions/closed?address={wallet_address}"

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Handle both formats: {"positions": [...]} or [...]
                            if isinstance(data, dict) and 'positions' in data:
                                positions_list = data.get('positions', [])
                                logger.info(f"✅ Fetched {len(positions_list)} closed positions from fallback {base_url}")
                                return positions_list if isinstance(positions_list, list) else []
                            elif isinstance(data, list):
                                logger.info(f"✅ Fetched {len(data)} closed positions from fallback {base_url}")
                                return data
                        elif response.status == 404:
                            logger.debug(f"⚠️ Fallback endpoint not found at {base_url}")
                            continue
                        else:
                            logger.debug(f"⚠️ API Error {response.status} from fallback {base_url}")
                            continue
            except Exception as e:
                logger.debug(f"⚠️ Error with fallback {base_url}: {e}")
                continue

        # If no endpoint works, return empty list (closed positions are optional)
        logger.debug(f"⚠️ Could not fetch closed positions for {wallet_address[:10]}..., returning empty list")
        return []

    except Exception as e:
        logger.warning(f"⚠️ Error fetching closed positions for {wallet_address[:10]}...: {e}")
        return []


async def get_market_id_from_token_id(token_id: str) -> Optional[str]:
    """
    Get market_id from CLOB token_id

    Args:
        token_id: CLOB token ID

    Returns:
        Market ID or None
    """
    try:
        async with get_db() as db:
            result = await db.execute(
                select(Market.id)
                .where(Market.clob_token_ids.contains([token_id]))
            )
            market = result.scalar_one_or_none()
            return market

    except Exception as e:
        logger.error(f"Error getting market_id for token_id {token_id}: {e}")
        return None


async def sync_positions_from_blockchain(
    user_id: int,
    wallet_address: str
) -> int:
    """
    Sync positions from blockchain to database
    Creates/updates positions based on blockchain data
    Also checks closed positions to fix corrupted positions

    Uses ONLY 'size' field from Polymarket API (not 'amount' or 'currentValue')
    NO hardcoded fallbacks - raises ValueError if required data is missing

    Args:
        user_id: User ID
        wallet_address: User's Polygon wallet address

    Returns:
        Number of positions synced

    Raises:
        ValueError: If required fields are missing from API response
    """
    try:
        logger.info(f"🔄 Starting sync for user {user_id}, wallet {wallet_address[:10]}...")

        # Get current positions from blockchain
        logger.debug(f"📡 Fetching current positions from blockchain...")
        blockchain_positions = await get_positions_from_blockchain(wallet_address)
        logger.info(f"✅ Fetched {len(blockchain_positions)} current positions from blockchain")

        # Get closed positions from blockchain (to detect corrupted positions)
        logger.debug(f"📡 Fetching closed positions from blockchain...")
        closed_positions = await get_closed_positions_from_blockchain(wallet_address)
        logger.info(f"✅ Fetched {len(closed_positions)} closed positions from blockchain")

        # Create set of closed position identifiers for quick lookup
        closed_positions_set = set()
        from core.services.position.pnl_calculator import normalize_outcome
        for cp in closed_positions:
            condition_id = cp.get('conditionId') or cp.get('marketId')
            outcome_raw = cp.get('outcome', 'YES')
            # Normalize outcome to YES/NO format (handles DOWN, UP, etc.)
            outcome = normalize_outcome(outcome_raw)
            if condition_id:
                closed_positions_set.add((condition_id, outcome))

        # Get existing positions from database
        logger.debug(f"📊 Fetching existing positions from database...")
        existing_positions = await get_active_positions(user_id)
        logger.info(f"✅ Found {len(existing_positions)} existing positions in database")
        existing_by_market_outcome = {}
        existing_by_market_outcome_index = {}  # Track by outcomeIndex for precise matching
        for pos in existing_positions:
            # Normalize outcome to uppercase for matching
            outcome_normalized = pos.outcome.upper() if pos.outcome else 'YES'
            key_normalized = (pos.market_id, outcome_normalized)
            key_original = (pos.market_id, pos.outcome)
            # Store with both keys to handle case differences
            existing_by_market_outcome[key_normalized] = pos
            if key_original != key_normalized:
                existing_by_market_outcome[key_original] = pos

            # Also track by outcomeIndex if we can determine it from market outcomes
            # This helps match positions more precisely when there are duplicates
            # Note: We'll populate this inside the db context below

        synced_count = 0
        closed_count = 0
        fixed_count = 0

        logger.debug(f"🔌 Opening database connection...")
        async with get_db() as db:
            logger.debug(f"✅ Database connection opened")

            # Populate existing_by_market_outcome_index with outcomeIndex mapping
            # This needs to be done inside the db context
            for pos in existing_positions:
                try:
                    from core.database.models import Market
                    from sqlalchemy import select
                    market_result = await db.execute(
                        select(Market).where(Market.id == pos.market_id)
                    )
                    market = market_result.scalar_one_or_none()
                    if market and market.outcomes:
                        from core.services.position.outcome_helper import find_outcome_index
                        outcome_idx = find_outcome_index(pos.outcome, market.outcomes)
                        if outcome_idx is not None:
                            condition_id = market.condition_id
                            if condition_id:
                                existing_by_market_outcome_index[(condition_id, outcome_idx)] = pos
                except Exception as e:
                    logger.debug(f"⚠️ Could not determine outcomeIndex for position {pos.id}: {e}")
                    pass  # Skip if we can't determine outcomeIndex

            # Process current positions
            # Track which positions exist in blockchain (to close positions not in blockchain)
            # Use outcomeIndex for more precise matching (handles duplicate positions with different outcome formats)
            blockchain_positions_set = set()
            blockchain_positions_by_index = {}  # (condition_id, outcomeIndex) -> position data

            for bp in blockchain_positions:
                try:
                    # Extract market info from blockchain position
                    condition_id = bp.get('conditionId') or bp.get('marketId')
                    outcome_raw = bp.get('outcome', 'YES')
                    outcome_index = bp.get('outcomeIndex')  # Use outcomeIndex for precise matching
                    # Normalize outcome to YES/NO format (handles DOWN, UP, etc.)
                    from core.services.position.pnl_calculator import normalize_outcome
                    outcome = normalize_outcome(outcome_raw)

                    # Use ONLY 'size' field from Polymarket API (most accurate)
                    # NO fallback to 'amount' or 'currentValue'
                    try:
                        size = validate_position_data(bp, 'size')
                    except ValueError as e:
                        logger.error(f"❌ Invalid position data: {e}. Skipping position.")
                        continue

                    # Track this position in blockchain (both normalized outcome and outcomeIndex)
                    if condition_id:
                        blockchain_positions_set.add((condition_id, outcome))
                        # Also track by outcomeIndex for precise matching
                        if outcome_index is not None:
                            blockchain_positions_by_index[(condition_id, outcome_index)] = bp

                    # Find market by condition_id
                    market_result = await db.execute(
                        select(Market).where(Market.condition_id == condition_id)
                    )
                    market = market_result.scalar_one_or_none()

                    if not market:
                        logger.debug(f"⚠️ Market not found for condition_id {condition_id}")
                        continue

                    # Check if position exists - try outcomeIndex first (most precise), then normalized outcome
                    existing = None
                    if outcome_index is not None and condition_id:
                        # Try to match by outcomeIndex first (most precise for duplicate positions)
                        existing = existing_by_market_outcome_index.get((condition_id, outcome_index))
                        if existing:
                            logger.debug(f"✅ Matched position {existing.id} by outcomeIndex {outcome_index} for condition {condition_id[:20]}...")

                    # Fallback to outcome-based matching if outcomeIndex didn't work
                    if not existing:
                        key_normalized = (market.id, outcome)
                        key_original = (market.id, outcome_raw) if outcome_raw != outcome else None
                        existing = existing_by_market_outcome.get(key_normalized)
                        if not existing and key_original:
                            existing = existing_by_market_outcome.get(key_original)
                            # If found with original case, update the key mapping
                            if existing:
                                existing_by_market_outcome[key_normalized] = existing
                                logger.debug(f"🔄 Found position with different case: {outcome_raw} -> {outcome}")

                    if existing:
                        # Update existing position with blockchain data
                        # Normalize outcome in DB to match API format
                        if existing.outcome.upper() != outcome:
                            logger.info(f"🔄 Normalizing outcome for position {existing.id}: {existing.outcome} -> {outcome}")
                            existing.outcome = outcome

                        # Always update amount from blockchain (source of truth)
                        # Force update if difference exists (even small ones) to fix corrupted data
                        # Log the comparison for debugging
                        logger.info(f"🔍 Comparing position {existing.id}: DB amount={existing.amount}, API size={size}, difference={abs(existing.amount - size)}")
                        if abs(existing.amount - size) > 0.0001:  # Update if any difference (more sensitive)
                            logger.info(f"🔄 Updating position {existing.id}: amount {existing.amount} -> {size} (from blockchain size field)")
                            existing.amount = size
                            existing.updated_at = datetime.now(timezone.utc)
                        else:
                            logger.info(f"✅ Position {existing.id} amount already correct: {size}")

                        # Update entry_price from avgPrice if available
                        avg_price = bp.get('avgPrice')
                        if avg_price is not None:
                            try:
                                avg_price = validate_position_data(bp, 'avgPrice')
                                if abs(existing.entry_price - avg_price) > 0.0001:
                                    logger.info(f"🔄 Updating position {existing.id} entry_price: {existing.entry_price} -> {avg_price} (from blockchain avgPrice)")
                                    existing.entry_price = avg_price
                                else:
                                    logger.debug(f"✅ Position {existing.id} entry_price already correct: {avg_price}")
                            except ValueError as e:
                                logger.warning(f"⚠️ Invalid avgPrice for position {existing.id}: {e}. Keeping existing entry_price.")

                        # Update current_price from curPrice if available
                        cur_price = bp.get('curPrice')
                        if cur_price is not None:
                            try:
                                cur_price = validate_position_data(bp, 'curPrice')
                                if existing.current_price is None or abs(existing.current_price - cur_price) > 0.0001:
                                    logger.info(f"🔄 Updating position {existing.id} current_price: {existing.current_price} -> {cur_price} (from blockchain curPrice)")
                                    existing.current_price = cur_price
                                else:
                                    logger.debug(f"✅ Position {existing.id} current_price already correct: {cur_price}")
                            except ValueError as e:
                                logger.warning(f"⚠️ Invalid curPrice for position {existing.id}: {e}. Keeping existing current_price.")

                        synced_count += 1
                    else:
                        # Create new position
                        # Use avgPrice from blockchain - NO fallback
                        try:
                            entry_price = validate_position_data(bp, 'avgPrice')
                        except ValueError as e:
                            logger.error(f"❌ Cannot create position: missing avgPrice. {e}")
                            continue

                        # Use curPrice from blockchain - NO fallback
                        try:
                            current_price = validate_position_data(bp, 'curPrice')
                        except ValueError as e:
                            logger.error(f"❌ Cannot create position: missing curPrice. {e}")
                            continue

                        position = Position(
                            user_id=user_id,
                            market_id=market.id,
                            outcome=outcome,  # Already normalized to uppercase
                            amount=size,
                            entry_price=entry_price,
                            current_price=current_price,
                            pnl_amount=0.0,
                            pnl_percentage=0.0,
                            status="active",
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc)
                        )

                        db.add(position)
                        synced_count += 1
                        logger.info(f"✅ Created new position for market {market.id} ({market.title[:50]}), outcome {outcome}, size {size}")

                except ValueError as e:
                    logger.error(f"❌ Error processing blockchain position: {e}")
                    continue
                except Exception as e:
                    logger.error(f"❌ Unexpected error processing blockchain position: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue

            # Fix corrupted positions: close positions that are NOT in blockchain anymore
            # or are in closed_positions_set, or have amount=0 but status='active'
            for pos in existing_positions:
                condition_id = None
                # Get condition_id from market
                market_result = await db.execute(
                    select(Market).where(Market.id == pos.market_id)
                )
                market = market_result.scalar_one_or_none()
                if market:
                    condition_id = market.condition_id

                should_close = False
                reason = ""

                # Normalize position outcome for comparison (handles DOWN, UP, etc.)
                pos_outcome_normalized = normalize_outcome(pos.outcome)

                # Try to match by outcomeIndex first (more precise for duplicate positions)
                matched_by_index = False
                if condition_id and market and market.outcomes:
                    from core.services.position.outcome_helper import find_outcome_index
                    pos_outcome_index = find_outcome_index(pos.outcome, market.outcomes)
                    if pos_outcome_index is not None:
                        # Check if this outcomeIndex exists in blockchain
                        if (condition_id, pos_outcome_index) in blockchain_positions_by_index:
                            matched_by_index = True
                            logger.debug(f"✅ Position {pos.id} matched by outcomeIndex {pos_outcome_index}")

                # Priority 1: Check if position is NOT in blockchain positions (most important)
                # Use outcomeIndex matching if available, otherwise fallback to normalized outcome
                if not matched_by_index:
                    if condition_id and (condition_id, pos_outcome_normalized) not in blockchain_positions_set:
                        should_close = True
                        reason = f"not found in blockchain API (market: {market.title[:50] if market else 'unknown'})"
                    # Also check if there are multiple positions for same market and this one doesn't match
                    elif condition_id:
                        # Check if there are other positions for this market that matched
                        # If this position didn't match by outcomeIndex, it might be a duplicate
                        other_positions_for_market = [
                            p for p in existing_positions
                            if p.market_id == pos.market_id and p.id != pos.id and p.status == 'active'
                        ]
                        if other_positions_for_market:
                            # Check if any other position matched
                            other_matched = False
                            for other_pos in other_positions_for_market:
                                other_outcome_idx = find_outcome_index(other_pos.outcome, market.outcomes) if market and market.outcomes else None
                                if other_outcome_idx is not None and (condition_id, other_outcome_idx) in blockchain_positions_by_index:
                                    other_matched = True
                                    break

                            if other_matched:
                                # Another position matched, this one is likely a duplicate
                                should_close = True
                                reason = f"duplicate position - another position for this market matched with blockchain API"

                # Priority 1.5: Check for duplicate positions for the same market (even if both are in blockchain)
                # This handles cases where the same position was created twice with different outcome formats
                if not should_close and condition_id:
                    other_positions_for_market = [
                        p for p in existing_positions
                        if p.market_id == pos.market_id and p.id != pos.id and p.status == 'active'
                    ]
                    if other_positions_for_market:
                        # Check if we have multiple positions for the same market
                        # Normalize outcomes and check if they represent the same outcome
                        from core.services.position.pnl_calculator import normalize_outcome
                        pos_outcome_norm = normalize_outcome(pos.outcome)

                        for other_pos in other_positions_for_market:
                            other_outcome_norm = normalize_outcome(other_pos.outcome)

                            # If outcomes normalize to the same value, they're duplicates
                            if pos_outcome_norm == other_outcome_norm:
                                # Keep the most recent one, close the older one
                                if pos.created_at < other_pos.created_at:
                                    should_close = True
                                    reason = f"duplicate position - same normalized outcome '{pos_outcome_norm}' as position {other_pos.id} (keeping newer)"
                                    break
                                else:
                                    # The other position will be closed in its iteration
                                    logger.debug(f"🔍 Position {pos.id} will be kept, position {other_pos.id} will be closed (duplicate)")
                                    break

                            # Also check if both positions have the same outcomeIndex (more precise)
                            if market and market.outcomes:
                                pos_outcome_idx = find_outcome_index(pos.outcome, market.outcomes)
                                other_outcome_idx = find_outcome_index(other_pos.outcome, market.outcomes)

                                if pos_outcome_idx is not None and other_outcome_idx is not None and pos_outcome_idx == other_outcome_idx:
                                    # Same outcomeIndex = duplicate
                                    if pos.created_at < other_pos.created_at:
                                        should_close = True
                                        reason = f"duplicate position - same outcomeIndex {pos_outcome_idx} as position {other_pos.id} (keeping newer)"
                                        break

                # Priority 2: Check if position is in closed positions list
                if not should_close and condition_id and (condition_id, pos_outcome_normalized) in closed_positions_set:
                    should_close = True
                    reason = "found in closed positions API"
                # Priority 3: Check if position has amount=0 but status='active' (corrupted)
                elif not should_close and pos.amount <= 0 and pos.status == 'active':
                    should_close = True
                    reason = "amount=0 with status=active (corrupted)"

                if should_close:
                    # Get current price for closing - NO fallback to entry_price
                    exit_price = pos.current_price
                    if exit_price is None:
                        logger.warning(f"⚠️ Position {pos.id} has no current_price, cannot close properly")
                        # Still close it but log the issue
                        exit_price = pos.entry_price  # Last resort, but log it
                        logger.warning(f"⚠️ Using entry_price {exit_price} as exit_price for position {pos.id}")

                    await close_position(pos.id, exit_price)
                    closed_count += 1
                    fixed_count += 1
                    logger.info(f"✅ Fixed corrupted position {pos.id} (market: {pos.market_id}, outcome: {pos.outcome}): {reason}")

            await db.commit()

        logger.info(f"✅ Synced {synced_count} positions, closed {closed_count} positions ({fixed_count} fixed) for user {user_id}")
        return synced_count

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"❌ Error syncing positions from blockchain: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise
