#!/usr/bin/env python3
"""
Positions Sell Handler
Handle sell position logic and execution
"""

import logging
import asyncio
import requests
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram_bot.services.user_trader import UserTrader
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from .utils import is_timeout_error, escape_markdown, format_pnl_indicator
from database import Transaction

logger = logging.getLogger(__name__)


async def handle_sell_position(query, position_index):
    """Handle selling a specific position with price range preview"""
    try:
        user_id = query.from_user.id

        from core.services import user_service, balance_checker
        from telegram_bot.services.fee_service import get_fee_service
        wallet = user_service.get_user_wallet(user_id)
        wallet_address = wallet['address']

        balance_str = "Error"
        try:
            usdc_balance, _ = balance_checker.check_usdc_balance(wallet_address)
            balance_str = f"{usdc_balance:.2f}"
        except Exception as e:
            logger.error(f"Error fetching balance for sell view: {e}")
            balance_str = "Error"

        # CRITICAL FIX: Use async aiohttp instead of sync requests (2-5s blocking → non-blocking)
        url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
        from core.utils.aiohttp_client import get_http_client
        import aiohttp
        session = await get_http_client()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            positions_data = await response.json()

        logger.info(f"📍 POSITIONS API RESPONSE: total_positions={len(positions_data)}")
        for idx, pos in enumerate(positions_data):
            logger.info(f"   Position {idx}: asset={pos.get('asset')[:20] if pos.get('asset') else 'N/A'}..., size={pos.get('size')}, avgPrice={pos.get('avgPrice')}, outcome={pos.get('outcome')}, conditionId={pos.get('conditionId')[:20] if pos.get('conditionId') else 'N/A'}...")

        if position_index >= len(positions_data):
            await query.edit_message_text("❌ Position not found", parse_mode='Markdown')
            return

        pos = positions_data[position_index]
        size = float(pos.get('size', 0))
        avg_price = float(pos.get('avgPrice', 0))
        outcome = pos.get('outcome', 'unknown').upper()
        title = pos.get('title', 'Unknown')[:40]
        token_id = pos.get('asset')
        condition_id = pos.get('conditionId')
        current_value = size * avg_price

        logger.info(f"🔍 POSITION DATA: condition_id={condition_id}, token_id={token_id[:20] if token_id else 'N/A'}..., size={size} (type: {type(size)}), avg_price=${avg_price:.6f} (type: {type(avg_price)}), outcome={outcome}")

        # Fetch spread data from Redis for price range
        # Try to get live pricing first, fallback to avg_price
        spread_info = None
        bid_price_live = None
        bid_price = avg_price  # Initialize with historical price as default
        ask_price = avg_price
        spread_pct = -1  # Use -1 to indicate "not calculated yet"
        conservative_price = None
        best_case_price = None
        worst_case_price = None
        conservative_total = None
        best_case_total = None
        worst_case_total = None

        # Initialize market to None to prevent NameError if market_service lookup fails
        market = None

        try:
            from telegram_bot.services import market_service
            # Allow closed markets when selling existing positions
            market = market_service.get_market_by_id(condition_id, allow_closed=True)

            if market:
                market_id = market.get('id')
                logger.info(f"✅ MARKET LOOKUP SUCCESS: condition_id={condition_id[:20]}... → market_id={market_id[:20]}...")

                # Try to get live prices from market_service
                try:
                    from core.services import get_redis_cache
                    redis_cache = get_redis_cache()
                    # Normalize outcome to lowercase for cache lookup
                    outcome_lower = outcome.lower()
                    logger.info(f"🔎 REDIS LOOKUP: market_id={market_id[:20]}..., outcome={outcome_lower}")

                    spread_info = redis_cache.get_market_spread(market_id, outcome_lower)

                    if spread_info:
                        bid_price_live = spread_info.get('bid')
                        bid_price = bid_price_live  # Use live price if available
                        logger.info(f"✅ REDIS HIT: bid=${bid_price_live:.6f}, ask=${spread_info.get('ask'):.6f}, spread={spread_info.get('spread_pct'):.2f}%")
                    else:
                        logger.warning(f"💨 REDIS MISS: market_id={market_id[:20]}..., outcome={outcome_lower} - using fallback")
                except Exception as e:
                    logger.error(f"❌ Redis spread lookup failed: {e}", exc_info=True)
            else:
                logger.error(f"❌ MARKET LOOKUP FAILED: condition_id={condition_id} returned None")

        except Exception as e:
            logger.error(f"❌ Market service lookup failed: {e}", exc_info=True)

        # NEW: Refactor to use unified price calculator for consistent midpoint-based pricing
        # Strategy: Get orderbook midpoint → API fallback → Historical price
        try:
            from telegram_bot.services.price_calculator import calculate_midpoint, calculate_sell_quote_price, calculate_price_range
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            logger.info(f"🔄 UNIFIED PRICING: Calculating consistent midpoint-based prices for position display")

            # Try to get orderbook for real midpoint
            try:
                client = ClobClient(
                    host="https://clob.polymarket.com",
                    chain_id=POLYGON
                )
                orderbook = client.get_order_book(token_id)

                best_bid_ob = 0
                best_ask_ob = 0

                if orderbook and orderbook.bids and len(orderbook.bids) > 0:
                    best_bid_ob = float(orderbook.bids[0].price)

                if orderbook and orderbook.asks and len(orderbook.asks) > 0:
                    best_ask_ob = float(orderbook.asks[0].price)

                # Calculate spread from live orderbook
                if best_bid_ob > 0 and best_ask_ob > 0:
                    spread_pct = ((best_ask_ob - best_bid_ob) / best_bid_ob) * 100
                    logger.info(f"📊 SPREAD CALCULATED: bid=${best_bid_ob:.6f}, ask=${best_ask_ob:.6f}, spread={spread_pct:.2f}%")

                    # VALIDATION: Reject orderbook if spread is absurdly large (>100%)
                    # This indicates stale/corrupted orderbook data
                    if spread_pct > 100:
                        logger.warning(f"⚠️ SPREAD TOO LARGE ({spread_pct:.1f}%) - Rejecting orderbook, using fallback")
                        best_bid_ob = 0  # Force fallback
                        best_ask_ob = 0
                        spread_pct = 0  # Reset spread since orderbook is rejected

                        # Calculate spread from outcome_prices instead
                        # Spread ≈ 1.0 - (YES_price + NO_price)
                        if market and market.get('outcome_prices'):
                            try:
                                outcome_prices = market.get('outcome_prices', [])
                                if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                                    yes_price = float(outcome_prices[0])
                                    no_price = float(outcome_prices[1])
                                    spread_from_outcomes = 1.0 - (yes_price + no_price)
                                    spread_pct = spread_from_outcomes * 100
                                    logger.info(f"📊 SPREAD FROM OUTCOME_PRICES: YES=${yes_price:.6f}, NO=${no_price:.6f}, spread={spread_pct:.2f}%")
                            except Exception as calc_err:
                                logger.warning(f"⚠️ Could not calculate spread from outcomes: {calc_err}")
                                spread_pct = 0

                # Calculate spread from outcome_prices: 1.0 - (YES_price + NO_price)
                # This represents market friction/inefficiency
                # Can be positive (friction) or negative (arbitrage opportunity)
                if market and market.get('outcome_prices'):
                    try:
                        outcome_prices = market.get('outcome_prices', [])
                        if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                            yes_price = float(outcome_prices[0])
                            no_price = float(outcome_prices[1])
                            spread_from_outcomes = 1.0 - (yes_price + no_price)
                            spread_pct = spread_from_outcomes * 100
                            logger.info(f"📊 SPREAD CALCULATED: YES=${yes_price:.6f}, NO=${no_price:.6f}, spread={spread_pct:.2f}%")
                    except Exception as calc_err:
                        logger.warning(f"⚠️ Could not calculate spread: {calc_err}")
                        spread_pct = -1
                else:
                    logger.warning(f"⚠️ No outcome prices available for spread calculation")
                    spread_pct = -1

                # SELL PRICING: Use BEST_BID directly (what buyers actually pay)
                # DO NOT use midpoint for sell orders - it's unrealistic when spread is huge
                if best_bid_ob > 0:
                    # Use best bid directly - this is what buyers are paying
                    midpoint = best_bid_ob
                    spread_str = f"${best_ask_ob-best_bid_ob:.6f}" if best_ask_ob > 0 else "N/A"
                    logger.info(f"✅ USING BEST_BID FOR SELL: ${midpoint:.6f} (ask=${best_ask_ob:.6f}, spread={spread_str})")
                else:
                    # No bids - fallback to market outcome prices (fresher than Redis cache!)
                    logger.warning(f"⚠️ No orderbook bids, trying fallbacks")
                    midpoint = None

                    # Fallback 1: Market outcome_prices
                    if market and market.get('outcome_prices'):
                        outcome_prices = market.get('outcome_prices', [])
                        if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                            if outcome.lower() == 'yes':
                                midpoint = float(outcome_prices[0])
                            else:
                                midpoint = float(outcome_prices[1])
                            logger.info(f"✅ Using market outcome_prices: ${midpoint:.6f}")

                    # Fallback 2: Try API prices
                    if not midpoint or midpoint <= 0:
                        try:
                            api_price = client.get_price(token_id, "BUY")
                            if api_price and api_price.get('price'):
                                midpoint = float(api_price.get('price'))
                                logger.info(f"✅ Using API BUY price: ${midpoint:.6f}")
                        except Exception as api_err:
                            logger.warning(f"⚠️ API price fetch failed: {api_err}")

                    # Final fallback to avg_price
                    if not midpoint or midpoint <= 0:
                        midpoint = avg_price
                        logger.warning(f"⚠️ Using historical avg_price: ${midpoint:.6f}")

                    logger.warning(f"⚠️ FALLBACK PRICE USED: ${midpoint:.6f}")
            except Exception as e:
                logger.warning(f"⚠️ Orderbook fetch failed: {e}, using market outcome_prices")
                # Don't use stale bid_price from Redis - use market outcome_prices instead
                midpoint = None
                try:
                    if market and market.get('outcome_prices'):
                        outcome_prices = market.get('outcome_prices', [])
                        if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                            if outcome.lower() == 'yes':
                                midpoint = float(outcome_prices[0])
                            else:
                                midpoint = float(outcome_prices[1])
                except Exception as parse_error:
                    logger.warning(f"Could not parse outcome_prices: {parse_error}")

                # Final fallback to avg_price (never use stale bid_price!)
                if not midpoint or midpoint <= 0:
                    midpoint = avg_price

                logger.warning(f"⚠️ Using final fallback price: ${midpoint:.6f}")

            # Calculate sell quote price (midpoint - 0.5%)
            quote_price = calculate_sell_quote_price(midpoint)
            if not quote_price:
                quote_price = midpoint * 0.995  # Fallback

            # Calculate price range
            price_range = calculate_price_range(midpoint, size)

            if price_range:
                # Use unified pricing
                best_case_price = price_range.get('best_case_price', midpoint)
                conservative_price = price_range.get('quote_price', quote_price)
                worst_case_price = price_range.get('worst_case_price', midpoint * 0.97)

                conservative_total = price_range.get('quote_total', 0)
                best_case_total = price_range.get('best_total', 0)
                worst_case_total = price_range.get('worst_total', 0)

                logger.info(f"📊 UNIFIED PRICES: midpoint=${midpoint:.6f}, quote=${conservative_price:.6f}, best=${best_case_price:.6f}, worst=${worst_case_price:.6f}")
            else:
                # Manual calculation fallback
                best_case_price = midpoint
                conservative_price = midpoint * 0.995
                worst_case_price = midpoint * 0.97

                conservative_total = size * conservative_price
                best_case_total = size * best_case_price
                worst_case_total = size * worst_case_price
        except Exception as e:
            logger.warning(f"❌ Unified pricing failed: {e}, using original bid-based pricing")
            # Use original bid_price based pricing (already calculated above)

        # Calculate net amounts after 1% fee deduction
        fee_service = get_fee_service()
        fee_calc = fee_service.calculate_fee(user_id, conservative_total)
        fee_amount = float(fee_calc['fee_amount'])

        # Net payouts (after fee)
        net_conservative = conservative_total - fee_amount
        net_best = best_case_total - fee_amount
        net_worst = worst_case_total - fee_amount

        logger.info(f"💰 FEE CALCULATION: gross=${conservative_total:.2f}, fee=${fee_amount:.2f}, net=${net_conservative:.2f}")

        # WARNING: If net payout would be negative/very small, alert user
        price_warning = ""
        if net_conservative < 0:
            logger.warning(f"⚠️ NET PAYOUT NEGATIVE: Position too small (${conservative_total:.2f} < ${fee_amount:.2f} fee)")
            price_warning = "\n⚠️ Warning: Position value is less than minimum fee ($0.10)\n"
        elif conservative_total < fee_amount * 2:
            logger.warning(f"⚠️ NET PAYOUT VERY SMALL: Fee is large portion of proceeds")
            price_warning = "\n⚠️ Note: Fee ($0.10 min) is significant portion of proceeds\n"

        sell_text = f"💸 SELL POSITION\n\n"
        sell_text += f"{outcome} - {title}\n{price_warning}\n"

        # Key info
        sell_text += f"📦 Tokens: {size:.2f}\n"
        # Display market price and net payout (after 1% fee)
        sell_text += f"💰 Market Price: ${midpoint:.6f}\n"
        sell_text += f"💵 You'll receive: ~${net_conservative:.2f} (after 1% fee)\n\n"

        # Spread info - display as absolute value in dollars, not percentage
        sell_text += f"Market Conditions:\n"
        if spread_pct is not None and spread_pct >= -100:
            # Spread was calculated from outcome prices
            # Spread impact in dollars: tokens * (spread_pct / 100)
            # Since spread_pct is percentage of $1.00 unit price
            spread_dollars = size * (spread_pct / 100)
            if abs(spread_dollars) >= 0.01:
                spread_display = f"${abs(spread_dollars):.2f}"
            else:
                spread_display = f"${abs(spread_dollars):.4f}"
        else:
            # Spread was NOT calculated, using fallback
            spread_display = "N/A (using fallback price)"
        sell_text += f"📊 Market Spread: {spread_display}\n\n"

        # Estimated payout range (net amounts after fee)
        sell_text += f"Estimated Range: ${net_worst:.2f} - ${net_best:.2f}\n\n"

        sell_text += f"💰 Your Balance: ${balance_str} USDC\n\n"
        sell_text += "Choose sell amount:"

        # Build 2x2 grid for sell percentages
        keyboard = []
        percentages = [25, 50, 75, 100]

        # Row 1: 25% and 50%
        row1 = []
        for pct in percentages[:2]:
            sell_value = net_conservative * (pct / 100)
            row1.append(InlineKeyboardButton(
                f"{pct}% (~${sell_value:.2f})",
                callback_data=f"execute_sell_{position_index}_{pct}"
            ))
        keyboard.append(row1)

        # Row 2: 75% and 100%
        row2 = []
        for pct in percentages[2:]:
            sell_value = net_conservative * (pct / 100)
            row2.append(InlineKeyboardButton(
                f"{pct}% (~${sell_value:.2f})",
                callback_data=f"execute_sell_{position_index}_{pct}"
            ))
        keyboard.append(row2)

        keyboard.append([
            InlineKeyboardButton("💰 Custom USD Amount", callback_data=f"sell_usd_{position_index}")
        ])

        keyboard.append([
            InlineKeyboardButton("⬅️ Back to Positions", callback_data="positions_refresh")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(sell_text, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        from telegram_bot.utils.escape_utils import escape_error_message
        await query.edit_message_text(f"❌ Error: {escape_error_message(e)}", parse_mode='Markdown')


async def handle_execute_sell(query, position_index, percentage):
    """Execute the actual sell order"""
    try:
        user_id = query.from_user.id
        await query.edit_message_text("⚡ Executing sell order...", parse_mode='Markdown')

        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)
        wallet_address = wallet['address']

        # CRITICAL FIX: Use async aiohttp instead of sync requests (2-5s blocking → non-blocking)
        url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
        from core.utils.aiohttp_client import get_http_client
        import aiohttp
        session = await get_http_client()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            positions_data = await response.json()

        pos = positions_data[position_index]
        size = float(pos.get('size', 0))
        avg_price = float(pos.get('avgPrice', 0))
        outcome = pos.get('outcome', 'unknown')
        title = pos.get('title', 'Unknown')
        condition_id = pos.get('conditionId')

        tokens_to_sell = int(size * (percentage / 100))

        if tokens_to_sell <= 0:
            await query.edit_message_text("❌ No tokens to sell", parse_mode='Markdown')
            return

        user_data = user_service.get_user(user_id)
        if not user_data or not user_data.api_key:
            await query.edit_message_text("❌ No API credentials found\n\nUse /start to set up your account.", parse_mode='Markdown')
            return

        private_key = user_data.polygon_private_key
        if not private_key:
            await query.edit_message_text("❌ No wallet private key found\n\nUse /start to set up your wallet.", parse_mode='Markdown')
            return

        from telegram_bot.services import market_service
        # Allow closed markets when selling existing positions
        market = market_service.get_market_by_id(condition_id, allow_closed=True)

        if not market:
            await query.edit_message_text(f"❌ Market not found\n\nCondition ID: {condition_id}", parse_mode='Markdown')
            return

        from telegram_bot.utils.token_utils import get_token_id_for_outcome

        try:
            token_id = get_token_id_for_outcome(market, outcome)
            if not token_id:
                raise ValueError(f"Cannot find token_id for outcome '{outcome}'")
            logger.info(f"✅ TOKEN LOOKUP (SELL): market={market.get('question', 'Unknown')[:50]}..., outcome={outcome.upper()}, token_id={token_id[:20]}...")
        except Exception as e:
            logger.error(f"❌ TOKEN LOOKUP FAILED: {e}")
            from telegram_bot.utils.escape_utils import escape_error_message
            await query.edit_message_text(f"❌ Token lookup failed\n\n{escape_error_message(e)}", parse_mode='Markdown')
            return

        creds = ApiCreds(
            api_key=user_data.api_key,
            api_secret=user_data.api_secret,
            api_passphrase=user_data.api_passphrase
        )

        client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=POLYGON,
            creds=creds
        )

        trader = UserTrader(client, private_key)
        logger.info(f"🔄 SELL ATTEMPT: User {user_id} - {tokens_to_sell} {outcome} tokens, token_id: {token_id[:20]}...")

        # CRITICAL FIX: Calculate conservative_price from LIVE ORDERBOOK (not cache!)
        # Priority: Orderbook → API → Market outcome_prices → avg_price
        conservative_price = None
        try:
            from telegram_bot.services.price_calculator import calculate_midpoint, calculate_sell_quote_price

            # PRIORITY 1: Get LIVE orderbook data (most accurate)
            try:
                orderbook = client.get_order_book(token_id)
                best_bid = 0
                best_ask = 0

                if orderbook and orderbook.bids and len(orderbook.bids) > 0:
                    best_bid = float(orderbook.bids[0].price)
                    logger.info(f"📊 LIVE ORDERBOOK: best_bid=${best_bid:.6f}")

                if orderbook and orderbook.asks and len(orderbook.asks) > 0:
                    best_ask = float(orderbook.asks[0].price)
                    logger.info(f"📊 LIVE ORDERBOOK: best_ask=${best_ask:.6f}")

                # SIMPLE & CORRECT: Use best_bid - this is what buyers pay for your tokens
                if best_bid > 0:
                    # Use best_bid directly - this is the seller price
                    conservative_price = best_bid
                    spread_str = f"${best_ask-best_bid:.6f}" if best_ask > 0 else "N/A"
                    logger.info(f"✅ SELL PRICE = BEST BID: ${conservative_price:.6f} (bid=${best_bid:.6f}, ask=${best_ask:.6f}, spread={spread_str})")
            except Exception as e:
                logger.warning(f"⚠️ Could not fetch orderbook: {e}")

            # PRIORITY 2: Check WebSocket data (subsquid_markets_ws)
            if not conservative_price and condition_id:
                from telegram_bot.services.price_calculator import PriceCalculator
                ws_price = PriceCalculator.get_live_price_from_subsquid_ws(condition_id, outcome)
                if ws_price:
                    conservative_price = ws_price * 0.995  # -0.5% safety margin
                    logger.info(f"✅ Using WebSocket price: ${conservative_price:.6f}")

            # PRIORITY 3: If WebSocket failed, try market outcome_prices
            if not conservative_price and market.get('outcome_prices'):
                outcome_prices = market.get('outcome_prices', [])
                if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                    if outcome.lower() == 'yes':
                        bid_price = float(outcome_prices[0])
                    else:
                        bid_price = float(outcome_prices[1])
                    conservative_price = bid_price * 0.995
                    logger.info(f"✅ Using market outcome price: ${conservative_price:.6f}")

            # PRIORITY 4: Final fallback - use avg_price
            if not conservative_price:
                conservative_price = avg_price * 0.995
                logger.warning(f"⚠️ Using fallback avg_price: ${conservative_price:.6f}")

        except Exception as e:
            logger.error(f"❌ Could not calculate conservative_price: {e}, using avg_price")
            conservative_price = avg_price * 0.995

        sell_result = trader.speed_sell_with_token_id(
            market=market,
            outcome=outcome,
            tokens=tokens_to_sell,
            token_id=token_id,
            is_tpsl_sell=False,
            suggested_price=conservative_price,  # Pass the calculated price for consistency
        )

        if sell_result and sell_result.get('order_id'):
            await _handle_sell_success(query, user_id, sell_result, pos, tokens_to_sell, avg_price, title, token_id, market)
        else:
            await query.edit_message_text("❌ Sell order failed - Please try again", parse_mode='Markdown')

    except Exception as e:
        if is_timeout_error(e):
            await _handle_sell_timeout(query, user_id, e, locals())
        else:
            logger.error(f"❌ SELL FAILED: User {user_id} - {e}")
            error_text = str(e).replace('*', r'\*').replace('_', r'\_').replace('`', r'\`').replace('[', r'\[').replace(']', r'\]')
            title_safe = escape_markdown(title) if 'title' in locals() else 'Unknown'
            error_message = f"""❌ SELL ORDER FAILED

📊 Market: {title_safe[:40]}...
📦 Amount: {tokens_to_sell if 'tokens_to_sell' in locals() else '?'} tokens

Error: {error_text}

💡 Please try again or contact support if the issue persists."""
            await query.edit_message_text(error_message, parse_mode='Markdown')


async def _handle_sell_success(query, user_id, sell_result, pos, tokens_to_sell, avg_price, title, token_id, market):
    """Handle successful sell"""
    from telegram_bot.services import get_transaction_service
    from telegram_bot.services.fee_service import get_fee_service
    from telegram_bot.services.tpsl_service import get_tpsl_service
    from core.services import user_service
    from core.services.redis_price_cache import get_redis_cache
    from sqlalchemy.orm import Session
    from database import SessionLocal
    from database import Fee
    from database import Transaction

    transaction_service = get_transaction_service()
    redis_cache = get_redis_cache()

    # ✅ NOTE: Cache invalidation is now CENTRALIZED in transaction_service.log_trade()
    # Every transaction (BUY/SELL/TP/SL/CopyTrade) automatically invalidates cache + marks recent trade
    # This ensures 100% coverage without code duplication

    is_real_price = sell_result.get('is_real', False)
    sell_price = sell_result.get('sell_price', 0)

    if 'total_received' in sell_result:
        actual_proceeds = sell_result['total_received']
        tokens_actually_sold = sell_result.get('tokens_sold', tokens_to_sell)
    else:
        actual_proceeds = sell_result.get('estimated_proceeds', tokens_to_sell * sell_price)
        tokens_actually_sold = tokens_to_sell

    transaction_logged = transaction_service.log_trade(
        user_id=user_id,
        transaction_type='SELL',
        market_id=pos.get('id', pos.get('conditionId', 'unknown')),
        outcome=pos.get('outcome', 'unknown'),
        tokens=tokens_actually_sold,
        price_per_token=sell_price,
        token_id=token_id,
        order_id=sell_result['order_id'],
        transaction_hash=sell_result.get('transaction_hash'),
        market_data=market  # ✅ CRITICAL FIX: Include market data for history display
    )

    # ✅ NEW: Calculate SELL fee upfront (before PNL calculation)
    fee_service = get_fee_service()
    sell_fee_calc = fee_service.calculate_fee(user_id, actual_proceeds)
    sell_fee_amount = float(sell_fee_calc['fee_amount'])

    # ✅ NEW: Retrieve BUY fee from database
    buy_fee_amount = 0.0
    try:
        with SessionLocal() as session:
            # Find the BUY transaction(s) for this position that we're selling
            buy_transaction = session.query(Transaction).filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type == 'BUY',
                Transaction.outcome == pos.get('outcome', 'unknown').lower()
            ).order_by(Transaction.executed_at.desc()).first()

            if buy_transaction:
                # Get the fee record for this BUY transaction
                buy_fee = session.query(Fee).filter(
                    Fee.transaction_id == buy_transaction.id
                ).first()
                if buy_fee:
                    buy_fee_amount = float(buy_fee.fee_amount)
                    logger.info(f"✅ BUY FEE RETRIEVED: ${buy_fee_amount:.2f}")
    except Exception as e:
        logger.error(f"❌ Failed to retrieve BUY fee: {e}")

    # ✅ FIX: Calculate REAL avg_price from database (not rounded Polymarket value)
    # Polymarket returns rounded avgPrice which causes PNL calculation errors
    db_avg_price = avg_price  # Fallback to Polymarket value
    try:
        with SessionLocal() as session:
            # Get ALL BUY transactions for this position
            buy_transactions = session.query(Transaction).filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type == 'BUY',
                Transaction.outcome == pos.get('outcome', 'unknown').lower(),
                Transaction.market_id == pos.get('id', pos.get('conditionId', 'unknown'))
            ).all()

            if buy_transactions:
                total_cost = sum(float(tx.total_amount) for tx in buy_transactions)
                total_tokens = sum(float(tx.tokens) for tx in buy_transactions)
                db_avg_price = total_cost / total_tokens if total_tokens > 0 else avg_price
                logger.info(f"✅ REAL AVG PRICE FROM DB: ${db_avg_price:.6f} (Polymarket rounded: ${avg_price:.6f})")
    except Exception as e:
        logger.warning(f"⚠️ Failed to get real avg_price from DB, using Polymarket value: {e}")

    # ✅ NEW: Calculate PNL with fees included
    # Total invested = (tokens × buy_price) + buy_fee
    # Total received = actual_proceeds - sell_fee
    # PNL = Total received - Total invested

    total_invested = (tokens_actually_sold * db_avg_price) + buy_fee_amount
    total_received = actual_proceeds - sell_fee_amount
    pnl_value = total_received - total_invested
    pnl_pct = (pnl_value / total_invested * 100) if total_invested > 0 else 0

    logger.info(
        f"💰 PNL CALCULATION (WITH FEES):\n"
        f"   Tokens: {tokens_actually_sold}, Sell Price: ${sell_price:.6f}\n"
        f"   Gross Proceeds: ${actual_proceeds:.2f}, Sell Fee: ${sell_fee_amount:.2f}\n"
        f"   Net Received: ${total_received:.2f}\n"
        f"   Avg Buy Price: ${avg_price:.6f}, Buy Fee: ${buy_fee_amount:.2f}\n"
        f"   Total Invested: ${total_invested:.2f}\n"
        f"   PNL: ${pnl_value:.2f} ({pnl_pct:.2f}%)"
    )

    pnl_indicator = format_pnl_indicator(pnl_value, pnl_pct)
    tx_display = str(transaction_logged)[:10] + "..." if transaction_logged else "Pending"
    title_safe = escape_markdown(title)

    success_text = f"💰 SELL EXECUTED!\n\n"
    success_text += f"✅ Market: {title_safe[:50]}...\n"
    success_text += f"🎯 Position: {pos.get('outcome', 'UNKNOWN').upper()}\n"
    success_text += f"📦 Sold: {tokens_actually_sold} tokens\n"
    success_text += f"💵 Price: ${sell_price:.4f}\n"
    success_text += f"💰 Received: ${total_received:.2f}\n"
    success_text += f"{pnl_indicator}\n\n"
    success_text += f"🎉 Order executing on Polymarket!"

    await query.edit_message_text(success_text, parse_mode='Markdown')

    # ✅ NEW: Collect fees after showing success message
    if actual_proceeds > 0:
        async def collect_sell_fee():
            try:
                success, msg, tx_hash = await fee_service.collect_fee(
                    user_id=user_id,
                    trade_amount=actual_proceeds,
                    transaction_id=transaction_logged
                )
                if success:
                    logger.info(f"✅ FEE SUCCESS: {tx_hash}")
                else:
                    logger.error(f"❌ FEE FAILED: {msg}")
            except Exception as e:
                logger.error(f"❌ FEE ERROR: {e}")

        asyncio.create_task(collect_sell_fee())

    async def sync_tpsl_after_sell():
        await _sync_tpsl(user_id, token_id, tokens_to_sell, title)

    asyncio.create_task(sync_tpsl_after_sell())


