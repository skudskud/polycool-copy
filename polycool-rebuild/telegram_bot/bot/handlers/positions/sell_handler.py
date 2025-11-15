"""
Positions Sell Handler
Handles position selling operations and confirmations
"""
import os
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# get_db removed - not used in this handler
from core.services.user.user_helper import get_user_data
from core.services.user.user_service import user_service
from core.services.position.position_service import position_service
from core.services.position.outcome_helper import find_outcome_index
from core.services.clob.clob_service import get_clob_service
from core.services.market.market_helper import get_market_data
from telegram_bot.bot.handlers.positions.view_builder import format_price_with_precision
from infrastructure.logging.logger import get_logger
from typing import Dict, Any

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


def _get_current_websocket_price(market: Dict, outcome: str, position: Any) -> float:
    """
    Get current WebSocket price from market data

    CRITICAL: Always uses WebSocket prices when available (source='ws')
    Falls back to position.current_price or position.entry_price only if WebSocket price unavailable

    Args:
        market: Market data dict (includes 'source' and 'outcome_prices')
        outcome: Position outcome ("YES" or "NO")
        position: Position object (for fallback)

    Returns:
        Current price (0-1) from WebSocket or fallback
    """
    from telegram_bot.bot.handlers.positions_handler import _extract_position_price_from_market

    # Try to get WebSocket price first
    price = _extract_position_price_from_market(market, outcome)

    if price is not None:
        return price

    # Fallback to position.current_price or position.entry_price only if WebSocket unavailable
    logger.warning(f"⚠️ WebSocket price unavailable for market {market.get('id', 'unknown')}, using position price as fallback")
    return position.current_price if position.current_price else position.entry_price


async def handle_sell_position(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle sell position callback - show amount selection"""
    try:
        # Parse: "sell_position_{position_id}"
        position_id = int(callback_data.split("_")[-1])

        # Get position (via API or DB)
        telegram_user_id = query.from_user.id
        logger.info(f"💸 Sell Position opened - Position {position_id} by user {telegram_user_id}")
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, telegram_user_id)
        else:
            position = await position_service.get_position(position_id)
        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Get user (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data or user_data.get('id') != position.user_id:
            await query.edit_message_text("❌ Unauthorized")
            return

        # Get market (via API or DB)
        market = await get_market_data(position.market_id, context)

        if not market:
            await query.edit_message_text("❌ Market not found")
            return

        # Calculate position value - CRITICAL: Use WebSocket price from market
        current_price = _get_current_websocket_price(market, position.outcome, position)
        position_value = current_price * position.amount

        # Store in context for confirmation
        context.user_data['pending_sell'] = {
            'position_id': position_id,
            'position': position,
            'market': market
        }

        # Build amount selection message
        current_price_formatted = format_price_with_precision(current_price, market)
        message = f"💰 **Sell Position**\n\n"
        message += f"Market: {market.get('title', 'Unknown')[:60]}...\n"
        message += f"Outcome: {position.outcome}\n"
        message += f"Current Price: {current_price_formatted}\n"
        message += f"Position Value: ${position_value:.2f}\n"
        message += f"Tokens: {position.amount:.0f}\n\n"
        message += "Select amount to sell:"

        # Calculate sell amounts (25%, 50%, 75%, 100%)
        keyboard = [
            [
                InlineKeyboardButton("25%", callback_data=f"sell_amount_{position_id}_25"),
                InlineKeyboardButton("50%", callback_data=f"sell_amount_{position_id}_50")
            ],
            [
                InlineKeyboardButton("75%", callback_data=f"sell_amount_{position_id}_75"),
                InlineKeyboardButton("100%", callback_data=f"sell_amount_{position_id}_100")
            ],
            [InlineKeyboardButton("💰 Custom Amount", callback_data=f"sell_custom_{position_id}")],
            [InlineKeyboardButton("← Back", callback_data=f"position_{position_id}")]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling sell position: {e}")
        await query.edit_message_text("❌ Error processing sell request")


async def handle_sell_amount(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle sell amount selection callback"""
    try:
        # Parse: "sell_amount_{position_id}_{percentage}"
        telegram_user_id = query.from_user.id
        logger.info(f"💰 Sell Amount selected - Callback: {callback_data} by user {telegram_user_id}")
        parts = callback_data.split("_")
        position_id = int(parts[2])
        percentage = int(parts[3])

        # Get position (via API or DB)
        telegram_user_id = query.from_user.id
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, telegram_user_id)
        else:
            position = await position_service.get_position(position_id)
        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Get user (via API or DB)
        telegram_user_id = query.from_user.id
        user_data = await get_user_data(telegram_user_id)
        if not user_data or user_data.get('id') != position.user_id:
            await query.edit_message_text("❌ Unauthorized")
            return

        # Get market for price formatting
        market = await get_market_data(position.market_id, context)

        # Calculate sell amount - CRITICAL: Use WebSocket price from market
        current_price = _get_current_websocket_price(market, position.outcome, position)
        position_value = current_price * position.amount
        sell_amount = position_value * (percentage / 100.0)
        current_price_formatted = format_price_with_precision(current_price, market)

        # Store in context
        context.user_data['pending_sell'] = {
            'position_id': position_id,
            'sell_amount': sell_amount,
            'percentage': percentage,
            'market': market
        }

        # Show confirmation
        message = f"💰 **Confirm Sell**\n\n"
        message += f"Amount: ${sell_amount:.2f} ({percentage}%)\n"
        message += f"Current Price: {current_price_formatted}\n"
        message += f"Estimated Tokens: {int(sell_amount / current_price) if current_price > 0 else 0}\n\n"
        message += "Proceed with sell?"

        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_sell_{position_id}_{percentage}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"position_{position_id}")
            ]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling sell amount: {e}")
        await query.edit_message_text("❌ Error processing sell amount")


