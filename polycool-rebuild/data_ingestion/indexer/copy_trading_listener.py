"""
Copy Trading Listener
Listens to Redis PubSub for trade notifications and executes copy trades
"""
import asyncio
import json
import time
import decimal
import httpx
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import CopyTradingAllocation, WatchedAddress, User, Market, Position
from core.services.redis_pubsub import get_redis_pubsub_service
from core.services.clob.clob_service import get_clob_service
from core.services.market_service import get_market_service
from core.services.trading.trade_service import trade_service
from core.services.copy_trading.leader_position_tracker import get_leader_position_tracker
from core.services.copy_trading.leader_balance_updater import get_leader_balance_updater
from core.services.notification_service import get_notification_service
from core.models.notification_models import Notification, NotificationType, NotificationPriority
from data_ingestion.indexer.watched_addresses.manager import get_watched_addresses_manager
from infrastructure.logging.logger import get_logger
from infrastructure.config.settings import settings

logger = get_logger(__name__)


class CopyTradingListener:
    """
    Listens to Redis PubSub for copy trading notifications
    - Subscribes to copy_trade:* pattern
    - Deduplicates trades (cache tx_id)
    - Filters watched addresses
    - Executes copy trades for followers
    """

    def __init__(self):
        """Initialize Copy Trading Listener"""
        self.pubsub_service = get_redis_pubsub_service()
        self.watched_manager = get_watched_addresses_manager()
        self.clob_service = get_clob_service()
        self.running = False
        self._processed_trades: Dict[str, float] = {}  # tx_id -> timestamp
        self._deduplication_ttl = 300  # 5 minutes

        # Market resolution cache (5min TTL)
        self._position_resolution_cache: Dict[str, Dict[str, Any]] = {}  # position_id -> resolution
        self._position_cache_timestamps: Dict[str, float] = {}  # position_id -> timestamp
        self._position_cache_ttl = 300  # 5 minutes

        # Cache pour éviter les appels API répétés pour les markets non trouvés
        self._api_fetch_failures: Dict[str, float] = {}  # market_id/position_id -> timestamp
        self._api_fetch_failure_ttl = 3600  # 1 heure - éviter de réessayer trop souvent

        # Metrics
        self._metrics = {
            'total_trades_processed': 0,
            'successful_copies': 0,
            'failed_copies': 0,
            'market_resolution_cache_hits': 0,
            'market_resolution_cache_misses': 0,
            'api_fetch_attempts': 0,
            'api_fetch_successes': 0,
            'api_fetch_failures': 0,
        }

    async def start(self) -> None:
        """Start listening to Redis PubSub"""
        try:
            if self.running:
                logger.warning("⚠️ [COPY_TRADE] Copy Trading Listener already running")
                return

            logger.info("🚀 [COPY_TRADE] Starting Copy Trading Listener...")

            # Connect to Redis with retry logic
            logger.info("🔌 [COPY_TRADE] Connecting to Redis PubSub...")
            max_retries = 3
            connected = False

            for attempt in range(max_retries):
                if await self.pubsub_service.health_check():
                    logger.info("✅ [COPY_TRADE] Redis PubSub already connected")
                    connected = True
                    break
                else:
                    logger.info(f"🔄 [COPY_TRADE] Attempting to connect to Redis (attempt {attempt + 1}/{max_retries})...")
                    connected = await self.pubsub_service.connect()
                    if connected:
                        logger.info("✅ [COPY_TRADE] Redis PubSub connected successfully")
                        break
                    else:
                        if attempt < max_retries - 1:
                            logger.warning(f"⚠️ [COPY_TRADE] Connection failed, retrying in 1s...")
                            await asyncio.sleep(1)
                        else:
                            logger.error("❌ [COPY_TRADE] Failed to connect to Redis PubSub after {max_retries} attempts")
                            return

            if not connected:
                logger.error("❌ [COPY_TRADE] Cannot start listener: Redis not connected")
                return

            # Subscribe to copy_trade:* pattern
            logger.info("📡 [COPY_TRADE] Subscribing to pattern: copy_trade:*")
            try:
                await self.pubsub_service.subscribe(
                    pattern="copy_trade:*",
                    callback=self._handle_trade_message
                )
                logger.info("✅ [COPY_TRADE] Successfully subscribed to pattern: copy_trade:*")
            except Exception as sub_error:
                logger.error(f"❌ [COPY_TRADE] Failed to subscribe to pattern: {sub_error}", exc_info=True)
                return

            self.running = True
            logger.info("✅ [COPY_TRADE] Copy Trading Listener started and listening for messages")

        except Exception as e:
            logger.error(f"❌ [COPY_TRADE] Failed to start Copy Trading Listener: {e}", exc_info=True)
            self.running = False

    async def stop(self) -> None:
        """Stop listening"""
        try:
            self.running = False
            await self.pubsub_service.unsubscribe("copy_trade:*")
            logger.info("✅ Copy Trading Listener stopped")
        except Exception as e:
            logger.error(f"❌ Error stopping Copy Trading Listener: {e}")

    async def _handle_trade_message(self, channel: str, data: str) -> None:
        """
        Handle incoming trade message from Redis PubSub

        Args:
            channel: Redis channel (e.g., "copy_trade:0xabc...")
            data: JSON string with trade data
        """
        try:
            # Parse message
            trade_data = json.loads(data)
            tx_id = trade_data.get('tx_id')
            user_address = trade_data.get('user_address')
            tx_type = trade_data.get('tx_type')

            if not tx_id or not user_address:
                logger.warning(f"⚠️ Invalid trade message: missing tx_id or user_address")
                return

            # Deduplication check
            if self._is_duplicate(tx_id):
                logger.debug(f"⏭️ Skipped duplicate trade: {tx_id[:20]}...")
                return

            # Mark as processed
            self._mark_processed(tx_id)

            # Track metrics
            self._metrics['total_trades_processed'] += 1

            logger.info(
                f"🚀 [COPY_TRADE] Received {tx_type} trade from {user_address[:10]}... "
                f"(tx_id: {tx_id[:20]}..., channel: {channel}, outcome: {trade_data.get('outcome')}, "
                f"market_id: {trade_data.get('market_id', 'N/A')[:20]}...)"
            )

            # Get leader address info
            address_info = await self.watched_manager.is_watched_address(user_address)
            logger.info(
                f"🔍 [COPY_TRADE] Address info for {user_address[:10]}...: "
                f"is_watched={address_info.get('is_watched')}, "
                f"address_type={address_info.get('address_type')}"
            )

            if not address_info['is_watched']:
                logger.info(f"⏭️ [COPY_TRADE] Address {user_address[:10]}... not watched, skipping")
                return

            # CRITICAL: Only process copy_leader addresses, skip smart_trader addresses
            if address_info['address_type'] != 'copy_leader':
                logger.info(
                    f"⏭️ [COPY_TRADE] Skipped non-leader address: {user_address[:10]}... "
                    f"(type: {address_info['address_type']}, tx_id: {tx_id[:20]}...)"
                )
                return

            # Get watched address record
            async with get_db() as db:
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.address == user_address.lower())
                    .where(WatchedAddress.is_active == True)
                    .where(WatchedAddress.address_type == 'copy_leader')  # Additional safety check
                )
                watched_address = result.scalar_one_or_none()

            if not watched_address:
                logger.warning(
                    f"⚠️ [COPY_TRADE] Watched address not found in DB: {user_address[:10]}... "
                    f"(tx_id: {tx_id[:20]}...)"
                )
                return

            logger.info(
                f"✅ [COPY_TRADE] Found watched address: id={watched_address.id}, "
                f"address_type={watched_address.address_type}, is_active={watched_address.is_active}"
            )

            # Get all active copy trading allocations for this leader
            async with get_db() as db:
                result = await db.execute(
                    select(CopyTradingAllocation)
                    .where(
                        and_(
                            CopyTradingAllocation.leader_address_id == watched_address.id,
                            CopyTradingAllocation.is_active == True
                        )
                    )
                )
                allocations = list(result.scalars().all())

            if not allocations:
                logger.info(f"⏭️ No active followers for leader {user_address[:10]}... (watched_address_id={watched_address.id})")
                return

            logger.info(
                f"🔄 [COPY_TRADE] Found {len(allocations)} active followers for leader {user_address[:10]}... "
                f"(watched_address_id={watched_address.id}, tx_id={tx_id[:20]}...)"
            )

            # Execute copy trades for each follower (parallel)
            tasks = []
            for allocation in allocations:
                logger.info(
                    f"📋 [COPY_TRADE] Creating task for follower user_id={allocation.user_id} "
                    f"(allocation_id={allocation.id}, mode={allocation.mode})"
                )
                task = asyncio.create_task(
                    self._execute_copy_trade(allocation, trade_data)
                )
                tasks.append(task)

            # Wait for all copy trades (but don't fail if some fail)
            results = await asyncio.gather(*tasks, return_exceptions=True)

            success_count = sum(1 for r in results if r is True)
            failed_count = len(allocations) - success_count
            logger.info(
                f"✅ [COPY_TRADE] Completed: {success_count}/{len(allocations)} successful, "
                f"{failed_count} failed (tx_id={tx_id[:20]}...)"
            )

        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in trade message: {e}")
        except Exception as e:
            logger.error(f"❌ Error handling trade message: {e}", exc_info=True)

    async def _execute_copy_trade(
        self,
        allocation: CopyTradingAllocation,
        trade_data: Dict[str, Any]
    ) -> bool:
        """
        Execute copy trade for a follower

        Args:
            allocation: CopyTradingAllocation object
            trade_data: Trade data from Redis

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(
                f"🔄 [COPY_TRADE] Starting copy trade execution for user {allocation.user_id} "
                f"(allocation_id={allocation.id}, tx_type={trade_data.get('tx_type', 'BUY')}, "
                f"tx_id={trade_data.get('tx_id', 'unknown')[:20]}...)"
            )

            # Get user
            async with get_db() as db:
                result = await db.execute(
                    select(User)
                    .where(User.id == allocation.user_id)
                )
                user = result.scalar_one_or_none()

            if not user or user.stage != "ready":
                logger.debug(f"⏭️ User {allocation.user_id} not ready for copy trading")
                return False

            # Resolve market and token ID (priority: position_id > market_id+outcome)
            resolution = await self._resolve_market_and_token(trade_data)
            if not resolution:
                logger.warning(f"⚠️ Could not resolve market/token for trade {trade_data.get('tx_id', 'unknown')}")
                return False

            market = resolution['market']

            # CRITICAL: Use resolved outcome as primary source of truth
            # The resolution from _resolve_market_by_position_id uses position_id to find
            # the exact outcome from the market's outcomes array
            resolved_outcome = resolution.get('outcome')
            if resolved_outcome and resolved_outcome != 'UNKNOWN':
                outcome = resolved_outcome
            else:
                # Fallback: Use outcome index from trade_data to get outcome from market's outcomes array
                trade_outcome_index = trade_data.get('outcome')
                outcomes = market.get('outcomes', [])

                if outcomes and isinstance(outcomes, list) and isinstance(trade_outcome_index, (int, str)):
                    try:
                        outcome_idx = int(trade_outcome_index)
                        if 0 <= outcome_idx < len(outcomes):
                            outcome = outcomes[outcome_idx]
                        else:
                            logger.warning(f"⚠️ Outcome index {outcome_idx} out of range for market {market.get('id')}")
                            outcome = "UNKNOWN"
                    except (ValueError, TypeError):
                        logger.warning(f"⚠️ Invalid outcome index {trade_outcome_index}")
                        outcome = "UNKNOWN"
                else:
                    logger.warning(f"⚠️ Cannot resolve outcome: no outcomes array or invalid index")
                    outcome = "UNKNOWN"

            trade_outcome_index = trade_data.get('outcome')
            logger.info(
                f"🔍 [COPY_TRADE] Outcome mapping: trade_outcome_index={trade_outcome_index}, "
                f"resolved_outcome={resolved_outcome}, final_outcome={outcome}, "
                f"market_outcomes={market.get('outcomes', [])}"
            )

            # CRITICAL: Use original market_id from webhook if available (for consistency with leader position tracking)
            # The webhook stores leader positions using event.market_id (which is often a condition_id)
            # But resolution returns market.id (which is a short numeric ID)
            # We need to use the same market_id format that was used during BUY
            original_market_id = trade_data.get('market_id')
            resolved_market_id = market.get('id')

            # Prefer original market_id from webhook for leader position lookup
            # This ensures we use the same market_id format as stored in leader_positions
            market_id_for_position = original_market_id if original_market_id else resolved_market_id
            # Use resolved market_id for market data retrieval (API calls)
            market_id_for_api = resolved_market_id

            logger.info(
                f"🔍 [COPY_TRADE] Resolved market: resolved_id={resolved_market_id}, "
                f"original_id={original_market_id}, using_for_position={market_id_for_position}, "
                f"outcome={outcome}, title={market.get('title', 'N/A')[:50]}..."
            )

            if not market_id_for_position:
                logger.warning(f"⚠️ [COPY_TRADE] Missing market_id for position lookup")
                return False

            if not market_id_for_api:
                logger.warning(f"⚠️ [COPY_TRADE] Missing market_id for API calls")
                return False

            # Calculate copy trade amount (use taking_amount directly if available)
            tx_type = trade_data.get('tx_type', 'BUY')
            taking_amount_str = trade_data.get('taking_amount')  # Total USDC amount (string)

            # Parse taking_amount (already in USDC real value, not units)
            leader_amount_usdc = None
            if taking_amount_str:
                try:
                    leader_amount_usdc = float(taking_amount_str)
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ Invalid taking_amount: {taking_amount_str}")

            # Get follower balance
            balance_info = await self.clob_service.get_balance(user.telegram_user_id)
            balance = balance_info.get('balance', 0.0) if balance_info else 0.0

            if balance <= 0:
                logger.debug(f"⏭️ User {user.telegram_user_id} has no balance")
                return False

            # Refresh allocation budget with current balance (dynamic update)
            allocation.update_budget_from_wallet(balance)

            # Save updated budget to DB
            async with get_db() as db:
                db.add(allocation)
                await db.commit()

            # Calculate copy amount based on allocation settings and trade type
            tx_type = trade_data.get('tx_type', 'BUY').upper()

            if tx_type == 'BUY':
                # BUY: Use calculation with leader balance for proportional mode
                copy_amount = await self._calculate_buy_copy_amount(
                    allocation=allocation,
                    leader_amount_usdc=leader_amount_usdc,
                    trade_data=trade_data,
                    follower_balance=balance,
                    mode=allocation.mode
                )
                logger.info(
                    f"📊 [COPY_TRADE_BUY] BUY calculation result: {copy_amount} USD "
                    f"for user {user.telegram_user_id}"
                )
            elif tx_type == 'SELL':
                # SELL: Use position-based calculation
                # Use market_id_for_position (original from webhook) for leader position lookup
                logger.info(
                    f"💰 [COPY_TRADE_SELL] Calculating SELL amount for user {user.telegram_user_id} "
                    f"(leader_amount_usdc={leader_amount_usdc}, market_id={market_id_for_position}, outcome={outcome})"
                )
                sell_result = await self._calculate_sell_copy_amount(
                    allocation=allocation,
                    leader_amount_usdc=leader_amount_usdc,
                    trade_data=trade_data,
                    market_id=market_id_for_position,  # Use original market_id for leader position lookup
                    outcome=outcome,
                    user=user,
                    resolved_market_id=market_id_for_api  # Pass resolved_id for follower position lookup
                )
                # sell_result is now a dict with 'tokens' and 'usd' keys
                if isinstance(sell_result, dict):
                    copy_amount = sell_result.get('usd', 0)
                    trade_data['_tokens_to_sell'] = sell_result.get('tokens')  # Store for later use
                else:
                    copy_amount = sell_result if sell_result else 0
                logger.info(
                    f"📊 [COPY_TRADE_SELL] SELL calculation result: {copy_amount} USD "
                    f"for user {user.telegram_user_id}"
                )

            if copy_amount <= 0:
                logger.warning(
                    f"⏭️ [COPY_TRADE] Copy amount is 0 for user {user.telegram_user_id} "
                    f"(allocation_id={allocation.id}, leader_amount_usdc={leader_amount_usdc})"
                )
                return False

            # Execute trade using the existing TradeService
            # Pass is_copy_trade=True to mark position as copy trade
            # Use market_id_for_api (resolved short ID) for API calls
            logger.info(
                f"💰 [COPY_TRADE] Executing {tx_type} trade for user {user.telegram_user_id}: "
                f"${copy_amount:.2f} on market {market_id_for_api} ({outcome}) "
                f"(allocation_id={allocation.id}, tx_id={trade_data.get('tx_id', 'unknown')[:20]}...)"
            )

            # Get token_id from resolution (if available) to ensure we use the exact position_id
            token_id = resolution.get('token_id') if resolution else None

            # For SELL, get tokens directly from the calculation we already did
            tokens_to_sell = trade_data.get('_tokens_to_sell') if tx_type == 'SELL' else None

            result = await trade_service.execute_market_order(
                user_id=user.telegram_user_id,
                market_id=market_id_for_api,  # Use resolved market_id for API calls
                outcome=outcome,
                amount_usd=copy_amount,
                order_type='IOC',  # Immediate or Cancel
                is_copy_trade=True,  # Mark as copy trade
                token_id=token_id,  # Pass token_id from resolution (position_id) for precise position creation
                side=tx_type,  # Pass tx_type ('BUY' or 'SELL') to execute correct order type
                tokens_to_sell=tokens_to_sell  # For SELL: pass tokens directly to avoid conversion errors
            )

            logger.info(
                f"📊 [COPY_TRADE] Trade execution result for user {user.telegram_user_id}: "
                f"status={result.get('status') if result else 'None'}, "
                f"error={result.get('error') if result else 'None'}"
            )

            if result and result.get('status') == 'executed':
                # Update allocation stats
                async with get_db() as db:
                    allocation.total_copied_trades += 1
                    # Fix: Convert copy_amount (float) to float for DB storage (total_invested is Float column)
                    allocation.total_invested += float(copy_amount)
                    allocation.updated_at = datetime.now(timezone.utc)
                    await db.commit()

                # Send copy trade notification (async, non-blocking, fire-and-forget)
                try:
                    asyncio.create_task(
                        self._send_copy_trade_notification(
                            user.telegram_user_id,
                            allocation,
                            market,
                            tx_type,
                            copy_amount
                        )
                    )
                    logger.debug(f"📨 [COPY_TRADE] Notification task created for user {user.telegram_user_id}")
                except Exception as notif_error:
                    logger.warning(f"⚠️ [COPY_TRADE] Failed to create notification task: {notif_error}")
                    # Continue - don't fail the trade because of notification issues

                self._metrics['successful_copies'] += 1
                logger.info(
                    f"✅ Copied {tx_type} trade: ${copy_amount:.2f} for user {user.telegram_user_id}"
                )
                return True
            else:
                self._metrics['failed_copies'] += 1
                error_msg = result.get('error', 'Unknown error') if result else 'Order failed'
                logger.warning(
                    f"⚠️ Copy trade failed for user {user.telegram_user_id}: {error_msg}"
                )
                return False

        except Exception as e:
            logger.error(f"❌ Error executing copy trade: {e}", exc_info=True)
            return False

    async def _resolve_market_and_token(self, trade_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Resolve market and token ID from trade data

        Priority 1: Use position_id (clob_token_id) - ground truth from blockchain
        Priority 2: Use market_id + outcome (fallback)

        Uses cache (5min TTL) for performance.

        Args:
            trade_data: Trade data from Redis

        Returns:
            Dict with 'market' and 'token_id', or None if resolution failed
        """
        position_id = trade_data.get('position_id')
        market_id = trade_data.get('market_id')
        outcome = trade_data.get('outcome')

        # Priority 1: Resolve via position_id (most reliable)
        if position_id:
            resolution = await self._resolve_market_by_position_id(position_id)
            if resolution:
                self._metrics['market_resolution_cache_hits'] += 1
                return {
                    'market': resolution['market'],
                    'token_id': position_id,  # Use position_id as token_id
                    'outcome': resolution['outcome'],
                }
            else:
                self._metrics['market_resolution_cache_misses'] += 1

        # Priority 2: Fallback to market_id + outcome
        if market_id and outcome is not None:
            return await self._resolve_market_by_id_and_outcome(market_id, outcome)

        logger.warning(f"⚠️ Could not resolve market: position_id={position_id}, market_id={market_id}, outcome={outcome}")
        return None

    async def _resolve_market_by_position_id(self, position_id: str) -> Optional[Dict[str, Any]]:
        """
        Resolve market via position_id (clob_token_id)
        Uses cache (5min TTL) for performance.

        Args:
            position_id: The token_id from the trade (clob_token_id)

        Returns:
            Dict with market data and outcome, or None if not found
        """
        if not position_id:
            return None

        # Check cache
        current_time = time.time()
        if position_id in self._position_resolution_cache:
            cache_age = current_time - self._position_cache_timestamps.get(position_id, 0)
            if cache_age < self._position_cache_ttl:
                logger.debug(f"✅ [CACHE_HIT] Using cached resolution for position_id ...{position_id[-20:]}")
                self._metrics['market_resolution_cache_hits'] += 1
                return self._position_resolution_cache[position_id]
            else:
                # Cache expired
                del self._position_resolution_cache[position_id]
                del self._position_cache_timestamps[position_id]

        try:
            logger.info(f"🔍 [RESOLUTION] Resolving position_id: ...{position_id[-20:]}")

            # Query markets table for market containing this position_id in clob_token_ids
            async with get_db() as db:
                import json
                from sqlalchemy import or_, func

                # Search for market with this position_id in clob_token_ids (JSONB)
                # Use PostgreSQL JSONB contains operator
                result = await db.execute(
                    select(Market)
                    .where(
                        or_(
                            Market.clob_token_ids.contains([position_id]),  # JSONB array contains
                            Market.clob_token_ids.contains([str(position_id)]),  # Try as string too
                        ),
                        Market.is_active == True
                    )
                )
                matching_market = result.scalar_one_or_none()

                if not matching_market:
                    logger.warning(f"⚠️ [RESOLUTION] No market found in DB for position_id ...{position_id[-20:]}")
                    self._metrics['market_resolution_cache_misses'] += 1

                    # FALLBACK: Essayer de récupérer depuis l'API Gamma si non trouvé en DB
                    # On ne peut pas chercher directement par token_id dans l'API Gamma,
                    # mais on peut essayer si on a un market_id dans trade_data
                    # Pour l'instant, on log et on retourne None
                    # La résolution par market_id + outcome sera tentée dans _resolve_market_and_token
                    logger.info(f"🔄 [RESOLUTION] Market not in DB, will try fallback resolution methods")
                    return None

                # Parse clob_token_ids to find index (now always a list after storage fix)
                clob_token_ids = matching_market.clob_token_ids or []

                # Find index of position_id
                token_index = -1
                for i, token_id in enumerate(clob_token_ids):
                    if str(token_id) == str(position_id):
                        token_index = i
                        break

                if token_index < 0:
                    logger.error(f"❌ position_id not found in clob_token_ids array")
                    return None

                # Get outcome from outcomes array
                outcomes = matching_market.outcomes or []
                if token_index >= len(outcomes):
                    logger.error(f"❌ token_index {token_index} out of range for outcomes")
                    return None

                outcome_str = outcomes[token_index]
                # Use exact outcome from market (no normalization to preserve "Over"/"Under" etc.)

                logger.info(
                    f"✅ [RESOLUTION] Found market: {matching_market.title[:50]}..., "
                    f"outcome={outcome_str} (index={token_index})"
                )

                # Build market dict
                market_dict = {
                    'id': matching_market.id,
                    'title': matching_market.title,
                    'outcomes': outcomes,
                    'clob_token_ids': clob_token_ids,
                    'outcome_prices': matching_market.outcome_prices or [],
                }

                resolution_result = {
                    'market': market_dict,
                    'outcome': outcome_str,  # Use exact outcome from market (no normalization)
                    'outcome_index': token_index,
                    'token_index': token_index,
                }

                # Cache it
                self._position_resolution_cache[position_id] = resolution_result
                self._position_cache_timestamps[position_id] = current_time

                return resolution_result

        except Exception as e:
            logger.error(f"❌ Error resolving position_id: {e}", exc_info=True)
            return None

    async def _calculate_sell_copy_amount(
        self,
        allocation: CopyTradingAllocation,
        leader_amount_usdc: Optional[float],
        trade_data: Dict[str, Any],
        market_id: str,
        outcome: str,
        user: User,
        resolved_market_id: Optional[str] = None
    ) -> float:
        """
        Calculate SELL copy amount using position-based logic

        Args:
            allocation: Copy trading allocation
            leader_amount_usdc: USD amount leader sold
            trade_data: Trade data from webhook
            market_id: Market ID (original_id for leader position lookup)
            outcome: Outcome (YES/NO)
            user: Follower user
            resolved_market_id: Resolved market ID (short ID) - used for follower position lookup

        Returns:
            USD amount to sell, or 0 if should skip
        """
        try:
            # Get amount leader sold in TOKENS (from trade_data) - PRIMARY for calculation
            amount_str = trade_data.get('amount', '0')
            try:
                tokens_sold = float(amount_str) / 1_000_000 if float(amount_str) > 1_000_000 else float(amount_str)
            except (ValueError, TypeError):
                logger.warning(f"⚠️ [COPY_TRADE_SELL] Invalid amount in trade_data: {amount_str}")
                return 0.0

            if tokens_sold <= 0:
                logger.warning(f"⏭️ [COPY_TRADE_SELL] Invalid leader tokens sold: {tokens_sold}")
                return 0.0

            logger.info(
                f"💰 [COPY_TRADE_SELL] Calculating SELL amount (token-based): "
                f"leader_tokens_sold={tokens_sold:.6f}, leader_amount_usdc={leader_amount_usdc}, "
                f"market_id={market_id}, outcome={outcome}, "
                f"user_id={user.id}, allocation_id={allocation.id}, "
                f"original_market_id={trade_data.get('market_id')}, resolved_market_id={resolved_market_id}"
            )

            # Get leader position tracker
            position_tracker = get_leader_position_tracker()

            # Get leader's position BEFORE the sell (add back what they sold)
            leader_watched_address_id = allocation.leader_address_id

            # Use position_id from trade_data if available (same logic as BUY)
            position_id = trade_data.get('position_id')

            logger.info(
                f"🔍 [COPY_TRADE_SELL] Getting leader position: "
                f"watched_address_id={leader_watched_address_id}, market_id={market_id}, outcome={outcome}, "
                f"position_id={position_id[:20] if position_id else None}..."
            )

            leader_position_size = await position_tracker.get_leader_position(
                watched_address_id=leader_watched_address_id,
                market_id=market_id,
                outcome=outcome,
                position_id=position_id  # Use position_id for more precise lookup (same as BUY)
            )

            logger.info(
                f"📊 [COPY_TRADE_SELL] Leader position size: {leader_position_size} "
                f"(market_id={market_id}, outcome={outcome})"
            )

            if not leader_position_size or leader_position_size <= 0:
                logger.warning(f"⏭️ [COPY_TRADE_SELL] Leader has no position for {market_id}/{outcome}")
                return 0.0

            # Calculate leader position BEFORE sell (add back tokens sold)
            # tokens_sold was already parsed above
            leader_position_before_sell = leader_position_size + tokens_sold

            # Get follower's position
            # SIMPLIFIED: Use position_id as primary identifier (most precise)
            # position_id is the clob_token_id, which uniquely identifies the token (YES/NO) for a market
            position_id = trade_data.get('position_id')

            follower_position = None

            if position_id:
                # Priority 1: Search by position_id (most precise - works regardless of market_id format)
                # NOTE: Multiple active positions can exist with same position_id (from multiple BUY trades)
                # We need to aggregate all active positions to get total token amount
                logger.info(
                    f"🔍 [COPY_TRADE_SELL] Getting follower position by position_id: "
                    f"user_id={user.id}, position_id={position_id[:20]}..."
                )

                async with get_db() as db:
                    result = await db.execute(
                        select(Position).where(
                            and_(
                                Position.user_id == user.id,
                                Position.position_id == position_id,
                                Position.status == 'active'
                            )
                        )
                    )
                    positions = result.scalars().all()

                if positions:
                    # Aggregate all active positions with same position_id
                    total_amount = sum(pos.amount for pos in positions)
                    # Use the most recent position as reference (for logging/debugging)
                    follower_position = max(positions, key=lambda p: p.created_at)
                    # Override amount with aggregated total
                    follower_position.amount = total_amount

                    logger.info(
                        f"✅ [COPY_TRADE_SELL] Found {len(positions)} active position(s) by position_id: "
                        f"position_id={position_id[:20]}..., total_amount={total_amount:.6f} tokens "
                        f"(aggregated from {len(positions)} positions)"
                    )
                else:
                    follower_position = None

            # Fallback: If position_id not available or not found, try market_id + outcome (for backward compatibility)
            if not follower_position:
                logger.info(
                    f"🔍 [COPY_TRADE_SELL] Fallback: Getting follower position by market_id+outcome: "
                    f"user_id={user.id}, market_id={resolved_market_id or market_id}, outcome={outcome}"
                )

                outcome_normalized = outcome.upper().strip()
                market_ids_to_try = []
                if resolved_market_id and resolved_market_id != market_id:
                    market_ids_to_try.append(resolved_market_id)
                market_ids_to_try.append(market_id)

                async with get_db() as db:
                    from sqlalchemy import func
                    for try_market_id in market_ids_to_try:
                        result = await db.execute(
                            select(Position).where(
                                and_(
                                    Position.user_id == user.id,
                                    Position.market_id == try_market_id,
                                    func.upper(Position.outcome) == outcome_normalized,
                                    Position.status == 'active'
                                )
                            )
                        )
                        follower_position = result.scalar_one_or_none()
                        if follower_position:
                            logger.info(
                                f"✅ [COPY_TRADE_SELL] Found follower position by market_id+outcome: "
                                f"market_id={try_market_id}, outcome={outcome}, amount={follower_position.amount:.6f} tokens"
                            )
                            break

            if not follower_position:
                logger.warning(
                    f"⏭️ [COPY_TRADE_SELL] Follower has no active position: "
                    f"user_id={user.id}, position_id={position_id[:20] if position_id else None}..., "
                    f"market_id={resolved_market_id or market_id}, outcome={outcome}"
                )
                return 0.0

            if follower_position.amount <= 0:
                logger.warning(
                    f"⏭️ [COPY_TRADE_SELL] Follower position amount is 0 or negative: "
                    f"{follower_position.amount} (user_id={user.id}, market_id={market_id})"
                )
                return 0.0

            follower_position_size = follower_position.amount
            logger.info(
                f"📊 [COPY_TRADE_SELL] Follower position size: {follower_position_size} "
                f"(user_id={user.id}, market_id={market_id})"
            )

            # Get current market price
            # Use resolved_market_id (short ID) for market data retrieval, as markets are stored with short ID
            # market_id (original_id) is only used for position lookup
            market_id_for_price = resolved_market_id if resolved_market_id else market_id
            logger.info(
                f"🔍 [COPY_TRADE_SELL] Getting market data for price calculation: "
                f"resolved_id={resolved_market_id}, original_id={market_id}, using={market_id_for_price}"
            )
            market_service = get_market_service()
            market_data = await market_service.get_market_by_id(market_id_for_price)
            if not market_data:
                logger.warning(
                    f"⚠️ [COPY_TRADE_SELL] Could not get market data for {market_id_for_price} "
                    f"(user_id={user.id}, tried resolved_id={resolved_market_id}, original_id={market_id})"
                )
                return 0.0

            current_price = market_data.get('last_mid_price') or market_data.get('last_trade_price')
            logger.info(
                f"💰 [COPY_TRADE_SELL] Current market price: {current_price} "
                f"(market_id={market_id})"
            )

            if not current_price or current_price <= 0:
                logger.warning(
                    f"⚠️ [COPY_TRADE_SELL] Invalid price for market {market_id}: {current_price} "
                    f"(user_id={user.id})"
                )
                return 0.0

            # Calculate position-based sell amount (TOKEN-BASED for precision)
            logger.info(
                f"🧮 [COPY_TRADE_SELL] Calculating position-based sell amount (token-based): "
                f"leader_tokens_sold={tokens_sold:.6f}, "
                f"leader_position_size={leader_position_before_sell:.6f}, "
                f"follower_position_size={follower_position_size:.6f}, "
                f"current_price={current_price:.4f}"
            )

            sell_result = await position_tracker.calculate_position_based_sell_amount(
                leader_tokens_sold=tokens_sold,  # PRIMARY: Use tokens directly (most precise)
                leader_position_size=leader_position_before_sell,
                follower_position_size=follower_position_size,
                current_price=current_price  # Only used for final USD conversion
            )

            if not sell_result or not isinstance(sell_result, dict):
                logger.warning(
                    f"⏭️ [COPY_TRADE_SELL] Calculated sell amount is invalid: {sell_result} "
                    f"(user_id={user.id}, market_id={market_id})"
                )
                return 0.0

            tokens_to_sell = sell_result.get('tokens', 0)
            sell_amount_usd = sell_result.get('usd', 0)

            logger.info(
                f"📊 [COPY_TRADE_SELL] Calculated sell amount: {tokens_to_sell:.6f} tokens = ${sell_amount_usd:.2f} "
                f"(user_id={user.id}, market_id={market_id})"
            )

            if not tokens_to_sell or tokens_to_sell <= 0:
                logger.warning(
                    f"⏭️ [COPY_TRADE_SELL] Calculated tokens to sell is 0 or invalid: {tokens_to_sell} "
                    f"(user_id={user.id}, market_id={market_id})"
                )
                return 0.0

            # Apply minimum threshold for SELL ($0.50)
            # Note: BUY minimum is $1.0, SELL minimum is $0.50
            MIN_SELL_AMOUNT = 0.50
            if sell_amount_usd < MIN_SELL_AMOUNT:
                logger.warning(
                    f"⏭️ [COPY_TRADE_SELL] Sell amount ${sell_amount_usd:.2f} below minimum ${MIN_SELL_AMOUNT} "
                    f"(user_id={user.id}, market_id={market_id})"
                )
                return {'tokens': 0, 'usd': 0}

            logger.info(
                f"✅ [COPY_TRADE_SELL] Position-based SELL calculated: Leader sold ${leader_amount_usdc:.2f} "
                f"({tokens_sold:.6f} tokens from {leader_position_before_sell:.6f}), "
                f"Follower selling ${sell_amount_usd:.2f} ({tokens_to_sell:.6f} tokens from {follower_position_size:.6f}) "
                f"(user_id={user.id}, market_id={market_id})"
            )

            # Return dict with both tokens and USD for SELL (to avoid conversion errors)
            return {'tokens': tokens_to_sell, 'usd': sell_amount_usd}

        except Exception as e:
            logger.error(f"❌ Error calculating SELL copy amount: {e}", exc_info=True)
            return 0.0

    async def _resolve_market_by_id_and_outcome(
        self,
        market_id: str,
        outcome: int
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve market via market_id + outcome (fallback method)
        Si le market n'est pas trouvé en DB, essaie de le récupérer depuis l'API Gamma

        Args:
            market_id: Market ID from trade data
            outcome: Outcome index (0 or 1)

        Returns:
            Dict with market and token_id, or None if not found
        """
        try:
            cache_manager = None  # TODO: Get from app state if needed
            market_service = get_market_service(cache_manager=cache_manager)
            market = await market_service.get_market_by_id(market_id)

            if not market:
                logger.warning(f"⚠️ [RESOLUTION] Market {market_id} not found in DB, trying Gamma API...")

                # FALLBACK: Récupérer depuis l'API Gamma et l'ajouter à la DB
                fetched_market = await self._fetch_market_from_gamma_api(market_id)
                if fetched_market:
                    # Réessayer après avoir ajouté le market à la DB
                    market = await market_service.get_market_by_id(market_id)
                    if not market:
                        logger.warning(f"⚠️ [RESOLUTION] Market {market_id} still not found after API fetch")
                        return None
                else:
                    logger.warning(f"⚠️ [RESOLUTION] Could not fetch market {market_id} from Gamma API")
                    return None

            # Get token ID for outcome using outcomes array (not hardcoded)
            clob_token_ids = market.get('clob_token_ids', [])
            outcomes = market.get('outcomes', [])

            if not outcomes or not isinstance(outcomes, list):
                logger.warning(f"⚠️ No outcomes array in market {market_id}")
                return None

            if not clob_token_ids or not isinstance(clob_token_ids, list):
                logger.warning(f"⚠️ No clob_token_ids array in market {market_id}")
                return None

            token_id = None
            outcome_str = None

            try:
                outcome_index = int(outcome) if isinstance(outcome, (int, str)) else 0

                # Validate index range for outcomes
                if outcome_index < 0 or outcome_index >= len(outcomes):
                    logger.warning(f"⚠️ Outcome index {outcome_index} out of range for market {market_id} (outcomes: {outcomes})")
                    return None

                # Validate index range for clob_token_ids
                if outcome_index >= len(clob_token_ids):
                    logger.warning(f"⚠️ Outcome index {outcome_index} out of range for clob_token_ids in market {market_id} (len={len(clob_token_ids)})")
                    return None

                # Get token_id and outcome string from arrays using the same index
                token_id = clob_token_ids[outcome_index]
                outcome_str = outcomes[outcome_index]

            except (ValueError, IndexError, TypeError) as e:
                logger.warning(f"⚠️ Error parsing outcome index {outcome} for market {market_id}: {e}")
                return None

            if not token_id or not outcome_str:
                logger.warning(f"⚠️ Token ID or outcome is empty for market {market_id}, outcome index {outcome}")
                return None

            return {
                'market': market,
                'token_id': token_id,
                'outcome': outcome_str,  # Use exact outcome from market's outcomes array
            }

        except Exception as e:
            logger.error(f"❌ Error resolving market by ID: {e}", exc_info=True)
            return None

    async def _fetch_market_from_gamma_api(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère un market depuis l'API Gamma et l'ajoute à la DB
        Utilise un cache pour éviter les appels API répétés

        Args:
            market_id: Market ID à récupérer

        Returns:
            Market dict si récupéré avec succès, None sinon
        """
        # Vérifier le cache d'échecs pour éviter les appels répétés
        current_time = time.time()
        if market_id in self._api_fetch_failures:
            failure_age = current_time - self._api_fetch_failures[market_id]
            if failure_age < self._api_fetch_failure_ttl:
                logger.debug(f"⏭️ [API_FETCH] Skipping API fetch for {market_id} (recent failure, age: {failure_age:.0f}s)")
                return None
            else:
                # Cache expiré, on peut réessayer
                del self._api_fetch_failures[market_id]

        try:
            self._metrics['api_fetch_attempts'] += 1
            logger.info(f"🌐 [API_FETCH] Fetching market {market_id} from Gamma API...")

            # Créer une instance temporaire du poller pour réutiliser la logique d'upsert
            from data_ingestion.poller.base_poller import BaseGammaAPIPoller
            temp_poller = BaseGammaAPIPoller()

            # Récupérer le market depuis l'API Gamma
            api_url = settings.polymarket.gamma_api_base
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{api_url}/markets/{market_id}")

                if response.status_code == 404:
                    logger.warning(f"⚠️ [API_FETCH] Market {market_id} not found in Gamma API (404)")
                    self._api_fetch_failures[market_id] = current_time
                    self._metrics['api_fetch_failures'] += 1
                    return None

                response.raise_for_status()
                market_data = response.json()

            # Ajouter le market à la DB via la logique d'upsert du poller
            # Le poller attend une liste de markets
            markets_list = [market_data]
            upserted_count = await temp_poller._upsert_markets(markets_list, allow_resolved=False)

            if upserted_count > 0:
                logger.info(f"✅ [API_FETCH] Successfully fetched and added market {market_id} to DB")
                self._metrics['api_fetch_successes'] += 1
                return market_data
            else:
                logger.warning(f"⚠️ [API_FETCH] Market {market_id} fetched but not upserted (may be resolved/inactive)")
                self._api_fetch_failures[market_id] = current_time
                self._metrics['api_fetch_failures'] += 1
                return None

        except httpx.TimeoutException:
            logger.warning(f"⏱️ [API_FETCH] Timeout fetching market {market_id} from Gamma API")
            self._api_fetch_failures[market_id] = current_time
            self._metrics['api_fetch_failures'] += 1
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"⚠️ [API_FETCH] HTTP error {e.response.status_code} fetching market {market_id}")
            self._api_fetch_failures[market_id] = current_time
            self._metrics['api_fetch_failures'] += 1
            return None
        except Exception as e:
            logger.error(f"❌ [API_FETCH] Error fetching market {market_id} from Gamma API: {e}", exc_info=True)
            self._api_fetch_failures[market_id] = current_time
            self._metrics['api_fetch_failures'] += 1
            return None

    async def _calculate_buy_copy_amount(
        self,
        allocation: CopyTradingAllocation,
        leader_amount_usdc: Optional[float],
        trade_data: Dict[str, Any],
        follower_balance: float,
        mode: str
    ) -> float:
        """
        Calculate BUY copy trade amount based on allocation settings

        For proportional mode: Uses leader's wallet balance to calculate the percentage
        of wallet used, then applies same percentage to follower's allocated budget.

        Priority: Use taking_amount (amount_usdc) directly if available.
        Fallback: Calculate from amount * price (with proper unit conversion).

        Args:
            allocation: CopyTradingAllocation object
            leader_amount_usdc: Leader's trade amount in USDC (from taking_amount)
            trade_data: Full trade data dict (for fallback calculation)
            follower_balance: Follower's current balance
            mode: 'proportional' or 'fixed_amount'

        Returns:
            Copy amount in USD
        """
        try:
            # Priority 1: Use amount_usdc directly (most accurate)
            if leader_amount_usdc is not None and leader_amount_usdc > 0:
                leader_amount_float = leader_amount_usdc
            else:
                # Fallback: Calculate from amount * price
                # amount is in units (6 decimals), convert to real value
                amount_str = trade_data.get('amount', '0')
                price_str = trade_data.get('price')

                try:
                    amount_raw = float(amount_str) if amount_str else 0.0
                    # Convert from units to real value (divide by 1_000_000 if > 1M)
                    amount_real = amount_raw / 1_000_000 if amount_raw > 1_000_000 else amount_raw
                    price = float(price_str) if price_str else None

                    if price and amount_real > 0:
                        leader_amount_float = amount_real * price
                        logger.debug(f"📊 Calculated leader amount from fallback: ${leader_amount_float:.2f}")
                    else:
                        leader_amount_float = 0.0
                        logger.warning(f"⚠️ Could not calculate leader amount: amount={amount_real}, price={price}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Error parsing amount/price for fallback: {e}")
                    leader_amount_float = 0.0

            if leader_amount_float <= 0:
                logger.warning(f"⚠️ Leader amount is 0 or invalid")
                return 0.0

            # Calculate max allocation based on allocation_type
            if allocation.allocation_type == "percentage":
                # Use pre-calculated allocated_budget (dynamically updated)
                max_allocation = float(allocation.allocated_budget or 0)
            else:
                # Allocation is fixed amount (legacy, should not happen in new system)
                max_allocation = min(allocation.allocation_value, follower_balance)

            # Calculate copy amount based on mode
            if mode == "proportional":
                # PROPORTIONAL MODE: Calculate percentage of leader's wallet used, apply to follower's budget
                # Get leader balance from DB (cached) or API (fallback)
                balance_updater = get_leader_balance_updater()
                leader_wallet_balance = await balance_updater.get_leader_balance(
                    watched_address_id=allocation.leader_address_id,
                    use_cache=True,
                    max_age_hours=2
                )

                if leader_wallet_balance is None or leader_wallet_balance <= 0:
                    logger.warning(
                        f"⚠️ [COPY_TRADE_BUY] Cannot get leader balance for proportional calculation "
                        f"(watched_address_id={allocation.leader_address_id}). "
                        f"Falling back to min(leader_amount, max_allocation)"
                    )
                    copy_amount = min(leader_amount_float, max_allocation)
                else:
                    # Calculate what % of leader's wallet was used
                    leader_percentage = leader_amount_float / leader_wallet_balance

                    # Apply same % to follower's allocated budget
                    copy_amount = leader_percentage * max_allocation

                    logger.info(
                        f"📊 [COPY_TRADE_BUY] Proportional calculation: "
                        f"leader_trade=${leader_amount_float:.2f}, "
                        f"leader_balance=${leader_wallet_balance:.2f}, "
                        f"leader_pct={leader_percentage*100:.2f}%, "
                        f"follower_budget=${max_allocation:.2f}, "
                        f"copy_amount=${copy_amount:.2f}"
                    )
            else:
                # Fixed amount mode: always use the dedicated fixed_amount field
                if hasattr(allocation, 'fixed_amount') and allocation.fixed_amount is not None:
                    copy_amount = min(allocation.fixed_amount, follower_balance)
                else:
                    # Fallback to old behavior for backward compatibility
                    copy_amount = min(allocation.allocation_value, max_allocation)

            # Ensure we don't exceed balance
            copy_amount = min(copy_amount, follower_balance)

            # Apply minimum threshold ($1.0 for BUY)
            MIN_COPY_AMOUNT_USD = 1.0
            if copy_amount > 0 and copy_amount < MIN_COPY_AMOUNT_USD:
                logger.warning(
                    f"⏭️ [COPY_TRADE_BUY] Copy amount ${copy_amount:.2f} below minimum ${MIN_COPY_AMOUNT_USD}, "
                    f"skipping trade"
                )
                return 0.0

            return copy_amount

        except (ValueError, TypeError) as e:
            logger.error(f"❌ Error calculating copy amount: {e}")
            return 0.0

    def _is_duplicate(self, tx_id: str) -> bool:
        """Check if trade was already processed"""
        # Clean old entries
        current_time = time.time()
        self._processed_trades = {
            k: v for k, v in self._processed_trades.items()
            if current_time - v < self._deduplication_ttl
        }

        # Check if exists
        return tx_id in self._processed_trades

    def _mark_processed(self, tx_id: str) -> None:
        """Mark trade as processed"""
        self._processed_trades[tx_id] = time.time()

    async def _send_copy_trade_notification(
        self,
        user_id: int,
        allocation: CopyTradingAllocation,
        market: Dict[str, Any],
        tx_type: str,
        copy_amount: float
    ) -> None:
        """
        Send copy trade execution notification to user

        Args:
            user_id: Telegram user ID
            allocation: Copy trading allocation
            market: Market data dict
            tx_type: 'BUY' or 'SELL'
            copy_amount: USD amount copied
        """
        try:
            # Validate inputs
            if not user_id or not allocation or not market:
                logger.warning("⚠️ [COPY_TRADE_NOTIFICATION] Missing required parameters")
                return

            # Get leader address
            leader_address = None
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(WatchedAddress).where(WatchedAddress.id == allocation.leader_address_id)
                    )
                    leader = result.scalar_one_or_none()
                    leader_address = leader.address if leader else "Unknown Leader"
            except Exception as db_error:
                logger.warning(f"⚠️ [COPY_TRADE_NOTIFICATION] Could not get leader address: {db_error}")
                leader_address = "Unknown Leader"

            # Calculate potential profit (simplified - only for BUY trades)
            potential_profit = None
            if tx_type.upper() == 'BUY':
                try:
                    current_price = market.get('last_mid_price') or market.get('last_trade_price') or 0.5
                    if current_price > 0 and current_price < 1:
                        potential_profit = round(1.0 / current_price, 2)
                except Exception as calc_error:
                    logger.debug(f"⚠️ Could not calculate potential profit: {calc_error}")

            # Create notification data
            # Convert Decimal to float for JSON serialization
            amount_usd = float(copy_amount) if copy_amount else 0.0
            notification_data = {
                'leader_address': leader_address,
                'market_title': market.get('title', 'Unknown Market')[:50],  # Truncate long titles
                'side': tx_type.upper(),
                'amount_usd': round(amount_usd, 2),  # Round to 2 decimals (ensure float, not Decimal)
                'potential_profit': float(potential_profit) if potential_profit is not None else None,  # Convert Decimal to float if present
            }

            # Create and queue notification
            notification = Notification(
                user_id=user_id,
                type=NotificationType.COPY_TRADE_EXECUTED,
                priority=NotificationPriority.NORMAL,
                data=notification_data
            )

            # Get notification service and queue notification
            try:
                notification_service = get_notification_service()
                result = await notification_service.queue_notification(notification)

                if result.success:
                    logger.info(
                        f"📨 [COPY_TRADE_NOTIFICATION] Queued notification for user {user_id}: "
                        f"{tx_type.upper()} ${copy_amount:.2f} on {market.get('title', 'Unknown Market')[:30]}..."
                    )
                else:
                    logger.warning(
                        f"⚠️ [COPY_TRADE_NOTIFICATION] Failed to queue notification for user {user_id}: "
                        f"{result.error_message or 'Unknown error'}"
                    )
            except Exception as service_error:
                logger.error(f"❌ [COPY_TRADE_NOTIFICATION] Notification service error: {service_error}")

        except Exception as e:
            logger.error(f"❌ [COPY_TRADE_NOTIFICATION] Unexpected error: {e}", exc_info=True)

    def get_stats(self) -> Dict[str, Any]:
        """Get listener statistics"""
        return {
            "running": self.running,
            "processed_trades_count": len(self._processed_trades),
            "deduplication_ttl": self._deduplication_ttl,
            "metrics": self._metrics.copy(),
            "cache_size": len(self._position_resolution_cache),
            "api_fetch_failures_cache_size": len(self._api_fetch_failures),
        }


# Global instance
_copy_trading_listener: Optional[CopyTradingListener] = None


def get_copy_trading_listener() -> CopyTradingListener:
    """Get global Copy Trading Listener instance"""
    global _copy_trading_listener
    if _copy_trading_listener is None:
        _copy_trading_listener = CopyTradingListener()
    return _copy_trading_listener
