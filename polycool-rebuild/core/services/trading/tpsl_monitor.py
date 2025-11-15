"""
TP/SL Monitor - Background task for monitoring Take Profit / Stop Loss orders
Continuously monitors positions with TP/SL and triggers automatic sells when targets are hit
"""
import asyncio
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy import select, and_, or_

from core.database.connection import get_db
from core.database.models import Position, Market
from core.services.position.position_service import position_service
from core.services.position.price_updater import extract_position_price
from core.services.position.outcome_helper import find_outcome_index
from core.services.clob.clob_service import get_clob_service
from core.services.market_service import get_market_service
from core.services.user.user_service import user_service
from core.services.cache_manager import CacheManager
from core.services.notification_service import get_notification_service
from core.models.notification_models import Notification, NotificationType, NotificationPriority
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)
cache_manager = CacheManager()

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


class PositionFromAPI:
    """Simple position object from API response for TP/SL monitoring"""
    def __init__(self, data):
        self.id = data.get('id')
        self.user_id = data.get('user_id', 1)  # Default to user 1 for API mode
        self.market_id = data.get('market_id')
        self.outcome = data.get('outcome')
        self.amount = float(data.get('amount', 0))
        self.entry_price = float(data.get('entry_price', 0))
        self.current_price = float(data.get('current_price', 0)) if data.get('current_price') else None
        self.take_profit_price = float(data.get('take_profit_price')) if data.get('take_profit_price') else None
        self.stop_loss_price = float(data.get('stop_loss_price')) if data.get('stop_loss_price') else None
        self.status = data.get('status', 'active')  # ✅ Ensure status attribute exists


