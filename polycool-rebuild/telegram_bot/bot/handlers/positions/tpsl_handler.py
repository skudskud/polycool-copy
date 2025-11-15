"""
Positions TP/SL Handler
Handles Take Profit and Stop Loss setup and management
"""
import os
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.database.connection import get_db
from core.services.user.user_helper import get_user_data
from core.services.user.user_service import user_service
from core.services.position.position_service import position_service
from core.services.market.market_helper import get_market_data
from telegram_bot.bot.handlers.positions.view_builder import format_price_with_precision
from telegram_bot.api.v1.positions import _extract_price_from_market
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_tpsl_setup(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle TP/SL setup callback - show setup interface"""
    try:
        # Parse: "tpsl_setup_{position_id}"
        position_id = int(callback_data.split("_")[-1])

        # Get position (via API or DB)
        telegram_user_id = query.from_user.id
        logger.info(f"🎯 TP/SL Setup opened - Position {position_id} by user {telegram_user_id}")
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

        # Get market (via API or DB)
        market = await get_market_data(position.market_id, context)

        # ✅ CRITICAL: Get current_price from market data (WebSocket prices) instead of position.current_price
        # This ensures consistency with the positions flow and real-time WebSocket updates
        current_price = None
        if market:
            current_price = _extract_price_from_market(market, position.outcome)
            logger.debug(f"🎯 TP/SL setup - Market price for {position.outcome}: {current_price}")

        # Fallback to position's stored current_price or entry_price if market price unavailable
        if current_price is None:
            current_price = position.current_price or position.entry_price
            logger.debug(f"⚠️ TP/SL setup - Using fallback price: {current_price} (market price unavailable)")

        # Build TP/SL setup interface
        current_price_formatted = format_price_with_precision(current_price, market)
        message = f"🎯 **Take Profit / Stop Loss**\n\n"
        message += f"Market: {market.get('title', 'Unknown')[:60]}...\n"
        message += f"Outcome: {position.outcome}\n"
        message += f"Current Price: {current_price_formatted}\n\n"

        if position.take_profit_price:
            tp_price_formatted = format_price_with_precision(position.take_profit_price, market)
            message += f"✅ Take Profit: {tp_price_formatted}\n"
        else:
            message += f"⏸️ Take Profit: Not set\n"

        if position.stop_loss_price:
            sl_price_formatted = format_price_with_precision(position.stop_loss_price, market)
            message += f"🛑 Stop Loss: {sl_price_formatted}\n"
        else:
            message += f"⏸️ Stop Loss: Not set\n"

        message += "\nSelect action:"

        keyboard = [
            [
                InlineKeyboardButton("🎯 Set TP", callback_data=f"tpsl_set_tp_{position_id}"),
                InlineKeyboardButton("🛑 Set SL", callback_data=f"tpsl_set_sl_{position_id}")
            ],
            [
                InlineKeyboardButton("❌ Clear TP", callback_data=f"tpsl_clear_tp_{position_id}"),
                InlineKeyboardButton("❌ Clear SL", callback_data=f"tpsl_clear_sl_{position_id}")
            ],
            [InlineKeyboardButton("← Back", callback_data=f"position_{position_id}")]
        ]

        # Truncate message if too long (Telegram limit is 4096 characters)
        MAX_MESSAGE_LENGTH = 4096
        if len(message) > MAX_MESSAGE_LENGTH:
            logger.warning(f"⚠️ TP/SL setup message too long ({len(message)} chars), truncating")
            message = message[:MAX_MESSAGE_LENGTH - 50] + "\n\n⚠️ Message truncated..."

        try:
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as edit_error:
            error_str = str(edit_error)
            if "Message is not modified" in error_str:
                logger.debug("TP/SL setup data unchanged, skipping message update")
                await query.answer("✅ Data is up to date")
                return
            elif "Bad Request" in error_str or "400" in error_str:
                logger.error(f"❌ HTTP 400 error editing TP/SL setup message: {edit_error}")
                logger.debug(f"Message length: {len(message)}, Keyboard buttons: {len(keyboard)}")
                # Try to send a simpler message
                try:
                    await query.edit_message_text(
                        f"🎯 **Take Profit / Stop Loss**\n\n"
                        f"Position: {position_id}\n\n"
                        f"⚠️ Use /positions for full details",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except Exception as e2:
                    logger.error(f"❌ Failed to send fallback TP/SL message: {e2}")
                    await query.answer("⚠️ Error updating message")
            else:
                raise

    except Exception as e:
        logger.error(f"Error handling TP/SL setup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await query.edit_message_text("❌ Error processing TP/SL setup")
        except:
            await query.answer("❌ Error processing TP/SL setup")


async def handle_tpsl_set_price(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle TP/SL set price callback - show percentage buttons"""
    try:
        # Parse: "tpsl_set_tp_{position_id}" or "tpsl_set_sl_{position_id}"
        parts = callback_data.split("_")
        tpsl_type = parts[2]  # "tp" or "sl"
        telegram_user_id = query.from_user.id
        position_id = int(parts[-1])
        logger.info(f"🎯 TP/SL Set Price opened - Position {position_id}, Type: {tpsl_type.upper()} by user {telegram_user_id}")

        # Get position (via API or DB)
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

        # Get market for price formatting
        market = await get_market_data(position.market_id, context)

        entry_price = position.entry_price

        # ✅ CRITICAL: Get current_price from market data (WebSocket prices) instead of position.current_price
        # This ensures consistency with the positions flow and real-time WebSocket updates
        current_price = None
        if market:
            current_price = _extract_price_from_market(market, position.outcome)
            logger.debug(f"🎯 TP/SL set price - Market price for {position.outcome}: {current_price}")

        # Fallback to position's stored current_price or entry_price if market price unavailable
        if current_price is None:
            current_price = position.current_price or entry_price
            logger.debug(f"⚠️ TP/SL set price - Using fallback price: {current_price} (market price unavailable)")
        tpsl_name = "Take Profit" if tpsl_type == "tp" else "Stop Loss"

        # Build message with entry price reference
        entry_price_formatted = format_price_with_precision(entry_price, market)
        current_price_formatted = format_price_with_precision(current_price, market)
        message = f"🎯 **Set {tpsl_name}**\n\n"
        message += f"Entry Price: {entry_price_formatted}\n"
        message += f"Current Price: {current_price_formatted}\n\n"

        if tpsl_type == "tp":
            message += "Select target price:\n"
        else:
            message += "Select stop loss price:\n"

        # Calculate percentage-based prices
        if tpsl_type == "tp":
            # Take Profit: positive percentages
            prices = {
                "+10%": min(entry_price * 1.10, 1.0),
                "+25%": min(entry_price * 1.25, 1.0),
                "+50%": min(entry_price * 1.50, 1.0),
                "+75%": min(entry_price * 1.75, 1.0)
            }
        else:
            # Stop Loss: negative percentages
            prices = {
                "-10%": max(entry_price * 0.90, 0.0),
                "-25%": max(entry_price * 0.75, 0.0),
                "-50%": max(entry_price * 0.50, 0.0),
                "-75%": max(entry_price * 0.25, 0.0)
            }

        # Build keyboard with percentage buttons
        keyboard = []
        row = []
        for label, price in prices.items():
            price_formatted = format_price_with_precision(price, market)
            row.append(InlineKeyboardButton(
                f"{label} ({price_formatted})",
                callback_data=f"tpsl_percent_{tpsl_type}_{position_id}_{label.replace('%', '').replace('+', '').replace('-', '')}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Add custom button
        keyboard.append([InlineKeyboardButton(
            "📝 Custom Price",
            callback_data=f"tpsl_custom_{tpsl_type}_{position_id}"
        )])
        keyboard.append([InlineKeyboardButton("← Back", callback_data=f"tpsl_setup_{position_id}")])

        # Truncate message if too long
        MAX_MESSAGE_LENGTH = 4096
        if len(message) > MAX_MESSAGE_LENGTH:
            logger.warning(f"⚠️ TP/SL price message too long ({len(message)} chars), truncating")
            message = message[:MAX_MESSAGE_LENGTH - 50] + "\n\n⚠️ Message truncated..."

        try:
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as edit_error:
            error_str = str(edit_error)
            if "Message is not modified" in error_str:
                logger.debug("TP/SL price data unchanged, skipping message update")
                await query.answer("✅ Data is up to date")
                return
            elif "Bad Request" in error_str or "400" in error_str:
                logger.error(f"❌ HTTP 400 error editing TP/SL price message: {edit_error}")
                logger.debug(f"Message length: {len(message)}, Keyboard buttons: {len(keyboard)}")
                try:
                    await query.edit_message_text(
                        f"🎯 **Set {tpsl_name}**\n\n"
                        f"Position: {position_id}\n\n"
                        f"⚠️ Use /positions for full details",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except Exception as e2:
                    logger.error(f"❌ Failed to send fallback TP/SL price message: {e2}")
                    await query.answer("⚠️ Error updating message")
            else:
                raise

    except Exception as e:
        logger.error(f"Error setting TP/SL price: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await query.edit_message_text("❌ Error setting TP/SL price")
        except:
            await query.answer("❌ Error setting TP/SL price")


async def handle_tpsl_clear(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle TP/SL clear callback - clear TP/SL prices"""
    try:
        # Parse: "tpsl_clear_tp_{position_id}" or "tpsl_clear_sl_{position_id}"
        parts = callback_data.split("_")
        tpsl_type = parts[2]  # "tp" or "sl"
        position_id = int(parts[3])
        telegram_user_id = query.from_user.id
        logger.info(f"🗑️ TP/SL Clear initiated - Position {position_id}, Type: {tpsl_type.upper()} by user {telegram_user_id}")

        # Get position (via API or DB)
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

        # Clear TP/SL (via API or DB)
        if SKIP_DB:
            # Use API client to clear TP/SL (pass price=0 to clear)
            api_client = get_api_client()
            result = await api_client.update_position_tpsl(position_id, tpsl_type, 0.0)
            if not result:
                logger.warning(f"Failed to clear {tpsl_type} via API for position {position_id}")
        else:
            # Direct DB update in non-SKIP_DB mode
            async with get_db() as db:
                if tpsl_type == "tp":
                    position.take_profit_price = None
                    position.take_profit_amount = None
                else:
                    position.stop_loss_price = None
                    position.stop_loss_amount = None

                position.updated_at = datetime.now(timezone.utc)
                await db.commit()

        tpsl_name = "Take Profit" if tpsl_type == "tp" else "Stop Loss"
        await query.answer(f"✅ {tpsl_name} cleared")
        # Refresh TP/SL setup view - wrap in try/except to handle potential 400 errors
        try:
            await handle_tpsl_setup(query, context, f"tpsl_setup_{position_id}")
        except Exception as refresh_error:
            error_str = str(refresh_error)
            if "Bad Request" in error_str or "400" in error_str:
                logger.warning(f"HTTP 400 when refreshing TP/SL setup after clear: {refresh_error}")
                # Message already updated by answer callback, so just log
            else:
                raise

    except Exception as e:
        logger.error(f"Error clearing TP/SL: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await query.edit_message_text("❌ Error clearing TP/SL")
        except:
            await query.answer("❌ Error clearing TP/SL")


async def handle_tpsl_percentage(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle TP/SL percentage selection callback"""
    try:
        telegram_user_id = query.from_user.id
        logger.info(f"📊 TP/SL Percentage selected - Callback: {callback_data} by user {telegram_user_id}")

        # Parse: "tpsl_percent_{tp|sl}_{position_id}_{percentage}"
        parts = callback_data.split("_")
        if len(parts) < 5:
            logger.error(f"❌ Invalid TP/SL percentage callback format: {callback_data}")
            await query.answer("❌ Invalid callback data", show_alert=True)
            return

        tpsl_type = parts[2]  # "tp" or "sl"
        position_id = int(parts[3])
        percentage_str = parts[4]  # "10", "25", "50", "75"

        logger.info(f"🔍 Parsed TP/SL: type={tpsl_type}, position_id={position_id}, percentage={percentage_str}")

        # Get position (via API or DB)
        telegram_user_id = query.from_user.id
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, telegram_user_id)
        else:
            position = await position_service.get_position(position_id)
        if not position:
            logger.error(f"❌ Position {position_id} not found for user {telegram_user_id}")
            await query.edit_message_text("❌ Position not found")
            return

        # Get user (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data or user_data.get('id') != position.user_id:
            logger.error(f"❌ Unauthorized: user {telegram_user_id} != position.user_id {position.user_id}")
            await query.edit_message_text("❌ Unauthorized")
            return

        entry_price = position.entry_price
        percentage = float(percentage_str)

        # Calculate target price
        if tpsl_type == "tp":
            # Take Profit: positive percentage
            target_price = min(entry_price * (1 + percentage / 100.0), 1.0)
        else:
            # Stop Loss: negative percentage
            target_price = max(entry_price * (1 - percentage / 100.0), 0.0)

        logger.info(f"🔍 Calculated target price: ${target_price:.4f} (entry=${entry_price:.4f}, {percentage}%)")

        # Save TP/SL
        try:
            logger.info(f"🔍 Saving TP/SL: position_id={position_id}, type={tpsl_type}, price={target_price}")
            await _save_tpsl_price(telegram_user_id, position_id, tpsl_type, target_price, position)
            logger.info(f"✅ TP/SL saved successfully for position {position_id}")

            tpsl_name = "Take Profit" if tpsl_type == "tp" else "Stop Loss"
            await query.answer(f"✅ {tpsl_name} set to ${target_price:.4f}")
            # Show success message with next action options
            await handle_tpsl_success(query, context, position_id, tpsl_type, target_price)
        except ValueError as validation_error:
            # Handle validation errors (e.g., SL >= TP)
            error_msg = str(validation_error)
            logger.warning(f"⚠️ TP/SL validation error: {error_msg}")
            await query.answer(error_msg, show_alert=True)
            try:
                await query.edit_message_text(error_msg, parse_mode='Markdown')
            except:
                pass  # Already answered callback
        except Exception as save_error:
            logger.error(f"❌ Error saving TP/SL: {save_error}")
            import traceback
            logger.error(traceback.format_exc())
            tpsl_name = "Take Profit" if tpsl_type == "tp" else "Stop Loss"
            await query.answer(f"❌ Failed to save {tpsl_name}", show_alert=True)
            try:
                await query.edit_message_text(f"❌ Error saving {tpsl_name}. Please try again.")
            except:
                pass  # Already answered callback

    except Exception as e:
        logger.error(f"❌ Error handling TP/SL percentage: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await query.edit_message_text("❌ Error setting TP/SL")
        except:
            await query.answer("❌ Error setting TP/SL")


async def handle_tpsl_custom(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle TP/SL custom price callback - prompt for custom price input"""
    try:
        # Parse: "tpsl_custom_{tp|sl}_{position_id}"
        parts = callback_data.split("_")
        tpsl_type = parts[2]  # "tp" or "sl"
        position_id = int(parts[3])
        telegram_user_id = query.from_user.id
        logger.info(f"✏️ TP/SL Custom Price input opened - Position {position_id}, Type: {tpsl_type.upper()} by user {telegram_user_id}")

        # Get position (via API or DB)
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

        # Store in context
        context.user_data['awaiting_tpsl_price'] = True
        context.user_data['tpsl_type'] = tpsl_type
        context.user_data['tpsl_position_id'] = position_id

        # Get market for price formatting
        market = await get_market_data(position.market_id, context)

        entry_price = position.entry_price

        # ✅ CRITICAL: Get current_price from market data (WebSocket prices) instead of position.current_price
        # This ensures consistency with the positions flow and real-time WebSocket updates
        current_price = None
        if market:
            current_price = _extract_price_from_market(market, position.outcome)
            logger.debug(f"🎯 TP/SL custom price - Market price for {position.outcome}: {current_price}")

        # Fallback to position's stored current_price or entry_price if market price unavailable
        if current_price is None:
            current_price = position.current_price or entry_price
            logger.debug(f"⚠️ TP/SL custom price - Using fallback price: {current_price} (market price unavailable)")

        tpsl_name = "Take Profit" if tpsl_type == "tp" else "Stop Loss"

        entry_price_formatted = format_price_with_precision(entry_price, market)
        current_price_formatted = format_price_with_precision(current_price, market)

        await query.edit_message_text(
            f"🎯 **Set {tpsl_name} - Custom Price**\n\n"
            f"Entry Price: {entry_price_formatted}\n"
            f"Current Price: {current_price_formatted}\n\n"
            f"Please enter the target price (0.00 - 1.00):",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling TP/SL custom: {e}")
        await query.edit_message_text("❌ Error setting TP/SL custom price")


async def handle_tpsl_price_input(update, context: ContextTypes.DEFAULT_TYPE, price_text: str) -> None:
    """Handle TP/SL price input from text message"""
    try:
        from telegram import Update
        user_id = update.effective_user.id

        # Get context data
        tpsl_type = context.user_data.get('tpsl_type')
        position_id = context.user_data.get('tpsl_position_id')

        if not tpsl_type or not position_id:
            context.user_data.pop('awaiting_tpsl_price', None)
            await update.message.reply_text("❌ Session expired. Please start over.")
            return

        # Parse price
        try:
            clean_text = price_text.replace('$', '').replace(',', '').strip()
            target_price = float(clean_text)

            # Validate price range (0-1 for Polymarket)
            if not (0 <= target_price <= 1):
                await update.message.reply_text("❌ Price must be between 0.00 and 1.00. Try again or /cancel")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid price. Please enter a number (e.g., 0.75)")
            return

        # Clear flag
        context.user_data.pop('awaiting_tpsl_price', None)
        context.user_data.pop('tpsl_type', None)
        context.user_data.pop('tpsl_position_id', None)

        # Get position
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, user_id)
        else:
            position = await position_service.get_position(position_id)

        if not position:
            await update.message.reply_text("❌ Position not found")
            return

        # Save TP/SL
        try:
            await _save_tpsl_price(user_id, position_id, tpsl_type, target_price, position)
        except ValueError as validation_error:
            # Handle validation errors (e.g., SL >= TP)
            error_msg = str(validation_error)
            logger.warning(f"⚠️ TP/SL validation error: {error_msg}")
            await update.message.reply_text(error_msg, parse_mode='Markdown')
            return
        except Exception as e:
            logger.error(f"❌ Error saving TP/SL: {e}")
            await update.message.reply_text("❌ Error saving TP/SL price. Please try again.")
            return

        # Create a fake callback query to use handle_tpsl_success
        class FakeCallbackQuery:
            def __init__(self, update):
                self.from_user = update.effective_user
                self.message = update.message

            async def answer(self, text=None, show_alert=False):
                # For text input, we can't answer a callback, so we do nothing
                pass

            async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                # Send a new message instead of editing
                await self.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

        fake_query = FakeCallbackQuery(update)

        # Use the same success handler as percentage selection
        await handle_tpsl_success(fake_query, context, position_id, tpsl_type, target_price)

    except Exception as e:
        logger.error(f"Error handling TP/SL price input: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await update.message.reply_text("❌ Error saving TP/SL price")


async def _save_tpsl_price(telegram_user_id: int, position_id: int, tpsl_type: str, target_price: float, position) -> None:
    """Helper function to save TP/SL price with validation"""
    try:
        logger.info(f"🔍 _save_tpsl_price called: position_id={position_id}, tpsl_type={tpsl_type}, price={target_price}, SKIP_DB={SKIP_DB}")

        # ✅ NEW: Validate SL < TP if both are set (limit order logic)
        # Get current TP/SL values from position
        current_tp = position.take_profit_price if hasattr(position, 'take_profit_price') else None
        current_sl = position.stop_loss_price if hasattr(position, 'stop_loss_price') else None

        # Determine what the new values will be
        new_tp = target_price if tpsl_type == "tp" else current_tp
        new_sl = target_price if tpsl_type == "sl" else current_sl

        # Validate SL < TP if both are set
        if new_tp is not None and new_sl is not None:
            if new_sl >= new_tp:
                error_msg = (
                    f"❌ Invalid TP/SL configuration: Stop Loss (${new_sl:.4f}) must be < Take Profit (${new_tp:.4f})\n\n"
                    f"Please adjust your prices so that SL < TP."
                )
                logger.warning(f"⚠️ TP/SL validation failed: SL={new_sl:.4f} >= TP={new_tp:.4f}")
                raise ValueError(error_msg)

        if SKIP_DB:
            # Use API client
            api_client = get_api_client()
            logger.info(f"🔍 Calling API client.update_position_tpsl for position {position_id}")
            result = await api_client.update_position_tpsl(
                position_id=position_id,
                tpsl_type=tpsl_type,
                price=target_price
            )
            if result:
                logger.info(f"✅ API returned result: {result}")
            else:
                logger.error(f"❌ API returned None for TP/SL update")
                raise Exception("API returned None for TP/SL update")
        else:
            # Direct DB update
            logger.info(f"🔍 Using position_service.update_position_tpsl for position {position_id}")
            result = await position_service.update_position_tpsl(
                position_id=position_id,
                tpsl_type=tpsl_type,
                price=target_price
            )
            if result:
                logger.info(f"✅ Service returned result: {result}")
            else:
                logger.error(f"❌ Service returned None for TP/SL update")
                raise Exception("Service returned None for TP/SL update")

        logger.info(f"✅ Saved {tpsl_type} price ${target_price:.4f} for position {position_id}")
    except Exception as e:
        logger.error(f"❌ Error saving TP/SL price: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


async def handle_tpsl_success(query, context: ContextTypes.DEFAULT_TYPE, position_id: int, tpsl_type_set: str, price: float) -> None:
    """Handle successful TP/SL setup - show confirmation and next actions"""
    try:
        telegram_user_id = query.from_user.id
        logger.info(f"✅ TP/SL Success - Position {position_id}, Type: {tpsl_type_set.upper()}, Price: ${price:.4f} by user {telegram_user_id}")

        # Get position to get market info for formatting
        if SKIP_DB:
            from telegram_bot.bot.handlers.positions_handler import get_position_helper
            position = await get_position_helper(position_id, telegram_user_id)
        else:
            position = await position_service.get_position(position_id)
        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Get market for price formatting
        market = await get_market_data(position.market_id, context)
        price_formatted = format_price_with_precision(price, market)

        # Determine which TP/SL was just set and which one to offer next
        tpsl_name_set = "Take Profit" if tpsl_type_set == "tp" else "Stop Loss"
        tpsl_type_other = "sl" if tpsl_type_set == "tp" else "tp"
        tpsl_name_other = "Stop Loss" if tpsl_type_set == "tp" else "Take Profit"

        # Check if the other TP/SL is already set
        other_already_set = (position.stop_loss_price if tpsl_type_set == "tp" else position.take_profit_price) is not None

        message = f"✅ **{tpsl_name_set} Set Successfully!**\n\n"
        message += f"🎯 {tpsl_name_set}: {price_formatted}\n"
        message += f"Position: {position.outcome} • {position.amount:.2f} shares\n\n"

        if other_already_set:
            message += f"💡 Both TP and SL are now configured for this position."
        else:
            message += f"💡 Want to set {tpsl_name_other} as well?"

        keyboard = []

        if not other_already_set:
            # Offer to set the other TP/SL
            keyboard.append([
                InlineKeyboardButton(f"🎯 Set {tpsl_name_other}", callback_data=f"tpsl_set_{tpsl_type_other}_{position_id}")
            ])

        # Always offer to go back to positions or view current TP/SL setup
        keyboard.append([
            InlineKeyboardButton("📊 View TP/SL Status", callback_data=f"tpsl_setup_{position_id}"),
            InlineKeyboardButton("← Back to Portfolio", callback_data="refresh_positions")
        ])

        # Truncate message if too long
        MAX_MESSAGE_LENGTH = 4096
        if len(message) > MAX_MESSAGE_LENGTH:
            logger.warning(f"⚠️ TP/SL success message too long ({len(message)} chars), truncating")
            message = message[:MAX_MESSAGE_LENGTH - 50] + "\n\n⚠️ Message truncated..."

        try:
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as edit_error:
            error_str = str(edit_error)
            if "Message is not modified" in error_str:
                logger.debug("TP/SL success data unchanged, skipping message update")
                await query.answer("✅ TP/SL updated successfully")
                return
            elif "Bad Request" in error_str or "400" in error_str:
                logger.error(f"❌ HTTP 400 error editing TP/SL success message: {edit_error}")
                logger.debug(f"Message length: {len(message)}, Keyboard buttons: {len(keyboard)}")
                # Try to send a simpler message
                try:
                    await query.edit_message_text(
                        f"✅ **{tpsl_name_set} Set Successfully!**\n\n"
                        f"🎯 {tpsl_name_set}: {price_formatted}\n\n"
                        f"💡 Use /positions to view your updated position.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except Exception as e2:
                    logger.error(f"❌ Failed to send fallback TP/SL success message: {e2}")
                    await query.answer("✅ TP/SL updated successfully")
            else:
                raise

    except Exception as e:
        logger.error(f"Error handling TP/SL success: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await query.edit_message_text("❌ Error processing TP/SL confirmation")
        except:
            await query.answer("❌ Error processing TP/SL confirmation")
