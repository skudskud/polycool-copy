#!/usr/bin/env python3
"""
Price Monitor - Background Task
Continuously monitors TP/SL orders and triggers automatic sells when targets are hit
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from telegram_bot.services.tpsl_service import get_tpsl_service
from telegram_bot.services.market_service import market_service
from telegram_bot.services.trading_service import TradingService
from core.services import notification_service

logger = logging.getLogger(__name__)


class PriceMonitor:
    """
    Background task that continuously monitors prices for active TP/SL orders
    Checks every 10 seconds and triggers automatic sells when targets are hit
    """

    def __init__(self, trading_service: TradingService, check_interval: int = 10):
        """
        Initialize price monitor

        Args:
            trading_service: TradingService instance for executing sells
            check_interval: Seconds between price checks (default: 10)
        """
        self.trading_service = trading_service
        self.tpsl_service = get_tpsl_service()
        self.check_interval = check_interval
        self.is_running = False
        self.monitor_task = None

        logger.info(f"✅ Price Monitor initialized (check interval: {check_interval}s)")

    async def start(self):
        """Start the price monitoring background task"""
        if self.is_running:
            logger.warning("⚠️ Price Monitor already running")
            return

        self.is_running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("🚀 Price Monitor started")

    async def stop(self):
        """Stop the price monitoring background task"""
        if not self.is_running:
            logger.warning("⚠️ Price Monitor not running")
            return

        self.is_running = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 Price Monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop - runs continuously"""
        logger.info("🔄 Price Monitor loop started")

        while self.is_running:
            try:
                await self._check_all_tpsl_orders()
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("🛑 Price Monitor loop cancelled")
                break

            except Exception as e:
                logger.error(f"❌ Price Monitor loop error: {e}")
                # Continue running even if one iteration fails
                await asyncio.sleep(self.check_interval)

    async def _check_all_tpsl_orders(self):
        """Check all active TP/SL orders and trigger if conditions met"""
        try:
            # Get all active TP/SL orders
            active_orders = self.tpsl_service.get_active_tpsl_orders()

            if not active_orders:
                logger.info("📭 No active TP/SL orders to monitor")
                return

            logger.info(f"🔍 Checking {len(active_orders)} active TP/SL orders")

            # ✅ ENHANCED: Use new method that includes Poller fallback with market_id context
            # This ensures accurate prices even when WebSocket is down and API has no liquidity
            prices_by_order_id = market_service.get_prices_for_tpsl_batch(active_orders)

            # Check each order
            for order in active_orders:
                try:
                    current_price = prices_by_order_id.get(order.id)
                    await self._check_single_order(order, current_price)
                except Exception as e:
                    logger.error(f"❌ Error checking TP/SL order {order.id}: {e}")
                    continue

            logger.info(f"✅ TP/SL check cycle completed - {len(active_orders)} orders checked")

        except Exception as e:
            logger.error(f"❌ CHECK ALL TP/SL ORDERS ERROR: {e}")

    async def _check_single_order(self, order, current_price: Optional[float]):
        """
        Check a single TP/SL order and trigger if needed

        Args:
            order: TPSLOrder object
            current_price: Current token price (or None if failed to fetch)
        """
        try:
            # Update last price check timestamp
            self.tpsl_service.update_last_price_check(order.id)

            # PHASE 1: Validate position still exists (cleanup ghost orders)
            position_exists = await self._validate_position_exists(order)
            if not position_exists:
                logger.warning(f"👻 Ghost TP/SL detected! Order {order.id} has no position - cancelling")
                self.tpsl_service.cancel_tpsl_order(order.id, reason="position_not_found")
                return

            # PHASE 2: Check market status (before price checking)
            market_status = await self._check_market_status(order)
            if market_status in ['closed', 'resolved']:
                await self._handle_market_ended(order, market_status)
                return

            # Can't check without price
            if current_price is None:
                logger.warning(f"⚠️ Skipping TP/SL order {order.id} - price unavailable")
                return

            entry_price = float(order.entry_price)
            tp_price = float(order.take_profit_price) if order.take_profit_price else None
            sl_price = float(order.stop_loss_price) if order.stop_loss_price else None

            # Check Take Profit
            if tp_price and current_price >= tp_price:
                logger.info(f"🎯 TAKE PROFIT HIT! Order {order.id} - Current: ${current_price:.4f} >= TP: ${tp_price:.4f}")
                await self._trigger_tpsl_sell(order, 'take_profit', current_price)
                return

            # Check Stop Loss
            if sl_price and current_price <= sl_price:
                logger.info(f"🛑 STOP LOSS HIT! Order {order.id} - Current: ${current_price:.4f} <= SL: ${sl_price:.4f}")
                await self._trigger_tpsl_sell(order, 'stop_loss', current_price)
                return

            # Log price status every check for visibility
            logger.info(f"📊 Order {order.id} - Entry: ${entry_price:.4f}, Current: ${current_price:.4f}, TP: ${tp_price or 0:.4f}, SL: ${sl_price or 0:.4f}")

        except Exception as e:
            logger.error(f"❌ CHECK SINGLE ORDER ERROR (Order {order.id}): {e}")

    async def _trigger_tpsl_sell(self, order, trigger_type: str, execution_price: float):
        """
        Trigger automatic sell when TP/SL condition is met

        Args:
            order: TPSLOrder object
            trigger_type: 'take_profit' or 'stop_loss'
            execution_price: Price at which trigger occurred
        """
        try:
            logger.info(f"⚡ TRIGGERING {trigger_type.upper()} SELL for Order {order.id}")

            # Get user trader
            user_trader = self.trading_service.get_trader(order.user_id)
            if not user_trader:
                logger.error(f"❌ Cannot get trader for user {order.user_id}")
                return

            # Verify position still exists and has enough tokens (BLOCKCHAIN-BASED)
            # Uses Polymarket API (source of truth) instead of local transaction calculations
            from core.services import user_service
            import requests

            # Get user's wallet address
            wallet = user_service.get_user_wallet(order.user_id)
            if not wallet:
                logger.error(f"❌ Cannot get wallet for user {order.user_id}")
                self.tpsl_service.cancel_tpsl_order(order.id, reason="wallet_not_found")
                return

            wallet_address = wallet['address']

            # Fetch real positions from Polymarket API (with Redis caching)
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()

            # Check cache first (30s TTL)
            cached_positions = redis_cache.get_user_positions(wallet_address)

            if cached_positions is not None:
                positions_data = cached_positions
                logger.debug(f"🚀 CACHE HIT: Loaded positions from Redis for TP/SL validation")
            else:
                # Cache miss - fetch from blockchain API
                logger.debug(f"💨 CACHE MISS: Fetching positions from Polymarket API for TP/SL validation")
                try:
                    url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
                    # CRITICAL FIX: Use async aiohttp instead of sync requests
                    from core.utils.aiohttp_client import get_http_client
                    import aiohttp
                    session = await get_http_client()
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            logger.error(f"❌ Polymarket API error: {response.status}")
                            return
                        positions_data = await response.json()

                    # Cache for 30 seconds
                    redis_cache.cache_user_positions(wallet_address, positions_data, ttl=30)

                except Exception as e:
                    logger.error(f"❌ Failed to fetch positions from blockchain: {e}")
                    return

            # Match position by 'asset' field (Polymarket API uses 'asset' not 'id')
            # API response structure: {'asset': '<token_id>', 'conditionId': '<market_id>', 'outcome': 'Yes', 'size': 10.5, ...}
            position = next((p for p in positions_data if str(p.get('asset')) == str(order.token_id)), None)

            if not position:
                logger.warning(f"⚠️ Position not found for Order {order.id}")
                logger.warning(f"   Looking for token_id: {order.token_id}")
                logger.warning(f"   API returned {len(positions_data)} positions")
                logger.warning(f"   Cancelling TP/SL order")
                self.tpsl_service.cancel_tpsl_order(order.id, reason="position_not_found")
                return

            # Get actual token count from blockchain
            available_tokens = float(position.get('size', 0))
            monitored_tokens = float(order.monitored_tokens)

            # Sell the lesser of: monitored tokens or available tokens
            tokens_to_sell = min(monitored_tokens, available_tokens)

            if tokens_to_sell <= 0:
                logger.warning(f"⚠️ No tokens to sell for TP/SL order {order.id}, cancelling")
                self.tpsl_service.cancel_tpsl_order(order.id, reason="no_tokens")
                return

            logger.info(f"💰 Executing TP/SL sell: {tokens_to_sell} tokens @ ${execution_price:.4f}")
            logger.info(f"📊 Blockchain position: {available_tokens} tokens, Monitored: {monitored_tokens}, Selling: {tokens_to_sell}")

            # Execute market sell
            # Use market_data from TP/SL order (stored when order was created)
            market_data = order.market_data or {}
            sell_result = user_trader.speed_sell_with_token_id(
                market_data,
                order.outcome,
                int(tokens_to_sell),
                order.token_id,
                is_tpsl_sell=True  # CRITICAL FIX (Bug #9): Use conservative pricing for TP/SL
            )

            if sell_result and sell_result.get('order_id'):
                # Calculate actual sell price FIRST (needed for DB update)
                entry_price_float = float(order.entry_price)

                # ✅ FIX: Use REAL price if available, not fallback estimate
                if sell_result.get('is_real') and 'total_received' in sell_result:
                    # BEST: Calculate from actual proceeds (most accurate)
                    tokens_sold_actual = sell_result.get('tokens_sold', tokens_to_sell)
                    total_received = sell_result['total_received']
                    actual_sell_price = total_received / tokens_sold_actual if tokens_sold_actual > 0 else execution_price
                    logger.info(f"✅ Using REAL execution price (from total_received): ${actual_sell_price:.4f} (received ${total_received:.2f})")
                elif sell_result.get('is_real'):
                    # GOOD: Use real price from order monitoring
                    actual_sell_price = sell_result['sell_price']
                    logger.info(f"✅ Using REAL sell_price from execution: ${actual_sell_price:.4f}")
                else:
                    # FALLBACK: Estimated price (may be inaccurate!)
                    actual_sell_price = sell_result.get('sell_price', execution_price)
                    logger.warning(f"⚠️ Using ESTIMATED sell price: ${actual_sell_price:.4f} (is_real=False - may be inaccurate!)")

                # Mark TP/SL as triggered with initial trigger price
                self.tpsl_service.mark_as_triggered(order.id, trigger_type, execution_price)

                # CRITICAL FIX (Bug #9 - Phase 3): Update DB with ACTUAL execution price
                # (not just trigger price, but the price we actually sold at after discount)
                from database import SessionLocal, TPSLOrder
                from decimal import Decimal
                try:
                    with SessionLocal() as session:
                        tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == order.id).first()
                        if tpsl:
                            tpsl.execution_price = Decimal(str(actual_sell_price))
                            session.commit()
                            logger.info(f"✅ Updated DB execution_price to ACTUAL sell price: ${actual_sell_price:.4f}")
                except Exception as db_error:
                    logger.error(f"❌ Failed to update execution_price in DB: {db_error}")

                # Calculate P&L for logging and notification
                # ✅ Use total_received if available (most accurate)
                if 'total_received' in sell_result:
                    proceeds = sell_result['total_received']
                    tokens_actually_sold = sell_result.get('tokens_sold', tokens_to_sell)
                else:
                    proceeds = tokens_to_sell * actual_sell_price
                    tokens_actually_sold = tokens_to_sell

                cost = tokens_actually_sold * entry_price_float
                profit = proceeds - cost
                profit_pct = (profit / cost * 100) if cost > 0 else 0

                logger.info(f"📊 P&L Calculation: Cost ${cost:.2f} - Proceeds ${proceeds:.2f} = ${profit:.2f} ({profit_pct:+.1f}%)")

                # Enhance market_data with TP/SL trigger information
                enhanced_market_data = {
                    **(market_data or {}),  # Original market data
                    "tpsl_trigger": {  # NEW: TP/SL trigger metadata
                        "type": trigger_type,  # "stop_loss" or "take_profit"
                        "order_id": order.id,  # Link to TP/SL order
                        "target_price": float(order.take_profit_price) if trigger_type == 'take_profit' else float(order.stop_loss_price) if order.stop_loss_price else execution_price,
                        "entry_price": entry_price_float,
                        "execution_price": actual_sell_price,
                        "pnl": {
                            "amount": round(profit, 2),
                            "percent": round(profit_pct, 1)
                        },
                        "triggered_at": datetime.utcnow().isoformat()
                    }
                }

                # Log transaction WITH TP/SL metadata
                from telegram_bot.services.transaction_service import get_transaction_service
                transaction_service = get_transaction_service()
                transaction_service.log_trade(
                    user_id=order.user_id,
                    transaction_type='SELL',
                    market_id=order.market_id,
                    outcome=order.outcome,
                    tokens=tokens_actually_sold,  # ✅ Use actual tokens sold
                    price_per_token=actual_sell_price,  # ✅ Already fixed above
                    token_id=order.token_id,
                    order_id=sell_result['order_id'],
                    transaction_hash=sell_result.get('transaction_hash'),
                    market_data=enhanced_market_data  # Enhanced with TP/SL info
                )

                logger.info(f"📝 Transaction logged: {tokens_actually_sold} tokens @ ${actual_sell_price:.4f} = ${proceeds:.2f}")

                logger.info(f"✅ TP/SL transaction logged with trigger metadata: Order #{order.id}, P&L: ${profit:+.2f}")

                # Send notification
                await self._send_tpsl_notification(
                    order,
                    trigger_type,
                    execution_price,
                    actual_sell_price,
                    tokens_actually_sold,  # ✅ Use actual tokens sold
                    profit,
                    profit_pct,
                    enhanced_market_data
                )

                logger.info(f"✅ TP/SL SELL EXECUTED: Order {order.id} - Profit: ${profit:.2f} ({profit_pct:+.2f}%)")
            else:
                logger.error(f"❌ TP/SL SELL FAILED: Order {order.id}")
                # Don't mark as triggered - will retry next check

        except Exception as e:
            logger.error(f"❌ TRIGGER TP/SL SELL ERROR: {e}")

    async def _send_tpsl_notification(
        self,
        order,
        trigger_type: str,
        trigger_price: float,
        actual_price: float,
        tokens_sold: float,
        profit: float,
        profit_pct: float,
        market_data: dict
    ):
        """Send Telegram notification when TP/SL is triggered"""
        try:
            market_question = market_data.get('question', 'Unknown Market')[:50]
            entry_price = float(order.entry_price)

            # ✅ Determine message tone based on ACTUAL profit, not trigger type
            # A "take profit" can still be a loss if market crashed before execution
            if profit >= 0:
                emoji = "🎉"
                title = "TAKE PROFIT HIT!" if trigger_type == 'take_profit' else "STOP LOSS TRIGGERED"
                status = "Position closed with profit ✅"
            else:
                emoji = "🛑"
                title = "TAKE PROFIT HIT!" if trigger_type == 'take_profit' else "STOP LOSS TRIGGERED"
                status = "Position closed with loss ⚠️"

            # Calculate total proceeds for clarity
            total_proceeds = tokens_sold * actual_price

            message = f"""
{emoji} **{title}**

Market: {market_question}...
Position: {order.outcome.upper()}
Tokens Sold: {tokens_sold:.2f}

Entry: ${entry_price:.4f}
Exit: ${actual_price:.4f}
Total Received: ${total_proceeds:.2f}

P&L: {profit_pct:+.1f}%

{status}

Use /positions to see remaining positions
Use /tpsl to view other TP/SL orders
            """.strip()

            # Send notification (use send_message, not send_notification!)
            success = await notification_service.send_message(order.user_id, message)
            if success:
                logger.info(f"✅ Notification sent to user {order.user_id}")
            else:
                logger.warning(f"⚠️ Failed to send notification to user {order.user_id}")

        except Exception as e:
            logger.error(f"❌ SEND TP/SL NOTIFICATION ERROR: {e}")

    async def _validate_position_exists(self, order) -> bool:
        """
        Validate that the position for this TP/SL order still exists on-chain
        Used to cleanup "ghost" orders for positions that were sold manually

        Args:
            order: TPSLOrder object

        Returns:
            True if position exists, False otherwise
        """
        try:
            from core.services import user_service
            from core.services.redis_price_cache import get_redis_cache
            import requests

            # Get user's wallet address
            wallet_data = user_service.get_user_wallet(order.user_id)
            if not wallet_data:
                logger.error(f"❌ No wallet found for user {order.user_id}")
                return False

            wallet_address = wallet_data.get('address')
            if not wallet_address:
                logger.error(f"❌ Invalid wallet data for user {order.user_id}")
                return False

            # Check Redis cache first (30s TTL)
            redis_cache = get_redis_cache()
            cached_positions = redis_cache.get_user_positions(wallet_address)

            if cached_positions is not None:
                positions_data = cached_positions
            else:
                # Cache miss - fetch from blockchain API
                try:
                    url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
                    # CRITICAL FIX: Use async aiohttp instead of sync requests
                    from core.utils.aiohttp_client import get_http_client
                    import aiohttp
                    session = await get_http_client()
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            logger.error(f"❌ Polymarket API error: {response.status}")
                            return True  # Assume exists if API fails (don't delete on API error)
                        positions_data = await response.json()

                    # Cache for 30 seconds
                    redis_cache.cache_user_positions(wallet_address, positions_data, ttl=30)

                except Exception as e:
                    logger.error(f"❌ Failed to fetch positions: {e}")
                    return True  # Assume exists if fetch fails

            # Match position by 'asset' field (token_id)
            position = next((p for p in positions_data if str(p.get('asset')) == str(order.token_id)), None)

            if not position:
                logger.info(f"❌ Position validation failed for Order {order.id} (token_id: {order.token_id[:20]}...)")
                return False

            # Check if position has non-zero size
            position_size = float(position.get('size', 0))
            if position_size <= 0:
                logger.info(f"❌ Position has zero size for Order {order.id}")
                return False

            logger.debug(f"✅ Position validated for Order {order.id} ({position_size} tokens)")
            return True

        except Exception as e:
            logger.error(f"❌ VALIDATE POSITION ERROR: {e}")
            return True  # Assume exists on error (don't delete)

    async def _check_market_status(self, order) -> str:
        """
        Check if market is active, closed, or resolved

        Args:
            order: TPSLOrder object

        Returns:
            'active', 'closed', 'resolved', or 'unknown'
        """
        try:
            market = market_service.get_market_by_id(order.market_id)

            if not market:
                logger.warning(f"⚠️ Market not found: {order.market_id}")
                return 'unknown'

            # Check market status (Polymarket uses: 'active', 'closed', 'resolved')
            status = market.get('active', True)  # Default to active if not specified

            # If it's a boolean, convert to string
            if isinstance(status, bool):
                return 'active' if status else 'closed'

            # If it's already a string, return lowercase
            return str(status).lower()

        except Exception as e:
            logger.error(f"❌ CHECK MARKET STATUS ERROR: {e}")
            return 'unknown'

    async def _handle_market_ended(self, order, market_status: str):
        """
        Handle TP/SL cancellation when market closes or resolves

        Args:
            order: TPSLOrder object
            market_status: 'closed' or 'resolved'
        """
        try:
            logger.info(f"🏁 Market ended ({market_status}) for TP/SL order {order.id}")

            # Cancel TP/SL with appropriate reason
            reason = 'market_resolved' if market_status == 'resolved' else 'market_closed'
            self.tpsl_service.cancel_tpsl_order(order.id, reason=reason)

            # Get position data
            from telegram_bot.services.position_service import get_position_size
            position_size = 0  # Default if we can't get size

            try:
                # Try to get actual position size
                position_size = await self.trading_service.position_service.get_position_size(
                    order.user_id,
                    order.token_id
                )
            except Exception as e:
                logger.warning(f"⚠️ Could not get position size: {e}")

            entry_price = float(order.entry_price)
            entry_value = entry_price * position_size if position_size > 0 else 0

            # Calculate P&L if we have position data
            final_price = None
            final_value = 0
            profit = 0
            profit_pct = 0

            if position_size > 0:
                # Get current price for closed markets, or 1.0/0.0 for resolved
                if market_status == 'resolved':
                    # For resolved markets, try to get winning outcome
                    # For now, use current price as proxy
                    current_price = market_service.get_token_price(order.token_id, order.market_id)
                    final_price = current_price if current_price else entry_price
                else:
                    # Market closed but not resolved - use current price
                    current_price = market_service.get_token_price(order.token_id, order.market_id)
                    final_price = current_price if current_price else entry_price

                final_value = final_price * position_size
                profit = final_value - entry_value
                if entry_value > 0:
                    profit_pct = (profit / entry_value) * 100

            # Send notification
            await self._send_market_ended_notification(
                order=order,
                market_status=market_status,
                position_size=position_size,
                entry_price=entry_price,
                entry_value=entry_value,
                final_price=final_price,
                final_value=final_value,
                profit=profit,
                profit_pct=profit_pct
            )

        except Exception as e:
            logger.error(f"❌ HANDLE MARKET ENDED ERROR: {e}")

    async def _send_market_ended_notification(
        self,
        order,
        market_status: str,
        position_size: float,
        entry_price: float,
        entry_value: float,
        final_price: Optional[float],
        final_value: float,
        profit: float,
        profit_pct: float
    ):
        """
        Send notification when market ends

        Args:
            order: TPSLOrder object
            market_status: 'closed' or 'resolved'
            position_size: Number of tokens in position
            entry_price: Entry price per token
            entry_value: Total entry value
            final_price: Final price per token
            final_value: Total final value
            profit: Profit/loss amount
            profit_pct: Profit/loss percentage
        """
        try:
            market_question = order.market_data.get('question', 'Unknown Market')[:50] if order.market_data else 'Unknown'

            # Determine message tone
            if market_status == 'resolved':
                emoji = "🎉" if profit >= 0 else "😔"
                title = "MARKET RESOLVED"
                status_msg = "📊 Market has been resolved!"
                action_msg = "🎁 **Claim Payout:** Winnings will be automatically credited to your wallet"
            else:
                emoji = "⏸️"
                title = "MARKET CLOSED"
                status_msg = "⏸️ Market closed for trading"
                action_msg = "💡 **Action:** You can wait for resolution or contact support if needed"

            # Build message
            message = f"{emoji} **{title}**\n\n"
            message += f"📊 **Market:** {market_question}...\n"
            message += f"🎯 **Position:** {order.outcome.upper()}"

            if position_size > 0:
                message += f" ({position_size:.0f} tokens)\n\n"
            else:
                message += "\n\n"

            message += f"❌ **TP/SL Auto-Cancelled**\n"
            message += f"Your take profit/stop loss order was cancelled because the market is no longer trading.\n\n"

            if position_size > 0:
                message += f"💰 **Position Summary:**\n"
                message += f"💵 Entry Value: ${entry_value:.2f}\n"
                message += f"💵 Final Value: ${final_value:.2f}\n"

                if profit >= 0:
                    message += f"📈 **Profit:** +${profit:.2f} (+{profit_pct:.1f}%)\n"
                else:
                    message += f"📉 **Loss:** ${profit:.2f} ({profit_pct:.1f}%)\n"

                message += f"\n{action_msg}\n"

            message += "\nUse /positions to view your holdings"

            # Send notification (use send_message, not send_notification!)
            success = await notification_service.send_message(order.user_id, message)
            if success:
                logger.info(f"✅ Market ended notification sent to user {order.user_id} for order {order.id}")
            else:
                logger.warning(f"⚠️ Failed to send market ended notification to user {order.user_id}")

        except Exception as e:
            logger.error(f"❌ SEND MARKET ENDED NOTIFICATION ERROR: {e}")

    def get_status(self) -> dict:
        """Get current monitor status"""
        active_orders = self.tpsl_service.get_active_tpsl_orders()

        return {
            'is_running': self.is_running,
            'check_interval': self.check_interval,
            'active_orders_count': len(active_orders),
            'last_check': datetime.utcnow().isoformat()
        }


# Global instance (will be initialized in bot.py)
price_monitor: Optional[PriceMonitor] = None


def get_price_monitor() -> Optional[PriceMonitor]:
    """Get the global price monitor instance"""
    return price_monitor


def set_price_monitor(monitor: PriceMonitor):
    """Set the global price monitor instance"""
    global price_monitor
    price_monitor = monitor
