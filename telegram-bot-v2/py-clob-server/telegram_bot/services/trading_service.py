#!/usr/bin/env python3
"""
Trading Service
Handles trade execution, order management, and trader instantiation
WITH ENTERPRISE-GRADE TRANSACTION LOGGING + FEE COLLECTION
"""

import logging
import asyncio
from typing import Optional

from core.services import user_service, balance_checker
from .user_trader import UserTrader
from .transaction_service import get_transaction_service
from .fee_service import get_fee_service

logger = logging.getLogger(__name__)


class TradingService:
    """
    Service for trading operations
    Manages trader creation and trade execution
    """

    def __init__(self, session_manager, position_service):
        """
        Initialize trading service

        Args:
            session_manager: SessionManager instance
            position_service: PositionService instance
        """
        self.session_manager = session_manager
        self.position_service = position_service

    def get_trader(self, user_id: int) -> Optional[UserTrader]:
        """
        Get or create UserTrader instance for user with their wallet

        Args:
            user_id: Telegram user ID

        Returns:
            UserTrader instance or None if wallet not available
        """
        user = user_service.get_user(user_id)
        if not user:
            logger.error(f"❌ No user found for user_id {user_id}")
            return None

        private_key = user.polygon_private_key

        # DEBUG: Check if private key exists
        if not private_key:
            logger.error(f"❌ User {user_id} has no polygon_private_key!")
            logger.error(f"   User data: address={user.polygon_address}, funded={user.funded}")
            return None

        logger.info(f"🔑 User {user_id} private key exists: {len(private_key)} chars")

        # Create trader with user's private key and API credentials
        try:
            # Get user's API credentials if available
            user_creds_dict = user_service.get_api_credentials(user_id)

            # Create a completely new trader instance with user's credentials
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON
            from py_clob_client.clob_types import ApiCreds

            # Convert dict to ApiCreds object if credentials exist
            user_creds = None
            if user_creds_dict:
                user_creds = ApiCreds(
                    api_key=user_creds_dict['api_key'],
                    api_secret=user_creds_dict['api_secret'],
                    api_passphrase=user_creds_dict['api_passphrase']
                )

            # Create client with user's wallet
            client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,  # User's private key
                chain_id=POLYGON,
                signature_type=0,  # EOA signature
                funder=None,  # User owns funds directly
                creds=user_creds  # User's API credentials (ApiCreds object)
            )

            # DEBUG: Verify client has address
            client_address = client.get_address()
            if not client_address:
                logger.error(f"❌ ClobClient created but get_address() returned None!")
                logger.error(f"   This suggests the private key format is invalid")
                return None

            logger.info(f"✅ ClobClient initialized with address: {client_address[:10]}...")

            user_trader = UserTrader(client, private_key)

            logger.info(f"✅ Created user-specific trader for {user_id}")
            return user_trader
        except Exception as e:
            logger.error(f"Error creating user trader: {e}")
            return None

    async def _collect_fee_background(
        self,
        user_id: int,
        trade_amount: float,
        transaction_id: Optional[int],
        trade_type: str
    ):
        """
        Collect fee in background after trade is executed
        User doesn't wait for this - maintains 0-2 second execution speed

        Args:
            user_id: Telegram user ID
            trade_amount: Trade amount in USD
            transaction_id: Transaction ID to link fee
            trade_type: 'BUY' or 'SELL'
        """
        try:
            fee_service = get_fee_service()

            # Calculate fee (1%)
            fee_calc = fee_service.calculate_fee(user_id, trade_amount)
            fee_amount = float(fee_calc['fee_amount'])

            logger.info(f"🔄 Background fee collection started: ${fee_amount} from user {user_id} ({trade_type})")

            # Retry logic: 3 attempts with 60 second delay
            max_retries = 3
            for attempt in range(max_retries):
                # Collect fee (3-5 seconds, but user already got their trade!)
                success, msg, tx_hash = await fee_service.collect_fee(
                    user_id=user_id,
                    trade_amount=trade_amount,
                    transaction_id=transaction_id
                )

                if success:
                    logger.info(f"✅ FEE SUCCESS: Background fee collected: {tx_hash}")

                    # Update fee record with transaction_id if we have one
                    if transaction_id and tx_hash:
                        try:
                            from database import SessionLocal
                            from sqlalchemy import text
                            session = SessionLocal()
                            session.execute(
                                text("UPDATE fees SET transaction_id = :tx_id WHERE fee_transaction_hash = :fee_hash"),
                                {'tx_id': transaction_id, 'fee_hash': tx_hash}
                            )
                            session.commit()
                            session.close()
                        except Exception as e:
                            logger.error(f"❌ FEE FAILED: Error updating fee record: {e}")

                    # REDIS CACHE: Invalidate position cache after successful fee collection
                    try:
                        from core.services.redis_price_cache import get_redis_cache
                        from core.services import user_service
                        user = user_service.get_user(user_id)
                        if user:
                            redis_cache = get_redis_cache()
                            redis_cache.invalidate_user_positions(user.polygon_address)
                            logger.debug(f"🗑️ Invalidated position cache for user {user_id}")
                    except Exception as e:
                        logger.warning(f"Cache invalidation failed (non-critical): {e}")

                    return  # Success, exit

                # Failed, log and retry
                logger.error(f"❌ FEE FAILED: Attempt {attempt + 1}/{max_retries} failed: {msg}")

                if attempt < max_retries - 1:
                    # Wait before retry
                    await asyncio.sleep(60)

            # All retries failed - alert admin
            logger.error(f"❌ FEE FAILED: All {max_retries} attempts failed for user {user_id}, trade ${trade_amount}")
            # TODO: Send alert to admin (Telegram notification, email, etc.)

        except Exception as e:
            logger.error(f"❌ FEE FAILED: Background fee collection error for user {user_id}: {e}")

    async def _sync_tpsl_after_sell(
        self,
        user_id: int,
        token_id: str,
        sold_amount: float
    ):
        """
        Update or cancel TP/SL after manual sell (non-blocking background task)

        Args:
            user_id: Telegram user ID
            token_id: ERC-1155 token ID
            sold_amount: Amount of tokens sold
        """
        try:
            from telegram_bot.services.tpsl_service import get_tpsl_service
            from core.services import notification_service

            tpsl_service = get_tpsl_service()

            # Find active TP/SL for this token
            tpsl_order = tpsl_service.get_active_tpsl_by_token(user_id, token_id)

            if not tpsl_order:
                return  # No TP/SL, nothing to sync

            # Get remaining position size from blockchain
            remaining_tokens = await self.position_service.get_position_size(user_id, token_id)

            logger.info(f"📊 TP/SL SYNC: User {user_id} sold {sold_amount} tokens, {remaining_tokens} remaining")

            # Handle different scenarios
            if remaining_tokens == 0:
                # Position fully closed - cancel TP/SL
                tpsl_service.cancel_tpsl_order(tpsl_order.id, reason='position_closed')

                from telegram_bot.utils.escape_utils import escape_markdown
                market_question = escape_markdown(tpsl_order.market_data.get('question', 'Unknown')[:40]) if tpsl_order.market_data else 'Unknown'

                await notification_service.send_notification(
                    user_id,
                    f"🔔 **TP/SL Cancelled**\n\n"
                    f"📊 Market: {market_question}...\n"
                    f"💸 You sold all tokens\n\n"
                    f"Your TP/SL order was automatically cancelled."
                )
                logger.info(f"✅ TP/SL AUTO-CANCELLED: User {user_id} sold entire position")

            elif remaining_tokens < float(tpsl_order.monitored_tokens):
                # Partial close - update monitored amount
                old_amount = float(tpsl_order.monitored_tokens)
                tpsl_service.update_monitored_tokens(tpsl_order.id, remaining_tokens)

                market_question = escape_markdown(tpsl_order.market_data.get('question', 'Unknown')[:40]) if tpsl_order.market_data else 'Unknown'

                await notification_service.send_notification(
                    user_id,
                    f"🔔 **TP/SL Updated**\n\n"
                    f"📊 Market: {market_question}...\n"
                    f"📦 Tokens: {old_amount:.0f} → {remaining_tokens:.0f} (-{sold_amount:.0f})\n\n"
                    f"TP/SL now monitors {remaining_tokens:.0f} tokens\n"
                    f"Targets remain unchanged."
                )
                logger.info(f"✅ TP/SL UPDATED: User {user_id} reduced monitored tokens to {remaining_tokens}")

        except Exception as e:
            logger.error(f"❌ TP/SL SYNC AFTER SELL ERROR: {e}")

    async def _sync_tpsl_after_buy(
        self,
        user_id: int,
        token_id: str,
        new_tokens: float,
        new_entry_price: float
    ):
        """
        Update TP/SL with weighted average after buying more tokens (non-blocking)

        Strategy: Recalculate entry with weighted average, maintain same TP/SL percentages

        Example:
        - Old: 100 tokens @ $0.60, TP=$0.75 (+25%), SL=$0.45 (-25%)
        - Buy: 50 tokens @ $0.80
        - New: 150 tokens @ $0.667 avg, TP=$0.834 (+25%), SL=$0.500 (-25%)

        Args:
            user_id: Telegram user ID
            token_id: ERC-1155 token ID
            new_tokens: Number of tokens just bought
            new_entry_price: Price per token for new buy
        """
        try:
            from telegram_bot.services.tpsl_service import get_tpsl_service
            from core.services import notification_service
            from decimal import Decimal

            tpsl_service = get_tpsl_service()

            # Find active TP/SL for this token
            tpsl_order = tpsl_service.get_active_tpsl_by_token(user_id, token_id)

            if not tpsl_order:
                return  # No TP/SL, nothing to update

            # Calculate weighted average
            old_tokens = float(tpsl_order.monitored_tokens)
            old_entry = float(tpsl_order.entry_price)
            old_cost = old_tokens * old_entry

            new_cost = new_tokens * new_entry_price
            total_tokens = old_tokens + new_tokens
            total_cost = old_cost + new_cost
            new_avg_entry = total_cost / total_tokens

            logger.info(
                f"📊 TP/SL WEIGHTED AVG: User {user_id} - "
                f"Old: {old_tokens:.0f}@${old_entry:.4f} + New: {new_tokens:.0f}@${new_entry_price:.4f} "
                f"= Total: {total_tokens:.0f}@${new_avg_entry:.4f}"
            )

            # Calculate old TP/SL percentages
            old_tp = float(tpsl_order.take_profit_price) if tpsl_order.take_profit_price else None
            old_sl = float(tpsl_order.stop_loss_price) if tpsl_order.stop_loss_price else None

            tp_pct = None
            sl_pct = None
            new_tp = None
            new_sl = None

            if old_tp:
                tp_pct = (old_tp - old_entry) / old_entry
                new_tp = new_avg_entry * (1 + tp_pct)

            if old_sl:
                sl_pct = (old_sl - old_entry) / old_entry
                new_sl = new_avg_entry * (1 + sl_pct)

            # Update database
            from database import SessionLocal, TPSLOrder
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_order.id).first()

                if not tpsl:
                    return

                tpsl.entry_price = Decimal(str(new_avg_entry))
                tpsl.monitored_tokens = Decimal(str(total_tokens))

                if new_tp:
                    tpsl.take_profit_price = Decimal(str(new_tp))
                if new_sl:
                    tpsl.stop_loss_price = Decimal(str(new_sl))

                session.commit()

            # Notify user
            market_question = tpsl_order.market_data.get('question', 'Unknown')[:40] if tpsl_order.market_data else 'Unknown'

            message = f"🔔 **TP/SL Auto-Updated**\n\n"
            message += f"📊 **Market:** {market_question}...\n"
            message += f"➕ **You bought {new_tokens:.0f} more tokens @ ${new_entry_price:.4f}**\n\n"
            message += f"**Position Updated:**\n"
            message += f"📦 Tokens: {old_tokens:.0f} → {total_tokens:.0f} (+{new_tokens:.0f})\n"
            message += f"💰 Avg Entry: ${old_entry:.4f} → ${new_avg_entry:.4f}\n\n"
            message += f"**TP/SL Adjusted:**\n"

            if old_tp and new_tp and tp_pct:
                message += f"🎯 TP: ${old_tp:.4f} → ${new_tp:.4f} (still {tp_pct*100:+.1f}%)\n"

            if old_sl and new_sl and sl_pct:
                message += f"🛑 SL: ${old_sl:.4f} → ${new_sl:.4f} (still {sl_pct*100:+.1f}%)\n"

            message += "\n💡 Use /tpsl to customize targets"

            await notification_service.send_notification(user_id, message)
            logger.info(f"✅ TP/SL AUTO-UPDATED: User {user_id} weighted average recalculated")

        except Exception as e:
            logger.error(f"❌ TP/SL SYNC AFTER BUY ERROR: {e}")

    async def execute_buy(self, query, market_id: str, outcome: str, amount: float, market: dict) -> dict:
        """
        Execute buy order with user's wallet

        Args:
            query: Telegram callback query
            market_id: Market identifier
            outcome: "yes" or "no"
            amount: USD amount to spend
            market: Market data dictionary

        Returns:
            Dictionary with success status and message
        """
        try:
            import time
            from core.services import balance_checker  # ✅ FIX: Import at function start
            user_id = query.from_user.id

            # Clear pending trade state
            self.session_manager.clear_pending_trade(user_id)

            # Check if wallet is ready for trading
            wallet_ready, status_msg = user_service.is_wallet_ready(user_id)
            if not wallet_ready:
                await query.answer(f"❌ Wallet not ready: {status_msg}")
                return {
                    'success': False,
                    'message': f"❌ **Trading Not Available**\n\n{status_msg}\n\nUse /wallet to complete setup."
                }

            # FEE SYSTEM: Calculate required balance (trade + fee)
            fee_service = get_fee_service()
            fee_calc = fee_service.calculate_fee(user_id, amount)
            required_usdc = amount + float(fee_calc['fee_amount'])

            # Check if user has enough balance for trade + fee
            user = user_service.get_user(user_id)
            user_balance, _ = balance_checker.check_usdc_balance(user.polygon_address)

            if user_balance < required_usdc:
                await query.answer(f"❌ Insufficient balance")
                return {
                    'success': False,
                    'message': f"❌ **Insufficient Balance**\n\n"
                               f"💰 Required: ${required_usdc:.2f}\n"
                               f"   • Trade: ${amount:.2f}\n"
                               f"   • Fee (1%): ${fee_calc['fee_amount']:.2f}\n\n"
                               f"💼 Your Balance: ${user_balance:.2f}\n\n"
                               f"Please fund your wallet with /wallet"
                }

            logger.info(f"💰 FEE CALC: User {user_id} has ${user_balance:.2f}, needs ${required_usdc:.2f} (trade + fee)")

            await query.answer("⚡ Executing ultra-fast trade with your wallet...")

            # Get user-specific trader
            user_trader = self.get_trader(user_id)
            if not user_trader:
                return {
                    'success': False,
                    'message': "❌ **Error:** Unable to access your wallet. Please try /start again."
                }

            # Execute the trade with user's custom amount (FAST MODE for copy trading priority)
            trade_result = user_trader.speed_buy(market, outcome, amount, fast_mode=True)

            if trade_result and trade_result.get('order_id'):
                order_id = trade_result['order_id']

                # Check if this is a market order with transaction hash (instant execution)
                if trade_result.get('transaction_hash'):
                    print(f"🎉 INSTANT MARKET ORDER SUCCESS - No monitoring needed!")

                    # ENTERPRISE-GRADE TRANSACTION LOGGING FOR MARKET ORDERS
                    transaction_service = get_transaction_service()

                    # For market orders, extract real execution data
                    actual_tokens = trade_result.get('tokens', 0)
                    actual_cost = trade_result.get('total_cost', amount)
                    actual_price = actual_cost / actual_tokens if actual_tokens > 0 else 0

                    transaction_logged = transaction_service.log_trade(
                        user_id=user_id,
                        transaction_type='BUY',
                        market_id=str(market['id']),
                        outcome=outcome,
                        tokens=actual_tokens,
                        price_per_token=actual_price,
                        token_id=trade_result['token_id'],
                        order_id=order_id,
                        transaction_hash=trade_result['transaction_hash'],
                        market_data=market
                    )

                    if transaction_logged:
                        logger.info(f"✅ MARKET ORDER LOGGED: User {user_id} BUY {actual_tokens} {outcome} tokens")
                    else:
                        logger.error(f"❌ MARKET ORDER LOG FAILED: User {user_id} BUY order {order_id}")

                    # CRITICAL: Invalidate positions cache immediately after successful buy
                    try:
                        from core.services.redis_price_cache import get_redis_cache
                        redis_cache = get_redis_cache()
                        redis_cache.invalidate_user_positions(user.polygon_address)
                        logger.info(f"✅ CACHE INVALIDATED (Redis) immediately after BUY: {user.polygon_address}")

                        # PHASE 2: Also invalidate local blockchain cache
                        try:
                            from telegram_bot.services.blockchain_position_service import get_blockchain_position_service
                            blockchain_service = get_blockchain_position_service()
                            blockchain_service.refresh_user_positions(user_id, user.polygon_address)
                            logger.info(f"✅ CACHE INVALIDATED (Blockchain local) immediately after BUY: {user_id}")
                        except Exception as local_cache_err:
                            logger.warning(f"⚠️ Local cache invalidation failed: {local_cache_err}")

                        # PHASE 3: CRITICAL FIX - Invalidate copy trading position cache
                        # This ensures rapid BUY→SELL sequences have fresh data
                        try:
                            from core.services.copy_trading.position_checker import clear_position_cache
                            clear_position_cache(user.polygon_address)
                            logger.info(f"✅ CACHE INVALIDATED (Copy Trading) immediately after BUY: {user.polygon_address}")
                        except Exception as copy_cache_err:
                            logger.warning(f"⚠️ Copy trading cache invalidation failed: {copy_cache_err}")
                    except Exception as e:
                        logger.warning(f"⚠️ Cache invalidation failed (non-critical): {e}")

                    # ✨ NEW FIX: Add market to watched list IMMEDIATELY for instant execution
                    # This ensures Streamer subscribes within seconds, not 5 minutes!
                    try:
                        from core.services.watched_markets_service import get_watched_markets_service
                        watched_service = get_watched_markets_service()

                        market_condition_id = market.get('conditionId') or market.get('condition_id') or str(market['id'])
                        market_title = market.get('question') or market.get('title', 'Unknown Market')

                        # ✅ CRITICAL FIX: Use condition_id as market_id (not short market_id)
                        # watched_markets.market_id MUST = condition_id for JOIN to work
                        success_watched = await watched_service._add_watched_market(
                            market_id=market_condition_id,  # ✅ Use condition_id, not market['id']
                            condition_id=market_condition_id,
                            title=market_title,
                            position_count=1
                        )

                        if success_watched:
                            logger.info(f"📈 [INSTANT] Added market {market['id']} to watched list immediately after instant buy")
                        else:
                            logger.warning(f"⚠️ [INSTANT] Failed to add market {market['id']} to watched list")

                    except Exception as e:
                        logger.error(f"❌ [INSTANT] Error adding market to watched list: {e}")
                        # Non-critical - don't fail the trade

                    # ✨ PHASE 4: IMMEDIATE CACHE WARMING - Fetch and cache token price now
                    # This prevents 20s wait for next PriceUpdater cycle
                    try:
                        token_id = trade_result.get('token_id')
                        if token_id:
                            from core.services.price_updater_service import get_price_updater
                            price_updater = get_price_updater()
                            await price_updater.fetch_and_cache_missing_tokens([token_id])
                            logger.info(f"🔥 [INSTANT] Warmed cache for new position token {token_id[:10]}...")
                    except Exception as cache_warm_err:
                        logger.warning(f"⚠️ Cache warming failed (non-critical): {cache_warm_err}")

                    # FEE SYSTEM: Collect fee in background (non-blocking)
                    asyncio.create_task(
                        self._collect_fee_background(
                            user_id=user_id,
                            trade_amount=amount,
                            transaction_id=transaction_logged,
                            trade_type='BUY'
                        )
                    )

                    # Extract fee info safely before using in f-string
                    fee_amount = float(fee_calc.get('fee_amount', 0)) if fee_calc else 0
                    min_applied = fee_calc.get('minimum_applied', False) if fee_calc else False

                    message_text = f"""
🎉 **MARKET ORDER EXECUTED!**

✅ **Market:** {market['question'][:50]}...
🎯 **Position:** {outcome.upper()}
⚡ **Speed:** Instant execution!
💰 **Tokens Received:** {actual_tokens}
💵 **Cost:** ${actual_cost:.2f}
📋 **Order ID:** {order_id[:20]}...
🔗 **Transaction:** {trade_result['transaction_hash'][:20]}...

✅ **Confirmed on Polygonscan!**

🧾 **Fee (Testing):**
• Fee: ${fee_amount:.2f} (1%)
• Min applied: {min_applied}
• Collecting in background...

💡 **Tip:** Set Take Profit/Stop Loss to auto-sell at target prices!
Use /positions to configure TP/SL for this position.
                    """
                    return {'success': True, 'message': message_text}

                # Fallback: Monitor order for non-market orders (shouldn't happen now)
                filled = user_trader.monitor_order(order_id, timeout=30)

                # CRITICAL FIX: Log transaction IMMEDIATELY after order submission
                # Don't wait for monitoring - monitoring can fail even if trade succeeds
                transaction_service = get_transaction_service()
                transaction_logged = transaction_service.log_trade(
                    user_id=user_id,
                    transaction_type='BUY',
                    market_id=str(market['id']),
                    outcome=outcome,
                    tokens=trade_result['tokens'],
                    price_per_token=trade_result['buy_price'],
                    token_id=trade_result['token_id'],
                    order_id=order_id,
                    market_data=market
                )

                if transaction_logged:
                    logger.info(f"✅ BUY TRANSACTION LOGGED: User {user_id} BUY {trade_result['tokens']} {outcome} tokens")
                else:
                    logger.error(f"❌ BUY TRANSACTION LOG FAILED: User {user_id} BUY order {order_id}")

                if filled:# Track the actual position bought with enhanced data for P&L
                    self.position_service.add_position(
                        user_id=user_id,
                        market_id=str(market['id']),
                        outcome=outcome,
                        tokens=trade_result['tokens'],
                        buy_price=trade_result['buy_price'],
                        total_cost=trade_result['total_cost'],
                        token_id=trade_result['token_id'],
                        market_data=market
                    )

                    # Save positions after successful trade
                    self.session_manager.save_all_positions()

                    # PERFORMANCE: Invalidate balance cache after successful trade
                    try:
                        from core.services import balance_checker
                        balance_checker.invalidate_balance_cache(user.polygon_address, balance_type='usdc')
                        logger.debug(f"🗑️ Invalidated USDC balance cache after buy")
                    except Exception as e:
                        logger.debug(f"Cache invalidation failed (non-fatal): {e}")

                    # Add market to watched list for real-time price updates
                    try:
                        from core.services.watched_markets_service import get_watched_markets_service
                        watched_service = get_watched_markets_service()

                        # Add this market to watched list with market metadata
                        market_condition_id = market.get('conditionId') or market.get('condition_id') or str(market['id'])
                        market_title = market.get('question') or market.get('title', 'Unknown Market')

                        # ✅ CRITICAL FIX: Use condition_id as market_id (not short market_id)
                        # watched_markets.market_id MUST = condition_id for JOIN to work
                        success = await watched_service._add_watched_market(
                            market_id=market_condition_id,  # ✅ Use condition_id, not market['id']
                            condition_id=market_condition_id,
                            title=market_title,
                            position_count=1  # Will be updated by the scanning service
                        )

                        if success:
                            logger.info(f"📈 Added market {market['id']} to watched list after successful buy")
                        else:
                            logger.warning(f"⚠️ Failed to add market {market['id']} to watched list")

                        # ✅ NEW: Signal Streamer to refresh watched markets (speeds up subscription)
                        try:
                            from core.services.redis_price_cache import get_redis_cache
                            redis_cache = get_redis_cache()

                            if redis_cache.enabled:
                                # Set flag with 60s TTL (Streamer checks periodically)
                                redis_cache.redis_client.setex(
                                    "streamer:watched_markets_changed",
                                    60,
                                    "1"
                                )
                                logger.info(f"🔔 Flagged watched_markets change for Streamer (will subscribe on next check)")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to flag Streamer refresh: {e}")

                    except Exception as e:
                        logger.error(f"❌ Error adding market to watched list: {e}")
                        # Don't fail the trade if this fails

                    # TP/SL SYNC: Update TP/SL if user bought more of existing position
                    asyncio.create_task(
                        self._sync_tpsl_after_buy(
                            user_id=user_id,
                            token_id=trade_result['token_id'],
                            new_tokens=trade_result['tokens'],
                            new_entry_price=trade_result['buy_price']
                        )
                    )

                    # FEE SYSTEM: Collect fee in background (non-blocking)
                    asyncio.create_task(
                        self._collect_fee_background(
                            user_id=user_id,
                            trade_amount=amount,
                            transaction_id=transaction_logged,
                            trade_type='BUY'
                        )
                    )

                    message_text = f"""
✅ **TRADE EXECUTED**

Market: {market['question'][:50]}...
Position: {outcome.upper()}
Amount: {trade_result['tokens']} tokens
Cost: ${trade_result['total_cost']:.2f} (${trade_result['buy_price']:.4f} per token)
Order ID: {order_id[:20]}...
Speed: Instant fill

Fee: ${fee_amount:.2f} (1%) - {min_applied}
Collecting in background...

Use /positions to see P&L and manage holdings!
                    """
                    return {'success': True, 'message': message_text}
                else:
                    # ORDER FAILED - Don't send false positive success message
                    message_text = f"""
❌ **TRADE FAILED**

Order ID: {order_id[:20]}...
Position: {outcome.upper()}
Amount: ${amount:.2f}

Order timed out or failed to fill. Please try again.
                    """
                    return {'success': False, 'message': message_text}
            else:
                message_text = f"""
❌ **TRADE FAILED**

Please try again.
                """
                return {'success': False, 'message': message_text}

        except Exception as e:
            logger.error(f"Speed buy error with user wallet: {e}")

            # Check if this is a timeout error (order likely succeeded despite timeout)
            from telegram_bot.handlers.positions.utils import is_timeout_error
            error_msg = str(e)

            if is_timeout_error(e):
                logger.warning(f"⏱️ TIMEOUT detected during BUY - Order may have succeeded despite timeout")
                logger.warning(f"   Attempting to recover order from API...")

                # Try to get trader and fetch recent orders
                try:
                    user_trader = self.get_trader(user_id)
                    if user_trader:
                        # Fetch recent orders from API to see if order was actually placed
                        orders = user_trader.client.get_orders()
                        logger.info(f"📋 Retrieved {len(orders) if orders else 0} recent orders from API")

                        if orders:
                            # Look for a recent order matching this market + outcome
                            for order in orders:
                                order_timestamp = order.get('created_at', '')
                                # Basic check - if order is very recent and matches market, likely ours
                                if order.get('market') == market_id or order.get('outcome') == outcome:
                                    logger.info(f"✅ RECOVERY SUCCESS: Found matching order {order.get('id', 'Unknown')}")
                                    # Order was likely placed - show pending message instead of error
                                    message_text = f"""
⏳ **TRADE PENDING CONFIRMATION**

Your order was likely submitted despite the connection timeout.

📋 **Order Details:**
✅ **Market:** {market['question'][:50]}...
🎯 **Position:** {outcome.upper()}
💰 **Amount:** ${amount:.2f}

**Status:** Confirming on blockchain...

Please wait a moment and check /positions for updates.
If the trade doesn't appear, you can try again.
                    """
                                    return {'success': True, 'message': message_text}
                except Exception as recovery_err:
                    logger.warning(f"⚠️ Order recovery failed: {recovery_err}")

                # If we can't recover, show honest timeout message
                message_text = f"""
⏳ **CONNECTION TIMEOUT - Checking if trade went through...**

Your connection timed out, but your order **may have been submitted** to Polymarket.

**What happens now:**
1. Check your balance in a few seconds
2. Use /positions to see your trades
3. If the trade didn't go through, try again

**Order Details:**
✅ **Market:** {market['question'][:50]}...
🎯 **Position:** {outcome.upper()}
💰 **Amount:** ${amount:.2f}

**Need help?** Use /start to restart
                """
                return {'success': False, 'message': message_text}

            # Handle other specific errors
            if "No orderbook exists" in error_msg or "404" in error_msg:
                message_text = """
⚠️ **ILLIQUID MARKET DETECTED**

This market has no active orderbook (very low trading volume):
• Market is still open and tradeable
• Using market orders instead of limit orders
• May experience higher price impact

The system will automatically retry with market orders.
Please try your trade again in a moment.
                """
            else:
                message_text = f"❌ **Error:** {error_msg}"

            return {'success': False, 'message': message_text}

    async def execute_sell_copy(self, user_id: int, token_id: str, amount: float, market: dict) -> dict:
        """
        Execute sell order for copy trading (no query/session needed)

        Args:
            user_id: Telegram user ID
            token_id: CLOB token ID to sell
            amount: USD amount to sell
            market: Market data dictionary

        Returns:
            Dictionary with success status and message
        """
        try:
            from core.services import balance_checker  # ✅ FIX: Import at function start

            logger.info(f"🔄 [COPY_SELL] Starting sell for user {user_id}: token={token_id[:20]}..., amount=${amount:.2f}")

            # Check if wallet is ready for trading
            wallet_ready, status_msg = user_service.is_wallet_ready(user_id)
            if not wallet_ready:
                logger.error(f"❌ [COPY_SELL] Wallet not ready for user {user_id}: {status_msg}")
                return {
                    'success': False,
                    'message': f"❌ **Trading Not Available**\n\n{status_msg}\n\nUse /wallet to complete setup."
                }

            # ✅ NEW: Validate API credentials BEFORE attempting sell
            api_creds_dict = user_service.get_api_credentials(user_id)
            if not api_creds_dict:
                logger.error(f"❌ [COPY_SELL] No API credentials for user {user_id}")
                return {
                    'success': False,
                    'message': "❌ **API Credentials Missing**\n\nPlease use /start to set up your trading account."
                }

            # Check each credential is present
            for cred_name in ['api_key', 'api_secret', 'api_passphrase']:
                if not api_creds_dict.get(cred_name):
                    logger.error(f"❌ [COPY_SELL] Missing {cred_name} for user {user_id}")
                    return {
                        'success': False,
                        'message': f"❌ **Incomplete Credentials**\n\nMissing: {cred_name}\n\nPlease use /start to fix your setup."
                    }

            logger.info(f"✅ [COPY_SELL] API credentials validated for user {user_id}")

            # FEE SYSTEM: Calculate required balance (only fee needed for sells)
            fee_service = get_fee_service()
            fee_calc = fee_service.calculate_fee(user_id, amount)
            required_usdc = float(fee_calc['fee_amount'])  # Only fee needed, proceeds from sell cover it

            # Check if user has enough balance for fee (proceeds from sell will be received)
            user = user_service.get_user(user_id)
            user_balance, _ = balance_checker.check_usdc_balance(user.polygon_address)

            if user_balance < required_usdc:
                logger.warning(f"❌ [COPY_SELL] Insufficient balance for user {user_id}: has ${user_balance:.2f}, needs ${required_usdc:.2f} for fee")
                return {
                    'success': False,
                    'message': f"❌ **Insufficient Balance for Fee**\n\n"
                               f"💰 Required: ${required_usdc:.2f} (fee only)\n"
                               f"💼 Your Balance: ${user_balance:.2f}\n\n"
                               f"Please fund your wallet with /wallet"
                }

            logger.info(f"💰 [COPY_SELL] FEE CALC: User {user_id} has ${user_balance:.2f}, fee needed: ${required_usdc:.2f}")

            # Get user-specific trader
            user_trader = self.get_trader(user_id)
            if not user_trader:
                logger.error(f"❌ [COPY_SELL] Unable to get trader for user {user_id}")
                return {
                    'success': False,
                    'message': "❌ **Error:** Unable to access your wallet. Please try /start again."
                }

            # Convert USD amount to token count using current market price
            # We need to get the current price for this token
            try:
                from telegram_bot.services.market_service import MarketService
                market_service = MarketService()
                current_price, cache_hit, fetch_time, ttl = market_service.get_token_price_with_audit(token_id, context="trading")

                if current_price is None or current_price <= 0:
                    logger.error(f"❌ [COPY_SELL] Could not get price for token {token_id}")
                    return {
                        'success': False,
                        'message': "❌ **Error:** Could not fetch current market price."
                    }

                # Calculate tokens to sell: amount_usd / price_per_token
                tokens_to_sell = amount / current_price

                logger.info(f"💰 [COPY_SELL] Converting ${amount:.2f} to {tokens_to_sell:.4f} tokens at ${current_price:.4f}/token")

            except Exception as price_error:
                logger.error(f"❌ [COPY_SELL] Price calculation error: {price_error}")
                return {
                    'success': False,
                    'message': "❌ **Error:** Could not calculate token amount."
                }

            # Execute the sell using the correct method with token_id
            logger.info(f"⚡ [COPY_SELL] Executing sell for user {user_id}: {tokens_to_sell:.4f} tokens of {token_id[:20]}...")

            # Determine outcome for speed_sell_with_token_id
            # Extract from market data or use fallback logic
            outcome_str = 'yes'  # Default fallback
            if market and 'outcomes' in market:
                outcomes = market['outcomes']
                if isinstance(outcomes, list) and len(outcomes) > 0:
                    # Use first outcome as default, but try to match the token
                    outcome_str = outcomes[0].lower()
                    # For Polymarket: token_id = condition_id * 2 + outcome (0=NO, 1=YES)
                    # We can determine outcome from token_id if we have condition_id
                    if 'condition_id' in market:
                        try:
                            condition_id = int(market['condition_id'])
                            calculated_token = str(condition_id * 2 + (1 if outcome_str == 'yes' else 0))
                            if calculated_token == token_id:
                                pass  # outcome_str is already correct
                            else:
                                # Try the other outcome
                                other_outcome = 'no' if outcome_str == 'yes' else 'yes'
                                calculated_token_other = str(condition_id * 2 + (1 if other_outcome == 'yes' else 0))
                                if calculated_token_other == token_id:
                                    outcome_str = other_outcome
                        except (ValueError, KeyError):
                            pass  # Keep default

            trade_result = user_trader.speed_sell_with_token_id(
                market=market,
                outcome=outcome_str,
                tokens=int(tokens_to_sell * 1e6),  # Convert to microunits (6 decimals)
                token_id=token_id,
                fast_mode=True
            )

            if trade_result and trade_result.get('order_id'):
                order_id = trade_result['order_id']
                logger.info(f"✅ [COPY_SELL] Trade executed successfully for user {user_id}: order_id={order_id}")

                # Check if this is a market order with transaction hash (instant execution)
                if trade_result.get('transaction_hash'):
                    logger.info(f"🎉 [COPY_SELL] INSTANT MARKET ORDER SUCCESS - No monitoring needed!")

                    # ENTERPRISE-GRADE TRANSACTION LOGGING FOR MARKET ORDERS
                    transaction_service = get_transaction_service()

                    # For market orders, extract real execution data
                    actual_tokens = trade_result.get('tokens', 0)
                    actual_revenue = trade_result.get('total_revenue', amount)
                    actual_price = actual_revenue / actual_tokens if actual_tokens > 0 else 0

                    # Extract market_id and outcome from market data
                    market_id = str(market.get('id', 'unknown'))
                    outcome = 'yes' if trade_result.get('outcome') == 1 else 'no'  # CLOB uses 0/1, UI uses yes/no

                    transaction_logged = transaction_service.log_trade(
                        user_id=user_id,
                        transaction_type='SELL',
                        market_id=market_id,
                        outcome=outcome,
                        tokens=actual_tokens,
                        price_per_token=actual_price,
                        token_id=token_id,
                        order_id=order_id,
                        transaction_hash=trade_result['transaction_hash'],
                        market_data=market,
                        copy_trading_config={'is_copy_trade': True}  # ✅ Mark as copy trade
                    )

                    if transaction_logged:
                        logger.info(f"✅ [COPY_SELL] MARKET ORDER LOGGED: User {user_id} SELL {actual_tokens} tokens")
                        return {
                            'success': True,
                            'message': f"✅ **Sell Executed Successfully**\n\n"
                                       f"🎯 Sold: {actual_tokens:.4f} tokens\n"
                                       f"💰 Revenue: ${actual_revenue:.2f}\n"
                                       f"📊 Price: ${actual_price:.4f}/token\n\n"
                                       f"🔗 Order ID: {order_id[:20]}...",
                            'order_id': order_id,
                            'transaction_hash': trade_result['transaction_hash']
                        }
                    else:
                        logger.error(f"❌ [COPY_SELL] MARKET ORDER LOG FAILED: User {user_id} SELL order {order_id}")
                        return {
                            'success': False,
                            'message': "❌ **Error:** Trade executed but logging failed. Please check your positions."
                        }

                # For limit orders, start monitoring
                else:
                    logger.info(f"📊 [COPY_SELL] LIMIT ORDER PLACED: User {user_id} order {order_id}")

                    # Start monitoring the order
                    await self._monitor_order(user_id, order_id, 'SELL', market, amount, token_id)

                    return {
                        'success': True,
                        'message': f"✅ **Sell Order Placed**\n\n"
                                   f"💰 Amount: ${amount:.2f}\n"
                                   f"🔗 Order ID: {order_id[:20]}...\n\n"
                                   f"📊 Monitoring order execution...",
                        'order_id': order_id
                    }

            else:
                error_msg = trade_result.get('error', 'Unknown error') if trade_result else 'Trade execution failed'
                logger.error(f"❌ [COPY_SELL] Trade execution failed for user {user_id}: {error_msg}")
                return {
                    'success': False,
                    'message': f"❌ **Sell Failed**\n\n{error_msg}"
                }

        except Exception as e:
            logger.error(f"❌ [COPY_SELL] Unexpected error for user {user_id}: {e}", exc_info=True)
            return {
                'success': False,
                'message': f"❌ **Error:** {str(e)}"
            }

    async def execute_sell_like_buy(self, user_id: int, market_id: str, outcome: str, amount: float, market: dict) -> dict:
        """
        Execute sell order like execute_buy() - robust method for copy trading

        This method works exactly like execute_buy() but for selling:
        - Takes user_id, market_id, outcome, amount, market
        - Uses get_token_id_for_outcome() for robust token resolution
        - No dependency on Telegram query or session manager

        Args:
            user_id: User ID
            market_id: Market identifier
            outcome: "yes" or "no" (case insensitive)
            amount: USD amount to sell
            market: Market data dictionary

        Returns:
            Dictionary with success status and message
        """
        try:
            import time
            from core.services import balance_checker

            logger.info(f"💰 [SELL_LIKE_BUY] Starting sell for user {user_id}: market={market_id}, outcome={outcome}, amount=${amount:.2f}")

            # Get user-specific trader
            user_trader = self.get_trader(user_id)
            if not user_trader:
                return {
                    'success': False,
                    'message': "❌ **Error:** Unable to access your wallet. Please try /start again."
                }

            # FIXED: Use outcome-based token matching (same as execute_buy)
            from telegram_bot.utils.token_utils import get_token_id_for_outcome

            token_id = get_token_id_for_outcome(market, outcome)

            if not token_id:
                logger.error(f"❌ [TOKEN_ID_NOT_FOUND] market={market_id}, outcome={outcome}")
                return {
                    'success': False,
                    'message': f"❌ **Error:** Could not find token for outcome '{outcome}'"
                }

            # Get current price for the token
            from telegram_bot.services.market_service import MarketService
            market_service = MarketService()
            current_price, _, _, _ = market_service.get_token_price_with_audit(token_id, context="trading")

            if not current_price or current_price <= 0:
                logger.error(f"❌ [PRICE_NOT_FOUND] token_id={token_id}")
                return {
                    'success': False,
                    'message': "❌ **Error:** Could not get current market price."
                }

            # Convert USD amount to token amount
            tokens_to_sell = amount / current_price
            logger.info(f"🔄 [SELL_LIKE_BUY] Converting ${amount:.2f} to {tokens_to_sell:.4f} tokens at ${current_price:.4f}/token")

            # ✅ CRITICAL FIX: Check actual token balance before selling
            # Get user's wallet to check real token holdings
            from core.services.copy_trading.position_checker import get_follower_position_size
            from core.services import user_service

            user = user_service.get_user(user_id)
            if not user or not user.polygon_address:
                logger.error(f"❌ [SELL_LIKE_BUY] No wallet address for user {user_id}")
                return {
                    'success': False,
                    'message': "❌ **Error:** Wallet not found. Please use /start to setup."
                }

            # Check real-time position from Polymarket API
            actual_token_count, position_data = await get_follower_position_size(
                wallet_address=user.polygon_address,
                token_id=token_id,
                market_id=market_id,
                outcome=outcome
            )

            logger.info(f"🔍 [SELL_BALANCE_CHECK] User {user_id} has {actual_token_count:.4f} tokens, needs {tokens_to_sell:.4f} tokens")

            # If user has no tokens, skip this sell
            if actual_token_count == 0:
                logger.warning(f"⏭️ [SELL_SKIP] User {user_id} has NO position in this market, skipping sell")
                return {
                    'success': False,
                    'message': "⏭️ **Sell Skipped:** You don't have any tokens in this position.",
                    'skip_reason': 'NO_POSITION'
                }

            # If user has less tokens than needed, adjust to sell what they have
            if actual_token_count < tokens_to_sell:
                logger.warning(
                    f"⚖️ [SELL_ADJUST] User {user_id} has only {actual_token_count:.4f} tokens, "
                    f"adjusting from {tokens_to_sell:.4f} tokens (${amount:.2f})"
                )
                tokens_to_sell = actual_token_count
                adjusted_amount = tokens_to_sell * current_price
                logger.info(f"🔄 [SELL_ADJUSTED] New sell amount: {tokens_to_sell:.4f} tokens (${adjusted_amount:.2f})")

            # Execute the sell using the token-specific method
            logger.info(f"⚡ [SELL_LIKE_BUY] Executing sell for user {user_id}: {tokens_to_sell:.4f} tokens of {token_id[:20]}...")

            # Use the same outcome determination as execute_buy
            outcome_str = outcome.lower()  # "yes" or "no"

            # ✅ CRITICAL FIX: Get best_bid from orderbook for FAK pricing
            # This matches /positions flow which uses best_bid as suggested_price
            # FAK will then treat it as aggressive market order and find best buyer
            sell_price = current_price  # Fallback
            best_bid = 0

            try:
                orderbook = user_trader.client.get_order_book(token_id)
                if orderbook and orderbook.bids and len(orderbook.bids) > 0:
                    best_bid = float(orderbook.bids[0].price)
                    if best_bid > 0:
                        sell_price = best_bid
                        logger.info(f"✅ [SELL_BEST_BID] Using orderbook best_bid=${sell_price:.6f} for FAK execution")
                    else:
                        logger.warning(f"⚠️ [SELL_BEST_BID] best_bid={best_bid}, using fallback current_price=${current_price:.6f}")
                else:
                    logger.warning(f"⚠️ [SELL_BEST_BID] No bids on orderbook, using current_price=${current_price:.6f}")
            except Exception as ob_error:
                logger.warning(f"⚠️ [SELL_BEST_BID] Could not fetch orderbook: {ob_error}, using current_price=${current_price:.6f}")

            # ✅ CRITICAL FIX: Pass tokens in REAL units, not microunits
            # OrderArgs.size expects tokens in real units, the builder converts to microunits internally
            # ✅ IMPORTANT: Don't use fast_mode=True (FAK) for copy trading
            # FAK fails when orderbook is fragmented. Use default GTC (Good-Till-Cancelled) instead
            # GTC is more robust: creates limit order that waits for match, won't fail
            trade_result = user_trader.speed_sell_with_token_id(
                market=market,
                outcome=outcome_str,
                tokens=tokens_to_sell,  # ✅ FIX: Pass real tokens (1.19), NOT microunits (1190475)
                token_id=token_id,
                fast_mode=False,  # ✅ FIX: Use GTC (default) instead of FAK - more robust
                suggested_price=sell_price  # ✅ FIX: Use best_bid for FAK matching (like /positions does)
            )

            if trade_result and trade_result.get('order_id'):
                order_id = trade_result['order_id']

                # Check if this is a market order with transaction hash (instant execution)
                if trade_result.get('transaction_hash'):
                    logger.info(f"🎉 [SELL_LIKE_BUY] INSTANT MARKET ORDER SUCCESS for user {user_id}")

                    # Log the transaction
                    transaction_service = get_transaction_service()

                    actual_tokens = trade_result.get('tokens', tokens_to_sell)
                    actual_cost = trade_result.get('total_cost', amount)
                    actual_price = actual_cost / actual_tokens if actual_tokens > 0 else 0

                    transaction_logged = transaction_service.log_trade(
                        user_id=user_id,
                        transaction_type='SELL',
                        market_id=str(market['id']),
                        outcome=outcome,
                        tokens=-actual_tokens,  # Negative for sells
                        price_per_token=actual_price,
                        token_id=token_id,
                        order_id=order_id,
                        transaction_hash=trade_result['transaction_hash'],
                        market_data=market
                    )

                    if transaction_logged:
                        logger.info(f"✅ [SELL_LIKE_BUY] Transaction logged: User {user_id} SELL {actual_tokens} {outcome} tokens")
                    else:
                        logger.error(f"❌ [SELL_LIKE_BUY] Transaction log failed: User {user_id}")

                    # ✅ CRITICAL FIX: Clear position cache after successful sell
                    # This ensures next position check gets fresh data (important for rapid BUY→SELL sequences)
                    from core.services.copy_trading.position_checker import clear_position_cache
                    clear_position_cache(user.polygon_address)
                    logger.info(f"🔄 [CACHE_CLEAR] Position cache cleared for user {user_id} after SELL")

                    return {
                        'success': True,
                        'message': f"✅ **Sell Successful!**\n\nSold {actual_tokens:.2f} {outcome.upper()} tokens for ${actual_cost:.2f}",
                        'order_id': order_id,
                        'transaction_hash': trade_result['transaction_hash']
                    }
                else:
                    # Limit order - would need monitoring (not implemented for copy trading)
                    logger.info(f"📋 [SELL_LIKE_BUY] LIMIT ORDER placed: {order_id}")
                    return {
                        'success': True,
                        'message': f"✅ **Sell Order Placed!**\n\nOrder ID: {order_id}",
                        'order_id': order_id
                    }
            else:
                error_msg = trade_result.get('error', 'Unknown error') if trade_result else 'Trade execution failed'
                logger.error(f"❌ [SELL_LIKE_BUY] Trade execution failed for user {user_id}: {error_msg}")
                return {
                    'success': False,
                    'message': f"❌ **Sell Failed**\n\n{error_msg}"
                }

        except Exception as e:
            logger.error(f"❌ [SELL_LIKE_BUY] Unexpected error for user {user_id}: {e}", exc_info=True)
            return {
                'success': False,
                'message': f"❌ **Error:** {str(e)}"
            }

    async def execute_sell(self, query, market_id: str, outcome: str, amount: float) -> dict:
        """
        Execute sell order with user's wallet (ORIGINAL METHOD - keeps existing functionality)

        Args:
            query: Telegram callback query
            market_id: Market identifier
            outcome: "yes" or "no"
            amount: USD amount to sell (will be converted to tokens)

        Returns:
            Dictionary with success status and message
        """
        try:
            from core.services import balance_checker  # ✅ FIX: Import at function start
            user_id = query.from_user.id

            # Clear pending trade state
            self.session_manager.clear_pending_trade(user_id)

            # Check if user has position
            position = self.session_manager.get_position(user_id, market_id, outcome)
            if not position:
                await query.answer("❌ No position found")
                return {'success': False, 'message': "❌ No position found"}

            # CRITICAL DEBUG: Add comprehensive logging
            logger.info(f"🔍 SELL DEBUG - Position type: {type(position)}")
            logger.info(f"🔍 SELL DEBUG - Position content: {position}")

            # CRITICAL FIX: Handle both dict and string cases
            if isinstance(position, str):
                logger.error(f"❌ CRITICAL: Position is string, attempting JSON parse: {position}")
                try:
                    import json
                    position = json.loads(position)
                    # Update the session with the parsed position
                    self.session_manager.set_position(user_id, market_id, outcome, position)
                    logger.info(f"✅ Successfully parsed position from string")
                except Exception as parse_error:
                    logger.error(f"❌ Failed to parse position JSON: {parse_error}")
                    await query.answer("❌ Position data corrupted")
                    return {'success': False, 'message': "❌ Position data corrupted"}

            # Ensure position is a dictionary
            if not isinstance(position, dict):
                logger.error(f"❌ CRITICAL: Position is {type(position)} instead of dict: {position}")
                await query.answer("❌ Position data corrupted")
                return {'success': False, 'message': "❌ Position data corrupted"}

            if position['outcome'].lower() != outcome.lower():
                await query.answer("❌ No position in this outcome")
                return {'success': False, 'message': "❌ No position in this outcome"}

            # Check if wallet is ready for trading
            wallet_ready, status_msg = user_service.is_wallet_ready(user_id)
            if not wallet_ready:
                await query.answer(f"❌ Wallet not ready: {status_msg}")
                return {
                    'success': False,
                    'message': f"❌ **Trading Not Available**\n\n{status_msg}\n\nUse /wallet to complete setup."
                }

            # ✅ NEW: Validate API credentials BEFORE attempting sell
            api_creds_dict = user_service.get_api_credentials(user_id)
            if not api_creds_dict:
                logger.error(f"❌ No API credentials for user {user_id}")
                await query.answer("❌ API credentials missing")
                return {
                    'success': False,
                    'message': "❌ **API Credentials Missing**\n\nPlease use /start to set up your trading account."
                }

            # Check each credential is present
            for cred_name in ['api_key', 'api_secret', 'api_passphrase']:
                if not api_creds_dict.get(cred_name):
                    logger.error(f"❌ Missing {cred_name} for user {user_id}")
                    await query.answer(f"❌ {cred_name} missing")
                    return {
                        'success': False,
                        'message': f"❌ **Incomplete Credentials**\n\nMissing: {cred_name}\n\nPlease use /start to fix your setup."
                    }

            logger.info(f"✅ API credentials validated for user {user_id}")

            # FEE SYSTEM: Calculate required balance (trade + fee)
            fee_service = get_fee_service()
            fee_calc = fee_service.calculate_fee(user_id, amount)
            required_usdc = float(fee_calc['fee_amount'])  # Only fee needed, proceeds from sell cover it

            # Check if user has enough balance for fee (proceeds will come from sell)
            user = user_service.get_user(user_id)
            user_balance, _ = balance_checker.check_usdc_balance(user.polygon_address)

            # For sells, we just need enough for the fee (proceeds from sale will be received)
            if user_balance < required_usdc:
                await query.answer(f"❌ Insufficient balance for fee")
                return {
                    'success': False,
                    'message': f"❌ **Insufficient Balance for Fee**\n\n"
                               f"💰 Fee Required: ${fee_calc['fee_amount']:.2f} (1%)\n"
                               f"💼 Your Balance: ${user_balance:.2f}\n\n"
                               f"Please fund your wallet with /wallet"
                }

            logger.info(f"💰 FEE CALC: User {user_id} SELL - has ${user_balance:.2f}, fee ${required_usdc:.2f}")

            await query.answer("⚡ Executing sell order...")

            # Get user-specific trader
            user_trader = self.get_trader(user_id)
            if not user_trader:
                return {
                    'success': False,
                    'message': "❌ **Error:** Unable to access your wallet. Please try /start again."
                }

            # CRITICAL: Get market data from position (always available)
            market = position.get('market', {})
            if not market or not isinstance(market, dict):
                logger.error(f"❌ CRITICAL: Position missing market data: {position}")
                return {'success': False, 'message': "❌ **Error:** Position data incomplete. Please try again."}

            # CRITICAL: Get token_id directly from position data (most reliable source)
            token_id = position.get('token_id')
            if not token_id:
                logger.error(f"❌ CRITICAL: No token_id found in position data")
                return {'success': False, 'message': "❌ **Error:** Token ID not found. Please try again."}

            logger.info(f"🔍 SELL DEBUG: Using position data directly - market: {market.get('question', 'Unknown')[:50]}, token_id: {token_id}")

            # ✨ CRITICAL FIX: Fetch REAL market price BEFORE calculating tokens
            # This ensures we sell at current market price, not estimated price
            from telegram_bot.services.market_service import MarketService
            market_service = MarketService()

            real_price, cache_hit, fetch_time, ttl = market_service.get_token_price_with_audit(token_id, context="trading")

            if real_price is None:
                logger.error(f"❌ SELL ERROR: Could not fetch real market price for token {token_id}")
                await query.answer("❌ Could not fetch market price")
                return {'success': False, 'message': "❌ **Error:** Could not fetch current market price. Please try again."}

            # Log the market price fetch
            cache_source = "🚀 CACHE" if cache_hit else "📡 API"
            logger.info(
                f"💰 [SELL_PRICE_FETCH] token={token_id[:20]}... | "
                f"real_price=${real_price:.4f} | "
                f"source={cache_source} | "
                f"time={fetch_time*1000:.1f}ms"
            )

            # Calculate tokens to sell based on REAL market price
            # Not estimated price - this ensures we get the right amount of USD
            tokens_to_sell = min(int(amount / real_price), int(position['tokens']))

            logger.info(
                f"📊 [SELL_CALCULATION] amount=${amount:.2f} | "
                f"real_price=${real_price:.4f} | "
                f"tokens_to_sell={tokens_to_sell} | "
                f"available_tokens={int(position['tokens'])}"
            )

            # No database lookup needed - position has everything we need for selling

            # FIXED: Pass token_id directly to speed_sell instead of relying on market parsing (FAST MODE for copy trading priority)
            sell_result = user_trader.speed_sell_with_token_id(
                market,
                outcome,
                tokens_to_sell,
                token_id,
                fast_mode=True,
                suggested_price=real_price  # ✅ Use real market price
            )

            if sell_result and sell_result.get('order_id'):
                order_id = sell_result['order_id']

                # CRITICAL FIX: Log transaction IMMEDIATELY after order submission
                # Don't wait for monitoring - monitoring can fail even if trade succeeds
                transaction_service = get_transaction_service()
                sell_price = sell_result.get('sell_price', real_price) # Use real_price here

                transaction_logged = transaction_service.log_trade(
                    user_id=user_id,
                    transaction_type='SELL',
                    market_id=market_id,
                    outcome=outcome,
                    tokens=tokens_to_sell,
                    price_per_token=sell_price,
                    token_id=token_id,
                    order_id=order_id,
                    transaction_hash=sell_result.get('transaction_hash'),  # Add transaction hash
                    market_data=market
                )

                if transaction_logged:
                    logger.info(f"✅ SELL TRANSACTION LOGGED: User {user_id} SELL {tokens_to_sell} {outcome} tokens at ${sell_price:.4f}")
                else:
                    logger.error(f"❌ SELL TRANSACTION LOG FAILED: User {user_id} SELL order {order_id}")

                filled = user_trader.monitor_order(order_id, timeout=30)

                if filled:
                    # Update position
                    remaining_tokens = position['tokens'] - tokens_to_sell
                    if remaining_tokens <= 0:
                        # Remove position entirely
                        self.position_service.remove_position(user_id, market_id, outcome)
                    else:
                        # Update remaining tokens
                        position['tokens'] = remaining_tokens
                        self.session_manager.set_position(user_id, market_id, outcome, position)

                    # Save positions after successful trade
                    self.session_manager.save_all_positions()

                    # PERFORMANCE: Invalidate balance cache after successful trade
                    try:
                        from core.services import balance_checker
                        balance_checker.invalidate_balance_cache(user.polygon_address, balance_type='usdc')
                        logger.debug(f"🗑️ Invalidated USDC balance cache after sell")
                    except Exception as e:
                        logger.debug(f"Cache invalidation failed (non-fatal): {e}")

                    # Log sell event for watched markets tracking
                    try:
                        logger.info(f"📉 Market {market_id} sold by user {user_id} - {remaining_tokens} tokens remaining")

                        # Note: We don't remove from watched list here as other users might still have positions
                        # The watched_markets_service will periodically scan and clean up

                    except Exception as e:
                        logger.error(f"❌ Error logging sell event: {e}")

                    # TP/SL SYNC: Update or cancel TP/SL after manual sell
                    asyncio.create_task(
                        self._sync_tpsl_after_sell(
                            user_id=user_id,
                            token_id=token_id,
                            sold_amount=tokens_to_sell
                        )
                    )

                    # FEE SYSTEM: Collect fee in background (non-blocking)
                    asyncio.create_task(
                        self._collect_fee_background(
                            user_id=user_id,
                            trade_amount=amount,
                            transaction_id=transaction_logged,
                            trade_type='SELL'
                        )
                    )

                    proceeds = tokens_to_sell * sell_result.get('sell_price', real_price)

                    # Calculate P&L
                    buy_price = position.get('buy_price', 0)
                    pnl_value = proceeds - (tokens_to_sell * buy_price)
                    pnl_pct = (pnl_value / (tokens_to_sell * buy_price) * 100) if (tokens_to_sell * buy_price) > 0 else 0

                    # Format P&L indicator
                    if pnl_value >= 0:
                        pnl_indicator = f"🟢 **+${pnl_value:.2f} (+{pnl_pct:.1f}%)**"
                    else:
                        pnl_indicator = f"🔴 **${pnl_value:.2f} ({pnl_pct:.1f}%)**"

                    # Format transaction ID nicely
                    tx_display = str(transaction_logged)[:16] + "..." if transaction_logged else "Pending"

                    # Extract fee info safely before using in f-string
                    fee_amount = float(fee_calc.get('fee_amount', 0)) if fee_calc else 0
                    min_applied = fee_calc.get('minimum_applied', False) if fee_calc else False

                    message_text = f"""
💰 **SELL EXECUTED!**

✅ **Market:** {market['question'][:50]}...
🎯 **Position:** {outcome.upper()}
📦 **Sold:** {tokens_to_sell} tokens
💵 **Amount Received:** ${proceeds:.2f}
{pnl_indicator}

📋 **Transaction ID:** `{tx_display}`
📊 **Order ID:** `{order_id[:20]}...`

🧾 **Fee (Testing):**
• Fee: ${fee_amount:.2f} (1%)
• Min applied: {min_applied}
• Collecting in background...

Use /positions to see updated holdings!
                    """
                    return {'success': True, 'message': message_text}
                else:
                    message_text = f"""
⏳ **SELL ORDER PLACED**

📋 **Order ID:** {order_id[:20]}...
🎯 **Position:** {outcome.upper()}
📦 **Amount:** {tokens_to_sell} tokens

Order may still be filling. Check /positions for updates.
                    """
                    return {'success': True, 'message': message_text}
            else:
                message_text = f"""
❌ **SELL FAILED**

Please try again or check your position.
                """
                return {'success': False, 'message': message_text}

        except Exception as e:
            from py_clob_client.exceptions import PolyApiException

            logger.error(f"Sell error: {e}", exc_info=True)

            # Handle specific API errors
            if isinstance(e, PolyApiException):
                if e.status_code == 403:
                    logger.error(f"❌ 403 FORBIDDEN - API credentials invalid")
                    return {
                        'success': False,
                        'message': "❌ **Authentication Failed**\n\nYour API credentials are invalid or expired.\n\nPlease use /start to re-authenticate."
                    }
                elif e.status_code == 429:
                    logger.error(f"❌ 429 RATE LIMITED")
                    return {
                        'success': False,
                        'message': "❌ **Rate Limited**\n\nAPI is rate-limited. Please wait and try again."
                    }
                else:
                    return {
                        'success': False,
                        'message': f"❌ **API Error:** Status {e.status_code}\n\nPlease try again."
                    }

            return {'success': False, 'message': f"❌ **Error:** {str(e)}"}

    async def _force_refresh_positions_after_trade(self, user_id: int, wallet_address: str):
        """
        PHASE 3: Force refresh user positions immediately after a successful trade
        Loads fresh positions from Polymarket API, bypassing all caches

        Args:
            user_id: Telegram user ID
            wallet_address: User's Polygon wallet address
        """
        try:
            import aiohttp
            import time

            logger.info(f"🔄 PHASE 3 START: Force-refreshing positions for user {user_id}")

            # Wait 2 seconds for blockchain to process the transaction
            await asyncio.sleep(2)

            # Call Polymarket API directly to get fresh positions (ASYNC)
            url = f"https://data-api.polymarket.com/positions?user={wallet_address}"

            from core.utils.aiohttp_client import get_http_client
            session = await get_http_client()

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    fresh_positions = await response.json()
                    logger.info(f"✅ PHASE 3 COMPLETE: Fetched {len(fresh_positions)} fresh positions for user {user_id}")

                    # Cache the fresh positions in Redis with short TTL
                    from core.services.redis_price_cache import get_redis_cache
                    redis_cache = get_redis_cache()
                    from config.config import POSITION_CACHE_TTL
                    redis_cache.cache_user_positions(wallet_address, fresh_positions, ttl=POSITION_CACHE_TTL)
                    logger.info(f"💾 PHASE 3: Cached fresh positions (180s TTL) for {wallet_address[:10]}...")
                else:
                    logger.warning(f"⚠️ PHASE 3: Failed to fetch fresh positions (status {response.status})")

        except Exception as e:
            logger.warning(f"⚠️ PHASE 3: Force refresh failed (non-critical): {e}")
            # This is non-blocking, so we don't propagate the error
