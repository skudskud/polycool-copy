#!/usr/bin/env python3
"""
TP/SL Service
Manages Take Profit and Stop Loss orders for positions
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from database import SessionLocal, TPSLOrder, User, Market

logger = logging.getLogger(__name__)


class TPSLService:
    """
    Take Profit & Stop Loss Management Service

    Features:
    - Create/Update/Cancel TP/SL orders
    - Query active TP/SL orders
    - Mark orders as triggered
    - Sync with actual positions
    - Validate price targets
    """

    def __init__(self):
        logger.info("✅ TP/SL Service initialized")

    def create_tpsl_order(
        self,
        user_id: int,
        market_id: str,
        outcome: str,
        token_id: str,
        monitored_tokens: float,
        entry_price: float,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        market_data: Optional[Dict] = None,
        entry_transaction_id: Optional[int] = None
    ) -> Optional[TPSLOrder]:
        """
        Create a new TP/SL order

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: 'yes' or 'no'
            token_id: ERC-1155 token ID
            monitored_tokens: Number of tokens to monitor
            entry_price: Position entry price
            take_profit_price: Price to sell at for profit (optional)
            stop_loss_price: Price to sell at to cut losses (optional)
            market_data: Market data snapshot (optional)
            entry_transaction_id: ID of the BUY transaction that started this position (optional)

        Returns:
            Created TPSLOrder or None if failed
        """
        try:
            # Validation: At least one target must be set
            if take_profit_price is None and stop_loss_price is None:
                logger.error("❌ TP/SL ORDER CREATION FAILED: At least one target price required")
                return None

            # Validation: TP must be above entry, SL must be below entry
            if take_profit_price is not None and take_profit_price <= entry_price:
                logger.error(f"❌ TP/SL ORDER CREATION FAILED: Take profit (${take_profit_price}) must be above entry (${entry_price})")
                return None

            if stop_loss_price is not None and stop_loss_price >= entry_price:
                logger.error(f"❌ TP/SL ORDER CREATION FAILED: Stop loss (${stop_loss_price}) must be below entry (${entry_price})")
                return None

            with SessionLocal() as session:
                # Check if active TP/SL already exists for this SPECIFIC position (by token_id)
                existing = session.query(TPSLOrder).filter(
                    and_(
                        TPSLOrder.user_id == user_id,
                        TPSLOrder.token_id == token_id,
                        TPSLOrder.status == 'active'
                    )
                ).first()

                if existing:
                    logger.warning(f"⚠️ TP/SL already exists for user {user_id} - token {token_id}, updating instead")
                    # Update existing order
                    return self.update_tpsl_order(
                        existing.id,
                        take_profit_price=take_profit_price,
                        stop_loss_price=stop_loss_price,
                        monitored_tokens=monitored_tokens
                    )

                # Create new TP/SL order
                tpsl_order = TPSLOrder(
                    user_id=user_id,
                    market_id=market_id,
                    outcome=outcome.lower(),
                    token_id=token_id,
                    take_profit_price=Decimal(str(take_profit_price)) if take_profit_price else None,
                    stop_loss_price=Decimal(str(stop_loss_price)) if stop_loss_price else None,
                    monitored_tokens=Decimal(str(monitored_tokens)),
                    entry_price=Decimal(str(entry_price)),
                    status='active',
                    market_data=market_data,
                    entry_transaction_id=entry_transaction_id,
                    created_at=datetime.utcnow()
                )

                session.add(tpsl_order)
                session.commit()
                session.refresh(tpsl_order)

                # PHASE 2: Invalidate position cache after TP/SL creation
                try:
                    from core.services import user_service
                    from core.services.redis_price_cache import get_redis_cache

                    wallet = user_service.get_user_wallet(user_id)
                    if wallet:
                        redis_cache = get_redis_cache()
                        redis_cache.invalidate_user_positions(wallet['address'])
                        logger.info(f"🗑️ [PHASE 2] Cache invalidated for user {user_id} after TP/SL creation")
                except Exception as cache_error:
                    logger.warning(f"⚠️ Failed to invalidate cache after TP/SL creation: {cache_error}")

                tp_str = f"TP: ${take_profit_price:.4f}" if take_profit_price else "No TP"
                sl_str = f"SL: ${stop_loss_price:.4f}" if stop_loss_price else "No SL"
                tx_str = f"Transaction #{entry_transaction_id}" if entry_transaction_id else "No transaction link"
                logger.info(f"✅ TP/SL ORDER CREATED: User {user_id} - {market_id} {outcome} ({tp_str}, {sl_str}, {tx_str})")

                return tpsl_order

        except Exception as e:
            logger.error(f"❌ TP/SL ORDER CREATION ERROR: {e}")
            return None

    def update_tpsl_order(
        self,
        tpsl_id: int,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        monitored_tokens: Optional[float] = None
    ) -> Optional[TPSLOrder]:
        """
        Update an existing TP/SL order

        Args:
            tpsl_id: TP/SL order ID
            take_profit_price: New take profit price (optional)
            stop_loss_price: New stop loss price (optional)
            monitored_tokens: New monitored tokens amount (optional)

        Returns:
            Updated TPSLOrder or None if failed
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return None

                if tpsl.status != 'active':
                    logger.error(f"❌ TP/SL ORDER UPDATE FAILED: Order {tpsl_id} is {tpsl.status}")
                    return None

                # Update prices if provided
                if take_profit_price is not None:
                    if take_profit_price <= float(tpsl.entry_price):
                        logger.error(f"❌ Invalid take profit: ${take_profit_price} must be above entry ${tpsl.entry_price}")
                        return None
                    tpsl.take_profit_price = Decimal(str(take_profit_price))

                if stop_loss_price is not None:
                    if stop_loss_price >= float(tpsl.entry_price):
                        logger.error(f"❌ Invalid stop loss: ${stop_loss_price} must be below entry ${tpsl.entry_price}")
                        return None
                    tpsl.stop_loss_price = Decimal(str(stop_loss_price))

                if monitored_tokens is not None:
                    tpsl.monitored_tokens = Decimal(str(monitored_tokens))

                # Validation: At least one target must be set
                if tpsl.take_profit_price is None and tpsl.stop_loss_price is None:
                    logger.error("❌ TP/SL ORDER UPDATE FAILED: At least one target price required")
                    return None

                session.commit()
                session.refresh(tpsl)

                # PHASE 2: Invalidate position cache after TP/SL update
                try:
                    from core.services import user_service
                    from core.services.redis_price_cache import get_redis_cache

                    wallet = user_service.get_user_wallet(tpsl.user_id)
                    if wallet:
                        redis_cache = get_redis_cache()
                        redis_cache.invalidate_user_positions(wallet['address'])
                        logger.info(f"🗑️ [PHASE 2] Cache invalidated for user {tpsl.user_id} after TP/SL update")
                except Exception as cache_error:
                    logger.warning(f"⚠️ Failed to invalidate cache after TP/SL update: {cache_error}")

                logger.info(f"✅ TP/SL ORDER UPDATED: ID {tpsl_id}")
                return tpsl

        except Exception as e:
            logger.error(f"❌ TP/SL ORDER UPDATE ERROR: {e}")
            return None

    def cancel_tpsl_order(self, tpsl_id: int, reason: str = "user_cancelled") -> bool:
        """
        Cancel a TP/SL order

        Args:
            tpsl_id: TP/SL order ID
            reason: Cancellation reason (user_cancelled, market_closed, etc.)

        Returns:
            True if cancelled successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER ALREADY {tpsl.status}: ID {tpsl_id}")
                    return False

                tpsl.status = 'cancelled'
                tpsl.cancelled_reason = reason
                tpsl.cancelled_at = datetime.utcnow()

                session.commit()

                # PHASE 2: Invalidate position cache after TP/SL cancellation
                try:
                    from core.services import user_service
                    from core.services.redis_price_cache import get_redis_cache

                    wallet = user_service.get_user_wallet(tpsl.user_id)
                    if wallet:
                        redis_cache = get_redis_cache()
                        redis_cache.invalidate_user_positions(wallet['address'])
                        logger.info(f"🗑️ [PHASE 2] Cache invalidated for user {tpsl.user_id} after TP/SL cancellation")
                except Exception as cache_error:
                    logger.warning(f"⚠️ Failed to invalidate cache after TP/SL cancellation: {cache_error}")

                logger.info(f"✅ TP/SL ORDER CANCELLED: ID {tpsl_id} - Reason: {reason}")
                return True

        except Exception as e:
            logger.error(f"❌ TP/SL ORDER CANCELLATION ERROR: {e}")
            return False

    def cancel_tpsl_for_position(self, user_id: int, market_id: str, outcome: str) -> bool:
        """
        Cancel TP/SL order for a specific position

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: Position outcome

        Returns:
            True if cancelled successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(
                    and_(
                        TPSLOrder.user_id == user_id,
                        TPSLOrder.market_id == market_id,
                        TPSLOrder.outcome == outcome.lower(),
                        TPSLOrder.status == 'active'
                    )
                ).first()

                if not tpsl:
                    logger.info(f"📭 NO ACTIVE TP/SL for user {user_id} - {market_id} {outcome}")
                    return False

                return self.cancel_tpsl_order(tpsl.id, reason="position_closed")

        except Exception as e:
            logger.error(f"❌ CANCEL TP/SL FOR POSITION ERROR: {e}")
            return False

    def get_active_tpsl_orders(self, user_id: Optional[int] = None, market_id: Optional[str] = None) -> List[TPSLOrder]:
        """
        Get all active TP/SL orders

        Args:
            user_id: Optional - filter by user
            market_id: Optional - filter by market

        Returns:
            List of active TPSLOrder objects

        OPT 4: Removed 2x COUNT() queries (50-100ms latency reduction per call)
        """
        try:
            with SessionLocal() as session:
                # OPT 4: REMOVED total_count and active_count queries
                # These were only for logging and added 50-100ms per /positions call

                query = session.query(TPSLOrder).filter(TPSLOrder.status == 'active')

                if user_id:
                    query = query.filter(TPSLOrder.user_id == user_id)

                if market_id:
                    query = query.filter(TPSLOrder.market_id == market_id)

                orders = query.order_by(TPSLOrder.created_at.desc()).all()
                logger.debug(f"🔍 Found {len(orders)} active TP/SL orders (user_id={user_id}, market_id={market_id})")

                # Detach from session to avoid lazy loading issues
                result = [session.merge(order, load=False) for order in orders]
                session.expunge_all()

                return result

        except Exception as e:
            logger.error(f"❌ GET ACTIVE TP/SL ORDERS ERROR: {e}")
            return []

    def get_tpsl_for_position(self, user_id: int, market_id: str, outcome: str) -> Optional[TPSLOrder]:
        """
        Get TP/SL order for a specific position

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: Position outcome

        Returns:
            TPSLOrder or None if not found
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(
                    and_(
                        TPSLOrder.user_id == user_id,
                        TPSLOrder.market_id == market_id,
                        TPSLOrder.outcome == outcome.lower(),
                        TPSLOrder.status == 'active'
                    )
                ).first()

                if tpsl:
                    # Detach from session
                    result = session.merge(tpsl, load=False)
                    session.expunge(result)
                    return result

                return None

        except Exception as e:
            logger.error(f"❌ GET TP/SL FOR POSITION ERROR: {e}")
            return None

    def get_tpsl_by_id(self, tpsl_id: int) -> Optional[TPSLOrder]:
        """
        Get TP/SL order by ID

        Args:
            tpsl_id: TP/SL order ID

        Returns:
            TPSLOrder or None if not found
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if tpsl:
                    # Detach from session
                    result = session.merge(tpsl, load=False)
                    session.expunge(result)
                    return result

                return None

        except Exception as e:
            logger.error(f"❌ GET TP/SL BY ID ERROR: {e}")
            return None

    def get_active_tpsl_by_token(self, user_id: int, token_id: str) -> Optional[TPSLOrder]:
        """
        Get active TP/SL order by token ID

        Args:
            user_id: Telegram user ID
            token_id: Token identifier

        Returns:
            TPSLOrder or None if not found
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(
                    and_(
                        TPSLOrder.user_id == user_id,
                        TPSLOrder.token_id == token_id,
                        TPSLOrder.status == 'active'
                    )
                ).first()

                if tpsl:
                    # Detach from session
                    result = session.merge(tpsl, load=False)
                    session.expunge(result)
                    return result

                return None

        except Exception as e:
            logger.error(f"❌ GET ACTIVE TP/SL BY TOKEN ERROR: {e}")
            return None

    def mark_as_triggered(
        self,
        tpsl_id: int,
        trigger_type: str,  # 'take_profit' or 'stop_loss'
        execution_price: float
    ) -> bool:
        """
        Mark TP/SL order as triggered

        Args:
            tpsl_id: TP/SL order ID
            trigger_type: 'take_profit' or 'stop_loss'
            execution_price: Price at which it was triggered

        Returns:
            True if marked successfully
        """
        try:
            if trigger_type not in ['take_profit', 'stop_loss']:
                logger.error(f"❌ Invalid trigger type: {trigger_type}")
                return False

            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER ALREADY {tpsl.status}: ID {tpsl_id}")
                    return False

                tpsl.status = 'triggered'
                tpsl.triggered_type = trigger_type
                tpsl.execution_price = Decimal(str(execution_price))
                tpsl.triggered_at = datetime.utcnow()

                session.commit()

                logger.info(f"✅ TP/SL ORDER TRIGGERED: ID {tpsl_id} - Type: {trigger_type} @ ${execution_price:.4f}")
                return True

        except Exception as e:
            logger.error(f"❌ MARK TP/SL AS TRIGGERED ERROR: {e}")
            return False

    def update_last_price_check(self, tpsl_id: int) -> bool:
        """
        Update last price check timestamp for monitoring

        Args:
            tpsl_id: TP/SL order ID

        Returns:
            True if updated successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if tpsl and tpsl.status == 'active':
                    tpsl.last_price_check = datetime.utcnow()
                    session.commit()
                    return True

                return False

        except Exception as e:
            logger.error(f"❌ UPDATE LAST PRICE CHECK ERROR: {e}")
            return False

    def cancel_tp_only(self, tpsl_id: int) -> bool:
        """
        Cancel Take Profit only, keep Stop Loss active

        Args:
            tpsl_id: TP/SL order ID

        Returns:
            True if cancelled successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER NOT ACTIVE: ID {tpsl_id} (status: {tpsl.status})")
                    return False

                # Set TP to NULL
                tpsl.take_profit_price = None

                # Check if SL also NULL - if so, cancel entire order
                if tpsl.stop_loss_price is None:
                    tpsl.status = 'cancelled'
                    tpsl.cancelled_reason = 'both_null'
                    tpsl.cancelled_at = datetime.utcnow()
                    logger.info(f"✅ TP/SL ORDER CANCELLED (both targets NULL): ID {tpsl_id}")
                else:
                    logger.info(f"✅ TP CANCELLED (SL remains active): ID {tpsl_id}")

                session.commit()
                return True

        except Exception as e:
            logger.error(f"❌ CANCEL TP ONLY ERROR: {e}")
            return False

    def cancel_sl_only(self, tpsl_id: int) -> bool:
        """
        Cancel Stop Loss only, keep Take Profit active

        Args:
            tpsl_id: TP/SL order ID

        Returns:
            True if cancelled successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER NOT ACTIVE: ID {tpsl_id} (status: {tpsl.status})")
                    return False

                # Set SL to NULL
                tpsl.stop_loss_price = None

                # Check if TP also NULL - if so, cancel entire order
                if tpsl.take_profit_price is None:
                    tpsl.status = 'cancelled'
                    tpsl.cancelled_reason = 'both_null'
                    tpsl.cancelled_at = datetime.utcnow()
                    logger.info(f"✅ TP/SL ORDER CANCELLED (both targets NULL): ID {tpsl_id}")
                else:
                    logger.info(f"✅ SL CANCELLED (TP remains active): ID {tpsl_id}")

                session.commit()
                return True

        except Exception as e:
            logger.error(f"❌ CANCEL SL ONLY ERROR: {e}")
            return False

    def update_tp_price(self, tpsl_id: int, new_tp_price: float) -> bool:
        """
        Update Take Profit price without recreating order

        Args:
            tpsl_id: TP/SL order ID
            new_tp_price: New take profit price

        Returns:
            True if updated successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER NOT ACTIVE: ID {tpsl_id}")
                    return False

                entry_price = float(tpsl.entry_price)

                # Validate new TP
                if new_tp_price <= entry_price:
                    logger.error(f"❌ Invalid TP: ${new_tp_price:.4f} must be > entry ${entry_price:.4f}")
                    return False

                if new_tp_price > entry_price * 10:
                    logger.error(f"❌ TP too high: ${new_tp_price:.4f} (max 10x entry)")
                    return False

                old_tp = float(tpsl.take_profit_price) if tpsl.take_profit_price else None
                tpsl.take_profit_price = Decimal(str(new_tp_price))

                session.commit()
                logger.info(f"✅ TP UPDATED: ID {tpsl_id} - ${old_tp or 0:.4f} → ${new_tp_price:.4f}")
                return True

        except Exception as e:
            logger.error(f"❌ UPDATE TP PRICE ERROR: {e}")
            return False

    def update_sl_price(self, tpsl_id: int, new_sl_price: float) -> bool:
        """
        Update Stop Loss price without recreating order

        Args:
            tpsl_id: TP/SL order ID
            new_sl_price: New stop loss price

        Returns:
            True if updated successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER NOT ACTIVE: ID {tpsl_id}")
                    return False

                entry_price = float(tpsl.entry_price)

                # Validate new SL
                if new_sl_price >= entry_price:
                    logger.error(f"❌ Invalid SL: ${new_sl_price:.4f} must be < entry ${entry_price:.4f}")
                    return False

                if new_sl_price < 0.001:
                    logger.error(f"❌ SL too low: ${new_sl_price:.4f} (minimum $0.001)")
                    return False

                old_sl = float(tpsl.stop_loss_price) if tpsl.stop_loss_price else None
                tpsl.stop_loss_price = Decimal(str(new_sl_price))

                session.commit()
                logger.info(f"✅ SL UPDATED: ID {tpsl_id} - ${old_sl or 0:.4f} → ${new_sl_price:.4f}")
                return True

        except Exception as e:
            logger.error(f"❌ UPDATE SL PRICE ERROR: {e}")
            return False

    def add_tp_to_existing_order(self, tpsl_id: int, tp_price: float) -> bool:
        """
        Add Take Profit to an order that only has Stop Loss

        Args:
            tpsl_id: TP/SL order ID
            tp_price: Take profit price

        Returns:
            True if added successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER NOT ACTIVE: ID {tpsl_id}")
                    return False

                if tpsl.take_profit_price is not None:
                    logger.warning(f"⚠️ TP already set: ID {tpsl_id}")
                    return False

                entry_price = float(tpsl.entry_price)

                # Validate TP
                if tp_price <= entry_price:
                    logger.error(f"❌ Invalid TP: ${tp_price:.4f} must be > entry ${entry_price:.4f}")
                    return False

                tpsl.take_profit_price = Decimal(str(tp_price))
                tpsl.status = 'active'  # Ensure it's active

                session.commit()
                logger.info(f"✅ TP ADDED: ID {tpsl_id} - ${tp_price:.4f}")
                return True

        except Exception as e:
            logger.error(f"❌ ADD TP ERROR: {e}")
            return False

    def add_sl_to_existing_order(self, tpsl_id: int, sl_price: float) -> bool:
        """
        Add Stop Loss to an order that only has Take Profit

        Args:
            tpsl_id: TP/SL order ID
            sl_price: Stop loss price

        Returns:
            True if added successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                if tpsl.status != 'active':
                    logger.warning(f"⚠️ TP/SL ORDER NOT ACTIVE: ID {tpsl_id}")
                    return False

                if tpsl.stop_loss_price is not None:
                    logger.warning(f"⚠️ SL already set: ID {tpsl_id}")
                    return False

                entry_price = float(tpsl.entry_price)

                # Validate SL
                if sl_price >= entry_price:
                    logger.error(f"❌ Invalid SL: ${sl_price:.4f} must be < entry ${entry_price:.4f}")
                    return False

                tpsl.stop_loss_price = Decimal(str(sl_price))
                tpsl.status = 'active'  # Ensure it's active

                session.commit()
                logger.info(f"✅ SL ADDED: ID {tpsl_id} - ${sl_price:.4f}")
                return True

        except Exception as e:
            logger.error(f"❌ ADD SL ERROR: {e}")
            return False

    def update_monitored_tokens(self, tpsl_id: int, new_amount: float) -> bool:
        """
        Update the number of monitored tokens (after partial sell)

        Args:
            tpsl_id: TP/SL order ID
            new_amount: New token amount

        Returns:
            True if updated successfully
        """
        try:
            with SessionLocal() as session:
                tpsl = session.query(TPSLOrder).filter(TPSLOrder.id == tpsl_id).first()

                if not tpsl:
                    logger.error(f"❌ TP/SL ORDER NOT FOUND: ID {tpsl_id}")
                    return False

                old_amount = float(tpsl.monitored_tokens)
                tpsl.monitored_tokens = Decimal(str(new_amount))

                session.commit()
                logger.info(f"✅ MONITORED TOKENS UPDATED: ID {tpsl_id} - {old_amount:.2f} → {new_amount:.2f}")
                return True

        except Exception as e:
            logger.error(f"❌ UPDATE MONITORED TOKENS ERROR: {e}")
            return False

    def get_tpsl_history(self, user_id: int, days: int = 30) -> List[TPSLOrder]:
        """
        Get cancelled/triggered TP/SL orders from last N days

        Args:
            user_id: Telegram user ID
            days: Number of days to look back (default: 30)

        Returns:
            List of TPSLOrder objects (triggered and cancelled only)
        """
        try:
            from datetime import timedelta
            from sqlalchemy import desc, func

            cutoff_date = datetime.utcnow() - timedelta(days=days)

            with SessionLocal() as session:
                orders = session.query(TPSLOrder).filter(
                    TPSLOrder.user_id == user_id,
                    TPSLOrder.status.in_(['triggered', 'cancelled']),
                    or_(
                        TPSLOrder.triggered_at >= cutoff_date,
                        TPSLOrder.cancelled_at >= cutoff_date
                    )
                ).order_by(
                    desc(func.coalesce(TPSLOrder.triggered_at, TPSLOrder.cancelled_at))
                ).all()

                logger.info(f"📜 Retrieved {len(orders)} history entries for user {user_id}")
                return orders

        except Exception as e:
            logger.error(f"❌ GET TP/SL HISTORY ERROR: {e}")
            return []

    def validate_price_targets(self, entry_price: float, tp_price: Optional[float], sl_price: Optional[float]) -> Tuple[bool, str]:
        """
        Validate TP/SL price targets

        Args:
            entry_price: Position entry price
            tp_price: Take profit price (optional)
            sl_price: Stop loss price (optional)

        Returns:
            (is_valid, error_message)
        """
        # At least one must be set
        if tp_price is None and sl_price is None:
            return False, "At least one target price (TP or SL) must be set"

        # Take profit must be above entry
        if tp_price is not None:
            if tp_price <= entry_price:
                return False, f"Take profit (${tp_price:.4f}) must be above entry price (${entry_price:.4f})"

            # Reasonable maximum (3x entry)
            if tp_price > entry_price * 3:
                return False, f"Take profit (${tp_price:.4f}) is unreasonably high (>300% gain)"

        # Stop loss must be below entry
        if sl_price is not None:
            if sl_price >= entry_price:
                return False, f"Stop loss (${sl_price:.4f}) must be below entry price (${entry_price:.4f})"

            # Reasonable minimum (at least $0.001)
            if sl_price < 0.001:
                return False, f"Stop loss (${sl_price:.4f}) is too low (minimum $0.001)"

        return True, "Valid"

    def get_latest_buy_transaction(self, user_id: int, token_id: str) -> Optional[int]:
        """
        Get the most recent BUY transaction ID for a given token

        Args:
            user_id: Telegram user ID
            token_id: ERC-1155 token ID

        Returns:
            Transaction ID or None if not found
        """
        try:
            from database import SessionLocal, Transaction

            with SessionLocal() as session:
                transaction = session.query(Transaction).filter(
                    Transaction.user_id == user_id,
                    Transaction.token_id == token_id,
                    Transaction.transaction_type == 'BUY'
                ).order_by(
                    Transaction.executed_at.desc()
                ).first()

                if transaction:
                    logger.info(f"✅ Found latest BUY transaction: #{transaction.id} for token {token_id[:20]}...")
                    return transaction.id

                logger.warning(f"⚠️ No BUY transaction found for user {user_id}, token {token_id[:20]}...")
                return None

        except Exception as e:
            logger.error(f"❌ GET LATEST BUY TRANSACTION ERROR: {e}")
            return None


# Global instance
tpsl_service = TPSLService()


def get_tpsl_service():
    """Get the global TP/SL service"""
    return tpsl_service
