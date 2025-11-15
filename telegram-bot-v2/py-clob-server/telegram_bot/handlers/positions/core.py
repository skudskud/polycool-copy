#!/usr/bin/env python3
"""
Positions Handler Core
Display and refresh position logic
"""

import logging
import aiohttp
from telegram import Update, CallbackQuery
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE, force_refresh: bool = True) -> None:
    """
    Display user positions from blockchain

    Args:
        update: Telegram update object
        context: Command context
        force_refresh: If True, bypass cache and fetch fresh data from API
                      DEFAULT: True - users expect fresh data when typing /positions
    """
    from telegram_bot.utils.performance import PerformanceTimer
    import time

    command_start = time.time()
    user_id = update.effective_user.id

    try:
        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)

        if not wallet:
            await update.message.reply_text(
                "❌ No wallet found!\n\nUse /start to create your wallet.",
                parse_mode='Markdown'
            )
            return

        wallet_address = wallet['address']

        loading_msg = await update.message.reply_text(
            "🔍 Loading your positions...",
            parse_mode='Markdown'
        )

        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        # Debug: Log cache status
        if not redis_cache.enabled:
            logger.warning(f"⚠️ REDIS DISABLED - Will use slow API call for {wallet_address[:10]}...")

        # ✅ NEW: Skip cache if force_refresh is True (after trades)
        cached_positions = None
        if not force_refresh:
            with PerformanceTimer("[PHASE 4] Cache lookup"):
                cached_positions = redis_cache.get_user_positions(wallet_address)
            logger.info(f"🔍 POSITIONS CACHE: Found {len(cached_positions) if cached_positions else 0} cached positions for {wallet_address[:10]}...")
        else:
            logger.info(f"🔄 FORCE REFRESH: Bypassing cache after trade - fetching fresh positions")

        if cached_positions is not None and len(cached_positions) > 0:
            positions_data = cached_positions
            logger.info(f"🚀 CACHE HIT: Loaded {len(positions_data)} positions from Redis (instant!)")
        else:
            if redis_cache.enabled:
                logger.info(f"💨 CACHE MISS: Fetching positions from API for {wallet_address[:10]}...")
            else:
                logger.warning(f"❌ NO CACHE: Fetching positions from slow API (expect 5-10s delay)...")

            url = f"https://data-api.polymarket.com/positions?user={wallet_address}"

            with PerformanceTimer("[PHASE 4] Blockchain API call (async)"):
                from core.utils.aiohttp_client import get_http_client
                session = await get_http_client()

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            await loading_msg.edit_text(
                                f"❌ API Error: {response.status}\n\nPolymarket API is down.",
                                parse_mode='Markdown'
                            )
                            return

                        positions_data = await response.json()
                except (aiohttp.ClientError, Exception) as e:
                    logger.error(f"API request failed: {e}")
                    await loading_msg.edit_text(
                        f"❌ API Error: {str(e)}\n\nPolymarket API is down.",
                        parse_mode='Markdown'
                    )
                    return

            # 🔥 DYNAMIC TTL: Use shorter cache for recent trades (faster refresh)
            from config.config import POSITION_CACHE_TTL
            ttl = 20 if redis_cache.has_recent_trade(wallet_address) else POSITION_CACHE_TTL
            redis_cache.cache_user_positions(wallet_address, positions_data, ttl=ttl)
            logger.info(f"📊 Found {len(positions_data)} positions from blockchain (cached for {ttl}s)")

        # ✅ CRITICAL FIX: Detect and filter redeemable positions from active positions
        # Redeemable positions should ONLY appear in "Claimable Winnings", not in active positions
        # Polymarket API structure: {'asset': '<token_id>', 'conditionId': '<market_id>', 'outcome': 'Yes', ...}
        redeemable_condition_ids = []
        if positions_data:
            from core.services.redeemable_position_detector import get_redeemable_position_detector
            detector = get_redeemable_position_detector()

            # Detect redeemable positions (will create resolved_positions records lazily)
            _, redeemable_condition_ids = detector.detect_redeemable_positions(
                positions_data=positions_data,
                user_id=user_id,
                wallet_address=wallet_address
            )

            # Also get existing resolved_positions condition_ids (for positions already redeemed)
            from database import SessionLocal, ResolvedPosition
            with SessionLocal() as db:
                existing_resolved = db.query(ResolvedPosition.condition_id).filter(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.status.in_(['PENDING', 'PROCESSING', 'REDEEMED'])
                ).all()
                existing_resolved_ids = set(r[0] for r in existing_resolved)
                redeemable_condition_ids.extend(existing_resolved_ids)

            # Filter out redeemable positions from active positions
            original_count = len(positions_data)
            positions_data = [
                pos for pos in positions_data
                if pos.get('conditionId') not in redeemable_condition_ids
            ]

            if original_count > len(positions_data):
                logger.debug(
                    f"🔍 [FILTER] Removed {original_count - len(positions_data)} redeemable positions "
                    f"from active positions display"
                )

            # 🔥 CRITICAL: Filter out dust positions (size < 0.1 tokens)
            # After selling 100%, API may still return position with size ~0.0001 for 10-30s
            # Using 0.1 threshold to be aggressive and avoid showing "ghost" positions
            original_count = len(positions_data)
            positions_data = [
                pos for pos in positions_data
                if float(pos.get('size', 0)) >= 0.1  # Filter positions < 0.1 tokens (more aggressive)
            ]

            if original_count > len(positions_data):
                logger.info(f"🧹 [DUST FILTER] Removed {original_count - len(positions_data)} dust positions (size < 0.1)")

        # ✅ CRITICAL FIX: Check for claimable positions even if active positions are empty
        # This ensures "Claimable Winnings" section is shown even when all positions are resolved
        has_claimable = False
        if not positions_data:
            try:
                from database import SessionLocal, ResolvedPosition
                with SessionLocal() as db:
                    claimable_count = db.query(ResolvedPosition).filter(
                        ResolvedPosition.user_id == user_id,
                        ResolvedPosition.status.in_(['PENDING', 'PROCESSING']),
                        ResolvedPosition.is_winner == True
                    ).count()
                    has_claimable = claimable_count > 0
            except Exception as e:
                logger.debug(f"⚠️ Error checking claimable positions: {e}")

        # Only return early if no active positions AND no claimable positions
        if not positions_data and not has_claimable:
            await loading_msg.edit_text(
                "📭 No positions found\n\n✨ Your wallet has no active positions.\n\nUse /markets to start trading!",
                parse_mode='Markdown'
            )
            return

        from telegram_bot.services.tpsl_service import get_tpsl_service
        tpsl_service = get_tpsl_service()

        with PerformanceTimer("[PHASE 4] TP/SL query"):
            active_tpsl = tpsl_service.get_active_tpsl_orders(user_id=user_id)

        from telegram_bot.services.position_view_builder import get_position_view_builder
        from telegram_bot.session_manager import session_manager
        view_builder = get_position_view_builder()

        # ✅ Try to use cached markets_map from previous loads
        session = session_manager.get(user_id)
        cached_markets = session.get('cached_markets_map')

        # Log price fetching start for WebSocket visibility
        logger.info(f"💰 POSITIONS PRICE FETCH: Getting current prices for {len(positions_data)} positions (WebSocket → Poller → API cascade)")

        with PerformanceTimer("[PHASE 4] View rendering"):
            positions_text, reply_markup = view_builder.build_position_view(
                positions_data=positions_data,
                active_tpsl=active_tpsl,
                user_id=user_id,
                wallet_address=wallet_address,
                mode="standard",
                include_refresh=True,
                include_timestamp=False,
                cached_markets_map=cached_markets  # ✅ Use cache if exists
            )

        edit_start = time.time()
        await loading_msg.edit_text(
            positions_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        edit_duration = time.time() - edit_start

        total_duration = time.time() - command_start
        logger.info(f"⏱️ [COMMAND TOTAL] {total_duration:.2f}s (Telegram edit: {edit_duration:.2f}s)")
        print(f"✅ Positions displayed: {len(positions_data)} positions")

    except Exception as e:
        logger.error(f"Positions command error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

        await update.message.reply_text(
            f"❌ Positions scan failed\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Try again in a few seconds.",
            parse_mode='Markdown'
        )


async def handle_positions_refresh(query: CallbackQuery) -> None:
    """Handle positions refresh - OPTIMIZED for speed"""
    from telegram_bot.utils.performance import PerformanceTimer
    import time

    refresh_start = time.time()

    try:
        user_id = query.from_user.id
        logger.info(f"⏱️ [REFRESH START] User {user_id}")

        # ✅ Rate limiting: Max 3 refreshes per 30 seconds
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        rate_limit_key = f"user_refresh_limit:{user_id}"
        refresh_count = redis_cache.redis_client.incr(rate_limit_key)
        if refresh_count == 1:
            redis_cache.redis_client.expire(rate_limit_key, 30)

        if refresh_count > 3:
            ttl = redis_cache.redis_client.ttl(rate_limit_key)
            await query.answer(f"⏳ Too many refreshes. Wait {ttl}s before refreshing again.", show_alert=True)
            logger.warning(f"⚠️ [RATE_LIMIT] User {user_id} exceeded refresh limit ({refresh_count}/3)")
            return

        # ✅ FIX: Answer callback with loading indicator (doesn't replace message)
        await query.answer("🔄 Refreshing prices...", show_alert=False)

        from core.services import user_service
        wallet = user_service.get_user_wallet(user_id)
        wallet_address = wallet['address']

        # ✅ DON'T edit message during refresh - keeps positions visible!

        # ✅ TEMP: Revert to API-based position fetching (position_calculator not implemented yet)
        with PerformanceTimer("[PHASE 4] Position refresh"):
            # Use the same logic as initial positions load

            # Check cache first (30s TTL for refresh)
            cached_positions = redis_cache.get_user_positions(wallet_address)

            if cached_positions is not None:
                positions_data = cached_positions
                logger.info(f"🚀 CACHE HIT: Loaded {len(positions_data)} positions from Redis")

                # ✅ Invalidate price cache for position tokens to force fresh fetch
                invalidated_count = 0
                for pos in positions_data:
                    token_id = pos.get('asset')
                    if token_id:
                        redis_cache.redis_client.delete(f"token_price:{token_id}")
                        invalidated_count += 1
                if invalidated_count > 0:
                    logger.info(f"🔥 Invalidated price cache for {invalidated_count} position tokens")
            else:
                # Cache miss - fetch from API
                logger.info(f"💨 CACHE MISS: Fetching positions from API for refresh")
                url = f"https://data-api.polymarket.com/positions?user={wallet_address}"

                from core.utils.aiohttp_client import get_http_client
                import aiohttp
                session = await get_http_client()

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            raise Exception(f"API Error: {response.status}")
                        positions_data = await response.json()

                    # Cache for 30 seconds
                    redis_cache.cache_user_positions(wallet_address, positions_data, ttl=30)
                    logger.info(f"📊 Cached {len(positions_data)} positions for refresh (30s TTL)")

                except Exception as e:
                    logger.error(f"❌ Position refresh API error: {e}")
                    # Fallback: return empty to avoid breaking refresh
                    positions_data = []

        logger.info(f"🔍 Retrieved {len(positions_data)} positions for refresh")

        # ✅ Detect and filter redeemable positions (same logic as main command)
        redeemable_condition_ids = []
        if positions_data:
            from core.services.redeemable_position_detector import get_redeemable_position_detector
            detector = get_redeemable_position_detector()

            _, redeemable_condition_ids = detector.detect_redeemable_positions(
                positions_data=positions_data,
                user_id=user_id,
                wallet_address=wallet_address
            )

            # Also get existing resolved_positions condition_ids
            from database import SessionLocal, ResolvedPosition
            with SessionLocal() as db:
                existing_resolved = db.query(ResolvedPosition.condition_id).filter(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.status.in_(['PENDING', 'PROCESSING', 'REDEEMED'])
                ).all()
                existing_resolved_ids = set(r[0] for r in existing_resolved)
                redeemable_condition_ids.extend(existing_resolved_ids)

            # Filter out redeemable positions
            original_count = len(positions_data)
            positions_data = [
                pos for pos in positions_data
                if pos.get('conditionId') not in redeemable_condition_ids
            ]

            if original_count > len(positions_data):
                logger.debug(
                    f"🔍 [REFRESH FILTER] Removed {original_count - len(positions_data)} "
                    f"redeemable positions from active display"
                )

        if not positions_data:
            await query.edit_message_text(
                "📭 No positions found\n\nUse /markets to start trading!",
                parse_mode='Markdown'
            )
            return

        tpsl_start = time.time()
        from telegram_bot.services.tpsl_service import get_tpsl_service
        tpsl_service = get_tpsl_service()
        active_tpsl = tpsl_service.get_active_tpsl_orders(user_id=user_id)
        tpsl_duration = time.time() - tpsl_start
        logger.info(f"⏱️ [TP/SL QUERY] {tpsl_duration:.3f}s")

        from telegram_bot.services.position_view_builder import get_position_view_builder
        from telegram_bot.session_manager import session_manager
        view_builder = get_position_view_builder()

        # ✅ OPTIMIZATION: Use cached markets_map from session if available (skip 780ms DB query!)
        session = session_manager.get(user_id)
        cached_markets = session.get('cached_markets_map')

        # Log price fetching start for WebSocket visibility during refresh
        logger.info(f"🔄 REFRESH PRICE FETCH: Getting current prices for {len(positions_data)} positions (WebSocket → Poller → API cascade)")

        view_start = time.time()
        positions_text, reply_markup = view_builder.build_position_view(
            positions_data=positions_data,
            active_tpsl=active_tpsl,
            user_id=user_id,
            wallet_address=wallet_address,
            mode="standard",
            include_refresh=True,
            include_timestamp=False,  # ✅ No timestamp for refresh (enables content comparison)
            cached_markets_map=cached_markets  # ✅ Pass cached markets
        )
        view_duration = time.time() - view_start
        logger.info(f"⏱️ [BUILD VIEW] {view_duration:.3f}s")

        # ✅ OPTIMIZATION: Check if content actually changed (avoid slow Telegram edit if prices unchanged)
        session = session_manager.get(user_id)
        last_positions_text = session.get('last_positions_text')

        if last_positions_text == positions_text:
            # Content identical - just show quick feedback
            logger.info(f"✅ Prices unchanged - skip slow Telegram edit!")
            total_duration = time.time() - refresh_start
            logger.info(f"⏱️ [REFRESH TOTAL] {total_duration:.2f}s (skipped edit)")
            # User already got instant callback answer, no need to edit
            return

        # Store for next comparison
        session['last_positions_text'] = positions_text

        edit_start = time.time()
        await query.edit_message_text(
            positions_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        edit_duration = time.time() - edit_start

        total_duration = time.time() - refresh_start
        logger.info(f"✅ Positions refreshed: {len(positions_data)} positions with TP/SL details")
        logger.info(f"⏱️ [REFRESH TOTAL] {total_duration:.2f}s (Telegram edit: {edit_duration:.2f}s)")

    except Exception as e:
        if "Message is not modified" in str(e):
            logger.info(f"✅ Refresh skipped - content unchanged (Telegram limitation)")
            # Don't try to answer again - callback already answered!
        elif "Query is too old" in str(e) or "query id is invalid" in str(e):
            # Callback timeout - just log it, don't try to respond
            logger.warning(f"⏱️ Callback timeout during refresh (operation took too long)")
        else:
            logger.error(f"❌ Positions refresh error: {e}")
            try:
                await query.edit_message_text(f"❌ Refresh failed: {str(e)}", parse_mode='Markdown')
            except Exception as edit_err:
                # If edit fails, just log - callback is already answered so we can't show alert
                logger.error(f"❌ Could not show error to user: {edit_err}")
