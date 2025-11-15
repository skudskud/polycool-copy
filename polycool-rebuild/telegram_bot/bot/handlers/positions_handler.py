"""
Positions command handler
Routes /positions commands and callbacks to specialized modules
"""
import os
from typing import Dict, Any, Optional, List
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.services.user.user_helper import get_user_data, get_user_internal_id
from core.services.user.user_service import user_service
from core.services.position.position_service import position_service
from core.services.position.outcome_helper import find_outcome_index
from core.services.clob.clob_service import get_clob_service
from core.services.market_service import get_market_service
from core.services.market.market_helper import get_market_data
from telegram_bot.bot.handlers.positions.view_builder import build_positions_view, build_position_detail_view
from core.services.balance.balance_service import balance_service
from core.services.redeem.redeemable_detector import get_redeemable_detector
# All specialized handlers imported dynamically to avoid circular dependencies
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


def _extract_position_price_from_market(market: Dict[str, Any], outcome: str) -> Optional[float]:
    """
    Extract current price for a position from market data

    CRITICAL: When source='ws', use ONLY outcome_prices (no fallbacks)
    This ensures consistency with WebSocket-streamed prices from markets table

    Args:
        market: Market data dict (from API, includes 'source' and 'outcome_prices')
        outcome: Position outcome ("YES" or "NO")

    Returns:
        Current price (0-1) or None if not available
    """
    try:
        source = market.get('source', 'poll')

        # CRITICAL: When source='ws', use ONLY outcome_prices (no fallbacks)
        # This ensures we always use WebSocket prices from markets.outcome_prices
        if source == 'ws':
            outcome_prices = market.get('outcome_prices')
            if not outcome_prices:
                logger.warning(f"⚠️ Market {market.get('id', 'unknown')} has source='ws' but no outcome_prices available")
                return None

            # Handle list format [YES_price, NO_price]
            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                outcomes = market.get('outcomes', ['YES', 'NO'])
                try:
                    outcome_index = find_outcome_index(outcome, outcomes)
                    if outcome_index is not None and outcome_index < len(outcome_prices):
                        price = float(outcome_prices[outcome_index])
                        if 0 <= price <= 1:
                            return price
                except (ValueError, IndexError, TypeError) as e:
                    logger.warning(f"⚠️ Error extracting price from outcome_prices list for market {market.get('id', 'unknown')}: {e}")
                    return None
            # Handle dict format (legacy)
            elif isinstance(outcome_prices, dict):
                outcome_key = outcome.upper()
                if outcome_key in outcome_prices:
                    price = float(outcome_prices[outcome_key])
                    if 0 <= price <= 1:
                        return price
                logger.warning(f"⚠️ Market {market.get('id', 'unknown')} has source='ws' but outcome '{outcome}' not in outcome_prices dict")
                return None
            else:
                logger.warning(f"⚠️ Market {market.get('id', 'unknown')} has source='ws' but invalid outcome_prices format: {type(outcome_prices)}")
                return None

        # For source='poll' or other sources, try outcome_prices first, then fallbacks
        outcome_prices = market.get('outcome_prices')
        if outcome_prices:
            # Handle list format [YES_price, NO_price]
            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                outcomes = market.get('outcomes', ['YES', 'NO'])
                try:
                    outcome_index = find_outcome_index(outcome, outcomes)
                    if outcome_index is not None and outcome_index < len(outcome_prices):
                        price = float(outcome_prices[outcome_index])
                        if 0 <= price <= 1:
                            return price
                except (ValueError, IndexError, TypeError) as e:
                    logger.debug(f"⚠️ Error extracting price from outcome_prices list: {e}")
            # Handle dict format (legacy)
            elif isinstance(outcome_prices, dict):
                outcome_key = outcome.upper()
                if outcome_key in outcome_prices:
                    price = float(outcome_prices[outcome_key])
                    if 0 <= price <= 1:
                        return price

        # Fallback to last_mid_price (only for source='poll')
        last_mid_price = market.get('last_mid_price')
        if last_mid_price is not None:
            price = float(last_mid_price)
            if 0 <= price <= 1:
                # CORRECTED: No longer invert prices for NO positions - P&L calculator handles both outcomes the same way
                return price

        # Fallback to last_trade_price (only for source='poll')
        last_trade_price = market.get('last_trade_price')
        if last_trade_price is not None:
            price = float(last_trade_price)
            if 0 <= price <= 1:
                # CORRECTED: No longer invert prices for NO positions - P&L calculator handles both outcomes the same way
                return price

        return None
    except Exception as e:
        logger.debug(f"⚠️ Error extracting price from market: {e}")
        return None


# Helper class for PositionFromAPI (shared across handlers)
class PositionFromAPI:
    """Simple position object from API response"""
    def __init__(self, data):
        self.id = data.get('id')
        self.user_id = data.get('user_id')
        self.market_id = data.get('market_id')
        self.outcome = data.get('outcome')
        self.amount = float(data.get('amount', 0))
        self.entry_price = float(data.get('entry_price', 0))
        self.current_price = float(data.get('current_price', 0)) if data.get('current_price') else None
        # P&L from API (may be stale if prices haven't been updated)
        self.pnl_amount = float(data.get('pnl_amount', 0))
        self.pnl_percentage = float(data.get('pnl_percentage', 0))
        self.status = data.get('status', 'active')
        self.take_profit_price = float(data.get('take_profit_price')) if data.get('take_profit_price') else None
        self.stop_loss_price = float(data.get('stop_loss_price')) if data.get('stop_loss_price') else None
        self.total_cost = float(data.get('total_cost')) if data.get('total_cost') else None
        self.created_at = data.get('created_at')
        self.updated_at = data.get('updated_at')

    def recalculate_pnl(self, current_price: float) -> None:
        """
        Recalculate P&L with current market price
        This ensures P&L is always up-to-date even if DB values are stale
        Uses WebSocket prices when available for real-time accuracy

        Args:
            current_price: Current market price (0-1) from WebSocket or market data
        """
        if current_price is None or self.entry_price <= 0:
            return

        try:
            from core.services.position.pnl_calculator import calculate_pnl
            # calculate_pnl now handles outcome normalization internally (DOWN->NO, UP->YES, etc.)
            self.pnl_amount, self.pnl_percentage = calculate_pnl(
                self.entry_price,
                current_price,
                self.amount,
                self.outcome
            )
            # ✅ CRITICAL: Update current_price to reflect latest WebSocket price
            self.current_price = current_price
        except Exception as e:
            logger.warning(f"⚠️ Failed to recalculate P&L for position {self.id}: {e}")


