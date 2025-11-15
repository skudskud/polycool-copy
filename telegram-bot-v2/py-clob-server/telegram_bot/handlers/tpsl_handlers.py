#!/usr/bin/env python3
"""
TP/SL Handlers
Handles Take Profit and Stop Loss user interactions
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from telegram_bot.services.tpsl_service import get_tpsl_service
from telegram_bot.services.transaction_service import get_transaction_service
from core.services import user_service
from .telegram_utils import safe_answer_callback_query

logger = logging.getLogger(__name__)

# Conversation states
AWAITING_TP_PRICE, AWAITING_SL_PRICE, AWAITING_CUSTOM_TP, AWAITING_CUSTOM_SL = range(4)


async def tpsl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /tpsl command - View all active TP/SL orders
    """
    try:
        user_id = update.effective_user.id
        tpsl_service = get_tpsl_service()

        # Get all active TP/SL orders for user
        active_orders = tpsl_service.get_active_tpsl_orders(user_id=user_id)

        if not active_orders:
            await update.message.reply_text(
                "📭 No Auto-Trading Rules Set\n\n"
                "TP/SL orders automatically sell your positions when they hit target prices.\n\n"
                "Set them up:\n"
                "1. Go to `/positions`\n"
                "2. Select a position\n"
                "3. Tap 'Set TP/SL'\n\n"
                "💡 Smart traders always use TP/SL!",
                parse_mode='Markdown'
            )
            return

        # Build message with all TP/SL orders
        message = f"📊 Active TP/SL Orders ({len(active_orders)})\n\n"

        keyboard = []

        for i, order in enumerate(active_orders, 1):
            market_question = order.market_data.get('question', 'Unknown Market') if order.market_data else 'Unknown Market'
            entry_price = float(order.entry_price)

            # Calculate percentages
            tp_pct = ((float(order.take_profit_price) - entry_price) / entry_price * 100) if order.take_profit_price else None
            sl_pct = ((float(order.stop_loss_price) - entry_price) / entry_price * 100) if order.stop_loss_price else None

            message += f"{i}️⃣ {market_question[:40]}...\n"
            message += f"Position: {order.outcome.upper()} ({float(order.monitored_tokens):.0f} tokens)\n"
            message += f"Entry: ${entry_price:.4f}\n"

            # PHASE 9: Show entry transaction if available
            if order.entry_transaction_id:
                message += f"📋 Entry: Transaction #{order.entry_transaction_id}\n"

            if order.take_profit_price:
                message += f"🎯 TP: ${float(order.take_profit_price):.4f} ({tp_pct:+.1f}%)\n"
            else:
                message += f"🎯 TP: Not set\n"

            if order.stop_loss_price:
                message += f"🛑 SL: ${float(order.stop_loss_price):.4f} ({sl_pct:+.1f}%)\n"
            else:
                message += f"🛑 SL: Not set\n"

            message += "\n"

            # Add buttons for each order
            keyboard.append([
                InlineKeyboardButton(
                    f"📝 Edit #{i}",
                    callback_data=f"edit_tpsl_by_id:{order.id}"
                ),
                InlineKeyboardButton(
                    f"❌ Cancel #{i}",
                    callback_data=f"cancel_tpsl:{order.id}"
                )
            ])

        message += "💡 Monitor checks every 10 seconds\n"
        message += "🔔 You'll receive instant notification when triggered"

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ /tpsl command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def set_tpsl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle 'set_tpsl' callback from /positions command
    Shows TP/SL configuration screen
    Uses position INDEX instead of full token ID (fixes 64-byte Telegram limit)
    """
    try:
        query = update.callback_query
        # Note: Callback already answered by button_callback() - no need to answer again

        user_id = query.from_user.id

        # Parse callback data: set_tpsl:{position_index}
        callback_data = query.data
        parts = callback_data.split(':')

        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        position_index = int(parts[1])

        # Get position data from session mapping (NEW!)
        from telegram_bot.session_manager import session_manager
        position_data = session_manager.get_position_mapping(user_id, position_index)

        if not position_data:
            await query.edit_message_text("❌ Position mapping not found. Please refresh /positions and try again.")
            return

        token_id = position_data['token_id']
        market_id = position_data['market_id']
        outcome = position_data['outcome']

        # Get position details from API
        wallet = user_service.get_user_wallet(user_id)
        if not wallet:
            await query.edit_message_text("❌ Wallet not found")
            return

        wallet_address = wallet['address']

        # Fetch positions from blockchain
        import requests
        url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
        # CRITICAL FIX: Use async aiohttp instead of sync requests
        from core.utils.aiohttp_client import get_http_client
        import aiohttp
        session = await get_http_client()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            positions_data = await response.json()

        # Find the specific position
        position = None
        for pos in positions_data:
            if pos.get('asset') == token_id:
                position = pos
                break

        if not position:
            await query.edit_message_text("❌ Position not found on blockchain")
            return

        # Extract position details
        entry_price = float(position.get('avgPrice', 0))
        tokens = float(position.get('size', 0))
        market_title = position.get('title', 'Unknown Market')[:40]

        # Fetch current price to show user if it differs from entry
        from telegram_bot.services.market_service import market_service
        current_price = market_service.get_token_price(token_id, market_id)

        # Store position info in context for next steps (compatible with existing handlers)
        context.user_data['tpsl_setup'] = {
            'token_id': token_id,
            'market_id': market_id,
            'outcome': outcome,
            'position_index': position_index,
            'current_price': current_price,  # NEW: Store for warning checks
            'position': {
                'token_id': token_id,
                'tokens': tokens,
                'buy_price': entry_price,
                'market': {
                    'id': market_id,
                    'question': market_title
                }
            }
        }

        # Build price comparison message
        price_info = f"💰 Entry Price: ${entry_price:.4f}\n"
        if current_price and current_price != entry_price:
            price_change_pct = ((current_price - entry_price) / entry_price) * 100
            emoji = "📈" if price_change_pct > 0 else "📉"
            warning_emoji = " ⚠️" if abs(price_change_pct) > 10 else ""
            price_info += f"💵 Current Price: ${current_price:.4f} ({price_change_pct:+.1f}%){warning_emoji}\n"

        # Show TP/SL setup screen
        message = f"""
🎯 Set Auto-Trading Rules
📊 Market: {market_title}...
🎯 Position: {outcome.upper()} ({tokens:.0f} tokens)
{price_info}

What are TP/SL orders?• Take Profit (TP): Auto-sell when price goes UP (lock in gains)
• Stop Loss (SL): Auto-sell when price goes DOWN (limit losses)

Choose what to set:
        """.strip()

        keyboard = [
            [
                InlineKeyboardButton("🎯 Set Take Profit", callback_data=f"setup_tp:{position_index}"),
                InlineKeyboardButton("🛑 Set Stop Loss", callback_data=f"setup_sl:{position_index}")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ set_tpsl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def setup_tp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'setup_tp' callback - show TP price options"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        tpsl_setup = context.user_data.get('tpsl_setup')
        if not tpsl_setup:
            await query.edit_message_text("❌ Session expired. Please start over from /positions")
            return ConversationHandler.END

        position = tpsl_setup['position']
        entry_price = position['buy_price']
        market_question = position['market'].get('question', 'Unknown')[:40]

        # Calculate suggested TP prices
        tp_10 = entry_price * 1.10
        tp_20 = entry_price * 1.20
        tp_30 = entry_price * 1.30

        message = f"""
💰 Set Take Profit Price
📊 Market: {market_question}...
💰 Entry: ${entry_price:.4f}

