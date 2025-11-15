"""
Positions Refresh Handler
Handles position synchronization and price updates
"""
import os
from telegram import InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.user.user_helper import get_user_data
from core.services.user.user_service import user_service
from core.services.position.position_service import position_service
from core.services.clob.clob_service import get_clob_service
from core.services.market.market_helper import get_market_data
from core.services.balance.balance_service import balance_service
from telegram_bot.bot.handlers.positions.view_builder import build_positions_view
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_refresh_positions(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle refresh positions callback"""
    try:
        telegram_user_id = query.from_user.id
        logger.info(f"🔄 Refreshing positions for user {telegram_user_id}")

        # Get user data (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data:
            await query.edit_message_text("❌ User not found")
            return

        internal_id = user_data.get('id')
        polygon_address = user_data.get('polygon_address')

        if not internal_id:
            await query.edit_message_text("❌ User ID not found")
            return

        await query.answer("🔄 Refreshing positions...")

        # Sync and update positions (via API or DB)
        synced = 0
        updated = 0

        if SKIP_DB:
            # Use API endpoint for syncing
            api_client = get_api_client()
            sync_result = await api_client.sync_positions(internal_id)
            if sync_result:
                synced = sync_result.get('synced_positions', 0)
                updated = sync_result.get('updated_prices', 0)
                logger.info(f"Synced {synced} positions via API, updated {updated} prices")
            else:
                logger.warning(f"Position sync via API failed for user {internal_id}")
        else:
            # Direct DB access
            synced = await position_service.sync_positions_from_blockchain(
                user_id=internal_id,
                wallet_address=polygon_address
            )
            logger.info(f"Synced {synced} positions from blockchain")

            updated = await position_service.update_all_positions_prices(user_id=internal_id)
            logger.info(f"Updated prices for {updated} positions")

        # Get positions (via API or DB) - force fresh fetch to avoid stale cache
        positions = None
        if SKIP_DB:
            api_client = get_api_client()
            # ✅ CRITICAL: Invalidate cache first to ensure fresh data (positions AND markets)
            await api_client.cache_manager.invalidate_pattern(f"api:positions:{internal_id}")
            logger.info(f"🗑️ Invalidated positions cache for user {internal_id} before fetch")

            positions_data = await api_client.get_user_positions(internal_id, use_cache=False)
            if positions_data:
                # Convert API response to position-like objects
                positions_list = positions_data.get('positions', [])

                # Import PositionFromAPI from positions_handler
                from telegram_bot.bot.handlers.positions_handler import PositionFromAPI

                # Filter: only active positions with amount > 0
                positions = [
                    PositionFromAPI(pos)
                    for pos in positions_list
                    if pos.get('status') == 'active'
                    and pos.get('amount', 0) > 0
                ]
                logger.info(f"📊 Refresh: Fetched {len(positions_list)} positions from API, filtered to {len(positions)} active positions with amount > 0")
            else:
                positions = []
                logger.warning(f"⚠️ No positions data returned from API for user {internal_id}")
        else:
            positions = await position_service.get_active_positions(user_id=internal_id)
            # Filter positions with amount > 0
            positions = [p for p in positions if p.amount and p.amount > 0]
            logger.info(f"📊 Refresh: Fetched {len(positions)} active positions from DB with amount > 0")

        # Get markets and recalculate P&L with current prices from markets table
        markets_map = {}
        positions_recalculated = 0

        if SKIP_DB:
            api_client = get_api_client()
            # Import _extract_position_price_from_market from positions_handler
            from telegram_bot.bot.handlers.positions_handler import _extract_position_price_from_market

            for position in positions:
                if position.market_id not in markets_map:
                    market = await api_client.get_market(position.market_id)
                    if market:
                        markets_map[position.market_id] = market

                # Recalculate P&L with current market price from markets.outcome_prices
                market = markets_map.get(position.market_id, {})
                if market:
                    # ✅ CRITICAL: Extract current price from market data
                    # When source='ws', _extract_position_price_from_market() uses ONLY outcome_prices (no fallbacks)
                    # This ensures P&L always uses latest WebSocket prices from markets.outcome_prices
                    current_price = _extract_position_price_from_market(market, position.outcome)
                    if current_price is not None:
                        # Always recalculate if we have a valid price
                        # This ensures P&L uses latest WebSocket prices from markets.outcome_prices
                        position.recalculate_pnl(current_price)
                        positions_recalculated += 1
                        logger.debug(
                            f"🔄 Recalculated P&L for position {position.id} with market price {current_price:.4f}: "
                            f"${position.pnl_amount:.2f} ({position.pnl_percentage:+.1f}%)"
                        )
                    else:
                        # No price available - log warning but keep existing P&L
                        logger.warning(f"⚠️ No market price available for position {position.id} (market {position.market_id})")
        else:
            for position in positions:
                if position.market_id not in markets_map:
                    market = await get_market_data(position.market_id, context)
                    if market:
                        markets_map[position.market_id] = market

                # Recalculate P&L with current market price
                market = markets_map.get(position.market_id)
                if market:
                    from telegram_bot.bot.handlers.positions_handler import _extract_position_price_from_market
                    current_price = _extract_position_price_from_market(market, position.outcome)
                    if current_price is not None:
                        # For DB positions, update via service
                        try:
                            updated = await position_service.update_position_price(position.id, current_price)
                            if updated:
                                position.pnl_amount = updated.pnl_amount
                                position.pnl_percentage = updated.pnl_percentage
                                position.current_price = updated.current_price
                                positions_recalculated += 1
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to update P&L for position {position.id}: {e}")

        if positions_recalculated > 0:
            logger.info(f"✅ Recalculated P&L for {positions_recalculated} positions with current market prices")

        # Calculate totals (using recalculated P&L values)
        total_pnl = sum(p.pnl_amount for p in positions)
        total_invested = sum(p.entry_price * p.amount for p in positions)
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

        # Truncate message if too long (Telegram limit is 4096 characters)
        MAX_MESSAGE_LENGTH = 4096
        if len(message_text) > MAX_MESSAGE_LENGTH:
            logger.warning(f"⚠️ Message too long ({len(message_text)} chars), truncating to {MAX_MESSAGE_LENGTH}")
            # Truncate and add indicator
            truncated_text = message_text[:MAX_MESSAGE_LENGTH - 50]
            message_text = truncated_text + "\n\n⚠️ Message truncated..."

        # Only update if content actually changed to avoid "Message is not modified" error
        try:
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            error_str = str(e)
            if "Message is not modified" in error_str:
                # Content hasn't changed, just acknowledge the callback
                logger.debug("Position data unchanged, skipping message update")
                await query.answer("✅ Data is up to date")
                return
            elif "Bad Request" in error_str or "400" in error_str:
                # HTTP 400 - likely message format issue
                logger.error(f"❌ HTTP 400 error editing message: {e}")
                logger.debug(f"Message length: {len(message_text)}, Keyboard buttons: {len(keyboard)}")
                # Try to send a simpler message
                try:
                    await query.edit_message_text(
                        f"📊 **Your Positions**\n\n{len(positions)} active position(s)\n\n⚠️ Use /positions for full details",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except Exception as e2:
                    logger.error(f"❌ Failed to send fallback message: {e2}")
                    await query.answer("⚠️ Error updating message")
            else:
                # Re-raise other exceptions
                logger.error(f"❌ Unexpected error editing message: {e}")
                raise

    except Exception as e:
        logger.error(f"Error refreshing positions: {e}")
        await query.edit_message_text("❌ Error refreshing positions")
