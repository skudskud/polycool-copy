#!/usr/bin/env python3
"""
TRANSACTION SERVICE
Enterprise-grade transaction logging and position calculation system
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from database import SessionLocal, Transaction, User

logger = logging.getLogger(__name__)

class TransactionService:
    """
    ENTERPRISE-GRADE TRANSACTION SERVICE

    Features:
    - Complete trade audit trail
    - Real-time position calculation from transactions
    - P&L calculation with cost basis tracking
    - Transaction history and analytics
    - Never gets out of sync (source of truth)
    """

    def __init__(self):
        logger.info("✅ Transaction Service initialized")

    def log_trade(self, user_id: int, transaction_type: str, market_id: str,
                  outcome: str, tokens: float, price_per_token: float,
                  token_id: str, order_id: str = None,
                  transaction_hash: str = None, market_data: Dict = None,
                  copy_trading_config: Dict = None) -> Optional[int]:
        """
        Log a completed trade transaction

        Args:
            user_id: Telegram user ID
            transaction_type: 'BUY' or 'SELL'
            market_id: Market identifier
            outcome: 'yes' or 'no'
            tokens: Number of tokens traded
            price_per_token: Price per token in USD
            token_id: ERC-1155 token ID
            order_id: Polymarket order ID
            transaction_hash: Blockchain transaction hash
            market_data: Market data snapshot
            copy_trading_config: Copy trading metadata (e.g., {'is_copy_trade': True})

        Returns:
            Transaction ID if logged successfully, None otherwise
        """
        try:
            with SessionLocal() as session:
                # Calculate total amount
                total_amount = tokens * price_per_token

                # Create transaction record
                transaction = Transaction(
                    user_id=user_id,
                    transaction_type=transaction_type.upper(),
                    market_id=market_id,
                    outcome=outcome.lower(),
                    tokens=tokens,
                    price_per_token=price_per_token,
                    total_amount=total_amount,
                    token_id=token_id,
                    order_id=order_id,
                    transaction_hash=transaction_hash,
                    market_data=market_data,
                    executed_at=datetime.utcnow()
                )

                session.add(transaction)
                session.commit()

                # Get the ID of the inserted transaction
                transaction_id = transaction.id

                logger.info(f"✅ TRANSACTION LOGGED: User {user_id} {transaction_type} {tokens} {outcome} tokens at ${price_per_token:.4f} (ID: {transaction_id})")

                # ✅ CRITICAL FIX: Extract user data BEFORE session closes
                user = session.query(User).filter(User.telegram_user_id == user_id).first()
                user_wallet_address = user.polygon_address if user else None

                # 🔥 NEW: Invalidate position cache + mark recent trade for dynamic TTL
                if user_wallet_address:
                    try:
                        from core.services.redis_price_cache import get_redis_cache
                        redis_cache = get_redis_cache()

                        # Invalidate cached positions
                        redis_cache.invalidate_user_positions(user_wallet_address)

                        # Mark recent trade for 20s TTL (instead of 180s)
                        redis_cache.mark_recent_trade(user_wallet_address)

                        logger.info(f"🔥 [CACHE] Invalidated + marked recent trade for {user_wallet_address[:10]}... ({transaction_type})")

                        # ✅ NEW: Add token to PriceUpdater hot list for immediate caching
                        try:
                            from core.services.price_updater_service import get_price_updater
                            price_updater = get_price_updater()
                            price_updater.add_hot_token(token_id, duration_minutes=60)
                            logger.debug(f"🔥 [HOT_TOKEN] Added {token_id[:10]}... to PriceUpdater (60min)")
                        except Exception as e:
                            logger.error(f"❌ [HOT_TOKEN] Failed to add token to PriceUpdater: {e}")
                    except Exception as e:
                        logger.error(f"❌ [CACHE] Cache invalidation failed (non-fatal): {e}")

                # ✅ NEW: Publish to Redis Pub/Sub for instant copy trading (<10s latency)
                # ⚠️ IMPORTANT: Only publish if this is a LEADER trade, not a follower copy trade
                # To prevent infinite loops where follower trades trigger more copies
                if user_wallet_address:
                    # Check if this is a copy trade (follower) or original trade (leader)
                    is_copy_trade = copy_trading_config and copy_trading_config.get('is_copy_trade', False)

                    if not is_copy_trade:
                        # Only publish leader trades, not follower copies
                        logger.info(f"📡 Publishing {transaction_type} trade to Redis for user {user_id} (wallet: {user_wallet_address[:10]}...)")
                        try:
                            import asyncio
                            import json
                            from config.config import REDIS_URL
                            import redis.asyncio as redis

                            # Publish in background (non-blocking)
                            async def publish_trade_notification():
                                try:
                                    logger.info(f"🔄 [REDIS_PUBLISH] Connecting to Redis for {transaction_type} trade...")
                                    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
                                    logger.debug("🔗 [REDIS_PUBLISH] Redis connection established")

                                    channel = f"copy_trade:{user_wallet_address.lower()}"
                                    message = json.dumps({
                                        'tx_id': str(transaction_id),
                                        'user_address': user_wallet_address,
                                        'market_id': market_id,
                                        'outcome': 1 if outcome.lower() == 'yes' else 0,
                                        'tx_type': transaction_type.upper(),
                                        'amount': float(tokens),
                                        'price': float(price_per_token),
                                        'tx_hash': transaction_hash,
                                        'timestamp': datetime.utcnow().isoformat(),
                                        'address_type': 'bot_user'
                                    })

                                    logger.info(f"📤 [REDIS_PUBLISH] Publishing {transaction_type} trade to channel: {channel}")
                                    result = await redis_client.publish(channel, message)
                                    logger.info(f"✅ [REDIS_PUBLISH] Published successfully to {channel}, subscribers: {result}")

                                    await redis_client.close()
                                    logger.debug("🔌 [REDIS_PUBLISH] Redis connection closed")

                                except Exception as e:
                                    logger.error(f"❌ [REDIS_PUBLISH] Redis publish failed: {e}", exc_info=True)

                            # Schedule async task
                            try:
                                import time
                                publish_start = time.time()
                                loop = asyncio.get_event_loop()
                                loop.create_task(publish_trade_notification())
                                logger.info(f"⏱️ Redis publish scheduled in {time.time() - publish_start:.3f}s")
                            except RuntimeError:
                                # No event loop running (shouldn't happen in async context)
                                logger.debug("⚠️ No event loop available for Redis publish")

                        except Exception as redis_error:
                            logger.warning(f"⚠️ Redis publish setup failed (non-critical): {redis_error}")
                    else:
                        # This is a follower copy trade, don't publish to avoid loops
                        logger.debug(f"⏭️ [REDIS_SKIP] Not publishing copy trade for follower {user_id} to avoid loops")

                # ✅ NEW: Update copy trading budget for BUY trades
                if transaction_type.upper() == 'BUY' and user_wallet_address:
                    try:
                        from core.services.copy_trading.repository import CopyTradingRepository
                        from core.services import balance_checker

                        # Use wallet address we already extracted
                        wallet_balance, _ = balance_checker.check_usdc_balance(user_wallet_address)

                        # Update copy trading budget (balance-based calculation)
                        copy_repo = CopyTradingRepository(session)
                        budget = copy_repo.sync_wallet_balance(user_id, wallet_balance)

                        logger.info(f"✅ COPY TRADING BUDGET UPDATED: User {user_id} - Balance: ${wallet_balance:.2f}, Budget: ${budget.budget_remaining:.2f}")

                    except Exception as budget_error:
                        logger.warning(f"⚠️ Failed to update copy trading budget: {budget_error}")
                        # Don't fail the transaction if budget update fails

                return transaction_id

        except Exception as e:
            logger.error(f"❌ TRANSACTION LOG ERROR: {e}")
            return None

    def calculate_current_positions(self, user_id: int) -> Dict[str, Dict]:
        """
        Calculate current positions from transaction history

        Args:
            user_id: Telegram user ID

        Returns:
            Dictionary of positions keyed by "market_id_outcome"
        """
        try:
            with SessionLocal() as session:
                # Get all transactions for user, ordered by execution time
                transactions = session.query(Transaction).filter(
                    Transaction.user_id == user_id
                ).order_by(Transaction.executed_at).all()

                if not transactions:
                    logger.info(f"📭 NO TRANSACTIONS: User {user_id} has no trade history")
                    return {}

                # Calculate positions by aggregating transactions
                positions = {}

                for tx in transactions:
                    position_key = f"{tx.market_id}_{tx.outcome}"

                    # Initialize position if doesn't exist
                    if position_key not in positions:
                        positions[position_key] = {
                            'market_id': tx.market_id,
                            'outcome': tx.outcome,
                            'tokens': 0.0,
                            'total_cost': 0.0,
                            'total_proceeds': 0.0,
                            'buy_transactions': [],
                            'sell_transactions': [],
                            'token_id': tx.token_id,
                            'market_data': tx.market_data or {},
                            'first_trade': tx.executed_at,
                            'last_trade': tx.executed_at
                        }

                    position = positions[position_key]

                    if tx.transaction_type == 'BUY':
                        position['tokens'] += tx.tokens
                        position['total_cost'] += tx.total_amount
                        position['buy_transactions'].append(tx.to_dict())
                    elif tx.transaction_type == 'SELL':
                        position['tokens'] -= tx.tokens
                        position['total_proceeds'] += tx.total_amount
                        position['sell_transactions'].append(tx.to_dict())

                    # Update timestamps
                    position['last_trade'] = tx.executed_at

                # Filter out zero positions and calculate metrics
                active_positions = {}
                for position_key, position in positions.items():
                    if position['tokens'] > 0.001:  # Small threshold for floating point errors
                        # Calculate average buy price
                        if position['total_cost'] > 0:
                            total_bought = sum(tx['tokens'] for tx in position['buy_transactions'])
                            position['buy_price'] = position['total_cost'] / total_bought if total_bought > 0 else 0
                        else:
                            position['buy_price'] = 0

                        # Convert to bot-expected format
                        bot_position = {
                            'tokens': position['tokens'],
                            'outcome': position['outcome'],
                            'buy_price': position['buy_price'],
                            'total_cost': position['total_cost'],
                            'token_id': position['token_id'],
                            'market': position['market_data'],
                            'market_id': position['market_id'],
                            'created_at': position['first_trade'].isoformat(),
                            'last_updated': position['last_trade'].isoformat(),
                            'source': 'transaction_log',
                            'transaction_count': len(position['buy_transactions']) + len(position['sell_transactions'])
                        }

                        active_positions[position_key] = bot_position

                logger.info(f"📊 CALCULATED POSITIONS: User {user_id} has {len(active_positions)} active positions from {len(transactions)} transactions")
                return active_positions

        except Exception as e:
            logger.error(f"❌ POSITION CALCULATION ERROR: {e}")
            return {}

    def get_user_transactions(self, user_id: int, limit: int = 100) -> List[Dict]:
        """
        Get transaction history for a user

        Args:
            user_id: Telegram user ID
            limit: Maximum number of transactions to return

        Returns:
            List of transaction dictionaries
        """
        try:
            with SessionLocal() as session:
                transactions = session.query(Transaction).filter(
                    Transaction.user_id == user_id
                ).order_by(desc(Transaction.executed_at)).limit(limit).all()

                return [tx.to_dict() for tx in transactions]

        except Exception as e:
            logger.error(f"❌ TRANSACTION HISTORY ERROR: {e}")
            return []

    def calculate_pnl(self, user_id: int, market_id: str = None, outcome: str = None) -> Dict:
        """
        Calculate P&L for user positions

        Args:
            user_id: Telegram user ID
            market_id: Optional - specific market
            outcome: Optional - specific outcome

        Returns:
            P&L summary dictionary
        """
        try:
            with SessionLocal() as session:
                query = session.query(Transaction).filter(Transaction.user_id == user_id)

                if market_id:
                    query = query.filter(Transaction.market_id == market_id)
                if outcome:
                    query = query.filter(Transaction.outcome == outcome.lower())

                transactions = query.order_by(Transaction.executed_at).all()

                if not transactions:
                    return {'realized_pnl': 0, 'unrealized_pnl': 0, 'total_pnl': 0}

                total_cost = sum(tx.total_amount for tx in transactions if tx.transaction_type == 'BUY')
                total_proceeds = sum(tx.total_amount for tx in transactions if tx.transaction_type == 'SELL')

                realized_pnl = total_proceeds - total_cost

                # For unrealized P&L, we'd need current market prices
                # This would require integration with market price service
                unrealized_pnl = 0  # Placeholder

                return {
                    'realized_pnl': realized_pnl,
                    'unrealized_pnl': unrealized_pnl,
                    'total_pnl': realized_pnl + unrealized_pnl,
                    'total_cost': total_cost,
                    'total_proceeds': total_proceeds,
                    'transaction_count': len(transactions)
                }

        except Exception as e:
            logger.error(f"❌ P&L CALCULATION ERROR: {e}")
            return {'realized_pnl': 0, 'unrealized_pnl': 0, 'total_pnl': 0}

    def get_position_history(self, user_id: int, market_id: str, outcome: str) -> Dict:
        """
        Get complete history for a specific position

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: Position outcome

        Returns:
            Position history with all transactions
        """
        try:
            with SessionLocal() as session:
                transactions = session.query(Transaction).filter(
                    Transaction.user_id == user_id,
                    Transaction.market_id == market_id,
                    Transaction.outcome == outcome.lower()
                ).order_by(Transaction.executed_at).all()

                if not transactions:
                    return {}

                buy_txs = [tx for tx in transactions if tx.transaction_type == 'BUY']
                sell_txs = [tx for tx in transactions if tx.transaction_type == 'SELL']

                total_bought = sum(tx.tokens for tx in buy_txs)
                total_sold = sum(tx.tokens for tx in sell_txs)
                current_tokens = total_bought - total_sold

                total_cost = sum(tx.total_amount for tx in buy_txs)
                total_proceeds = sum(tx.total_amount for tx in sell_txs)

                avg_buy_price = total_cost / total_bought if total_bought > 0 else 0
                avg_sell_price = total_proceeds / total_sold if total_sold > 0 else 0

                return {
                    'market_id': market_id,
                    'outcome': outcome,
                    'current_tokens': current_tokens,
                    'total_bought': total_bought,
                    'total_sold': total_sold,
                    'total_cost': total_cost,
                    'total_proceeds': total_proceeds,
                    'avg_buy_price': avg_buy_price,
                    'avg_sell_price': avg_sell_price,
                    'realized_pnl': total_proceeds - (total_cost * (total_sold / total_bought)) if total_bought > 0 else 0,
                    'buy_transactions': [tx.to_dict() for tx in buy_txs],
                    'sell_transactions': [tx.to_dict() for tx in sell_txs],
                    'first_trade': transactions[0].executed_at.isoformat(),
                    'last_trade': transactions[-1].executed_at.isoformat(),
                    'transaction_count': len(transactions)
                }

        except Exception as e:
            logger.error(f"❌ POSITION HISTORY ERROR: {e}")
            return {}

# Global instance
transaction_service = TransactionService()

def get_transaction_service():
    """Get the global transaction service"""
    return transaction_service