async def get_position_helper(position_id: int, telegram_user_id: int = None):
    """
    Helper to get position via API or DB depending on SKIP_DB setting

    Args:
        position_id: Position ID
        telegram_user_id: Optional Telegram user ID (needed for API fallback)

    Returns:
        Position object (PositionFromAPI or Position model) or None
    """
    if SKIP_DB:
        api_client = get_api_client()
        # Try direct endpoint first - force fresh data (no cache) for TP/SL updates
        position_data = await api_client.get_position(position_id, use_cache=False)
        if position_data and 'id' in position_data:
            # Endpoint returned position data
            return PositionFromAPI(position_data)
        # Fallback: get all positions and filter by ID
        # This works even if the endpoint isn't fully implemented yet
        if telegram_user_id:
            user_data = await get_user_data(telegram_user_id)
            if user_data:
                internal_id = user_data.get('id')
                if internal_id:
                    # Force fresh data for TP/SL updates
                    user_positions = await api_client.get_user_positions(internal_id, use_cache=False)
                    if user_positions:
                        positions_list = user_positions.get('positions', [])
                        for pos_data in positions_list:
                            if pos_data.get('id') == position_id:
                                return PositionFromAPI(pos_data)
        return None
    else:
        return await position_service.get_position(position_id)


async def handle_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /positions command - Show user positions
    Optimized for <1s latency: display cached data immediately, refresh in background
    """
    if not update.effective_user:
        return

    telegram_user_id = update.effective_user.id

    try:
        logger.info(f"📈 /positions command - User {telegram_user_id}")

        # Mark positions view as active (for background refresh control)
        context.user_data['positions_view_active'] = True

        # Get user data (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data:
            await update.message.reply_text(
                "❌ You are not registered. Use /start to begin."
            )
            return

        internal_id = user_data.get('id')
        polygon_address = user_data.get('polygon_address')

        if not internal_id:
            await update.message.reply_text(
                "❌ User ID not found. Please use /start to create your account."
            )
            return

        # PHASE 1: Display cached positions immediately (< 100ms)
        loading_msg = await update.message.reply_text("🔍 Loading your positions...")

        positions = None
        markets_map = {}
        usdc_balance = None
        total_pnl = 0.0
        total_pnl_percentage = 0.0

        if SKIP_DB:
            api_client = get_api_client()
            # ✅ OPTIMIZATION: Paralléliser les appels API indépendants pour réduire la latence
            import asyncio
            # Lancer get_user_positions() et get_wallet_balance() en parallèle
            positions_task = api_client.get_user_positions(internal_id, use_cache=True)
            balance_task = api_client.get_wallet_balance(internal_id, use_cache=True)
            positions_data, balance_data = await asyncio.gather(positions_task, balance_task)

            if balance_data:
                usdc_balance = balance_data.get('usdc_balance')

            if positions_data:
                positions_list = positions_data.get('positions', [])
                positions = [
                    PositionFromAPI(pos)
                    for pos in positions_list
                    if pos.get('status') == 'active'
                    and pos.get('amount', 0) > 0
                ]
                logger.info(f"📊 Loaded {len(positions)} cached positions for immediate display")

                # Get markets in batch (optimized - single API call instead of N calls)
                market_ids_to_fetch = [
                    position.market_id for position in positions
                    if position.market_id not in markets_map
                ]

                if market_ids_to_fetch:
                    # Batch fetch all markets at once
                    markets_list = await api_client.get_markets_batch(market_ids_to_fetch, use_cache=True)
                    if markets_list:
                        for market in markets_list:
                            if market and market.get('id'):
                                markets_map[market['id']] = market
                        logger.info(f"✅ Fetched {len(markets_list)} markets in batch (optimized)")

                # ✅ CRITICAL: Recalculate P&L immediately with current market prices
                # This eliminates the 2-second latency by using fresh prices for P&L calculation
                positions_recalculated = 0
                for position in positions:
                    market = markets_map.get(position.market_id)
                    if market:
                        # Extract current price from market data (same logic as PHASE 2)
                        current_price = _extract_position_price_from_market(market, position.outcome)
                        if current_price is not None:
                            # Recalculate P&L with current market price
                            position.recalculate_pnl(current_price)
                            positions_recalculated += 1
                            logger.debug(
                                f"🔄 PHASE 1: Recalculated P&L for position {position.id} with price {current_price:.4f}: "
                                f"${position.pnl_amount:.2f} ({position.pnl_percentage:+.1f}%)"
                            )
                        else:
                            # No price available - keep cached P&L as fallback
                            logger.debug(f"⚠️ PHASE 1: No market price for position {position.id}, keeping cached P&L")

                if positions_recalculated > 0:
                    logger.info(f"✅ PHASE 1: Recalculated P&L for {positions_recalculated} positions with current market prices")

                # Calculate totals with freshly recalculated P&L
                total_pnl = sum(p.pnl_amount for p in positions) if positions else 0.0
                total_invested = sum(p.entry_price * p.amount for p in positions) if positions else 0.0
                total_pnl_percentage = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

                # ✅ OPTIMIZATION: Détection redeemable déplacée en arrière-plan pour ne pas bloquer l'affichage
                # Les positions sont affichées immédiatement, la détection se fait en background

        # Display cached data immediately if available
        if positions is not None:
            message_text, keyboard = await build_positions_view(
                positions=positions,
                markets_map=markets_map,
                total_pnl=total_pnl,
                total_pnl_percentage=total_pnl_percentage,
                balance=None,
                usdc_balance=usdc_balance,
                include_refresh=True,
                user_id=internal_id
            )

            # ✅ OPTIMIZATION: Load claimable positions in background and update message if needed
            import asyncio
            asyncio.create_task(_load_claimable_and_update(
                internal_id, loading_msg, message_text, keyboard, telegram_user_id
            ))

            # Truncate if needed
            MAX_MESSAGE_LENGTH = 4096
            if len(message_text) > MAX_MESSAGE_LENGTH:
                truncated_text = message_text[:MAX_MESSAGE_LENGTH - 50]
                message_text = truncated_text + "\n\n⚠️ Message truncated..."

            try:
                await loading_msg.edit_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                logger.info(f"✅ Displayed cached positions immediately for user {telegram_user_id}")
            except Exception as e:
                logger.warning(f"⚠️ Error displaying cached positions: {e}")

        # PHASE 2: Background tasks (async, non-blocking)
        import asyncio
        # Détection redeemable en background (ne bloque pas l'affichage)
        if positions and polygon_address:
            asyncio.create_task(_detect_redeemable_background(
                internal_id, polygon_address, positions, loading_msg, telegram_user_id, context
            ))
        # Refresh positions data in background
        asyncio.create_task(_refresh_positions_background(
            internal_id, polygon_address, loading_msg, telegram_user_id, context
        ))

    except Exception as e:
        logger.error(f"Error in positions handler for user {telegram_user_id}: {e}")
        if 'loading_msg' in locals():
            await loading_msg.edit_text("❌ An error occurred. Please try again.")
        else:
            await update.message.reply_text("❌ An error occurred. Please try again.")


async def _load_claimable_and_update(
    internal_id: int,
    loading_msg,
    current_message: str,
    current_keyboard: List[List[Any]],
    telegram_user_id: int
) -> None:
    """
    Background task to load claimable positions and update message if needed
    """
    try:
        logger.debug(f"🔄 Background claimable loading started for user {internal_id}")

        # Load claimable positions
        from telegram_bot.bot.handlers.positions.view_builder import _get_claimable_positions
        claimable_positions = await _get_claimable_positions(internal_id)

        # Only update if claimable positions were found and message shows loading placeholder
        if claimable_positions:
            # Rebuild view with claimable positions
            from telegram_bot.bot.handlers.positions.view_builder import build_positions_view
            # Get fresh positions data
            if SKIP_DB:
                api_client = get_api_client()
                positions_data = await api_client.get_user_positions(internal_id, use_cache=True)
                if positions_data:
                    positions_list = positions_data.get('positions', [])
                    positions = [
                        PositionFromAPI(pos)
                        for pos in positions_list
                        if pos.get('status') == 'active'
                        and pos.get('amount', 0) > 0
                    ]
                    # Get markets
                    market_ids = [p.market_id for p in positions]
                    markets_map = {}
                    if market_ids:
                        markets_list = await api_client.get_markets_batch(market_ids, use_cache=True)
                        if markets_list:
                            for market in markets_list:
                                if market and market.get('id'):
                                    markets_map[market['id']] = market

                    # Recalculate P&L
                    for position in positions:
                        market = markets_map.get(position.market_id)
                        if market:
                            current_price = _extract_position_price_from_market(market, position.outcome)
                            if current_price is not None:
                                position.recalculate_pnl(current_price)

                    total_pnl = sum(p.pnl_amount for p in positions) if positions else 0.0
                    total_invested = sum(p.entry_price * p.amount for p in positions) if positions else 0.0
                    total_pnl_percentage = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

                    # Get balance
                    balance_data = await api_client.get_wallet_balance(internal_id, use_cache=True)
                    usdc_balance = balance_data.get('usdc_balance') if balance_data else None

                    # Rebuild view with claimable positions
                    message_text, keyboard = await build_positions_view(
                        positions=positions,
                        markets_map=markets_map,
                        total_pnl=total_pnl,
                        total_pnl_percentage=total_pnl_percentage,
                        balance=None,
                        usdc_balance=usdc_balance,
                        include_refresh=True,
                        user_id=internal_id
                    )

                    # Update message
                    MAX_MESSAGE_LENGTH = 4096
                    if len(message_text) > MAX_MESSAGE_LENGTH:
                        truncated_text = message_text[:MAX_MESSAGE_LENGTH - 50]
                        message_text = truncated_text + "\n\n⚠️ Message truncated..."

                    from telegram import InlineKeyboardMarkup
                    await loading_msg.edit_text(
                        message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                    logger.info(f"✅ Updated positions view with claimable positions for user {telegram_user_id}")
    except Exception as e:
        logger.warning(f"⚠️ Error loading claimable positions in background for user {internal_id}: {e}")
        # Don't block - positions are already displayed


async def _detect_redeemable_background(
    internal_id: int,
    polygon_address: str,
    positions: List[Any],
    loading_msg,
    telegram_user_id: int,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Background task to detect redeemable positions
    Updates the message if redeemable positions are found
    """
    try:
        logger.info(f"🔍 Background redeemable detection started for user {internal_id}")

        # Fetch positions from blockchain (has conditionId, asset, etc.)
        blockchain_positions = await position_service.get_positions_from_blockchain(polygon_address)

        if not blockchain_positions:
            logger.debug(f"⚠️ No blockchain positions found for user {internal_id}")
            return

        # Detect redeemable positions using blockchain data (via API or direct)
        redeemable_condition_ids = []
        if SKIP_DB:
            api_client = get_api_client()
            result = await api_client.detect_redeemable_positions(
                internal_id,
                blockchain_positions,
                polygon_address
            )
            if result:
                redeemable_condition_ids = result.get('resolved_condition_ids', [])
        else:
            detector = get_redeemable_detector()
            _, redeemable_condition_ids = await detector.detect_redeemable_positions(
                blockchain_positions,
                internal_id,
                polygon_address
            )

        # If redeemable positions found, log but don't update message (user can use "Check Redeemable" button)
        if redeemable_condition_ids:
            logger.info(
                f"🔍 [BACKGROUND] Found {len(redeemable_condition_ids)} redeemable positions "
                f"for user {internal_id}. User can use 'Check Redeemable' button to view them."
            )
        else:
            logger.debug(f"✅ No redeemable positions found for user {internal_id}")

    except Exception as e:
        logger.warning(f"⚠️ Error in background redeemable detection for user {internal_id}: {e}")
        # Don't block or update message on error - positions are already displayed


