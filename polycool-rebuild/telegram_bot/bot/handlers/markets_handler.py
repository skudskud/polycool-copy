"""
Markets command handler
Handles /markets command and routes callbacks to specialized modules
"""
import os
from telegram import Update
from telegram.ext import ContextTypes

# Import functions dynamically to avoid circular imports
from telegram_bot.bot.handlers.markets.hub import get_hub_message, build_hub_keyboard
from core.services.market.market_helper import get_market_data
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_markets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /markets command - Show markets hub
    """
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    try:
        logger.info(f"📊 /markets command - User {user_id}")

        # Clear any previous search/category context
        if context.user_data:
            context.user_data.pop('last_search_query', None)
            context.user_data.pop('last_category', None)

        # Build hub message and keyboard
        from telegram import InlineKeyboardMarkup
        message = get_hub_message()
        keyboard = build_hub_keyboard()

        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

        logger.info(f"✅ Market hub displayed for user {user_id}")

    except Exception as e:
        logger.error(f"Error in markets handler for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ An error occurred. Please try again."
        )


async def handle_market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle market callback queries
    Routes to appropriate handler based on callback data pattern
    """
    if not update.callback_query:
        return

    callback_data = update.callback_query.data
    logger.info(f"📨 MARKET CALLBACK: {callback_data}")

    query = update.callback_query
    user_id = query.from_user.id

    try:
        await query.answer()

        # Route callbacks based on pattern
        if callback_data == "markets_hub":
            from telegram_bot.bot.handlers.markets.hub import get_hub_message, build_hub_keyboard
            from telegram import InlineKeyboardMarkup
            message = get_hub_message()
            keyboard = build_hub_keyboard()
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

        elif callback_data.startswith("trending_markets_"):
            await _handle_trending_callback(query, context, callback_data, user_id)
        elif callback_data.startswith("cat_"):
            from telegram_bot.bot.handlers.markets.categories import handle_category_callback
            await handle_category_callback(query, context, callback_data)
        elif callback_data.startswith("catfilter_"):
            from telegram_bot.bot.handlers.markets.categories import handle_category_filter_callback
            await handle_category_filter_callback(query, context, callback_data)
        elif callback_data.startswith("filter_"):
            await _handle_filter_callback(query, context, callback_data)
        elif callback_data.startswith("market_select_"):
            await _handle_market_select_callback(query, context, callback_data)
        elif callback_data.startswith("event_select_"):
            await _handle_event_select_callback(query, context, callback_data)
        elif callback_data == "trigger_search":
            from telegram_bot.bot.handlers.markets.search import handle_search_trigger
            await handle_search_trigger(query, context)
        elif callback_data.startswith("search_page_"):
            from telegram_bot.bot.handlers.markets.search import handle_search_page_callback
            await handle_search_page_callback(query, context, callback_data)
        elif callback_data.startswith("quick_buy_"):
            from telegram_bot.bot.handlers.markets.trading import handle_quick_buy_callback
            await handle_quick_buy_callback(query, context, callback_data)
        elif callback_data.startswith("buy_amount_"):
            from telegram_bot.bot.handlers.markets.trading import handle_buy_amount_callback
            await handle_buy_amount_callback(query, context, callback_data)
        elif callback_data.startswith("custom_buy_amount_"):
            from telegram_bot.bot.handlers.markets.trading import handle_custom_buy_amount_callback
            await handle_custom_buy_amount_callback(query, context, callback_data)
        elif callback_data.startswith("custom_buy_") and callback_data.count("_") >= 3:
            # Handle dynamic outcomes: "custom_buy_{outcome}_{market_id}"
            # Check if it's an outcome selection (has at least 3 underscores)
            from telegram_bot.bot.handlers.markets.trading import handle_custom_buy_outcome_callback
            await handle_custom_buy_outcome_callback(query, context, callback_data)
        elif callback_data.startswith("custom_buy_"):
            from telegram_bot.bot.handlers.markets.trading import handle_custom_buy_callback
            await handle_custom_buy_callback(query, context, callback_data)
        elif callback_data.startswith("confirm_order_"):
            from telegram_bot.bot.handlers.markets.trading import handle_confirm_order_callback
            await handle_confirm_order_callback(query, context, callback_data)
        elif callback_data.startswith("refresh_prices_"):
            await _handle_refresh_prices_callback(query, context, callback_data)
        else:
            logger.warning(f"Unknown callback: {callback_data}")
            await query.edit_message_text("❌ Unknown action")

    except Exception as e:
        logger.error(f"Error handling market callback for user {user_id}: {e}")
        if query.message:
            await query.edit_message_text("❌ An error occurred. Please try again.")

