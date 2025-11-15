"""
Trade Service - Trading operations with fill-or-kill execution
Handles buy/sell orders using user's wallet with CLOB API
"""
import asyncio
import os
from typing import Dict, Optional, Any
from datetime import datetime

from core.services.clob.clob_service import CLOBService
from core.services.user.user_service import user_service
from core.services.user.user_helper import get_user_data
from core.services.position.position_service import position_service
from core.services.position.outcome_helper import find_outcome_index
# from core.services.websocket_manager.websocket_manager import websocket_manager  # TODO: Implement later
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"


class TradeService:
    """
    Trade Service - Execute trades with fill-or-kill best price
    Uses user's wallet and CLOB API for instant execution
    """

    def __init__(self):
        self.clob_service = CLOBService()
        logger.info("TradeService initialized")

    def _is_test_mode(self) -> bool:
        """Check if we're in test mode (environment variable or dry run flag)"""
        import os
        return os.getenv('TEST_MODE', '').lower() in ('true', '1', 'yes') or \
               os.getenv('PYTEST_CURRENT_TEST') is not None

    async def execute_market_order(
        self,
        user_id: int,
        market_id: str,
        outcome: str,
        amount_usd: float,
        order_type: str = 'FOK',
        dry_run: bool = False,
        is_copy_trade: bool = False,
        token_id: Optional[str] = None,
        side: str = 'BUY',
        tokens_to_sell: Optional[float] = None  # For SELL: pass tokens directly to avoid conversion errors
    ) -> Dict[str, Any]:
        """
        Execute market order with fill-or-kill best price

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: 'YES' or 'NO'
            amount_usd: USD amount to spend
            order_type: 'FOK' (Fill-or-Kill) or 'IOC' (Immediate-or-Cancel)

        Returns:
            Dict with execution results
        """
        try:
            logger.info(
                f"🎯 [TRADE] Executing {order_type} order: user={user_id}, market={market_id}, "
                f"outcome={outcome}, amount=${amount_usd:.2f}, dry_run={dry_run}, "
                f"is_copy_trade={is_copy_trade}"
            )

            # DRY RUN MODE: Simulate successful trade without API calls
            # Automatically enabled in test mode or when dry_run=True
            is_dry_run = dry_run or self._is_test_mode()

            if is_dry_run:
                logger.info(f"🏃 DRY RUN: Simulating trade execution for user {user_id}")
                # Simulate realistic trade execution
                mock_price = 0.55  # Mock price per share (Polymarket format 0-1)
                # Calculate shares: USD spent / price = shares received
                # Apply 95% fill rate to simulate partial fill (realistic market behavior)
                fill_rate = 0.95
                shares_received = (amount_usd / mock_price) * fill_rate
                usd_actually_spent = amount_usd  # Full amount spent (fill rate affects shares, not USD)

                return {
                    'status': 'executed',
                    'trade': {
                        'success': True,
                        'order_id': f'dry_run_{user_id}_{market_id}_{outcome}',
                        'tokens': shares_received,  # Shares received (with 95% fill rate)
                        'price': mock_price,  # Mock price per share
                        'total_cost': shares_received,  # Shares received (total_cost stores shares)
                        'usd_spent': usd_actually_spent,  # USD spent
                        'tx_hash': f'dry_run_tx_{user_id}',
                        'dry_run': True
                    },
                    'market_title': f'Market {market_id} (DRY RUN)'
                }

            # Get user data (via API or DB)
            user_data = await get_user_data(user_id)
            if not user_data:
                return {
                    'status': 'failed',
                    'error': 'User not found'
                }

            # Get user object for backward compatibility (needed for _check_wallet_ready and _execute_trade)
            user = None
            if SKIP_DB:
                # Create a mock user object from user_data dict
                class MockUser:
                    def __init__(self, data):
                        self.id = data.get('id')
                        self.telegram_user_id = data.get('telegram_user_id')
                        self.polygon_address = data.get('polygon_address')
                        self.solana_address = data.get('solana_address')
                        self.polygon_private_key = data.get('polygon_private_key')  # Encrypted, but we'll check via API
                        self.solana_private_key = data.get('solana_private_key')
                user = MockUser(user_data)
            else:
                user = await user_service.get_by_telegram_id(user_id)
                if not user:
                    return {
                        'status': 'failed',
                        'error': 'User not found'
                    }

            # Check wallet ready
            wallet_ready, status_msg = await self._check_wallet_ready(user)
            if not wallet_ready:
                return {
                    'status': 'failed',
                    'error': f'Wallet not ready: {status_msg}'
                }

            # Check balance
            balance_check = await self._check_balance(user.polygon_address, amount_usd)
            if not balance_check['sufficient']:
                return {
                    'status': 'failed',
                    'error': f'Insufficient balance: {balance_check["message"]}'
                }

            # Get market data
            market_data = await self._get_market_data(market_id)
            if not market_data:
                return {
                    'status': 'failed',
                    'error': 'Market not found or inactive'
                }

            # Execute trade
            logger.info(
                f"⚡ [TRADE] Calling _execute_trade for user {user_id}: "
                f"market={market_id}, outcome={outcome}, amount=${amount_usd:.2f}, "
                f"side={side}, is_copy_trade={is_copy_trade}"
            )

            trade_result = await self._execute_trade(
                user=user,
                market_data=market_data,
                outcome=outcome,
                amount_usd=amount_usd,
                order_type=order_type,
                is_copy_trade=is_copy_trade,
                token_id=token_id,  # Pass token_id if provided (from position_id resolution)
                side=side,  # Pass side ('BUY' or 'SELL')
                tokens_to_sell=tokens_to_sell  # Pass tokens_to_sell for SELL orders
            )

            logger.info(
                f"📈 [TRADE] _execute_trade result for user {user_id}: "
                f"success={trade_result.get('success')}, "
                f"error={trade_result.get('error')}, "
                f"order_id={trade_result.get('order_id')}"
            )

            if trade_result['success']:
                # Calculate and record trade fee + commissions (for referral system)
                try:
                    internal_user_id = user_data.get('id')
                    if internal_user_id:
                        from core.services.referral.commission_service import get_commission_service
                        commission_service = get_commission_service()

                        # Get trade amount (USD spent for BUY, or USD received for SELL)
                        trade_amount = trade_result.get('usd_spent') or trade_result.get('usd_received') or amount_usd
                        trade_type = 'BUY'  # Default to BUY (we can detect SELL later if needed)

                        # Calculate fee and commissions
                        trade_fee = await commission_service.calculate_and_record_fee(
                            user_id=internal_user_id,
                            trade_amount=trade_amount,
                            trade_type=trade_type,
                            market_id=market_id,
                            trade_id=None  # We don't have a trade_id yet (could add later)
                        )

                        if trade_fee:
                            logger.info(f"💰 Fee calculated: ${trade_fee.final_fee_after_discount:.2f} for user {internal_user_id}")
                        else:
                            logger.debug(f"No fee calculated (fees disabled or error) for user {internal_user_id}")
                except Exception as e:
                    logger.error(f"❌ Error calculating fee/commission: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    # Don't fail the trade if fee calculation fails

                # Subscribe to WebSocket for real-time updates after trade
                try:
                    logger.info(f"🔌 Attempting to subscribe to WebSocket for market {market_id} after trade")
                    if SKIP_DB:
                        # Use API endpoint for subscription
                        from core.services.api_client import get_api_client
                        api_client = get_api_client()
                        result_data = await api_client.subscribe_websocket(user_id, market_id)
                        if result_data and result_data.get('success'):
                            logger.info(f"✅ WebSocket subscription via API for market {market_id}: success")
                        else:
                            logger.warning(f"⚠️ WebSocket subscription via API failed: {result_data}")
                    else:
                        # Direct call to websocket_manager when DB access available
                        from core.services.websocket_manager import websocket_manager
                        logger.debug(f"WebSocket manager imported successfully")
                        result = await websocket_manager.on_trade_executed(user_id, market_id)
                        logger.info(f"✅ WebSocket subscription result for market {market_id}: {result}")
                except Exception as e:
                    logger.error(f"❌ Failed to subscribe to WebSocket after trade: {e}")
                    import traceback
                    logger.debug(f"Traceback: {traceback.format_exc()}")

                # TODO: Update positions cache - commented out to avoid cache error
                # await self._update_positions_cache(user_id)

                logger.info(
                    f"✅ [TRADE] Trade executed successfully for user {user_id}: "
                    f"order_id={trade_result.get('order_id')}, "
                    f"tokens={trade_result.get('tokens')}, "
                    f"usd_spent={trade_result.get('usd_spent')}, "
                    f"is_copy_trade={is_copy_trade}"
                )
                return {
                    'status': 'executed',
                    'trade': trade_result,
                    'market_title': market_data.get('title', 'Unknown Market')
                }
            else:
                logger.error(
                    f"❌ [TRADE] Trade failed for user {user_id}: "
                    f"error={trade_result.get('error')}, "
                    f"is_copy_trade={is_copy_trade}"
                )
                return {
                    'status': 'failed',
                    'error': trade_result.get('error', 'Unknown error')
                }

        except Exception as e:
            logger.error(f"Trade execution error for user {user_id}: {e}")
            return {
                'status': 'failed',
                'error': f'Execution error: {str(e)}'
            }

    async def _check_wallet_ready(self, user) -> tuple[bool, str]:
        """Check if user's wallet is ready for trading"""
        try:
            logger.info(f"🔍 Checking wallet for user {user.telegram_user_id}")

            # Check if user has required credentials
            if not user.polygon_address:
                logger.warning(f"❌ No polygon address for user {user.telegram_user_id}")
                return False, "Polygon wallet not set up"

            # Don't check private key here - let CLOB service handle it when creating client
            # This avoids unnecessary API calls and allows CLOB service to handle errors gracefully
            logger.info(f"✅ User {user.telegram_user_id} has polygon address: {user.polygon_address}")

            # Check if user has API credentials (optional but recommended)
            api_creds = await self.clob_service.get_api_credentials(user.telegram_user_id)
            if not api_creds:
                logger.warning(f"User {user.telegram_user_id} has no API credentials - using slower execution")

            return True, "Ready"

        except Exception as e:
            logger.error(f"Wallet check error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False, f"Wallet check failed: {str(e)}"

    async def _check_balance(self, polygon_address: str, required_amount: float) -> Dict[str, Any]:
        """Check if user has sufficient balance"""
        try:
            # Get USDC balance
            balance_info = await self.clob_service.get_balance_by_address(polygon_address)

            if not balance_info or 'balance' not in balance_info:
                return {
                    'sufficient': False,
                    'message': 'Unable to check balance'
                }

            current_balance = float(balance_info['balance'])

            if current_balance < required_amount:
                return {
                    'sufficient': False,
                    'message': f'Required: ${required_amount:.2f}, Available: ${current_balance:.2f}'
                }

            return {
                'sufficient': True,
                'balance': current_balance
            }

        except Exception as e:
            logger.error(f"Balance check error: {e}")
            return {
                'sufficient': False,
                'message': f'Balance check failed: {str(e)}'
            }

    async def _get_market_data(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get market data for trading"""
        try:
            # Use market helper (context=None for services)
            from core.services.market.market_helper import get_market_data
            market = await get_market_data(market_id, context=None)

            if not market:
                logger.warning(f"Market {market_id} not found")
                return None

            # Check if market is active (handle both 'active' and 'is_active' fields)
            is_active = market.get('active', market.get('is_active', True))
            if not is_active:
                logger.warning(f"Market {market_id} is not active")
                return None

            return market

        except Exception as e:
            logger.error(f"Market data fetch error: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return None

    async def _execute_trade(
        self,
        user,
        market_data: Dict[str, Any],
        outcome: str,
        amount_usd: float,
        order_type: str,
        is_copy_trade: bool = False,
        token_id: Optional[str] = None,
        side: str = 'BUY',
        tokens_to_sell: Optional[float] = None  # For SELL: pass tokens directly to avoid conversion errors
    ) -> Dict[str, Any]:
        """Execute the actual trade using CLOB API"""
        try:
            # Create ClobClient for user
            client = await self.clob_service.create_user_client(user.telegram_user_id)

            if not client:
                # Check if user has polygon address but no private key
                if user.polygon_address:
                    logger.error(f"❌ Cannot create trading client for user {user.telegram_user_id}: Private key not available")
                    return {
                        'success': False,
                        'error': 'Wallet not ready: Private key not available. Please complete wallet setup via /wallet'
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Polygon wallet not set up. Please complete onboarding via /start'
                    }

            # Get token ID for outcome (use provided token_id if available, otherwise calculate)
            if not token_id:
                token_id = await self._get_token_id_for_outcome(market_data, outcome)
                if not token_id:
                    return {
                        'success': False,
                        'error': f'No token found for outcome {outcome}'
                    }
            else:
                logger.info(f"✅ [TRADE] Using provided token_id: {token_id[:20]}... (from position_id resolution)")

            # Execute market order
            # For SELL orders, amount must be in tokens, not USD
            # For BUY orders, amount is in USD
            if side.upper() == 'SELL':
                # Use tokens_to_sell if provided (more precise), otherwise convert USD to tokens
                if tokens_to_sell is not None and tokens_to_sell > 0:
                    order_amount = tokens_to_sell
                    logger.info(
                        f"💰 [TRADE] Using provided tokens for SELL: {tokens_to_sell:.6f} tokens "
                        f"(≈ ${amount_usd:.2f} at current price)"
                    )
                else:
                    # Fallback: Convert USD amount to tokens using current price
                    current_price = market_data.get('last_mid_price') or market_data.get('last_trade_price') or 0.5
                    if current_price <= 0:
                        return {
                            'success': False,
                            'error': f'Invalid price for SELL order: {current_price}'
                        }
                    # Calculate tokens to sell: amount_usd / price
                    order_amount = amount_usd / current_price
                    logger.info(
                        f"💰 [TRADE] Converting SELL amount: ${amount_usd:.2f} → {order_amount:.6f} tokens "
                        f"(price: ${current_price:.4f})"
                    )
            else:
                order_amount = amount_usd

            order_result = await self.clob_service.place_market_order(
                client=client,
                token_id=token_id,
                side=side.upper(),
                amount=order_amount,
                order_type=order_type,
                market_id=market_data['id'],
                outcome=outcome
            )

            if order_result.get('success'):
                if side.upper() == 'SELL':
                    # For SELL: Find and update/close existing position
                    from core.database.connection import get_db
                    from core.database.models import Position
                    from sqlalchemy import select, and_

                    execution_price = order_result.get('price', 0)
                    tokens_sold = order_result.get('tokens', 0)  # Tokens actually sold

                    # Find position by token_id (position_id)
                    async with get_db() as db:
                        result = await db.execute(
                            select(Position).where(
                                and_(
                                    Position.user_id == user.id,
                                    Position.position_id == token_id,
                                    Position.status == 'active'
                                )
                            )
                        )
                        position = result.scalar_one_or_none()

                    if not position:
                        logger.warning(
                            f"⚠️ [TRADE] No active position found for SELL: "
                            f"user_id={user.id}, token_id={token_id[:20]}..."
                        )
                        # Still return success since order executed, but log warning
                        return {
                            'success': True,
                            'order_id': order_result.get('order_id'),
                            'tokens': tokens_sold,
                            'price': execution_price,
                            'usd_received': order_result.get('usd_received', amount_usd),
                            'tx_hash': order_result.get('tx_hash'),
                            'warning': 'Position not found in DB (may have been closed already)'
                        }

                    # Calculate remaining tokens
                    remaining_tokens = position.amount - tokens_sold

                    # Close position if remaining is dust (< 0.05 tokens)
                    # This prevents positions with tiny amounts from staying active
                    if remaining_tokens <= 0.05:  # Close if dust remaining
                        # Close position
                        logger.info(
                            f"🔒 [TRADE] Closing position {position.id} after SELL "
                            f"(sold {tokens_sold:.6f} of {position.amount:.6f} tokens, "
                            f"remaining {remaining_tokens:.6f} is dust)"
                        )
                        await position_service.close_position(
                            position_id=position.id,
                            exit_price=execution_price
                        )
                    else:
                        # Partial sell - update position
                        logger.info(
                            f"📊 [TRADE] Updating position {position.id} after partial SELL: "
                            f"{position.amount:.6f} → {remaining_tokens:.6f} tokens "
                            f"(sold {tokens_sold:.6f})"
                        )
                        await position_service.update_position(
                            position_id=position.id,
                            amount=remaining_tokens,
                            current_price=execution_price
                        )

                    return {
                        'success': True,
                        'order_id': order_result.get('order_id'),
                        'tokens': tokens_sold,  # Tokens sold
                        'price': execution_price,
                        'usd_received': order_result.get('usd_received', amount_usd),  # USD received from sell
                        'tx_hash': order_result.get('tx_hash')
                    }
                else:
                    # For BUY: Create new position record
                    position = await position_service.create_position(
                        user_id=user.id,
                        market_id=market_data['id'],
                        outcome=outcome,
                        amount=order_result.get('tokens', 0),  # Number of tokens/shares received
                        entry_price=order_result.get('price', 0),
                        is_copy_trade=is_copy_trade,
                        total_cost=order_result.get('total_cost'),  # Shares received (total_cost stores shares, not USD)
                        position_id=token_id  # Store position_id (clob_token_id) for precise lookup
                    )

                    if not position:
                        logger.error(f"Failed to create position record for user {user.id}")
                        return {
                            'success': False,
                            'error': 'Position creation failed'
                        }

                    return {
                        'success': True,
                        'order_id': order_result.get('order_id'),
                        'tokens': order_result.get('tokens', 0),  # Shares received
                        'price': order_result.get('price', 0),
                        'usd_spent': order_result.get('usd_spent', amount_usd),  # USD actually spent
                        'tx_hash': order_result.get('tx_hash')
                    }
            else:
                return {
                    'success': False,
                    'error': order_result.get('error', 'Order placement failed')
                }

        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            return {
                'success': False,
                'error': f'Execution failed: {str(e)}'
            }

    async def _get_token_id_for_outcome(self, market_data: Dict[str, Any], outcome: str) -> Optional[str]:
        """Get token ID for specific outcome using market data"""
        logger.info(f"🔍 _get_token_id_for_outcome called with outcome='{outcome}' for market {market_data.get('id')}")
        return self._get_token_id_fallback(market_data, outcome)

    def _get_token_id_fallback(self, market_data: Dict[str, Any], outcome: str) -> Optional[str]:
        """Fallback method using clob_token_ids (dangerous assumption)"""
        try:
            import json

            logger.warning(f"⚠️ Using DANGEROUS fallback method for outcome '{outcome}'")

            # Debug: log raw market data
            logger.warning(f"Market data keys: {list(market_data.keys())}")
            logger.warning(f"Raw clob_token_ids: {market_data.get('clob_token_ids')}")
            logger.warning(f"Raw outcomes: {market_data.get('outcomes')}")

            # Parse clob_token_ids - now stored as proper JSON string (single parse)
            clob_token_ids_raw = market_data.get('clob_token_ids', '[]')
            logger.warning(f"clob_token_ids_raw: {repr(clob_token_ids_raw)} (type: {type(clob_token_ids_raw)})")

            if isinstance(clob_token_ids_raw, str):
                try:
                    # Single parse: get the actual array from JSON string
                    clob_token_ids = json.loads(clob_token_ids_raw)
                    logger.warning(f"Parsed clob_token_ids: {clob_token_ids}")
                except Exception as parse_error:
                    logger.error(f"JSON parsing failed: {parse_error}")
                    clob_token_ids = []
            else:
                # Fallback: if already parsed (shouldn't happen with new storage)
                clob_token_ids = clob_token_ids_raw or []
                logger.warning(f"Using clob_token_ids as-is: {clob_token_ids}")

            # Get outcomes list
            outcomes_raw = market_data.get('outcomes', ['YES', 'NO'])
            logger.warning(f"outcomes_raw: {outcomes_raw}")

            if isinstance(outcomes_raw, str):
                outcomes_list = json.loads(outcomes_raw)
            else:
                outcomes_list = outcomes_raw

            # Use intelligent outcome normalization
            outcome_index = find_outcome_index(outcome, outcomes_list)
            logger.warning(f"Looking for outcome: '{outcome}' in {outcomes_list}")

            if outcome_index is not None:
                logger.warning(f"Found outcome at index {outcome_index}")

                if outcome_index < len(clob_token_ids):
                    token_id = clob_token_ids[outcome_index]
                    logger.warning(f"⚠️ Fallback success: '{token_id}' (type: {type(token_id)}, index {outcome_index})")
                    return str(token_id)
                else:
                    logger.error(f"Index {outcome_index} out of range for {len(clob_token_ids)} tokens")
            else:
                logger.error(f"Outcome '{outcome}' not found in {outcomes_list}")

            logger.error(f"Fallback failed for outcome '{outcome}'")
            return None

        except Exception as e:
            logger.error(f"Fallback error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def _update_positions_cache(self, user_id: int):
        """Update positions cache after trade"""
        try:
            from core.services.cache_manager import CacheManager
            cache_manager = CacheManager()

            # Invalidate user's positions cache (standardized pattern: api:positions:{user_id})
            await cache_manager.invalidate_pattern(f"api:positions:{user_id}")

        except Exception as e:
            logger.error(f"Cache update error: {e}")


# Global instance
trade_service = TradeService()
