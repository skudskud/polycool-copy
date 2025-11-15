#!/usr/bin/env python3
"""
Callback Handlers
Handles all inline button callbacks (routing and delegation)
"""

import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Application, CallbackQueryHandler

logger = logging.getLogger(__name__)

# Import telegram_utils using absolute import to avoid circular import issues
try:
    from telegram_bot.handlers.telegram_utils import safe_answer_callback_query
except ImportError:
    # Fallback for direct execution
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from telegram_utils import safe_answer_callback_query

# Import buy callbacks - these are safe to import directly
from telegram_bot.handlers.callbacks.buy_callbacks import handle_quick_buy_callback, handle_confirm_order_callback, handle_custom_buy_callback


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         session_manager, trading_service, position_service, market_service):
    """
    Main callback router for all inline button clicks
    Delegates to appropriate handlers based on callback_data pattern

    NOTE: Withdrawal callbacks are handled by ConversationHandler and filtered out during registration
    """
    query = update.callback_query
    await safe_answer_callback_query(query)

    callback_data = query.data
    user_id = query.from_user.id

    # Debug: Log all callbacks to trace routing
    logger.info(f"[CALLBACK] data='{callback_data[:50]}' user={user_id}")

    try:
        # Category callbacks
        if callback_data.startswith("cat_"):
            from .category_handlers import show_category_markets, show_category_menu
            if callback_data == "cat_menu":
                await show_category_menu(update, context)
            else:
                # Parse: cat_<category>_<page>
                parts = callback_data.split("_")
                category = parts[1]
                page = int(parts[2])

                # Import market_db
                from market_database import MarketDatabase
                market_db = MarketDatabase()

                await show_category_markets(update, context, session_manager, market_db, category, page)

        # TP/SL callbacks (NEW - Handle short indices for 64-byte limit fix!)
        elif callback_data.startswith("set_tpsl:"):
            from . import tpsl_handlers
            await tpsl_handlers.set_tpsl_callback(update, context)

        elif callback_data.startswith("edit_tpsl_by_id:"):
            from . import tpsl_handlers
            await tpsl_handlers.edit_tpsl_by_id_callback(update, context)

        elif callback_data.startswith("edit_tpsl:"):
            from . import tpsl_handlers
            await tpsl_handlers.edit_tpsl_callback(update, context)

        elif callback_data.startswith("update_tp_preset:"):
            from . import tpsl_handlers
            await tpsl_handlers.update_tp_preset_callback(update, context)

        elif callback_data.startswith("update_sl_preset:"):
            from . import tpsl_handlers
            await tpsl_handlers.update_sl_preset_callback(update, context)

        elif callback_data.startswith("update_tp:"):
            from . import tpsl_handlers
            await tpsl_handlers.update_tp_callback(update, context)

        elif callback_data.startswith("update_sl:"):
            from . import tpsl_handlers
            await tpsl_handlers.update_sl_callback(update, context)

        elif callback_data == "view_all_tpsl":
            from . import tpsl_handlers
            await tpsl_handlers.view_all_tpsl_callback(update, context)

        elif callback_data.startswith("cancel_tpsl:"):
            from . import tpsl_handlers
            await tpsl_handlers.cancel_tpsl_callback(update, context)

        elif callback_data == "confirm_immediate_trigger":
            from . import tpsl_handlers
            await tpsl_handlers.confirm_immediate_trigger_callback(update, context)

        # NEW: Market filter callbacks (Phase 4 - Handle filter buttons)
        elif callback_data.startswith("filter_"):
            from market_database import MarketDatabase
            market_db = MarketDatabase()
            await handle_market_filter_callback(query, callback_data, session_manager, market_db)

        # NEW: Category filter callbacks (Phase 4 - Handle category filter buttons)
        elif callback_data.startswith("catfilter_"):
            from market_database import MarketDatabase
            market_db = MarketDatabase()
            await handle_category_filter_callback(query, callback_data, session_manager, market_db)

        # NEW: Event callbacks (Multi-outcome markets like Win/Draw/Win - using Events API)
        elif callback_data.startswith("event_select_") or callback_data.startswith("group_select_"):
            from market_database import MarketDatabase
            market_db = MarketDatabase()
            await handle_event_select_callback(query, callback_data, session_manager, market_db)

        # Referral system callbacks
        elif callback_data == "claim_commissions":
            from .referral_handlers import handle_claim_commissions
            await handle_claim_commissions(query)
        elif callback_data == "refresh_referral_stats":
            from .referral_handlers import handle_refresh_referral_stats
            await handle_refresh_referral_stats(query)
        elif callback_data == "claim_min_not_met":
            from .referral_handlers import handle_claim_min_not_met
            await handle_claim_min_not_met(query)

        # Redemption callbacks for resolved positions
        elif callback_data.startswith("redeem_position_"):
            resolved_position_id = int(callback_data.split("_")[2])
            from .redemption_handler import handle_redeem_position
            await handle_redeem_position(query, resolved_position_id)
        elif callback_data.startswith("confirm_redeem_"):
            resolved_position_id = int(callback_data.split("_")[2])
            from .redemption_handler import handle_confirm_redeem
            await handle_confirm_redeem(query, resolved_position_id)
        elif callback_data == "cancel_redeem":
            from .redemption_handler import handle_cancel_redeem
            await handle_cancel_redeem(query)

        # Emergency position callbacks
        elif callback_data == "emergency_refresh":
            from .positions import handle_positions_refresh
            await handle_positions_refresh(query)
        elif callback_data == "emergency_sell":
            from .positions import handle_sell_position
            await handle_sell_position(query, 0)  # First position
        elif callback_data.startswith("sell_pos_"):
            position_index = int(callback_data.split("_")[2])
            from .positions import handle_sell_position
            await handle_sell_position(query, position_index)
        elif callback_data.startswith("execute_sell_"):
            parts = callback_data.split("_")
            position_index = int(parts[2])
            percentage = int(parts[3])
            from .positions import handle_execute_sell
            await handle_execute_sell(query, position_index, percentage)

        # Market selection callbacks
        elif callback_data.startswith("market_select_"):
            # NEW: Phase 2 - Show YES/NO buttons for selected market
            await handle_market_select_callback(query, callback_data, session_manager, market_service)

        elif callback_data.startswith("market_"):
            await handle_market_callback(query, callback_data, session_manager, market_service)

        # NEW: Markets pagination callbacks
        elif callback_data.startswith("markets_page_"):
            await handle_markets_page_callback(query, callback_data, session_manager, market_service)

        # PHASE 3: Search pagination callbacks
        elif callback_data.startswith("search_page_"):
            await handle_search_page_callback(query, callback_data, session_manager)

        # NEW: Buy prompt callbacks (Phase 3 - Ask for amount)
        elif callback_data.startswith("buy_prompt_"):
            await handle_buy_prompt_callback(query, callback_data, session_manager)

        # NEW: Quick buy callbacks (preset amounts: $5, $10, $20)
        elif callback_data.startswith("quick_buy_"):
            await handle_quick_buy_callback(query, callback_data, session_manager, trading_service)

        # NEW: Custom buy amount callback (shows text input)
        elif callback_data == "buy_custom":
            await handle_custom_buy_callback(query, session_manager)

        # NEW: Confirm order callback (Phase 4 - Execute order)
        # Supports both "confirm_order" and "confirm_order_{details}"
        elif callback_data.startswith("confirm_order"):
            await handle_confirm_order_callback(query, callback_data, session_manager, trading_service)

        # NEW: Category callbacks
        elif callback_data.startswith("cat_") and callback_data != "cat_menu":
            await handle_category_callback(query, callback_data, session_manager, market_service)

        elif callback_data == "cat_menu":
            await handle_category_menu_callback(query)

        elif callback_data == "trending_markets":
            await handle_trending_markets_callback(query, session_manager)

        # Smart wallet callbacks (support multiple trade indexes)
        elif callback_data.startswith("smart_view_"):
            await handle_smart_view_market_callback(query, callback_data, session_manager, market_service)

        elif callback_data.startswith("smart_buy_"):
            await handle_smart_quick_buy_callback(query, callback_data, session_manager, trading_service, market_service)

        # Smart wallet custom buy callback (NEW - for "💰 Custom" button)
        elif callback_data.startswith("scb_"):
            logger.info(f"[CALLBACK] MATCHED scb_ route!")
            await handle_smart_custom_buy_callback(query, callback_data, session_manager, trading_service, market_service)

        # Smart wallet pagination callbacks (NEW)
        elif callback_data == "smart_page_next":
            from .smart_trading_pagination import smart_page_next_handler
            await smart_page_next_handler(update, context, session_manager)

        elif callback_data == "smart_page_prev":
            from .smart_trading_pagination import smart_page_prev_handler
            await smart_page_prev_handler(update, context, session_manager)

        elif callback_data == "smart_page_first":
            from .smart_trading_pagination import smart_page_first_handler
            await smart_page_first_handler(update, context, session_manager)

        elif callback_data == "smart_page_info":
            from .smart_trading_pagination import smart_page_info_handler
            await smart_page_info_handler(update, context, session_manager)

        # Buy callbacks
        elif callback_data.startswith("buy_"):
            await handle_buy_callback(query, callback_data, session_manager, trading_service)

        # CRITICAL: Check SPECIFIC sell patterns BEFORE generic "sell_" pattern!
        # This prevents sell_usd_, sell_all_, sell_quick_, sell_idx_ from being caught by generic sell_

        # New indexed sell callbacks (SPECIFIC - check first)
        elif callback_data.startswith("sell_idx_"):
            await handle_sell_idx_callback(query, callback_data, session_manager, trading_service, position_service)

        # MODERN USD-BASED SELL CALLBACKS - WORLD-CLASS UX! (SPECIFIC - check first)
        elif callback_data.startswith("sell_usd_"):
            await handle_sell_usd_callback(query, callback_data, session_manager, position_service)

        elif callback_data.startswith("sell_all_"):
            await handle_sell_all_callback(query, callback_data, session_manager, trading_service, position_service)

        elif callback_data.startswith("sell_quick_"):
            await handle_sell_quick_callback(query, callback_data, session_manager, trading_service, position_service)

        # Generic sell callbacks (GENERIC - check last, after all specific patterns)
        elif callback_data.startswith("sell_"):
            await handle_sell_callback(query, callback_data, session_manager, trading_service)

        # Trade confirmation callbacks
        elif callback_data.startswith("conf_buy_"):
            await handle_confirm_buy_callback(query, callback_data, session_manager, trading_service)

        elif callback_data.startswith("conf_sell_"):
            await handle_confirm_sell_callback(query, callback_data, session_manager, trading_service)

        # WORLD-CLASS USD SELL CONFIRMATION
        elif callback_data.startswith("conf_usd_sell_"):
            await handle_confirm_usd_sell_callback(query, callback_data, session_manager, trading_service, position_service)

        # Position callbacks
        elif callback_data.startswith("pos_"):
            await handle_position_callback(query, callback_data, session_manager, position_service, trading_service)

        # Wallet/Setup callbacks
        elif callback_data == "show_wallet":
            await handle_show_wallet(query, session_manager)

        elif callback_data == "bridge_from_wallet":
            logger.info(f"🌉 [DEBUG] bridge_from_wallet callback matched! Calling handler...")
            try:
                await handle_bridge_from_wallet(query, session_manager)
                logger.info(f"✅ [DEBUG] handle_bridge_from_wallet completed successfully")
            except Exception as e:
                logger.error(f"❌ [DEBUG] handle_bridge_from_wallet CRASHED: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise

        elif callback_data == "show_funding":
            await handle_show_funding(query, session_manager)

        elif callback_data == "show_polygon_key":
            await handle_show_polygon_key(query, session_manager)

        elif callback_data == "show_solana_key":
            await handle_show_solana_key(query, session_manager)


        elif callback_data == "hide_polygon_key":
            await handle_hide_polygon_key(query, session_manager)

        elif callback_data == "hide_solana_key":
            await handle_hide_solana_key(query, session_manager)
        elif callback_data == "check_balance":
            await handle_check_balance(query, session_manager)

        elif callback_data == "check_approvals":
            await handle_check_approvals(query, session_manager)

        # PHASE 3: Restart callbacks
        elif callback_data.startswith("confirm_restart_"):
            await handle_confirm_restart(query, session_manager)

        elif callback_data == "cancel_restart":
            await handle_cancel_restart(query)

        elif callback_data == "auto_approve":
            await handle_auto_approve(query, session_manager)

        elif callback_data == "generate_api":
            await handle_generate_api(query, session_manager)

        elif callback_data == "test_api_credentials":
            await handle_test_api(query, session_manager)

        # Bridge callbacks
        elif callback_data == "fund_bridge_solana":
            from . import bridge_handlers
            await bridge_handlers.handle_fund_bridge_solana(query, session_manager)

        elif callback_data.startswith("confirm_bridge_"):
            from . import bridge_handlers
            await bridge_handlers.handle_confirm_bridge(query, session_manager)

        elif callback_data == "cancel_bridge":
            from . import bridge_handlers
            await bridge_handlers.handle_cancel_bridge(query, session_manager)

        elif callback_data == "refresh_sol_balance":
            from . import bridge_handlers
            await bridge_handlers.handle_refresh_sol_balance(query, session_manager)

        elif callback_data.startswith("bridge_auto_"):
            from . import bridge_handlers
            await bridge_handlers.handle_bridge_auto(query, session_manager)

        elif callback_data == "bridge_custom_amount":
            from . import bridge_handlers
            await bridge_handlers.handle_bridge_custom_amount(query, session_manager)

        elif callback_data == "copy_solana_address":
            from . import bridge_handlers
            await bridge_handlers.handle_copy_solana_address(query, session_manager)

        elif callback_data == "back_to_bridge_menu":
            from . import bridge_handlers
            await bridge_handlers.handle_back_to_bridge_menu(query, session_manager)

        # PHASE 5: Streamlined bridge callbacks
        elif callback_data == "start_streamlined_bridge":
            await handle_start_streamlined_bridge(query, session_manager)

        elif callback_data == "refresh_sol_balance_start":
            await handle_refresh_sol_balance_start(query, session_manager)

        elif callback_data == "refresh_start":
            await handle_refresh_start(query, session_manager)

        elif callback_data == "cancel_streamlined_bridge":
            await handle_cancel_streamlined_bridge(query)

        # Refresh callbacks
        elif callback_data == "refresh_markets":
            await handle_refresh_markets(query, session_manager, market_service)

        elif callback_data == "refresh_positions":
            await handle_refresh_positions(query, session_manager, position_service, trading_service)

        elif callback_data == "positions_refresh":
            from .positions import handle_positions_refresh
            await handle_positions_refresh(query)

        # Cancel/Back callbacks
        elif callback_data == "cancel_trade":
            session_manager.clear_pending_trade(user_id)
            await query.edit_message_text("❌ Trade cancelled.")

        elif callback_data == "back_to_market":
            session = session_manager.get(user_id)
            current_market = session.get('current_market')

            # Handle different data types for current_market (could be None, str, or dict)
            market_id = None
            if isinstance(current_market, dict):
                market_id = current_market.get('id')
            elif isinstance(current_market, str):
                market_id = current_market

            if market_id:
                await handle_market_callback(query, f"market_{market_id}", session_manager, market_service)

        # Analytics callbacks
        elif callback_data == "detailed_pnl":
            await handle_detailed_pnl(query, session_manager)

        elif callback_data == "trading_stats":
            await handle_trading_stats(query, session_manager)

        elif callback_data == "refresh_pnl":
            await handle_refresh_pnl(query, session_manager)

        elif callback_data == "view_positions":
            await handle_view_positions(query, session_manager, position_service, trading_service)

        elif callback_data == "show_pnl":
            await handle_show_pnl(query, session_manager)

        elif callback_data == "refresh_history":
            await handle_refresh_history(query, session_manager)

        elif callback_data == "export_history":
            await handle_export_history(query, session_manager)

        elif callback_data == "show_history":
            await handle_show_history(query, session_manager)

        elif callback_data.startswith("history_page_"):
            await handle_history_page(query, callback_data, session_manager)

        elif callback_data.startswith("stats_"):
            await handle_stats_period(query, callback_data, session_manager)

        elif callback_data == "refresh_performance":
            await handle_refresh_performance(query, session_manager)

        elif callback_data == "trigger_search":
            # Handle search button from /markets command
            await handle_trigger_search(query, session_manager)

        elif callback_data == "back_to_smart_trading":
            # Handle back button from market view when coming from /smart_trading
            await handle_back_to_smart_trading(query, session_manager)

        elif callback_data.startswith("notif_view_"):
            # Handle view market button from push notifications
            await handle_notification_view_callback(query, callback_data, session_manager, market_service)

        elif callback_data.startswith("notif_buy_"):
            # Handle buy buttons from push notifications
            await handle_notification_buy_callback(query, callback_data, session_manager, trading_service, market_service)

        else:
            # Try registry for dynamically registered handlers
            from .callbacks import get_registry
            registry = get_registry()
            handler = registry.get_handler(callback_data)
            if handler:
                try:
                    await handler(update, context)
                except Exception as e:
                    logger.error(f"Error executing registered handler for {callback_data}: {e}")
                    await query.edit_message_text("❌ Error executing action. Please try again.")
            else:
                logger.warning(f"Unknown callback pattern: {callback_data}")
                await query.edit_message_text("❌ Unknown action. Please try again.")

    except Exception as e:
        import traceback
        logger.error(f"Callback error for {callback_data}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        try:
            await query.edit_message_text(f"❌ Error: {str(e)}\n\nPlease try again or use /markets to start over.")
        except:
            pass


async def handle_market_callback(query, callback_data, session_manager, market_service):
    """Handle market selection callback"""
    market_id = callback_data.replace("market_", "")
    user_id = query.from_user.id

    # Get market details
    market = market_service.get_market_by_id(market_id)
    if not market:
        await query.edit_message_text("❌ Market not found or no longer available.")
        return

    # Validate market data structure
    if not isinstance(market, dict) or 'id' not in market:
        logger.error(f"Invalid market data structure for market_id {market_id}: {type(market)}")
        await query.edit_message_text("❌ Invalid market data. Please try again.")
        return

    # Store in session (always store as dict)
    session = session_manager.get(user_id)
    session['current_market'] = market

    # Get return page from session or default to 0
    return_page = session.get('return_page', 0)

    # Format market detail message
    from ..utils import formatters

    question = market['question']
    outcomes = market.get('outcomes', [])

    message_text = formatters.format_market_info(market, include_details=True)

    # Create buy buttons
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = []

    if len(outcomes) >= 2:
        # For binary markets (YES/NO), show 2-button row
        if len(outcomes) == 2:
            keyboard.append([
                InlineKeyboardButton(f"✅ BUY {outcomes[0].upper()}", callback_data=f"buy_{market_id}_{outcomes[0].lower()}"),
                InlineKeyboardButton(f"❌ BUY {outcomes[1].upper()}", callback_data=f"buy_{market_id}_{outcomes[1].lower()}")
            ])
        else:
            # For multi-outcome markets (3+), show outcomes as separate buttons (2 per row)
            for i, outcome in enumerate(outcomes):
                if i % 2 == 0:
                    keyboard.append([])

                # Format outcome name (e.g., "rangers" -> "Rangers")
                outcome_display = outcome.title() if outcome.lower() in ['yes', 'no'] else outcome
                keyboard[-1].append(
                    InlineKeyboardButton(f"BUY {outcome_display.upper()}", callback_data=f"buy_{market_id}_{outcome.lower()}")
                )

    keyboard.append([InlineKeyboardButton("← Back to Markets", callback_data=f"markets_page_{return_page}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def handle_buy_callback(query, callback_data, session_manager, trading_service):
    """Handle buy button callback"""
    parts = callback_data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ Invalid buy data")
        return

    market_id = parts[1]
    outcome = parts[2]

    # Prompt for amount
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    user_id = query.from_user.id
    session = session_manager.get(user_id)

    # Store pending trade
    session['state'] = 'awaiting_buy_amount'
    session['pending_trade'] = {
        'market_id': market_id,
        'outcome': outcome,
        'action': 'buy'
    }

    # Simple message without complex formatting (avoid Markdown parsing issues)
    message = f"💰 *Enter USD amount to buy {outcome.upper()}*\n\n"
    message += f"Example: 5.00 = ~5 tokens at current price\n\n"
    message += f"Type your amount in dollars (e.g., 10.00)"

    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trade")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def handle_sell_idx_callback(query, callback_data, session_manager, trading_service, position_service):
    """Handle sell callback using position index instead of market_id"""
    try:
        # Parse: sell_idx_0_50 -> position_index=0, percentage=50
        parts = callback_data.split("_")
        if len(parts) < 4:
            await query.edit_message_text("❌ Invalid sell data")
            return

        position_index = int(parts[2])
        percentage = int(parts[3])

        user_id = query.from_user.id

        # Get position by index
        positions = position_service.get_all_positions(user_id)
        position_keys = list(positions.keys())

        if position_index >= len(position_keys):
            await query.edit_message_text("❌ Position not found")
            return

        position_key = position_keys[position_index]
        position = positions.get(position_key)

        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Extract market_id and outcome from position
        market = position.get('market', {})
        market_id = market.get('id', '')
        outcome = position.get('outcome', 'unknown')

        # Now call the original sell handler logic with reconstructed data
        reconstructed_callback_data = f"sell_{market_id}_{outcome}_{percentage}"
        await handle_sell_callback(query, reconstructed_callback_data, session_manager, trading_service)

    except (ValueError, IndexError) as e:
        await query.edit_message_text("❌ Invalid sell selection")
    except Exception as e:
        logger.error(f"Sell idx callback error: {e}")
        await query.edit_message_text("❌ Error processing sell request")


def _get_positions_from_blockchain(wallet_address: str) -> dict:
    """
    ❌ DEPRECATED: Use positions/core.py logic instead
    This function is kept for backwards compatibility but should be replaced.

    ⚠️ WARNING: This is a SYNC function that blocks the event loop!
    ⚠️ WARNING: No caching, no filtering, no TTL management!

    Use the centralized logic from positions/core.py instead:
    - Async operations
    - Redis caching with proper TTL
    - Filtering of resolved/dust positions
    - Consistent data format

    Returns dict format compatible with existing code:
    {
        'condition_id_outcome': {
            'tokens': float,
            'buy_price': float,
            'token_id': str,
            'outcome': str,
            'market': dict,
            'condition_id': str
        }
    }
    """
    import requests

    try:
        url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
        logger.warning(f"⚠️ SYNC API: Fetching positions from {url} - Consider migrating caller to async")
        response = requests.get(url, timeout=10)
        blockchain_positions = response.json()

        logger.info(f"✅ BLOCKCHAIN API: Returned {len(blockchain_positions)} positions")

        # Convert blockchain format to dict format for compatibility with existing code
        positions = {}
        for idx, pos in enumerate(blockchain_positions):
            # Create unique key from condition_id and outcome
            key = f"{pos.get('conditionId', 'unknown')}_{pos.get('outcome', 'unknown').lower()}"

            positions[key] = {
                'tokens': float(pos.get('size', 0)),
                'buy_price': float(pos.get('avgPrice', 0)),
                'token_id': pos.get('asset', ''),
                'outcome': pos.get('outcome', 'unknown').lower(),
                'market': {
                    'id': pos.get('conditionId'),
                    'question': pos.get('title', 'Unknown Market')
                },
                'condition_id': pos.get('conditionId', '')
            }
            logger.info(f"  Position {idx}: {pos.get('outcome')} {pos.get('size')} tokens @ ${pos.get('avgPrice')}")

        return positions

    except Exception as e:
        logger.error(f"❌ BLOCKCHAIN API ERROR: {e}")
        return {}


async def handle_sell_usd_callback(query, callback_data, session_manager, position_service):
    """WORLD-CLASS UX: Handle custom USD amount selling - BLOCKCHAIN FIRST"""
    try:
        logger.error(f"🔍 DEBUG: USD sell callback triggered with data: {callback_data}")

        position_index = int(callback_data.replace("sell_usd_", ""))
        user_id = query.from_user.id

        logger.error(f"🔍 DEBUG: Parsed position_index: {position_index}, user_id: {user_id}")

        # Get user's wallet and balance
        from core.services import user_service, balance_checker
        wallet = user_service.get_user_wallet(user_id)

        if not wallet:
            await query.edit_message_text("❌ Wallet not found. Please run /start to set up.")
            return

        wallet_address = wallet['address']
        logger.info(f"💼 Wallet: {wallet_address}")

        balance_str = "Error"
        try:
            usdc_balance, _ = balance_checker.check_usdc_balance(wallet_address)
            balance_str = f"{usdc_balance:.2f}"
        except Exception as e:
            logger.error(f"Error fetching balance for custom sell prompt: {e}")
            balance_str = "Error"

        # 🔥 BLOCKCHAIN-FIRST: Get positions from blockchain API (source of truth)
        logger.info(f"🔗 BLOCKCHAIN: Fetching positions for wallet {wallet_address}")
        positions = _get_positions_from_blockchain(wallet_address)
        position_keys = list(positions.keys())

        logger.info(f"✅ BLOCKCHAIN: Found {len(positions)} positions")

        if position_index >= len(position_keys):
            logger.error(f"❌ Position index {position_index} >= {len(position_keys)}")
            await query.edit_message_text("❌ Position not found")
            return

        position_key = position_keys[position_index]
        position = positions.get(position_key)

        logger.error(f"🔍 DEBUG: Position key: {position_key}")
        logger.error(f"🔍 DEBUG: Position data: {position}")

        if not position:
            logger.error(f"❌ DEBUG: Position is None for key {position_key}")
            await query.edit_message_text("❌ Position not found")
            return

        # CRITICAL DEBUG: Check position structure
        required_fields = ['tokens', 'buy_price', 'market', 'outcome', 'token_id']
        for field in required_fields:
            value = position.get(field)
            logger.error(f"🔍 DEBUG: Position.{field} = {value} (type: {type(value)})")

        # Calculate position info for user context
        current_tokens = position.get('tokens', 0)
        buy_price = position.get('buy_price', 0)
        estimated_value = current_tokens * buy_price
        market_question = position.get('market', {}).get('question', 'Unknown Market')[:40]
        outcome = position.get('outcome', 'unknown').upper()

        logger.error(f"🔍 DEBUG: Calculated values - tokens: {current_tokens}, buy_price: {buy_price}, value: {estimated_value}")

        # Store sell session data
        session = session_manager.get(user_id)
        session['state'] = 'awaiting_usd_sell_amount'
        session['pending_sell'] = {
            'position_index': position_index,
            'position_key': position_key,
            'action': 'sell_usd'
        }

        logger.error(f"🔍 DEBUG: Set session state to awaiting_usd_sell_amount")

        # Modern, professional message
        message = f"💰 **Sell {outcome} Position**\n\n"
        message += f"📊 **Market:** {market_question}...\n"
        message += f"📦 **Your Position:** {current_tokens:.0f} tokens\n"
        message += f"💵 **Estimated Value:** ~${estimated_value:.2f}\n"
        message += f"💰 **Your Balance:** ${balance_str} USDC\n\n"
        message += f"**💸 Enter USD amount to sell:**\n"
        message += f"Examples: `25`, `50.50`, `100`\n\n"
        message += f"💡 *Enter any amount up to ${estimated_value:.2f}*"

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data="refresh_positions")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        logger.error(f"🔍 DEBUG: About to send message to user")

        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

        logger.error(f"✅ DEBUG: USD sell callback completed successfully")

    except Exception as e:
        logger.error(f"❌ DEBUG: USD sell callback error: {e}")
        logger.error(f"❌ DEBUG: Exception details: {str(e)}")
        import traceback
        logger.error(f"❌ DEBUG: Traceback: {traceback.format_exc()}")
        await query.edit_message_text("❌ Error processing sell request")


async def handle_sell_all_callback(query, callback_data, session_manager, trading_service, position_service):
    """WORLD-CLASS UX: Sell entire position with one click - BLOCKCHAIN FIRST"""
    try:
        logger.error(f"🔍 DEBUG: Sell all callback triggered with data: {callback_data}")

        position_index = int(callback_data.replace("sell_all_", ""))
        user_id = query.from_user.id

        logger.error(f"🔍 DEBUG: Sell all - position_index: {position_index}, user_id: {user_id}")

        # Get wallet
        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)
        if not wallet:
            await query.edit_message_text("❌ Wallet not found")
            return

        # 🔥 BLOCKCHAIN-FIRST: Get positions from blockchain API
        logger.info(f"🔗 BLOCKCHAIN: Fetching positions for sell all")
        positions = _get_positions_from_blockchain(wallet['address'])
        position_keys = list(positions.keys())

        logger.error(f"🔍 DEBUG: Sell all - Found {len(positions)} positions")

        if position_index >= len(position_keys):
            logger.error(f"❌ DEBUG: Sell all - Position index {position_index} >= {len(position_keys)}")
            await query.edit_message_text("❌ Position not found")
            return

        position_key = position_keys[position_index]
        position = positions.get(position_key)

        logger.error(f"🔍 DEBUG: Sell all - Position key: {position_key}")

        if not position:
            logger.error(f"❌ DEBUG: Sell all - Position is None")
            await query.edit_message_text("❌ Position not found")
            return

        logger.error(f"🔍 DEBUG: Sell all - About to execute direct sell")

        # Execute direct sell of entire position
        result = await execute_direct_sell(
            user_id=user_id,
            position=position,
            sell_type="all",
            amount=None,
            trading_service=trading_service,
            position_service=position_service
        )

        logger.error(f"🔍 DEBUG: Sell all - Execute result: {result}")

        if result['success']:
            logger.error(f"✅ DEBUG: Sell all - Success!")
            await query.edit_message_text(result['message'], parse_mode='Markdown')
        else:
            logger.error(f"❌ DEBUG: Sell all - Failed: {result['message']}")
            await query.edit_message_text(f"❌ {result['message']}")

    except Exception as e:
        logger.error(f"❌ DEBUG: Sell all callback error: {e}")
        logger.error(f"❌ DEBUG: Sell all exception details: {str(e)}")
        import traceback
        logger.error(f"❌ DEBUG: Sell all traceback: {traceback.format_exc()}")
        await query.edit_message_text("❌ Error processing sell request")


async def handle_sell_quick_callback(query, callback_data, session_manager, trading_service, position_service):
    """WORLD-CLASS UX: Quick sell preset amounts ($25, $50) - BLOCKCHAIN FIRST"""
    try:
        parts = callback_data.replace("sell_quick_", "").split("_")
        position_index = int(parts[0])
        usd_amount = float(parts[1])
        user_id = query.from_user.id

        # Get wallet
        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)
        if not wallet:
            await query.edit_message_text("❌ Wallet not found")
            return

        # 🔥 BLOCKCHAIN-FIRST: Get positions from blockchain API
        logger.info(f"🔗 BLOCKCHAIN: Fetching positions for quick sell")
        positions = _get_positions_from_blockchain(wallet['address'])
        position_keys = list(positions.keys())

        if position_index >= len(position_keys):
            await query.edit_message_text("❌ Position not found")
            return

        position_key = position_keys[position_index]
        position = positions.get(position_key)

        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Execute direct sell with USD amount
        result = await execute_direct_sell(
            user_id=user_id,
            position=position,
            sell_type="usd_amount",
            amount=usd_amount,
            trading_service=trading_service,
            position_service=position_service
        )

        if result['success']:
            await query.edit_message_text(result['message'], parse_mode='Markdown')
        else:
            await query.edit_message_text(f"❌ {result['message']}")

    except Exception as e:
        logger.error(f"Quick sell callback error: {e}")
        await query.edit_message_text("❌ Error processing sell request")


async def execute_direct_sell(user_id: int, position: dict, sell_type: str, amount: float,
                             trading_service, position_service) -> dict:
    """
    ENTERPRISE-GRADE DIRECT SELLING - NO DATABASE LOOKUPS!
    Executes sells using position data directly for maximum reliability
    """
    try:
        logger.error(f"🔍 DEBUG: execute_direct_sell called - user_id: {user_id}, sell_type: {sell_type}, amount: {amount}")

        # Get all required data from position (no external lookups!)
        current_tokens = position.get('tokens', 0)
        buy_price = position.get('buy_price', 0)
        token_id = position.get('token_id')
        market = position.get('market', {})
        outcome = position.get('outcome', 'unknown')

        logger.error(f"🔍 DEBUG: Position data - tokens: {current_tokens}, buy_price: {buy_price}, token_id: {token_id}, outcome: {outcome}")
        logger.error(f"🔍 DEBUG: Market data: {market}")

        # Validate position data
        if not token_id:
            logger.error(f"❌ DEBUG: Missing token_id in position")
            return {'success': False, 'message': 'Position missing token ID - cannot sell'}

        if current_tokens <= 0:
            logger.error(f"❌ DEBUG: No tokens to sell - current_tokens: {current_tokens}")
            return {'success': False, 'message': 'No tokens to sell'}

        # Calculate tokens to sell based on sell type
        if sell_type == "all":
            tokens_to_sell = int(current_tokens)
            estimated_usd = tokens_to_sell * buy_price
            logger.error(f"🔍 DEBUG: Sell all - tokens_to_sell: {tokens_to_sell}, estimated_usd: {estimated_usd}")
        elif sell_type == "usd_amount":
            # Convert USD to tokens using buy price as estimate
            tokens_to_sell = min(int(amount / buy_price), int(current_tokens))
            estimated_usd = amount
            logger.error(f"🔍 DEBUG: Sell USD - amount: {amount}, tokens_to_sell: {tokens_to_sell}")
        else:
            logger.error(f"❌ DEBUG: Invalid sell_type: {sell_type}")
            return {'success': False, 'message': 'Invalid sell type'}

        if tokens_to_sell <= 0:
            logger.error(f"❌ DEBUG: No tokens to sell after calculation - tokens_to_sell: {tokens_to_sell}")
            return {'success': False, 'message': 'No tokens to sell at this price'}

        # Get user trader for execution
        logger.error(f"🔍 DEBUG: Getting user trader for user_id: {user_id}")
        user_trader = trading_service.get_trader(user_id)

        if not user_trader:
            logger.error(f"❌ DEBUG: No user trader found for user_id: {user_id}")
            return {'success': False, 'message': 'Trading not available - please check your setup'}

        logger.error(f"✅ DEBUG: User trader found: {type(user_trader)}")

        # DIRECT EXECUTION - Use position data directly!
        logger.error(f"🔍 DEBUG: About to call speed_sell_with_token_id - market: {market}, outcome: {outcome}, tokens: {tokens_to_sell}, token_id: {token_id}")

        sell_result = user_trader.speed_sell_with_token_id(market, outcome, tokens_to_sell, token_id)

        logger.error(f"🔍 DEBUG: speed_sell_with_token_id result: {sell_result}")

        if sell_result and sell_result.get('order_id'):
            # Success! Update position data
            remaining_tokens = current_tokens - tokens_to_sell

            # Get actual sell price from result
            sell_price = sell_result.get('sell_price', buy_price)
            actual_proceeds = tokens_to_sell * sell_price

            # CRITICAL FIX: Log transaction with market data
            from telegram_bot.services.transaction_service import get_transaction_service
            transaction_service = get_transaction_service()
            transaction_logged = transaction_service.log_trade(
                user_id=user_id,
                transaction_type='SELL',
                market_id=market.get('id', 'unknown'),
                outcome=outcome,
                tokens=tokens_to_sell,
                price_per_token=sell_price,
                token_id=token_id,
                order_id=sell_result['order_id'],
                transaction_hash=sell_result.get('transaction_hash'),
                market_data=market  # ← CRITICAL: Include market data for history display
            )

            if transaction_logged:
                logger.info(f"✅ USD SELL TRANSACTION LOGGED: User {user_id} SELL {tokens_to_sell} {outcome} tokens at ${sell_price:.4f}")
            else:
                logger.error(f"❌ USD SELL TRANSACTION LOG FAILED: User {user_id} order {sell_result['order_id']}")

            # Calculate P&L
            pnl_value = actual_proceeds - (tokens_to_sell * buy_price)
            pnl_pct = (pnl_value / (tokens_to_sell * buy_price) * 100) if (tokens_to_sell * buy_price) > 0 else 0

            # Format P&L indicator
            if pnl_value >= 0:
                pnl_indicator = f"🟢 **+${pnl_value:.2f} (+{pnl_pct:.1f}%)**"
            else:
                pnl_indicator = f"🔴 **${pnl_value:.2f} ({pnl_pct:.1f}%)**"

            success_msg = f"💰 **SELL EXECUTED!**\n\n"
            success_msg += f"✅ **Market:** {market.get('question', 'Market')[:50]}...\n"
            success_msg += f"🎯 **Position:** {outcome.upper()}\n"
            success_msg += f"📦 **Sold:** {tokens_to_sell} tokens\n"
            success_msg += f"💵 **Amount Received:** ${actual_proceeds:.2f}\n"
            success_msg += f"{pnl_indicator}\n\n"
            success_msg += f"📋 **Order ID:** `{sell_result['order_id'][:20]}...`\n"
            success_msg += f"📊 **Remaining:** {remaining_tokens:.0f} tokens\n\n"
            success_msg += f"🎉 **Trade executing on Polymarket!**"

            return {'success': True, 'message': success_msg}
        else:
            logger.error(f"❌ DEBUG: Sell execution failed - no order_id in result")
            return {'success': False, 'message': 'Trade execution failed - please try again'}

    except Exception as e:
        logger.error(f"❌ DEBUG: Direct sell execution error: {e}")
        logger.error(f"❌ DEBUG: Direct sell exception details: {str(e)}")
        import traceback
        logger.error(f"❌ DEBUG: Direct sell traceback: {traceback.format_exc()}")
        return {'success': False, 'message': f'Execution error: {str(e)}'}


async def handle_sell_callback(query, callback_data, session_manager, trading_service):
    """Handle sell button callback"""
    parts = callback_data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ Invalid sell data")
        return

    market_id = parts[1]
    outcome = parts[2]

    # Prompt for amount
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    user_id = query.from_user.id
    session = session_manager.get(user_id)

    # Store pending trade
    session['state'] = 'awaiting_sell_amount'
    session['pending_trade'] = {
        'market_id': market_id,
        'outcome': outcome,
        'action': 'sell'
    }

    # Simple message without complex formatting (avoid Markdown parsing issues)
    message = f"📤 *Enter number of {outcome.upper()} tokens to sell*\n\n"
    message += f"Example: 10 tokens\n\n"
    message += f"Type the number of tokens you want to sell"

    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trade")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def handle_confirm_buy_callback(query, callback_data, session_manager, trading_service):
    """Handle buy confirmation"""
    parts = callback_data.replace("conf_buy_", "").split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ Invalid confirmation data")
        return

    market_id = parts[0]
    outcome = parts[1]
    amount = float(parts[2])

    from ..services import MarketService
    market_service = MarketService()
    market = market_service.get_market_by_id(market_id)

    if not market:
        await query.edit_message_text("❌ Market not found")
        return

    # Execute buy
    result = await trading_service.execute_buy(query, market_id, outcome, amount, market)

    if result['success']:
        await query.edit_message_text(result['message'], parse_mode='Markdown')
    else:
        await query.edit_message_text(result['message'], parse_mode='Markdown')


async def handle_confirm_sell_callback(query, callback_data, session_manager, trading_service):
    """Handle sell confirmation"""
    parts = callback_data.replace("conf_sell_", "").split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ Invalid confirmation data")
        return

    market_id = parts[0]
    outcome = parts[1]
    amount = float(parts[2])

    # Execute sell
    result = await trading_service.execute_sell(query, market_id, outcome, amount)

    if result['success']:
        await query.edit_message_text(result['message'], parse_mode='Markdown')
    else:
        await query.edit_message_text(result['message'], parse_mode='Markdown')


async def handle_confirm_usd_sell_callback(query, callback_data, session_manager, trading_service, position_service):
    """WORLD-CLASS UX: Handle USD sell confirmation - BLOCKCHAIN FIRST"""
    try:
        # Parse: conf_usd_sell_0_25.50
        parts = callback_data.replace("conf_usd_sell_", "").split("_")
        position_index = int(parts[0])
        usd_amount = float(parts[1])
        user_id = query.from_user.id

        # Get wallet
        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)
        if not wallet:
            await query.edit_message_text("❌ Wallet not found")
            return

        # 🔥 BLOCKCHAIN-FIRST: Get positions from blockchain API
        logger.info(f"🔗 BLOCKCHAIN: Fetching positions for USD sell confirmation")
        positions = _get_positions_from_blockchain(wallet['address'])
        position_keys = list(positions.keys())

        if position_index >= len(position_keys):
            await query.edit_message_text("❌ Position not found")
            return

        position_key = position_keys[position_index]
        position = positions.get(position_key)

        if not position:
            await query.edit_message_text("❌ Position not found")
            return

        # Execute direct sell with USD amount
        result = await execute_direct_sell(
            user_id=user_id,
            position=position,
            sell_type="usd_amount",
            amount=usd_amount,
            trading_service=trading_service,
            position_service=position_service
        )

        if result['success']:
            await query.edit_message_text(result['message'], parse_mode='Markdown')
        else:
            await query.edit_message_text(f"❌ {result['message']}")

    except Exception as e:
        logger.error(f"USD sell confirmation error: {e}")
        await query.edit_message_text("❌ Error confirming sell order")


async def handle_position_callback(query, callback_data, session_manager, position_service, trading_service):
    """Handle position detail view"""
    try:
        position_index = int(callback_data.replace("pos_", ""))
    except ValueError:
        await query.edit_message_text("❌ Invalid position selection")
        return

    user_id = query.from_user.id
    positions = position_service.get_all_positions(user_id)

    # Get position by index
    position_keys = list(positions.keys())
    if position_index >= len(position_keys):
        await query.edit_message_text("❌ Position not found")
        return

    position_key = position_keys[position_index]
    position = positions.get(position_key)

    if not position:
        await query.edit_message_text("❌ Position not found")
        return

    # Get market data
    market = position.get('market', {})
    outcome = position.get('outcome', 'unknown')

    # Calculate P&L if possible
    user_trader = trading_service.get_trader(user_id)
    pnl = None
    if user_trader:
        pnl = position_service.calculate_pnl(position, user_trader)

    # Format position
    from ..utils import formatters
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    message_text = formatters.format_position(position, market, pnl)

    # Get position index for callback data
    positions = position_service.get_all_positions(user_id)
    position_keys = list(positions.keys())
    current_position_index = position_keys.index(position_key) if position_key in position_keys else 0

    # Create modern USD-based sell buttons - WORLD-CLASS UX!
    # Calculate position value for user context
    current_tokens = position.get('tokens', 0)
    buy_price = position.get('buy_price', 0)
    total_cost = position.get('total_cost', 0)

    # Estimate current position value (using buy price as baseline)
    estimated_value = current_tokens * buy_price

    keyboard = [
        [InlineKeyboardButton("💰 Sell Custom Amount", callback_data=f"sell_usd_{current_position_index}")],
        [InlineKeyboardButton("📊 Sell All Position", callback_data=f"sell_all_{current_position_index}")],
        [InlineKeyboardButton("← Back", callback_data="refresh_positions")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        message_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


# Placeholder implementations for wallet/setup callbacks
async def handle_show_wallet(query, session_manager):
    """Show wallet details - DELETE BUTTON MENU THEN CALL /wallet"""
    try:
        # Delete the button menu
        await query.message.delete()

        # Call wallet command - it will send its own reply
        from telegram_bot.handlers.setup_handlers import wallet_command

        class FakeContext:
            args = []  # Commands expect context.args

        class FakeUpdate:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.message = query.message

        fake_update = FakeUpdate(query)
        fake_context = FakeContext()
        await wallet_command(fake_update, fake_context)

    except Exception as e:
        logger.error(f"Error calling wallet command: {e}")
        await query.message.reply_text(f"❌ Error: {str(e)}")


async def handle_bridge_from_wallet(query, session_manager):
    """
    Handle "Bridge SOL → USDC" button from /wallet command
    Checks balance, then forwards to existing bridge flow
    """
    user_id = query.from_user.id

    try:
        from core.services import user_service
        from solana_bridge.solana_transaction import SolanaTransactionBuilder

        # Get user
        user = user_service.get_user(user_id)
        if not user or not user.solana_address:
            await query.edit_message_text(
                "❌ **Wallet not found!**\n\nPlease use /start to create your wallet.",
                parse_mode='Markdown'
            )
            return

        solana_address = user.solana_address

        # Check SOL balance
        solana_tx_builder = SolanaTransactionBuilder()
        sol_balance = await solana_tx_builder.get_sol_balance(solana_address)

        # Minimum check (0.1 SOL required)
        if sol_balance < 0.1:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            error_text = f"""
❌ **Insufficient SOL Balance**

📊 **Current Balance:** {sol_balance:.4f} SOL
⚠️ **Minimum Required:** 0.1 SOL

📍 **Your SOL Address:**
`{solana_address}`

💡 **Next Steps:**
1. Send at least 0.1 SOL to your address above
2. Wait for confirmation (~30 seconds)
3. Click "🔄 Check Balance Again" below

🔄 Bridge will be available once you have enough SOL!
            """

            keyboard = [
                [InlineKeyboardButton("🔄 Check Balance Again", callback_data="bridge_from_wallet")],
                [InlineKeyboardButton("💼 Back to Wallet", callback_data="show_wallet")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                error_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return

        # Balance OK - show bridge menu with Auto and Custom Amount options
        logger.info(f"User {user_id} starting bridge from wallet with {sol_balance:.4f} SOL")

        # Import bridge menu handler
        from telegram_bot.handlers.bridge_handlers import handle_refresh_sol_balance

        # Show bridge menu (Auto vs Custom Amount)
        await handle_refresh_sol_balance(query, session_manager)

    except Exception as e:
        logger.error(f"Error in handle_bridge_from_wallet: {e}")
        await query.edit_message_text(
            f"❌ **Error checking balance:** {str(e)}\n\n"
            f"Please try again or contact support.",
            parse_mode='Markdown'
        )


async def handle_show_funding(query, session_manager):
    """Show funding instructions"""
    await query.edit_message_text(
        "💰 **Fund Your Wallet**\n\nUse the wallet menu for funding options!",
        parse_mode='Markdown'
    )


async def handle_show_polygon_key(query, session_manager):
    """Show Polygon private key"""
    user_id = query.from_user.id
    from core.services import user_service
    from core.services.encryption_service import log_key_access
    from datetime import datetime

    logger.info(f"🔑 [WALLET_DISPLAY_START] user_id={user_id} | key_type=polygon | ts={datetime.utcnow().isoformat()}")

    try:
        wallet = user_service.get_user_wallet(user_id)
        if not wallet:
            logger.error(f"❌ [WALLET_NOT_FOUND] user_id={user_id} | ts={datetime.utcnow().isoformat()}")
            await query.edit_message_text("❌ No wallet found")
            return

        logger.info(f"✅ [WALLET_RETRIEVED] user_id={user_id} | wallet_keys={list(wallet.keys())} | ts={datetime.utcnow().isoformat()}")

        private_key = wallet['private_key']

        # Validate decryption worked
        if not private_key:
            logger.error(f"❌ [DECRYPTION_FAILED] user_id={user_id} | key_type=polygon | reason=empty_private_key | ts={datetime.utcnow().isoformat()}")
            await query.answer("❌ Failed to decrypt private key", show_alert=True)
            return

        if not private_key.startswith('0x') or len(private_key) < 60:
            logger.warning(f"⚠️ [SUSPICIOUS_KEY_FORMAT] user_id={user_id} | key_type=polygon | key_len={len(private_key)} | starts_with_0x={private_key.startswith('0x')} | ts={datetime.utcnow().isoformat()}")

        logger.info(f"✅ [KEY_DECRYPTED] user_id={user_id} | key_type=polygon | key_format_valid=True | key_len={len(private_key)} | ts={datetime.utcnow().isoformat()}")
        log_key_access(user_id, 'polygon', 'display', 'handle_show_polygon_key')

        # Create inline button to hide the key
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Hide Key", callback_data="hide_polygon_key")]
        ])

        # Send key message WITH button
        key_msg = await query.message.reply_text(
            f"🔑 **Your Polygon Private Key:**\n\n`{private_key}`\n\n"
            f"⚠️ **KEEP THIS SECRET!**\n"
            f"Click the button below to hide this message.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

        logger.info(f"✅ [MESSAGE_SENT] user_id={user_id} | key_type=polygon | message_id={key_msg.message_id} | ts={datetime.utcnow().isoformat()}")

        # Delete after 30 seconds in background (non-blocking)
        async def auto_delete():
            await asyncio.sleep(30)
            try:
                await key_msg.delete()
                logger.info(f"✅ [AUTO_DELETED] user_id={user_id} | key_type=polygon | message_id={key_msg.message_id} | ts={datetime.utcnow().isoformat()}")
            except:
                logger.warning(f"⚠️ [AUTO_DELETE_FAILED] user_id={user_id} | key_type=polygon | message_id={key_msg.message_id}")

        asyncio.create_task(auto_delete())

    except Exception as e:
        logger.error(f"❌ [CRITICAL_ERROR] user_id={user_id} | key_type=polygon | error={str(e)[:150]} | ts={datetime.utcnow().isoformat()}", exc_info=True)
        try:
            await query.answer(f"❌ Error: {str(e)[:60]}", show_alert=True)
        except:
            pass


async def handle_show_solana_key(query, session_manager):
    """Show Solana private key"""
    user_id = query.from_user.id
    from core.services import user_service
    from core.services.encryption_service import log_key_access
    from datetime import datetime

    logger.info(f"🔑 [WALLET_DISPLAY_START] user_id={user_id} | key_type=solana | ts={datetime.utcnow().isoformat()}")

    try:
        result = user_service.generate_solana_wallet(user_id)
        if not result:
            logger.error(f"❌ [WALLET_GENERATION_FAILED] user_id={user_id} | key_type=solana | ts={datetime.utcnow().isoformat()}")
            await query.answer("❌ Failed to generate Solana wallet", show_alert=True)
            return

        address, private_key = result

        # Validate decryption worked
        if not private_key:
            logger.error(f"❌ [DECRYPTION_FAILED] user_id={user_id} | key_type=solana | reason=empty_private_key | ts={datetime.utcnow().isoformat()}")
            await query.answer("❌ Failed to decrypt Solana private key", show_alert=True)
            return

        if not len(private_key) > 40:
            logger.warning(f"⚠️ [SUSPICIOUS_KEY_FORMAT] user_id={user_id} | key_type=solana | key_len={len(private_key)} | ts={datetime.utcnow().isoformat()}")

        logger.info(f"✅ [KEY_DECRYPTED] user_id={user_id} | key_type=solana | address_len={len(address)} | key_len={len(private_key)} | ts={datetime.utcnow().isoformat()}")
        log_key_access(user_id, 'solana', 'display', 'handle_show_solana_key')

        # Create inline button to hide the key
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Hide Key", callback_data="hide_solana_key")]
        ])

        # Send key message WITH button
        key_msg = await query.message.reply_text(
            f"🔑 **Your Solana Private Key:**\n\n`{private_key}`\n\n"
            f"⚠️ **KEEP THIS SECRET!**\n"
            f"Click the button below to hide this message.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

        logger.info(f"✅ [MESSAGE_SENT] user_id={user_id} | key_type=solana | message_id={key_msg.message_id} | ts={datetime.utcnow().isoformat()}")

        # Delete after 30 seconds in background (non-blocking)
        async def auto_delete():
            await asyncio.sleep(30)
            try:
                await key_msg.delete()
                logger.info(f"✅ [AUTO_DELETED] user_id={user_id} | key_type=solana | message_id={key_msg.message_id} | ts={datetime.utcnow().isoformat()}")
            except:
                logger.warning(f"⚠️ [AUTO_DELETE_FAILED] user_id={user_id} | key_type=solana | message_id={key_msg.message_id}")

        asyncio.create_task(auto_delete())

    except Exception as e:
        logger.error(f"❌ [CRITICAL_ERROR] user_id={user_id} | key_type=solana | error={str(e)[:150]} | ts={datetime.utcnow().isoformat()}", exc_info=True)
        try:
            await query.answer(f"❌ Error: {str(e)[:60]}", show_alert=True)
        except:
            pass


async def handle_check_balance(query, session_manager):
    """Check wallet balance"""
    user_id = query.from_user.id
    from core.services import user_service
    from core.services import balance_checker

    wallet = user_service.get_user_wallet(user_id)
    if not wallet:
        await query.edit_message_text("❌ No wallet found")
        return

    address = wallet['address']

    try:
        balances = balance_checker.check_balance(address)

        from ..utils import formatters
        balance_text = f"""
💰 **Wallet Balances**

USDC.e: {formatters.format_usd(balances.get('usdc', 0))}
POL: {balances.get('pol', 0):.4f}

Address: `{address}`
        """

        await query.edit_message_text(balance_text, parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def handle_check_approvals(query, session_manager):
    """Check approval status"""
    await query.edit_message_text(
        "✅ **Checking Approvals...**\n\nUse /approve for detailed status!",
        parse_mode='Markdown'
    )


async def handle_auto_approve(query, session_manager):
    """Handle auto-approve"""
    await query.edit_message_text(
        "🔥 **Auto-Approval**\n\nStarting auto-approval process...\n\n"
        "This may take 30-60 seconds.",
        parse_mode='Markdown'
    )


async def handle_generate_api(query, session_manager):
    """Generate API credentials"""
    await query.edit_message_text(
        "🔑 **Generating API Credentials...**\n\nPlease wait...",
        parse_mode='Markdown'
    )


async def handle_test_api(query, session_manager):
    """Test API credentials"""
    await query.edit_message_text(
        "🧪 **Testing API Credentials...**\n\nPlease wait...",
        parse_mode='Markdown'
    )


async def handle_refresh_markets(query, session_manager, market_service):
    """Refresh markets list"""
    from database import db_manager, Market
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    # Get top 20 tradeable markets from PostgreSQL
    with db_manager.get_session() as db:
        markets_query = db.query(Market).filter(
            Market.tradeable == True,
            Market.active == True
        ).order_by(Market.volume.desc()).limit(20).all()
        markets = [m.to_dict() for m in markets_query]

    keyboard = []
    for i, market in enumerate(markets[:20]):
        market_name = market['question']
        if len(market_name) > 45:
            market_name = market_name[:42] + "..."

        button = InlineKeyboardButton(
            f"{i+1}. {market_name}",
            callback_data=f"market_{market['id']}"
        )
        keyboard.append([button])

    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_markets")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🏆 **TOP VOLUME MARKETS**\n\nClick to trade:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def handle_refresh_positions(query, session_manager, position_service, trading_service):
    """Refresh positions list - NOW WITH BLOCKCHAIN DETECTION!"""
    user_id = query.from_user.id

    try:
        # Update loading message
        await query.edit_message_text("🔍 **Refreshing blockchain positions...**", parse_mode='Markdown')

        # Get user wallet
        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)

        if not wallet:
            await query.edit_message_text(
                "❌ **No wallet found!**\n\nUse /start to create your wallet.",
                parse_mode='Markdown'
            )
            return

        wallet_address = wallet['address']

        # Get fresh positions from blockchain
        from blockchain_position_service import get_blockchain_position_service
        blockchain_service = get_blockchain_position_service()

        # Force refresh (bypass cache)
        positions = blockchain_service.refresh_user_positions(user_id, wallet_address)

        if not positions:
            await query.edit_message_text(
                "📭 **No blockchain positions found**\n\n✨ **This is accurate!** Your wallet has no active position tokens.\n\nUse /markets to start trading!",
                parse_mode='Markdown'
            )
            return

        # Fetch current prices with audit statistics
        from telegram_bot.services.market_service import MarketService
        from telegram_bot.utils.pnl_formatters import (
            format_global_pnl_summary,
            format_position_pnl,
            log_price_fetch_stats,
            get_cache_audit_footer
        )

        market_service = MarketService()
        current_prices = {}
        cache_stats = {}

        logger.info(f"📊 Fetching current prices for {len(positions)} positions (refresh)...")

        for position_key, position in positions.items():
            token_id = position.get('token_id', '')
            if token_id:
                price, cache_hit, fetch_time, ttl = market_service.get_token_price_with_audit(token_id)
                if price is not None:
                    current_prices[token_id] = price
                    cache_stats[token_id] = {
                        'hit': cache_hit,
                        'time': fetch_time,
                        'ttl': ttl
                    }
                    log_price_fetch_stats(token_id, cache_hit, price, fetch_time)

        # Build refreshed positions message
        message_text = f"🎯 **YOUR BLOCKCHAIN POSITIONS** (Refreshed)\n\n"

        # Add global P&L summary
        global_summary = format_global_pnl_summary(positions, current_prices, cache_stats)
        message_text += global_summary

        message_text += f"👤 **User:** {user_id}\n"
        message_text += f"📍 **Wallet:** `{wallet_address[:10]}...{wallet_address[-6:]}`\n"
        message_text += f"📊 **Total Positions:** {len(positions)}\n\n"

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = []
        position_index = 0

        for position_key, position in list(positions.items())[:20]:  # Limit to 20
            market = position.get('market', {})
            market_name = market.get('question', 'Unknown')[:35]
            outcome = position.get('outcome', 'unknown').upper()
            tokens = position.get('tokens', 0)
            buy_price = position.get('buy_price', 0)
            token_id = position.get('token_id', '')

            # Get current price and cache stats
            current_price = current_prices.get(token_id, buy_price)
            cache_info = cache_stats.get(token_id, {'hit': False, 'time': 0, 'ttl': 0})

            message_text += f"**{position_index + 1}. {outcome} - {market_name}**\n"
            message_text += f"   📦 Tokens: {tokens:.0f}\n"

            # Add P&L section with current price and color indicator
            if token_id in current_prices:
                pnl_section = format_position_pnl(
                    position,
                    current_price,
                    cache_info['hit'],
                    cache_info['time']
                )
                message_text += pnl_section
            else:
                message_text += f"   💰 Buy Price: ${buy_price:.4f}\n"
                message_text += f"   📈 Current: N/A\n\n"

            # Create button for this position
            button_text = f"{outcome} - {market_name[:25]}..."
            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"pos_{position_index}")
            ])
            position_index += 1

        message_text += "✅ **100% Blockchain Verified**\n"
        message_text += "🔄 **Fresh data from blockchain + Live P&L**"

        # Add cache audit footer
        cache_footer = get_cache_audit_footer(cache_stats)
        message_text += cache_footer

        keyboard.append([InlineKeyboardButton("🔄 Refresh Again", callback_data="refresh_positions")])
        keyboard.append([InlineKeyboardButton("📊 Browse Markets", callback_data="markets_page_0")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Store fresh positions in session
        session = session_manager.get(user_id)
        session['positions'] = positions
        session['current_positions_list'] = list(positions.keys())

        await query.edit_message_text(
            message_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

        logger.info(f"✅ BLOCKCHAIN REFRESH: Updated {len(positions)} positions with live P&L for user {user_id}")

    except Exception as e:
        logger.error(f"❌ BLOCKCHAIN REFRESH ERROR: {e}")
        await query.edit_message_text(
            f"❌ **Error refreshing positions:** {str(e)}\n\nPlease try again.",
            parse_mode='Markdown'
        )


# Analytics callback handlers
async def handle_detailed_pnl(query, session_manager):
    """Handle detailed P&L analysis"""
    user_id = query.from_user.id

    try:
        await query.edit_message_text("📊 **Calculating Detailed P&L...**\n⏳ Fetching real-time data...", parse_mode='Markdown')

        from telegram_bot.services import get_pnl_service
        pnl_service = get_pnl_service()
        portfolio_pnl = await pnl_service.calculate_portfolio_pnl(user_id)

        if 'error' in portfolio_pnl:
            await query.edit_message_text(f"❌ **Error:** {portfolio_pnl['error']}")
            return

        if portfolio_pnl['total_positions'] == 0:
            await query.edit_message_text("📭 **No positions found for detailed analysis.**")
            return

        message_text = f"""
📊 **DETAILED P&L ANALYSIS**

💰 **Portfolio Summary:**
• Total P&L: ${portfolio_pnl['total_pnl']:.2f}
• ROI: {portfolio_pnl['portfolio_roi']:.1f}%
• Realized P&L: ${portfolio_pnl['total_realized_pnl']:.2f}
• Unrealized P&L: ${portfolio_pnl['total_unrealized_pnl']:.2f}

📋 **All Positions:**
        """

        for pos in portfolio_pnl['positions']:
            if 'error' in pos:
                continue

            pos_pnl = pos.get('total_pnl', 0)
            emoji = "🟢" if pos_pnl >= 0 else "🔴"

            message_text += f"""
{emoji} **{pos.get('market_question', 'Unknown')[:30]}...**
   • {pos['current_tokens']:.1f} {pos['outcome'].upper()} @ ${pos.get('current_price', 0):.3f}
   • P&L: ${pos_pnl:.2f} ({pos.get('roi_percentage', 0):.1f}%)
   • Trades: {pos.get('transaction_count', 0)}
            """

        await query.edit_message_text(message_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ Detailed P&L error: {e}")
        await query.edit_message_text(f"❌ **Error:** {str(e)}")


async def handle_trading_stats(query, session_manager):
    """Handle trading statistics display"""
    user_id = query.from_user.id

    try:
        await query.edit_message_text("📈 **Calculating Trading Stats...**", parse_mode='Markdown')

        from telegram_bot.services import get_pnl_service
        pnl_service = get_pnl_service()
        stats = pnl_service.get_trading_statistics(user_id, days=30)

        if 'error' in stats:
            await query.edit_message_text(f"❌ **Error:** {stats['error']}")
            return

        if stats.get('total_trades', 0) == 0:
            await query.edit_message_text("📭 **No trading activity in the last 30 days.**")
            return

        message_text = f"""
📈 **TRADING STATISTICS** (30 days)

🎯 **Activity:**
• Total Trades: {stats['total_trades']}
• Buy Orders: {stats['buy_trades']} 🟢
• Sell Orders: {stats['sell_trades']} 🔴
• Trading Days: {stats['trading_days']}

💰 **Volume:**
• Total: ${stats['total_volume']:.2f}
• Average Trade: ${stats['avg_trade_size']:.2f}
        """

        if stats.get('most_active_day'):
            most_active = stats['most_active_day']
            message_text += f"\n📅 **Most Active:** {most_active['date']} ({most_active['trades']} trades)"

        await query.edit_message_text(message_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ Trading stats error: {e}")
        await query.edit_message_text(f"❌ **Error:** {str(e)}")


async def handle_refresh_pnl(query, session_manager):
    """Handle P&L refresh - OPTIMIZED without FakeUpdate"""
    # Show loading message
    await query.edit_message_text("💰 **Calculating P&L...**", parse_mode='Markdown')

    try:
        user_id = query.from_user.id
        from telegram_bot.services import get_pnl_service

        pnl_service = get_pnl_service()
        result = await pnl_service.calculate_portfolio_pnl(user_id)

        if 'error' in result:
            await query.edit_message_text(f"❌ **Error:** {result['error']}", parse_mode='Markdown')
            return

        # Build P&L message
        total_pnl = result.get('total_pnl', 0)
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        pnl_sign = "+" if total_pnl >= 0 else ""

        message_text = f"""
💰 **Portfolio P&L**

{pnl_emoji} **Total P&L:** {pnl_sign}${total_pnl:.2f}

📊 **Details:**
• Realized P&L: ${result.get('total_realized_pnl', 0):.2f}
• Unrealized P&L: ${result.get('total_unrealized_pnl', 0):.2f}
• Total Invested: ${result.get('total_invested', 0):.2f}
• Active Positions: {result.get('total_positions', 0)}

Use /pnl for detailed analysis
        """

        await query.edit_message_text(message_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"P&L refresh error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}\n\nTry /pnl command instead.", parse_mode='Markdown')


async def handle_view_positions(query, session_manager, position_service, trading_service):
    """Handle view positions - DELETE BUTTON MENU THEN CALL emergency /positions (with TP/SL)"""
    try:
        # Delete the button menu
        await query.message.delete()

        # Call positions command with FORCE REFRESH - shows fresh positions after trade
        from telegram_bot.handlers.positions import positions_command

        class FakeContext:
            args = []  # Commands expect context.args

        class FakeUpdate:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.message = query.message

        fake_update = FakeUpdate(query)
        fake_context = FakeContext()

        # ✅ NEW: Force refresh after trade to show updated positions immediately
        await positions_command(fake_update, fake_context, force_refresh=True)

    except Exception as e:
        logger.error(f"Error calling positions command: {e}")
        await query.message.reply_text(f"❌ Error: {str(e)}\n\nTry /positions")


async def handle_show_pnl(query, session_manager):
    """Handle show P&L"""
    await handle_refresh_pnl(query, session_manager)


async def handle_refresh_history(query, session_manager):
    """Handle history refresh - DELETE BUTTON MENU THEN CALL /history"""
    try:
        # Delete the button menu
        await query.message.delete()

        # Call history command - it will send its own reply
        from telegram_bot.handlers.analytics_handlers import history_command

        class FakeContext:
            args = []  # Commands expect context.args (page 0)

        class FakeUpdate:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.message = query.message

        fake_update = FakeUpdate(query)
        fake_context = FakeContext()
        await history_command(fake_update, fake_context)

    except Exception as e:
        logger.error(f"❌ History callback error: {e}")
        await query.message.reply_text(f"❌ Error: {str(e)}\n\nTry /history")


async def handle_history_page(query, callback_data, session_manager):
    """Handle history pagination"""
    try:
        # Extract page number from callback
        page = int(callback_data.split("_")[-1])

        # Try to delete old message (may already be deleted)
        try:
            await query.message.delete()
        except Exception as del_err:
            logger.warning(f"Could not delete message: {del_err}")

        # Call history command with page number
        from telegram_bot.handlers.analytics_handlers import history_command

        class FakeContext:
            args = [str(page)]  # Pass page number

        class FakeUpdate:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.message = query.message

        fake_update = FakeUpdate(query)
        fake_context = FakeContext()
        await history_command(fake_update, fake_context)

    except Exception as e:
        logger.error(f"❌ History page error: {e}")
        try:
            await query.message.reply_text(f"❌ Error loading page\n\nTry /history")
        except:
            # Message might be deleted, just log
            logger.error(f"Could not send error message")


async def handle_export_history(query, session_manager):
    """Handle history export (placeholder)"""
    await query.edit_message_text("📋 **Export feature coming soon!**\n\nFor now, use /history to view your transactions.", parse_mode='Markdown')


async def handle_show_history(query, session_manager):
    """Handle show history"""
    await handle_refresh_history(query, session_manager)


async def handle_stats_period(query, callback_data, session_manager):
    """Handle stats for different periods"""
    user_id = query.from_user.id

    # Extract period from callback_data (e.g., "stats_7" -> 7)
    period = int(callback_data.split('_')[1])

    try:
        await query.edit_message_text(f"📈 **Calculating {period}-day stats...**", parse_mode='Markdown')

        from telegram_bot.services import get_pnl_service
        pnl_service = get_pnl_service()
        stats = pnl_service.get_trading_statistics(user_id, days=period)

        if 'error' in stats:
            await query.edit_message_text(f"❌ **Error:** {stats['error']}")
            return

        if stats.get('total_trades', 0) == 0:
            await query.edit_message_text(f"📭 **No trading activity in the last {period} days.**")
            return

        message_text = f"""
📈 **TRADING STATISTICS** ({period} days)

🎯 **Activity:**
• Total Trades: {stats['total_trades']}
• Buy/Sell: {stats['buy_trades']}/{stats['sell_trades']}
• Trading Days: {stats['trading_days']}

💰 **Volume:**
• Total: ${stats['total_volume']:.2f}
• Average: ${stats['avg_trade_size']:.2f}
        """

        await query.edit_message_text(message_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ Stats period error: {e}")
        await query.edit_message_text(f"❌ **Error:** {str(e)}")


async def handle_refresh_performance(query, session_manager):
    """Handle performance refresh - OPTIMIZED without FakeUpdate"""
    # Show loading message
    await query.edit_message_text("📊 **Analyzing performance...**", parse_mode='Markdown')

    try:
        user_id = query.from_user.id
        from telegram_bot.services import get_pnl_service

        pnl_service = get_pnl_service()
        result = pnl_service.get_performance_analysis(user_id)

        if 'error' in result:
            await query.edit_message_text(f"❌ **Error:** {result['error']}", parse_mode='Markdown')
            return

        # Build performance message
        message_text = f"""
📊 **Performance Analysis**

💰 **Overall:**
• Total P&L: ${result.get('total_pnl', 0):.2f}
• Win Rate: {result.get('win_rate', 0):.1f}%
• Best Trade: ${result.get('best_trade', 0):.2f}
• Worst Trade: ${result.get('worst_trade', 0):.2f}

📈 **Activity:**
• Total Trades: {result.get('total_trades', 0)}
• Winning Trades: {result.get('winning_trades', 0)}
• Losing Trades: {result.get('losing_trades', 0)}

Use /stats for detailed statistics
        """

        await query.edit_message_text(message_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Performance refresh error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}\n\nTry /stats command instead.", parse_mode='Markdown')


async def handle_trigger_search(query, session_manager):
    """
    Handle search button trigger from /markets command
    Opens ForceReply search prompt
    """
    try:
        from telegram import ForceReply

        user_id = query.from_user.id
        session_manager.init_user(user_id)

        # Send ForceReply prompt
        prompt_msg = await query.message.reply_text(
            f"🔍 **Search Markets**\n\n"
            f"Enter a term to find markets\n\n"
            f"_Examples: trump kim, nba lakers, bitcoin_",
            parse_mode='Markdown',
            reply_markup=ForceReply(selective=True)
        )

        # Set state to await search input
        session_manager.set_search_state(user_id, prompt_msg.message_id)
        logger.info(f"🔍 User {user_id} clicked search button, opened ForceReply prompt")

        # Edit original message to show search was triggered
        await query.edit_message_text(
            "🔍 **Search opened!**\n\n"
            "Enter your search term below ⬆️",
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Trigger search error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text(
            "❌ **Error opening search**\n\n"
            "Please use /search command directly.",
            parse_mode='Markdown'
        )


async def handle_back_to_smart_trading(query, session_manager):
    """
    Handle back button to return to /smart_trading list
    Re-sends the smart trading list from session
    """
    try:
        user_id = query.from_user.id
        logger.info(f"🔙 [BACK_TO_SMART_TRADING] User {user_id} clicked back button")

        # Get session to retrieve pagination data
        session = session_manager.get(user_id)
        pagination = session.get('smart_trades_pagination')

        if not pagination:
            await query.answer("❌ Trade data expired. Please run /smart_trading again.", show_alert=True)
            return

        # Delete the market detail message
        await query.message.delete()

        # Re-send the smart trading list (page 1)
        from .smart_trading_handler import format_smart_trading_message
        message_text, reply_markup = format_smart_trading_message(
            trades=pagination.get('trades', []),
            page_num=1,
            total_pages=pagination.get('total_pages', 1)
        )

        await query.message.reply_text(
            message_text,
            parse_mode='Markdown',
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

        await query.answer("✅ Returned to Smart Trading", show_alert=False)

    except Exception as e:
        logger.error(f"Error in back_to_smart_trading: {e}")
        await query.answer("✅ Use /smart_trading to see the list again", show_alert=False)


async def handle_confirm_restart(query, session_manager):
    """
    Handle restart confirmation (PHASE 3)
    COMPLETELY DELETES user for fresh testing
    """
    try:
        user_id = query.from_user.id

        await query.edit_message_text(
            "🔥 **Deleting your account...**\n\n"
            "⏳ Removing all data...",
            parse_mode='Markdown'
        )

        from database import db_manager, User, LeaderboardEntry, LeaderboardHistory, UserStats, Withdrawal, Fee, TPSLOrder, Transaction

        # COMPLETE DELETION - Remove user from database entirely
        try:
            with db_manager.get_session() as db:
                user = db.query(User).filter(
                    User.telegram_user_id == user_id
                ).first()

                if user:
                    # PHASE 1: Delete ALL related records manually (foreign key cascade not working properly)
                    # Order matters: delete dependent records first

                    # Delete fees (references transactions)
                    db.query(Fee).filter(
                        Fee.user_id == user_id
                    ).delete(synchronize_session=False)

                    # Delete TP/SL orders
                    db.query(TPSLOrder).filter(
                        TPSLOrder.user_id == user_id
                    ).delete(synchronize_session=False)

                    # Delete withdrawals
                    db.query(Withdrawal).filter(
                        Withdrawal.user_id == user_id
                    ).delete(synchronize_session=False)

                    # Delete transactions
                    db.query(Transaction).filter(
                        Transaction.user_id == user_id
                    ).delete(synchronize_session=False)

                    # Delete leaderboard entries
                    db.query(LeaderboardEntry).filter(
                        LeaderboardEntry.user_id == user_id
                    ).delete(synchronize_session=False)

                    # Delete leaderboard history
                    db.query(LeaderboardHistory).filter(
                        LeaderboardHistory.user_id == user_id
                    ).delete(synchronize_session=False)

                    # Delete user stats
                    db.query(UserStats).filter(
                        UserStats.user_id == user_id
                    ).delete(synchronize_session=False)

                    # PHASE 2: Finally delete user
                    db.delete(user)
                    db.commit()
                    success = True
                else:
                    success = False
        except Exception as e:
            logger.error(f"Delete user error: {e}")
            success = False

        if success:
            # Clear session (use private _sessions attribute)
            if user_id in session_manager._sessions:
                del session_manager._sessions[user_id]

            await query.edit_message_text(
                "✅ **Account Completely Deleted!**\n\n"
                "🔥 Everything has been removed:\n"
                "• All wallets deleted\n"
                "• All keys deleted\n"
                "• Transaction history deleted\n"
                "• User record deleted\n\n"
                "🆕 **You're now a brand new user!**\n\n"
                "Use /start to create a fresh account and test the complete onboarding flow!",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "❌ **Deletion Failed**\n\n"
                "Could not delete account. Please try again or contact support.",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"❌ Restart confirmation error: {e}")
        await query.edit_message_text(
            f"❌ **Error:** {str(e)}",
            parse_mode='Markdown'
        )


async def handle_cancel_restart(query):
    """Handle restart cancellation"""
    await query.edit_message_text(
        "❌ **Deletion Cancelled**\n\n"
        "Your account remains unchanged.",
        parse_mode='Markdown'
    )


# ============================================================================
# PHASE 5: Streamlined Start Flow Handlers
# ============================================================================

async def handle_start_streamlined_bridge(query, session_manager):
    """
    PHASE 5: Handle "I've Funded - Start Bridge" button from new /start flow
    Triggers the complete bridge workflow
    """
    user_id = query.from_user.id

    try:
        from core.services import user_service

        # Get user wallets
        user = user_service.get_user(user_id)
        if not user or not user.solana_address:
            await query.edit_message_text(
                "❌ **Wallet not found!**\n\nPlease use /start to create your wallet.",
                parse_mode='Markdown'
            )
            return

        solana_address = user.solana_address
        polygon_address = user.polygon_address

        # Check SOL balance
        try:
            from solana_bridge.solana_transaction import SolanaTransactionBuilder
            solana_tx_builder = SolanaTransactionBuilder()
            sol_balance = await solana_tx_builder.get_sol_balance(solana_address)
        except Exception as e:
            logger.error(f"Error checking SOL balance: {e}")
            sol_balance = 0.0

        if sol_balance < 0.1:
            await query.edit_message_text(
                f"⚠️ **Insufficient Balance**\n\n"
                f"Current balance: {sol_balance:.4f} SOL\n"
                f"Minimum required: 0.1 SOL\n\n"
                f"📍 **Your SOL Address:**\n`{solana_address}`\n\n"
                f"Please fund your wallet first, then try again!",
                parse_mode='Markdown'
            )
            return

        # Prepare bridge confirmation
        sol_to_bridge = max(0.1, sol_balance - 0.01)  # Reserve for fees
        estimated_usdc = sol_to_bridge * 147  # Rough estimate
        estimated_pol = 3.0

        confirmation_text = f"""
🌉 **START BRIDGE CONFIRMATION**

📊 **Bridge Details:**
• Amount: **{sol_to_bridge:.4f} SOL**
• Via: **deBridge (3.5% fee)**
• From: Solana → Polygon
• Time: ~3-5 minutes

💰 **Estimated Output:**
• USDC.e: ~{estimated_usdc:.2f}
• POL (gas): ~{estimated_pol:.1f}

🔶 From: `{solana_address[:8]}...{solana_address[-8:]}`
🔷 To: `{polygon_address[:8]}...{polygon_address[-8:]}`

⚠️ **Important:**
• This will bridge your entire SOL balance
• Cannot be reversed once started
• You'll receive progress updates

**Ready to proceed?**
        """

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = [
            [InlineKeyboardButton("✅ Confirm Bridge", callback_data=f"confirm_bridge_{user_id}_{sol_to_bridge}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_streamlined_bridge")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(confirmation_text, parse_mode='Markdown', reply_markup=reply_markup)

        # Store in session for bridge handler
        session = session_manager.get(user_id)
        session['pending_bridge'] = {
            'sol_amount': sol_to_bridge,
            'solana_address': solana_address,
            'polygon_address': polygon_address
        }
        session['state'] = 'confirming_bridge'

    except Exception as e:
        logger.error(f"Error in handle_start_streamlined_bridge: {e}")
        await query.edit_message_text(
            f"❌ **Error:** {str(e)}\n\nPlease try again or use /bridge command.",
            parse_mode='Markdown'
        )


async def handle_refresh_sol_balance_start(query, session_manager):
    """
    PHASE 5: Refresh SOL balance from /start screen
    Updates the new user flow with current balance
    """
    user_id = query.from_user.id

    try:
        await query.answer("🔄 Refreshing balance...")

        from core.services import user_service

        user = user_service.get_user(user_id)
        if not user or not user.solana_address:
            await query.edit_message_text(
                "❌ **Wallet not found!**\n\nPlease use /start.",
                parse_mode='Markdown'
            )
            return

        solana_address = user.solana_address
        username = query.from_user.username or "Anonymous"

        # Get fresh SOL balance
        try:
            from solana_bridge.solana_transaction import SolanaTransactionBuilder
            solana_tx_builder = SolanaTransactionBuilder()
            sol_balance = await solana_tx_builder.get_sol_balance(solana_address)
        except Exception as e:
            logger.error(f"Error fetching SOL balance: {e}")
            await query.answer("❌ Could not fetch balance. Try again.", show_alert=True)
            return

        balance_status = f"💰 **Current Balance:** {sol_balance:.4f} SOL" if sol_balance > 0 else ""

        welcome_text = f"""
🚀 **POLYMARKET TRADING BOT**
✨ **Personal Wallet Generated**

👤 **Welcome @{username}!**

📍 **Your SOL Address:**
`{solana_address}`

💰 **Fund this address with 0.1+ SOL**
{balance_status}

💡 **What happens next:**
1. 🌉 Bridge SOL → USDC.e + POL **(via deBridge, 3.5% fee)**
2. ⚡ Auto-approve contracts **(30 sec)**
3. 🔑 Generate API keys **(15 sec)**
4. 🚀 **Ready to trade!**

⏱️ **Total time: ~3-5 minutes**

🔒 Your wallets are secure and ready!
        """

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = []

        if sol_balance >= 0.1:
            keyboard.append([InlineKeyboardButton("🌉 I've Funded - Start Bridge", callback_data="start_streamlined_bridge")])
        else:
            keyboard.append([InlineKeyboardButton("🔄 Check Balance", callback_data="refresh_sol_balance_start")])

        keyboard.append([InlineKeyboardButton("💼 View Wallet Details", callback_data="show_wallet")])
        keyboard.append([InlineKeyboardButton("📊 Browse Markets", callback_data="markets_page_0")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error refreshing SOL balance from start: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_refresh_start(query, session_manager):
    """
    PHASE 5: Refresh the /start screen with current user status
    Re-detects user stage and shows appropriate flow
    """
    user_id = query.from_user.id
    username = query.from_user.username or "Anonymous"

    try:
        await query.answer("🔄 Refreshing status...")

        from core.services import user_service
        from core.services.user_states import UserStateValidator, UserStage

        user = user_service.get_user(user_id)
        if not user:
            await query.edit_message_text(
                "❌ **User not found!**\n\nPlease use /start.",
                parse_mode='Markdown'
            )
            return

        # Detect current stage
        stage = UserStateValidator.get_user_stage(user)

        # Show appropriate flow based on stage
        if stage == UserStage.READY:
            await _show_ready_user_flow_callback(query, user, username)
        elif stage == UserStage.SOL_GENERATED:
            await _show_new_user_flow_callback(query, user, username, session_manager)
        elif stage in [UserStage.FUNDED, UserStage.APPROVED]:
            await _show_progress_flow_callback(query, user, username, stage)
        else:
            await _show_new_user_flow_callback(query, user, username, session_manager)

    except Exception as e:
        logger.error(f"Error refreshing start: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def _show_new_user_flow_callback(query, user, username: str, session_manager):
    """Helper for new user flow in callback context"""
    user_id = query.from_user.id
    solana_address = user.solana_address

    try:
        from solana_bridge.solana_transaction import SolanaTransactionBuilder
        solana_tx_builder = SolanaTransactionBuilder()
        sol_balance = await solana_tx_builder.get_sol_balance(solana_address)
    except Exception as e:
        logger.warning(f"Could not fetch SOL balance: {e}")
        sol_balance = 0.0

    balance_status = f"💰 **Current Balance:** {sol_balance:.4f} SOL" if sol_balance > 0 else ""

    welcome_text = f"""
🚀 **POLYMARKET TRADING BOT**
✨ **Personal Wallet Generated**

👤 **Welcome @{username}!**

📍 **Your SOL Address:**
`{solana_address}`

💰 **Fund this address with 0.1+ SOL**
{balance_status}

💡 **What happens next:**
1. 🌉 Bridge SOL → USDC.e + POL **(via deBridge, 3.5% fee)**
2. ⚡ Auto-approve contracts **(30 sec)**
3. 🔑 Generate API keys **(15 sec)**
4. 🚀 **Ready to trade!**

⏱️ **Total time: ~3-5 minutes**

🔒 Your wallets are secure and ready!
    """

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = []

    if sol_balance >= 0.1:
        keyboard.append([InlineKeyboardButton("🌉 I've Funded - Start Bridge", callback_data="start_streamlined_bridge")])
    else:
        keyboard.append([InlineKeyboardButton("🔄 Check Balance", callback_data="refresh_sol_balance_start")])

    keyboard.append([InlineKeyboardButton("💼 View Wallet Details", callback_data="show_wallet")])
    keyboard.append([InlineKeyboardButton("📊 Browse Markets", callback_data="markets_page_0")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)


async def _show_ready_user_flow_callback(query, user, username: str):
    """Helper for ready user flow in callback context"""
    polygon_address = user.polygon_address

    try:
        from core.services import balance_checker
        usdc_balance, _ = balance_checker.check_usdc_balance(polygon_address)
        usdc_balance = f"{usdc_balance:.2f}" if isinstance(usdc_balance, (int, float)) else "Error"
    except Exception as e:
        logger.error(f"Error fetching balance: {e}")
        usdc_balance = "Error"

    welcome_text = f"""
👋 **Welcome back, @{username}!**

**Status:** 🚀 **READY TO TRADE** ✅

💼 **Your Wallet:**
`{polygon_address}`

💰 **USDC.e Balance:** {usdc_balance}

🎯 **Quick Actions:**
• Browse trending markets
• View your positions
• Check transaction history
    """

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = [
        [InlineKeyboardButton("📊 Browse Markets", callback_data="markets_page_0")],
        [InlineKeyboardButton("📈 My Positions", callback_data="view_positions")],
        [InlineKeyboardButton("💼 Wallet Details", callback_data="show_wallet")],
        [InlineKeyboardButton("📜 History", callback_data="show_history")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)


async def _show_progress_flow_callback(query, user, username: str, stage):
    """Helper for progress flow in callback context"""
    from core.services.user_states import UserStage

    if stage == UserStage.FUNDED:
        status_emoji = "⏳"
        status_text = "Bridge/Approval in Progress"
        detail_text = "⚡ Processing bridge and approving contracts...\n⏱️ **Estimated:** 2-3 minutes\n\nYour wallet will be ready soon!"
    elif stage == UserStage.APPROVED:
        status_emoji = "🔑"
        status_text = "Generating API Keys"
        detail_text = "🔑 Creating your API credentials...\n⏱️ **Estimated:** 30 seconds\n\nAlmost ready!"
    else:
        status_emoji = "🔧"
        status_text = "Setting Up"
        detail_text = "⚙️ Completing setup..."

    welcome_text = f"""
{status_emoji} **SETUP IN PROGRESS**

👤 **@{username}**

**Status:** {status_text}

{detail_text}

💡 **Refresh this page in a minute to see updates!**
    """

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Status", callback_data="refresh_start")],
        [InlineKeyboardButton("💼 View Wallet", callback_data="show_wallet")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)


async def handle_cancel_streamlined_bridge(query):
    """Cancel streamlined bridge from Phase 5 flow"""
    await query.edit_message_text(
        "❌ **Bridge Cancelled**\n\n"
        "You can start again anytime with /start or /bridge",
        parse_mode='Markdown'
    )


# ========================================
# NEW MARKETS UI CALLBACKS (Phase 2-4)
# ========================================

async def handle_market_select_callback(query, callback_data, session_manager, market_service):
    """
    NEW Phase 2: Handle market_select_{id}_{page} callbacks
    Shows market details with YES/NO buy buttons
    """
    try:
        from datetime import datetime

        logger.info(f"🔥 [MARKET_SELECT] FUNCTION CALLED! callback_data={callback_data}")

        # Show loading notification immediately (toast at top of screen)
        await query.answer("⏳ Loading...", show_alert=False)

        # Show loading message while fetching data
        await query.edit_message_text(
            "⏳ **Loading market details...**\n\n_Please wait while we fetch the latest data._",
            parse_mode='Markdown'
        )

        logger.info(f"🔥 [MARKET_SELECT] Loading message displayed")

        # Parse callback: market_select_{market_id}_{return_page}
        parts = callback_data.split("_")
        market_id = parts[2]
        return_page = int(parts[3])

        # Clean up any stale session state that might cause issues
        user_id = query.from_user.id
        session = session_manager.get(user_id)
        # Remove any stale market data that might interfere
        if 'current_market' in session and isinstance(session['current_market'], dict):
            stale_market_id = session['current_market'].get('id')
            if stale_market_id and stale_market_id != market_id:
                logger.info(f"🧹 [MARKET_SELECT] Cleaning stale market data from session: {stale_market_id}")
                session.pop('current_market', None)

        logger.info(f"🔍 [MARKET_SELECT] Callback data: {callback_data}")
        logger.info(f"🔍 [MARKET_SELECT] Parsed market_id: {market_id}")
        logger.info(f"🔍 [MARKET_SELECT] Return page: {return_page}")

        # Get market from database with timeout protection
        import asyncio
        logger.info(f"🔍 [MARKET_SELECT] Calling market_service.get_market_by_id({market_id})...")

        try:
            # Add timeout to prevent hanging
            market = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, lambda: market_service.get_market_by_id(market_id)),
                timeout=10.0  # 10 second timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"⏰ [MARKET_SELECT] Timeout getting market {market_id}")
            market = None
        except Exception as e:
            logger.error(f"❌ [MARKET_SELECT] Error getting market {market_id}: {e}")
            market = None

        # FALLBACK: Try with allow_closed=True for markets from smart trading
        # Smart traders sometimes buy markets that are temporarily not tradeable
        if not market:
            logger.warning(f"⚠️ [MARKET_SELECT] Market not found with strict filters, trying with allow_closed=True")
            try:
                market = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: market_service.get_market_by_id(market_id, allow_closed=True)),
                    timeout=10.0  # 10 second timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ [MARKET_SELECT] Timeout getting market {market_id} with allow_closed=True")
                market = None
            except Exception as e:
                logger.error(f"❌ [MARKET_SELECT] Error getting market {market_id} with allow_closed=True: {e}")
                market = None

        logger.info(f"🔍 [MARKET_SELECT] Result: market={'Found' if market else 'NOT FOUND'}")
        if market:
            logger.info(f"🔍 [MARKET_SELECT] Market data keys: {list(market.keys()) if isinstance(market, dict) else type(market)}")
            logger.info(f"🔍 [MARKET_SELECT] Market title: {market.get('title', 'No title')[:50] if isinstance(market, dict) else 'Not dict'}")

        if not market:
            logger.error(f"❌ [MARKET_SELECT] Market not found even with relaxed filters: {market_id}")
            await query.edit_message_text(
                "❌ **Market not found or no longer available.**\n\n"
                "This market may have been:\n"
                "• Delisted from Polymarket\n"
                "• Not yet synced to our database\n"
                "• Expired or closed\n\n"
                "Try refreshing with /markets to see current markets.",
                parse_mode='Markdown'
            )
            return

        # Store market in session
        user_id = query.from_user.id
        session = session_manager.get(user_id)

        # Get user's balance
        from core.services import user_service, balance_checker
        wallet = user_service.get_user_wallet(user_id)
        balance_str = "Error"
        if wallet:
            try:
                usdc_balance, _ = balance_checker.check_usdc_balance(wallet['address'])
                balance_str = f"{usdc_balance:.2f}"
            except Exception as e:
                logger.error(f"Error fetching balance for market view: {e}")
                balance_str = "Error"

        # Check if this is the same market as currently displayed (prevent duplicate edits)
        current_market_id = session.get('current_market', {}).get('id') if isinstance(session.get('current_market'), dict) else None
        logger.info(f"🔍 [MARKET_SELECT] Current market ID in session: {current_market_id}, requested: {market_id}")
        if current_market_id == market_id:
            # Same market - just answer callback to remove loading state
            logger.info(f"🔍 [MARKET_SELECT] Same market detected, returning early")
            await query.answer("✅ Déjà sur ce marché")
            return

        session['current_market'] = market
        session['return_page'] = return_page

        # Format volume
        volume = market.get('volume', 0)
        if volume >= 1_000_000:
            volume_str = f"${volume/1_000_000:.1f}M"
        elif volume >= 1_000:
            volume_str = f"${volume/1_000:.1f}K"
        else:
            volume_str = f"${volume:,.0f}"

        # Format end date
        end_date = market.get('end_date', '')
        if end_date:
            try:
                if isinstance(end_date, str):
                    date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                else:
                    date_obj = end_date
                day = date_obj.day
                suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
                end_date_str = date_obj.strftime(f"%B {day}{suffix}, %Y")
            except:
                end_date_str = "TBD"
        else:
            end_date_str = "TBD"

        # Get current prices and category
        outcome_prices = market.get('outcome_prices', [])
        outcomes = market.get('outcomes', [])
        category = market.get('category', '')  # ✅ FIX: Extract category for emoji selection

        if isinstance(outcome_prices, str):
            import ast
            try:
                outcome_prices = ast.literal_eval(outcome_prices)
            except:
                outcome_prices = []

        # CRITICAL FIX: Ensure outcome_prices is a list, not dict/tuple
        if isinstance(outcome_prices, dict):
            # Handle dict format: {"yes": "0.8", "no": "0.2"}
            outcome_prices = [float(outcome_prices.get("yes", 0.5)), float(outcome_prices.get("no", 0.5))]
        elif isinstance(outcome_prices, tuple):
            # Convert tuple to list
            outcome_prices = list(outcome_prices)
        elif not isinstance(outcome_prices, list):
            # Fallback for any other type
            outcome_prices = [0.5, 0.5]

        # Build message with actual outcomes
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        # ✅ CHECK IF MARKET IS EXPIRED
        is_expired = market.get('is_expired', False)
        expiry_warning = "\n⚠️ **Market Ended** - Trading closed\n" if is_expired else ""

        message_text = f"**{market.get('question') or 'Unknown Market'}**\n\n"
        message_text += f"📊 Volume: {volume_str}\n"
        message_text += f"⏰ Ends: {end_date_str}\n"
        message_text += expiry_warning
        message_text += "\n**Current Prices:**\n"

        # Display all outcomes with their prices
        if len(outcomes) >= 2 and len(outcome_prices) >= len(outcomes):
            # We have outcomes - display them all
            for i, outcome in enumerate(outcomes):
                price = outcome_prices[i] if i < len(outcome_prices) else 0.5
                # Convert to float if it's a string
                price = float(price) if isinstance(price, (str, int, float)) else 0.5
                emoji = "✅" if i == 0 else "❌" if i == 1 else "❓"
                message_text += f"{emoji} {outcome.upper()}: {price*100:.0f}¢ ({price*100:.0f}% chance)\n"
        else:
            # Fallback to YES/NO if we can't parse outcomes
            yes_price = outcome_prices[0] if len(outcome_prices) > 0 else 0.5
            no_price = outcome_prices[1] if len(outcome_prices) > 1 else 0.5
            # Convert to float if it's a string
            yes_price = float(yes_price) if isinstance(yes_price, (str, int, float)) else 0.5
            no_price = float(no_price) if isinstance(no_price, (str, int, float)) else 0.5
            message_text += f"✅ YES: {yes_price*100:.0f}¢ ({yes_price*100:.0f}% chance)\n"
            message_text += f"❌ NO: {no_price*100:.0f}¢ ({no_price*100:.0f}% chance)\n"

        message_text += f"\n💰 **Your Balance:** ${balance_str} USDC\n\n"
        message_text += "What would you like to do?"

        # Create outcome buttons - show custom names for non-YES/NO markets
        keyboard = []

        # ✅ DISABLE BUY BUTTONS IF MARKET IS EXPIRED
        if not is_expired and len(outcomes) >= 2 and len(outcome_prices) >= 2:
            # Get prices
            yes_price = float(outcome_prices[0]) if isinstance(outcome_prices[0], (str, int, float)) else 0.5
            no_price = float(outcome_prices[1]) if isinstance(outcome_prices[1], (str, int, float)) else 0.5

            # Check if it's a YES/NO market or custom outcomes (like team names)
            from telegram_bot.utils.outcome_formatter import should_show_custom_outcomes, get_outcome_emoji

            if should_show_custom_outcomes(outcomes):
                # Custom outcomes - show team/player names
                outcome1_name = outcomes[0]
                outcome2_name = outcomes[1]
                emoji1 = get_outcome_emoji(category, outcome1_name)
                emoji2 = get_outcome_emoji(category, outcome2_name)

                keyboard.append([
                    InlineKeyboardButton(f"{emoji1} Buy {outcome1_name} ({yes_price*100:.0f}¢)", callback_data="buy_prompt_yes"),
                    InlineKeyboardButton(f"{emoji2} Buy {outcome2_name} ({no_price*100:.0f}¢)", callback_data="buy_prompt_no")
                ])
            else:
                # Traditional YES/NO market
                keyboard.append([
                    InlineKeyboardButton(f"Buy YES ({yes_price*100:.0f}¢)", callback_data="buy_prompt_yes"),
                    InlineKeyboardButton(f"Buy NO ({no_price*100:.0f}¢)", callback_data="buy_prompt_no")
                ])

        # ✨ Smart back button - check context priority: smart_trading > event > search > category > markets
        user_id = query.from_user.id
        session = session_manager.get(user_id)
        came_from_smart_trading = session.get('came_from_smart_trading', False)
        last_search_query = session.get('last_search_query', '')
        last_category = session.get('last_category', '')

        # Check if market is part of an event group
        events = market.get('events', [])
        is_part_of_event = events and len(events) > 0

        # Check if user came from push notification (Priority -1: no back button!)
        came_from_notification = session.get('came_from_notification', False)

        if came_from_notification:
            # User came from push notification - NO back button!
            # Clear the flag after using it
            session['came_from_notification'] = False
        elif came_from_smart_trading:
            # Priority 0: User came from /smart_trading - show "Back to Smart Trading"
            keyboard.append([InlineKeyboardButton("💎 Back to Smart Trading", callback_data="back_to_smart_trading")])
            # Clear the flag after using it
            session['came_from_smart_trading'] = False
        elif is_part_of_event:
            # Priority 1: Market is part of an event group - go back to event outcomes view
            event = events[0]  # Get first event (markets typically belong to one event)
            event_id = event.get('event_id')
            event_title = event.get('event_title', 'Event')
            # Truncate title if too long
            display_title = event_title[:30] + "..." if len(event_title) > 30 else event_title
            keyboard.append([InlineKeyboardButton(f"◀️ Back to {display_title}", callback_data=f"event_select_{event_id}_0")])
        elif last_search_query:
            # Priority 2: User came from search - show "Back to Search Results"
            keyboard.append([InlineKeyboardButton("🔍 Back to Search", callback_data=f"search_page_{last_search_query}_0")])
        elif last_category:
            # Priority 3: User came from category - show "Back to [Category]"
            from .category_handlers import CATEGORIES
            category_emoji = next((c['emoji'] for c in CATEGORIES if c['name'].lower() == last_category.lower()), "📊")
            keyboard.append([InlineKeyboardButton(f"{category_emoji} Back to {last_category.capitalize()}", callback_data=f"cat_{last_category}_0")])
        else:
            # Priority 4: Default - show "Back to Markets"
            keyboard.append([InlineKeyboardButton("◀️ Back to Markets", callback_data=f"markets_page_{return_page}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        logger.info(f"🔥 [MARKET_SELECT] About to edit message with final market details - title: {market.get('question', 'No question')[:30]}...")
        await query.edit_message_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)
        logger.info(f"🔥 [MARKET_SELECT] Successfully displayed market details")

    except Exception as e:
        logger.error(f"Error in market_select callback: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        try:
            await query.edit_message_text(f"❌ Error loading market: {str(e)}")
        except Exception as edit_error:
            logger.error(f"Failed to edit message after error: {edit_error}")
            # Try to answer the callback query to remove loading state
            try:
                await query.answer("❌ Error loading market", show_alert=True)
            except:
                pass


async def handle_markets_page_callback(query, callback_data, session_manager, market_service):
    """
    Handle markets_page_{page} callbacks - Edit message to show markets (no delete + FakeUpdate)
    """
    try:
        # Parse page number
        page = int(callback_data.split("_")[2])

        # FIXED: Use same logic for all pages (edit instead of delete + FakeUpdate)
        from telegram import InlineKeyboardMarkup
        from . import trading_handlers
        from market_database import MarketDatabase

        user_id = query.from_user.id
        session = session_manager.get(user_id)
        markets_filter = session.get('markets_filter', {'type': 'volume'})
        filter_type = markets_filter.get('type', 'volume')

        market_db = MarketDatabase()
        markets = await trading_handlers._get_filtered_markets(market_db, filter_type, page)

        if not markets:
            await query.edit_message_text("❌ No more markets available", parse_mode='Markdown')
            return

        if 'markets_filter' not in session:
            session['markets_filter'] = {'type': 'volume'}
        session['markets_filter']['page'] = page

        message_text, keyboard = trading_handlers._build_markets_ui(
            markets=markets,
            view_type='markets',
            context_name='',
            page=page,
            filter_type=filter_type
        )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in markets_page callback: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}\n\nTry /markets", parse_mode='Markdown')


async def handle_search_page_callback(query, callback_data, session_manager):
    """
    PHASE 3: Handle search_page_{query}_{page} callbacks for search result pagination
    """
    try:
        from . import trading_handlers

        # Parse callback data: search_page_{query}_{page}
        # The query can contain underscores, so we use rsplit to get the last part as page
        parts = callback_data.split("_", 2)  # Split into ["search", "page", "{query}_{page}"]
        if len(parts) < 3:
            await query.answer("❌ Invalid search pagination", show_alert=True)
            return

        remainder = parts[2]
        query_and_page = remainder.rsplit('_', 1)  # Split from right to separate query and page

        if len(query_and_page) < 2:
            await query.answer("❌ Invalid search pagination", show_alert=True)
            return

        search_query = query_and_page[0]
        page = int(query_and_page[1])

        logger.info(f"🔍 Search pagination: query='{search_query}', page={page}")

        # Show loading
        await query.answer("⏳ Loading page...", show_alert=False)

        # Edit message to show loading
        await query.edit_message_text(
            "⏳ **Loading search results...**",
            parse_mode='Markdown'
        )

        # Re-execute search with new page
        await trading_handlers._execute_search(search_query, query.message, page=page)

    except ValueError as e:
        logger.error(f"Error parsing search pagination: {e}")
        await query.answer("❌ Invalid page number", show_alert=True)
    except Exception as e:
        logger.error(f"Error in search_page callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.answer("❌ Error loading page", show_alert=True)


async def handle_buy_prompt_callback(query, callback_data, session_manager):
    """
    Handle buy prompt callbacks.
    Supports both old format (buy_prompt_{side}_{market_id}_{page}) and new short format (buy_prompt_{side}).
    """
    try:
        user_id = query.from_user.id
        session = session_manager.get(user_id)

        # Get user's balance
        from core.services import user_service, balance_checker
        wallet = user_service.get_user_wallet(user_id)
        balance_str = "Error"
        if wallet:
            try:
                usdc_balance, _ = balance_checker.check_usdc_balance(wallet['address'])
                balance_str = f"{usdc_balance:.2f}"
            except Exception as e:
                logger.error(f"Error fetching balance for amount prompt: {e}")
                balance_str = "Error"

        # Determine side and context
        parts = callback_data.split("_")
        # New short format: ["buy", "prompt", "yes"]
        if len(parts) == 3:
            side = parts[2]
            market_id = session.get('current_market', {}).get('id')
            return_page = session.get('return_page', 0)
        else:
            # Old format: buy_prompt_{side}_{market_id}_{return_page}
            side = parts[2]
            market_id = parts[3]
            return_page = int(parts[4])

        # Get market from session
        market = session.get('current_market')
        if not market or (market_id and market.get('id') != market_id):
            await query.edit_message_text("❌ Market data lost. Please start over.")
            return

        # Get price for the selected side with freshness check
        outcome_prices = market.get('outcome_prices', [])
        market_updated_at = market.get('updated_at')

        # Check if DB price is fresh (<180s)
        price_is_fresh = False
        if market_updated_at:
            from datetime import datetime, timezone
            if isinstance(market_updated_at, str):
                market_updated_at = datetime.fromisoformat(market_updated_at.replace('Z', '+00:00'))
            age_seconds = (datetime.now(timezone.utc) - market_updated_at).total_seconds()
            price_is_fresh = age_seconds < 180
            logger.info(f"💰 [BUY_QUOTE] Market price age: {age_seconds:.0f}s (fresh: {price_is_fresh})")

        # Parse outcome_prices (existing logic)
        if isinstance(outcome_prices, str):
            import ast
            try:
                outcome_prices = ast.literal_eval(outcome_prices)
            except:
                outcome_prices = [0.5, 0.5]

        # CRITICAL FIX: Ensure outcome_prices is a list, not dict/tuple
        if isinstance(outcome_prices, dict):
            # Handle dict format: {"yes": "0.8", "no": "0.2"}
            outcome_prices = [float(outcome_prices.get("yes", 0.5)), float(outcome_prices.get("no", 0.5))]
        elif isinstance(outcome_prices, tuple):
            # Convert tuple to list
            outcome_prices = list(outcome_prices)
        elif not isinstance(outcome_prices, list):
            # Fallback for any other type
            outcome_prices = [0.5, 0.5]

        # Get price from DB or API based on freshness
        price = 0.5  # Default fallback
        if price_is_fresh and len(outcome_prices) >= 2:
            # Use fresh DB price
            try:
                if side.lower() == "yes":
                    price = float(outcome_prices[0])
                elif side.lower() == "no":
                    price = float(outcome_prices[1])
                logger.info(f"✅ [BUY_QUOTE] Using fresh DB price: ${price:.4f}")
            except (IndexError, ValueError, TypeError) as e:
                logger.warning(f"Error parsing DB price: {e}, falling back to API")
                price_is_fresh = False  # Force API fetch

        if not price_is_fresh:
            # Fetch live price from CLOB API
            logger.info(f"⚠️ [BUY_QUOTE] DB price stale (age: {age_seconds if market_updated_at else 'unknown'}s), fetching from CLOB API...")
            try:
                # Use same simple approach as speed_sell: get_price from client
                from py_clob_client.client import ClobClient
                from py_clob_client.constants import POLYGON

                # Create a simple read-only client (no auth needed for price queries)
                clob_client = ClobClient(host="https://clob.polymarket.com", chain_id=POLYGON)

                clob_token_ids = market.get('clob_token_ids', [])

                # Parse clob_token_ids if it's stored as JSON string (from DB)
                if isinstance(clob_token_ids, str):
                    import json
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"⚠️ [BUY_QUOTE] Failed to parse clob_token_ids JSON: {clob_token_ids}")
                        clob_token_ids = []

                if clob_token_ids and len(clob_token_ids) >= 2:
                    token_id = clob_token_ids[0 if side.lower() == "yes" else 1]

                    # Use the same simple get_price method as speed_sell
                    price_data = clob_client.get_price(token_id, "BUY")  # BUY side for buying
                    fresh_price = float(price_data.get('price', 0))

                    if fresh_price > 0:
                        price = fresh_price
                        logger.info(f"✅ [BUY_QUOTE] Using fresh CLOB price: ${price:.4f}")
                    else:
                        # Fallback to DB price even if stale
                        price = float(outcome_prices[0 if side.lower() == "yes" else 1])
                        logger.warning(f"⚠️ [BUY_QUOTE] CLOB returned zero price, using stale DB price: ${price:.4f}")
                else:
                    # No token IDs available, use DB price
                    price = float(outcome_prices[0 if side.lower() == "yes" else 1]) if len(outcome_prices) >= 2 else 0.5
                    logger.warning(f"⚠️ [BUY_QUOTE] No token IDs, using DB price: ${price:.4f}")
            except Exception as e:
                logger.error(f"❌ [BUY_QUOTE] API price fetch error: {e}")
                # Final fallback to DB price
                try:
                    price = float(outcome_prices[0 if side.lower() == "yes" else 1]) if len(outcome_prices) >= 2 else 0.5
                    logger.warning(f"⚠️ [BUY_QUOTE] Using DB fallback price: ${price:.4f}")
                except:
                    price = 0.5

        # Store order details in session
        session['pending_order'] = {
            'market_id': market_id,
            'side': side,
            'return_page': return_page,
            'price': price
        }
        # Set awaiting_amount state to allow direct numeric input
        session['state'] = 'awaiting_amount'

        # Calculate example shares for quick amounts
        shares_5 = int(5 / price) if price > 0 else 0
        shares_10 = int(10 / price) if price > 0 else 0
        shares_20 = int(20 / price) if price > 0 else 0

        # Build prompt message with buttons
        side_display = side.upper()
        message_text = f"💰 **How much do you want to spend?**\n\n"
        message_text += f"Market: {market.get('title') or 'Unknown Market'}\n"
        message_text += f"Side: {side_display} ({price*100:.0f}¢)\n\n"
        message_text += f"💵 **Your Balance:** ${balance_str} USDC\n\n"
        message_text += "**Quick amounts or enter custom:**"

        # Create quick buy buttons
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [
                InlineKeyboardButton(f"$5 (~{shares_5} shares)", callback_data="quick_buy_5"),
                InlineKeyboardButton(f"$10 (~{shares_10} shares)", callback_data="quick_buy_10")
            ],
            [
                InlineKeyboardButton(f"$20 (~{shares_20} shares)", callback_data="quick_buy_20"),
                InlineKeyboardButton("💰 Custom Amount", callback_data="buy_custom")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error in buy_prompt callback: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


async def handle_category_callback(query, callback_data, session_manager, market_service):
    """
    Handle cat_{category}_{page} callbacks for category pagination
    """
    try:
        # Parse: cat_politics_0, cat_trump_1, etc.
        parts = callback_data.split("_")
        category = parts[1]
        page = int(parts[2])

        # Import the category handler function
        from .category_handlers import show_category_markets

        # Create fake update object for category handler
        class FakeUpdate:
            def __init__(self, query):
                self.callback_query = query

        fake_update = FakeUpdate(query)

        # Get market_db
        from market_database import MarketDatabase
        market_db = MarketDatabase()

        # Call the category handler with pagination
        await show_category_markets(fake_update, None, session_manager, market_db, category, page)

    except Exception as e:
        logger.error(f"Error in category callback: {e}")
        await query.answer(f"Error: {str(e)}")


async def handle_category_menu_callback(query):
    """
    Handle cat_menu callback - show category selection menu
    """
    try:
        # Answer the callback query immediately to remove loading state
        await query.answer()

        # Import the menu function
        from .category_handlers import show_category_menu

        # Create fake update object
        class FakeUpdate:
            def __init__(self, query):
                self.callback_query = query

        fake_update = FakeUpdate(query)

        # Show category menu
        await show_category_menu(fake_update, None)

    except Exception as e:
        logger.error(f"Error showing category menu: {e}")
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_trending_markets_callback(query, session_manager):
    """
    Handle trending_markets callback - show top volume markets across all categories
    """
    try:
        from telegram import InlineKeyboardMarkup
        from .trading_handlers import _build_markets_ui
        from core.services.market_data_layer import get_market_data_layer

        await query.answer()

        user_id = query.from_user.id
        session_manager.init_user(user_id)

        # Get top volume markets (trending) using MarketDataLayer
        market_layer = get_market_data_layer()
        paginated_items, total = market_layer.get_high_volume_markets_page(
            page=0,
            page_size=10,
            group_by_events=True
        )

        if not paginated_items:
            await query.edit_message_text(
                "❌ No trending markets available at the moment.",
                parse_mode='Markdown'
            )
            return

        # Build UI with trending context
        message_text, keyboard = _build_markets_ui(
            markets=paginated_items,
            view_type='trending',  # Special view type for trending
            context_name='',
            page=0,
            filter_type='volume'
        )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

        logger.info(f"✅ Trending markets displayed for user {user_id}")

    except Exception as e:
        logger.error(f"Error showing trending markets: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.answer(f"Error: {str(e)}")


async def handle_market_filter_callback(query, callback_data, session_manager, market_db):
    """
    Handle filter_{type}_{page} callbacks for main markets

    Format: filter_volume_0, filter_trending_2, etc.
    """
    try:
        from telegram import InlineKeyboardMarkup
        from .trading_handlers import _get_filtered_markets, _build_markets_ui

        # Parse: filter_volume_0
        parts = callback_data.split("_")
        filter_type = parts[1]  # 'volume', 'trending', etc.
        page = int(parts[2])

        user_id = query.from_user.id
        session = session_manager.get(user_id)

        # Store filter in session
        session['market_filter'] = filter_type
        session['market_filter_page'] = page

        # Get filtered markets
        markets = await _get_filtered_markets(market_db, filter_type, page)

        if not markets:
            await query.answer("No markets found for this filter.")
            return

        # Build UI
        message_text, keyboard = _build_markets_ui(markets, 'markets', '', page, filter_type)

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.answer()
        await query.edit_message_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in market filter callback: {e}")
        await query.answer(f"Error: {str(e)}")


async def handle_category_filter_callback(query, callback_data, session_manager, market_db):
    """
    Handle catfilter_{category}_{type}_{page} callbacks for category views

    Format: catfilter_politics_volume_0, catfilter_trump_trending_1, etc.
    """
    try:
        from telegram import InlineKeyboardMarkup
        from .category_handlers import _get_filtered_category_markets
        from .trading_handlers import _build_markets_ui

        # Parse: catfilter_politics_volume_0
        parts = callback_data.split("_")
        category = parts[1]  # 'politics', 'trump', etc.
        filter_type = parts[2]  # 'volume', 'trending', etc.
        page = int(parts[3])

        user_id = query.from_user.id
        session = session_manager.get(user_id)

        # Store filter in session
        session['category_filter'] = filter_type
        session['category_filter_page'] = page

        # Get filtered category markets
        markets = await _get_filtered_category_markets(market_db, category, filter_type, page)

        if not markets:
            await query.answer("No markets found in this category.")
            return

        # Build UI
        message_text, keyboard = _build_markets_ui(markets, 'category', category, page, filter_type)

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.answer()
        await query.edit_message_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in category filter callback: {e}")
        await query.answer(f"Error: {str(e)}")


def register(app: Application, session_manager, trading_service, position_service, market_service):
    """Register callback handler"""
    from functools import partial
    from telegram.ext import filters
    from .callbacks import initialize_registry

    # Initialize the callback registry (copy_trading, bridge, etc. callbacks)
    initialize_registry()

    # Bind all dependencies
    callback_with_deps = partial(
        button_callback,
        session_manager=session_manager,
        trading_service=trading_service,
        position_service=position_service,
        market_service=market_service
    )

    # Create custom filter to EXCLUDE withdrawal callbacks (handled by ConversationHandler)
    def not_withdrawal_callback(data):
        """Filter to exclude withdrawal-related callbacks"""
        return data not in ["withdraw_sol", "withdraw_usdc", "cancel_withdrawal", "confirm_withdrawal"]

    # Register with filter to exclude withdrawal callbacks
    app.add_handler(CallbackQueryHandler(
        callback_with_deps,
        pattern=not_withdrawal_callback
    ))


async def handle_event_select_callback(query, callback_data, session_manager, market_db):
    """
    Handle event selection (Win/Draw/Win outcomes) using Events API

    Callback formats:
    - event_select_{event_id}_{page}
    - group_select_{market_group_id}_{page} (legacy support)

    Shows all outcomes in the event and allows user to pick which one to trade
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import datetime
    from core.services.market_group_cache import get_market_group_cache

    try:
        # Get cache instance
        group_cache = get_market_group_cache()

        # Show loading notification immediately (toast at top of screen)
        await query.answer("⏳ Loading event...", show_alert=False)

        # Show loading message while fetching data
        await query.edit_message_text(
            "⏳ **Loading event outcomes...**\n\n_Please wait while we fetch the latest data._",
            parse_mode='Markdown'
        )

        # Parse callback data
        # Format: event_select_{event_id}_{page} or group_select_{group_id}_{page}
        # event_id can contain underscores (e.g., slug_will-in-the-2028)
        # So we use rsplit to isolate the page number at the end

        # Support both event_select and group_select (legacy)
        if callback_data.startswith("event_select_"):
            # Remove "event_select_" prefix
            remainder = callback_data[len("event_select_"):]
            # Split from the right to get page (last part) and event_id (everything else)
            parts = remainder.rsplit('_', 1)
            event_id = parts[0]
            page = int(parts[1]) if len(parts) > 1 else 0
            logger.info(f"📋 User {query.from_user.id} selected event {event_id}")

            # FIX: Query subsquid_markets_poll directly instead of old markets table
            from database import SubsquidMarketPoll, db_manager
            from datetime import datetime, timezone
            from sqlalchemy import cast, text, or_  # ✅ Add or_ to imports
            from sqlalchemy.dialects.postgresql import JSONB

            markets = []
            try:
                with db_manager.get_session() as db:
                    now = datetime.now(timezone.utc)

                    # Query markets by event_id from the events JSONB field
                    # The events field contains: [{"event_id": "23246", "event_title": "..."}]
                    # event_id is stored as a STRING, not an integer!

                    # Use raw SQL with proper JSONB syntax - more reliable than SQLAlchemy cast
                    from sqlalchemy import func
                    query_result = db.query(SubsquidMarketPoll).filter(
                        SubsquidMarketPoll.status == 'ACTIVE',
                        SubsquidMarketPoll.accepting_orders == True,
                        SubsquidMarketPoll.archived == False,
                        func.jsonb_path_exists(
                            SubsquidMarketPoll.events,
                            f'$[*] ? (@.event_id == "{event_id}")'
                        ),  # JSONB path query - works with strings!
                        or_(
                            SubsquidMarketPoll.end_date == None,
                            SubsquidMarketPoll.end_date > now
                        )
                    ).order_by(SubsquidMarketPoll.volume.desc()).all()

                    # Convert to dict format
                    for m in query_result:
                        markets.append({
                            'id': m.market_id,
                            'market_id': m.market_id,
                            'title': m.title,
                            'question': m.title,
                            'volume': float(m.volume) if m.volume else 0,
                            'liquidity': float(m.liquidity) if m.liquidity else 0,
                            'end_date': m.end_date,
                            'category': m.category,
                            'events': m.events,
                            'outcome_prices': m.outcome_prices,
                            'clob_token_ids': m.clob_token_ids,
                            'outcomes': m.outcomes,
                            'active': True,
                            'closed': False
                        })

                    logger.info(f"✅ Found {len(markets)} markets in event {event_id} from subsquid_markets_poll")
            except Exception as e:
                logger.error(f"❌ Error querying subsquid_markets_poll for event {event_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        else:  # group_select (legacy)
            remainder = callback_data[len("group_select_"):]
            parts = remainder.rsplit('_', 1)
            market_group_id = int(parts[0])
            page = int(parts[1]) if len(parts) > 1 else 0
            logger.info(f"📋 User {query.from_user.id} selected market group {market_group_id} (legacy)")
            markets = market_db.get_markets_in_group(market_group_id)
            event_id = f"legacy_{market_group_id}"

        if not markets:
            logger.error(f"❌ No markets found for event {event_id}")
            await query.edit_message_text(
                "❌ Market group not found or no longer available.",
                parse_mode='Markdown'
            )
            return

        # 🚀 OPTIMIZATION: Pre-cache tous les marchés de cet événement
        # L'utilisateur va probablement cliquer sur un des outcomes
        # Cela réduit le temps de réponse de 250ms → 10ms (25x plus rapide)
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        cached_count = 0
        for market in markets:
            market_id = str(market.get('id'))
            from config.config import MARKET_LIST_TTL
            if redis_cache.cache_market_data(market_id, market, ttl=MARKET_LIST_TTL):
                cached_count += 1

        if cached_count > 0:
            logger.info(f"📦 Pre-cached {cached_count}/{len(markets)} markets from event {event_id} (TTL: 120s)")

        # Format event display
        from core.services.market_grouping_service import MarketGroupingService
        grouping_service = MarketGroupingService()

        formatted = grouping_service.format_group_for_display(event_id, markets)

        # Build message
        event_title = formatted.get('event_title', 'Unknown Event')
        total_volume = formatted.get('total_volume', 0)

        # Format volume
        if total_volume >= 1_000_000:
            volume_str = f"${total_volume/1_000_000:.1f}M"
        elif total_volume >= 1_000:
            volume_str = f"${total_volume/1_000:.1f}K"
        else:
            volume_str = f"${total_volume:,.0f}"

        # Format end date
        end_date = formatted.get('end_date')
        if end_date:
            try:
                if isinstance(end_date, str):
                    date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                else:
                    date_obj = end_date
                day = date_obj.day
                suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
                end_date_str = date_obj.strftime(f"%B {day}{suffix}, %Y")
            except:
                end_date_str = "TBD"
        else:
            end_date_str = "TBD"

        message = f"📊 **{event_title}**\n\n"
        message += f"💰 Total Volume: {volume_str}\n"
        message += f"⏰ Ends: {end_date_str}\n\n"

        # List outcomes with pagination (10 per page)
        outcomes = formatted.get('outcomes', [])
        outcomes_per_page = 10
        total_outcomes = len(outcomes)
        total_pages = (total_outcomes + outcomes_per_page - 1) // outcomes_per_page

        # Paginate outcomes
        start_idx = page * outcomes_per_page
        end_idx = min(start_idx + outcomes_per_page, total_outcomes)
        page_outcomes = outcomes[start_idx:end_idx]

        message += f"**Outcomes ({start_idx + 1}-{end_idx} of {total_outcomes}):**\n\n"

        # STEP 1: Build message text showing all outcomes
        for i, outcome in enumerate(page_outcomes, start=start_idx + 1):
            title = outcome.get('title', 'Unknown')
            price = outcome.get('price')
            vol = outcome.get('volume', 0)

            # Format price (Yes outcome probability)
            if price is not None:
                yes_price_pct = int(price * 100)
                no_price_pct = 100 - yes_price_pct
                yes_price_str = f"{yes_price_pct}¢"
                no_price_str = f"{no_price_pct}¢"
            else:
                yes_price_str = "N/A"
                no_price_str = "N/A"

            # Format volume
            if vol >= 1_000_000:
                vol_str = f"${vol/1_000_000:.1f}M"
            elif vol >= 1_000:
                vol_str = f"${vol/1_000:.0f}K"
            else:
                vol_str = f"${vol:.0f}"

            # Build outcome display with smart YES/NO or custom outcome names
            from telegram_bot.utils.outcome_formatter import format_outcome_display

            # Get outcomes and prices for smart formatting
            outcomes = outcome.get('outcomes', [])
            prices = outcome.get('outcome_prices', [])
            category = outcome.get('category', '')

            # Format outcomes (will show YES/NO or custom team/player names)
            outcome_display = format_outcome_display(outcomes, prices, category)

            message += f"{i}. **{title}**\n"
            message += f"   Vol: {vol_str}  •  {outcome_display}\n\n"

        # STEP 2: Build numbered buttons in rows of 4 (mobile-friendly!)
        keyboard = []
        button_row = []

        for i, outcome in enumerate(page_outcomes, start=start_idx + 1):
            market_id = outcome.get('market_id')

            # Add numbered button to current row
            button_row.append(
                InlineKeyboardButton(str(i), callback_data=f"market_select_{market_id}_0")
            )

            # When row has 4 buttons OR it's the last button, add row to keyboard
            if len(button_row) == 4 or i == (start_idx + len(page_outcomes)):
                keyboard.append(button_row)
                button_row = []  # Reset for next row

        # Add pagination buttons if needed
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"event_select_{event_id}_{page-1}"))
        if end_idx < total_outcomes:
            nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"event_select_{event_id}_{page+1}"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Add back button
        # ✨ Smart back button - check context priority: search > category > markets
        user_id = query.from_user.id
        session = session_manager.get(user_id)
        last_search_query = session.get('last_search_query', '')
        last_category = session.get('last_category', '')

        if last_search_query:
            # Priority 1: User came from search - show "Back to Search Results"
            keyboard.append([
                InlineKeyboardButton("🔍 Back to Search", callback_data=f"search_page_0_{last_search_query}")
            ])
        elif last_category:
            # Priority 2: User came from category - show "Back to [Category]"
            from .category_handlers import CATEGORIES
            category_emoji = next((c['emoji'] for c in CATEGORIES if c['name'].lower() == last_category.lower()), "📊")
            keyboard.append([
                InlineKeyboardButton(f"{category_emoji} Back to {last_category.capitalize()}", callback_data=f"cat_{last_category}_0")
            ])
        else:
            # Priority 3: User came from general markets - show "Back to Markets"
            keyboard.append([
                InlineKeyboardButton("◀️ Back to Markets", callback_data=f"markets_page_0")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error handling group select: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text(
            "❌ Error loading market group. Please try again.",
            parse_mode='Markdown'
        )

    logger.info("✅ Callback handlers registered (excluding withdrawal callbacks)")


async def handle_smart_view_market_callback(query, callback_data, session_manager, market_service):
    """
    Handle view market callback for smart wallet trades
    Format: smart_view_{trade_number}
    Retrieves market_id from session storage (supports pagination)
    """
    try:
        # Parse trade number
        trade_num = int(callback_data.replace("smart_view_", ""))
        trade_index = trade_num - 1  # Convert to 0-based index

        user_id = query.from_user.id
        session = session_manager.get(user_id)

        logger.info(f"🔍 [SMART_VIEW] User {user_id} clicked smart_view_{trade_num}")
        logger.info(f"🔍 [SMART_VIEW] Trade index: {trade_index}")

        # Try new pagination format first
        pagination = session.get('smart_trades_pagination')
        if pagination:
            # New pagination format - find trade by global index
            all_trades = pagination.get('trades', [])
            trade_data = next((t for t in all_trades if t['index'] == trade_num), None)

            if not trade_data:
                logger.warning(f"⚠️ [SMART_VIEW] Trade #{trade_num} not found in pagination")
                await query.edit_message_text("❌ Trade data expired. Please run /smart_trading again.")
                return

            market_id = trade_data.get('market_id')
        else:
            # Fallback to old format for backwards compatibility
            smart_trades = session.get('smart_trades', [])
            logger.info(f"🔍 [SMART_VIEW] Session has {len(smart_trades)} smart_trades (old format)")

            if not smart_trades or trade_index >= len(smart_trades):
                logger.warning(f"⚠️ [SMART_VIEW] Trade index {trade_index} out of range (total: {len(smart_trades)})")
                await query.edit_message_text("❌ Trade data expired. Please run /smart_trading again.")
                return

            # Get the specific trade
            trade_data = smart_trades[trade_index]
            market_id = trade_data.get('market_id')

        logger.info(f"🔍 [SMART_VIEW] Retrieved trade_data: {trade_data}")
        logger.info(f"🔍 [SMART_VIEW] Market ID from session: {market_id}")

        if not market_id:
            logger.error(f"❌ [SMART_VIEW] No market_id in trade_data!")
            await query.edit_message_text("❌ Market ID not found.")
            return

        # Store context for back button
        user_id = query.from_user.id
        session = session_manager.get(user_id)
        session['came_from_smart_trading'] = True

        # Try to get market by ID first (will fail for trades with mismatched condition_id)
        market = market_service.get_market_by_id(market_id, allow_closed=True)

        # FALLBACK: If not found by ID, try searching by title
        # This handles the case where condition_id from Subsquid doesn't match Gamma API
        if not market:
            market_title = trade_data.get('market_question')
            if market_title:
                logger.warning(f"⚠️ [SMART_VIEW] Market not found by ID, trying title search: {market_title[:50]}...")
                market = market_service.search_by_title(market_title, fuzzy=True)

                if market:
                    logger.info(f"✅ [SMART_VIEW] Found market by title! Using market_id: {market['id']}")
                    # Update market_id to the correct one from database
                    market_id = market['id']
                else:
                    logger.error(f"❌ [SMART_VIEW] Market not found by ID or title!")
                    await query.edit_message_text(
                        "❌ **Market not found.**\n\n"
                        "This market may have been:\n"
                        "• Delisted from Polymarket\n"
                        "• Expired or resolved\n\n"
                        "_Try /smart_trading again for current opportunities._",
                        parse_mode='Markdown'
                    )
                    return

        # Redirect to standard market view callback
        logger.info(f"🔍 [SMART_VIEW] Calling handle_market_select_callback with market_id={market_id}")
        logger.info(f"🔍 [SMART_VIEW] About to call handle_market_select_callback_new_message...")
        # CHANGE: Send as NEW message instead of editing current one
        # This prevents the smart_trading list from being replaced
        await handle_market_select_callback_new_message(query, f"market_select_{market_id}_0", session_manager, market_service)
        logger.info(f"✅ [SMART_VIEW] handle_market_select_callback_new_message returned!")

    except ValueError:
        await query.answer("❌ Invalid trade number", show_alert=True)
    except Exception as e:
        logger.error(f"Error in smart view market callback: {e}")
        await query.answer("❌ Error loading market", show_alert=True)



async def handle_market_select_callback_new_message(query, callback_data, session_manager, market_service):
    """
    Wrapper for handle_market_select_callback that sends result as NEW message
    Instead of editing the current message (which would hide the smart trading list)
    """
    try:
        logger.info(f"🔥 [MARKET_SELECT_NEW_MSG] CALLED! callback_data={callback_data}")

        # Create a fake query object that will send to a new message
        class FakeQuery:
            def __init__(self, real_query):
                self.real_query = real_query
                self.from_user = real_query.from_user
                self.message = real_query.message
                self._message_sent = None

            async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
                """Instead of editing, send a new message"""
                logger.info(f"🔥 [FAKE_QUERY] edit_message_text called, sending NEW message instead")
                self._message_sent = await self.message.reply_text(
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                logger.info(f"✅ [FAKE_QUERY] NEW message sent!")

            async def answer(self, text=None, show_alert=False):
                """Pass through to real query"""
                await self.real_query.answer(text, show_alert=show_alert)

        fake_query = FakeQuery(query)

        logger.info(f"🔥 [MARKET_SELECT_NEW_MSG] About to call handle_market_select_callback...")
        # Call the original handler with the fake query
        await handle_market_select_callback(fake_query, callback_data, session_manager, market_service)
        logger.info(f"✅ [MARKET_SELECT_NEW_MSG] handle_market_select_callback completed!")

        # Always show a brief confirmation that it was sent as new message
        await query.answer("📊 Market details sent below!", show_alert=False)

    except Exception as e:
        logger.error(f"❌ [MARKET_SELECT_NEW_MSG] Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.answer("❌ Error loading market", show_alert=True)

async def handle_smart_custom_buy_callback(query, callback_data, session_manager, trading_service, market_service):
    """
    Handle smart wallet custom buy callback
    Format: scb_{market_id_short}_{outcome_initial}
    Example: scb_0x308d5a20_Y

    This prompts the user to enter a custom amount for the trade.
    """
    try:
        logger.info(f"🔥 [SMART_CUSTOM_BUY] CALLED! callback_data={callback_data}")

        # Parse callback data: scb_0x308d5a20_Y
        parts = callback_data.split("_")
        logger.info(f"🔥 [SMART_CUSTOM_BUY] Parsed parts: {parts}")

        if len(parts) < 3:
            await query.answer("❌ Invalid button data", show_alert=True)
            return

        # parts[0] = "scb"
        # parts[1] = shortened market_id (e.g., "0x308d5a20")
        # parts[2] = outcome initial (Y or N)
        market_id_short = parts[1]
        outcome_initial = parts[2]

        # Map outcome initial back to full name
        outcome_map = {'Y': 'YES', 'N': 'NO', 'T': 'T1', 'F': 'T2'}  # Support multi-outcome
        outcome = outcome_map.get(outcome_initial.upper(), 'YES')

        logger.info(f"🔍 [SMART_CUSTOM_BUY] Parsed callback: market_short={market_id_short}, outcome={outcome}")

        # Get full market_id from session (we need to find the trade with this shortened ID)
        user_id = query.from_user.id
        session = session_manager.get(user_id)

        pagination = session.get('smart_trades_pagination')
        if not pagination:
            await query.answer("❌ Trade data expired. Please run /smart_trading again.", show_alert=True)
            return

        # Find the trade that matches this shortened market_id
        all_trades = pagination.get('trades', [])
        matching_trade = None
        for trade in all_trades:
            trade_market_id = trade.get('market_id', '')
            # Check if this trade's market_id starts with the shortened version
            if trade_market_id.startswith(market_id_short):
                matching_trade = trade
                break

        if not matching_trade:
            logger.error(f"❌ [SMART_CUSTOM_BUY] No trade found matching {market_id_short}")
            await query.answer("❌ Trade not found. Please run /smart_trading again.", show_alert=True)
            return

        market_id = matching_trade.get('market_id')
        market_question = matching_trade.get('market_question', 'Unknown Market')

        logger.info(f"✅ [SMART_CUSTOM_BUY] Found matching trade: market_id={market_id[:20]}...")

        # Check wallet readiness
        from core.services import user_service
        wallet_ready, status_msg = user_service.is_wallet_ready(user_id)
        if not wallet_ready:
            await query.answer(f"❌ {status_msg}", show_alert=True)
            return

        # Acknowledge button click
        await query.answer("💰 Enter custom amount...", show_alert=False)

        # Send prompt for custom amount as a new message
        prompt_msg = await query.message.reply_text(
            f"💰 *Custom Buy Order*\n\n"
            f"📊 Market: {market_question[:60]}...\n"
            f"📈 Side: BUY {outcome}\n\n"
            f"Please enter your buy amount in USD:\n"
            f"_Example: 10 (for $10)_\n\n"
            f"💡 Min: $2  •  Max: Your wallet balance",
            parse_mode='Markdown'
        )

        # Store pending trade in session for the next message handler
        from ..session_manager import session_manager as sm
        session = sm.get(user_id)
        session['pending_trade'] = {
            'market_id': market_id,
            'outcome': outcome,
            'action': 'buy',
            'source': 'smart_trading_custom',
            'market_question': market_question  # Store for title fallback
        }
        # Set state to awaiting_buy_amount so text handler picks it up
        session['state'] = 'awaiting_buy_amount'

        logger.info(f"✅ [SMART_CUSTOM_BUY] Stored pending trade for user {user_id}, state=awaiting_buy_amount")

    except ValueError as e:
        logger.error(f"❌ [SMART_CUSTOM_BUY] ValueError: {e}")
        await query.answer("❌ Invalid button format", show_alert=True)
    except Exception as e:
        logger.error(f"❌ [SMART_CUSTOM_BUY] Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.answer("❌ Error processing request", show_alert=True)


async def handle_smart_quick_buy_callback(query, callback_data, session_manager, trading_service, market_service):
    """
    Handle smart wallet quick buy callback
    Format: smart_buy_{trade_number}
    Retrieves market_id and outcome from session storage (supports pagination)
    """
    try:
        # Parse trade number
        trade_num = int(callback_data.replace("smart_buy_", ""))
        trade_index = trade_num - 1  # Convert to 0-based index

        user_id = query.from_user.id
        session = session_manager.get(user_id)

        # Try new pagination format first
        pagination = session.get('smart_trades_pagination')
        if pagination:
            # New pagination format - find trade by global index
            all_trades = pagination.get('trades', [])
            trade_data = next((t for t in all_trades if t['index'] == trade_num), None)

            if not trade_data:
                await query.edit_message_text("❌ Trade data expired. Please run /smart_trading again.")
                return
        else:
            # Fallback to old format for backwards compatibility
            smart_trades = session.get('smart_trades', [])
            if not smart_trades or trade_index >= len(smart_trades):
                await query.edit_message_text("❌ Trade data expired. Please run /smart_trading again.")
                return

            # Get the specific trade
            trade_data = smart_trades[trade_index]

        market_id = trade_data.get('market_id')
        outcome = trade_data.get('outcome')
        amount = 2.0  # Fixed $2 quick buy

        if not market_id or not outcome:
            await query.edit_message_text("❌ Invalid trade data.")
            return

        # Check wallet readiness
        from core.services import user_service
        wallet_ready, status_msg = user_service.is_wallet_ready(user_id)
        if not wallet_ready:
            await query.answer(f"❌ Wallet not ready: {status_msg}")
            await query.edit_message_text(
                f"❌ *Trading Not Available*\n\n{status_msg}\n\nUse /wallet to complete setup.",
                parse_mode='Markdown'
            )
            return

        await query.answer("⚡ Executing quick buy order...")

        # Get market data - add logging for debugging
        logger.info(f"🔍 [SMART_BUY] Looking up market: {market_id[:20]}... (NOV4 FORCE REDEPLOY)")
        logger.info(f"🔍 [SMART_BUY] trade_data keys: {list(trade_data.keys())}")
        logger.info(f"🔍 [SMART_BUY] market_question: {trade_data.get('market_question', 'NOT FOUND')[:50]}")
        market = market_service.get_market_by_id(market_id)

        # FALLBACK: If not found with strict filters, try allowing closed/non-tradeable markets
        # Smart traders sometimes buy markets that are temporarily not tradeable
        if not market:
            logger.warning(f"⚠️ [SMART_BUY] Market not found with strict filters, trying with allow_closed=True")
            market = market_service.get_market_by_id(market_id, allow_closed=True)

        # FALLBACK 2: If still not found by ID, try searching by title
        # This handles the case where condition_id from Subsquid doesn't match Gamma API
        if not market:
            market_title = trade_data.get('market_question')
            if market_title:
                logger.warning(f"⚠️ [SMART_BUY] Market not found by ID, trying title search: {market_title[:50]}...")
                market = market_service.search_by_title(market_title, fuzzy=True)

                if market:
                    logger.info(f"✅ [SMART_BUY] Found market by title! Using market_id: {market['id']}")
                    # Update market_id to the correct one from database
                    market_id = market['id']

        if not market:
            logger.error(f"❌ [SMART_BUY] Market not found by ID or title!")
            await query.edit_message_text(
                f"❌ *Market Not Found*\n\n"
                f"This market may have been:\n"
                f"• Delisted from Polymarket\n"
                f"• Expired or resolved\n\n"
                f"_Try /smart_trading again for current opportunities._",
                parse_mode='Markdown'
            )
            return

        # ✅ CHECK IF MARKET IS EXPIRED (using new flag from market_service)
        if market.get('is_expired', False):
            await query.edit_message_text(
                f"⏰ **Market Ended**\n\n"
                f"Trading has closed for this market.\n\n"
                f"Use /smart_trading to find active opportunities.",
                parse_mode='Markdown'
            )
            return

        # CHANGE: Send "executing" message as NEW message instead of editing
        # This prevents the smart_trading list from being replaced
        executing_msg = await query.message.reply_text(
            "⚡ *Quick Buy Executing...*",
            parse_mode='Markdown'
        )

        # Execute buy with trading service
        result = await trading_service.execute_buy(query, market_id, outcome, amount, market)

        if result.get('success'):
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            success_message = (
                f"✅ *Trade Executed!*\n\n"
                f"{result.get('message', '')}\n\n"
                f"💡 *Following smart wallet strategy ({outcome})*"
            )

            # Add action buttons
            keyboard = [
                [
                    InlineKeyboardButton("📊 View My Positions", callback_data="my_open_positions"),
                    InlineKeyboardButton("💎 Back to Smart Trading", callback_data="back_to_smart_trading")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Update the NEW executing message with the result
            await executing_msg.edit_text(success_message, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            # Update the NEW executing message with error
            await executing_msg.edit_text(
                f"❌ {result.get('message', 'Error executing trade')}",
                parse_mode='Markdown'
            )


    except Exception as e:
        logger.error(f"Error in smart quick buy callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text("❌ Error executing quick buy. Please try again.")


async def handle_notification_view_callback(query, callback_data, session_manager, market_service):
    """
    Handle view market button from push notification
    Format: notif_view_{market_id[:10]}_{outcome}
    """
    try:
        # Parse callback data: notif_view_0x1bcf4088_Y
        parts = callback_data.split('_')
        if len(parts) < 4:
            await query.answer("❌ Invalid notification data", show_alert=True)
            return

        market_id_short = parts[2]  # First 10 chars of market ID
        outcome_initial = parts[3]  # Y or N

        # Find the trade in smart_wallet_trades_to_share (source of notification)
        from database import db_manager
        from core.persistence.models import SmartWalletTradesToShare

        with db_manager.get_session() as db:
            trade = db.query(SmartWalletTradesToShare).filter(
                SmartWalletTradesToShare.condition_id.like(f"{market_id_short}%")
            ).order_by(SmartWalletTradesToShare.timestamp.desc()).first()

            if not trade:
                await query.answer("❌ Trade expired or not found", show_alert=True)
                return

            # Use token_id as market_id (same as /smart_trading!)
            market_id = trade.market_id  # 77-char token_id
            condition_id = trade.condition_id  # 0x... format
            market_title = trade.market_question

            # Try to fetch market (same fallback logic as buy button!)
            market = market_service.get_market_by_id(market_id)

            # FALLBACK 1: Try with allow_closed=True
            if not market:
                logger.warning(f"⚠️ [NOTIF_VIEW] Market not found with strict filters, trying allow_closed=True")
                market = market_service.get_market_by_id(market_id, allow_closed=True)

            # FALLBACK 2: Try title search
            if not market:
                logger.warning(f"⚠️ [NOTIF_VIEW] Market not found by ID, trying title search: {market_title[:50]}...")
                market = market_service.search_by_title(market_title, fuzzy=True)
                if market:
                    logger.info(f"✅ [NOTIF_VIEW] Found market by title! Using market_id: {market['id']}")
                    market_id = market['id']  # Update to correct market_id

            if not market:
                await query.answer("❌ Market not found or expired", show_alert=True)
                return

            # Use the SHORT market_id from the fetched market (NOT condition_id!)
            # This is what market_select_callback expects!
            final_market_id = market.get('id') or market.get('market_id') or condition_id

        # Track engagement
        await _track_notification_engagement(query.from_user.id, callback_data, 'view')

        # Set flag to indicate user came from push notification (no back button needed)
        user_id = query.from_user.id
        session = session_manager.get(user_id)
        session['came_from_notification'] = True

        # Show market details using the SHORT market_id
        await handle_market_select_callback_new_message(query, f"market_select_{final_market_id}_0", session_manager, market_service)

    except Exception as e:
        logger.error(f"Error in notification view callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.answer("❌ Error loading market", show_alert=True)


async def handle_notification_buy_callback(query, callback_data, session_manager, trading_service, market_service):
    """
    Handle buy button from push notification
    Format: notif_buy_{market_id[:10]}_{outcome}_{amount}
    Where amount is '2' for quick buy $2, or 'custom' for custom amount
    """
    try:
        # Parse callback data: notif_buy_0x1bcf4088_Y_2 or notif_buy_0x1bcf4088_Y_custom
        parts = callback_data.split('_')
        if len(parts) < 5:
            await query.answer("❌ Invalid notification data", show_alert=True)
            return

        market_id_short = parts[2]
        outcome_initial = parts[3]
        amount_str = parts[4]

        # Map outcome initial to full outcome
        outcome = 'YES' if outcome_initial.upper() == 'Y' else 'NO'

        # Find the trade in smart_wallet_trades_to_share (source of notification)
        from database import db_manager
        from core.persistence.models import SmartWalletTradesToShare

        with db_manager.get_session() as db:
            trade = db.query(SmartWalletTradesToShare).filter(
                SmartWalletTradesToShare.condition_id.like(f"{market_id_short}%")
            ).order_by(SmartWalletTradesToShare.timestamp.desc()).first()

            if not trade:
                await query.answer("❌ Trade expired or not found", show_alert=True)
                return

            # Use token_id as market_id (same as /smart_trading!)
            # The column name is misleading - market_id stores the 77-char token_id
            market_id = trade.market_id  # ✅ 77-char token_id (same as /smart_trading!)
            condition_id = trade.condition_id  # 0x... format
            market_title = trade.market_question

            # Fetch market data using token_id (SAME AS /smart_trading!)
            market = market_service.get_market_by_id(market_id)

            # FALLBACK: Try with allow_closed=True (SAME AS /smart_trading!)
            if not market:
                logger.warning(f"⚠️ [NOTIF_BUY] Market not found with strict filters, trying allow_closed=True")
                market = market_service.get_market_by_id(market_id, allow_closed=True)

            # FALLBACK 2: Try title search (SAME AS /smart_trading!)
            if not market:
                logger.warning(f"⚠️ [NOTIF_BUY] Market not found by ID, trying title search: {market_title[:50]}...")
                market = market_service.search_by_title(market_title, fuzzy=True)
                if market:
                    logger.info(f"✅ [NOTIF_BUY] Found market by title! Using market_id: {market['id']}")
                    market_id = market['id']

            if not market:
                await query.answer("❌ Market not found or expired", show_alert=True)
                return

            # Use the fetched market dict
            market_dict = market

        # Handle custom amount
        if amount_str == 'custom':
            await query.answer("💡 Type your custom amount (e.g., '10' for $10)")

            # Store in session for text input handler
            user_id = query.from_user.id
            session = session_manager.get(user_id)
            session['notification_buy_pending'] = {
                'market_id': token_id,  # ✅ Use token_id!
                'outcome': outcome,
                'market': market_dict
            }

            # Track engagement
            await _track_notification_engagement(user_id, callback_data, 'custom_buy_prompt')
            return

        # Quick buy with preset amount
        try:
            amount = float(amount_str)
        except ValueError:
            await query.answer("❌ Invalid amount", show_alert=True)
            return

        # Check wallet readiness
        from core.services import user_service
        user_id = query.from_user.id
        wallet_ready, status_msg = user_service.is_wallet_ready(user_id)
        if not wallet_ready:
            await query.answer(f"❌ {status_msg}\n\nUse /wallet to complete setup.", show_alert=True)
            return

        await query.answer("⚡ Executing quick buy...")

        # Track engagement
        await _track_notification_engagement(user_id, callback_data, 'quick_buy')

        # Execute buy (SAME AS /smart_trading!)
        result = await trading_service.execute_buy(query, market_id, outcome, amount, market_dict)

        if result.get('success'):
            success_message = (
                f"✅ *Quick Buy Executed!*\n\n"
                f"{result.get('message', '')}\n\n"
                f"_Following expert trader strategy ({outcome})_"
            )
            await query.message.reply_text(success_message, parse_mode='Markdown')
        else:
            await query.message.reply_text(
                f"❌ {result.get('message', 'Error executing trade')}",
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error in notification buy callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.answer("❌ Error executing buy", show_alert=True)


async def _track_notification_engagement(user_id: int, callback_data: str, action: str) -> None:
    """Track notification engagement for analytics"""
    try:
        # Extract trade_id from callback (we don't have it directly, so we use callback as identifier)
        from database import db_manager
        from core.persistence.models import SmartTradeNotification

        with db_manager.get_session() as db:
            # Find the most recent notification for this user
            notification = db.query(SmartTradeNotification).filter(
                SmartTradeNotification.user_id == user_id
            ).order_by(SmartTradeNotification.notified_at.desc()).first()

            if notification:
                notification.clicked = True
                notification.action_taken = action
                db.commit()
                logger.debug(f"✅ [NOTIF] Tracked engagement: user={user_id}, action={action}")
    except Exception as e:
        logger.error(f"❌ [NOTIF] Error tracking engagement: {e}")


async def handle_hide_polygon_key(query, session_manager):
    """Delete the displayed polygon key message"""
    user_id = query.from_user.id
    from datetime import datetime

    try:
        # Delete the current message (which contains the key)
        await query.message.delete()
        await query.answer("🔑 Key message hidden", show_alert=False)
        logger.info(f"✅ [KEY_HIDDEN] user_id={user_id} | key_type=polygon | action=manual_hide | ts={datetime.utcnow().isoformat()}")
    except Exception as e:
        logger.error(f"❌ [HIDE_FAILED] user_id={user_id} | key_type=polygon | error={str(e)[:100]}")
        await query.answer("❌ Failed to hide key", show_alert=False)


async def handle_hide_solana_key(query, session_manager):
    """Delete the displayed solana key message"""
    user_id = query.from_user.id
    from datetime import datetime

    try:
        # Delete the current message (which contains the key)
        await query.message.delete()
        await query.answer("🔑 Key message hidden", show_alert=False)
        logger.info(f"✅ [KEY_HIDDEN] user_id={user_id} | key_type=solana | action=manual_hide | ts={datetime.utcnow().isoformat()}")
    except Exception as e:
        logger.error(f"❌ [HIDE_FAILED] user_id={user_id} | key_type=solana | error={str(e)[:100]}")
        await query.answer("❌ Failed to hide key", show_alert=False)
