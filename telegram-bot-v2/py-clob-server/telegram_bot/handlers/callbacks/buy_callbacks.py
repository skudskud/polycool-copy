#!/usr/bin/env python3
"""
Buy Callbacks
Handles buy order confirmation, quick buy, and related callbacks
"""

import asyncio
import logging
import os
import sys
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TimedOut, NetworkError

logger = logging.getLogger(__name__)


async def _safe_edit_text(message, text, reply_markup=None, parse_mode=None, max_attempts=3):
    """
    Safely edit a Telegram message with timeout resilience.
    Falls back to reply_text if edit_text fails after max_attempts.

    Args:
        message: Telegram message object
        text: New message text
        reply_markup: Keyboard markup
        parse_mode: Parse mode (HTML, Markdown, etc)
        max_attempts: Max retry attempts

    Returns:
        True if update successful, False otherwise
    """
    for attempt in range(max_attempts):
        try:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return True  # Success
        except (TimedOut, NetworkError) as e:
            logger.warning(f"⏱️ Telegram timeout on edit attempt {attempt+1}: {e}")
            if attempt < max_attempts - 1:
                # Retry with exponential backoff
                wait_time = (attempt + 1) * 0.5
                await asyncio.sleep(wait_time)
            else:
                # Final attempt: send new message instead
                logger.warning(f"❌ Max edit attempts reached. Sending new message.")
                try:
                    await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                    return True
                except Exception as err:
                    logger.error(f"❌ Fallback message failed: {err}")
                    return False
        except Exception as e:
            logger.error(f"❌ Unexpected error editing message: {e}")
            return False

    return False


