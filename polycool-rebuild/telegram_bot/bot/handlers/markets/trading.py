"""
Markets Trading Module
Handles buy/sell operations and order management
"""
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.user.user_helper import get_user_data
from core.services.market.market_helper import get_market_data
from core.services.position.outcome_helper import find_outcome_index
from core.services.clob.clob_service import get_clob_service
from core.services.balance.balance_service import balance_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_quick_buy_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle quick buy callback with preset amounts
    Format: "quick_buy_{market_id}_{outcome}"
    Shows preset amount buttons: $10, $25, $50
    """
    try:
        # Note: query.answer() is already called in handle_market_callback
        # Parse: "quick_buy_{market_id}_{outcome}"
        parts = callback_data.split("_")
        market_id = "_".join(parts[2:-1])  # Handle market IDs with underscores
        outcome = parts[-1]

        logger.info(f"🎯 Quick buy callback: market_id={market_id[:30]}..., outcome={outcome}")

        # Get market details (via API or DB)
        market = await get_market_data(market_id, context)

        if not market:
            logger.warning(f"⚠️ Market not found for quick buy: {market_id[:30]}...")
            await query.edit_message_text("❌ Market not found. Please try again.")
            return

        # Get current prices
        outcome_prices = market.get('outcome_prices', [])
        outcomes = market.get('outcomes', ['YES', 'NO'])

        try:
            # Use intelligent outcome normalization
            outcome_index = find_outcome_index(outcome, outcomes)
            if outcome_index is not None and outcome_index < len(outcome_prices):
                current_price = float(outcome_prices[outcome_index])
            else:
                logger.warning(f"⚠️ Could not find price for outcome '{outcome}' in market {market_id}, using fallback 0.5")
                current_price = 0.5
        except (IndexError, ValueError, TypeError) as e:
            logger.warning(f"⚠️ Error extracting price for outcome '{outcome}': {e}, using fallback 0.5")
            current_price = 0.5

        # Calculate estimated tokens for each preset
        presets = [10, 25, 50]
        keyboard = []

        for amount in presets:
            estimated_tokens = int(amount / current_price) if current_price > 0 else 0
            button_text = f"${amount} (~{estimated_tokens} tokens)"
            callback_data = f"buy_amount_{market_id}_{outcome}_{amount}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        # Custom buy button (with outcome pre-selected)
        keyboard.append([InlineKeyboardButton("💰 Custom Buy", callback_data=f"custom_buy_amount_{market_id}_{outcome}")])

        # Back button
        keyboard.append([InlineKeyboardButton("← Back to Market", callback_data=f"market_select_{market_id}_0")])

        # Format message - use actual outcome from market
        # Get the outcome as it appears in the market (preserve original case)
        outcomes = market.get('outcomes', ['YES', 'NO'])
        outcome_upper = outcome.upper()
        # Find matching outcome to preserve original case
        actual_outcome = outcome  # Default to passed outcome
        for o in outcomes:
            if o.upper() == outcome_upper:
                actual_outcome = o
                break

        # Use emoji based on position (first outcome = green, second = red)
        if len(outcomes) >= 2 and outcomes[0].upper() == outcome_upper:
            side_emoji = f"🟢 {actual_outcome}"
        elif len(outcomes) >= 2 and outcomes[1].upper() == outcome_upper:
            side_emoji = f"🔴 {actual_outcome}"
        else:
            side_emoji = actual_outcome

        message = f"""
**Quick Buy - {side_emoji}**

Market: {market.get('title', 'Unknown Market')[:50]}...

Current Price: ${current_price:.4f} per token