class TPSLMonitor:
    """
    Background task that continuously monitors TP/SL orders
    - HYBRID APPROACH: WebSocket triggers (< 100ms) + Polling fallback (10s)
    - Checks every 10 seconds (polling mode)
    - WebSocket-triggered checks for instant TP/SL execution
    - Batch checks all positions with TP/SL
    - Rate limited: max 100 positions per cycle
    - Batch updates positions
    - Uses centralized notification service for Telegram messages
    """

    def __init__(self, check_interval: int = 10):
        """
        Initialize TP/SL Monitor

        Args:
            check_interval: Seconds between checks (default: 10)
        """
        self.check_interval = check_interval
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None
        self.max_positions_per_cycle = 100  # Rate limit: max 100 positions per cycle

    async def start(self) -> None:
        """Start the monitoring background task"""
        if self.running:
            logger.warning("⚠️ TP/SL Monitor already running")
            return

        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"🚀 TP/SL Monitor started (check interval: {self.check_interval}s)")

    async def stop(self) -> None:
        """Stop the monitoring background task"""
        if not self.running:
            return

        self.running = False
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 TP/SL Monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop"""
        logger.info("🔄 TP/SL Monitor loop started")

        while self.running:
            try:
                await self._check_all_active_orders()
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("🛑 TP/SL Monitor loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ TP/SL Monitor loop error: {e}")
                await asyncio.sleep(self.check_interval)

    async def _check_all_active_orders(self) -> None:
        """
        Check all positions with active TP/SL orders
        Uses batch query for efficiency (DB or API depending on SKIP_DB mode)
        """
        try:
            positions = []

            if SKIP_DB:
                # ✅ SKIP_DB mode: Use API client to get positions with TP/SL
                logger.debug("🔍 TP/SL Monitor: Using API client (SKIP_DB=true)")
                api_client = get_api_client()

                # Get all users and their positions (we need to check all users since TP/SL monitor runs globally)
                # In a production system, this would be optimized, but for now we'll get positions for known users
                # For now, we'll focus on user_id=1 (the main user) since that's what's in the logs
                user_positions_data = await api_client.get_user_positions(user_id=1, use_cache=False)

                if user_positions_data and 'positions' in user_positions_data:
                    for pos_data in user_positions_data['positions']:
                        # Only include active positions with TP/SL set
                        if (pos_data.get('status') == 'active' and
                            (pos_data.get('take_profit_price') is not None or
                             pos_data.get('stop_loss_price') is not None)):
                            # Create a position-like object from API data
                            positions.append(self._api_position_to_position_obj(pos_data))

                logger.info(f"🔍 TP/SL Monitor (API): Found {len(positions)} positions with TP/SL for user 1")
            else:
                # Standard DB mode
                logger.debug("🔍 TP/SL Monitor: Using direct DB access (SKIP_DB=false)")
                async with get_db() as db:
                    result = await db.execute(
                        select(Position)
                        .where(
                            and_(
                                Position.status == "active",
                                or_(
                                    Position.take_profit_price.isnot(None),
                                    Position.stop_loss_price.isnot(None)
                                )
                            )
                        )
                        .limit(self.max_positions_per_cycle)
                    )
                    positions = list(result.scalars().all())
                logger.info(f"🔍 TP/SL Monitor (DB): Found {len(positions)} positions with TP/SL")

            if not positions:
                logger.debug("📭 No positions with TP/SL to monitor")
                return

            # Get markets for positions (batch)
            market_ids = list(set(p.market_id for p in positions))
            markets_map = await self._get_markets_batch(market_ids)

            # Check each position
            triggered_positions = []
            for position in positions:
                try:
                    market = markets_map.get(position.market_id)
                    if not market:
                        logger.warning(f"⚠️ Market {position.market_id} not found for position {position.id}")
                        continue

                    # Get current price
                    current_price = await self._get_current_price(position, market)
                    if current_price is None:
                        logger.debug(f"⚠️ Could not get price for position {position.id}")
                        continue

                    # Check TP/SL conditions
                    triggered = await self._check_tpsl_conditions(position, current_price)
                    if triggered:
                        triggered_positions.append((position, triggered, current_price))

                except Exception as e:
                    logger.error(f"❌ Error checking position {position.id}: {e}")
                    continue

            # Execute sells for triggered positions (batch)
            if triggered_positions:
                await self._execute_triggered_sells(triggered_positions)

            logger.debug(f"✅ TP/SL check cycle completed - {len(positions)} positions checked")

        except Exception as e:
            logger.error(f"❌ Error checking TP/SL orders: {e}")

    def _api_position_to_position_obj(self, pos_data: Dict) -> PositionFromAPI:
        """Convert API position data to PositionFromAPI object for TP/SL monitoring"""
        return PositionFromAPI(pos_data)

    async def _get_markets_batch(self, market_ids: List[str]) -> Dict[str, Dict]:
        """Get markets in batch for efficiency"""
        try:
            markets_map = {}
            market_service = get_market_service(cache_manager=cache_manager)

            for market_id in market_ids:
                market = await market_service.get_market_by_id(market_id)
                if market:
                    markets_map[market_id] = market

            return markets_map
        except Exception as e:
            logger.error(f"❌ Error getting markets batch: {e}")
            return {}

    async def _get_current_price(
        self,
        position: Position,
        market: Dict
    ) -> Optional[float]:
        """
        Get current price for position
        CRITICAL: Uses WebSocket prices (source='ws') when available via extract_position_price()
        This ensures TP/SL monitoring uses real-time WebSocket prices, not stale DB values

        Priority:
        1. WebSocket outcome_prices (if source='ws') - real-time, <100ms latency
        2. Poller outcome_prices (if source='poll') - updated every 60s
        3. Position current_price (fallback if market data unavailable)
        4. CLOB API (last resort, only if source != 'ws')
        """
        try:
            source = market.get('source', 'poll')

            # ✅ CRITICAL: Use shared helper function that handles WebSocket prices correctly
            # This ensures consistency with /positions flow and respects source='ws' priority
            current_price = extract_position_price(market, position.outcome)

            if current_price is not None:
                logger.debug(
                    f"✅ TP/SL Monitor: Got price for position {position.id} "
                    f"(source={source}, outcome={position.outcome}): ${current_price:.4f}"
                )
                return current_price

            # Fallback: Use position current_price if market data unavailable
            # This can happen if market was just created or data is temporarily unavailable
            if position.current_price:
                logger.debug(
                    f"⚠️ TP/SL Monitor: Using position.current_price fallback for position {position.id}: "
                    f"${position.current_price:.4f}"
                )
                return float(position.current_price)

            # Last resort: CLOB API (only if source != 'ws' to avoid unnecessary API calls)
            # CRITICAL: Never use CLOB API if source='ws' - WebSocket prices should always be available
            if source != 'ws':
                clob_token_ids = market.get('clob_token_ids', [])
                outcomes = market.get('outcomes', ['YES', 'NO'])

                if clob_token_ids and isinstance(clob_token_ids, list) and len(clob_token_ids) > 0:
                    try:
                        outcome_index = find_outcome_index(position.outcome, outcomes)
                        if outcome_index is None:
                            logger.warning(
                                f"⚠️ TP/SL Monitor: Could not find outcome index for position {position.id}: "
                                f"outcome='{position.outcome}', market outcomes={outcomes}, "
                                f"market_id={market.get('id', 'unknown')}. Using fallback index 0."
                            )
                            outcome_index = 0

                        if outcome_index >= len(clob_token_ids):
                            logger.error(
                                f"❌ TP/SL Monitor: Outcome index {outcome_index} out of range for clob_token_ids "
                                f"(length: {len(clob_token_ids)}). Market: {market.get('id', 'unknown')}, "
                                f"outcomes: {outcomes}. Using fallback token_id."
                            )
                            token_id = clob_token_ids[0]
                        else:
                            token_id = clob_token_ids[outcome_index]
                            logger.debug(f"✅ TP/SL Monitor: Resolved token_id {token_id} for position {position.id} (outcome: {position.outcome})")

                        clob_service = get_clob_service()
                        prices = await clob_service.get_market_prices([token_id])
                        api_price = prices.get(token_id)

                        if api_price:
                            logger.debug(
                                f"⚠️ TP/SL Monitor: Using CLOB API fallback for position {position.id}: "
                                f"${api_price:.4f}"
                            )
                            return api_price
                    except Exception as e:
                        logger.debug(f"⚠️ Error fetching price from CLOB: {e}")
            else:
                logger.warning(
                    f"⚠️ TP/SL Monitor: Market {market.get('id', 'unknown')} has source='ws' but "
                    f"no price available for position {position.id} (outcome={position.outcome}). "
                    f"This should not happen - WebSocket prices should always be available."
                )

            return None

        except Exception as e:
            logger.error(f"❌ Error getting current price for position {position.id}: {e}")
            return None

    async def _check_tpsl_conditions(
        self,
        position: Position,
        current_price: float
    ) -> Optional[str]:
        """
        Check if TP/SL conditions are met (limit order logic)
        - SL < market_price < TP
        - First one to trigger sells 100% of position

        Args:
            position: Position object
            current_price: Current market price

        Returns:
            'take_profit' or 'stop_loss' if triggered, None otherwise
        """
        try:
            # ✅ CRITICAL: Only check active positions
            if getattr(position, 'status', 'active') != 'active':
                logger.debug(f"⚠️ Skipping TP/SL check for position {position.id} - status is '{getattr(position, 'status', 'unknown')}' (not active)")
                return None

            # Check both TP and SL in parallel (no priority)
            tp_triggered = False
            sl_triggered = False

            # Check Take Profit
            if position.take_profit_price and current_price >= float(position.take_profit_price):
                tp_triggered = True
                logger.info(
                    f"🎯 TAKE PROFIT HIT! Position {position.id} - "
                    f"Current: ${current_price:.4f} >= TP: ${position.take_profit_price:.4f}"
                )

            # Check Stop Loss
            if position.stop_loss_price and current_price <= float(position.stop_loss_price):
                sl_triggered = True
                logger.info(
                    f"🛑 STOP LOSS HIT! Position {position.id} - "
                    f"Current: ${current_price:.4f} <= SL: ${position.stop_loss_price:.4f}"
                )

            # Return first triggered (both can trigger simultaneously, but we execute one)
            if tp_triggered:
                return 'take_profit'
            elif sl_triggered:
                return 'stop_loss'

            return None

        except Exception as e:
            logger.error(f"❌ Error checking TP/SL conditions: {e}")
            return None

    async def _execute_triggered_sells(
        self,
        triggered_positions: List[tuple]
    ) -> None:
        """
        Execute sells for triggered positions
        Rate limited: max 5 sells/second per user
        """
        try:
            clob_service = get_clob_service()

            for position, trigger_type, current_price in triggered_positions:
                try:
                    # Get user
                    user = await user_service.get_by_id(position.user_id)
                    if not user:
                        logger.error(f"❌ User {position.user_id} not found")
                        continue

                    # Get market (via API or DB)
                    if SKIP_DB:
                        # ✅ SKIP_DB mode: Use market service which handles API/DB automatically
                        market_service = get_market_service(cache_manager=cache_manager)
                        market = await market_service.get_market_by_id(position.market_id)
                        if market:
                            # Convert market dict to object-like structure for compatibility
                            class MarketFromAPI:
                                def __init__(self, data):
                                    self.id = data.get('id')
                                    self.title = data.get('title', 'Unknown Market')
                                    self.clob_token_ids = data.get('clob_token_ids', [])
                                    self.outcomes = data.get('outcomes', ['YES', 'NO'])
                            market = MarketFromAPI(market)
                    else:
                        # Standard DB mode
                        async with get_db() as db:
                            result = await db.execute(
                                select(Market).where(Market.id == position.market_id)
                            )
                            market = result.scalar_one_or_none()

                    if not market:
                        logger.error(f"❌ Market {position.market_id} not found")
                        continue

                    # ✅ CRITICAL: TP/SL always sells 100% of the position
                    # Users only configure a PRICE (take_profit_price or stop_loss_price), not an amount
                    # When triggered, we sell ALL tokens at that price

                    # Get token_id - Use same logic as sell_handler for consistency
                    import json
                    clob_token_ids_raw = market.clob_token_ids if hasattr(market, 'clob_token_ids') else getattr(market, 'clob_token_ids', '[]')
                    outcomes = market.outcomes if hasattr(market, 'outcomes') else getattr(market, 'outcomes', ['YES', 'NO'])

                    # Handle both string and list formats (same as sell_handler)
                    if isinstance(clob_token_ids_raw, str):
                        clob_token_ids_raw = clob_token_ids_raw
                    else:
                        clob_token_ids_raw = json.dumps(clob_token_ids_raw) if clob_token_ids_raw else '[]'

                    try:
                        # Parse JSON string to list - DOUBLE PARSING needed because data is double-encoded in DB
                        clob_token_ids = json.loads(clob_token_ids_raw) if isinstance(clob_token_ids_raw, str) else clob_token_ids_raw
                        # If it's still a string after first parse, parse again (double encoding issue)
                        if isinstance(clob_token_ids, str):
                            clob_token_ids = json.loads(clob_token_ids)

                        # Find outcome index using intelligent normalization
                        outcome_index = find_outcome_index(position.outcome, outcomes)
                        if outcome_index is None:
                            logger.error(
                                f"❌ CRITICAL TP/SL: Could not find outcome index for position {position.id}: "
                                f"outcome='{position.outcome}', market outcomes={outcomes}, "
                                f"market_id={position.market_id}, clob_token_ids={clob_token_ids}"
                            )
                            logger.error(
                                f"❌ This will prevent TP/SL execution. "
                                f"Position outcome may need normalization or market data may be corrupted."
                            )
                            token_id = None
                        else:
                            logger.info(f"✅ TP/SL: Found outcome index: {outcome_index} for outcome '{position.outcome}' in market {position.market_id}")
                            if outcome_index >= len(clob_token_ids):
                                logger.error(
                                    f"❌ CRITICAL TP/SL: Outcome index {outcome_index} out of range for clob_token_ids "
                                    f"(length: {len(clob_token_ids)}). Market: {position.market_id}, outcomes: {outcomes}"
                                )
                                token_id = None
                            else:
                                token_id = clob_token_ids[outcome_index]
                                logger.info(f"✅ TP/SL: Resolved token_id: {token_id} for position {position.id}")

                    except (IndexError, ValueError, TypeError, json.JSONDecodeError) as e:
                        logger.error(f"❌ Error parsing token IDs for position {position.id}: {e}, raw: {clob_token_ids_raw}")
                        token_id = None

                    if not token_id:
                        logger.error(f"❌ Token ID not found for position {position.id}, outcome: {position.outcome}")
                        continue

                    # ✅ CRITICAL: Sync position from blockchain before selling to ensure accurate token amount
                    # This prevents selling more tokens than actually available (e.g., if position was partially sold manually)
                    telegram_user_id = user.telegram_user_id
                    logger.info(f"🔄 Syncing position {position.id} from blockchain before TP/SL sell...")

                    try:
                        if SKIP_DB:
                            api_client = get_api_client()
                            # Sync positions to get latest blockchain data
                            sync_result = await api_client.sync_positions(user.id)
                            if sync_result:
                                logger.info(f"✅ Synced positions for user {user.id}: {sync_result.get('synced_positions', 0)} positions")

                            # Refresh position data after sync
                            user_positions_data = await api_client.get_user_positions(user.id, use_cache=False)
                            if user_positions_data and 'positions' in user_positions_data:
                                for pos_data in user_positions_data['positions']:
                                    if pos_data.get('id') == position.id:
                                        # Update position amount from synced data
                                        synced_amount = float(pos_data.get('amount', 0))
                                        if synced_amount != position.amount:
                                            logger.info(
                                                f"🔄 Position {position.id} amount updated after sync: "
                                                f"{position.amount:.4f} → {synced_amount:.4f}"
                                            )
                                            position.amount = synced_amount
                                        break
                        else:
                            # Direct DB mode: sync from blockchain
                            from core.services.position.blockchain_sync import sync_positions_from_blockchain
                            await sync_positions_from_blockchain(
                                user_id=user.id,
                                wallet_address=user.polygon_address if hasattr(user, 'polygon_address') else None
                            )
                            # Refresh position from DB
                            async with get_db() as db:
                                result = await db.execute(
                                    select(Position).where(Position.id == position.id)
                                )
                                refreshed_position = result.scalar_one_or_none()
                                if refreshed_position and refreshed_position.amount != position.amount:
                                    logger.info(
                                        f"🔄 Position {position.id} amount updated after sync: "
                                        f"{position.amount:.4f} → {refreshed_position.amount:.4f}"
                                    )
                                    position.amount = refreshed_position.amount
                    except Exception as sync_error:
                        logger.warning(f"⚠️ Failed to sync position before TP/SL sell: {sync_error}")
                        # Continue anyway - we'll use the position amount we have

                    # Recalculate tokens to sell after sync (in case amount changed)
                    tokens_to_sell = position.amount  # Always sell 100% of position

                    # ✅ CRITICAL: Double-check real token balance from blockchain before selling
                    # This prevents selling more tokens than actually available (e.g., if position was partially sold manually)
                    try:
                        from core.services.position.blockchain_sync import get_positions_from_blockchain
                        wallet_address = user.polygon_address if hasattr(user, 'polygon_address') else None
                        if wallet_address:
                            blockchain_positions = await get_positions_from_blockchain(wallet_address)
                            # Find matching position by token_id (API may use 'asset' or 'tokenId')
                            for bp in blockchain_positions:
                                bp_token_id = str(bp.get('tokenId', '') or bp.get('asset', ''))
                                bp_size = float(bp.get('size', 0))
                                # Compare both token_id formats (string comparison)
                                if bp_token_id and (bp_token_id == str(token_id) or bp_token_id == token_id) and bp_size > 0:
                                    # Found matching position - use real blockchain balance
                                    logger.info(
                                        f"🔍 TP/SL: Found blockchain position - token_id: {bp_token_id[:20]}..., "
                                        f"size: {bp_size:.4f}, DB amount: {tokens_to_sell:.4f}"
                                    )
                                    if bp_size < tokens_to_sell:
                                        logger.warning(
                                            f"⚠️ TP/SL: Blockchain balance ({bp_size:.4f}) < DB amount ({tokens_to_sell:.4f}). "
                                            f"Adjusting to sell {bp_size:.4f} tokens."
                                        )
                                        tokens_to_sell = bp_size
                                    elif abs(bp_size - tokens_to_sell) > 0.01:
                                        logger.info(
                                            f"🔄 TP/SL: Blockchain balance ({bp_size:.4f}) differs from DB ({tokens_to_sell:.4f}). "
                                            f"Using blockchain balance."
                                        )
                                        tokens_to_sell = bp_size
                                    break
                            else:
                                # No matching position found in blockchain
                                logger.warning(
                                    f"⚠️ TP/SL: No matching blockchain position found for token_id {token_id[:20]}... "
                                    f"(searched {len(blockchain_positions)} positions)"
                                )
                    except Exception as balance_check_error:
                        logger.warning(f"⚠️ Failed to check blockchain balance before TP/SL sell: {balance_check_error}")
                        # Continue with DB amount - better to try and fail than skip

                    expected_sell_value = tokens_to_sell * current_price

                    if tokens_to_sell <= 0:
                        logger.warning(
                            f"⚠️ Position {position.id} has no tokens to sell (amount={tokens_to_sell:.4f}). "
                            f"Skipping TP/SL sell."
                        )
                        continue

                    logger.info(
                        f"💰 TP/SL Sell Info - User {user.telegram_user_id}:\n"
                        f"   Tokens to sell: {tokens_to_sell:.4f}\n"
                        f"   Expected USD value: ${expected_sell_value:.2f} at ${current_price:.4f}"
                    )

                    # ✅ CRITICAL: Execute sell order with TOKENS, not USD
                    # Use place_market_order like sell_handler for proper SELL order handling
                    logger.info(
                        f"🚀 Executing TP/SL sell: {tokens_to_sell:.4f} tokens "
                        f"(expected USD: ${expected_sell_value:.2f} at ${current_price:.4f})"
                    )

                    # Create client for user (required for place_market_order)
                    client = await clob_service.create_user_client(user.telegram_user_id)
                    if not client:
                        logger.error(f"❌ Cannot create trading client for user {user.telegram_user_id}")
                        continue

                    # Execute market order - pass market_id and outcome for proper price calculation
                    # CRITICAL: For SELL, amount must be tokens, not USD
                    result = await clob_service.place_market_order(
                        client=client,
                        token_id=token_id,
                        side="SELL",
                        amount=tokens_to_sell,  # ✅ Number of tokens to sell (not USD!)
                        order_type="FAK",  # Fill-And-Kill for instant execution
                        market_id=position.market_id,
                        outcome=position.outcome
                    )

                    if result and result.get('success'):
                        # ✅ CRITICAL: Extract REAL execution data from transaction result
                        # place_market_order returns: tokens, usd_price_per_share, usd_received, price, tx_hash
                        actual_tokens_sold = result.get('tokens', 0)  # Tokens actually sold
                        actual_usd_received = result.get('usd_received', 0)  # USD actually received (for SELL)
                        actual_execution_price_usd = result.get('usd_price_per_share', 0)  # USD price per share
                        actual_execution_price_pm = result.get('price', 0)  # Polymarket price (0-1 format)

                        # Use USD price per share for calculations (more accurate than Polymarket price)
                        if actual_execution_price_usd > 0:
                            actual_execution_price = actual_execution_price_usd
                        elif actual_tokens_sold > 0 and actual_usd_received > 0:
                            # Calculate from USD received / tokens sold
                            actual_execution_price = actual_usd_received / actual_tokens_sold
                        else:
                            # Last resort: use trigger price (less accurate)
                            actual_execution_price = current_price
                            logger.warning(
                                f"⚠️ TP/SL: No execution price in result, using trigger price {current_price:.4f} "
                                f"for position {position.id}"
                            )

                        # Use actual USD received if available, otherwise calculate from tokens and price
                        if actual_usd_received > 0:
                            actual_sell_amount = actual_usd_received
                        else:
                            actual_sell_amount = actual_tokens_sold * actual_execution_price if actual_execution_price else expected_sell_value

                        # ✅ CRITICAL: Recalculate P&L based on REAL execution data
                        # P&L = (execution_price - entry_price) * tokens_sold
                        entry_price = float(position.entry_price)
                        actual_pnl_amount = (actual_execution_price - entry_price) * actual_tokens_sold
                        actual_pnl_percentage = ((actual_execution_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0

                        logger.info(
                            f"✅ TP/SL Execution Data - Position {position.id}:\n"
                            f"   Entry Price: ${entry_price:.4f}\n"
                            f"   Execution Price: ${actual_execution_price:.4f}\n"
                            f"   Tokens Sold: {actual_tokens_sold:.4f}\n"
                            f"   USD Received: ${actual_usd_received:.2f}\n"
                            f"   P&L: ${actual_pnl_amount:.2f} ({actual_pnl_percentage:+.1f}%)"
                        )

                        # Close position or update amount based on actual tokens sold
                        tokens_sold_ratio = actual_tokens_sold / position.amount if position.amount > 0 else 1.0
                        logger.info(
                            f"📊 TP/SL Sell Summary - Position {position.id}:\n"
                            f"   Tokens before: {position.amount:.4f}\n"
                            f"   Tokens sold: {actual_tokens_sold:.4f}\n"
                            f"   Tokens remaining: {position.amount - actual_tokens_sold:.4f}\n"
                            f"   Sell ratio: {tokens_sold_ratio*100:.1f}%"
                        )

                        if tokens_sold_ratio >= 0.95:  # 95% threshold
                            # Close entire position
                            logger.info(f"✅ Closing entire position {position.id} (sold {tokens_sold_ratio*100:.1f}%)")

                            if SKIP_DB:
                                # ✅ SKIP_DB mode: Use API to close position
                                api_client = get_api_client()
                                close_data = {
                                    'status': 'closed',
                                    'exit_price': actual_execution_price,
                                    'closed_at': datetime.now(timezone.utc).isoformat()
                                }
                                await api_client.update_position(position.id, close_data)
                                logger.info(f"✅ Position {position.id} closed via API")

                                # ✅ CRITICAL: Clear TP/SL after successful sell (SKIP_DB mode)
                                try:
                                    # Clear TP if it exists
                                    if position.take_profit_price:
                                        await api_client.update_position_tpsl(
                                            position_id=position.id,
                                            tpsl_type="tp",
                                            price=0.0  # 0.0 means clear
                                        )
                                        logger.info(f"✅ Cleared TP for position {position.id} via API")
                                    # Clear SL if it exists
                                    if position.stop_loss_price:
                                        await api_client.update_position_tpsl(
                                            position_id=position.id,
                                            tpsl_type="sl",
                                            price=0.0  # 0.0 means clear
                                        )
                                        logger.info(f"✅ Cleared SL for position {position.id} via API")
                                except Exception as e:
                                    logger.warning(f"⚠️ Failed to clear TP/SL for position {position.id} via API: {e}")
                            else:
                                # Standard DB mode
                                await position_service.close_position(position.id, exit_price=actual_execution_price)

                                # ✅ CRITICAL: Clear TP/SL after successful sell (DB mode)
                                try:
                                    # Clear TP if it exists
                                    if position.take_profit_price:
                                        await position_service.update_position_tpsl(
                                            position_id=position.id,
                                            tpsl_type="tp",
                                            price=0.0  # 0.0 means clear
                                        )
                                        logger.info(f"✅ Cleared TP for position {position.id}")
                                    # Clear SL if it exists
                                    if position.stop_loss_price:
                                        await position_service.update_position_tpsl(
                                            position_id=position.id,
                                            tpsl_type="sl",
                                            price=0.0  # 0.0 means clear
                                        )
                                        logger.info(f"✅ Cleared SL for position {position.id}")
                                except Exception as e:
                                    logger.warning(f"⚠️ Failed to clear TP/SL for position {position.id}: {e}")
                        else:
                            # Partial sell - update position amount
                            remaining_amount = position.amount - actual_tokens_sold
                            if remaining_amount < 0:
                                remaining_amount = 0

                            logger.info(
                                f"✅ Partial sell - Position {position.id} remaining: {remaining_amount:.4f} tokens"
                            )

                            if SKIP_DB:
                                # ✅ SKIP_DB mode: Use API to update position amount
                                api_client = get_api_client()
                                update_data = {
                                    'amount': remaining_amount,
                                    'current_price': actual_execution_price  # Update current price after partial sell
                                }
                                await api_client.update_position(position.id, update_data)
                                logger.info(f"✅ Position {position.id} amount updated via API: {remaining_amount:.4f}")
                            else:
                                # Standard DB mode
                                position.amount = remaining_amount
                                position.updated_at = datetime.now(timezone.utc)
                                async with get_db() as db:
                                    await db.commit()

                        # Queue notification via centralized service with REAL execution data
                        notification_service = get_notification_service()
                        notification = Notification(
                            user_id=user.telegram_user_id,
                            type=NotificationType.TPSL_TRIGGER,
                            priority=NotificationPriority.HIGH,
                            data={
                                'position_id': position.id,
                                'position_outcome': position.outcome,
                                'trigger_type': trigger_type,
                                'trigger_price': float(position.take_profit_price) if trigger_type == 'take_profit' else float(position.stop_loss_price),
                                'execution_price': actual_execution_price,  # ✅ REAL execution price
                                'current_price': actual_execution_price,  # Keep for backward compatibility
                                'sell_amount': actual_sell_amount,  # ✅ REAL amount sold
                                'tokens_sold': actual_tokens_sold,  # ✅ REAL tokens sold
                                'usd_received': actual_usd_received,  # ✅ REAL USD received
                                'market_title': market.title[:60] if market.title else 'Unknown Market',
                                'pnl_amount': actual_pnl_amount,  # ✅ REAL P&L
                                'pnl_percentage': actual_pnl_percentage,  # ✅ REAL P&L %
                                'entry_price': entry_price,  # Entry price for reference
                                'tx_hash': result.get('tx_hash')  # Transaction hash for verification
                            }
                        )
                        await notification_service.queue_notification(notification)

                        logger.info(
                            f"✅ TP/SL sell executed: Position {position.id}, "
                            f"Type: {trigger_type}, Amount: ${actual_sell_amount:.2f}, "
                            f"Execution Price: ${actual_execution_price:.4f}, P&L: ${actual_pnl_amount:.2f}"
                        )
                    else:
                        # Order failed - extract error message
                        error_msg = result.get('error', 'Unknown error') if result else 'No result returned'
                        logger.error(
                            f"❌ TP/SL sell failed for position {position.id}:\n"
                            f"   Error: {error_msg}\n"
                            f"   Tokens to sell: {tokens_to_sell:.4f}\n"
                            f"   Token ID: {token_id[:20]}..."
                        )

                        # Queue notification about failed TP/SL
                        notification_service = get_notification_service()
                        notification = Notification(
                            user_id=user.telegram_user_id,
                            type=NotificationType.TPSL_FAILED,
                            priority=NotificationPriority.HIGH,
                            data={
                                'position_id': position.id,
                                'position_outcome': position.outcome,
                                'trigger_type': trigger_type,
                                'trigger_price': float(position.take_profit_price) if trigger_type == 'take_profit' else float(position.stop_loss_price),
                                'current_price': current_price,
                                'tokens_to_sell': tokens_to_sell,
                                'expected_value': expected_sell_value,
                                'reason': 'order_failed',
                                'error_message': error_msg,
                                'market_title': market.title[:60] if market.title else 'Unknown Market',
                                'failure_message': f'TP/SL sell order failed: {error_msg}. Please try selling manually.'
                            }
                        )
                        await notification_service.queue_notification(notification)

                    # Rate limiting: wait 0.2s between sells (max 5/second)
                    await asyncio.sleep(0.2)

                except Exception as e:
                    logger.error(f"❌ Error executing sell for position {position.id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"❌ Error executing triggered sells: {e}")


    def get_stats(self) -> Dict[str, Any]:
        """Get monitor statistics"""
        return {
            'running': self.running,
            'check_interval': self.check_interval,
        }


# Global instance
tpsl_monitor: Optional[TPSLMonitor] = None


def get_tpsl_monitor() -> Optional[TPSLMonitor]:
    """Get the global TP/SL monitor instance"""
    return tpsl_monitor


def set_tpsl_monitor(monitor: TPSLMonitor) -> None:
    """Set the global TP/SL monitor instance"""
    global tpsl_monitor
    tpsl_monitor = monitor