async def _sync_tpsl(user_id, token_id, tokens_sold, title):
    """Sync TP/SL orders after sell"""
    try:
        from telegram_bot.services import get_tpsl_service
        from core.services import user_service

        tpsl_service = get_tpsl_service()
        wallet = user_service.get_user_wallet(user_id)
        wallet_address = wallet['address']

        # CRITICAL FIX: Use async aiohttp instead of sync requests (2-5s blocking → non-blocking)
        url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
        from core.utils.aiohttp_client import get_http_client
        import aiohttp
        session = await get_http_client()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            positions = await response.json()

        remaining_tokens = 0.0
        for position in positions:
            if position.get('asset') == token_id:
                remaining_tokens = float(position.get('size', 0))
                break

        active_orders = tpsl_service.get_active_tpsl_orders(user_id=user_id)

        if active_orders:
            for order in active_orders:
                if remaining_tokens <= 0:
                    tpsl_service.cancel_tpsl_order(order.id, reason="position_closed_manual")
                    bot = Bot(token="8483038224:AAFg8OGxlRvGNFDZmATFGB4dWcAiAdCrL-M")
                    msg = f"🔔 TP/SL Auto-Cancelled\n\n{title}\n\n📉 Position fully closed ({tokens_sold} tokens sold)"
                    await bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
                    logger.info(f"✅ TP/SL #{order.id} auto-cancelled")
                else:
                    tpsl_service.update_monitored_tokens(order.id, remaining_tokens)
                    logger.info(f"✅ TP/SL #{order.id} updated")

    except Exception as e:
        logger.error(f"❌ TP/SL sync failed: {e}")


async def _handle_sell_timeout(query, user_id, error, local_vars):
    """Handle timeout during sell"""
    logger.warning(f"⏱️ SELL TIMEOUT: Order likely submitted")

    title = local_vars.get('title', 'Unknown')
    tokens_to_sell = local_vars.get('tokens_to_sell', 0)
    estimated_sell_price = 0.5
    outcome = local_vars.get('outcome', 'UNKNOWN')

    timeout_message = f"""⏳ ORDER SUBMITTED - PENDING CONFIRMATION

📦 Selling: {tokens_to_sell} {outcome} tokens
📊 Market: {title[:40]}...
💵 Estimated: ~${tokens_to_sell * estimated_sell_price:.2f}

⚠️ Confirmation is taking longer than expected.
Your order was submitted to Polymarket and is likely executing.

💡 What to do:
• Check `/history` in 1-2 minutes for confirmation
• Check Polygonscan for blockchain status

🎯 This is not a failure - just a slow network response."""

    await query.edit_message_text(timeout_message, parse_mode='Markdown')