Choose amount:
""".strip()

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in quick buy callback: {e}")
        await query.edit_message_text("❌ Error loading quick buy options")


async def handle_buy_amount_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle buy amount selection and show confirmation
    Format: "buy_amount_{market_id}_{outcome}_{amount}"
    """
    try:
        # Parse: "buy_amount_{market_id}_{outcome}_{amount}"
        parts = callback_data.split("_")
        market_id = "_".join(parts[2:-2])  # Handle market IDs with underscores
        outcome = parts[-2]
        amount = float(parts[-1])

        # Get market details (via API or DB)
        market = await get_market_data(market_id, context)

        if not market:
            await query.answer("Market not found", show_alert=True)
            return

        # Get current prices
        outcome_prices = market.get('outcome_prices', [])
        outcomes = market.get('outcomes', ['YES', 'NO'])

        try:
            # Use intelligent outcome normalization
            outcome_index = find_outcome_index(outcome, outcomes)
            if outcome_index is not None and outcome_index < len(outcome_prices):
                current_price = float(outcome_prices[outcome_index])
            else:
                logger.warning(f"⚠️ Could not find price for outcome '{outcome}' in market {market_id}, using fallback 0.5")
                current_price = 0.5
        except (IndexError, ValueError, TypeError) as e:
            logger.warning(f"⚠️ Error extracting price for outcome '{outcome}': {e}, using fallback 0.5")
            current_price = 0.5

        # Calculate estimated tokens
        estimated_tokens = int(amount / current_price) if current_price > 0 else 0

        # Get user's USDC.e balance via API
        telegram_user_id = query.from_user.id
        user_data = await get_user_data(telegram_user_id)
        usdc_balance = None

        if user_data:
            try:
                api_client = get_api_client()
                internal_id = user_data.get('id')
                if internal_id:
                    balance_data = await api_client.get_wallet_balance(internal_id)
                    if balance_data:
                        usdc_balance = balance_data.get('usdc_balance')
            except Exception as e:
                logger.warning(f"Could not fetch USDC.e balance: {e}")

        # Build confirmation message
        # Use actual outcome from market - preserve original case
        outcomes = market.get('outcomes', ['YES', 'NO'])
        outcome_upper = outcome.upper()
        actual_outcome = outcome  # Default to passed outcome
        for o in outcomes:
            if o.upper() == outcome_upper:
                actual_outcome = o
                break

        # Use emoji based on position (first outcome = green, second = red)
        if len(outcomes) >= 2 and outcomes[0].upper() == outcome_upper:
            side_emoji = f"🟢 {actual_outcome}"
        elif len(outcomes) >= 2 and outcomes[1].upper() == outcome_upper:
            side_emoji = f"🔴 {actual_outcome}"
        else:
            side_emoji = actual_outcome
        balance_display = f"💵 **Your USDC.e Balance:** ${usdc_balance:.2f}" if usdc_balance is not None else "💵 **Balance unavailable**"

        message = f"""
**Confirm Order**

Market: {market.get('title', 'Unknown Market')[:50]}...

**Details:**
• Side: {side_emoji}
• Amount: ${amount:.2f}
• Current Price: ${current_price:.4f}
• Est. Tokens: ~{estimated_tokens}

{balance_display}

⚠️ *This will execute immediately using your wallet*
""".strip()

        # Confirmation buttons
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm Buy", callback_data=f"confirm_order_{market_id}_{outcome}_{amount}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"market_select_{market_id}_0")
            ]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in buy amount callback: {e}")
        await query.edit_message_text("❌ Error processing buy amount")