async def _refresh_positions_background(
    internal_id: int,
    polygon_address: str,
    loading_msg,
    telegram_user_id: int,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Background task to sync and refresh positions data
    Updates the message after sync completes
    """
    try:
        logger.info(f"🔄 Background refresh started for user {internal_id}")

        # Sync positions from blockchain (via API or DB)
        synced = 0
        updated = 0

        if SKIP_DB:
            # Use API endpoint for syncing
            api_client = get_api_client()
            logger.info(f"🔄 Syncing positions from blockchain for user {internal_id}")
            sync_result = await api_client.sync_positions(internal_id)
            if sync_result:
                synced = sync_result.get('synced_positions', 0)
                updated = sync_result.get('updated_prices', 0)
                logger.info(f"✅ Synced {synced} positions via API, updated {updated} prices")

                # Invalidate positions cache after sync to ensure fresh data
                await api_client.cache_manager.invalidate_pattern(f"api:positions:{internal_id}")
                logger.info(f"🗑️ Invalidated positions cache after sync")
            else:
                logger.warning(f"⚠️ Position sync via API failed for user {internal_id}")
        else:
            # Direct DB access
            synced = await position_service.sync_positions_from_blockchain(
                user_id=internal_id,
                wallet_address=polygon_address
            )
            logger.info(f"Synced {synced} positions from blockchain")

            # Update prices for all positions
            updated = await position_service.update_all_positions_prices(user_id=internal_id)
            logger.info(f"Updated prices for {updated} positions")

        # Get fresh positions (via API or DB) - force fresh fetch
        positions = None
        if SKIP_DB:
            api_client = get_api_client()
            # Force fresh fetch (no cache)
            positions_data = await api_client.get_user_positions(internal_id, use_cache=False)
            if positions_data:
                positions_list = positions_data.get('positions', [])
                positions = [
                    PositionFromAPI(pos)
                    for pos in positions_list
                    if pos.get('status') == 'active'
                    and pos.get('amount', 0) > 0
                ]
                logger.info(f"📊 Fresh: Fetched {len(positions_list)} positions from API, filtered to {len(positions)} active positions")
            else:
                positions = []
                logger.warning(f"⚠️ No positions data returned from API for user {internal_id}")
        else:
            positions = await position_service.get_active_positions(user_id=internal_id)
            positions = [p for p in positions if p.amount and p.amount > 0]
            logger.info(f"📊 Fresh: Fetched {len(positions)} active positions from DB")

        # ✅ Detect and filter redeemable positions
        # Get positions from blockchain for detection (has all required fields: conditionId, asset, etc.)
        if positions and polygon_address:
            try:
                # Fetch positions from blockchain (has conditionId, asset, etc.)
                blockchain_positions = await position_service.get_positions_from_blockchain(polygon_address)

                if blockchain_positions:
                    # Detect redeemable positions using blockchain data (via API or direct)
                    if SKIP_DB:
                        api_client = get_api_client()
                        result = await api_client.detect_redeemable_positions(
                            internal_id,
                            blockchain_positions,
                            polygon_address
                        )
                        if result:
                            redeemable_positions = result.get('redeemable_positions', [])
                            redeemable_condition_ids = result.get('resolved_condition_ids', [])
                        else:
                            redeemable_positions = []
                            redeemable_condition_ids = []
                    else:
                        detector = get_redeemable_detector()
                        redeemable_positions, redeemable_condition_ids = await detector.detect_redeemable_positions(
                            blockchain_positions,
                            internal_id,
                            polygon_address
                        )

                    # Filter out redeemable positions from active positions
                    if redeemable_condition_ids:
                        original_count = len(positions)
                        positions = [
                            pos for pos in positions
                            if getattr(pos, 'market_id', '') not in redeemable_condition_ids
                        ]
                        if original_count > len(positions):
                            logger.info(
                                f"🔍 [REFRESH FILTER] Removed {original_count - len(positions)} redeemable positions "
                                f"from active display (kept {len(redeemable_positions)} for claimable winnings)"
                            )
            except Exception as e:
                logger.warning(f"⚠️ Could not detect redeemable positions: {e}")
                # Continue without filtering - positions will still be shown

        # Get markets for positions and recalculate P&L with current prices
        markets_map = {}
        positions_recalculated = 0

        if SKIP_DB:
            api_client = get_api_client()
            # Batch fetch all markets at once (optimized)
            market_ids_to_fetch = list(set(position.market_id for position in positions))
            if market_ids_to_fetch:
                markets_list = await api_client.get_markets_batch(market_ids_to_fetch, use_cache=True)
                if markets_list:
                    for market in markets_list:
                        if market and market.get('id'):
                            markets_map[market['id']] = market
                    logger.info(f"✅ Background: Fetched {len(markets_list)} markets in batch (optimized)")

            # Recalculate P&L with current market price from WebSocket
            for position in positions:
                market = markets_map.get(position.market_id, {})
                if market:
                    # Extract current price from market data (prioritizes WebSocket outcome_prices)
                    current_price = _extract_position_price_from_market(market, position.outcome)
                    if current_price is not None:
                        # Always recalculate if we have a valid price (even if same as stored)
                        # This ensures P&L uses latest WebSocket prices
                        position.recalculate_pnl(current_price)
                        positions_recalculated += 1
                        logger.debug(
                            f"🔄 Recalculated P&L for position {position.id} with WebSocket price {current_price:.4f}: "
                            f"${position.pnl_amount:.2f} ({position.pnl_percentage:+.1f}%)"
                        )
                    else:
                        # No price available - use entry_price as fallback for P&L calculation
                        if position.current_price is None or position.current_price == 0:
                            logger.warning(f"⚠️ No market price available for position {position.id}, using entry_price {position.entry_price} as fallback")
                            position.recalculate_pnl(position.entry_price)
                else:
                    # Market not found - use entry_price as fallback
                    if position.current_price is None or position.current_price == 0:
                        logger.warning(f"⚠️ Market {position.market_id} not found for position {position.id}, using entry_price {position.entry_price} as fallback")
                        position.recalculate_pnl(position.entry_price)
        else:
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            market_service = get_market_service(cache_manager=cache_manager)

            for position in positions:
                if position.market_id not in markets_map:
                    market = await market_service.get_market_by_id(position.market_id)
                    if market:
                        markets_map[position.market_id] = market

                # Recalculate P&L with current market price
                market = markets_map.get(position.market_id)
                if market:
                    current_price = _extract_position_price_from_market(market, position.outcome)
                    if current_price is not None:
                        # For DB positions, update via service (always update if price available)
                        try:
                            updated = await position_service.update_position_price(position.id, current_price)
                            if updated:
                                position.pnl_amount = updated.pnl_amount
                                position.pnl_percentage = updated.pnl_percentage
                                position.current_price = updated.current_price
                                positions_recalculated += 1
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to update P&L for position {position.id}: {e}")
                    else:
                        # No price available - use entry_price as fallback
                        if position.current_price is None or position.current_price == 0:
                            logger.warning(f"⚠️ No market price available for position {position.id}, using entry_price {position.entry_price} as fallback")
                            try:
                                updated = await position_service.update_position_price(position.id, position.entry_price)
                                if updated:
                                    position.pnl_amount = updated.pnl_amount
                                    position.pnl_percentage = updated.pnl_percentage
                                    position.current_price = updated.current_price
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to update P&L with entry_price fallback for position {position.id}: {e}")
                else:
                    # Market not found - use entry_price as fallback
                    if position.current_price is None or position.current_price == 0:
                        logger.warning(f"⚠️ Market {position.market_id} not found for position {position.id}, using entry_price {position.entry_price} as fallback")
                        try:
                            updated = await position_service.update_position_price(position.id, position.entry_price)
                            if updated:
                                position.pnl_amount = updated.pnl_amount
                                position.pnl_percentage = updated.pnl_percentage
                                position.current_price = updated.current_price
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to update P&L with entry_price fallback for position {position.id}: {e}")

        if positions_recalculated > 0:
            logger.info(f"✅ Recalculated P&L for {positions_recalculated} positions with current market prices")

        # Calculate total P&L (using recalculated values)
        total_pnl = sum(p.pnl_amount for p in positions) if positions else 0.0
        total_invested = sum(p.entry_price * p.amount for p in positions) if positions else 0.0
        total_pnl_percentage = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

        # Get USDC.e balance - force fresh fetch to avoid stale cache
        usdc_balance = None
        balance = None  # Legacy balance (deprecated, use usdc_balance instead)

        if polygon_address:
            try:
                if SKIP_DB:
                    api_client = get_api_client()
                    # Force fresh fetch (no cache) to get accurate balance
                    balance_data = await api_client.get_wallet_balance(internal_id, use_cache=False)
                    if balance_data:
                        usdc_balance = balance_data.get('usdc_balance')
                        logger.info(f"💵 Fetched USDC balance for user {internal_id}: ${usdc_balance:.2f}")
                    else:
                        logger.warning(f"⚠️ No balance data returned for user {internal_id}")
                else:
                    usdc_balance = await balance_service.get_usdc_balance(polygon_address)
                    logger.info(f"💵 Fetched USDC balance directly: ${usdc_balance:.2f}")
            except Exception as e:
                logger.error(f"❌ Could not fetch USDC.e balance: {e}")
                import traceback
                logger.error(traceback.format_exc())

        # Note: Legacy balance via clob_service.get_balance() removed to avoid API Credentials warning
        # usdc_balance from API is the preferred and more reliable method

        # Build view
        message_text, keyboard = await build_positions_view(
            positions=positions,
            markets_map=markets_map,
            total_pnl=total_pnl,
            total_pnl_percentage=total_pnl_percentage,
            balance=balance,
            usdc_balance=usdc_balance,
            include_refresh=True,
            user_id=internal_id
        )

        # Check if user is still in positions view (prevent interference with other interfaces)
        positions_view_active = context.user_data.get('positions_view_active', True)
        if not positions_view_active:
            logger.debug(f"🔄 Skipping positions refresh for user {telegram_user_id} - user left positions view")
            return

        # Truncate message if too long (Telegram limit is 4096 characters)
        MAX_MESSAGE_LENGTH = 4096
        if len(message_text) > MAX_MESSAGE_LENGTH:
            logger.warning(f"⚠️ Message too long ({len(message_text)} chars), truncating to {MAX_MESSAGE_LENGTH}")
            # Truncate and add indicator
            truncated_text = message_text[:MAX_MESSAGE_LENGTH - 50]
            message_text = truncated_text + "\n\n⚠️ Message truncated..."

        try:
            await loading_msg.edit_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            error_str = str(e)
            if "Message is not modified" in error_str:
                # Content hasn't changed, this is normal - data is already up to date
                logger.debug(f"Position data unchanged for user {telegram_user_id}, skipping message update")
                # Don't raise error, just log and continue
                return
            elif "Bad Request" in error_str or "400" in error_str:
                # HTTP 400 - likely message format issue
                logger.error(f"❌ HTTP 400 error editing message: {e}")
                logger.debug(f"Message length: {len(message_text)}, Keyboard buttons: {len(keyboard)}")
                # Try to send a simpler message
                try:
                    await loading_msg.edit_text(
                        f"📊 **Your Positions**\n\n{len(positions)} active position(s)\n\n⚠️ Use /positions for full details",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except Exception as e2:
                    logger.error(f"❌ Failed to send fallback message: {e2}")
                    await loading_msg.edit_text("❌ Error displaying positions. Please try again.")
            else:
                raise

        logger.info(f"✅ Positions displayed for user {telegram_user_id}")

    except Exception as e:
        logger.error(f"Error in positions handler for user {telegram_user_id}: {e}")
        if 'loading_msg' in locals():
            await loading_msg.edit_text("❌ An error occurred. Please try again.")
        else:
            await update.message.reply_text("❌ An error occurred. Please try again.")


async def handle_position_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle position callback queries - Route to specialized handlers
    """
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id

    try:
        logger.info(f"🔍 Position callback received: {callback_data[:100]} from user {user_id}")
        # Answer callback immediately to show user feedback
        await query.answer()

        # Route callbacks to specialized handlers with dynamic imports
        if callback_data == "positions_hub" or callback_data == "refresh_positions":
            logger.info(f"🔄 Refresh Positions clicked by user {user_id}")
            from telegram_bot.bot.handlers.positions.refresh_handler import handle_refresh_positions
            await handle_refresh_positions(query, context)
        elif callback_data.startswith("position_"):
            position_id = callback_data.split("_")[-1] if "_" in callback_data else "unknown"
            logger.info(f"📊 Position Detail clicked - Position {position_id} by user {user_id}")
            # Mark that user left positions view
            context.user_data['positions_view_active'] = False
            await _handle_position_detail(query, context, callback_data)
        elif callback_data.startswith("sell_position_"):
            position_id = callback_data.split("_")[-1]
            logger.info(f"💸 Sell Position clicked - Position {position_id} by user {user_id}")
            # Mark that user left positions view
            context.user_data['positions_view_active'] = False
            from telegram_bot.bot.handlers.positions.sell_handler import handle_sell_position
            await handle_sell_position(query, context, callback_data)
        elif callback_data.startswith("sell_amount_"):
            parts = callback_data.split("_")
            position_id = parts[-1] if len(parts) > 2 else "unknown"
            amount = parts[2] if len(parts) > 2 else "unknown"
            logger.info(f"💰 Sell Amount clicked - Position {position_id}, Amount: {amount} by user {user_id}")
            from telegram_bot.bot.handlers.positions.sell_handler import handle_sell_amount
            await handle_sell_amount(query, context, callback_data)
        elif callback_data.startswith("sell_custom_"):
            position_id = callback_data.split("_")[-1]
            logger.info(f"✏️ Sell Custom Amount clicked - Position {position_id} by user {user_id}")
            from telegram_bot.bot.handlers.positions.sell_handler import handle_sell_custom
            await handle_sell_custom(query, context, callback_data)
        elif callback_data.startswith("confirm_sell_"):
            parts = callback_data.split("_")
            position_id = parts[-1] if len(parts) > 2 else "unknown"
            logger.info(f"✅ Confirm Sell clicked - Position {position_id} by user {user_id}")
            from telegram_bot.bot.handlers.positions.sell_handler import handle_confirm_sell
            await handle_confirm_sell(query, context, callback_data)
        elif callback_data.startswith("tpsl_setup_"):
            position_id = callback_data.split("_")[-1]
            logger.info(f"🎯 TP/SL Setup clicked - Position {position_id} by user {user_id}")
            # Mark that user left positions view
            context.user_data['positions_view_active'] = False
            from telegram_bot.bot.handlers.positions.tpsl_handler import handle_tpsl_setup
            await handle_tpsl_setup(query, context, callback_data)
        elif callback_data.startswith("tpsl_set_tp_") or callback_data.startswith("tpsl_set_sl_"):
            parts = callback_data.split("_")
            tpsl_type = parts[2]  # "tp" or "sl"
            position_id = parts[-1]
            logger.info(f"🎯 TP/SL Set Price clicked - Position {position_id}, Type: {tpsl_type.upper()} by user {user_id}")
            from telegram_bot.bot.handlers.positions.tpsl_handler import handle_tpsl_set_price
            await handle_tpsl_set_price(query, context, callback_data)
        elif callback_data.startswith("tpsl_percent_"):
            parts = callback_data.split("_")
            tpsl_type = parts[2]  # "tp" or "sl"
            percentage = parts[3] if len(parts) > 3 else "unknown"
            position_id = parts[-1]
            logger.info(f"📊 TP/SL Percentage clicked - Position {position_id}, Type: {tpsl_type.upper()}, %: {percentage} by user {user_id}")
            from telegram_bot.bot.handlers.positions.tpsl_handler import handle_tpsl_percentage
            await handle_tpsl_percentage(query, context, callback_data)
        elif callback_data.startswith("tpsl_custom_"):
            parts = callback_data.split("_")
            tpsl_type = parts[2]  # "tp" or "sl"
            position_id = parts[-1]
            logger.info(f"✏️ TP/SL Custom Price clicked - Position {position_id}, Type: {tpsl_type.upper()} by user {user_id}")
            from telegram_bot.bot.handlers.positions.tpsl_handler import handle_tpsl_custom
            await handle_tpsl_custom(query, context, callback_data)
        elif callback_data.startswith("tpsl_clear_tp_") or callback_data.startswith("tpsl_clear_sl_"):
            parts = callback_data.split("_")
            tpsl_type = parts[2]  # "tp" or "sl"
            position_id = parts[-1]
            logger.info(f"🗑️ TP/SL Clear clicked - Position {position_id}, Type: {tpsl_type.upper()} by user {user_id}")
            from telegram_bot.bot.handlers.positions.tpsl_handler import handle_tpsl_clear
            await handle_tpsl_clear(query, context, callback_data)
        elif callback_data == "view_all_tpsl":
            logger.info(f"📋 View All TP/SL clicked by user {user_id}")
            await handle_view_all_tpsl(query, context)
        elif callback_data.startswith("history_page_"):
            page = callback_data.split("_")[-1]
            logger.info(f"📜 History Page clicked - Page {page} by user {user_id}")
            await handle_history_page(query, context, callback_data)
        elif callback_data == "check_redeemable":
            logger.info(f"🔍 Check Redeemable clicked by user {user_id}")
            await handle_check_redeemable(query, context)
        elif callback_data.startswith("markets_page_"):
            page = callback_data.split("_")[-1]
            logger.info(f"📊 Markets Page clicked - Page {page} by user {user_id}")
            await handle_markets_page(query, context, callback_data)
        elif callback_data.startswith("tpsl_edit_"):
            position_id = callback_data.split("_")[-1]
            logger.info(f"✏️ TP/SL Edit clicked - Position {position_id} by user {user_id}")
            # Mark that user left positions view
            context.user_data['positions_view_active'] = False
            await handle_tpsl_edit(query, context, callback_data)
        elif callback_data.startswith("redeem_position_"):
            resolved_position_id = int(callback_data.split("_")[-1])
            logger.info(f"💰 Redeem Position clicked - Resolved Position {resolved_position_id} by user {user_id}")
            from telegram_bot.bot.handlers.positions.redeem_handler import handle_redeem_position
            await handle_redeem_position(query, resolved_position_id)
        elif callback_data.startswith("confirm_redeem_"):
            resolved_position_id = int(callback_data.split("_")[-1])
            logger.info(f"✅ Confirm Redeem clicked - Resolved Position {resolved_position_id} by user {user_id}")
            from telegram_bot.bot.handlers.positions.redeem_handler import handle_confirm_redeem
            await handle_confirm_redeem(query, resolved_position_id)
        elif callback_data == "cancel_redeem":
            logger.info(f"❌ Cancel Redeem clicked by user {user_id}")
            from telegram_bot.bot.handlers.positions.redeem_handler import handle_cancel_redeem
            await handle_cancel_redeem(query, context)
        else:
            logger.warning(f"Unknown position callback: {callback_data}")
            await query.edit_message_text("❌ Unknown action")

    except Exception as e:
        logger.error(f"Error handling position callback for user {query.from_user.id}: {e}")
        if query.message:
            await query.edit_message_text("❌ An error occurred. Please try again.")


async def _handle_position_detail(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle position detail view callback"""
    try:
        # Parse: "position_{position_id}"
        position_id = int(callback_data.split("_")[-1])

        # Get position (via API or DB)
        telegram_user_id = query.from_user.id
        logger.info(f"📊 Position Detail opened - Position {position_id} by user {telegram_user_id}")
        position = await get_position_helper(position_id, telegram_user_id)
        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Get market
        if SKIP_DB:
            api_client = get_api_client()
            market = await api_client.get_market(position.market_id)
        else:
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            market_service = get_market_service(cache_manager=cache_manager)
            market = await market_service.get_market_by_id(position.market_id)

        # Build detail view
        message_text, keyboard = build_position_detail_view(position, market)

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error showing position detail: {e}")
        await query.edit_message_text("❌ Error loading position details")


async def handle_view_all_tpsl(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle view all TP/SL orders"""
    try:
        telegram_user_id = query.from_user.id
        logger.info(f"📋 View All TP/SL opened by user {telegram_user_id}")

        # Get user data (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data:
            await query.edit_message_text("❌ User not found")
            return

        internal_id = user_data.get('id')
        if not internal_id:
            await query.edit_message_text("❌ User ID not found")
            return

        # Get all active TP/SL orders for this user (via API or DB)
        active_tpsl = []

        if SKIP_DB:
            # Workaround: Get positions and filter those with TP/SL
            # TODO: Add dedicated API endpoint for TP/SL orders
            api_client = get_api_client()
            positions_data = await api_client.get_user_positions(internal_id)
            if positions_data:
                positions_list = positions_data.get('positions', [])
                # Filter positions with TP/SL
                for pos_data in positions_list:
                    if pos_data.get('take_profit_price') or pos_data.get('stop_loss_price'):
                        # Convert to TP/SL order-like structure
                        active_tpsl.append({
                            'position_id': pos_data.get('id'),
                            'take_profit_price': pos_data.get('take_profit_price'),
                            'stop_loss_price': pos_data.get('stop_loss_price')
                        })
        else:
            # Direct DB access
            from core.services.tpsl.tpsl_service import tpsl_service
            active_tpsl = await tpsl_service.get_active_orders(internal_id)
            # Convert to list of dicts for consistency
            if active_tpsl:
                active_tpsl = [
                    {
                        'position_id': order.position_id,
                        'take_profit_price': order.take_profit_price,
                        'stop_loss_price': order.stop_loss_price
                    }
                    for order in active_tpsl
                ]

        if not active_tpsl:
            await query.edit_message_text(
                "🎯 **TP/SL Orders Overview**\n\n"
                "No active TP/SL orders found.\n\n"
                "💡 Set TP/SL on your positions to automatically sell when price targets are reached.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Back to Portfolio", callback_data="refresh_positions")
                ]])
            )
            return

        # Build overview message
        message = "🎯 **Active TP/SL Orders**\n\n"
        keyboard = []

        for i, order in enumerate(active_tpsl, 1):
            position_id = order.get('position_id') if isinstance(order, dict) else order.position_id

            # Get position info (via API or DB)
            position = await get_position_helper(position_id, telegram_user_id)
            if position:
                # Get market info (via API or DB)
                market = await get_market_data(position.market_id, context)
                market_title = market.get('title', 'Unknown')[:25] if market else 'Unknown'

                message += f"{i}. **{market_title}**\n"
                message += f"   Side: {position.outcome} • Qty: {position.amount:.0f}\n"

                take_profit_price = order.get('take_profit_price') if isinstance(order, dict) else order.take_profit_price
                stop_loss_price = order.get('stop_loss_price') if isinstance(order, dict) else order.stop_loss_price

                if take_profit_price:
                    tp_pct = (take_profit_price - position.entry_price) / position.entry_price * 100
                    message += f"   🎯 TP: ${take_profit_price:.4f} ({tp_pct:+.1f}%)\n"

                if stop_loss_price:
                    sl_pct = (stop_loss_price - position.entry_price) / position.entry_price * 100
                    message += f"   🛑 SL: ${stop_loss_price:.4f} ({sl_pct:+.1f}%)\n"

                message += "\n"

                # Action button for this order
                keyboard.append([
                    InlineKeyboardButton(f"✏️ {i}. Edit", callback_data=f"tpsl_edit_{position_id}")
                ])

        keyboard.append([
            InlineKeyboardButton("← Back to Portfolio", callback_data="refresh_positions")
        ])

        await query.edit_message_text(
            message.strip(),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in view_all_tpsl: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text("❌ Error loading TP/SL orders")


async def handle_history_page(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle history page navigation"""
    try:
        telegram_user_id = query.from_user.id
        page = callback_data.split("_")[-1] if "_" in callback_data else "0"
        logger.info(f"📜 History Page opened - Page {page} by user {telegram_user_id}")
        # For now, redirect to positions hub with a message
        await query.edit_message_text(
            "📜 **Trade History**\n\n"
            "Trade history feature coming soon!\n\n"
            "💡 This will show your past trades, P&L, and performance analytics.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← Back to Portfolio", callback_data="refresh_positions")
            ]])
        )
    except Exception as e:
        logger.error(f"Error in history_page: {e}")
        await query.edit_message_text("❌ Error loading history")


async def handle_check_redeemable(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle Check Redeemable button - detect and show redeemable positions
    Optimized to use closed-positions endpoint directly for efficiency
    """
    try:
        telegram_user_id = query.from_user.id
        logger.info(f"🔍 Check Redeemable clicked by user {telegram_user_id}")

        await query.answer("🔍 Checking for redeemable positions...")

        # Get user data
        user_data = await get_user_data(telegram_user_id)
        if not user_data:
            await query.edit_message_text("❌ User not found")
            return

        internal_id = user_data.get('id')
        polygon_address = user_data.get('polygon_address')

        if not internal_id or not polygon_address:
            await query.edit_message_text("❌ User data incomplete")
            return

        # Show loading message
        loading_text = "🔍 Checking for redeemable positions...\n\nThis may take a few seconds."
        await query.edit_message_text(loading_text)

        # ✅ OPTIMIZATION: Fetch both active and closed positions in parallel
        # This is more efficient than fetching only active positions
        import asyncio

        logger.info(f"🔍 [CHECK REDEEMABLE] Fetching positions for wallet {polygon_address[:10]}...")

        # Fetch active positions from blockchain
        active_task = position_service.get_positions_from_blockchain(polygon_address)
        # Fetch closed positions from Polymarket API directly
        closed_task = position_service.get_closed_positions_from_blockchain(polygon_address)

        # Execute both in parallel
        active_positions, closed_positions = await asyncio.gather(
            active_task, closed_task, return_exceptions=True
        )

        # Handle exceptions
        if isinstance(active_positions, Exception):
            logger.error(f"❌ Error fetching active positions: {active_positions}", exc_info=True)
            active_positions = []
        if isinstance(closed_positions, Exception):
            logger.error(f"❌ Error fetching closed positions: {closed_positions}", exc_info=True)
            closed_positions = []

        logger.info(f"📊 [CHECK REDEEMABLE] Fetched {len(active_positions)} active, {len(closed_positions)} closed positions")

        # Combine positions: closed positions with positive PnL are automatically redeemable
        # Mark closed positions for easier processing
        all_positions = []
        if active_positions:
            logger.debug(f"✅ [CHECK REDEEMABLE] Processing {len(active_positions)} active positions")
            for pos in active_positions:
                pos['closed'] = False
                all_positions.append(pos)

        if closed_positions:
            logger.info(f"✅ [CHECK REDEEMABLE] Processing {len(closed_positions)} closed positions")
            for pos in closed_positions:
                pos['closed'] = True
                # Add realizedPnl if not present (for compatibility)
                if 'realizedPnl' not in pos:
                    pos['realizedPnl'] = pos.get('profit', 0)

                # Log closed position details for debugging
                realized_pnl = pos.get('realizedPnl', 0)
                condition_id = pos.get('conditionId', pos.get('id', 'N/A'))
                title = pos.get('title', 'Unknown')[:50]
                logger.debug(
                    f"📋 [CHECK REDEEMABLE] Closed position: {title}... "
                    f"(conditionId={condition_id[:20]}..., realizedPnl=${realized_pnl:.2f})"
                )
                all_positions.append(pos)
        else:
            logger.warning(f"⚠️ [CHECK REDEEMABLE] No closed positions found from API for {polygon_address[:10]}...")

        if not all_positions:
            await query.edit_message_text(
                "✅ **No Positions Found**\n\n"
                "No active or closed positions found on blockchain.\n\n"
                "💡 Start trading to see your positions here!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📊 Back to Positions", callback_data="positions_hub")
                ]])
            )
            return

        # Detect redeemable positions (handles both active and closed)
        redeemable_positions = []
        redeemable_condition_ids = []

        logger.info(f"🔍 [CHECK REDEEMABLE] Detecting redeemable positions from {len(all_positions)} total positions")

        if SKIP_DB:
            api_client = get_api_client()
            # ✅ OPTIMIZATION: Use cache to avoid redundant API calls
            cache_key = f"redeemable_check:{internal_id}:{polygon_address}"
            cached_result = await api_client.cache_manager.get(cache_key)

            if cached_result:
                logger.debug(f"✅ [CACHE HIT] Using cached redeemable positions for user {internal_id}")
                redeemable_positions = cached_result.get('redeemable_positions', [])
                redeemable_condition_ids = cached_result.get('resolved_condition_ids', [])
                logger.info(f"📊 [CHECK REDEEMABLE] Found {len(redeemable_positions)} redeemable positions from cache")
            else:
                # Cache miss - detect redeemable positions
                logger.info(f"🔍 [CHECK REDEEMABLE] Cache miss - calling detect_redeemable_positions API")
                result = await api_client.detect_redeemable_positions(
                    internal_id,
                    all_positions,
                    polygon_address
                )
                if result:
                    redeemable_positions = result.get('redeemable_positions', [])
                    redeemable_condition_ids = result.get('resolved_condition_ids', [])
                    logger.info(
                        f"✅ [CHECK REDEEMABLE] API returned {len(redeemable_positions)} redeemable positions, "
                        f"{len(redeemable_condition_ids)} resolved condition IDs"
                    )

                    # Cache result for 5 minutes to reduce API/DB load
                    await api_client.cache_manager.set(
                        cache_key,
                        {
                            'redeemable_positions': redeemable_positions,
                            'resolved_condition_ids': redeemable_condition_ids
                        },
                        ttl=300  # 5 minutes
                    )
                    logger.debug(f"✅ [CACHE SET] Cached redeemable positions for user {internal_id}")
                else:
                    logger.warning(f"⚠️ [CHECK REDEEMABLE] API returned None or empty result")
        else:
            detector = get_redeemable_detector()
            redeemable_positions, redeemable_condition_ids = await detector.detect_redeemable_positions(
                all_positions,
                internal_id,
                polygon_address
            )
            logger.info(
                f"✅ [CHECK REDEEMABLE] Detector found {len(redeemable_positions)} redeemable positions, "
                f"{len(redeemable_condition_ids)} resolved condition IDs"
            )

        # ✅ NEW: Identify losing positions (resolved but not winners)
        # resolved_condition_ids contains both winners and losers
        # We need to find losing positions from active_positions and close them
        losing_positions = []
        if redeemable_condition_ids and active_positions:
            # Get resolved positions from API to check which are losers
            if SKIP_DB:
                resolved_positions_data = await api_client.get_resolved_positions(internal_id, use_cache=False)
                resolved_positions_list = resolved_positions_data.get('resolved_positions', []) if resolved_positions_data else []

                # Create a set of condition_ids for winning resolved positions
                winning_condition_ids = set()
                for rp in resolved_positions_list:
                    if rp.get('is_winner', False):
                        condition_id = rp.get('condition_id', '')
                        if condition_id:
                            winning_condition_ids.add(condition_id)

                # Find losing positions: in resolved_condition_ids but not winners
                for pos in active_positions:
                    condition_id = pos.get('conditionId', pos.get('id', ''))
                    if condition_id and condition_id in redeemable_condition_ids:
                        if condition_id not in winning_condition_ids:
                            # This is a losing position - should be closed
                            losing_positions.append(pos)
                            logger.info(
                                f"📉 [CHECK REDEEMABLE] Found losing position to close: "
                                f"{pos.get('title', 'Unknown')[:50]}... (condition_id={condition_id[:20]}...)"
                            )

        # Close losing positions via API
        closed_count = 0
        if losing_positions and SKIP_DB:
            logger.info(f"🔒 [CHECK REDEEMABLE] Closing {len(losing_positions)} losing positions...")
            for pos in losing_positions:
                try:
                    # Get position_id from DB via API
                    user_positions_data = await api_client.get_user_positions(internal_id, use_cache=False)
                    if user_positions_data:
                        positions_list = user_positions_data.get('positions', [])
                        condition_id = pos.get('conditionId', pos.get('id', ''))
                        outcome = pos.get('outcome', '')

                        # Find matching position in DB
                        for db_pos in positions_list:
                            if (db_pos.get('market_id') == condition_id or
                                db_pos.get('position_id') == pos.get('asset', '')) and \
                               db_pos.get('outcome', '').upper() == outcome.upper() and \
                               db_pos.get('status') == 'active':
                                position_id = db_pos.get('id')
                                if position_id:
                                    # Close position via API
                                    current_price = pos.get('curPrice', 0)
                                    result = await api_client.update_position(
                                        position_id=position_id,
                                        status="closed",
                                        current_price=current_price
                                    )
                                    if result:
                                        closed_count += 1
                                        logger.info(f"✅ [CHECK REDEEMABLE] Closed losing position {position_id}")
                                    break
                except Exception as e:
                    logger.error(f"❌ [CHECK REDEEMABLE] Error closing losing position: {e}", exc_info=True)

        # Build response message
        message_parts = []

        # Show losing positions info (if any were closed)
        if closed_count > 0:
            message_parts.append(f"📉 **{closed_count} Losing Position(s) Closed**\n\n")
            message_parts.append("The following positions were resolved as losses and have been removed from your active positions:\n\n")
            for idx, pos in enumerate(losing_positions[:3], 1):
                title = pos.get('title', 'Unknown Market')
                if len(title) > 50:
                    title = title[:47] + "..."
                outcome = pos.get('outcome', 'N/A')
                pnl = pos.get('cashPnl', 0)
                message_parts.append(f"{idx}. {title}\n")
                message_parts.append(f"   Outcome: {outcome} (Lost)\n")
                message_parts.append(f"   P&L: ${pnl:.2f}\n\n")
            if len(losing_positions) > 3:
                message_parts.append(f"*... and {len(losing_positions) - 3} more*\n\n")
            message_parts.append("━━━━━━━━━━━━━━━━━━━━\n\n")

        # Show winning positions (redeemable)
        if redeemable_positions:
            message_parts.append(f"🎊 **{len(redeemable_positions)} WINNING POSITION(S) FOUND**\n\n")
            message_parts.append("These positions are ready to redeem:\n\n")
            message_parts.append("━━━━━━━━━━━━━━━━━━━━\n\n")

            for idx, rp in enumerate(redeemable_positions[:5], 1):  # Show max 5
                title = rp.get('market_title', 'Unknown Market')
                if len(title) > 50:
                    title = title[:47] + "..."

                net_value = float(rp.get('net_value', 0))
                tokens = float(rp.get('tokens_held', 0))
                outcome = rp.get('outcome', 'YES')
                pnl = float(rp.get('pnl', 0))
                pnl_pct = float(rp.get('pnl_percentage', 0))

                profit_emoji = "📈" if pnl > 0 else "📉"
                profit_sign = "+" if pnl > 0 else ""

                message_parts.append(f"{idx}. {title}\n")
                message_parts.append(f"   💰 **Claimable:** ${net_value:.2f}\n")
                message_parts.append(f"   {profit_emoji} **P&L:** {profit_sign}${pnl:.2f} ({profit_sign}{pnl_pct:.1f}%)\n")
                message_parts.append(f"   📦 {tokens:.2f} {outcome} tokens\n\n")

            if len(redeemable_positions) > 5:
                message_parts.append(f"*... and {len(redeemable_positions) - 5} more*\n\n")

            message_parts.append("━━━━━━━━━━━━━━━━━━━━\n\n")
            message_parts.append("💡 Use /positions to see all claimable winnings and redeem them.")
        elif closed_count == 0:
            message_parts.append("✅ **No Redeemable Positions**\n\n")
            message_parts.append("All your positions are still active. Check back later when markets resolve!")

        message = "".join(message_parts)
        keyboard = [[InlineKeyboardButton("📊 Back to Positions", callback_data="positions_hub")]]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in check_redeemable: {e}", exc_info=True)
        await query.edit_message_text("❌ Error checking redeemable positions. Please try again.")


