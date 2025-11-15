"""
Redeemable Position Detector Service
Detects positions that are redeemable (in RESOLVED markets with winning tokens)
"""

import logging
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from database import SessionLocal, ResolvedPosition, SubsquidMarketPoll
from core.services.redis_price_cache import get_redis_cache

logger = logging.getLogger(__name__)


class RedeemablePositionDetector:
    """Detects and creates redeemable position records"""

    @staticmethod
    async def get_redeemable_positions_from_db(user_id: int) -> List[Dict]:
        """✅ NEW: Get redeemable positions directly from user_positions table

        Much more efficient than API calls - uses pre-computed data.

        Args:
            user_id: Telegram user ID

        Returns:
            List of redeemable position dicts
        """
        try:
            from database import SessionLocal
            from decimal import Decimal

            with SessionLocal() as db:
                # Get user by telegram_user_id
                user = db.query(db.table('users')).filter(
                    db.table('users').telegram_user_id == user_id
                ).first()

                if not user:
                    logger.warning(f"User {user_id} not found")
                    return []

                # Get redeemable positions from user_positions
                positions = db.execute("""
                    SELECT
                        up.*,
                        smp.title,
                        smp.outcomes,
                        smp.winning_outcome
                    FROM user_positions up
                    JOIN subsquid_markets_poll smp ON up.market_id = smp.market_id
                    WHERE up.user_id = :user_id
                      AND up.redeemable = true
                      AND smp.resolution_status = 'RESOLVED'
                """, {'user_id': str(user.telegram_user_id)}).fetchall()

                redeemable_positions = []
                for pos in positions:
                    redeemable_positions.append({
                        'user_id': user_id,
                        'condition_id': pos.condition_id,
                        'market_id': pos.market_id,
                        'asset': pos.asset,
                        'outcome': pos.outcome,
                        'outcome_index': pos.outcome_index,
                        'size': Decimal(str(pos.size)),
                        'current_value': Decimal(str(pos.current_value or 0)),
                        'cash_pnl': Decimal(str(pos.cash_pnl or 0)),
                        'winning_outcome': pos.winning_outcome,
                        'title': pos.title,
                        'end_date': pos.end_date
                    })

                logger.info(f"✅ Found {len(redeemable_positions)} redeemable positions in DB for user {user_id}")
                return redeemable_positions

        except Exception as e:
            logger.error(f"❌ Failed to get redeemable positions from DB: {e}")
            return []

    @staticmethod
    def _normalize_outcome(outcome: str, market: Optional[Dict] = None, token_id: Optional[str] = None) -> str:
        """
        Normalize outcome to 'YES' or 'NO' for database constraint
        Uses dynamic mapping based on market outcomes list if available

        Args:
            outcome: Raw outcome from API (e.g., 'UP', 'DOWN', 'YES', 'NO', 'OVER', 'UNDER')
            market: Market dict with 'outcomes' and 'clob_token_ids' arrays (optional)
            token_id: Token ID from position (optional, for token-based matching)

        Returns:
            Normalized outcome: 'YES' (index 0) or 'NO' (index 1)
        """
        outcome_upper = outcome.upper().strip()

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

        # METHOD 2: Use outcome name to find index in outcomes array
        if market:
            outcomes = market.get('outcomes', [])
            if outcomes and isinstance(outcomes, list):
                try:
                    # Try exact match
                    for i, market_outcome in enumerate(outcomes):
                        if isinstance(market_outcome, str) and market_outcome.upper().strip() == outcome_upper:
                            normalized = 'YES' if i == 0 else 'NO'
                            logger.debug(f"✅ [REDEEM] Found outcome '{outcome}' at index {i} → '{normalized}'")
                            return normalized

                    # Try normalized matching (remove special chars)
                    import re
                    outcome_normalized = re.sub(r'[^\w]', '', outcome_upper)
                    for i, market_outcome in enumerate(outcomes):
                        if isinstance(market_outcome, str):
                            market_outcome_normalized = re.sub(r'[^\w]', '', market_outcome.upper().strip())
                            if market_outcome_normalized == outcome_normalized:
                                normalized = 'YES' if i == 0 else 'NO'
                                logger.debug(f"✅ [REDEEM] Found normalized outcome '{outcome}' at index {i} → '{normalized}'")
                                return normalized
                except Exception as e:
                    logger.debug(f"⚠️ [REDEEM] Error matching outcome name: {e}")

        # METHOD 3: Fallback to static mapping for common cases
        if outcome_upper in ['UP', 'YES', 'Y', 'OVER', 'ABOVE']:
            return 'YES'
        elif outcome_upper in ['DOWN', 'NO', 'N', 'UNDER', 'BELOW']:
            return 'NO'
        else:
            # Default to NO if unknown (log warning)
            logger.warning(f"⚠️ [REDEEM] Unknown outcome '{outcome}', defaulting to 'NO'")
            return 'NO'

    @staticmethod
    def detect_redeemable_positions(
        positions_data: List[Dict],
        user_id: int,
        wallet_address: str
    ) -> Tuple[List[Dict], List[str]]:
        """
        Detect which positions are redeemable and separate them from active positions

        Args:
            positions_data: Raw position data from blockchain API
            user_id: Telegram user ID
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
        closed_positions = [p for p in positions_data if p.get('closed', False) and p.get('realizedPnl', 0) > 0]
        active_condition_ids = [cid for cid in condition_ids if not any(p.get('conditionId') == cid and p.get('closed') for p in positions_data)]

        # For active positions, query resolved markets
        resolved_markets = {}
        if active_condition_ids:
            resolved_markets = RedeemablePositionDetector._batch_query_resolved_markets(
                active_condition_ids, user_id
            )

        if not resolved_markets and not closed_positions:
            logger.debug(f"🔍 [REDEEM] No resolved markets found for {len(active_condition_ids)} active condition_ids and no closed positions")
            return [], []

        # Detect resolved positions (both winners and losers)
        redeemable_positions = []  # Only winners for display
        resolved_condition_ids = set()  # Both winners and losers to filter from active

        # Process closed positions first (don't need market resolution)
        for position in closed_positions:
            condition_id = position.get('conditionId', position.get('id', ''))
            if not condition_id:
                continue

            realized_pnl = position.get('realizedPnl', 0)

            # Handle closed positions with positive PnL (automatically redeemable)
            is_resolved, resolved_pos = RedeemablePositionDetector._check_position_redeemable(
                position, {}, user_id, wallet_address  # Empty market dict, handled internally
            )

            if is_resolved:
                if resolved_pos:
                    # Add to filter list (winners)
                    resolved_condition_ids.add(condition_id)

                    # Add winners to redeemable_positions (for display)
                    if resolved_pos.get('is_winner'):
                        redeemable_positions.append(resolved_pos)
                        logger.info(
                            f"💰 [REDEEM] Detected winning CLOSED position: "
                            f"user={user_id}, market={condition_id[:10]}..., "
                            f"outcome={position.get('outcome')}, pnl=${realized_pnl}"
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
            is_resolved, resolved_pos = RedeemablePositionDetector._check_position_redeemable(
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

    @staticmethod
    def _batch_query_resolved_markets(
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
        redis_cache = get_redis_cache()
        resolved_markets = {}
        uncached_ids = []

        # Check Redis cache first
        if redis_cache.enabled:
            for condition_id in condition_ids:
                cache_key = f"redeemable_check:{user_id}:{condition_id}"
                cached_result = redis_cache.redis_client.get(cache_key)

                if cached_result:
                    # Cache hit - check if it's resolved
                    if cached_result == "RESOLVED":
                        # Still need to fetch market data from DB
                        uncached_ids.append(condition_id)
                    # If cached as "NOT_RESOLVED", skip DB query
                    logger.debug(f"✅ [REDEEM CACHE] Hit for {condition_id[:10]}...")
                else:
                    uncached_ids.append(condition_id)
        else:
            uncached_ids = condition_ids

        if not uncached_ids:
            # All cached, but we still need market data for resolved ones
            # Re-query DB for resolved markets (but fewer now)
            uncached_ids = condition_ids

        # Batch query DB for uncached markets
        # Include both RESOLVED markets AND PROPOSED markets with extreme prices
        try:
            with SessionLocal() as db:
                # Query RESOLVED markets (existing logic)
                resolved_markets_query = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.condition_id.in_(uncached_ids),
                    SubsquidMarketPoll.resolution_status == 'RESOLVED',
                    SubsquidMarketPoll.winning_outcome.isnot(None)
                ).all()

                # Query PROPOSED markets with extreme prices (new logic)
                # These markets have extreme prices indicating resolution, even if not officially RESOLVED yet
                proposed_extreme_query = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.condition_id.in_(uncached_ids),
                    SubsquidMarketPoll.resolution_status == 'PROPOSED',
                    SubsquidMarketPoll.winning_outcome.is_(None),
                    SubsquidMarketPoll.end_date.isnot(None),
                    SubsquidMarketPoll.end_date < datetime.utcnow() - timedelta(hours=1),
                    SubsquidMarketPoll.outcome_prices.isnot(None)
                ).all()

                # Process RESOLVED markets
                for market in resolved_markets_query:
                    condition_id = market.condition_id or market.market_id
                    if condition_id:
                        # Parse outcomes and clob_token_ids for dynamic outcome mapping
                        outcomes = []
                        if market.outcomes:
                            outcomes = list(market.outcomes)

                        clob_token_ids = []
                        if market.clob_token_ids:
                            try:
                                import json
                                if isinstance(market.clob_token_ids, str):
                                    clob_token_ids = json.loads(market.clob_token_ids)
                                elif isinstance(market.clob_token_ids, list):
                                    clob_token_ids = market.clob_token_ids
                            except (json.JSONDecodeError, TypeError):
                                pass

                        resolved_markets[condition_id] = {
                            'market_id': market.market_id,
                            'condition_id': condition_id,
                            'title': market.title,
                            'winning_outcome': market.winning_outcome,
                            'resolution_status': market.resolution_status,
                            'resolution_date': market.resolution_date,
                            'polymarket_url': market.polymarket_url,
                            'outcomes': outcomes,  # For dynamic outcome mapping
                            'clob_token_ids': clob_token_ids  # For token_id-based matching
                        }

                        # Cache result in Redis (5min TTL)
                        if redis_cache.enabled:
                            cache_key = f"redeemable_check:{user_id}:{condition_id}"
                            redis_cache.redis_client.setex(cache_key, 300, "RESOLVED")

                # Process PROPOSED markets with extreme prices
                for market in proposed_extreme_query:
                    # Check if prices are extreme (>= 0.99 and <= 0.01)
                    if not market.outcome_prices or len(market.outcome_prices) != 2:
                        continue

                    try:
                        yes_price = float(market.outcome_prices[0]) if market.outcome_prices[0] else 0
                        no_price = float(market.outcome_prices[1]) if market.outcome_prices[1] else 0

                        # Determine winning outcome from extreme prices
                        winning_outcome = None
                        if yes_price >= 0.99 and no_price <= 0.01:
                            winning_outcome = 1  # YES wins
                        elif no_price >= 0.99 and yes_price <= 0.01:
                            winning_outcome = 0  # NO wins

                        # Only include if prices are extreme
                        if winning_outcome is not None:
                            condition_id = market.condition_id or market.market_id
                            if condition_id:
                                # Parse outcomes and clob_token_ids for dynamic outcome mapping
                                outcomes = []
                                if market.outcomes:
                                    outcomes = list(market.outcomes)

                                clob_token_ids = []
                                if market.clob_token_ids:
                                    try:
                                        import json
                                        if isinstance(market.clob_token_ids, str):
                                            clob_token_ids = json.loads(market.clob_token_ids)
                                        elif isinstance(market.clob_token_ids, list):
                                            clob_token_ids = market.clob_token_ids
                                    except (json.JSONDecodeError, TypeError):
                                        pass

                                resolved_markets[condition_id] = {
                                    'market_id': market.market_id,
                                    'condition_id': condition_id,
                                    'title': market.title,
                                    'winning_outcome': winning_outcome,  # Calculated from prices
                                    'resolution_status': 'PROPOSED',  # Still PROPOSED, but treat as resolved
                                    'resolution_date': market.end_date or market.updated_at,  # Use end_date as resolution date
                                    'polymarket_url': market.polymarket_url,
                                    'outcomes': outcomes,  # For dynamic outcome mapping
                                    'clob_token_ids': clob_token_ids  # For token_id-based matching
                                }

                                # Cache result in Redis (5min TTL)
                                if redis_cache.enabled:
                                    cache_key = f"redeemable_check:{user_id}:{condition_id}"
                                    redis_cache.redis_client.setex(cache_key, 300, "RESOLVED")

                                logger.debug(
                                    f"🔍 [REDEEM] Found PROPOSED market with extreme prices: "
                                    f"{market.market_id[:10]}... YES={yes_price:.4f}, NO={no_price:.4f}, "
                                    f"winner={'YES' if winning_outcome == 1 else 'NO'}"
                                )
                    except (ValueError, TypeError, IndexError) as e:
                        logger.debug(f"⚠️ [REDEEM] Error parsing prices for market {market.market_id}: {e}")
                        continue

                # Count PROPOSED with extreme prices that were included
                proposed_extreme_count = sum(1 for market in proposed_extreme_query
                    if market.outcome_prices and len(market.outcome_prices) == 2
                    and ((float(market.outcome_prices[0]) >= 0.99 and float(market.outcome_prices[1]) <= 0.01)
                         or (float(market.outcome_prices[1]) >= 0.99 and float(market.outcome_prices[0]) <= 0.01)))

                logger.debug(
                    f"🔍 [REDEEM] Batch query found {len(resolved_markets)} resolved markets "
                    f"({len(resolved_markets_query)} RESOLVED + {proposed_extreme_count} PROPOSED with extreme prices) "
                    f"out of {len(uncached_ids)} checked"
                )

        except Exception as e:
            logger.error(f"❌ [REDEEM] Error querying resolved markets: {e}", exc_info=True)
            return {}

        return resolved_markets

    @staticmethod
    def _check_position_redeemable(
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
            user_id: Telegram user ID
            wallet_address: User's wallet address

        Returns:
            Tuple of (is_redeemable, resolved_position_dict)
        """
        condition_id = position.get('conditionId', position.get('id', ''))
        if not condition_id:
            return False, None

        # SPECIAL HANDLING: If this is a CLOSED position with positive PnL from API
        # These are automatically redeemable without needing market resolution
        is_closed_position = position.get('closed', False)
        realized_pnl = position.get('realizedPnl', 0)

        if is_closed_position and realized_pnl > 0:
            logger.info(f"🎯 [REDEEM] Found closed winning position: {position.get('title', 'Unknown')[:50]}... (+${realized_pnl})")
            # Create a synthetic market dict for closed positions
            synthetic_market = {
                'market_id': condition_id,
                'condition_id': condition_id,
                'title': position.get('title', 'Unknown Market'),
                'resolution_status': 'RESOLVED',  # We know it's resolved
                'winning_outcome': None  # We'll determine from position data
            }
            market = synthetic_market

        # Extract position data
        position_outcome_raw = position.get('outcome', '').upper()
        position_outcome_index = position.get('outcomeIndex', 0)
        tokens_held = float(position.get('size', position.get('totalBought', 0)))
        avg_price = float(position.get('avgPrice', 0))
        token_id = position.get('asset', '')
        title = position.get('title', market.get('title', 'Unknown Market'))

        # Filter out dust positions
        if tokens_held < 0.1:
            logger.debug(f"🔍 [REDEEM] Skipping dust position: {tokens_held} tokens")
            return False, None

        # Check if market has winning outcome
        winning_outcome = market.get('winning_outcome')
        if winning_outcome is None:
            return False, None

        # ✅ CRITICAL FIX: Compare outcome indices directly
        # winning_outcome is the INDEX of the winning outcome (0 or 1)
        # position_outcome_index is the index of this position's outcome (0 or 1)
        is_winner = (position_outcome_index == winning_outcome)

        logger.debug(f"🔍 [REDEEM] Position outcome_index={position_outcome_index}, winning_outcome={winning_outcome}, is_winner={is_winner}")

        # For closed positions, we can infer winning outcome from positive PnL
        if is_closed_position and realized_pnl > 0:
            # If it's a closed position with positive PnL, the outcome won
            position_outcome = position_outcome_raw
            # For closed positions with positive PnL, the position outcome is the winning one
            # Convert to YES/NO format for consistency
            if position_outcome_raw.upper() in ['UP', 'OVER', 'YES']:
                position_outcome = 'YES'
            else:
                position_outcome = 'NO'
        else:
            # Normalize outcome using dynamic mapping from market outcomes
            position_outcome = RedeemablePositionDetector._normalize_outcome(
                position_outcome_raw,
                market=market,
                token_id=token_id
            )

        # Position is in resolved market! Get or create resolved_positions record (both winners and losers)
        resolved_pos = RedeemablePositionDetector._get_or_create_resolved_position(
            user_id=user_id,
            condition_id=condition_id,
            market_id=market.get('market_id', condition_id),
            market_title=title,
            position_outcome=position_outcome,
            token_id=token_id,
            tokens_held=tokens_held,
            avg_price=avg_price,
            winning_outcome_num=winning_outcome,
            is_winner=is_winner,
            resolution_date=market.get('resolution_date') or datetime.utcnow()
        )

        # Return True for both winners and losers (they should be filtered from active positions)
        return True, resolved_pos

    @staticmethod
    def _get_or_create_resolved_position(
        user_id: int,
        condition_id: str,
        market_id: str,
        market_title: str,
        position_outcome: str,
        token_id: str,
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
        try:
            with SessionLocal() as db:
                # Check if record already exists
                existing = db.query(ResolvedPosition).filter(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.condition_id == condition_id
                ).first()

                if existing:
                    logger.debug(
                        f"✅ [REDEEM] Found existing resolved_position #{existing.id} "
                        f"for user={user_id}, condition={condition_id[:10]}..."
                    )
                    return existing.to_dict()

                # Calculate values based on winner/loser
                winning_outcome_str = 'YES' if winning_outcome_num == 1 else 'NO'
                total_cost = Decimal(str(tokens_held * avg_price))  # Convert to Decimal immediately

                if is_winner:
                    # Winner: tokens worth 1 USDC each
                    gross_value = Decimal(str(tokens_held * 1.0))  # Convert to Decimal
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
                    market_id=market_id,
                    condition_id=condition_id,
                    market_title=market_title,
                    outcome=position_outcome,
                    token_id=token_id,
                    tokens_held=Decimal(str(tokens_held)),
                    total_cost=total_cost,  # Already Decimal
                    avg_buy_price=Decimal(str(avg_price)),
                    transaction_count=1,
                    winning_outcome=winning_outcome_str,
                    is_winner=is_winner,
                    resolved_at=resolution_date,
                    gross_value=gross_value,  # Already Decimal
                    fee_amount=fee_amount,  # Already Decimal
                    net_value=net_value,  # Already Decimal
                    pnl=pnl,  # Already Decimal
                    pnl_percentage=pnl_percentage,  # Already Decimal
                    status='PENDING',
                    notified=False  # Will be set to True after notification sent
                )

                db.add(resolved_pos)
                db.commit()
                db.refresh(resolved_pos)

                logger.info(
                    f"✅ [REDEEM] Created resolved_position #{resolved_pos.id} "
                    f"for user={user_id}, market={market_id[:10]}..., "
                    f"is_winner={is_winner}, net_value=${float(net_value):.2f}"
                )

                # Send notification ONLY for losers (winners will see it in /positions)
                if not resolved_pos.notified and not is_winner:
                    RedeemablePositionDetector._send_notification(user_id, resolved_pos)
                    logger.info(f"📨 [NOTIFICATION] Sent loss notification to user {user_id}")
                elif is_winner:
                    # Mark as notified for winners (no notification needed)
                    resolved_pos.notified = True
                    db.commit()
                    logger.info(f"🎉 [NOTIFICATION] Skipped win notification (user will see in /positions)")

                return resolved_pos.to_dict()

        except Exception as e:
            logger.error(f"❌ [REDEEM] Error creating resolved_position: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Return None - caller will handle gracefully
            return None

    @staticmethod
    def _send_notification(user_id: int, resolved_pos: ResolvedPosition) -> None:
        """
        Send Telegram notification for newly resolved position
        ONLY sends notifications for LOSERS (winners see it in /positions)
        Uses background thread to avoid blocking
        """
        try:
            import threading
            from telegram_bot.services.resolution_notification_service import send_resolution_notification
            import asyncio

            def send_in_thread():
                """Send notification in background thread"""
                try:
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Send notification
                    success = loop.run_until_complete(
                        send_resolution_notification(user_id, resolved_pos)
                    )

                    # Update notified flag in DB if notification succeeded
                    if success:
                        try:
                            with SessionLocal() as db:
                                pos = db.query(ResolvedPosition).filter(
                                    ResolvedPosition.id == resolved_pos.id
                                ).first()
                                if pos:
                                    pos.notified = True
                                    pos.notification_sent_at = datetime.utcnow()
                                    db.commit()
                                    logger.debug(f"✅ [NOTIFICATION] Marked as notified for position #{resolved_pos.id}")
                        except Exception as db_error:
                            logger.warning(f"⚠️ [NOTIFICATION] Failed to update notified flag: {db_error}")

                    loop.close()
                except Exception as thread_error:
                    logger.error(f"❌ [NOTIFICATION] Thread error: {thread_error}")

            # Start notification in background thread (non-blocking)
            thread = threading.Thread(target=send_in_thread, daemon=True)
            thread.start()
            logger.debug(f"📨 [NOTIFICATION] Started notification thread for user {user_id}, position #{resolved_pos.id}")

        except Exception as e:
            logger.error(f"❌ [NOTIFICATION] Error setting up notification: {e}")
            # Don't break flow if notification fails


def get_redeemable_position_detector() -> RedeemablePositionDetector:
    """Get singleton instance"""
    return RedeemablePositionDetector()