async def handle_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle search message when user types search query
    """
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    logger.info(f"📨 Markets Message handler called for user {user_id}: '{text}'")
    logger.info(f"📊 Context awaiting_custom_amount: {context.user_data.get('awaiting_custom_amount', False)}")
    logger.info(f"📊 Context keys: {list(context.user_data.keys())}")

    # Check if we're waiting for custom buy amount - SIMPLE APPROACH like old code
    if context.user_data.get('awaiting_custom_amount'):
        logger.info(f"✅ Processing custom amount input for user {user_id}: '{text}'")

        # Parse amount (same logic as old code)
        try:
            # Remove $ and commas
            clean_text = text.replace('$', '').replace(',', '').strip()
            amount = float(clean_text)

            if amount <= 0:
                await update.message.reply_text("❌ Amount must be greater than 0. Try again or /cancel")
                return

            if amount > 10000:
                await update.message.reply_text("❌ Amount too large. Maximum $10,000 per order. Try again or /cancel")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a number (e.g., 25.50)")
            return

        # Get context data
        market_id = context.user_data.get('custom_buy_market_id')
        outcome = context.user_data.get('custom_buy_outcome')

        if not market_id or not outcome:
            context.user_data.pop('awaiting_custom_amount', None)
            await update.message.reply_text("❌ Session expired. Please start over.")
            return

        # Clear flag
        context.user_data.pop('awaiting_custom_amount', None)

        # Get market and show confirmation (same as old code logic)
        cache_manager = None
        if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
            cache_manager = context.bot.application.bot_data.get('cache_manager')

        from core.services.api_client import get_api_client
        api_client = get_api_client()
        market = await api_client.get_market(market_id)

        if not market:
            await update.message.reply_text("❌ Market not found")
            return

        # Get price
        outcome_prices = market.get('outcome_prices', [])
        outcomes = market.get('outcomes', ['YES', 'NO'])

        try:
            outcome_index = outcomes.index(outcome) if outcome in outcomes else 0
            price = float(outcome_prices[outcome_index]) if outcome_index < len(outcome_prices) else 0.5
        except (IndexError, ValueError, TypeError):
            price = 0.5

        # Calculate estimated shares
        estimated_shares = int(amount / price) if price > 0 else 0

        # Build confirmation message (same format as old code)
        side_emoji = "✅ YES" if outcome == "Yes" else "❌ NO"
        message_text = f"🎯 **Confirm Your Order**\n\n"
        message_text += f"Market: {market['title'][:60]}...\n"
        message_text += f"Side: {side_emoji}\n"
        message_text += f"Amount: ${amount:.2f}\n"
        message_text += f"Price: ${price:.4f} per share\n"
        message_text += f"Estimated Shares: ~{estimated_shares}\n\n"
        message_text += "Proceed?"

        # Build keyboard (same as old code)
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_order_{market_id}_{outcome}_{amount}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"market_select_{market_id}_0")
            ]
        ]

        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    # Check if we're waiting for TP/SL price input
    if context.user_data.get('awaiting_tpsl_price'):
        logger.info(f"✅ Processing TP/SL price input for user {user_id}: '{text}'")

        # Import TP/SL handler
        from telegram_bot.bot.handlers.positions.tpsl_handler import handle_tpsl_price_input

        await handle_tpsl_price_input(update, context, text)
        return

    # Check if we're waiting for custom sell amount
    if context.user_data.get('awaiting_sell_amount'):
        logger.info(f"✅ Processing custom sell amount input for user {user_id}: '{text}'")

        # Import sell handler
        from telegram_bot.bot.handlers.positions.sell_handler import handle_custom_sell_amount_input

        await handle_custom_sell_amount_input(update, context, text)
        return

    # Delegate to search module
    from telegram_bot.bot.handlers.markets.search import handle_search_message
    await handle_search_message(update, context)


# Temporary functions - will be moved to appropriate modules later
async def _handle_trending_callback(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str, user_id: int) -> None:
    """Handle trending markets callback"""
    try:
        # Parse page from callback_data: "trending_markets_0"
        page = int(callback_data.split("_")[-1])

        # Use API client in SKIP_DB mode
        markets = None

        if SKIP_DB:
            api_client = get_api_client()

            # Try up to 2 times with a short delay
            total_count = None
            for attempt in range(2):
                markets = await api_client.get_trending_markets(page=page, page_size=9, group_by_events=True, filter_type=None)
                if markets is not None:
                    # Try to get total_count from cache (same key for all pages)
                    if api_client.cache_manager:
                        total_count_key = "api:markets:trending:total_count:true:none"
                        total_count = await api_client.cache_manager.get(total_count_key, 'metadata')
                    break
                if attempt < 1:  # Don't wait after last attempt
                    import asyncio
                    await asyncio.sleep(1)  # Wait 1 second before retry
        else:
            # Get cache manager
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            from core.services.market_service import get_market_service
            market_service = get_market_service(cache_manager=cache_manager)
            markets, _ = await market_service.get_trending_markets(page=page, page_size=9, group_by_events=True, filter_type=None)

        if not markets:
            # More helpful error message for API issues
            if SKIP_DB:
                await query.edit_message_text(
                    "⚠️ **Loading markets...**\n\n"
                    "Markets are being loaded. Please try again in a few seconds.\n\n"
                    "If this persists, the market data service may be temporarily unavailable.",
                    reply_markup=None
                )
            else:
                await query.edit_message_text("❌ No trending markets found")
            return

        from telegram_bot.bot.handlers.markets.formatters import build_markets_list_ui
        from telegram import InlineKeyboardMarkup

        # Use total_count if available for accurate pagination
        message_text, keyboard = build_markets_list_ui(
            markets=markets,
            page=page,
            view_type='trending',
            filter_type='volume',
            total_count=total_count
        )

        # Check if message content has actually changed to avoid Telegram error
        try:
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as edit_error:
            # If message content is the same, Telegram returns "Message is not modified"
            # In this case, we just acknowledge the callback without changing anything
            if "Message is not modified" in str(edit_error):
                logger.info("Trending callback: message content unchanged, skipping edit")
                # Don't show error to user, just acknowledge
                pass
            else:
                # Re-raise other errors
                raise edit_error

    except Exception as e:
        logger.error(f"Error in trending callback: {e}")
        await query.edit_message_text("❌ Error loading trending markets")


async def _handle_filter_callback(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle filter callback for trending markets"""
    try:
        # Parse: "filter__volume_0" or "catfilter_category_volume_0"
        parts = callback_data.split("_")
        if parts[0] == "catfilter":
            # Format: "catfilter_category_volume_0"
            category = parts[1]
            filter_type = parts[2]
            page = int(parts[3])
        else:
            # Format: "filter__volume_0" (trending with empty context)
            # Skip empty parts from double underscores
            filtered_parts = [p for p in parts[1:] if p]  # Remove empty strings
            filter_type = filtered_parts[0]
            page = int(filtered_parts[1])

        # Use API client in SKIP_DB mode
        if SKIP_DB:
            api_client = get_api_client()
            markets = await api_client.get_trending_markets(page=page, page_size=9, group_by_events=True, filter_type=filter_type)
        else:
            # Get cache manager
            cache_manager = None
            if hasattr(context.bot, 'application') and hasattr(context.bot.application, 'bot_data'):
                cache_manager = context.bot.application.bot_data.get('cache_manager')

            from core.services.market_service import get_market_service
            market_service = get_market_service(cache_manager=cache_manager)
            markets, _ = await market_service.get_trending_markets(page=page, page_size=9, group_by_events=True, filter_type=filter_type)

        if not markets:
            await query.edit_message_text("❌ No markets found")
            return

        from telegram_bot.bot.handlers.markets.formatters import build_markets_list_ui
        from telegram import InlineKeyboardMarkup
        message_text, keyboard = build_markets_list_ui(
            markets=markets,
            page=page,
            view_type='trending',
            filter_type=filter_type
        )

        # Check if message content has actually changed to avoid Telegram error
        try:
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as edit_error:
            # If message content is the same, Telegram returns "Message is not modified"
            # In this case, we just acknowledge the callback without changing anything
            if "Message is not modified" in str(edit_error):
                logger.info("Filter callback: message content unchanged, skipping edit")
                # Don't show error to user, just acknowledge
                pass
            else:
                # Re-raise other errors
                raise edit_error

    except Exception as e:
        logger.error(f"Error in filter callback: {e}")
        await query.edit_message_text("❌ Error loading markets")


