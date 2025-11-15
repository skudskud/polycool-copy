"""
Redeemable Position Detector Service
Detects positions that are redeemable (in RESOLVED markets with winning tokens)
"""
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.database.models import Market, ResolvedPosition
from core.database.connection import get_db
from core.services.cache_manager import CacheManager
from core.services.position.outcome_helper import find_outcome_index
from core.services.position.pnl_calculator import normalize_outcome as normalize_outcome_pnl
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class RedeemablePositionDetector:
    """Detects and creates redeemable position records"""

    def __init__(self):
        self.cache_manager = CacheManager()
        self.cache_ttl = 300  # 5 minutes

    async def detect_redeemable_positions(
        self,
        positions_data: List[Dict],
        user_id: int,
        wallet_address: str
    ) -> Tuple[List[Dict], List[str]]:
        """
        Detect which positions are redeemable and separate them from active positions

        Args:
            positions_data: Raw position data from blockchain API
            user_id: Telegram user ID (internal user ID)
            wallet_address: User's wallet address

        Returns:
            Tuple of (redeemable_positions, redeemable_condition_ids)
            - redeemable_positions: List of resolved_positions dicts ready for display
            - redeemable_condition_ids: Set of condition_ids to filter from active positions
        """
        if not positions_data:
            return [], []

        # Extract all condition_ids from positions
        condition_ids = [
            pos.get('conditionId', pos.get('id', ''))
            for pos in positions_data
            if pos.get('conditionId') or pos.get('id')
        ]

        if not condition_ids:
            logger.debug(f"🔍 [REDEEM] No condition_ids found in positions")
            return [], []

        # Separate closed positions from active positions
        closed_positions = [p for p in positions_data if p.get('closed', False) and float(p.get('realizedPnl', 0)) > 0]
        active_condition_ids = [
            cid for cid in condition_ids
            if not any(p.get('conditionId') == cid and p.get('closed') for p in positions_data)
        ]

        logger.info(
            f"📊 [REDEEM] Processing {len(closed_positions)} closed positions with positive PnL, "
            f"{len(active_condition_ids)} active condition_ids"
        )

        # For active positions, query resolved markets
        resolved_markets = {}
        if active_condition_ids:
            resolved_markets = await self._batch_query_resolved_markets(active_condition_ids, user_id)

        if not resolved_markets and not closed_positions:
            logger.debug(
                f"🔍 [REDEEM] No resolved markets found for {len(active_condition_ids)} active condition_ids "
                f"and no closed positions"
            )
            return [], []

        # Detect resolved positions (both winners and losers)
        redeemable_positions = []  # Only winners for display
        resolved_condition_ids = set()  # Both winners and losers to filter from active

        # Process closed positions first (don't need market resolution)
        # ✅ SOLUTION: Create resolved_positions directly for closed positions with positive PnL
        logger.info(f"🔍 [REDEEM] Processing {len(closed_positions)} closed positions...")
        for position in closed_positions:
            condition_id = position.get('conditionId', position.get('id', ''))
            if not condition_id:
                logger.warning(f"⚠️ [REDEEM] Closed position missing conditionId, skipping")
                continue

            realized_pnl = float(position.get('realizedPnl', 0))
            if realized_pnl <= 0:
                logger.debug(f"🔍 [REDEEM] Skipping closed position with non-positive PnL: ${realized_pnl:.2f}")
                continue  # Skip non-winning closed positions

            logger.info(
                f"🎯 [REDEEM] Processing closed position: condition_id={condition_id[:20]}..., "
                f"realizedPnl=${realized_pnl:.2f}"
            )

            # Extract position data
            position_outcome_raw = position.get('outcome', '').upper()
            tokens_held = float(position.get('size', position.get('totalBought', 0)))
            avg_price = float(position.get('avgPrice', 0))
            token_id = position.get('asset', '')
            title = position.get('title', 'Unknown Market')

            # Filter out dust positions
            if tokens_held < 0.1:
                logger.debug(f"🔍 [REDEEM] Skipping dust closed position: {tokens_held} tokens")
                continue

            # Normalize outcome using outcome_helper (same logic as rest of codebase)
            position_outcome = normalize_outcome_pnl(position_outcome_raw)
            logger.debug(
                f"🔍 [REDEEM] Normalized outcome: '{position_outcome_raw}' -> '{position_outcome}'"
            )

            # Determine winning outcome index (0=YES, 1=NO)
            if position_outcome.upper() == 'YES':
                winning_outcome_index = 0
            else:
                winning_outcome_index = 1

            # Create resolved_position directly (bypass _check_position_redeemable for closed positions)
            resolved_pos = await self._get_or_create_resolved_position(
                user_id=user_id,
                condition_id=condition_id,
                market_id=condition_id,  # Will be resolved to real market_id in _get_or_create_resolved_position
                market_title=title,
                position_outcome=position_outcome,
                position_id=token_id,
                tokens_held=tokens_held,
                avg_price=avg_price,
                winning_outcome_num=winning_outcome_index,
                is_winner=True,  # Closed position with positive PnL is always a winner
                resolution_date=datetime.now(timezone.utc)
            )

            if resolved_pos:
                # Add to filter list (winners)
                resolved_condition_ids.add(condition_id)

                # Add winners to redeemable_positions (for display)
                if resolved_pos.get('is_winner'):
                    redeemable_positions.append(resolved_pos)
                    logger.info(
                        f"💰 [REDEEM] Created resolved_position for winning CLOSED position: "
                        f"user={user_id}, market={condition_id[:10]}..., "
                        f"outcome={position_outcome}, pnl=${realized_pnl:.2f}, "
                        f"net_value=${resolved_pos.get('net_value', 0):.2f}"
                    )
            else:
                logger.error(
                    f"❌ [REDEEM] Failed to create resolved_position for closed position: "
                    f"condition_id={condition_id[:20]}..., user_id={user_id}"
                )

        # Process active positions that need market resolution
        for position in positions_data:
            if position.get('closed', False):
                continue  # Already processed above

            condition_id = position.get('conditionId', position.get('id', ''))
            if not condition_id:
                continue

            market = resolved_markets.get(condition_id)
            if not market:
                continue

            # Check if position is in resolved market (both winners and losers)
            is_resolved, resolved_pos = await self._check_position_redeemable(
                position, market, user_id, wallet_address
            )

            if is_resolved:
                if resolved_pos:
                    # Add to filter list (both winners and losers)
                    resolved_condition_ids.add(condition_id)

                    # Only add winners to redeemable_positions (for display)
                    if resolved_pos.get('is_winner'):
                        redeemable_positions.append(resolved_pos)
                        logger.info(
                            f"💰 [REDEEM] Detected winning position: "
                            f"user={user_id}, market={market.get('market_id', condition_id)[:10]}..., "
                            f"outcome={position.get('outcome')}, tokens={position.get('size', 0)}"
                        )
                    else:
                        logger.debug(
                            f"📉 [REDEEM] Detected losing position: "
                            f"user={user_id}, market={market.get('market_id', condition_id)[:10]}..., "
                            f"outcome={position.get('outcome')}"
                        )
                else:
                    logger.warning(
                        f"⚠️ [REDEEM] Position is resolved but failed to create resolved_position: "
                        f"user={user_id}, condition={condition_id[:10]}..."
                    )

        logger.debug(
            f"🔍 [REDEEM] Found {len(redeemable_positions)} winning positions "
            f"and {len(resolved_condition_ids) - len(redeemable_positions)} losing positions "
            f"out of {len(positions_data)} total positions"
        )

        return redeemable_positions, list(resolved_condition_ids)

    async def _batch_query_resolved_markets(
        self,
        condition_ids: List[str],
        user_id: int
    ) -> Dict[str, Dict]:
        """
        Batch query resolved markets with Redis caching

        Args:
            condition_ids: List of condition_ids to check
            user_id: User ID for cache key

        Returns:
            Dict mapping condition_id -> market dict
        """
        resolved_markets = {}
        uncached_ids = []

        # Check Redis cache first
        for condition_id in condition_ids:
            cache_key = f"redeemable_check:{user_id}:{condition_id}"
            cached_result = await self.cache_manager.get(cache_key)

            if cached_result:
                # Cache hit - check if it's resolved
                if cached_result == "RESOLVED":
                    # Still need to fetch market data from DB
                    uncached_ids.append(condition_id)
                # If cached as "NOT_RESOLVED", skip DB query
                logger.debug(f"✅ [REDEEM CACHE] Hit for {condition_id[:10]}...")
            else:
                uncached_ids.append(condition_id)

        if not uncached_ids:
            # All cached, but we still need market data for resolved ones
            # Re-query DB for resolved markets (but fewer now)
            uncached_ids = condition_ids

        # Batch query DB for uncached markets
        try:
            async with get_db() as db:
                from sqlalchemy import select

                # Query RESOLVED markets
                resolved_query = select(Market).where(
                    Market.condition_id.in_(uncached_ids),
                    Market.is_resolved == True,
                    Market.resolved_outcome.isnot(None)
                )
                result = await db.execute(resolved_query)
                resolved_markets_list = result.scalars().all()

                # Query PROPOSED markets with extreme prices (new logic)
                # These markets have extreme prices indicating resolution, even if not officially RESOLVED yet
                one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

                proposed_query = select(Market).where(
                    Market.condition_id.in_(uncached_ids),
                    Market.is_resolved == False,
                    Market.resolved_outcome.is_(None),
                    Market.end_date.isnot(None),
                    Market.end_date < one_hour_ago,
                    Market.outcome_prices.isnot(None)
                )
                result = await db.execute(proposed_query)
                proposed_markets_list = result.scalars().all()

                # Process RESOLVED markets
                for market in resolved_markets_list:
                    condition_id = market.condition_id or market.id
                    if condition_id:
                        # Parse outcomes and clob_token_ids for dynamic outcome mapping
                        outcomes = []
                        if market.outcomes:
                            outcomes = list(market.outcomes) if isinstance(market.outcomes, list) else [market.outcomes]

                        clob_token_ids = []
                        if market.clob_token_ids:
                            if isinstance(market.clob_token_ids, list):
                                clob_token_ids = market.clob_token_ids
                            elif isinstance(market.clob_token_ids, str):
                                import json
                                try:
                                    clob_token_ids = json.loads(market.clob_token_ids)
                                except (json.JSONDecodeError, TypeError):
                                    pass

                        resolved_markets[condition_id] = {
                            'market_id': market.id,
                            'condition_id': condition_id,
                            'title': market.title,
                            'winning_outcome': self._normalize_outcome_from_resolved(market.resolved_outcome),
                            'resolution_status': 'RESOLVED',
                            'resolution_date': market.resolved_at or datetime.now(timezone.utc),
                            'polymarket_url': market.polymarket_url,
                            'outcomes': outcomes,
                            'clob_token_ids': clob_token_ids
                        }

                        # Cache result in Redis (5min TTL)
                        cache_key = f"redeemable_check:{user_id}:{condition_id}"
                        await self.cache_manager.set(cache_key, "RESOLVED", ttl=self.cache_ttl)

                # Process PROPOSED markets with extreme prices
                for market in proposed_markets_list:
                    # Check if prices are extreme (>= 0.999 and <= 0.001)
                    if not market.outcome_prices or len(market.outcome_prices) != 2:
                        continue

                    try:
                        yes_price = float(market.outcome_prices[0]) if market.outcome_prices[0] else 0
                        no_price = float(market.outcome_prices[1]) if market.outcome_prices[1] else 0

                        # Determine winning outcome from extreme prices
                        winning_outcome = None
                        if yes_price >= 0.999 and no_price <= 0.001:
                            winning_outcome = 1  # YES wins
                        elif no_price >= 0.999 and yes_price <= 0.001:
                            winning_outcome = 0  # NO wins

                        # Only include if prices are extreme
                        if winning_outcome is not None:
                            condition_id = market.condition_id or market.id
                            if condition_id:
                                outcomes = []
                                if market.outcomes:
                                    outcomes = list(market.outcomes) if isinstance(market.outcomes, list) else [market.outcomes]

                                clob_token_ids = []
                                if market.clob_token_ids:
                                    if isinstance(market.clob_token_ids, list):
                                        clob_token_ids = market.clob_token_ids
                                    elif isinstance(market.clob_token_ids, str):
                                        import json
                                        try:
                                            clob_token_ids = json.loads(market.clob_token_ids)
                                        except (json.JSONDecodeError, TypeError):
                                            pass

                                resolved_markets[condition_id] = {
                                    'market_id': market.id,
                                    'condition_id': condition_id,
                                    'title': market.title,
                                    'winning_outcome': winning_outcome,
                                    'resolution_status': 'PROPOSED',
                                    'resolution_date': market.end_date or datetime.now(timezone.utc),
                                    'polymarket_url': market.polymarket_url,
                                    'outcomes': outcomes,
                                    'clob_token_ids': clob_token_ids
                                }

                                # Cache result in Redis (5min TTL)
                                cache_key = f"redeemable_check:{user_id}:{condition_id}"
                                await self.cache_manager.set(cache_key, "RESOLVED", ttl=self.cache_ttl)

                                logger.debug(
                                    f"🔍 [REDEEM] Found PROPOSED market with extreme prices: "
                                    f"{market.id[:10]}... YES={yes_price:.4f}, NO={no_price:.4f}, "
                                    f"winner={'YES' if winning_outcome == 1 else 'NO'}"
                                )
                    except (ValueError, TypeError, IndexError) as e:
                        logger.debug(f"⚠️ [REDEEM] Error parsing prices for market {market.id}: {e}")
                        continue

                logger.debug(
                    f"🔍 [REDEEM] Batch query found {len(resolved_markets)} resolved markets "
                    f"out of {len(uncached_ids)} checked"
                )

        except Exception as e:
            logger.error(f"❌ [REDEEM] Error querying resolved markets: {e}", exc_info=True)
            return {}

        return resolved_markets

    def _normalize_outcome_from_resolved(self, resolved_outcome: str) -> int:
        """Convert resolved_outcome string to int (0 for NO, 1 for YES)"""
        if resolved_outcome and resolved_outcome.upper() in ['YES', 'Y', '1']:
            return 1
        return 0

    def _normalize_outcome(
        self,
        outcome: str,
        market: Optional[Dict] = None,
        token_id: Optional[str] = None
    ) -> str:
        """
        Normalize outcome to 'YES' or 'NO' for database constraint
        Uses find_outcome_index() for intelligent outcome mapping
        """
        if not outcome:
            logger.warning(f"⚠️ [REDEEM] Empty outcome provided, defaulting to 'NO'")
            return 'NO'

        # METHOD 1: Use token_id to find index in clob_token_ids (most reliable)
        if token_id and market:
            clob_token_ids = market.get('clob_token_ids', [])
            if clob_token_ids and isinstance(clob_token_ids, list):
                try:
                    token_index = -1
                    for i, tid in enumerate(clob_token_ids):
                        if str(tid) == str(token_id):
                            token_index = i
                            break

                    if token_index >= 0:
                        # Index 0 = YES, Index 1 = NO
                        normalized = 'YES' if token_index == 0 else 'NO'
                        logger.debug(f"✅ [REDEEM] Mapped token_id to index {token_index} → '{normalized}'")
                        return normalized
                except Exception as e:
                    logger.debug(f"⚠️ [REDEEM] Error matching token_id: {e}")

        # METHOD 2: Use find_outcome_index() for intelligent outcome mapping
        if market:
            outcomes = market.get('outcomes', [])
            if outcomes and isinstance(outcomes, list):
                outcome_index = find_outcome_index(outcome, outcomes)
                if outcome_index is not None:
                    # Index 0 = YES, Index 1 = NO (for binary markets)
                    normalized = 'YES' if outcome_index == 0 else 'NO'
                    logger.debug(f"✅ [REDEEM] Found outcome '{outcome}' at index {outcome_index} → '{normalized}'")
                    return normalized
                else:
                    logger.warning(f"⚠️ [REDEEM] Could not find outcome '{outcome}' in market outcomes {outcomes}")

        # METHOD 3: Fallback to static mapping for common cases
        outcome_upper = outcome.upper().strip()
        if outcome_upper in ['UP', 'YES', 'Y', 'OVER', 'ABOVE']:
            return 'YES'
        elif outcome_upper in ['DOWN', 'NO', 'N', 'UNDER', 'BELOW']:
            return 'NO'
        else:
            # Default to NO if unknown (log warning)
            logger.warning(f"⚠️ [REDEEM] Unknown outcome '{outcome}', defaulting to 'NO'")
            return 'NO'

    async def _check_position_redeemable(
        self,
        position: Dict,
        market: Dict,
        user_id: int,
        wallet_address: str
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Check if a position is redeemable and create/get resolved_positions record

        Args:
            position: Position data from API (can be active or closed)
            market: Market data from DB (may not be RESOLVED for closed positions)
            user_id: Internal user ID
            wallet_address: User's wallet address

        Returns:
            Tuple of (is_redeemable, resolved_position_dict)
        """
        condition_id = position.get('conditionId', position.get('id', ''))
        if not condition_id:
            logger.warning(f"⚠️ [REDEEM] Position missing conditionId: {position.get('id', 'N/A')}")
            return False, None

        # Log condition_id for debugging
        logger.debug(f"🔍 [REDEEM] Processing position with conditionId: {condition_id}")

        # SPECIAL HANDLING: If this is a CLOSED position with positive PnL from API
        # These are automatically redeemable without needing market resolution
        is_closed_position = position.get('closed', False)
        realized_pnl = position.get('realizedPnl', 0)

        # Extract position data first (needed for closed position handling)
        position_outcome_raw = position.get('outcome', '').upper()
        position_outcome_index = position.get('outcomeIndex', 0)
        tokens_held = float(position.get('size', position.get('totalBought', 0)))
        avg_price = float(position.get('avgPrice', 0))
        token_id = position.get('asset', '')
        title = position.get('title', market.get('title', 'Unknown Market') if market else 'Unknown Market')

        # Filter out dust positions
        if tokens_held < 0.1:
            logger.debug(f"🔍 [REDEEM] Skipping dust position: {tokens_held} tokens")
            return False, None

        # SPECIAL HANDLING: If this is a CLOSED position with positive PnL from API
        # These are automatically redeemable without needing market resolution
        if is_closed_position and realized_pnl > 0:
            logger.info(
                f"🎯 [REDEEM] Found closed winning position: "
                f"{title[:50]}... (+${realized_pnl})"
            )
            logger.debug(
                f"📋 [REDEEM] Closed position details: "
                f"conditionId={condition_id[:30]}..., "
                f"outcome={position_outcome_raw}, "
                f"outcomeIndex={position_outcome_index}, "
                f"tokens={tokens_held}, "
                f"avgPrice={avg_price}"
            )

            # For closed positions with positive PnL, the position outcome is the winning one
            # Determine winning_outcome index from position outcome
            # Index 0 = YES, Index 1 = NO (for binary markets)
            if position_outcome_raw.upper() in ['UP', 'OVER', 'YES', 'Y']:
                winning_outcome_index = 0  # YES wins
            else:
                winning_outcome_index = 1  # NO wins

            # ✅ CRITICAL: Try to find real market_id from DB first
            # This ensures FK constraint is satisfied
            real_market_id_for_closed = None
            try:
                async with get_db() as db:
                    from sqlalchemy import select
                    market_lookup = select(Market.id).where(Market.condition_id == condition_id).limit(1)
                    market_lookup_result = await db.execute(market_lookup)
                    found_market = market_lookup_result.scalar_one_or_none()
                    if found_market:
                        real_market_id_for_closed = found_market
                        logger.debug(f"✅ [REDEEM] Found real market_id {real_market_id_for_closed} for closed position")
            except Exception as lookup_error:
                logger.debug(f"⚠️ [REDEEM] Could not lookup market_id: {lookup_error}")

            # Create a synthetic market dict for closed positions
            synthetic_market = {
                'market_id': real_market_id_for_closed or condition_id,  # Use real market_id if found
                'condition_id': condition_id,
                'title': title,
                'resolution_status': 'RESOLVED',
                'winning_outcome': winning_outcome_index,  # Set winning outcome index
                'resolution_date': datetime.now(timezone.utc)
            }
            market = synthetic_market
            is_winner = True  # Closed position with positive PnL is always a winner
            position_outcome = 'YES' if winning_outcome_index == 0 else 'NO'

            logger.debug(
                f"🔍 [REDEEM] Closed position: outcome_index={position_outcome_index}, "
                f"winning_outcome={winning_outcome_index}, is_winner={is_winner}, "
                f"market_id={synthetic_market['market_id']}"
            )
        else:
            # Check if market has winning outcome (for active positions in resolved markets)
            winning_outcome = market.get('winning_outcome')
            if winning_outcome is None:
                return False, None

            # ✅ CRITICAL FIX: Compare outcome indices directly
            # winning_outcome is the INDEX of the winning outcome (0 or 1)
            # position_outcome_index is the index of this position's outcome (0 or 1)
            is_winner = (position_outcome_index == winning_outcome)

            logger.debug(
                f"🔍 [REDEEM] Position outcome_index={position_outcome_index}, "
                f"winning_outcome={winning_outcome}, is_winner={is_winner}"
            )

            # Normalize outcome using dynamic mapping from market outcomes
            position_outcome = self._normalize_outcome(
                position_outcome_raw,
                market=market,
                token_id=token_id
            )

        # Create resolved_position record (for both closed positions with PnL and active positions in resolved markets)
        if is_closed_position and realized_pnl > 0:
            # For closed positions with positive PnL, create resolved_position record
            # Use the real_market_id found earlier, or fallback to condition_id (will be resolved in _get_or_create_resolved_position)
            market_id_to_use = market.get('market_id', condition_id)
            logger.info(
                f"🔍 [REDEEM] Creating resolved_position for closed position: "
                f"market_id={market_id_to_use}, condition_id={condition_id[:20]}..., "
                f"market dict keys: {list(market.keys()) if market else 'empty'}"
            )
            resolved_pos = await self._get_or_create_resolved_position(
                user_id=user_id,
                condition_id=condition_id,
                market_id=market_id_to_use,
                market_title=title,
                position_outcome=position_outcome,
                position_id=token_id,
                tokens_held=tokens_held,
                avg_price=avg_price,
                winning_outcome_num=winning_outcome_index,
                is_winner=is_winner,
                resolution_date=market.get('resolution_date') or datetime.now(timezone.utc)
            )

            if resolved_pos:
                logger.info(
                    f"✅ [REDEEM] Successfully created/retrieved resolved_position for closed position: "
                    f"condition_id={condition_id[:20]}..., market_id={market_id_to_use}, "
                    f"is_winner={is_winner}, net_value=${resolved_pos.get('net_value', 0):.2f}"
                )
            else:
                logger.error(
                    f"❌ [REDEEM] Failed to create resolved_position for closed position: "
                    f"condition_id={condition_id[:20]}..., market_id={market_id_to_use}"
                )
                return False, None  # Return early if creation failed
        else:
            # For active positions in resolved markets, create resolved_position record
            resolved_pos = await self._get_or_create_resolved_position(
                user_id=user_id,
                condition_id=condition_id,
                market_id=market.get('market_id', condition_id),
                market_title=title,
                position_outcome=position_outcome,
                position_id=token_id,  # token_id from position is the clob_token_id (position_id)
                tokens_held=tokens_held,
                avg_price=avg_price,
                winning_outcome_num=winning_outcome,
                is_winner=is_winner,
                resolution_date=market.get('resolution_date') or datetime.now(timezone.utc)
            )

        # Return True for both winners and losers (they should be filtered from active positions)
        return True, resolved_pos

    async def _get_or_create_resolved_position(
        self,
        user_id: int,
        condition_id: str,
        market_id: str,
        market_title: str,
        position_outcome: str,
        position_id: str,  # Changed from token_id to position_id (clob_token_id)
        tokens_held: float,
        avg_price: float,
        winning_outcome_num: int,
        is_winner: bool,
        resolution_date: datetime
    ) -> Optional[Dict]:
        """
        Get existing resolved_position or create new one (lazy creation)
        Handles both winners and losers

        Returns:
            resolved_position dict ready for display
        """
        logger.info(
            f"🔍 [REDEEM] _get_or_create_resolved_position called: "
            f"user_id={user_id}, condition_id={condition_id[:20]}..., "
            f"market_id={market_id}, is_winner={is_winner}, tokens_held={tokens_held}"
        )
        try:
            async with get_db() as db:
                from sqlalchemy import select

                # ✅ CRITICAL FIX: Find the real market_id from markets table
                # market_id parameter might be condition_id, we need the actual market.id (numeric)
                real_market_id = market_id

                # Always try to find market by condition_id first (most reliable)
                logger.info(f"🔍 [REDEEM] Looking up market_id for condition_id {condition_id[:20]}... (full: {condition_id})")

                # Try exact match first
                market_query = select(Market.id).where(Market.condition_id == condition_id).limit(1)
                market_result = await db.execute(market_query)
                found_market_id = market_result.scalar_one_or_none()

                # If not found, try case-insensitive match (some condition_ids might have different casing)
                if not found_market_id:
                    logger.debug(f"⚠️ [REDEEM] Exact match failed, trying case-insensitive search...")
                    from sqlalchemy import func
                    market_query_ci = select(Market.id).where(func.lower(Market.condition_id) == func.lower(condition_id)).limit(1)
                    market_result_ci = await db.execute(market_query_ci)
                    found_market_id = market_result_ci.scalar_one_or_none()

                if found_market_id:
                    real_market_id = found_market_id
                    logger.info(f"✅ [REDEEM] Found market_id {real_market_id} for condition_id {condition_id[:20]}...")
                elif market_id == condition_id or (market_id.startswith('0x') and len(market_id) > 20):
                    # market_id is actually a condition_id and not found in DB
                    # This can happen for very old closed positions
                    logger.warning(
                        f"⚠️ [REDEEM] Market not found in DB for condition_id {condition_id[:20]}... "
                        f"This may be an old closed position. Trying to create minimal market entry..."
                    )
                    try:
                        # Generate a unique numeric ID for the market (use hash of condition_id)
                        import hashlib
                        hash_obj = hashlib.md5(condition_id.encode())
                        numeric_id = str(int(hash_obj.hexdigest()[:8], 16))[:10]  # First 10 digits of hash

                        # Create minimal market entry for closed positions
                        new_market = Market(
                            id=numeric_id,  # Use numeric ID derived from condition_id
                            condition_id=condition_id,
                            title=market_title[:500] if len(market_title) > 500 else market_title,
                            source='closed_position',
                            is_resolved=True,
                            resolved_outcome='YES' if winning_outcome_num == 1 else 'NO',
                            resolved_at=resolution_date,
                            is_active=False,
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc)
                        )
                        db.add(new_market)
                        await db.flush()  # Flush to get the ID without committing
                        real_market_id = numeric_id
                        logger.info(f"✅ [REDEEM] Created minimal market entry {real_market_id} for closed position")
                    except Exception as create_error:
                        logger.error(
                            f"❌ [REDEEM] Failed to create market entry: {create_error}. "
                            f"Market may already exist. Trying to find it again..."
                        )
                        # Try to find it again (might have been created by another process)
                        market_query_retry = select(Market.id).where(Market.condition_id == condition_id).limit(1)
                        market_result_retry = await db.execute(market_query_retry)
                        found_market_id_retry = market_result_retry.scalar_one_or_none()
                        if found_market_id_retry:
                            real_market_id = found_market_id_retry
                            logger.info(f"✅ [REDEEM] Found market_id {real_market_id} on retry")
                        else:
                            # Last resort: skip this position (can't create without valid market_id)
                            logger.error(
                                f"❌ [REDEEM] Cannot create resolved_position: market {condition_id[:20]}... "
                                f"does not exist and cannot be created. Skipping."
                            )
                            return None

                # Check if record already exists
                existing_query = select(ResolvedPosition).where(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.condition_id == condition_id
                )
                result = await db.execute(existing_query)
                existing = result.scalar_one_or_none()

                if existing:
                    logger.debug(
                        f"✅ [REDEEM] Found existing resolved_position #{existing.id} "
                        f"for user={user_id}, condition={condition_id[:10]}..."
                    )
                    return existing.to_dict()

                # Calculate values based on winner/loser
                winning_outcome_str = 'YES' if winning_outcome_num == 1 else 'NO'
                total_cost = Decimal(str(tokens_held * avg_price))

                if is_winner:
                    # Winner: tokens worth 1 USDC each
                    gross_value = Decimal(str(tokens_held * 1.0))
                    fee_amount = gross_value * Decimal('0.01')  # 1% fee
                    net_value = gross_value - fee_amount
                    pnl = net_value - total_cost
                    pnl_percentage = (pnl / total_cost * Decimal('100')) if total_cost > 0 else Decimal('0')
                else:
                    # Loser: tokens worth 0
                    gross_value = Decimal('0')
                    fee_amount = Decimal('0')
                    net_value = Decimal('0')
                    pnl = -total_cost  # Loss = negative of investment
                    pnl_percentage = Decimal('-100.00')  # -100% loss

                # Create new record
                resolved_pos = ResolvedPosition(
                    user_id=user_id,
                    market_id=real_market_id,  # Use resolved market_id
                    condition_id=condition_id,
                    market_title=market_title,
                    outcome=position_outcome,
                    position_id=position_id,  # Changed from token_id to position_id
                    tokens_held=Decimal(str(tokens_held)),
                    total_cost=total_cost,
                    avg_buy_price=Decimal(str(avg_price)),
                    winning_outcome=winning_outcome_str,
                    is_winner=is_winner,
                    resolved_at=resolution_date,
                    gross_value=gross_value,
                    fee_amount=fee_amount,
                    net_value=net_value,
                    pnl=pnl,
                    pnl_percentage=pnl_percentage,
                    status='PENDING',
                    notified=False
                )

                db.add(resolved_pos)
                await db.commit()
                await db.refresh(resolved_pos)

                logger.info(
                    f"✅ [REDEEM] Created resolved_position #{resolved_pos.id} "
                    f"for user={user_id}, market={real_market_id[:10]}..., "
                    f"is_winner={is_winner}, net_value=${float(net_value):.2f}"
                )

                return resolved_pos.to_dict()

        except Exception as e:
            logger.error(f"❌ [REDEEM] Error creating resolved_position: {e}", exc_info=True)
            # If FK constraint violation, try to find/create market first
            if "ForeignKeyViolation" in str(e) or "foreign key constraint" in str(e).lower():
                logger.warning(
                    f"⚠️ [REDEEM] FK constraint violation - market {market_id[:20]}... may not exist in markets table. "
                    f"Trying to find or create market entry..."
                )
                # Try to get market via API or create a minimal entry
                # For now, return None and log the issue
                return None
            return None


# Singleton instance
_detector = None


def get_redeemable_detector() -> RedeemablePositionDetector:
    """Get singleton instance"""
    global _detector
    if _detector is None:
        _detector = RedeemablePositionDetector()
    return _detector