async def handle_quick_buy_callback(query, callback_data, session_manager, trading_service):
    """
    Handle quick buy callbacks for preset amounts ($5, $10, $20)
    Shows confirmation screen like the normal flow
    """
    try:
        user_id = query.from_user.id
        logger.info(f"🔵 [QUICK_BUY] START: user_id={user_id}, callback={callback_data}")

        session = session_manager.get(user_id)

        # Parse amount from callback (e.g., "quick_buy_5" -> 5)
        amount = float(callback_data.replace("quick_buy_", ""))
        logger.info(f"💰 [QUICK_BUY] Amount: ${amount}")

        # Get pending order from session
        pending_order = session.get('pending_order')
        if not pending_order:
            logger.error(f"❌ [QUICK_BUY] No pending_order in session")
            await _safe_edit_text(query.message, "❌ Session expired. Please start over.")
            return

        market = session.get('current_market')
        if not market:
            logger.error(f"❌ [QUICK_BUY] No current_market in session")
            await _safe_edit_text(query.message, "❌ Market data lost. Please start over.")
            return

        side = pending_order['side']
        price = pending_order['price']
        return_page = pending_order.get('return_page', 0)
        market_id = pending_order['market_id']

        logger.info(f"📊 [QUICK_BUY] Order: side={side}, price=${price:.4f}, market_id={market_id}")

        # Calculate estimated shares
        estimated_shares = int(amount / price)
        logger.info(f"📈 [QUICK_BUY] Estimated shares: {estimated_shares}")

        # Build confirmation message
        side_emoji = "✅ YES" if side == "yes" else "❌ NO"
        message_text = f"🎯 Confirm Your Order\n\n"
        message_text += f"Market: {market['question'][:60]}...\n"
        message_text += f"Side: {side_emoji}\n"
        message_text += f"Amount: ${amount:.2f}\n"
        message_text += f"Price: {price*100:.0f}¢ per share\n"
        message_text += f"Shares: {estimated_shares}\n\n"
        message_text += "Proceed?"

        # Build keyboard
        keyboard = [
            [
                InlineKeyboardButton("✅ YES, Buy!", callback_data=f"confirm_order_{market_id}_{side}_{amount}_{return_page}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"markets_page_{return_page}")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await _safe_edit_text(query.message, message_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in quick_buy callback: {e}")
        await _safe_edit_text(query.message, f"❌ Error: {str(e)}")


async def handle_confirm_order_callback(query, callback_data, session_manager, trading_service):

    """Handle confirming an order (Buy/Sell)"""
    try:
        # LOG IMMÉDIATEMENT - avant tout traitement
        logger.info(f"🔴 [CONFIRM_START] callback_data={callback_data}")

        user_id = query.from_user.id
        session = session_manager.get(user_id)

        # Parse callback: confirm_order_<market_id>_<side>_<amount>_<return_page>
        # OR just "confirm_order" for custom amount flow
        parts = callback_data.split("_", 4)
        logger.info(f"[CONFIRM_ORDER] callback_data={callback_data}, parts={parts}, len(parts)={len(parts)}")

        # If we only have "confirm_order" (custom amount flow), get data from session
        if len(parts) < 5:
            logger.info(f"[CONFIRM_ORDER] Using session data for custom amount (callback: {callback_data})")
            # Try both keys since there's a mismatch between trading_handlers and buy_callbacks
            pending_order = session.get('pending_order') or session.get('pending_confirmation')
            logger.info(f"[CONFIRM_ORDER] pending_order={pending_order}, pending_confirmation={session.get('pending_confirmation')}")
            if not pending_order:
                logger.error(f"[CONFIRM_ORDER] ERROR: Neither pending_order nor pending_confirmation found in session!")
                logger.error(f"[CONFIRM_ORDER] Available session keys: {list(session.keys())}")
                await query.edit_message_text("❌ Session expired. Please start over.")
                return

            market_id = pending_order.get('market_id')
            side = pending_order.get('side')
            amount = pending_order.get('amount')  # Get from pending_order, not session.get('custom_amount')
            return_page = pending_order.get('return_page', 0)
            logger.info(f"[CONFIRM_ORDER] Custom flow: market_id={market_id}, side={side}, amount={amount}, return_page={return_page}")
        else:
            # Standard flow with all params in callback
            # Also get pending_order from session for source tracking
            pending_order = session.get('pending_order', {})
            market_id = parts[2]
            side = parts[3]
            # Safely parse parts[4] which contains "amount_returnpage"
            last_part_split = parts[4].rsplit("_", 1)
            if len(last_part_split) < 2:
                logger.error(f"[CONFIRM_ORDER] ERROR: parts[4] doesn't contain underscore: {parts[4]}")
                await query.edit_message_text("❌ Invalid order format. Please try again.")
                return
            amount = float(last_part_split[0])
            return_page = int(last_part_split[1])
            logger.info(f"[CONFIRM_ORDER] Standard flow: market_id={market_id}, side={side}, amount={amount}, return_page={return_page}")

        market = session.get('current_market')
        logger.info(f"[CONFIRM_ORDER] market={market}")

        if not market:
            await query.edit_message_text("❌ Market data expired. Please try again.")
            return

        # IMPORTANT: For smart_trading source, market_id is condition_id (0x...)
        # For /markets source, market_id is numeric id (648228)
        # We need to check BOTH to support both flows
        source = pending_order.get('source', 'markets')

        if source == 'smart_trading':
            # Smart trading uses condition_id - no validation needed (already validated in handler)
            logger.info(f"[CONFIRM_ORDER] Smart trading flow - skipping market_id check")
        else:
            # Regular /markets flow - validate market_id matches
            if market['id'] != market_id:
                await query.edit_message_text("❌ Market data expired. Please try again.")
                return

        # ✅ CRITICAL: Answer callback IMMEDIATELY to avoid Telegram timeout
        # Telegram requires callback response within 10 seconds
        try:
            await query.answer("⚡ Executing order with your wallet...")
        except Exception as answer_error:
            # Non-critical: User won't see popup but trade will still execute
            logger.debug(f"⚠️ Callback answer failed (non-critical): {answer_error}")

        # Send "executing" message as NEW message (like smart_trading)
        # This prevents timeout errors from being displayed
        executing_msg = await query.message.reply_text(
            "⚡ *Executing order...*\n\n🔄 Please wait while your trade is being processed.",
            parse_mode='Markdown'
        )

        # Execute trade (using trading_service)
        # Signature: execute_buy(query, market_id, outcome, amount, market)
        logger.info(f"[CONFIRM_ORDER] About to call execute_buy with: market_id={market_id}, side={side}, amount={amount}")
        result = await trading_service.execute_buy(query, market_id, side, amount, market)
        logger.info(f"[CONFIRM_ORDER] execute_buy returned: {result}")

        if result.get('success'):
            order_id = result.get('order_id', 'N/A')

            # Safely calculate shares from result or pending_order
            shares_bought = result.get('shares', None)
            if shares_bought:
                estimated_shares = int(float(shares_bought))
            elif session.get('pending_order') and session['pending_order'].get('price'):
                estimated_shares = int(amount / session['pending_order']['price'])
            else:
                estimated_shares = 0  # Fallback

            side_emoji = "✅ YES" if side == "yes" else "❌ NO"

            # Build success message
            if estimated_shares > 0:
                shares_text = f"📊 Shares: {estimated_shares}"
            else:
                shares_text = f"📊 Shares: Check /positions"

            message_text = f"""
🎉 TRADE SUCCESSFUL!

Market: {market['question'][:60]}...
Position: {side_emoji}
Invested: ${amount:.2f}
{shares_text}

✅ Position added to your portfolio
            """
        else:
            error_msg = result.get('error', 'Unknown error')
            message_text = f"❌ ORDER FAILED\n\n{error_msg}\n\nPlease try again."

        # Clear user state
        session['state'] = None
        session['pending_order'] = None

        # Add back to markets button
        keyboard = [
            [InlineKeyboardButton("📊 Back to Markets", callback_data=f"markets_page_{return_page}")],
            [InlineKeyboardButton("💼 View Positions", callback_data="view_positions")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        # CRITICAL FIX: Update the executing message with timeout resilience
        # Problem: Telegram API can timeout during edit_text (httpx.WriteTimeout)
        # Solution: Retry logic + fallback to send_message if needed
        max_edit_attempts = 3
        for attempt in range(max_edit_attempts):
            try:
                logger.info(f"[CONFIRM_ORDER] Attempting to edit message (attempt {attempt+1}/{max_edit_attempts})")
                await executing_msg.edit_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
                logger.info(f"[CONFIRM_ORDER] ✅ Message updated successfully")
                break  # Success, exit retry loop
            except (TimedOut, NetworkError) as e:
                logger.warning(f"[CONFIRM_ORDER] ⏱️ Telegram timeout/network error on edit attempt {attempt+1}: {e}")
                if attempt < max_edit_attempts - 1:
                    # Retry with exponential backoff
                    wait_time = (attempt + 1) * 0.5  # 0.5s, 1s, etc
                    logger.info(f"[CONFIRM_ORDER] Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    # Final attempt failed: send new message instead
                    logger.warning(f"[CONFIRM_ORDER] ❌ Max edit attempts reached. Sending new message instead.")
                    try:
                        await query.message.reply_text(
                            message_text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                        logger.info(f"[CONFIRM_ORDER] ✅ Sent fallback message via reply_text")
                    except Exception as fallback_err:
                        logger.error(f"[CONFIRM_ORDER] ❌ Fallback message also failed: {fallback_err}")
                        # Trade succeeded anyway, just can't update UI
            except Exception as edit_err:
                logger.error(f"[CONFIRM_ORDER] ❌ Unexpected error editing message: {edit_err}")
                # Try fallback once
                try:
                    await query.message.reply_text(
                        message_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                    logger.info(f"[CONFIRM_ORDER] ✅ Sent fallback message after error")
                except:
                    logger.error(f"[CONFIRM_ORDER] ❌ Fallback also failed, but trade succeeded")
                break

        # PHASE 3: Smart refresh positions immediately after successful buy (non-blocking)
        if result.get('success'):
            try:
                from core.services import user_service
                wallet = user_service.get_user_wallet(query.from_user.id)
                if wallet:
                    # Force refresh positions immediately via background task
                    asyncio.create_task(
                        trading_service._force_refresh_positions_after_trade(
                            user_id=query.from_user.id,
                            wallet_address=wallet['address']
                        )
                    )
                    logger.info(f"🔄 Smart refresh started for user {query.from_user.id} after successful buy")
            except Exception as e:
                logger.warning(f"⚠️ Smart refresh setup failed: {e}")

    except IndexError as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"❌ IndexError in confirm_order: {e}")
        logger.error(f"Line info: {tb}")
        # Also print to console for visibility
        print(f"[ERROR] IndexError: {e}")
        print(f"[TRACEBACK]\n{tb}")
        await query.message.reply_text(f"❌ Data structure error: {str(e)}")
    except Exception as e:
        import traceback
        logger.error(f"Error in confirm_order callback: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        await query.message.reply_text(f"❌ Error executing order: {str(e)}")


async def handle_custom_buy_callback(query, session_manager):
    """Handle custom buy amount input (shows text input prompt)"""
    try:
        user_id = query.from_user.id
        session = session_manager.get(user_id)

        # Store that we're waiting for amount input
        session['state'] = 'awaiting_amount'
        session['action'] = 'custom_buy'

        # Send prompt for amount
        message = (
            "💰 Enter USD amount to buy:\n\n"
            "💡 Examples: 2, 5, 10, 20\n"
            "_Minimum: $0.25_"
        )

        await _safe_edit_text(query.message, message, parse_mode='Markdown')
        logger.info(f"📝 User {user_id} entering custom amount for buy")

    except Exception as e:
        logger.error(f"Error in custom_buy callback: {e}")
        await _safe_edit_text(query.message, f"❌ Error: {str(e)}")