async def handle_custom_buy_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle custom buy callback - show outcome selection first
    Format: "custom_buy_{market_id}"
    """
    try:
        # Parse: "custom_buy_{market_id}"
        parts = callback_data.split("_")
        market_id = "_".join(parts[2:])  # Handle market IDs with underscores

        # Get market details (via API or DB)
        market = await get_market_data(market_id, context)

        if not market:
            await query.answer("Market not found", show_alert=True)
            return

        # Store context
        context.user_data['custom_buy_market_id'] = market_id

        # Get outcomes dynamically
        outcomes = market.get('outcomes', ['YES', 'NO'])

        # Show outcome selection
        message = f"💵 **Custom Buy**\n\nMarket: {market.get('title', 'Unknown')[:50]}...\n\nChoose which side to buy:"

        # Build buttons dynamically based on outcomes (use first 2)
        outcome_buttons = []
        if len(outcomes) >= 2:
            outcome0 = outcomes[0]
            outcome1 = outcomes[1]
            outcome_buttons.append(InlineKeyboardButton(f"🟢 Buy {outcome0}", callback_data=f"custom_buy_{outcome0}_{market_id}"))
            outcome_buttons.append(InlineKeyboardButton(f"🔴 Buy {outcome1}", callback_data=f"custom_buy_{outcome1}_{market_id}"))
        elif len(outcomes) >= 1:
            outcome0 = outcomes[0]
            outcome_buttons.append(InlineKeyboardButton(f"🟢 Buy {outcome0}", callback_data=f"custom_buy_{outcome0}_{market_id}"))
        else:
            # Fallback to YES/NO if no outcomes
            outcome_buttons.append(InlineKeyboardButton("🟢 Buy YES", callback_data=f"custom_buy_Yes_{market_id}"))
            outcome_buttons.append(InlineKeyboardButton("🔴 Buy NO", callback_data=f"custom_buy_No_{market_id}"))

        keyboard = [
            outcome_buttons,
            [InlineKeyboardButton("← Back", callback_data=f"market_select_{market_id}_0")]
        ]

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in custom buy callback: {e}")
        await query.edit_message_text("❌ Error processing custom buy request")


async def handle_custom_buy_outcome_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle custom buy outcome selection - prompt for amount
    Format: "custom_buy_{outcome}_{market_id}" where outcome can be any outcome (Yes, No, Up, Down, etc.)
    """
    try:
        logger.info(f"🎯 CUSTOM BUY OUTCOME CALLBACK: {callback_data}")

        # Parse: "custom_buy_{outcome}_{market_id}"
        # Note: outcome is at index 2, market_id is everything after
        parts = callback_data.split("_")
        outcome = parts[2]  # Can be "Yes", "No", "Up", "Down", etc.
        market_id = "_".join(parts[3:])  # Handle market IDs with underscores

        logger.info(f"📊 Parsed: outcome={outcome}, market_id={market_id}")

        # Get user's USDC.e balance via API
        telegram_user_id = query.from_user.id
        user_data = await get_user_data(telegram_user_id)
        usdc_balance = None

        if user_data:
            try:
                api_client = get_api_client()
                internal_id = user_data.get('id')
                if internal_id:
                    balance_data = await api_client.get_wallet_balance(internal_id)
                    if balance_data:
                        usdc_balance = balance_data.get('usdc_balance')
            except Exception as e:
                logger.warning(f"Could not fetch USDC.e balance: {e}")

        # Store context
        context.user_data['custom_buy_market_id'] = market_id
        context.user_data['custom_buy_outcome'] = outcome
        context.user_data['awaiting_custom_amount'] = True

        logger.info(f"✅ Context set: {context.user_data}")

        balance_display = f"💵 **Your USDC.e Balance:** ${usdc_balance:.2f}" if usdc_balance is not None else "💵 **Balance unavailable**"

        # Send NEW message for custom amount input
        await query.message.reply_text(
            f"💵 **Custom Buy - {outcome}**\n\n"
            f"{balance_display}\n\n"
            "Enter the amount in USDC you want to invest:\n"
            "(Example: 25.50)",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in custom buy outcome callback: {e}")
        await query.message.reply_text("❌ Error processing custom buy request")


async def handle_custom_buy_amount_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle custom buy with pre-selected outcome - prompt for amount
    Format: "custom_buy_amount_{market_id}_{outcome}"
    """
    try:
        # Parse: "custom_buy_amount_{market_id}_{outcome}"
        parts = callback_data.split("_")
        market_id = "_".join(parts[3:-1])  # Handle market IDs with underscores
        outcome = parts[-1]  # Can be any outcome (Yes, No, Up, Down, etc.)

        # Store context
        context.user_data['custom_buy_market_id'] = market_id
        context.user_data['custom_buy_outcome'] = outcome
        context.user_data['awaiting_custom_amount'] = True

        # Send NEW message for custom amount input
        await query.message.reply_text(
            f"💵 **Custom Buy - {outcome}**\n\n"
            "Enter the amount in USDC you want to invest:\n"
            "(Example: 25.50)",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in custom buy amount callback: {e}")
        await query.message.reply_text("❌ Error processing custom buy request")


async def handle_confirm_order_callback(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: str
) -> None:
    """
    Handle order confirmation and execute trade
    Format: "confirm_order_{market_id}_{outcome}_{amount}"
    """
    try:
        # Parse: "confirm_order_{market_id}_{outcome}_{amount}"
        parts = callback_data.split("_")
        market_id = "_".join(parts[2:-2])  # Handle market IDs with underscores
        outcome = parts[-2]
        amount_usd = float(parts[-1])

        user_id = query.from_user.id

        # Send NEW message showing execution in progress
        await query.message.reply_text(
            "⚡ **Executing trade...**\n\n"
            "Please wait while your order is being processed.\n"
            "This may take a few seconds.",
            parse_mode='Markdown'
        )

        # Get market title for display (via API or DB)
        market = await get_market_data(market_id, context)
        market_title = market.get('title', market_id) if market else market_id

        # Execute trade using TradeService
        # Message still shows "Executing..." during order execution, position creation, and sync
        from core.services.trading.trade_service import trade_service
        result = await trade_service.execute_market_order(
            user_id=user_id,
            market_id=market_id,
            outcome=outcome,
            amount_usd=amount_usd,
            order_type='FOK'  # Fill-or-Kill
        )

        # Handle different result formats from TradeService
        if result.get('success') or result.get('status') == 'executed':
            # Trade successful - handle both result formats

            # Extract trade data based on result format
            if 'trade' in result:
                # Old format: result['trade'] contains the trade data
                trade_data = result['trade']
                tokens = trade_data.get('tokens', 0)  # Shares received
                usd_price_per_share = trade_data.get('usd_price_per_share')  # USD price per share for display
                price = trade_data.get('price', 0)  # Polymarket price (fallback)
                usd_spent = trade_data.get('usd_spent', amount_usd)  # USD actually spent
                tx_hash = trade_data.get('tx_hash')
            else:
                # New format: trade data is directly in result
                tokens = result.get('tokens', 0)  # Shares received
                usd_price_per_share = result.get('usd_price_per_share')  # USD price per share for display
                price = result.get('price', 0)  # Polymarket price (fallback)
                usd_spent = result.get('usd_spent', amount_usd)  # USD actually spent
                tx_hash = result.get('tx_hash')

            # Use USD price per share for display, or calculate it if not available
            if usd_price_per_share is None and tokens > 0 and usd_spent > 0:
                usd_price_per_share = usd_spent / tokens
            elif usd_price_per_share is None:
                usd_price_per_share = price  # Fallback to Polymarket price if calculation not possible

            # All operations complete - NOW update message with success result
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
                [InlineKeyboardButton("📈 View Market", callback_data=f"market_select_{market_id}_0")]
            ]

            # Send NEW message with final result
            await query.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        else:
            # Trade failed
            error_msg = result.get('error') or 'Unknown error'
            await query.message.reply_text(
                f"❌ Order failed: {error_msg}\n\n"
                "Please try again or contact support."
            )

    except Exception as e:
        logger.error(f"Error in confirm order callback: {e}")
        await query.message.reply_text("❌ An error occurred during execution. Please try again.")


async def handle_custom_amount_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    amount_text: str
) -> None:
    """
    Handle custom amount input for buy order
    """
    try:
        user_id = update.effective_user.id
        logger.info(f"🔢 CUSTOM AMOUNT INPUT CALLED: '{amount_text}' for user {user_id}")
        logger.info(f"🔢 Context: {context.user_data}")

        # Keep context data (don't pop yet)
        market_id = context.user_data.get('custom_buy_market_id')
        outcome = context.user_data.get('custom_buy_outcome')

        if not market_id or not outcome:
            logger.warning(f"Missing context data for user {user_id}")
            # Clear flag and show error
            context.user_data.pop('awaiting_custom_amount', None)
            await update.message.reply_text("❌ Session expired. Please start over.")
            return

        # Parse amount
        try:
            amount = float(amount_text.strip())
            if amount <= 0:
                raise ValueError("Amount must be positive")
            if amount > 10000:  # Reasonable upper limit
                raise ValueError("Amount too large (max $10,000)")
        except ValueError as e:
            logger.warning(f"Invalid amount '{amount_text}' for user {user_id}: {e}")
            # Keep the awaiting flag so user can try again
            await update.message.reply_text(
                f"❌ Invalid amount: {e}\n\nPlease enter a number between $0.01 and $10,000 (e.g., 25.50)"
            )
            return

        logger.info(f"✅ Valid amount ${amount:.2f} for market {market_id}, outcome {outcome}")

        # Clear flag now that we have valid input
        context.user_data.pop('awaiting_custom_amount', None)

        # Get market and price (via API or DB)
        market = await get_market_data(market_id, context)

        if not market:
            logger.error(f"Market {market_id} not found for user {user_id}")
            await update.message.reply_text("❌ Market not found")
            return

        # Get price
        outcome_prices = market.get('outcome_prices', [])
        outcomes = market.get('outcomes', ['YES', 'NO'])

        try:
            # Use intelligent outcome normalization
            outcome_index = find_outcome_index(outcome, outcomes)
            if outcome_index is not None and outcome_index < len(outcome_prices):
                price = float(outcome_prices[outcome_index])
            else:
                logger.warning(f"⚠️ Could not find price for outcome '{outcome}' in market {market_id}, using fallback 0.5")
                price = 0.5
        except (IndexError, ValueError, TypeError) as e:
            logger.warning(f"Price lookup error for market {market_id}: {e}, using fallback 0.5")
            price = 0.5

        logger.info(f"📊 Market price: ${price:.4f} for outcome {outcome}")

        # Calculate estimated shares
        estimated_shares = int(amount / price) if price > 0 else 0

        # Build confirmation message - use actual outcome from market
        outcomes = market.get('outcomes', ['YES', 'NO'])
        outcome_upper = outcome.upper()
        # Find matching outcome to preserve original case
        actual_outcome = outcome  # Default to passed outcome
        for o in outcomes:
            if o.upper() == outcome_upper:
                actual_outcome = o
                break

        # Use emoji based on position (first outcome = green, second = red)
        if len(outcomes) >= 2 and outcomes[0].upper() == outcome_upper:
            side_display = f"🟢 {actual_outcome}"
        elif len(outcomes) >= 2 and outcomes[1].upper() == outcome_upper:
            side_display = f"🔴 {actual_outcome}"
        else:
            side_display = actual_outcome

        message = f"🎯 **Confirm Your Order**\n\n"
        message += f"Market: {market['title'][:60]}...\n"
        message += f"Side: {side_display}\n"
        message += f"Amount: ${amount:.2f}\n"
        message += f"Price: ${price:.4f} per share\n"
        message += f"Estimated Shares: ~{estimated_shares}\n\n"

        # Check balance via API (optional - don't fail if we can't get it)
        try:
            telegram_user_id = update.effective_user.id
            user_data = await get_user_data(telegram_user_id)

            if user_data:
                api_client = get_api_client()
                internal_id = user_data.get('id')
                if internal_id:
                    balance_data = await api_client.get_wallet_balance(internal_id)
                    if balance_data:
                        balance = balance_data.get('usdc_balance', 0)
                        if balance is not None and balance < amount:
                            logger.warning(f"Insufficient balance for user {user_id}: ${balance:.2f} < ${amount:.2f}")
                            await update.message.reply_text(
                                f"❌ **Insufficient Balance**\n\n"
                                f"💰 Required: ${amount:.2f}\n"
                                f"💼 Your Balance: ${balance:.2f}\n\n"
                                f"Please fund your wallet with /wallet",
                                parse_mode='Markdown'
                            )
                            return
                        message += f"💼 Balance: ${balance:.2f}\n\n"
        except Exception as e:
            logger.warning(f"Could not check balance for user {user_id}: {e}")
            # Continue anyway - balance check is not critical

        message += "Proceed?"

        # Build keyboard
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_order_{market_id}_{outcome}_{amount}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"market_select_{market_id}_0")
            ]
        ]

        logger.info(f"📤 Sending confirmation message for user {user_id}")
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling custom amount input for user {update.effective_user.id}: {e}")
        # Clear flag on error
        context.user_data.pop('awaiting_custom_amount', None)
        await update.message.reply_text("❌ Error processing custom amount. Please try again.")