Select a target or enter custom:
        """.strip()

        keyboard = [
            [
                InlineKeyboardButton(f"+10%: ${tp_10:.2f}", callback_data=f"tp_preset:{tp_10:.4f}"),
                InlineKeyboardButton(f"+20%: ${tp_20:.2f}", callback_data=f"tp_preset:{tp_20:.4f}")
            ],
            [
                InlineKeyboardButton(f"+30%: ${tp_30:.2f}", callback_data=f"tp_preset:{tp_30:.4f}"),
                InlineKeyboardButton("✏️ Custom", callback_data="tp_custom")
            ],
            [InlineKeyboardButton("⏭️ Skip TP", callback_data="setup_sl:skip_tp")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

        return AWAITING_TP_PRICE

    except Exception as e:
        logger.error(f"❌ setup_tp_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def setup_sl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'setup_sl' callback - show SL price options"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        tpsl_setup = context.user_data.get('tpsl_setup')
        if not tpsl_setup:
            await query.edit_message_text("❌ Session expired. Please start over from /positions")
            return ConversationHandler.END

        position = tpsl_setup['position']
        entry_price = position['buy_price']
        market_question = position['market'].get('question', 'Unknown')[:40]

        # Calculate suggested SL prices
        sl_10 = entry_price * 0.90
        sl_15 = entry_price * 0.85
        sl_25 = entry_price * 0.75

        message = f"""
🛑 Set Stop Loss Price
📊 Market: {market_question}...
💰 Entry: ${entry_price:.4f}

Select a target or enter custom:
        """.strip()

        keyboard = [
            [
                InlineKeyboardButton(f"-10%: ${sl_10:.2f}", callback_data=f"sl_preset:{sl_10:.4f}"),
                InlineKeyboardButton(f"-15%: ${sl_15:.2f}", callback_data=f"sl_preset:{sl_15:.4f}")
            ],
            [
                InlineKeyboardButton(f"-25%: ${sl_25:.2f}", callback_data=f"sl_preset:{sl_25:.4f}"),
                InlineKeyboardButton("✏️ Custom", callback_data="sl_custom")
            ],
            [InlineKeyboardButton("⏭️ Skip SL", callback_data="finalize_tpsl")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

        return AWAITING_SL_PRICE

    except Exception as e:
        logger.error(f"❌ setup_sl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def tp_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle preset TP price selection"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query, text="✅ Take Profit set!")

        # Extract price from callback data
        price_str = query.data.split(':')[1]
        tp_price = float(price_str)

        # Store in context
        if 'tpsl_setup' not in context.user_data:
            await query.edit_message_text("❌ Session expired")
            return ConversationHandler.END

        tpsl_setup = context.user_data['tpsl_setup']
        tpsl_setup['tp_price'] = tp_price

        # Ask if user wants to set SL
        position = tpsl_setup['position']
        entry_price = position['buy_price']
        tp_pct = (tp_price - entry_price) / entry_price * 100

        message = f"""
✅ Take Profit Set!
💰 Entry: ${entry_price:.4f}
🎯 TP: ${tp_price:.4f} (+{tp_pct:.1f}%)

Would you like to set a Stop Loss?
        """.strip()

        keyboard = [
            [InlineKeyboardButton("✅ Yes, set SL", callback_data="setup_sl_after_tp")],
            [InlineKeyboardButton("⏭️ Skip SL (TP only)", callback_data="finalize_tpsl")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

        return AWAITING_SL_PRICE

    except Exception as e:
        logger.error(f"❌ tp_preset_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def sl_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle preset SL price selection"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query, text="✅ Stop Loss set!")

        # Extract price from callback data
        price_str = query.data.split(':')[1]
        sl_price = float(price_str)

        # Store in context
        if 'tpsl_setup' not in context.user_data:
            await query.edit_message_text("❌ Session expired")
            return ConversationHandler.END

        tpsl_setup = context.user_data['tpsl_setup']
        tpsl_setup['sl_price'] = sl_price

        # Check if TP is already set
        tp_price = tpsl_setup.get('tp_price')

        if tp_price:
            # TP already set, finalize
            return await finalize_tpsl(update, context)
        else:
            # TP not set, ask if user wants to set it
            position = tpsl_setup['position']
            entry_price = position['buy_price']
            sl_pct = (sl_price - entry_price) / entry_price * 100

            message = f"""
✅ Stop Loss Set!
💰 Entry: ${entry_price:.4f}
🛑 SL: ${sl_price:.4f} ({sl_pct:+.1f}%)

Would you like to set a Take Profit?
            """.strip()

            keyboard = [
                [InlineKeyboardButton("✅ Yes, set TP", callback_data="setup_tp_after_sl")],
                [InlineKeyboardButton("✅ Done (SL only)", callback_data="finalize_tpsl")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

            return AWAITING_TP_PRICE

    except Exception as e:
        logger.error(f"❌ sl_preset_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def tp_custom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom TP price input request"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        tpsl_setup = context.user_data.get('tpsl_setup')
        if not tpsl_setup:
            await query.edit_message_text("❌ Session expired")
            return ConversationHandler.END

        position = tpsl_setup['position']
        entry_price = position['buy_price']
        market_question = position['market'].get('question', 'Unknown')[:40]

        message = f"""
✏️ Enter Custom Take Profit
📊 Market: {market_question}...
💰 Entry Price: ${entry_price:.4f}

💡 Enter as percentage or price:• `2` or `+2%` → +2% above entry
• `5` or `+5%` → +5% above entry
• `0.15` → absolute price $0.15

📝 Type your target or tap /cancel
        """.strip()

        await query.edit_message_text(message, parse_mode='Markdown')

        # Flag that we're awaiting custom TP input
        context.user_data['tpsl_setup']['awaiting_custom_tp'] = True

        return AWAITING_TP_PRICE

    except Exception as e:
        logger.error(f"❌ tp_custom_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def sl_custom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom SL price input request"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        tpsl_setup = context.user_data.get('tpsl_setup')
        if not tpsl_setup:
            await query.edit_message_text("❌ Session expired")
            return ConversationHandler.END

        position = tpsl_setup['position']
        entry_price = position['buy_price']
        market_question = position['market'].get('question', 'Unknown')[:40]

        message = f"""
✏️ Enter Custom Stop Loss
📊 Market: {market_question}...
💰 Entry Price: ${entry_price:.4f}

💡 Enter as percentage or price:• `-2` or `-2%` → -2% below entry
• `-5` or `-5%` → -5% below entry
• `0.08` → absolute price $0.08

