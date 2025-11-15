"""
Position View Builder Service
Centralized position display logic to eliminate code duplication
"""
import logging
from typing import List, Dict, Tuple, Any, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime

logger = logging.getLogger(__name__)


class PositionViewBuilder:
    """Builds position view text and keyboard buttons with TP/SL integration"""

    @staticmethod
    def build_position_view(
        positions_data: List[Dict[str, Any]],
        active_tpsl: List,
        user_id: int,
        wallet_address: str,
        mode: str = "emergency",
        include_refresh: bool = True,
        include_timestamp: bool = False,
        cached_markets_map: Dict[str, Any] = None  # ✅ NEW: Allow cached markets
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """
        Build position view with TP/SL details

        Args:
            positions_data: Raw position data from blockchain API
            active_tpsl: List of active TP/SL orders
            user_id: Telegram user ID
            wallet_address: User's wallet address
            mode: "emergency" or "standard" display mode
            include_refresh: Whether to include refresh button
            include_timestamp: Whether to include timestamp in footer

        Returns:
            Tuple of (positions_text, reply_markup)
        """
        from telegram_bot.session_manager import session_manager
        import time

        build_start = time.time()

        # Get claimable winnings (resolved positions)
        # Note: Detection is done in positions/core.py before calling this function
        # This function only reads existing resolved_positions records from DB
        claimable_positions = []
        try:
            from database import SessionLocal, ResolvedPosition
            with SessionLocal() as db:
                # Show PENDING, PROCESSING, and FAILED positions (all allow retry)
                # FAILED positions should still be claimable if redemption failed due to temporary issues
                claimable = db.query(ResolvedPosition).filter(
                    ResolvedPosition.user_id == user_id,
                    ResolvedPosition.status.in_(['PENDING', 'PROCESSING', 'FAILED']),
                    ResolvedPosition.is_winner == True,
                    ResolvedPosition.tokens_held >= 0.5  # Only show positions with >= 0.5 tokens
                ).order_by(ResolvedPosition.resolved_at.desc()).all()

                claimable_positions = [pos.to_dict() for pos in claimable]
                logger.debug(f"💰 [CLAIMABLE] Found {len(claimable_positions)} claimable positions for user {user_id} (filtered: tokens >= 0.5)")
        except Exception as e:
            logger.error(f"❌ Error fetching claimable positions: {e}")

        # Create TP/SL mapping
        tpsl_map = {}
        for tpsl in active_tpsl:
            tpsl_map[tpsl.token_id] = tpsl

        # Clear and rebuild position mappings
        session_manager.clear_position_mappings(user_id)

        markets_load_start = time.time()

        # OPTIMIZATION: Use cached markets_map or batch load if needed
        if cached_markets_map:
            # ✅ FAST PATH: Use cached markets (no DB query!)
            markets_map = cached_markets_map
            logger.info(f"🚀 [POSITION_VIEW] Using cached markets_map ({len(markets_map)} markets, skip DB query!)")
        else:
            # SLOW PATH: Batch load ALL market data before loop (prevents N+1 queries)
            markets_map = {}
            try:
                from telegram_bot.services.market_service import MarketService
                from database import db_manager, SubsquidMarketPoll

                # Extract all condition IDs from positions
                condition_ids = [
                    pos.get('conditionId', pos.get('id', ''))
                    for pos in positions_data[:10]
                    if pos.get('conditionId') or pos.get('id')
                ]

                if condition_ids:
                    logger.debug(f"🔍 [POSITION_VIEW] Extracted {len(condition_ids)} condition_ids from positions: {condition_ids[:2]}...")
                    # Batch load all markets - try SubsquidMarketPoll first (fresher data), then fallback to old Market table

                    db_query_start = time.time()
                    with db_manager.get_session() as db:
                        markets_list = []

                        # Query SubsquidMarketPoll (condition_id field)
                        try:
                            subsquid_markets = db.query(SubsquidMarketPoll).filter(
                                SubsquidMarketPoll.condition_id.in_(condition_ids)
                            ).all()
                            db_query_duration = time.time() - db_query_start
                            logger.info(f"⏱️ [DB QUERY] {db_query_duration:.3f}s for {len(condition_ids)} markets")

                            markets_list.extend(subsquid_markets)
                            logger.debug(f"📦 [POSITION_VIEW] Found {len(subsquid_markets)} markets in SubsquidMarketPoll")
                        except Exception as e:
                            logger.warning(f"⚠️ [POSITION_VIEW] SubsquidMarketPoll query failed: {e}")

                        # Build map using condition_id as key (that's what positions use)
                        to_dict_start = time.time()
                        markets_map = {}
                        for market in markets_list:
                            # Use condition_id if available, otherwise market_id or id
                            key = getattr(market, 'condition_id', None) or getattr(market, 'market_id', None) or getattr(market, 'id', None)
                            if key:
                                markets_map[key] = market.to_dict() if hasattr(market, 'to_dict') else dict(market.__dict__)
                        to_dict_duration = time.time() - to_dict_start
                        if to_dict_duration > 0.1:
                            logger.info(f"⏱️ [TO_DICT] {to_dict_duration:.3f}s for {len(markets_list)} markets")

                        logger.info(f"📦 [POSITION_VIEW] Batch loaded {len(markets_map)}/{len(condition_ids)} markets (using condition_id as key)")
                        if len(markets_map) == 0:
                            logger.warning(f"⚠️ [POSITION_VIEW] No markets found! condition_ids: {condition_ids[:2]}...")

                        # ✅ Store in session for next refresh (avoid re-loading!)
                        session = session_manager.get(user_id)
                        session['cached_markets_map'] = markets_map

            except Exception as e:
                logger.error(f"⚠️ [POSITION_VIEW] Batch load failed: {e}")
                # Continue with empty map - will use fallback prices
                markets_map = {}

        markets_load_duration = time.time() - markets_load_start
        if markets_load_duration > 0.1:
            logger.info(f"⏱️ [MARKETS LOAD] {markets_load_duration:.2f}s")

        # Note: On-demand price fetch removed due to sync/async conflict
        # Prices are already cached by price_updater_service every 20s
        price_cache_map = {}

        # 🔍 DIAGNOSTIC: Check Redis for position tokens directly
        logger.info("🔍 [DIAGNOSTIC] Checking Redis cache for position tokens...")
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        if redis_cache.enabled:
            for pos in positions_data[:3]:  # Test first 3 positions
                token_id = pos.get('asset', '')
                if token_id:
                    cached_price = redis_cache.get_token_price(token_id)
                    if cached_price is not None:
                        logger.info(f"✅ [DIAGNOSTIC] Redis has price for {token_id[:10]}...: ${cached_price:.6f}")
                        price_cache_map[token_id] = cached_price  # Actually use it!
                    else:
                        logger.warning(f"❌ [DIAGNOSTIC] No Redis price for {token_id[:10]}... (should be cached)")
        else:
            logger.error("❌ [DIAGNOSTIC] Redis cache DISABLED!")

        logger.info(f"🔍 [DIAGNOSTIC] Redis check complete: {len(price_cache_map)}/{len(positions_data)} prices found")

        # Build header with claimable winnings
        positions_text = PositionViewBuilder._build_header(
            user_id, wallet_address, len(positions_data), mode, claimable_positions
        )

        # Add claimable winnings section if any
        keyboard = []
        if claimable_positions:
            positions_text += "\n🎊 **CLAIMABLE WINNINGS**\n"
            positions_text += "━━━━━━━━━━━━━━━━━━━━\n\n"

            for idx, claimable in enumerate(claimable_positions[:5]):  # Show max 5
                title = claimable['market_title']
                if len(title) > 50:
                    title = title[:47] + "..."

                net_value = claimable['net_value']
                tokens = claimable['tokens_held']
                outcome = claimable['outcome']
                pnl = claimable['pnl']
                pnl_pct = claimable['pnl_percentage']
                status = claimable.get('status', 'PENDING')
                last_error = claimable.get('last_redemption_error')
                attempt_count = claimable.get('redemption_attempt_count', 0)

                profit_emoji = "📈" if pnl > 0 else "📉"
                profit_sign = "+" if pnl > 0 else ""

                # Show status indicator
                if status == 'FAILED':
                    status_emoji = "⚠️"
                    status_text = " (Previous attempt failed)"
                elif status == 'PROCESSING':
                    status_emoji = "🔄"
                    status_text = " (Processing...)"
                else:
                    status_emoji = "✅"
                    status_text = ""

                positions_text += f"{idx + 1}. {status_emoji} {title}{status_text}\n"
                positions_text += f"   💰 **Claimable:** ${net_value:.2f}\n"
                positions_text += f"   {profit_emoji} **P&L:** {profit_sign}${pnl:.2f} ({profit_sign}{pnl_pct:.1f}%)\n"
                positions_text += f"   📦 {tokens:.2f} {outcome} tokens\n"

                # Show error if previous attempt failed
                if status == 'FAILED' and last_error:
                    error_short = last_error[:60] + "..." if len(last_error) > 60 else last_error
                    positions_text += f"   ⚠️ Last error: {error_short}\n"

                positions_text += "\n"

                # Add redeem button (positions already filtered to >= 0.5 tokens)
                keyboard.append([
                    InlineKeyboardButton(
                        f"💰 Redeem #{idx + 1}",
                        callback_data=f"redeem_position_{claimable['id']}"
                    )
                ])

            positions_text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        # Build position items
        total_value = 0.0

        for i, pos in enumerate(positions_data[:10]):  # Limit to 10
            position_value = PositionViewBuilder._process_position(
                pos, i, tpsl_map, user_id, session_manager, positions_text, keyboard, markets_map, price_cache_map
            )
            total_value += position_value[0]
            positions_text = position_value[1]

        # Build footer
        positions_text = PositionViewBuilder._build_footer(
            positions_text, total_value, active_tpsl, mode, include_timestamp
        )

        build_duration = time.time() - build_start
        logger.info(f"⏱️ [VIEW BUILD] Total {build_duration:.2f}s (Markets: {markets_load_duration:.2f}s)")

        # Add control buttons
        if include_refresh:
            # Row 1: Refresh | View All TP/SL (2 columns)
            keyboard.insert(0, [
                InlineKeyboardButton("🔄 Refresh", callback_data="emergency_refresh"),
                InlineKeyboardButton("📊 View All TP/SL", callback_data="view_all_tpsl")
            ])
            # Row 2: History | Markets (2 columns)
            keyboard.insert(1, [
                InlineKeyboardButton("📜 History", callback_data="history_page_0"),
                InlineKeyboardButton("📊 Markets", callback_data="markets_page_0")
            ])
        else:
            # Emergency mode: Same 2x2 layout
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh", callback_data="emergency_refresh"),
                InlineKeyboardButton("📊 View All TP/SL", callback_data="view_all_tpsl")
            ])
            keyboard.append([
                InlineKeyboardButton("📜 History", callback_data="history_page_0"),
                InlineKeyboardButton("📊 Markets", callback_data="markets_page_0")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        return positions_text, reply_markup

    @staticmethod
    def _build_header(user_id: int, wallet_address: str, position_count: int, mode: str, claimable_positions: List = None) -> str:
        """Build position view header"""
        if claimable_positions is None:
            claimable_positions = []

        if mode == "emergency":
            header = f"🎯 **EMERGENCY POSITIONS** (Direct Blockchain)\n\n"
            header += f"👤 **User:** {user_id}\n"
        else:
            header = f"📊 **Your Positions**\n\n"

        header += f"💼 **Wallet:** `{wallet_address[:10]}...{wallet_address[-6:]}`\n"
        header += f"📊 **Total Positions:** {position_count}\n"

        if claimable_positions:
            header += f"💰 **Claimable Winnings:** {len(claimable_positions)}\n"

        header += "\n"

        return header

    @staticmethod
    def _process_position(
        pos: Dict[str, Any],
        index: int,
        tpsl_map: Dict[str, Any],
        user_id: int,
        session_manager,
        positions_text: str,
        keyboard: List,
        markets_map: Dict[str, Any] = None,
        price_cache_map: Dict[str, float] = None  # ✅ NEW: Pre-fetched prices
    ) -> Tuple[float, str]:
        """Process a single position and add to text/keyboard"""
        if markets_map is None:
            markets_map = {}
        if price_cache_map is None:
            price_cache_map = {}

        # Extract position data
        token_id = pos.get('asset', '')
        size = float(pos.get('size', 0))
        avg_price = float(pos.get('avgPrice', 0))  # Historical buy price
        outcome = pos.get('outcome', 'unknown').upper()
        title = pos.get('title', 'Unknown')
        condition_id = pos.get('conditionId', pos.get('id', ''))

        # Store position mapping for callbacks
        session_manager.store_position_mapping(user_id, index, {
            'token_id': token_id,
            'market_id': condition_id,
            'outcome': outcome.lower()
        })

        # Fetch current market price - PRIORITY ORDER:
        # 1. Pre-fetched price (from on-demand batch) - FASTEST!
        # 2. SubsquidMarketPoll outcome_prices (60s refresh)
        # 3. Fallback to avg_price

        current_price = avg_price  # Default fallback
        price_source = "fallback"

        # ✅ PRIORITY 1: Use pre-fetched price from on-demand batch (Redis)
        if token_id in price_cache_map and price_cache_map[token_id] is not None:
            current_price = price_cache_map[token_id]
            price_source = "redis_cache"
            logger.info(f"🚀 REDIS PRICE for token {token_id[:10]}..., price=${current_price:.6f}")
        else:
            # ⚡ WEBSOCKET CASCADE: Use PriceCalculator for WebSocket → Orderbook → API cascade
            # This is FAST: WebSocket query is just a DB SELECT (~10ms)
            logger.warning(f"⚠️ CACHE MISS for token {token_id[:10]}... - using WebSocket cascade")
            try:
                from telegram_bot.services.price_calculator import PriceCalculator
                from py_clob_client.client import ClobClient
                from py_clob_client.constants import POLYGON

                # Create client for fallback only (WebSocket/Orderbook don't need it)
                client = ClobClient(host="https://clob.polymarket.com", chain_id=POLYGON)

                # Use full cascade: WebSocket (DB query <10ms) → Orderbook → API
                # Pass condition_id so WebSocket can be queried
                fetched_price, source = PriceCalculator.get_price_for_position_display(
                    client=client,
                    token_id=token_id,
                    outcome=outcome.lower() if outcome else None,
                    fallback_price=avg_price,
                    market_id=condition_id  # ✅ Enable WebSocket lookup
                )

                if fetched_price and fetched_price > 0:
                    current_price = fetched_price
                    price_source = source
                    logger.info(f"✅ PRICE from {source}: ${current_price:.6f}")

                    # Cache this price for future use (all sources)
                    try:
                        from core.services.redis_price_cache import get_redis_cache
                        redis_cache_instance = get_redis_cache()
                        if redis_cache_instance:
                            redis_cache_instance.cache_token_price(token_id, current_price, ttl=30)
                            logger.debug(f"💾 Cached price for {token_id[:10]}...")
                    except Exception as cache_error:
                        logger.warning(f"⚠️ Failed to cache price: {cache_error}")
                else:
                    logger.error(f"❌ Price fetch failed for token {token_id[:10]}... - using fallback")
                    price_source = "fallback"

            except Exception as e:
                logger.error(f"❌ Error in price cascade for {token_id[:10]}...: {e} - using fallback")
                price_source = "fallback"

        # Calculate position value based on CURRENT market price, not historical
        current_value = size * current_price

        # Calculate estimated fees (both buy and sell: 1% each = 2% total, min $0.10 each)
        # Fee is: max(1% of value, $0.10 minimum) per trade
        estimated_buy_fee = max(avg_price * size * 0.01, 0.10)
        estimated_sell_fee = max(current_value * 0.01, 0.10)
        total_estimated_fees = estimated_buy_fee + estimated_sell_fee

        # Display value after sell fees
        net_value = current_value - estimated_sell_fee

        # Shorten title if too long (production-ready format)
        title_short = title if len(title) <= 50 else title[:47] + "..."

        # Calculate P&L using CONSISTENT midpoint price (already fetched above)
        # NOTE: Includes estimated fees for net impact transparency
        try:
            # Calculate gross P&L using the same midpoint price as position value
            pnl_gross = (current_price - avg_price) * size

            # Subtract total estimated fees for NET P&L (what user actually makes/loses)
            pnl_value = pnl_gross - total_estimated_fees
            pnl_pct = (pnl_value / (avg_price * size)) * 100 if (avg_price * size) > 0 else 0

            # Format P&L indicator (short format)
            if pnl_value >= 0:
                pnl_indicator = f"🟢 +{pnl_pct:.1f}%"
            else:
                pnl_indicator = f"🔴 {pnl_pct:.1f}%"

            # Build position text with EXPLICIT entry/current prices
            positions_text += f"**{index+1}. {outcome} • {title_short}**\n"
            positions_text += f"   📊 Entry ${avg_price:.4f} → Current ${current_price:.4f}\n"
            positions_text += f"   💰 ${net_value:.2f} ({size:.0f} tokens) • {pnl_indicator}\n"
        except Exception as e:
            # Fallback if P&L calculation fails
            logger.warning(f"⚠️ P&L calculation failed for position {index}: {e}")
            positions_text += f"**{index+1}. {outcome} • {title_short}**\n"
            positions_text += f"   📊 Entry ${avg_price:.4f} → Current ${current_price:.4f}\n"
            positions_text += f"   💰 ${net_value:.2f} ({size:.0f} tokens)\n"

        # Check for TP/SL order
        tpsl_order = tpsl_map.get(token_id)

        if tpsl_order:
            positions_text = PositionViewBuilder._add_tpsl_info(
                positions_text, tpsl_order, avg_price
            )
            # Add Edit/Sell buttons
            keyboard.append([
                InlineKeyboardButton(f"📝 {index+1} Edit TP/SL", callback_data=f"edit_tpsl:{index}"),
                InlineKeyboardButton(f"💸 {index+1} Sell", callback_data=f"sell_pos_{index}")
            ])
        else:
            positions_text += f"   🎯 TP/SL: Not set\n"
            # Add Set TP/SL and Sell buttons
            keyboard.append([
                InlineKeyboardButton(f"⚙️ {index+1} Set TP/SL", callback_data=f"set_tpsl:{index}"),
                InlineKeyboardButton(f"💸 {index+1} Sell", callback_data=f"sell_pos_{index}")
            ])

        positions_text += "\n"

        return current_value, positions_text

    @staticmethod
    def _add_tpsl_info(positions_text: str, tpsl_order, avg_price: float) -> str:
        """Add TP/SL information to position text (condensed format)"""
        tp_price = float(tpsl_order.take_profit_price) if tpsl_order.take_profit_price else None
        sl_price = float(tpsl_order.stop_loss_price) if tpsl_order.stop_loss_price else None

        # Build condensed TP/SL line (single line if both set, or individual lines)
        tpsl_parts = []

        if tp_price:
            tp_pct = (tp_price - avg_price) / avg_price * 100
            tpsl_parts.append(f"🎯 TP {tp_pct:+.1f}%")

        if sl_price:
            sl_pct = (sl_price - avg_price) / avg_price * 100
            tpsl_parts.append(f"🛑 SL {sl_pct:+.1f}%")

        if tpsl_parts:
            positions_text += f"   {' • '.join(tpsl_parts)}\n"
        else:
            positions_text += f"   🎯 TP/SL: Not set\n"

        return positions_text

    @staticmethod
    def _build_footer(
        positions_text: str,
        total_value: float,
        active_tpsl: List,
        mode: str,
        include_timestamp: bool
    ) -> str:
        """Build position view footer"""
        positions_text += f"━━━━━━━━━━━━━━━━━━━━\n"
        positions_text += f"💰 **Total Value: ~${total_value:.2f}**\n\n"

        if active_tpsl:
            positions_text += f"🎯 **Active TP/SL Orders:** {len(active_tpsl)}\n"
            if mode == "standard":
                positions_text += f"\n\n"
        else:
            if mode == "standard":
                positions_text += "💡 **Tip:** Set TP/SL to auto-sell at target prices\n\n"

        if mode == "emergency":
            positions_text += "🚨 **EMERGENCY MODE:** Direct blockchain read\n"
            positions_text += "✅ **No database dependencies**\n\n"

        # ✅ Show timestamp only if explicitly requested (for transparency)
        if include_timestamp:
            current_time = datetime.utcnow().strftime("%H:%M:%S")
            positions_text += f"🔄 **Updated:** {current_time} UTC"

        return positions_text


def get_position_view_builder() -> PositionViewBuilder:
    """Get singleton instance of PositionViewBuilder"""
    return PositionViewBuilder()