async def _handle_market_select_callback(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle market selection callback - show market details"""
    try:
        # Parse: "market_select_{market_id}_{page}"
        parts = callback_data.split("_")
        market_id = "_".join(parts[2:-1])  # Handle market IDs with underscores
        page = int(parts[-1])

        # Get market (via API or DB)
        market = await get_market_data(market_id, context)

        if not market:
            await query.edit_message_text("❌ Market not found")
            return

        # Build market detail view with prices and trading buttons
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram_bot.bot.handlers.markets.formatters import format_end_date

        message = f"**{market['title']}**\n\n"
        if market.get('description'):
            message += f"{market['description'][:200]}...\n\n"

        # Format volume and liquidity safely
        volume = market.get('volume', 0)
        liquidity = market.get('liquidity', 0)
        try:
            message += f"📊 Volume: ${float(volume):,.0f}\n"
            message += f"💧 Liquidity: ${float(liquidity):,.0f}\n\n"
        except (ValueError, TypeError):
            message += f"📊 Volume: ${volume}\n"
            message += f"💧 Liquidity: ${liquidity}\n\n"

        # Show current prices for each outcome
        message += "**Current Prices:**\n"
        if market.get('outcome_prices') and market.get('outcomes'):
            prices = market['outcome_prices']
            outcomes = market['outcomes']
            if len(prices) >= len(outcomes):
                for i, outcome in enumerate(outcomes):
                    try:
                        price = float(prices[i]) if i < len(prices) else 0.0
                        probability = price * 100
                        message += f"  {outcome}: ${price:.4f} ({probability:.1f}%)\n"
                    except (ValueError, TypeError, IndexError):
                        price = prices[i] if i < len(prices) else "N/A"
                        message += f"  {outcome}: ${price}\n"
            elif len(prices) == 0 and len(outcomes) >= 2:
                # Handle markets with no price data yet
                message += f"  {outcomes[0]} vs {outcomes[1]} (prices pending)\n"
            else:
                message += "  Prices unavailable\n"
        else:
            message += "  No price data available\n"
        message += "\n"

        if market.get('end_date'):
            message += f"⏰ Ends: {format_end_date(market['end_date'])}\n\n"

        # Check if prices are available
        has_prices = market.get('outcome_prices') and market.get('outcomes') and len(market.get('outcome_prices', [])) > 0

        # Build keyboard with trading buttons
        keyboard = []

        if has_prices:
            # Show trading buttons if prices are available - use dynamic outcomes
            outcomes = market.get('outcomes', ['YES', 'NO'])
            # Use first 2 outcomes
            if len(outcomes) >= 2:
                outcome0 = outcomes[0]
                outcome1 = outcomes[1]
                keyboard.append([InlineKeyboardButton(f"🟢 Buy {outcome0}", callback_data=f"quick_buy_{market_id}_{outcome0}")])
                keyboard.append([InlineKeyboardButton(f"🔴 Buy {outcome1}", callback_data=f"quick_buy_{market_id}_{outcome1}")])
            elif len(outcomes) >= 1:
                # Fallback if only one outcome
                outcome0 = outcomes[0]
                keyboard.append([InlineKeyboardButton(f"🟢 Buy {outcome0}", callback_data=f"quick_buy_{market_id}_{outcome0}")])
            else:
                # Fallback to YES/NO if no outcomes
                keyboard.append([InlineKeyboardButton("🟢 Buy YES", callback_data=f"quick_buy_{market_id}_Yes")])
                keyboard.append([InlineKeyboardButton("🔴 Buy NO", callback_data=f"quick_buy_{market_id}_No")])
        else:
            # Show refresh button if prices are not available
            keyboard.append([InlineKeyboardButton("🔄 Refresh Prices", callback_data=f"refresh_prices_{market_id}_{page}")])

        # Always show back button
        keyboard.append([InlineKeyboardButton("← Back", callback_data=f"trending_markets_{page}")])

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in market select callback: {e}")
        await query.edit_message_text("❌ Error loading market details")


async def _handle_refresh_prices_callback(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle refresh prices callback - fetch fresh data from Polymarket"""
    try:
        # Parse: "refresh_prices_{market_id}_{page}"
        parts = callback_data.split("_")
        market_id = "_".join(parts[2:-1])  # Handle market IDs with underscores
        page = int(parts[-1])

        await query.answer("🔄 Refreshing prices...")

        # Use API client to fetch fresh data
        if SKIP_DB:
            api_client = get_api_client()

            # Fetch fresh market data
            fresh_market = await api_client.fetch_market_on_demand(market_id)

            if not fresh_market:
                await query.edit_message_text("❌ Failed to refresh market data. Please try again.")
                return

            market = fresh_market
        else:
            # In DB mode, we shouldn't need refresh since data should be current
            await query.edit_message_text("❌ Refresh not available in this mode.")
            return

        # Rebuild market detail view with fresh data
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram_bot.bot.handlers.markets.formatters import format_end_date

        message = f"**{market['title']}**\n\n"
        if market.get('description'):
            message += f"{market['description'][:200]}...\n\n"

        # Format volume and liquidity safely
        volume = market.get('volume', 0)
        liquidity = market.get('liquidity', 0)
        try:
            message += f"📊 Volume: ${float(volume):,.0f}\n"
            message += f"💧 Liquidity: ${float(liquidity):,.0f}\n\n"
        except (ValueError, TypeError):
            message += f"📊 Volume: ${volume}\n"
            message += f"💧 Liquidity: ${liquidity}\n\n"

        # Show current prices for each outcome
        message += "**Current Prices:**\n"
        if market.get('outcome_prices') and market.get('outcomes'):
            prices = market['outcome_prices']
            outcomes = market['outcomes']
            if len(prices) >= len(outcomes):
                for i, outcome in enumerate(outcomes):
                    try:
                        price = float(prices[i]) if i < len(prices) else 0.0
                        probability = price * 100
                        message += f"  {outcome}: ${price:.4f} ({probability:.1f}%)\n"
                    except (ValueError, TypeError, IndexError):
                        price = prices[i] if i < len(prices) else "N/A"
                        message += f"  {outcome}: ${price}\n"
            elif len(prices) == 0 and len(outcomes) >= 2:
                # Handle markets with no price data yet
                message += f"  {outcomes[0]} vs {outcomes[1]} (prices pending)\n"
            else:
                message += "  Prices unavailable\n"
        else:
            message += "  No price data available\n"
        message += "\n"

        if market.get('end_date'):
            message += f"⏰ Ends: {format_end_date(market['end_date'])}\n\n"

        # Check if prices are now available after refresh
        has_prices = market.get('outcome_prices') and market.get('outcomes') and len(market.get('outcome_prices', [])) > 0

        # Build keyboard with trading buttons
        keyboard = []

        if has_prices:
            # Show trading buttons if prices are available - use dynamic outcomes
            outcomes = market.get('outcomes', ['YES', 'NO'])
            # Use first 2 outcomes
            if len(outcomes) >= 2:
                outcome0 = outcomes[0]
                outcome1 = outcomes[1]
                keyboard.append([InlineKeyboardButton(f"🟢 Buy {outcome0}", callback_data=f"quick_buy_{market_id}_{outcome0}")])
                keyboard.append([InlineKeyboardButton(f"🔴 Buy {outcome1}", callback_data=f"quick_buy_{market_id}_{outcome1}")])
            elif len(outcomes) >= 1:
                # Fallback if only one outcome
                outcome0 = outcomes[0]
                keyboard.append([InlineKeyboardButton(f"🟢 Buy {outcome0}", callback_data=f"quick_buy_{market_id}_{outcome0}")])
            else:
                # Fallback to YES/NO if no outcomes
                keyboard.append([InlineKeyboardButton("🟢 Buy YES", callback_data=f"quick_buy_{market_id}_Yes")])
                keyboard.append([InlineKeyboardButton("🔴 Buy NO", callback_data=f"quick_buy_{market_id}_No")])
        else:
            # Show refresh button again if still no prices
            keyboard.append([InlineKeyboardButton("🔄 Refresh Prices", callback_data=f"refresh_prices_{market_id}_{page}")])

        # Always show back button
        keyboard.append([InlineKeyboardButton("← Back", callback_data=f"trending_markets_{page}")])

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in refresh prices callback: {e}")
        await query.edit_message_text("❌ Error refreshing prices. Please try again.")


async def _handle_event_select_callback(query, context: ContextTypes.DEFAULT_TYPE, callback_data: str) -> None:
    """Handle event selection callback - show markets in event"""
    try:
        # Parse: "event_select_{page}_{event_id}"
        # Updated to use event_id instead of encoded event_title to avoid 64-byte limit
        if not callback_data.startswith("event_select_"):
            await query.edit_message_text("❌ Invalid callback data format")
            return

        # Extract page and event_id
        # Format: "event_select_{page}_{event_id}"
        # Note: page here is the event page number (0-based)
        parts = callback_data.replace("event_select_", "", 1).split("_", 1)
        if len(parts) != 2:
            await query.edit_message_text("❌ Invalid callback data format")
            return

        page = int(parts[0])
        event_id = parts[1]

        # Use API to get markets by event_id
        if SKIP_DB:
            api_client = get_api_client()
            # Use event_id endpoint (more reliable than title)
            # Note: Include page and page_size in cache key to avoid stale cache
            # Use dedicated method that handles caching properly
            event_response = await api_client.get_event_markets(event_id, page=page, page_size=12)

            # Handle response (get_event_markets returns dict with pagination info or None)
            if event_response is None:
                event_markets = []
                total_count = 0
                has_more_pages = False
            else:
                event_markets = event_response.get('markets', [])
                total_count = event_response.get('total_count', 0)
                has_more_pages = event_response.get('has_more_pages', False)

            logger.info(f"✅ Got {len(event_markets)} markets from API for event {event_id} (total: {total_count}, has_more: {has_more_pages})")

            # Get event title from trending markets if needed
            event_title = None
            if event_markets and len(event_markets) > 0:
                # Get title from first market's event_title
                event_title = event_markets[0].get('event_title')
            else:
                # Fallback: get from trending markets
                trending = await api_client.get_trending_markets(page=0, page_size=50, group_by_events=True)
                if trending:
                    for item in trending:
                        if item.get('type') == 'event_group' and str(item.get('event_id')) == str(event_id):
                            event_title = item.get('event_title', f'Event {event_id}')
                            break
        else:
            # Fallback for non-SKIP_DB mode
            await query.edit_message_text("❌ Event selection not available in this mode.")
            return

        # Check if we have markets (handle both None and empty list)
        if not event_markets or (isinstance(event_markets, list) and len(event_markets) == 0):
            event_title_display = event_title or f"Event {event_id}"
            await query.edit_message_text(f"❌ No markets found for event: {event_title_display}")
            return

        # API already filters out invalid markets, so use the results directly
        filtered_markets = event_markets

        # Get event_title from first market (should be consistent across all markets in event)
        if not event_title and filtered_markets:
            event_title = filtered_markets[0].get('event_title')

        # Fallback: try to get from trending markets
        if not event_title and SKIP_DB:
            try:
                trending = await api_client.get_trending_markets(page=0, page_size=50, group_by_events=True)
                if trending:
                    for item in trending:
                        if item.get('type') == 'event_group' and str(item.get('event_id')) == str(event_id):
                            event_title = item.get('event_title', f'Event {event_id}')
                            break
            except Exception:
                pass  # If we can't get trending, use fallback

        # Final fallback
        event_title = event_title or f'Event {event_id}'

        # UX Optimization: If this is a standalone market (single market event), redirect directly to market details
        if len(filtered_markets) == 1 and page == 0 and total_count == 1:
            single_market = filtered_markets[0]
            market_id = single_market.get('id')
            if market_id:
                logger.info(f"🎯 Redirecting standalone market {market_id} directly to trading details")
                # Simulate market select callback
                await _handle_market_select_callback(query, context, f"market_select_{market_id}_0")
                return

        # Build event markets list
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from datetime import datetime, timezone

        # Use pagination info from API response
        display_markets = filtered_markets

        message = f"**{event_title}**\n\n"

        # Show pagination info
        current_page_count = len(display_markets)
        if has_more_pages:
            message += f"Showing {page * 12 + 1}-{page * 12 + current_page_count} (page {page + 1})\n\n"
        else:
            message += f"Showing {page * 12 + 1}-{page * 12 + current_page_count} of {total_count} markets\n\n"

        # Display markets with numbers, full title, and stored info
        for i, market in enumerate(display_markets, start=1):
            title = market.get('title', 'Unknown')
            # Show full title (no truncation)
            message += f"{i}. **{title}**\n"

            # Show stored info: volume and prices if available
            volume = market.get('volume', 0)
            if volume:
                try:
                    volume_float = float(volume)
                    if volume_float >= 1_000_000:
                        volume_str = f"${volume_float/1_000_000:.1f}M"
                    elif volume_float >= 1_000:
                        volume_str = f"${volume_float/1_000:.1f}K"
                    else:
                        volume_str = f"${volume_float:,.0f}"
                    message += f"   💰 Vol: {volume_str}"
                except (ValueError, TypeError):
                    message += f"   💰 Vol: ${volume}"

            # Show prices if available and fresh (< 20 minutes)
            outcome_prices = market.get('outcome_prices', [])
            outcomes = market.get('outcomes', [])
            updated_at = market.get('updated_at')

            if outcome_prices and outcomes and len(outcome_prices) >= 2 and len(outcomes) >= 2:
                # Check if data is fresh (< 20 minutes)
                is_fresh = False
                if updated_at:
                    try:
                        if isinstance(updated_at, str):
                            updated_dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        else:
                            updated_dt = updated_at
                        if updated_dt.tzinfo is None:
                            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                        age_minutes = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 60
                        is_fresh = age_minutes < 20
                    except Exception:
                        is_fresh = False  # Assume not fresh if we can't parse

                if is_fresh:
                    try:
                        yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.0
                        no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0.0
                        message += f" | ✅ ${yes_price:.3f} / ❌ ${no_price:.3f}"
                    except (ValueError, TypeError, IndexError):
                        pass

            message += "\n\n"

        message += "\n**Select a market to trade:**"

        # Build keyboard with markets in 3 columns, 3 rows (9 markets per page)
        keyboard = []
        market_buttons = []

        for i, market in enumerate(display_markets, start=1):
            market_buttons.append(
                InlineKeyboardButton(
                    str(i),
                    callback_data=f"market_select_{market['id']}_{page}"
                )
            )

            # 3 buttons per row (3 rows total for 9 items)
            if len(market_buttons) == 3:
                keyboard.append(market_buttons)
                market_buttons = []

        # Add remaining buttons if any
        if market_buttons:
            keyboard.append(market_buttons)

        # Add pagination buttons if needed (no page numbering, just Prev/Next)
        if has_more_pages or page > 0:
            pagination_row = []
            if page > 0:
                pagination_row.append(
                    InlineKeyboardButton("⬅️ Prev", callback_data=f"event_select_{page - 1}_{event_id}")
                )

            if has_more_pages:
                pagination_row.append(
                    InlineKeyboardButton("Next ➡️", callback_data=f"event_select_{page + 1}_{event_id}")
                )

            if pagination_row:  # Only add if we have buttons
                keyboard.append(pagination_row)

        # Get original page from context for back button
        # Try to get from user_data, fallback to 0
        original_page = context.user_data.get('last_trending_page', 0)

        # Add back button on new row
        keyboard.append([InlineKeyboardButton("← Back", callback_data=f"trending_markets_{original_page}")])

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in event select callback: {e}")
        await query.edit_message_text("❌ Error loading event markets")