📝 Type your target or tap /cancel
        """.strip()

        await query.edit_message_text(message, parse_mode='Markdown')

        # Flag that we're awaiting custom SL input
        context.user_data['tpsl_setup']['awaiting_custom_sl'] = True

        return AWAITING_SL_PRICE

    except Exception as e:
        logger.error(f"❌ sl_custom_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def setup_sl_after_tp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Yes, set SL' after TP is set in initial setup"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        # Show SL setup screen (same as setup_sl_callback logic)
        return await setup_sl_callback(update, context)

    except Exception as e:
        logger.error(f"❌ setup_sl_after_tp_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def setup_tp_after_sl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Yes, set TP' after SL is set in initial setup"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        # Show TP setup screen (same as setup_tp_callback logic)
        return await setup_tp_callback(update, context)

    except Exception as e:
        logger.error(f"❌ setup_tp_after_sl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def handle_custom_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for custom TP/SL prices (both initial setup and editing)"""
    try:
        tpsl_setup = context.user_data.get('tpsl_setup')

        # Check if this is INITIAL SETUP flow
        if tpsl_setup and (tpsl_setup.get('awaiting_custom_tp') or tpsl_setup.get('awaiting_custom_sl')):
            # === INITIAL SETUP FLOW ===
            pass  # Continue with setup logic below
        # Check if this is EDITING EXISTING flow
        elif 'awaiting_custom_tp' in context.user_data or 'awaiting_custom_sl' in context.user_data:
            # Delegate to edit handler
            await handle_edit_custom_percentage(update, context)
            return
        else:
            # Not in any TP/SL flow - ignore silently
            return

        # === INITIAL SETUP FLOW CONTINUES ===
        position = tpsl_setup['position']
        entry_price = position['buy_price']

        # Parse the price input
        user_input = update.message.text.strip().replace('$', '').replace(' ', '')

        try:
            # Detect if input is a percentage
            is_percentage = False

            # Contains '%' sign
            if '%' in user_input:
                is_percentage = True
                user_input = user_input.replace('%', '')

            # Has '+' or '-' prefix (likely percentage)
            if user_input.startswith('+') or user_input.startswith('-'):
                is_percentage = True

            # Is a simple number between -100 and 100 without many decimal places
            # This catches: 2, 5, 10, -2, etc. as percentages
            # But NOT: 0.1234, 150, etc. (those are prices)
            try:
                num_value = float(user_input.replace('+', ''))
                if -100 <= num_value <= 100 and (not '.' in user_input or len(user_input.split('.')[1]) <= 1):
                    is_percentage = True
            except:
                pass

            if is_percentage:
                # Parse as percentage
                percentage_str = user_input.replace('+', '')
                percentage = float(percentage_str)

                # Calculate absolute price from percentage
                custom_price = entry_price * (1 + percentage / 100)

                await update.message.reply_text(
                    f"📊 {percentage:+.1f}% = ${custom_price:.4f}\n"
                    f"(Entry: ${entry_price:.4f})",
                    parse_mode='Markdown'
                )
            else:
                # Parse as absolute price
                custom_price = float(user_input)
        except ValueError:
            await update.message.reply_text(
                f"❌ Invalid format. Examples:\n"
                f"• Percentage: `2`, `+2`, `2%`, `-2%`\n"
                f"• Price: `0.15`, `0.08`\n\n"
                f"Try again or tap /cancel",
                parse_mode='Markdown'
            )
            return  # Stay in same state

        # Check if it's custom TP or SL
        if tpsl_setup.get('awaiting_custom_tp'):
            # Validate TP price
            if custom_price <= entry_price:
                await update.message.reply_text(
                    f"❌ Take Profit must be HIGHER than entry (${entry_price:.4f})\n\n"
                    f"You entered: ${custom_price:.4f}\n"
                    f"Please try again or tap /cancel",
                    parse_mode='Markdown'
                )
                return  # Stay in same state

            # Store TP price
            context.user_data['tpsl_setup']['tp_price'] = custom_price
            context.user_data['tpsl_setup']['awaiting_custom_tp'] = False

            # Ask if user wants to set SL
            position = tpsl_setup['position']
            entry_price = position['buy_price']
            tp_pct = (custom_price - entry_price) / entry_price * 100

            message = f"""
✅ Take Profit Set!
💰 Entry: ${entry_price:.4f}
🎯 TP: ${custom_price:.4f} (+{tp_pct:.1f}%)

Would you like to set a Stop Loss?
            """.strip()

            keyboard = [
                [InlineKeyboardButton("✅ Yes, set SL", callback_data="setup_sl_after_tp")],
                [InlineKeyboardButton("⏭️ Skip SL (TP only)", callback_data="finalize_tpsl")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

            return AWAITING_SL_PRICE

        elif tpsl_setup.get('awaiting_custom_sl'):
            # Validate SL price
            if custom_price >= entry_price:
                await update.message.reply_text(
                    f"❌ Stop Loss must be LOWER than entry (${entry_price:.4f})\n\n"
                    f"You entered: ${custom_price:.4f}\n"
                    f"Please try again or tap /cancel",
                    parse_mode='Markdown'
                )
                return  # Stay in same state

            # Store SL price
            context.user_data['tpsl_setup']['sl_price'] = custom_price
            context.user_data['tpsl_setup']['awaiting_custom_sl'] = False

            # Check if TP is already set
            tp_price = tpsl_setup.get('tp_price')
            position = tpsl_setup['position']
            entry_price = position['buy_price']

            if tp_price:
                # TP already set, finalize by delegating to finalize_tpsl function
                # Create a fake update object for finalize_tpsl
                class FakeUpdate:
                    def __init__(self, message):
                        self.message = message
                        self.callback_query = None
                        self.effective_user = message.from_user

                fake_update = FakeUpdate(update.message)
                return await finalize_tpsl(fake_update, context)
            else:
                # TP not set, ask if user wants to set it
                sl_pct = (custom_price - entry_price) / entry_price * 100

                message = f"""
✅ Stop Loss Set!
💰 Entry: ${entry_price:.4f}
🛑 SL: ${custom_price:.4f} ({sl_pct:+.1f}%)

Would you like to set a Take Profit?
                """.strip()

                keyboard = [
                    [InlineKeyboardButton("✅ Yes, set TP", callback_data="setup_tp_after_sl")],
                    [InlineKeyboardButton("✅ Done (SL only)", callback_data="finalize_tpsl")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
                ]

                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

                return AWAITING_TP_PRICE

            # The code below will not execute due to returns above
            market_question = position['market'].get('question', 'Unknown')[:40]
            entry_price = position['buy_price']

            message = f"""✅ TP/SL Set

{market_question}
{outcome.upper()} • {position['tokens']:.0f} tokens @ ${entry_price:.4f}

"""

            if tp_price:
                tp_pct = (tp_price - entry_price) / entry_price * 100
                message += f"🎯 TP ${tp_price:.4f} ({tp_pct:+.0f}%)\n"

            if sl_price:
                sl_pct = (sl_price - entry_price) / entry_price * 100
                message += f"🛑 SL ${sl_price:.4f} ({sl_pct:+.0f}%)\n"

            message = message.strip()

            await update.message.reply_text(message, parse_mode='Markdown')

            # Clean up context
            context.user_data.pop('tpsl_setup', None)

            return ConversationHandler.END

        else:
            await update.message.reply_text("❌ Unexpected state. Please start over from /positions")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"❌ handle_custom_price_input error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def finalize_tpsl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create the TP/SL order with configured prices"""
    try:
        query = update.callback_query if update.callback_query else None

        tpsl_setup = context.user_data.get('tpsl_setup')
        if not tpsl_setup:
            if query:
                await query.edit_message_text("❌ Session expired")
            return ConversationHandler.END

        # Extract data
        market_id = tpsl_setup['market_id']
        outcome = tpsl_setup['outcome']
        position = tpsl_setup['position']
        tp_price = tpsl_setup.get('tp_price')
        sl_price = tpsl_setup.get('sl_price')

        # Validation
        tpsl_service = get_tpsl_service()
        is_valid, error_msg = tpsl_service.validate_price_targets(
            entry_price=position['buy_price'],
            tp_price=tp_price,
            sl_price=sl_price
        )

        if not is_valid:
            message = f"❌ Invalid TP/SL Configuration\n\n{error_msg}"
            if query:
                await query.edit_message_text(message)
            return ConversationHandler.END

        # ⚠️ NEW: Check if TP/SL would trigger immediately
        current_price = tpsl_setup.get('current_price')
        entry_price = position['buy_price']

        # Check if we need to show immediate trigger warning
        show_warning = False
        warning_type = None
        warning_price = None

        if current_price:
            # Check if TP would trigger immediately (current >= TP)
            if tp_price and current_price >= tp_price:
                show_warning = True
                warning_type = "TP"
                warning_price = tp_price
            # Check if SL would trigger immediately (current <= SL)
            elif sl_price and current_price <= sl_price:
                show_warning = True
                warning_type = "SL"
                warning_price = sl_price

        # If immediate trigger detected, show warning and ask for confirmation
        if show_warning and not tpsl_setup.get('confirmed_immediate_trigger'):
            price_vs_entry = ((current_price - entry_price) / entry_price) * 100
            estimated_value = position['tokens'] * current_price

            if warning_type == "TP":
                warning_message = f"""
⚠️ IMMEDIATE TRIGGER WARNING
Your Take Profit (${warning_price:.4f}) is at or below the current market price (${current_price:.4f})!

📊 Position Status:• Entry: ${entry_price:.4f}
• Current: ${current_price:.4f} ({price_vs_entry:+.1f}%)
• Your TP: ${warning_price:.4f}

This order will execute IMMEDIATELY upon creation.

💵 Estimated proceeds: ${estimated_value:.2f}
📈 Profit: ${estimated_value - (position['tokens'] * entry_price):.2f}

Continue?
                """.strip()
            else:  # SL
                warning_message = f"""
⚠️ IMMEDIATE TRIGGER WARNING
Your Stop Loss (${warning_price:.4f}) is at or above the current market price (${current_price:.4f})!

📊 Position Status:• Entry: ${entry_price:.4f}
• Current: ${current_price:.4f} ({price_vs_entry:+.1f}%)
• Your SL: ${warning_price:.4f}

This order will execute IMMEDIATELY upon creation, selling your position at a loss.

💵 Estimated proceeds: ${estimated_value:.2f}
📉 Loss: ${estimated_value - (position['tokens'] * entry_price):.2f}

Continue?
                """.strip()

            keyboard = [
                [InlineKeyboardButton("✅ Yes, Execute Now", callback_data="confirm_immediate_trigger")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpsl_setup")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            if query:
                await query.edit_message_text(warning_message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(warning_message, reply_markup=reply_markup)

            return ConversationHandler.END  # Wait for user confirmation

        # PHASE 9: Get latest buy transaction for this token
        entry_transaction_id = tpsl_service.get_latest_buy_transaction(
            user_id=update.effective_user.id,
            token_id=position['token_id']
        )

        if entry_transaction_id:
            logger.info(f"✅ Linking TP/SL to entry transaction #{entry_transaction_id}")
        else:
            logger.warning(f"⚠️ No buy transaction found, TP/SL will have NULL entry_transaction_id")

        # Create TP/SL order
        order = tpsl_service.create_tpsl_order(
            user_id=update.effective_user.id,
            market_id=market_id,
            outcome=outcome,
            token_id=position['token_id'],
            monitored_tokens=position['tokens'],
            entry_price=position['buy_price'],
            take_profit_price=tp_price,
            stop_loss_price=sl_price,
            market_data=position['market'],
            entry_transaction_id=entry_transaction_id
        )

        if not order:
            message = "❌ Failed to create TP/SL order. Please try again."
            if query:
                await query.edit_message_text(message)
            return ConversationHandler.END

        # Success message
        market_question = position['market'].get('question', 'Unknown')[:40]
        entry_price = position['buy_price']

        message = f"""✅ TP/SL Set

{market_question}
{outcome.upper()} • {position['tokens']:.0f} tokens @ ${entry_price:.4f}

"""

        if tp_price:
            tp_pct = (tp_price - entry_price) / entry_price * 100
            message += f"🎯 TP ${tp_price:.4f} ({tp_pct:+.0f}%)\n"

        if sl_price:
            sl_pct = (sl_price - entry_price) / entry_price * 100
            message += f"🛑 SL ${sl_price:.4f} ({sl_pct:+.0f}%)\n"

        message = message.strip()

        if query:
            await query.edit_message_text(message)

        # Clean up context
        context.user_data.pop('tpsl_setup', None)

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"❌ finalize_tpsl error: {e}")
        if query:
            await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def cancel_tpsl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle TP/SL order cancellation"""
    try:
        query = update.callback_query
        # Note: Callback already answered by button_callback() - no need to answer again

        # Parse callback data: cancel_tpsl:order_id
        order_id = int(query.data.split(':')[1])

        tpsl_service = get_tpsl_service()
        success = tpsl_service.cancel_tpsl_order(order_id, reason="user_cancelled")

        if success:
            await query.edit_message_text(
                "✅ TP/SL Order Cancelled\n\n"
                "The monitoring has been stopped for this position.\n\n"
                "Use /tpsl to view remaining orders"
            )
        else:
            await query.edit_message_text("❌ Failed to cancel TP/SL order")

    except Exception as e:
        logger.error(f"❌ cancel_tpsl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def cancel_tpsl_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel TP/SL setup process"""
    query = update.callback_query
    await safe_answer_callback_query(query)
    await query.edit_message_text("❌ TP/SL setup cancelled")
    context.user_data.pop('tpsl_setup', None)
    return ConversationHandler.END


async def edit_tpsl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle 'edit_tpsl' callback from /positions command
    Uses position INDEX instead of token ID (fixes 64-byte limit)
    """
    try:
        query = update.callback_query
        # Note: Callback already answered by button_callback() - no need to answer again

        user_id = query.from_user.id

        # Parse callback data: edit_tpsl:{position_index}
        callback_data = query.data
        parts = callback_data.split(':')

        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        position_index = int(parts[1])

        # Get position data from session mapping
        from telegram_bot.session_manager import session_manager
        position_data = session_manager.get_position_mapping(user_id, position_index)

        if not position_data:
            await query.edit_message_text("❌ Position mapping not found. Please refresh /positions and try again.")
            return

        token_id = position_data['token_id']

        # Get existing TP/SL order
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_active_tpsl_by_token(user_id, token_id)

        if not tpsl_order:
            await query.edit_message_text("❌ No active TP/SL found for this position")
            return

        # Show edit screen
        entry_price = float(tpsl_order.entry_price)
        tp_price = float(tpsl_order.take_profit_price) if tpsl_order.take_profit_price else None
        sl_price = float(tpsl_order.stop_loss_price) if tpsl_order.stop_loss_price else None

        market_title = tpsl_order.market_data.get('question', 'Unknown')[:40] if tpsl_order.market_data else 'Unknown'

        message = f"""
📝 Edit TP/SL
📊 Market: {market_title}...
🎯 Position: {tpsl_order.outcome.upper()} ({float(tpsl_order.monitored_tokens):.0f} tokens)
💰 Entry: ${entry_price:.4f}

Current Settings:"""

        if tp_price:
            tp_pct = (tp_price - entry_price) / entry_price * 100
            message += f"🎯 TP: ${tp_price:.4f} ({tp_pct:+.1f}%)\n"
        else:
            message += "🎯 TP: Not set\n"

        if sl_price:
            sl_pct = (sl_price - entry_price) / entry_price * 100
            message += f"🛑 SL: ${sl_price:.4f} ({sl_pct:+.1f}%)\n"
        else:
            message += "🛑 SL: Not set\n"

        message += "\nWhat would you like to do?"

        # Dynamic cancel button text
        if tp_price and sl_price:
            cancel_text = "❌ Cancel TP/SL"
        elif tp_price:
            cancel_text = "❌ Cancel TP"
        elif sl_price:
            cancel_text = "❌ Cancel SL"
        else:
            cancel_text = "❌ Cancel"

        keyboard = [
            [
                InlineKeyboardButton("🎯 Update TP", callback_data=f"update_tp:{tpsl_order.id}"),
                InlineKeyboardButton("🛑 Update SL", callback_data=f"update_sl:{tpsl_order.id}")
            ],
            [InlineKeyboardButton(cancel_text, callback_data=f"cancel_tpsl:{tpsl_order.id}")],
            [InlineKeyboardButton("← Back", callback_data="emergency_refresh")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ edit_tpsl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def edit_tpsl_by_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle 'edit_tpsl_by_id' callback from /tpsl command
    Uses TP/SL order ID directly (for viewing all TP/SL orders)
    """
    try:
        query = update.callback_query
        # Note: Callback already answered by button_callback() - no need to answer again

        user_id = query.from_user.id

        # Parse callback data: edit_tpsl_by_id:{order_id}
        callback_data = query.data
        parts = callback_data.split(':')

        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])

        # Get TP/SL order directly by ID
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_tpsl_by_id(order_id)

        if not tpsl_order or tpsl_order.user_id != user_id:
            await query.edit_message_text("❌ TP/SL order not found")
            return

        # Show edit screen
        entry_price = float(tpsl_order.entry_price)
        tp_price = float(tpsl_order.take_profit_price) if tpsl_order.take_profit_price else None
        sl_price = float(tpsl_order.stop_loss_price) if tpsl_order.stop_loss_price else None

        market_title = tpsl_order.market_data.get('question', 'Unknown')[:40] if tpsl_order.market_data else 'Unknown'

        message = f"""
📝 Edit TP/SL
📊 Market: {market_title}...
🎯 Position: {tpsl_order.outcome.upper()} ({float(tpsl_order.monitored_tokens):.0f} tokens)
💰 Entry: ${entry_price:.4f}

Current Settings:"""

        if tp_price:
            tp_pct = (tp_price - entry_price) / entry_price * 100
            message += f"🎯 TP: ${tp_price:.4f} ({tp_pct:+.1f}%)\n"
        else:
            message += "🎯 TP: Not set\n"

        if sl_price:
            sl_pct = (sl_price - entry_price) / entry_price * 100
            message += f"🛑 SL: ${sl_price:.4f} ({sl_pct:+.1f}%)\n"
        else:
            message += "🛑 SL: Not set\n"

        message += "\nWhat would you like to do?"

        # Dynamic cancel button text
        if tp_price and sl_price:
            cancel_text = "❌ Cancel TP/SL"
        elif tp_price:
            cancel_text = "❌ Cancel TP"
        elif sl_price:
            cancel_text = "❌ Cancel SL"
        else:
            cancel_text = "❌ Cancel"

        keyboard = [
            [
                InlineKeyboardButton("🎯 Update TP", callback_data=f"update_tp:{tpsl_order.id}"),
                InlineKeyboardButton("🛑 Update SL", callback_data=f"update_sl:{tpsl_order.id}")
            ],
            [InlineKeyboardButton(cancel_text, callback_data=f"cancel_tpsl:{tpsl_order.id}")],
            [InlineKeyboardButton("← Back to List", callback_data="view_all_tpsl")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ edit_tpsl_by_id_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def update_tp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'update_tp' callback - show TP price update options"""
    try:
        query = update.callback_query
        # Note: Callback already answered by button_callback() - no need to answer again

        user_id = query.from_user.id

        # Parse callback data: update_tp:{order_id}
        callback_data = query.data
        parts = callback_data.split(':')

        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])

        # Get TP/SL order
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_tpsl_by_id(order_id)

        if not tpsl_order or tpsl_order.user_id != user_id:
            await query.edit_message_text("❌ TP/SL order not found")
            return

        entry_price = float(tpsl_order.entry_price)
        market_title = tpsl_order.market_data.get('question', 'Unknown')[:40] if tpsl_order.market_data else 'Unknown'

        # Calculate preset TP levels
        tp_5 = entry_price * 1.05
        tp_10 = entry_price * 1.10
        tp_20 = entry_price * 1.20
        tp_30 = entry_price * 1.30

        message = f"""
🎯 Update Take Profit
📊 Market: {market_title}...
💰 Entry: ${entry_price:.4f}

Select new TP price:
        """.strip()

        keyboard = [
            [
                InlineKeyboardButton(f"+5%: ${tp_5:.2f}", callback_data=f"update_tp_preset:{order_id}:{tp_5:.4f}"),
                InlineKeyboardButton(f"+10%: ${tp_10:.2f}", callback_data=f"update_tp_preset:{order_id}:{tp_10:.4f}")
            ],
            [
                InlineKeyboardButton(f"+20%: ${tp_20:.2f}", callback_data=f"update_tp_preset:{order_id}:{tp_20:.4f}"),
                InlineKeyboardButton(f"+30%: ${tp_30:.2f}", callback_data=f"update_tp_preset:{order_id}:{tp_30:.4f}")
            ],
            [InlineKeyboardButton("✏️ Custom %", callback_data=f"custom_tp:{order_id}")],
            [InlineKeyboardButton("🗑️ Remove TP", callback_data=f"remove_tp:{order_id}")],
            [InlineKeyboardButton("← Back", callback_data=f"edit_tpsl_by_id:{order_id}")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ update_tp_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def update_sl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'update_sl' callback - show SL price update options"""
    try:
        query = update.callback_query
        # Note: Callback already answered by button_callback() - no need to answer again

        user_id = query.from_user.id

        # Parse callback data: update_sl:{order_id}
        callback_data = query.data
        parts = callback_data.split(':')

        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])

        # Get TP/SL order
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_tpsl_by_id(order_id)

        if not tpsl_order or tpsl_order.user_id != user_id:
            await query.edit_message_text("❌ TP/SL order not found")
            return

        entry_price = float(tpsl_order.entry_price)
        market_title = tpsl_order.market_data.get('question', 'Unknown')[:40] if tpsl_order.market_data else 'Unknown'

        # Calculate preset SL levels
        sl_5 = entry_price * 0.95
        sl_10 = entry_price * 0.90
        sl_20 = entry_price * 0.80
        sl_30 = entry_price * 0.70

        message = f"""
🛑 Update Stop Loss
📊 Market: {market_title}...
💰 Entry: ${entry_price:.4f}

Select new SL price:
        """.strip()

        keyboard = [
            [
                InlineKeyboardButton(f"-5%: ${sl_5:.2f}", callback_data=f"update_sl_preset:{order_id}:{sl_5:.4f}"),
                InlineKeyboardButton(f"-10%: ${sl_10:.2f}", callback_data=f"update_sl_preset:{order_id}:{sl_10:.4f}")
            ],
            [
                InlineKeyboardButton(f"-20%: ${sl_20:.2f}", callback_data=f"update_sl_preset:{order_id}:{sl_20:.4f}"),
                InlineKeyboardButton(f"-30%: ${sl_30:.2f}", callback_data=f"update_sl_preset:{order_id}:{sl_30:.4f}")
            ],
            [InlineKeyboardButton("✏️ Custom %", callback_data=f"custom_sl:{order_id}")],
            [InlineKeyboardButton("🗑️ Remove SL", callback_data=f"remove_sl:{order_id}")],
            [InlineKeyboardButton("← Back", callback_data=f"edit_tpsl_by_id:{order_id}")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ update_sl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def update_tp_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle preset TP price update"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query, text="✅ Take Profit updated!")

        user_id = query.from_user.id

        # Parse: update_tp_preset:{order_id}:{price}
        parts = query.data.split(':')
        if len(parts) != 3:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])
        new_tp_price = float(parts[2])

        # Update TP/SL order
        tpsl_service = get_tpsl_service()
        updated_order = tpsl_service.update_tpsl_order(
            tpsl_id=order_id,
            take_profit_price=new_tp_price
        )

        if not updated_order:
            await query.edit_message_text("❌ Failed to update Take Profit")
            return

        # Show success message with chained SL update option
        entry_price = float(updated_order.entry_price)
        tp_pct = (new_tp_price - entry_price) / entry_price * 100
        current_sl = float(updated_order.stop_loss_price) if updated_order.stop_loss_price else None

        message = f"""
✅ Take Profit Updated!
💰 Entry: ${entry_price:.4f}
🎯 New TP: ${new_tp_price:.4f} ({tp_pct:+.1f}%)
"""

        if current_sl and current_sl > 0:
            sl_pct = (current_sl - entry_price) / entry_price * 100
            message += f"🛑 Current SL: ${current_sl:.4f} ({sl_pct:+.1f}%)\n"
        else:
            message += "🛑 SL: Not set\n"

        message += "\nWould you like to update Stop Loss too?"

        keyboard = [
            [InlineKeyboardButton("✅ Yes, update SL", callback_data=f"update_sl:{order_id}")],
            [InlineKeyboardButton("✅ Done", callback_data=f"edit_tpsl_by_id:{order_id}")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ update_tp_preset_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def update_sl_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle preset SL price update"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query, text="✅ Stop Loss updated!")

        user_id = query.from_user.id

        # Parse: update_sl_preset:{order_id}:{price}
        parts = query.data.split(':')
        if len(parts) != 3:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])
        new_sl_price = float(parts[2])

        # Update TP/SL order
        tpsl_service = get_tpsl_service()
        updated_order = tpsl_service.update_tpsl_order(
            tpsl_id=order_id,
            stop_loss_price=new_sl_price
        )

        if not updated_order:
            await query.edit_message_text("❌ Failed to update Stop Loss")
            return

        # Show success message with chained TP update option
        entry_price = float(updated_order.entry_price)
        sl_pct = (new_sl_price - entry_price) / entry_price * 100
        current_tp = float(updated_order.take_profit_price) if updated_order.take_profit_price else None

        message = f"""
✅ Stop Loss Updated!
💰 Entry: ${entry_price:.4f}
🛑 New SL: ${new_sl_price:.4f} ({sl_pct:+.1f}%)
"""

        if current_tp and current_tp > 0:
            tp_pct = (current_tp - entry_price) / entry_price * 100
            message += f"🎯 Current TP: ${current_tp:.4f} ({tp_pct:+.1f}%)\n"
        else:
            message += "🎯 TP: Not set\n"

        message += "\nWould you like to update Take Profit too?"

        keyboard = [
            [InlineKeyboardButton("✅ Yes, update TP", callback_data=f"update_tp:{order_id}")],
            [InlineKeyboardButton("✅ Done", callback_data=f"edit_tpsl_by_id:{order_id}")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ update_sl_preset_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def view_all_tpsl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle 'view_all_tpsl' callback from /positions command
    Shows all active TP/SL orders (same as /tpsl command but from callback)
    """
    try:
        query = update.callback_query
        # Note: Callback already answered by button_callback() - no need to answer again

        user_id = query.from_user.id
        tpsl_service = get_tpsl_service()

        # Get all active TP/SL orders for user
        active_orders = tpsl_service.get_active_tpsl_orders(user_id=user_id)

        if not active_orders:
            keyboard = [[InlineKeyboardButton("⬅️ Back to Positions", callback_data="positions_refresh")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "📭 No Active TP/SL\n\n"
                "Set TP/SL on your positions to auto-sell at target prices.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return

        # Build message with all TP/SL orders
        message = f"📊 Active TP/SL ({len(active_orders)})\n\n"

        keyboard = []

        for i, order in enumerate(active_orders, 1):
            market_question = order.market_data.get('question', 'Unknown Market') if order.market_data else 'Unknown Market'
            entry_price = float(order.entry_price)

            # Calculate percentages
            tp_pct = ((float(order.take_profit_price) - entry_price) / entry_price * 100) if order.take_profit_price else None
            sl_pct = ((float(order.stop_loss_price) - entry_price) / entry_price * 100) if order.stop_loss_price else None

            # Condensed format
            message += f"{i}. {market_question[:40]}\n"
            message += f"   {order.outcome.upper()} • Entry ${entry_price:.4f}\n"

            # Build TP/SL line
            tpsl_parts = []
            if order.take_profit_price:
                tpsl_parts.append(f"🎯 TP {tp_pct:+.0f}%")
            if order.stop_loss_price:
                tpsl_parts.append(f"🛑 SL {sl_pct:+.0f}%")

            if tpsl_parts:
                message += f"   {' • '.join(tpsl_parts)}\n"

            message += "\n"

            # Add buttons for each order
            keyboard.append([
                InlineKeyboardButton(
                    f"📝 Edit #{i}",
                    callback_data=f"edit_tpsl_by_id:{order.id}"
                ),
                InlineKeyboardButton(
                    f"❌ Cancel #{i}",
                    callback_data=f"cancel_tpsl:{order.id}"
                )
            ])

        keyboard.append([InlineKeyboardButton("⬅️ Back to Positions", callback_data="positions_refresh")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ view_all_tpsl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def tpsl_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /tpsl_history command - View cancelled/triggered TP/SL orders from last 30 days
    """
    try:
        user_id = update.effective_user.id
        tpsl_service = get_tpsl_service()

        # Get history (last 30 days)
        history = tpsl_service.get_tpsl_history(user_id, days=30)

        if not history:
            await update.message.reply_text(
                "📜 TP/SL History\n\n"
                "No cancelled or triggered orders in the last 30 days.\n\n"
                "Use /tpsl to view active orders",
                parse_mode='Markdown'
            )
            return

        # Group by status
        triggered = [o for o in history if o.status == 'triggered']
        cancelled = [o for o in history if o.status == 'cancelled']

        # Build message
        message = "📜 TP/SL History (Last 30 days)\n\n"

        # Show triggered orders (executions)
        if triggered:
            message += "✅ Triggered & Executed:\n\n"
            for order in triggered[:5]:  # Limit to 5 most recent
                market_question = order.market_data.get('question', 'Unknown')[:40] if order.market_data else 'Unknown'
                trigger_type = "🎯 TP" if order.triggered_type == 'take_profit' else "🛑 SL"
                exec_price = float(order.execution_price) if order.execution_price else 0
                entry_price = float(order.entry_price)
                pnl_pct = ((exec_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                message += f"{trigger_type} {market_question}...\n"
                # PHASE 9: Show entry transaction
                if order.entry_transaction_id:
                    message += f"   📋 Entry: Transaction #{order.entry_transaction_id}\n"
                message += f"   {order.outcome.upper()} @ ${exec_price:.4f} ({pnl_pct:+.1f}%)\n"
                message += f"   {order.triggered_at.strftime('%m/%d %H:%M')}\n\n"

        # Show cancelled orders
        if cancelled:
            message += "❌ Cancelled:\n\n"

            # Reason display mapping
            reason_display = {
                'user_cancelled': '👤 User cancelled',
                'market_closed': '⏸️ Market closed',
                'market_resolved': '🎉 Market resolved',
                'position_closed': '💸 Position sold',
                'position_increased': '📈 Position increased',
                'insufficient_tokens': '⚠️ Not enough tokens',
                'both_null': '⚫ Both targets removed'
            }

            for order in cancelled[:10]:  # Limit to 10 most recent
                market_question = order.market_data.get('question', 'Unknown')[:40] if order.market_data else 'Unknown'
                reason = reason_display.get(
                    order.cancelled_reason,
                    '❓ Unknown'
                )
                cancelled_date = order.cancelled_at.strftime('%m/%d %H:%M') if order.cancelled_at else 'Unknown'

                message += f"{market_question}...\n"
                # PHASE 9: Show entry transaction
                if order.entry_transaction_id:
                    message += f"   📋 Entry: Transaction #{order.entry_transaction_id}\n"
                message += f"   {reason}\n"
                message += f"   {cancelled_date}\n\n"

        message += "━━━━━━━━━━━━━━━━━━━━\n"
        message += "Use /tpsl to view active orders"

        await update.message.reply_text(message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ TP/SL HISTORY ERROR: {e}")
        await update.message.reply_text(
            "❌ Error loading history. Please try again.",
            parse_mode='Markdown'
        )


async def custom_tp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom TP price input request"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        user_id = query.from_user.id

        # Parse: custom_tp:{order_id}
        parts = query.data.split(':')
        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])

        # Get TP/SL order info
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_tpsl_by_id(order_id)

        if not tpsl_order or tpsl_order.user_id != user_id:
            await query.edit_message_text("❌ TP/SL order not found")
            return

        entry_price = float(tpsl_order.entry_price)
        market_title = tpsl_order.market_data.get('question', 'Unknown')[:40] if tpsl_order.market_data else 'Unknown'

        # Store order info in context for text input handler
        context.user_data['awaiting_custom_tp'] = {
            'order_id': order_id,
            'entry_price': entry_price,
            'market_title': market_title
        }

        message = f"""
✏️ Custom Take Profit %
📊 Market: {market_title}...
💰 Entry: ${entry_price:.4f}

Please send your custom TP percentage (e.g., 7 for +7%)

⚠️ Enter positive number only (e.g., 7 = +7%)
        """.strip()

        from telegram import ForceReply
        await query.message.reply_text(message, parse_mode='Markdown', reply_markup=ForceReply(selective=True))

        # Delete the button menu
        try:
            await query.message.delete()
        except:
            pass

    except Exception as e:
        logger.error(f"❌ custom_tp_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def custom_sl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom SL price input request"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        user_id = query.from_user.id

        # Parse: custom_sl:{order_id}
        parts = query.data.split(':')
        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])

        # Get TP/SL order info
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_tpsl_by_id(order_id)

        if not tpsl_order or tpsl_order.user_id != user_id:
            await query.edit_message_text("❌ TP/SL order not found")
            return

        entry_price = float(tpsl_order.entry_price)
        market_title = tpsl_order.market_data.get('question', 'Unknown')[:40] if tpsl_order.market_data else 'Unknown'

        # Store order info in context for text input handler
        context.user_data['awaiting_custom_sl'] = {
            'order_id': order_id,
            'entry_price': entry_price,
            'market_title': market_title
        }

        message = f"""
✏️ Custom Stop Loss %
📊 Market: {market_title}...
💰 Entry: ${entry_price:.4f}

Please send your custom SL percentage (e.g., -7 for -7%)

⚠️ Enter NEGATIVE number only (e.g., -7 = -7% below entry)
        """.strip()

        from telegram import ForceReply
        await query.message.reply_text(message, parse_mode='Markdown', reply_markup=ForceReply(selective=True))

        # Delete the button menu
        try:
            await query.message.delete()
        except:
            pass

    except Exception as e:
        logger.error(f"❌ custom_sl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def handle_edit_custom_percentage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for editing existing TP/SL with custom percentage"""
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()

        # Check if we're awaiting custom TP input (FOR EDITING EXISTING)
        if 'awaiting_custom_tp' in context.user_data:
            order_info = context.user_data.pop('awaiting_custom_tp')

            # Parse percentage
            try:
                custom_pct = float(text)
            except ValueError:
                await update.message.reply_text(
                    f"❌ Invalid format. Please enter a number (e.g., 7 for +7%)\n\n"
                    f"Entry price: ${order_info['entry_price']:.4f}",
                    parse_mode='Markdown'
                )
                return

            # Validate: Must be positive
            if custom_pct <= 0:
                await update.message.reply_text(
                    f"❌ Please enter a positive number!\n\n"
                    f"Example: 7 (for +7% profit)\n\n"
                    f"Try again.",
                    parse_mode='Markdown'
                )
                context.user_data['awaiting_custom_tp'] = order_info
                return

            entry_price = order_info['entry_price']

            # Calculate TP price from percentage
            custom_price = entry_price * (1 + custom_pct / 100)

            # Update TP/SL order
            tpsl_service = get_tpsl_service()
            updated_order = tpsl_service.update_tpsl_order(
                tpsl_id=order_info['order_id'],
                take_profit_price=custom_price
            )

            if not updated_order:
                await update.message.reply_text("❌ Failed to update Take Profit")
                return

            # Success! Show chained SL update option
            current_sl = float(updated_order.stop_loss_price) if updated_order.stop_loss_price else None

            message = f"""
✅ Take Profit Updated!
💰 Entry: ${entry_price:.4f}
🎯 New TP: ${custom_price:.4f} (+{custom_pct:.1f}%)
"""

            if current_sl and current_sl > 0:
                sl_pct = (current_sl - entry_price) / entry_price * 100
                message += f"🛑 Current SL: ${current_sl:.4f} ({sl_pct:+.1f}%)\n"
            else:
                message += "🛑 SL: Not set\n"

            message += "\nWould you like to update Stop Loss too?"

            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = [
                [InlineKeyboardButton("✅ Yes, update SL", callback_data=f"update_sl:{order_info['order_id']}")],
                [InlineKeyboardButton("✅ Done", callback_data=f"edit_tpsl_by_id:{order_info['order_id']}")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

        # Check if we're awaiting custom SL input
        elif 'awaiting_custom_sl' in context.user_data:
            order_info = context.user_data.pop('awaiting_custom_sl')

            # Parse percentage
            try:
                custom_pct = float(text)
            except ValueError:
                await update.message.reply_text(
                    f"❌ Invalid format. Please enter a number (e.g., -7 for -7%)\n\n"
                    f"Entry price: ${order_info['entry_price']:.4f}",
                    parse_mode='Markdown'
                )
                return

            # Validate: Must be NEGATIVE for SL
            if custom_pct >= 0:
                await update.message.reply_text(
                    f"❌ Stop Loss must be a NEGATIVE number!\n\n"
                    f"Entry: ${order_info['entry_price']:.4f}\n"
                    f"Example: -7 (for -7% stop loss)\n\n"
                    f"Try again.",
                    parse_mode='Markdown'
                )
                context.user_data['awaiting_custom_sl'] = order_info
                return

            entry_price = order_info['entry_price']

            # Calculate SL price from percentage (already negative)
            custom_price = entry_price * (1 + custom_pct / 100)

            # Update TP/SL order
            tpsl_service = get_tpsl_service()
            updated_order = tpsl_service.update_tpsl_order(
                tpsl_id=order_info['order_id'],
                stop_loss_price=custom_price
            )

            if not updated_order:
                await update.message.reply_text("❌ Failed to update Stop Loss")
                return

            # Success! Show chained TP update option
            current_tp = float(updated_order.take_profit_price) if updated_order.take_profit_price else None

            message = f"""
✅ Stop Loss Updated!
💰 Entry: ${entry_price:.4f}
🛑 New SL: ${custom_price:.4f} ({custom_pct:.1f}%)
"""

            if current_tp and current_tp > 0:
                tp_pct = (current_tp - entry_price) / entry_price * 100
                message += f"🎯 Current TP: ${current_tp:.4f} ({tp_pct:+.1f}%)\n"
            else:
                message += "🎯 TP: Not set\n"

            message += "\nWould you like to update Take Profit too?"

            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = [
                [InlineKeyboardButton("✅ Yes, update TP", callback_data=f"update_tp:{order_info['order_id']}")],
                [InlineKeyboardButton("✅ Done", callback_data=f"edit_tpsl_by_id:{order_info['order_id']}")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ handle_edit_custom_percentage error: {e}")
        # Silently ignore if not waiting for custom input


async def remove_tp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Remove TP - set TP to None/0"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        user_id = query.from_user.id

        # Parse: remove_tp:{order_id}
        parts = query.data.split(':')
        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])

        # Get TP/SL order info
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_tpsl_by_id(order_id)

        if not tpsl_order or tpsl_order.user_id != user_id:
            await query.edit_message_text("❌ TP/SL order not found")
            return

        # Remove TP (set to None)
        updated_order = tpsl_service.update_tpsl_order(
            tpsl_id=order_id,
            take_profit_price=0  # 0 = remove
        )

        if not updated_order:
            await query.edit_message_text("❌ Failed to remove Take Profit")
            return

        # Check if SL still exists
        sl_price = float(updated_order.stop_loss_price) if updated_order.stop_loss_price else None

        if not sl_price or sl_price == 0:
            # No TP or SL left - cancel the entire order
            tpsl_service.cancel_tpsl_order(order_id, reason="no_tp_or_sl")
            await query.edit_message_text(
                "✅ Take Profit Removed\n\n"
                "Since there's no Stop Loss either, the TP/SL order has been cancelled.\n\n"
                "Use /positions to set a new TP/SL."
            )
        else:
            await query.edit_message_text(
                f"✅ Take Profit Removed\n\n"
                f"Stop Loss is still active at ${sl_price:.4f}\n\n"
                f"Use /positions to edit or view your TP/SL orders."
            )

    except Exception as e:
        logger.error(f"❌ remove_tp_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")




async def confirm_immediate_trigger_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user confirmation to proceed with immediate trigger"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        # Mark as confirmed and call finalize_tpsl again
        tpsl_setup = context.user_data.get('tpsl_setup')
        if not tpsl_setup:
            await query.edit_message_text("❌ Session expired")
            return ConversationHandler.END

        # Set confirmation flag
        context.user_data['tpsl_setup']['confirmed_immediate_trigger'] = True

        # Call finalize_tpsl again (will bypass warning this time)
        return await finalize_tpsl(update, context)

    except Exception as e:
        logger.error(f"❌ confirm_immediate_trigger_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        return ConversationHandler.END


async def remove_sl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Remove SL - set SL to None/0"""
    try:
        query = update.callback_query
        await safe_answer_callback_query(query)

        user_id = query.from_user.id

        # Parse: remove_sl:{order_id}
        parts = query.data.split(':')
        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data")
            return

        order_id = int(parts[1])

        # Get TP/SL order info
        tpsl_service = get_tpsl_service()
        tpsl_order = tpsl_service.get_tpsl_by_id(order_id)

        if not tpsl_order or tpsl_order.user_id != user_id:
            await query.edit_message_text("❌ TP/SL order not found")
            return

        # Remove SL (set to None)
        updated_order = tpsl_service.update_tpsl_order(
            tpsl_id=order_id,
            stop_loss_price=0  # 0 = remove
        )

        if not updated_order:
            await query.edit_message_text("❌ Failed to remove Stop Loss")
            return

        # Check if TP still exists
        tp_price = float(updated_order.take_profit_price) if updated_order.take_profit_price else None

        if not tp_price or tp_price == 0:
            # No TP or SL left - cancel the entire order
            tpsl_service.cancel_tpsl_order(order_id, reason="no_tp_or_sl")
            await query.edit_message_text(
                "✅ Stop Loss Removed\n\n"
                "Since there's no Take Profit either, the TP/SL order has been cancelled.\n\n"
                "Use /positions to set a new TP/SL."
            )
        else:
            await query.edit_message_text(
                f"✅ Stop Loss Removed\n\n"
                f"Take Profit is still active at ${tp_price:.4f}\n\n"
                f"Use /positions to edit or view your TP/SL orders."
            )

    except Exception as e:
        logger.error(f"❌ remove_sl_callback error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


def register(app, session_manager):
    """Register TP/SL handlers with the application"""

    # /tpsl command to view all TP/SL orders
    app.add_handler(CommandHandler("tpsl", tpsl_command))

    # PHASE 6: /tpsl_history command to view past orders
    app.add_handler(CommandHandler("tpsl_history", tpsl_history_command))

    # Callback handlers for TP/SL actions
    app.add_handler(CallbackQueryHandler(set_tpsl_callback, pattern=r"^set_tpsl:"))
    app.add_handler(CallbackQueryHandler(setup_tp_callback, pattern=r"^setup_tp:"))
    app.add_handler(CallbackQueryHandler(setup_sl_callback, pattern=r"^setup_sl:"))
    app.add_handler(CallbackQueryHandler(tp_preset_callback, pattern=r"^tp_preset:"))
    app.add_handler(CallbackQueryHandler(sl_preset_callback, pattern=r"^sl_preset:"))
    app.add_handler(CallbackQueryHandler(tp_custom_callback, pattern="^tp_custom$"))
    app.add_handler(CallbackQueryHandler(sl_custom_callback, pattern="^sl_custom$"))
    app.add_handler(CallbackQueryHandler(setup_sl_after_tp_callback, pattern="^setup_sl_after_tp$"))
    app.add_handler(CallbackQueryHandler(setup_tp_after_sl_callback, pattern="^setup_tp_after_sl$"))
    app.add_handler(CallbackQueryHandler(cancel_tpsl_callback, pattern=r"^cancel_tpsl:"))
    app.add_handler(CallbackQueryHandler(cancel_tpsl_setup, pattern="^cancel_tpsl_setup$"))
    app.add_handler(CallbackQueryHandler(finalize_tpsl, pattern="^finalize_tpsl$"))

    # NEW: Custom TP/SL price input handlers
    app.add_handler(CallbackQueryHandler(custom_tp_callback, pattern=r"^custom_tp:"))
    app.add_handler(CallbackQueryHandler(custom_sl_callback, pattern=r"^custom_sl:"))

    # NEW: Remove TP/SL handlers
    app.add_handler(CallbackQueryHandler(remove_tp_callback, pattern=r"^remove_tp:"))
    app.add_handler(CallbackQueryHandler(remove_sl_callback, pattern=r"^remove_sl:"))

    # Message handler for custom price text input
    # This needs to be added with low priority so it doesn't intercept all messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_custom_price_input
        ),
        group=10  # Lower priority group so it doesn't intercept everything
    )

    logger.info("✅ TP/SL handlers registered (including custom price input)")