async def handle_markets_page(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle markets page navigation"""
    try:
        telegram_user_id = query.from_user.id
        page = callback_data.split("_")[-1] if "_" in callback_data else "0"
        logger.info(f"📊 Markets Page opened - Page {page} by user {telegram_user_id}")
        # Redirect to main markets handler
        from telegram_bot.bot.handlers.markets_handler import handle_market_callback
        # Simulate a markets callback
        from telegram import CallbackQuery
        fake_query = type('FakeQuery', (), {
            'data': 'markets_hub',
            'from_user': query.from_user,
            'message': query.message,
            'answer': query.answer,
            'edit_message_text': query.edit_message_text
        })()
        await handle_market_callback(type('FakeUpdate', (), {'callback_query': fake_query})(), context)
    except Exception as e:
        logger.error(f"Error in markets_page: {e}")
        await query.edit_message_text("❌ Error loading markets")


async def handle_tpsl_edit(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle TP/SL edit - redirect to setup which handles both create and edit"""
    try:
        position_id = int(callback_data.split("_")[-1])
        telegram_user_id = query.from_user.id
        logger.info(f"✏️ TP/SL Edit clicked - Position {position_id} by user {telegram_user_id}")
        # Redirect to TP/SL setup which can handle editing existing orders
        from telegram_bot.bot.handlers.positions.tpsl_handler import handle_tpsl_setup
        await handle_tpsl_setup(query, context, f"tpsl_setup_{position_id}")
    except Exception as e:
        logger.error(f"Error in tpsl_edit: {e}")
        await query.edit_message_text("❌ Error editing TP/SL")