async def handle_sell_custom(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle custom sell amount callback - prompt for amount"""
    try:
        # Parse: "sell_custom_{position_id}"
        position_id = int(callback_data.split("_")[-1])
        telegram_user_id = query.from_user.id
        logger.info(f"✏️ Sell Custom Amount opened - Position {position_id} by user {telegram_user_id}")

        # Get position to show current value
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, telegram_user_id)
        else:
            position = await position_service.get_position(position_id)

        if position:
            # Get market for price formatting
            market = await get_market_data(position.market_id, context)
            # CRITICAL: Use WebSocket price from market
            current_price = _get_current_websocket_price(market, position.outcome, position)
            position_value = current_price * position.amount
            current_price_formatted = format_price_with_precision(current_price, market)

            # Store in context
            context.user_data['awaiting_sell_amount'] = True
            context.user_data['custom_sell_position_id'] = position_id

            await query.edit_message_text(
                f"💰 **Custom Sell Amount**\n\n"
                f"Position Value: ${position_value:.2f}\n"
                f"Current Price: {current_price_formatted}\n\n"
                f"Please enter the USD amount you want to sell:\n\n"
                f"Example: 25.50",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ Position not found")

    except Exception as e:
        logger.error(f"Error handling custom sell: {e}")
        await query.edit_message_text("❌ Error processing custom sell")


async def handle_custom_sell_amount_input(update, context: ContextTypes.DEFAULT_TYPE, amount_text: str) -> None:
    """Handle custom sell amount input from text message"""
    try:
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        user_id = update.effective_user.id

        # Get context data
        position_id = context.user_data.get('custom_sell_position_id')

        if not position_id:
            context.user_data.pop('awaiting_sell_amount', None)
            await update.message.reply_text("❌ Session expired. Please start over.")
            return

        # Parse amount
        try:
            clean_text = amount_text.replace('$', '').replace(',', '').strip()
            sell_amount = float(clean_text)

            if sell_amount <= 0:
                await update.message.reply_text("❌ Amount must be greater than 0. Try again or /cancel")
                return

            if sell_amount > 100000:  # Reasonable upper limit
                await update.message.reply_text("❌ Amount too large. Maximum $100,000 per order. Try again or /cancel")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a number (e.g., 25.50)")
            return

        # Get position
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, user_id)
        else:
            position = await position_service.get_position(position_id)

        if not position:
            context.user_data.pop('awaiting_sell_amount', None)
            context.user_data.pop('custom_sell_position_id', None)
            await update.message.reply_text("❌ Position not found")
            return

        # Get user (via API or DB)
        user_data = await get_user_data(user_id)
        if not user_data or user_data.get('id') != position.user_id:
            context.user_data.pop('awaiting_sell_amount', None)
            context.user_data.pop('custom_sell_position_id', None)
            await update.message.reply_text("❌ Unauthorized")
            return

        # Get market
        market = await get_market_data(position.market_id, context)
        if not market:
            context.user_data.pop('awaiting_sell_amount', None)
            context.user_data.pop('custom_sell_position_id', None)
            await update.message.reply_text("❌ Market not found")
            return

        # Get market for price formatting
        market = await get_market_data(position.market_id, context)

        # Calculate percentage - CRITICAL: Use WebSocket price from market
        current_price = _get_current_websocket_price(market, position.outcome, position)
        position_value = current_price * position.amount
        percentage = int((sell_amount / position_value) * 100) if position_value > 0 else 0
        current_price_formatted = format_price_with_precision(current_price, market)

        # Clear flags
        context.user_data.pop('awaiting_sell_amount', None)
        context.user_data.pop('custom_sell_position_id', None)

        # Show confirmation
        message = f"💰 **Confirm Sell**\n\n"
        message += f"Amount: ${sell_amount:.2f} ({percentage}%)\n"
        message += f"Current Price: {current_price_formatted}\n"
        message += f"Estimated Tokens: {int(sell_amount / current_price) if current_price > 0 else 0}\n\n"
        message += "Proceed with sell?"

        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_sell_{position_id}_{percentage}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"position_{position_id}")
            ]
        ]

        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling custom sell amount input: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await update.message.reply_text("❌ Error processing sell amount")


async def handle_confirm_sell(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle sell confirmation - execute sell order"""
    try:
        # Parse: "confirm_sell_{position_id}_{percentage}"
        telegram_user_id = query.from_user.id
        logger.info(f"✅ Confirm Sell clicked - Callback: {callback_data} by user {telegram_user_id}")
        parts = callback_data.split("_")
        position_id = int(parts[2])
        percentage = int(parts[3])

        await query.answer("⚡ Executing sell order...")

        # Show loading message to user - this will remain until the entire operation is complete
        executing_message = await query.edit_message_text(
            "⚡ **Executing sell order...**\n\n"
            "Please wait while your order is being processed.\n"
            "This may take a few seconds.",
            parse_mode='Markdown'
        )

        # Get position (via API or DB)
        telegram_user_id = query.from_user.id
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, telegram_user_id)
        else:
            position = await position_service.get_position(position_id)
        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Check if position is already closed
        if hasattr(position, 'status') and position.status == 'closed':
            await query.edit_message_text(
                "❌ **Position Already Closed**\n\n"
                "This position has already been closed and cannot be sold.\n\n"
                "Use /positions to view your active positions.",
                parse_mode='Markdown'
            )
            return

        # Get user (via API or DB)
        telegram_user_id = query.from_user.id
        user_data = await get_user_data(telegram_user_id)
        if not user_data or user_data.get('id') != position.user_id:
            await query.edit_message_text("❌ Unauthorized")
            return

        # Get market (via API or DB)
        market = await get_market_data(position.market_id, context)

        if not market:
            await query.edit_message_text("❌ Market not found")
            return

        # Calculate sell amount
        # CRITICAL: For SELL orders, amount must be in TOKENS, not USD
        # BUY: amount = USD to spend → returns tokens received
        # SELL: amount = tokens to sell → returns USD received
        # CRITICAL: Use WebSocket price from market for accurate calculations
        current_price = _get_current_websocket_price(market, position.outcome, position)
        position_value = current_price * position.amount  # For display only
        tokens_to_sell = position.amount * (percentage / 100.0)  # Number of tokens to sell

        # Get token ID - Parse JSON string from DB
        import json
        clob_token_ids_raw = market.get('clob_token_ids', '[]')
        outcomes = market.get('outcomes', ['YES', 'NO'])

        logger.info(f"🔍 DEBUG - Market data: outcomes={outcomes}, position.outcome={position.outcome}")
        logger.info(f"🔍 DEBUG - clob_token_ids_raw: {clob_token_ids_raw}")

        try:
            # Parse JSON string to list - DOUBLE PARSING needed because data is double-encoded in DB
            clob_token_ids = json.loads(clob_token_ids_raw) if isinstance(clob_token_ids_raw, str) else clob_token_ids_raw
            # If it's still a string after first parse, parse again (double encoding issue)
            if isinstance(clob_token_ids, str):
                clob_token_ids = json.loads(clob_token_ids)
            logger.info(f"🔍 DEBUG - Final parsed clob_token_ids: {clob_token_ids} (type: {type(clob_token_ids)})")

            # Find outcome index using intelligent normalization
            outcome_index = find_outcome_index(position.outcome, outcomes)
            if outcome_index is None:
                logger.error(
                    f"❌ CRITICAL: Could not find outcome index for position {position.id}: "
                    f"outcome='{position.outcome}', market outcomes={outcomes}, "
                    f"market_id={position.market_id}, clob_token_ids={clob_token_ids}"
                )
                logger.error(
                    f"❌ This will prevent the sell order from executing. "
                    f"Position outcome may need normalization or market data may be corrupted."
                )
                token_id = None
            else:
                logger.info(f"✅ Found outcome index: {outcome_index} for outcome '{position.outcome}' in market {position.market_id}")
                if outcome_index >= len(clob_token_ids):
                    logger.error(
                        f"❌ CRITICAL: Outcome index {outcome_index} out of range for clob_token_ids "
                        f"(length: {len(clob_token_ids)}). Market: {position.market_id}, outcomes: {outcomes}"
                    )
                    token_id = None
                else:
                    token_id = clob_token_ids[outcome_index]
                    logger.info(f"✅ Resolved token_id: {token_id} for position {position.id}")

        except (IndexError, ValueError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"Error parsing token IDs: {e}, raw: {clob_token_ids_raw}")
            token_id = None

        if not token_id:
            logger.error(f"❌ No token_id found - position: {position.id}, outcome: {position.outcome}")
            await query.edit_message_text("❌ Token ID not found")
            return

        # Execute sell order - Use MARKET order for best market price
        # Market orders execute at the best available price immediately
        clob_service = get_clob_service()

        # Create client for user
        client = await clob_service.create_user_client(telegram_user_id)
        if not client:
            await query.edit_message_text(
                "❌ **Sell Order Failed**\n\n"
                "Cannot create trading client. Please check your wallet setup.",
                parse_mode='Markdown'
            )
            return

        # Execute market order - pass market_id and outcome for proper price calculation fallback
        # CRITICAL: For SELL, amount must be tokens, not USD
        # Keep "Executing..." message displayed during order execution
        result = await clob_service.place_market_order(
            client=client,
            token_id=token_id,
            side="SELL",
            amount=tokens_to_sell,  # Number of tokens to sell (not USD!)
            order_type="FAK",  # Fill-And-Kill for instant execution
            market_id=position.market_id,
            outcome=position.outcome
        )

        if result and result.get('success'):
            # Order executed successfully - keep "Executing..." message during sync and update
            # Get execution price from result (or use current_price as fallback)
            execution_price = result.get('price') or current_price

            # Sync positions from blockchain first to get accurate amounts
            # Message still shows "Executing..." during this step
            if SKIP_DB:
                api_client = get_api_client()
                logger.info(f"🔄 Syncing positions after sell for position {position_id}, user {user_data.get('id')}")
                sync_result = await api_client.sync_positions(user_data.get('id'))
                logger.info(f"✅ Synced positions after sell: {sync_result}")

                # Invalidate positions cache to force refresh
                await api_client.cache_manager.invalidate_pattern(f"api:positions:{user_data.get('id')}")
                logger.info(f"🗑️ Invalidated positions cache for user {user_data.get('id')}")

                # Invalidate wallet balance cache (balance changed after sell)
                await api_client.cache_manager.invalidate_pattern(f"api:wallet:{user_data.get('id')}")
                logger.info(f"🗑️ Invalidated wallet cache for user {user_data.get('id')}")
            else:
                await position_service.sync_positions_from_blockchain(
                    user_id=user_data.get('id'),
                    wallet_address=user_data.get('polygon_address')
                )
                logger.info(f"Synced positions after sell for position {position_id}")

            # Update position (close if 100%, reduce amount if partial)
            if SKIP_DB:
                # Use API client for updates
                api_client = get_api_client()
                if percentage >= 100:
                    # Close position via API
                    logger.info(f"🔒 Closing position {position_id} (100% sell)")
                    updated_position = await api_client.update_position(
                        position_id=position_id,
                        status="closed",
                        current_price=execution_price
                    )
                    if updated_position:
                        logger.info(f"✅ Position {position_id} closed successfully")
                    else:
                        logger.warning(f"❌ Failed to close position {position_id} via API after sell")
                else:
                    # Partial sell - update amount via API
                    remaining_amount = position.amount * (1 - percentage / 100.0)
                    logger.info(f"📉 Updating position {position_id}: remaining_amount={remaining_amount:.2f}")
                    updated_position = await api_client.update_position(
                        position_id=position_id,
                        amount=remaining_amount,
                        current_price=execution_price
                    )
                    if updated_position:
                        logger.info(f"✅ Position {position_id} updated successfully")
                    else:
                        logger.warning(f"❌ Failed to update position {position_id} via API after partial sell")
            else:
                # Direct DB access
                if percentage >= 100:
                    # Close position
                    await position_service.close_position(position_id, exit_price=execution_price)
                else:
                    # Partial sell - update amount
                    remaining_amount = position.amount * (1 - percentage / 100.0)
                    # Recalculate P&L with new amount
                    updated_position = await position_service.update_position(
                        position_id=position_id,
                        amount=remaining_amount,
                        current_price=execution_price
                    )
                    if not updated_position:
                        logger.warning(f"Failed to update position {position_id} after partial sell")

            # All operations complete - NOW update message with success result
            # Success message - use actual values from order execution
            tokens_sold = result.get('tokens', tokens_to_sell)  # Actual shares sold from order response
            usd_received = result.get('usd_received', 0)  # USD received from sell order
            message = f"✅ **Sell Order Executed!**\n\n"
            message += f"Market: {market.get('title', 'Unknown')[:60]}...\n"
            message += f"Tokens Sold: {tokens_sold:.4f} ({percentage}%)\n"
            message += f"USD Received: ${usd_received:.2f}\n"
            message += f"Order ID: {result.get('order_id', 'N/A')}\n\n"
            message += f"View updated position with /positions"

            keyboard = [
                [InlineKeyboardButton("📈 View Portfolio", callback_data="refresh_positions")],
                [InlineKeyboardButton("← Back", callback_data=f"position_{position_id}")]
            ]

            # Final message update - only after everything is complete
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                f"❌ **Sell Order Failed**\n\n"
                f"Error: {result.get('error', 'Unknown error') if result else 'Order execution failed'}\n\n"
                f"Please try again or check your balance.",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error confirming sell: {e}")
        await query.edit_message_text("❌ Error executing sell order")
