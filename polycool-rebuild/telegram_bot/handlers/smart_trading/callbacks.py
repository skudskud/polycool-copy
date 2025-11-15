"""
Smart Trading Callbacks Handler
Handles all smart trading inline keyboard callbacks
"""
import os
import traceback
from typing import Optional, Any, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.smart_trading import SmartTradingService
from core.services.api_client.api_client import get_api_client
from core.services.market.market_helper import get_market_data
from core.services.trading.trade_service import trade_service
from core.services.user.user_helper import get_user_data
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Initialize services
smart_trading_service = SmartTradingService()
api_client = get_api_client() if SKIP_DB else None


async def _resolve_market_by_position_id(position_id: str, context: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """
    Resolve market information using position_id (clob_token_id)
    Uses API endpoint /markets/by-token-id/{token_id} in SKIP_DB mode
    Uses DB directly in non-SKIP_DB mode

    Args:
        position_id: Token ID from blockchain (clob_token_id)
        context: Optional context for API mode

    Returns:
        Market information dict or None if not found
    """
    if not position_id:
        return None

    try:
        if SKIP_DB:
            # API mode: Use API endpoint /markets/by-token-id/{token_id}
            if api_client:
                logger.debug(f"🔍 [API] Resolving market by token_id: {position_id[:20]}...")
                market = await api_client._get(f"/markets/by-token-id/{position_id}", f"api:market:token:{position_id}", 'market_detail')
                if market:
                    logger.debug(f"✅ [API] Found market {market.get('id')} by token_id")
                    return market
                else:
                    logger.debug(f"⚠️ [API] Market not found by token_id: {position_id[:20]}...")
                    return None
            else:
                logger.error("❌ API client not available in SKIP_DB mode")
                return None
        else:
            # DB mode: Use service directly
            resolution = await smart_trading_service.resolve_market_by_position_id(position_id)
            if resolution:
                # Get full market data
                from core.services.market.market_helper import get_market_data
                market = await get_market_data(resolution['id'], context)
                if market:
                    return market
            return None
    except Exception as e:
        logger.error(f"❌ Error resolving market by position_id {position_id[:20]}...: {e}\n{traceback.format_exc()}")
        return None


def _get_current_page_trades(context):
    """Helper function to get trades for the current page"""
    current_page = context.user_data.get('smart_trades_page', 1)

    # Use pre-filtered trades if available (from _display_trades_page)
    # This ensures consistency between display and callback handlers
    filtered_trades = context.user_data.get('smart_trades_filtered', [])

    if not filtered_trades:
        # Fallback: if filtered trades not available, return empty list
        # This should not happen if _display_trades_page was called first
        return []

    # Get trades for current page
    TRADES_PER_PAGE = 5
    start_idx = (current_page - 1) * TRADES_PER_PAGE
    end_idx = start_idx + TRADES_PER_PAGE
    return filtered_trades[start_idx:end_idx]


async def handle_smart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle smart trading callback queries
    Routes: smart_view_{index}, smart_buy_{index}, smart_page_{page}, smart_quick_buy_{market_id}_{outcome}, smart_custom_buy_{outcome}_{market_id}
    """
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id

    logger.info(f"📨 SMART TRADING CALLBACK: {callback_data} (user: {user_id})")

    try:
        # Don't call query.answer() here - each handler will call it with appropriate parameters
        # This prevents double answer() calls which can cause segmentation faults

        # Check most specific patterns first to avoid conflicts
        if callback_data.startswith("smart_view_"):
            # View market for a trade
            index = int(callback_data.split("_")[-1])
            logger.info(f"📊 Routing to _handle_view_market with index {index}")
            await _handle_view_market(query, context, index)
        elif callback_data.startswith("smart_quick_buy_"):
            # Quick buy from market view (MUST be checked before smart_buy_)
            # Format: smart_quick_buy_{market_id}_{outcome}
            parts = callback_data.split("_")
            if len(parts) >= 5:  # smart_quick_buy_{market_id}_{outcome}
                market_id = parts[3]  # e.g., "12345"
                outcome = "_".join(parts[4:])  # e.g., "Yes" or "No"
                logger.info(f"⚡ Routing to _handle_smart_quick_buy_from_market with market_id={market_id}, outcome={outcome}")
                await _handle_smart_quick_buy_from_market(query, context, market_id, outcome)
            else:
                logger.error(f"❌ Invalid smart_quick_buy_ callback format: {callback_data}")
                await query.answer("❌ Invalid callback format", show_alert=True)
        elif callback_data.startswith("smart_buy_"):
            # Quick buy for a trade (from main list)
            # Format: smart_buy_{index}
            index = int(callback_data.split("_")[-1])
            logger.info(f"⚡ Routing to _handle_quick_buy with index {index}")
            await _handle_quick_buy(query, context, index)
        elif callback_data.startswith("smart_custom_buy_"):
            # Custom buy - can be from main list or market view
            # Format: smart_custom_buy_{index} (from main list)
            # Format: smart_custom_buy_{outcome}_{market_id} (from market view)
            parts = callback_data.split("_")
            if len(parts) == 4:  # smart_custom_buy_{index}
                index = int(parts[-1])
                logger.info(f"💰 Routing to _handle_custom_buy with index {index}")
                await _handle_custom_buy(query, context, index)
            elif len(parts) >= 5:  # smart_custom_buy_{outcome}_{market_id}
                outcome = parts[3]  # e.g., "yes" or "no"
                market_id = "_".join(parts[4:])  # Handle market IDs with underscores
                logger.info(f"💰 Routing to _handle_smart_custom_buy_from_market with market_id={market_id}, outcome={outcome}")
                await _handle_smart_custom_buy_from_market(query, context, market_id, outcome)
            else:
                logger.error(f"❌ Invalid smart_custom_buy_ callback format: {callback_data}")
                await query.answer("❌ Invalid callback format", show_alert=True)
        elif callback_data.startswith("smart_page_"):
            # Pagination
            page = int(callback_data.split("_")[-1])
            logger.info(f"📄 Routing to _handle_pagination with page {page}")
            await _handle_pagination(query, context, page)
        else:
            logger.warning(f"❌ Unknown smart trading callback: {callback_data}")
            await query.answer("❌ Unknown action", show_alert=True)

    except Exception as e:
        logger.error(f"❌ Error handling smart trading callback for user {user_id}: {e}\n{traceback.format_exc()}")
        if query.message:
            await query.edit_message_text("❌ An error occurred. Please try again.")


async def _handle_view_market(query, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    """Handle view market callback - redirect to Polymarket URL"""
    try:
        # Answer callback first
        await query.answer()

        page_trades = _get_current_page_trades(context)
        if not page_trades or index < 1 or index > len(page_trades):
            await query.message.reply_text("❌ Trade not found on this page")
            return

        trade = page_trades[index - 1]

        # Validate trade has required fields
        if not trade or not isinstance(trade, dict):
            logger.error(f"Invalid trade object: {trade}")
            await query.message.reply_text("❌ Invalid trade data")
            return

        # Get Polymarket URL from trade (already resolved in view_handler)
        polymarket_url = trade.get('polymarket_url')

        if not polymarket_url:
            # Try to resolve market to get URL
            position_id = trade.get('position_id')
            if position_id:
                market = await _resolve_market_by_position_id(position_id, context)
                if market:
                    polymarket_url = market.get('polymarket_url')

        if polymarket_url:
            # Show message with link button
            market_title = trade.get('resolved_market_title') or trade.get('market_title', 'Market')
            message = f"**{market_title}**\n\n"
            message += "Click the button below to view this market on Polymarket:"

            keyboard = [
                [InlineKeyboardButton("🔗 Open on Polymarket", url=polymarket_url)],
                [InlineKeyboardButton("← Back to Smart Trading", callback_data=f"smart_page_{context.user_data.get('smart_trades_page', 1)}")]
            ]

            await query.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            # No URL available
            await query.message.reply_text(
                "❌ **Market URL Not Available**\n\n"
                "This market's Polymarket URL is not available.\n"
                "Please try again later.",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error viewing market: {e}\n{traceback.format_exc()}")
        await query.message.reply_text("❌ Error loading market details")


async def _handle_quick_buy(query, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    """Handle quick buy callback - buy $2 worth of the smart trader's outcome (direct execution, no confirmation)"""
    user_id = query.from_user.id
    amount_usd = 2.0

    try:
        logger.info(f"⚡ [QUICK_BUY] Starting quick buy $2 for user {user_id}, trade index {index}")

        page_trades = _get_current_page_trades(context)
        if not page_trades or index < 1 or index > len(page_trades):
            logger.warning(f"⚠️ [QUICK_BUY] Trade not found on page: index={index}, page_trades_len={len(page_trades) if page_trades else 0}")
            await query.answer("❌ Trade not found on this page", show_alert=True)
            return

        trade = page_trades[index - 1]

        # Validate trade has required fields
        if not trade or not isinstance(trade, dict):
            logger.error(f"❌ [QUICK_BUY] Invalid trade object for user {user_id}: {trade}")
            await query.answer("❌ Invalid trade data", show_alert=True)
            return

        position_id = trade.get('position_id')
        outcome = trade.get('outcome')
        if not position_id or not outcome:
            logger.error(f"❌ [QUICK_BUY] Trade missing required fields for user {user_id}: position_id={position_id}, outcome={outcome}")
            await query.answer("❌ Trade data incomplete", show_alert=True)
            return

        # Answer callback after all validations pass (before async operations)
        await query.answer("⚡ Executing $2 buy...")

        # Resolve market using position_id (clob_token_id) via clob_token_ids lookup
        logger.info(f"🔍 [QUICK_BUY] Resolving market by position_id: {position_id[:20]}...")
        market = await _resolve_market_by_position_id(position_id, context)
        if not market:
            logger.error(f"❌ [QUICK_BUY] Market not found for user {user_id}: position_id={position_id[:20]}...")
            market_title = trade.get('market_title', 'Unknown Market')
            await query.message.reply_text(
                f"❌ **Market Not Available**\n\n"
                f"Market: {market_title}\n\n"
                f"This market may not be indexed yet in our database.\n"
                f"Please try again later or use /markets to browse available markets.",
                parse_mode='Markdown'
            )
            return

        # Use resolved market ID
        market_id_short = market.get('id')
        if not market_id_short:
            logger.error(f"❌ [QUICK_BUY] Market ID not found in market data for user {user_id}")
            await query.answer("❌ Market ID not found", show_alert=True)
            return

        # Get full market data if we only have partial data
        if not market.get('outcomes') or not market.get('outcome_prices'):
            logger.info(f"📊 [QUICK_BUY] Fetching full market data for {market_id_short}")
            full_market = await get_market_data(market_id_short, context)
            if full_market:
                market = full_market

        logger.info(f"📊 [QUICK_BUY] Executing trade: user={user_id}, market_id={market_id_short}, outcome={outcome}, amount=${amount_usd}")

        # Get market title for display
        market_title = market.get('title', 'Unknown Market')

        # Send message showing execution in progress
        await query.message.reply_text(
            "⚡ **Executing trade...**\n\n"
            "Please wait while your order is being processed.\n"
            "This may take a few seconds.",
            parse_mode='Markdown'
        )

        # Execute trade using TradeService (same as /markets)
        result = await trade_service.execute_market_order(
            user_id=user_id,
            market_id=market_id_short,
            outcome=outcome,
            amount_usd=amount_usd,
            order_type='FOK'  # Fill-or-Kill
        )

        # Handle result
        if result.get('success') or result.get('status') == 'executed':
            # Extract trade data
            if 'trade' in result:
                trade_data = result['trade']
                tokens = trade_data.get('tokens', 0)
                usd_price_per_share = trade_data.get('usd_price_per_share')
                price = trade_data.get('price', 0)
                usd_spent = trade_data.get('usd_spent', amount_usd)
                tx_hash = trade_data.get('tx_hash')
            else:
                tokens = result.get('tokens', 0)
                usd_price_per_share = result.get('usd_price_per_share')
                price = result.get('price', 0)
                usd_spent = result.get('usd_spent', amount_usd)
                tx_hash = result.get('tx_hash')

            # Calculate price per share if not available
            if usd_price_per_share is None and tokens > 0 and usd_spent > 0:
                usd_price_per_share = usd_spent / tokens
            elif usd_price_per_share is None:
                usd_price_per_share = price

            logger.info(f"✅ [QUICK_BUY] Success: user={user_id}, tokens={tokens:.2f}, spent=${usd_spent:.2f}")

            # Send success message with trade details (same format as /markets)
            message = f"""
✅ **ORDER EXECUTED**

Market: {market_title[:50]}...
Side: BUY {outcome}
Shares: {tokens:.2f}
Price: ${usd_price_per_share:.4f}
Total Cost: ${usd_spent:.2f}

Transaction: `{tx_hash[:16] if tx_hash else 'N/A'}...`

💡 Your position is now live!
Use /positions to view and manage it.
""".strip()

            keyboard = [
                [InlineKeyboardButton("📊 View Positions", callback_data="view_positions")],
                [InlineKeyboardButton("← Back to Smart Trading", callback_data=f"smart_page_{context.user_data.get('smart_trades_page', 1)}")]
            ]

            await query.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

            # Refresh the smart trading page
            page = context.user_data.get('smart_trades_page', 1)
            from .view_handler import _display_trades_page
            await _display_trades_page(query, context, page=page, is_callback=True)
        else:
            error_msg = result.get('error') or 'Unknown error'
            logger.error(f"❌ [QUICK_BUY] Failed for user {user_id}: {error_msg}")
            await query.message.reply_text(
                f"❌ Order failed: {error_msg}\n\n"
                "Please try again or contact support."
            )

    except Exception as e:
        logger.error(f"❌ [QUICK_BUY] Error for user {user_id}: {e}\n{traceback.format_exc()}")
        await query.answer("❌ Error processing buy request", show_alert=True)


async def _handle_custom_buy(query, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    """Handle custom buy callback - store trade data and show amount prompt (reuses /markets logic)"""
    user_id = query.from_user.id

    try:
        logger.info(f"💰 [CUSTOM_BUY] Starting custom buy for user {user_id}, trade index {index}")

        page_trades = _get_current_page_trades(context)
        if not page_trades or index < 1 or index > len(page_trades):
            logger.warning(f"⚠️ [CUSTOM_BUY] Trade not found on page: index={index}, page_trades_len={len(page_trades) if page_trades else 0}")
            await query.answer("❌ Trade not found on this page", show_alert=True)
            return

        trade = page_trades[index - 1]

        # Validate trade has required fields
        if not trade or not isinstance(trade, dict):
            logger.error(f"❌ [CUSTOM_BUY] Invalid trade object for user {user_id}: {trade}")
            await query.answer("❌ Invalid trade data", show_alert=True)
            return

        position_id = trade.get('position_id')
        outcome = trade.get('outcome')
        if not position_id or not outcome:
            logger.error(f"❌ [CUSTOM_BUY] Trade missing required fields for user {user_id}: position_id={position_id}, outcome={outcome}")
            await query.answer("❌ Trade data incomplete", show_alert=True)
            return

        # Answer callback after all validations pass
        await query.answer()

        # Resolve market using position_id (clob_token_id) via clob_token_ids lookup
        logger.info(f"🔍 [CUSTOM_BUY] Resolving market by position_id: {position_id[:20]}...")
        market = await _resolve_market_by_position_id(position_id, context)
        if not market:
            logger.error(f"❌ [CUSTOM_BUY] Market not found for user {user_id}: position_id={position_id[:20]}...")
            market_title = trade.get('market_title', 'Unknown Market')
            await query.message.reply_text(
                f"❌ **Market Not Available**\n\n"
                f"Market: {market_title}\n\n"
                f"This market may not be indexed yet in our database.\n"
                f"Please try again later or use /markets to browse available markets.",
                parse_mode='Markdown'
            )
            return

        # Get full market data if we only have partial data
        market_id_short = market.get('id')
        if not market_id_short:
            logger.error(f"❌ [CUSTOM_BUY] Market ID not found in market data for user {user_id}")
            await query.answer("❌ Market ID not found", show_alert=True)
            return

        if not market.get('outcomes') or not market.get('outcome_prices'):
            logger.info(f"📊 [CUSTOM_BUY] Fetching full market data for {market_id_short}")
            full_market = await get_market_data(market_id_short, context)
            if full_market:
                market = full_market

        # Store trade data in context for custom buy flow (use resolved market ID)

        # Reuse the same logic as /markets - store in context for handle_search_message
        context.user_data['custom_buy_market_id'] = market_id_short
        context.user_data['custom_buy_outcome'] = outcome
        context.user_data['awaiting_custom_amount'] = True

        logger.info(f"📝 [CUSTOM_BUY] Prompting for amount: user={user_id}, market_id={market_id_short}, outcome={outcome}")

        # Send amount prompt as new message (same format as /markets)
        await query.message.reply_text(
            f"💵 **Custom Buy - {outcome}**\n\n"
            "Enter the amount in USDC you want to invest:\n"
            "(Example: 25.50)",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"❌ [CUSTOM_BUY] Error for user {user_id}: {e}\n{traceback.format_exc()}")
        await query.answer("❌ Error processing custom buy request", show_alert=True)


async def _handle_pagination(query, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    """Handle pagination callback - client-side pagination"""
    try:
        # Answer callback first
        await query.answer()

        # Check if we have the raw trades data loaded
        trades_data = context.user_data.get('smart_trades_raw', [])
        if not trades_data:
            await query.edit_message_text("❌ No trades data available. Please run /smart_trading again.")
            return

        # Update current page in context
        context.user_data['smart_trades_page'] = page

        # Display the requested page (client-side pagination will handle it)
        from .view_handler import _display_trades_page
        await _display_trades_page(query, context, page=page, is_callback=True)

    except Exception as e:
        logger.error(f"Error handling pagination: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("❌ Error loading page")


async def _handle_smart_quick_buy_from_market(query, context: ContextTypes.DEFAULT_TYPE, market_id: str, outcome: str) -> None:
    """Handle quick buy callback from market view - buy $2 worth of the selected outcome (direct execution, no confirmation)"""
    user_id = query.from_user.id
    amount_usd = 2.0

    try:
        logger.info(f"⚡ [QUICK_BUY_MARKET] Starting quick buy $2 for user {user_id}, market_id={market_id}, outcome={outcome}")

        # Answer callback first
        await query.answer("⚡ Executing $2 buy...")

        # Get market data to verify market exists and normalize outcome
        market = await get_market_data(market_id, context)
        if not market:
            logger.error(f"❌ [QUICK_BUY_MARKET] Market not found for user {user_id}: market_id={market_id}")
            await query.answer("❌ Market not found", show_alert=True)
            return

        # Normalize outcome name (Yes/No vs YES/NO)
        outcomes = market.get('outcomes', [])
        outcome_normalized = outcome.upper()
        actual_outcome = None

        for o in outcomes:
            if o.upper() == outcome_normalized:
                actual_outcome = o
                break

        if actual_outcome is None:
            # Try to find by first letter
            if outcome_normalized.startswith('Y') and len(outcomes) > 0:
                actual_outcome = outcomes[0]
            elif outcome_normalized.startswith('N') and len(outcomes) > 1:
                actual_outcome = outcomes[1]
            else:
                actual_outcome = outcomes[0] if outcomes else outcome

        logger.info(f"📊 [QUICK_BUY_MARKET] Executing trade: user={user_id}, market_id={market_id}, outcome={actual_outcome}, amount=${amount_usd}")

        # Get market title for display
        market_title = market.get('title', 'Unknown Market')

        # Send message showing execution in progress
        await query.message.reply_text(
            "⚡ **Executing trade...**\n\n"
            "Please wait while your order is being processed.\n"
            "This may take a few seconds.",
            parse_mode='Markdown'
        )

        # Execute trade using TradeService (same as /markets)
        result = await trade_service.execute_market_order(
            user_id=user_id,
            market_id=market_id,
            outcome=actual_outcome,
            amount_usd=amount_usd,
            order_type='FOK'  # Fill-or-Kill
        )

        # Handle result
        if result.get('success') or result.get('status') == 'executed':
            # Extract trade data
            if 'trade' in result:
                trade_data = result['trade']
                tokens = trade_data.get('tokens', 0)
                usd_price_per_share = trade_data.get('usd_price_per_share')
                price = trade_data.get('price', 0)
                usd_spent = trade_data.get('usd_spent', amount_usd)
                tx_hash = trade_data.get('tx_hash')
            else:
                tokens = result.get('tokens', 0)
                usd_price_per_share = result.get('usd_price_per_share')
                price = result.get('price', 0)
                usd_spent = result.get('usd_spent', amount_usd)
                tx_hash = result.get('tx_hash')

            # Calculate price per share if not available
            if usd_price_per_share is None and tokens > 0 and usd_spent > 0:
                usd_price_per_share = usd_spent / tokens
            elif usd_price_per_share is None:
                usd_price_per_share = price

            logger.info(f"✅ [QUICK_BUY_MARKET] Success: user={user_id}, tokens={tokens:.2f}, spent=${usd_spent:.2f}")

            # Send success message with trade details (same format as /markets)
            message = f"""
✅ **ORDER EXECUTED**

Market: {market_title[:50]}...
Side: BUY {actual_outcome}
Shares: {tokens:.2f}
Price: ${usd_price_per_share:.4f}
Total Cost: ${usd_spent:.2f}

Transaction: `{tx_hash[:16] if tx_hash else 'N/A'}...`

💡 Your position is now live!
Use /positions to view and manage it.
""".strip()

            keyboard = [
                [InlineKeyboardButton("📊 View Positions", callback_data="view_positions")],
                [InlineKeyboardButton("← Back to Smart Trading", callback_data=f"smart_page_{context.user_data.get('smart_trades_page', 1)}")]
            ]

            await query.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            error_msg = result.get('error') or 'Unknown error'
            logger.error(f"❌ [QUICK_BUY_MARKET] Failed for user {user_id}: {error_msg}")
            await query.message.reply_text(
                f"❌ Order failed: {error_msg}\n\n"
                "Please try again or contact support."
            )

    except Exception as e:
        logger.error(f"❌ [QUICK_BUY_MARKET] Error for user {user_id}: {e}\n{traceback.format_exc()}")
        await query.answer("❌ Error processing buy request", show_alert=True)


async def _handle_smart_custom_buy_from_market(query, context: ContextTypes.DEFAULT_TYPE, market_id: str, outcome: str) -> None:
    """Handle custom buy callback from market view - store market data and show amount prompt (reuses /markets logic)"""
    user_id = query.from_user.id

    try:
        logger.info(f"💰 [CUSTOM_BUY_MARKET] Starting custom buy for user {user_id}, market_id={market_id}, outcome={outcome}")

        # Answer callback first
        await query.answer()

        # Get market data to verify market exists and get proper outcome name
        market = await get_market_data(market_id, context)
        if not market:
            logger.error(f"❌ [CUSTOM_BUY_MARKET] Market not found for user {user_id}: market_id={market_id}")
            await query.answer("❌ Market not found", show_alert=True)
            return

        # Normalize outcome name to match market outcomes
        outcomes = market.get('outcomes', [])
        outcome_normalized = outcome.upper()
        actual_outcome = None

        for o in outcomes:
            if o.upper() == outcome_normalized:
                actual_outcome = o
                break

        if actual_outcome is None:
            # Try to find by first letter
            if outcome_normalized.startswith('Y') and len(outcomes) > 0:
                actual_outcome = outcomes[0]
            elif outcome_normalized.startswith('N') and len(outcomes) > 1:
                actual_outcome = outcomes[1]
            else:
                actual_outcome = outcomes[0] if outcomes else outcome

        # Reuse the same logic as /markets - store in context for handle_search_message
        context.user_data['custom_buy_market_id'] = market_id
        context.user_data['custom_buy_outcome'] = actual_outcome
        context.user_data['awaiting_custom_amount'] = True

        logger.info(f"📝 [CUSTOM_BUY_MARKET] Prompting for amount: user={user_id}, market_id={market_id}, outcome={actual_outcome}")

        # Send amount prompt as new message (same format as /markets)
        await query.message.reply_text(
            f"💵 **Custom Buy - {actual_outcome}**\n\n"
            "Enter the amount in USDC you want to invest:\n"
            "(Example: 25.50)",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"❌ [CUSTOM_BUY_MARKET] Error for user {user_id}: {e}\n{traceback.format_exc()}")
        await query.answer("❌ Error processing custom buy request", show_alert=True)
