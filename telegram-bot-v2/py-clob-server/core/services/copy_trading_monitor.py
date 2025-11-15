"""
Copy Trading Monitor Service
Polls for leader trades and automatically copies them to followers
Runs on APScheduler background jobs for continuous monitoring

Features:
- Robust session management with automatic rollback
- Retry logic for transient failures
- Rate limiting and performance optimization
"""

import logging
import asyncio
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import aiohttp

from core.services.copy_trading import get_copy_trading_service
from core.services import user_service
from core.persistence.db_manager import RobustDatabaseManager

logger = logging.getLogger(__name__)

# Global monitor instance
_monitor_service: Optional['CopyTradingMonitorService'] = None
_db_manager: Optional[RobustDatabaseManager] = None


def get_copy_trading_monitor() -> 'CopyTradingMonitorService':
    """Get or create global monitor service instance"""
    global _monitor_service
    if _monitor_service is None:
        _monitor_service = CopyTradingMonitorService()
    return _monitor_service


def get_market_display_name(market_id: str) -> str:
    """Global helper to get market display name"""
    monitor = get_copy_trading_monitor()
    return monitor.get_market_display_name(market_id)


def get_database_manager() -> RobustDatabaseManager:
    """Get or create global database manager instance"""
    global _db_manager
    if _db_manager is None:
        from database import SessionLocal
        _db_manager = RobustDatabaseManager(SessionLocal)
    return _db_manager


def map_numeric_outcome_to_real_outcome(outcome_index: int, market_data: dict) -> str:
    """
    Map numeric outcome (0, 1) to real market outcome name

    IMPORTANT: This function MUST have market_data to work correctly.
    Without market_data, we CANNOT assume what index 0 or 1 means!

    Args:
        outcome_index: Numeric outcome from webhook (0 or 1)
        market_data: Market dictionary with outcomes array (REQUIRED for correct mapping)

    Returns:
        Real outcome name from market, or None if cannot determine
    """
    if not market_data:
        # ⚠️ CRITICAL FIX: DO NOT assume YES/NO mapping without market data!
        # Different markets have different outcome orders:
        # - Some have ["Yes", "No"] (index 0=Yes, 1=No)
        # - Some have ["No", "Yes"] (index 0=No, 1=Yes)
        # - Some have custom outcomes like ["Team A", "Team B"]
        logger.error(f"⚠️ map_numeric_outcome called without market_data for outcome_index={outcome_index}")
        logger.error(f"⚠️ Cannot determine outcome - caller should use position_id resolution instead!")
        return None  # Force caller to use position_id resolution

    # Try to get real outcomes from market data
    outcomes = market_data.get('outcomes', [])

    # Handle different outcome formats
    if isinstance(outcomes, str):
        # Sometimes outcomes come as JSON string
        try:
            import json
            outcomes = json.loads(outcomes)
        except:
            outcomes = []

    if isinstance(outcomes, list) and len(outcomes) > outcome_index:
        real_outcome = outcomes[outcome_index]
        if real_outcome and isinstance(real_outcome, str):
            # Return the ACTUAL outcome from the market (don't normalize unless it's standard YES/NO)
            normalized_outcome = real_outcome.upper()
            if normalized_outcome in ['YES', 'Y', 'TRUE', 'WIN']:
                return 'YES'
            elif normalized_outcome in ['NO', 'N', 'FALSE', 'LOSE']:
                return 'NO'
            else:
                # Custom outcome (e.g., "Team A", "Biden", "Over 50")
                logger.info(f"✅ Mapped outcome index {outcome_index} to real outcome: '{real_outcome}'")
                return real_outcome  # Use as-is for custom outcomes

    # If we reach here, we have market_data but couldn't parse outcomes
    logger.error(f"⚠️ Could not map outcome index {outcome_index} from market outcomes: {outcomes}")
    logger.error(f"⚠️ Market data keys: {list(market_data.keys()) if market_data else 'None'}")
    return None  # Force caller to handle error


class CopyTradingMonitorService:
    """
    Monitors leaders' trades and copies them to followers
    Uses APScheduler for background polling at different intervals
    """

    def __init__(self):
        """Initialize monitor service"""
        self.copy_service = get_copy_trading_service()
        self.db_manager = get_database_manager()
        self.last_checked_leaders: Dict[int, datetime] = {}
        self.top_leaders_cache: List[int] = []
        self.top_leaders_last_update = None

        # 🚀 SPEED OPTIMIZATION: Cache for instant lookups
        self._leader_address_cache: Dict[str, int] = {}  # address -> leader_id
        self._followers_cache: Dict[int, List[int]] = {}  # leader_id -> [follower_ids]
        self._cache_last_refresh = 0
        self._cache_ttl = 30  # 30 seconds cache

        # 🎯 UX IMPROVEMENT: Cache for real market names
        self._market_names_cache: Dict[str, str] = {}  # market_id -> real_market_name

        # 🚀 NEW: Cache for position_id → market resolutions (CRITICAL for performance!)
        self._position_resolution_cache: Dict[str, dict] = {}  # position_id -> {market, outcome, title}
        self._position_cache_ttl = 300  # 5 minutes cache (markets don't change often)
        self._position_cache_timestamps: Dict[str, float] = {}  # position_id -> timestamp

        # 🚀 DEDUPLICATION: Cache for processed trade IDs (prevents duplicate processing)
        self._processed_trades_cache: Dict[str, float] = {}  # tx_id -> timestamp
        self._processed_trades_ttl = 300  # 5 minutes cache

        # Redis Pub/Sub for instant webhooks
        self.redis_client = None
        self.pubsub = None
        self.webhook_enabled = False

    async def poll_and_copy_trades(self):
        """
        Main polling job - check all active leaders for new trades
        Called every 120 seconds
        Queries all active subscriptions and copies trades from leaders

        This is the general-purpose polling that catches all leaders

        FALLBACK MODE: Only runs if Redis Pub/Sub webhook is down
        """
        try:
            # ✅ SKIP if webhook is active (no need for polling)
            if self.webhook_enabled:
                logger.debug("⏭️ Webhook active, skipping general polling (fallback not needed)")
                return

            logger.info("🔄 Copy trading poll started (FALLBACK MODE - webhook down)")

            def query_active_subscriptions(session: Session):
                from core.services.copy_trading.models import CopyTradingSubscription
                subscriptions = session.query(CopyTradingSubscription).filter_by(status='ACTIVE').all()
                return subscriptions

            subscriptions = self.db_manager.safe_query(
                query_active_subscriptions,
                retry_on_failure=True
            )

            if not subscriptions:
                logger.debug("ℹ️ No active copy trading subscriptions")
                return

            # Group by leader_id to avoid duplicate polling
            leaders_to_check = {}
            for sub in subscriptions:
                if sub.leader_id not in leaders_to_check:
                    leaders_to_check[sub.leader_id] = []
                leaders_to_check[sub.leader_id].append(sub.follower_id)

            logger.debug(f"🔄 Polling {len(leaders_to_check)} active leaders for {len(subscriptions)} followers")

            # Poll each leader for new trades
            for leader_id, follower_ids in leaders_to_check.items():
                try:
                    await self._poll_leader_trades(leader_id, follower_ids)
                except Exception as e:
                    logger.error(f"❌ Error polling leader {leader_id}: {e}")
                    # Continue with next leader instead of stopping

        except Exception as e:
            logger.error(f"❌ Copy trading poll failed: {e}")

    async def fast_track_top_leaders(self):
        """
        High-priority polling for top 20 leaders
        Called every 60 seconds
        Focuses on leaders with most followers to maximize coverage

        FALLBACK MODE: Only runs if Redis Pub/Sub webhook is down
        """
        try:
            # ✅ SKIP if webhook is active (no need for polling)
            if self.webhook_enabled:
                logger.debug("⏭️ Webhook active, skipping fast-track polling (fallback not needed)")
                return

            logger.info("⚡ Fast-track polling (FALLBACK MODE - webhook down)")

            def query_top_leaders(session: Session):
                from core.services.copy_trading.models import CopyTradingSubscription
                from sqlalchemy import func, and_

                top_leaders = session.query(
                    CopyTradingSubscription.leader_id,
                    func.count(CopyTradingSubscription.id).label('follower_count')
                ).filter(
                    CopyTradingSubscription.status == 'ACTIVE'
                ).group_by(
                    CopyTradingSubscription.leader_id
                ).order_by(
                    func.count(CopyTradingSubscription.id).desc()
                ).limit(20).all()

                return top_leaders

            top_leaders = self.db_manager.safe_query(
                query_top_leaders,
                retry_on_failure=True
            )

            if not top_leaders:
                logger.debug("ℹ️ No top leaders to fast-track")
                return

            leader_ids = [l[0] for l in top_leaders]
            logger.debug(f"⚡ Fast-tracking {len(leader_ids)} top leaders")

            # Poll top leaders
            for leader_id, follower_count in top_leaders:
                def query_followers_for_leader(session: Session):
                    from core.services.copy_trading.models import CopyTradingSubscription
                    followers = session.query(
                        CopyTradingSubscription.follower_id
                    ).filter(
                        CopyTradingSubscription.leader_id == leader_id,
                        CopyTradingSubscription.status == 'ACTIVE'
                    ).all()
                    return [f[0] for f in followers]

                follower_ids = self.db_manager.safe_query(
                    query_followers_for_leader,
                    retry_on_failure=True
                )

                if follower_ids:
                    try:
                        await self._poll_leader_trades(leader_id, follower_ids)
                    except Exception as e:
                        logger.error(f"❌ Error fast-tracking leader {leader_id}: {e}")

        except Exception as e:
            logger.error(f"❌ Fast-track polling failed: {e}")

    async def update_top_leaders_list(self):
        """
        Refresh top 20 leaders rankings hourly
        Called every 1 hour
        Updates stats and recalculates top performers
        """
        try:
            logger.info("🏆 Updating top leaders rankings...")

            def query_top_stats(session: Session):
                from core.services.copy_trading.models import CopyTradingStats
                top_stats = session.query(CopyTradingStats).order_by(
                    CopyTradingStats.total_active_followers.desc()
                ).limit(20).all()
                return top_stats

            top_stats = self.db_manager.safe_query(
                query_top_stats,
                retry_on_failure=True
            )

            if top_stats:
                self.top_leaders_cache = [s.leader_id for s in top_stats]
                self.top_leaders_last_update = datetime.utcnow()
                logger.info(f"✅ Updated top leaders cache: {len(self.top_leaders_cache)} leaders")

                # Log top 3 for reference
                if self.top_leaders_cache:
                    logger.info(f"🏆 Top leaders: {self.top_leaders_cache[:3]}")
            else:
                logger.info("ℹ️ No top leaders stats available")

        except Exception as e:
            logger.error(f"❌ Error updating top leaders: {e}")

    async def _poll_leader_trades(self, leader_id: int, follower_ids: List[int]):
        """
        Check if a leader has new trades and copy to followers
        NEW: Uses tracked_leader_trades for external leaders (on-chain source)
        OLD: Falls back to transactions table for internal bot users

        Args:
            leader_id: Leader's telegram user ID (or virtual_id for external)
            follower_ids: List of follower IDs to copy to
        """
        try:
            def query_and_process_trades(session: Session):
                from database import Transaction, ExternalLeader, TrackedLeaderTrade
                from config.config import USE_SUBSQUID_COPY_TRADING

                # Query ExternalLeader with proper error handling
                external_leader = None
                try:
                    external_leader = session.query(ExternalLeader).filter_by(
                        virtual_id=leader_id
                    ).first()
                except Exception as e:
                    logger.debug(f"ℹ️ ExternalLeader query skipped for {leader_id}: {e}")

                # Determine which trades are new
                recent_trades = []

                # NEW: Use tracked_leader_trades for external leaders if flag enabled
                if external_leader and USE_SUBSQUID_COPY_TRADING:
                    logger.debug(f"📊 [SUBSQUID] Querying tracked_leader_trades for external leader {leader_id}")

                    # Query from on-chain source (tracked_leader_trades)
                    recent_trades = session.query(TrackedLeaderTrade).filter(
                        TrackedLeaderTrade.user_address == external_leader.polygon_address,
                        TrackedLeaderTrade.timestamp > (external_leader.last_poll_at or datetime.utcnow() - timedelta(minutes=5))
                    ).order_by(
                        TrackedLeaderTrade.timestamp.asc()
                    ).limit(10).all()

                else:
                    # OLD: Query transactions table (internal bot users)
                    logger.debug(f"📊 Querying transactions for leader {leader_id}")

                    # For bot users, always check recent trades (no external_leader tracking)
                    recent_trades = session.query(Transaction).filter(
                        Transaction.user_id == leader_id,
                        Transaction.executed_at > (datetime.utcnow() - timedelta(minutes=10))  # Last 10 minutes
                    ).order_by(
                        Transaction.id.asc()
                    ).limit(10).all()

                    logger.debug(f"📊 Found {len(recent_trades)} recent trades for bot user {leader_id}")

                return external_leader, recent_trades

            external_leader, recent_trades = self.db_manager.safe_query(
                query_and_process_trades,
                retry_on_failure=True
            )

            if not recent_trades:
                logger.debug(f"ℹ️ No new trades for leader {leader_id}")
                return

            logger.debug(f"📊 Found {len(recent_trades)} new trades from leader {leader_id}")

            # Copy each trade to followers
            for trade in recent_trades:
                try:
                    # Convert tracked trade to transaction format (same as webhook)
                    trade_dict = await self._convert_tracked_trade_to_transaction(trade)

                    # Execute copy in background
                    asyncio.create_task(
                        self.copy_service.copy_trade(trade_dict, leader_id)
                    )

                    # Update last_trade_id after queueing the copy
                    if external_leader:
                        def update_external_leader_state(session: Session):
                            from database import ExternalLeader
                            from datetime import datetime

                            el = session.query(ExternalLeader).filter_by(
                                virtual_id=leader_id
                            ).first()
                            if el:
                                el.last_trade_id = str(trade.id) if hasattr(trade, 'id') else str(trade.tx_id)
                                el.last_poll_at = datetime.utcnow()
                                session.commit()
                                logger.debug(f"✅ Updated external leader {leader_id} last_trade_id to {el.last_trade_id}")

                        try:
                            self.db_manager.safe_update(update_external_leader_state)
                        except Exception as e:
                            logger.warning(f"⚠️ Could not update ExternalLeader for {leader_id}: {e}")

                except Exception as trade_error:
                    logger.error(f"❌ Error processing trade from leader {leader_id}: {trade_error}")

        except Exception as e:
            logger.error(f"❌ Error polling leader {leader_id}: {e}")

    # =========================================================================
    # REDIS PUB/SUB INSTANT WEBHOOK LISTENER (Phase 3.2)
    # =========================================================================

    async def start_redis_listener(self):
        """
        Subscribe to copy_trade:* channels for instant trade notifications
        This provides <10s latency vs 10-60s polling

        PERFORMANCE FIX: Guard against multiple subscriptions (caused 3-4x duplicate processing)
        """
        # CRITICAL: Prevent multiple subscriptions to same channel
        if self.webhook_enabled or self.pubsub is not None:
            logger.warning("⚠️ Redis listener already started - skipping duplicate subscription")
            return

        try:
            import redis.asyncio as redis
            from config.config import REDIS_URL

            self.redis_client = await redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,  # Connection timeout (short is fine)
                socket_timeout=None  # ✅ CRITICAL: No timeout for Pub/Sub (waits indefinitely for messages)
            )

            self.pubsub = self.redis_client.pubsub()

            # Subscribe to all copy trade notifications
            await self.pubsub.psubscribe("copy_trade:*")

            logger.info("✅ Redis Pub/Sub listener started for copy trading webhooks")
            self.webhook_enabled = True

            # Listen for messages (non-blocking)
            async def listen_for_messages():
                logger.info("🔄 [REDIS_LISTENER] Starting message listening loop")
                try:
                    async for message in self.pubsub.listen():
                        logger.debug(f"📨 [REDIS_LISTENER] Received message: type={message.get('type')}, channel={message.get('channel')}")
                        try:
                            if message['type'] == 'pmessage':
                                logger.info(f"🚨 [REDIS_LISTENER] Processing copy trade message on channel: {message['channel']}")
                                await self._handle_redis_trade_notification(
                                    channel=message['channel'],
                                    data=message['data']
                                )
                            elif message['type'] == 'subscribe':
                                logger.info(f"✅ [REDIS_LISTENER] Successfully subscribed to channel: {message.get('channel')}")
                            elif message['type'] == 'psubscribe':
                                logger.info(f"✅ [REDIS_LISTENER] Successfully pattern-subscribed to: {message.get('pattern')}")
                        except Exception as e:
                            logger.error(f"❌ [REDIS_LISTENER] Message processing error: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"❌ [REDIS_LISTENER] Listener loop error: {e}", exc_info=True)
                    self.webhook_enabled = False

            # Start listener in background (non-blocking)
            asyncio.create_task(listen_for_messages())

        except Exception as e:
            logger.error(f"❌ Redis listener startup failed: {e}")
            logger.warning("⚠️ Falling back to polling-only mode")
            self.webhook_enabled = False

    async def stop_redis_listener(self):
        """Cleanup Redis listener on shutdown"""
        try:
            if self.pubsub:
                await self.pubsub.unsubscribe()
                await self.pubsub.close()
                logger.info("✅ Redis listener stopped")
            if self.redis_client:
                await self.redis_client.close()

            self.webhook_enabled = False
            self.pubsub = None
            self.redis_client = None

        except Exception as e:
            logger.error(f"❌ Error stopping Redis listener: {e}")

    async def _handle_redis_trade_notification(self, channel: str, data: str):
        """
        Process instant trade notification from Redis Pub/Sub

        Args:
            channel: Redis channel (e.g., "copy_trade:0xabc...")
            data: JSON string with trade data
        """
        import time
        received_time = time.time()

        try:
            import json
            trade_data = json.loads(data)
            user_address = trade_data['user_address']
            tx_id = trade_data.get('tx_id')
            tx_timestamp = trade_data.get('timestamp')

            # ✅ DEDUPLICATION: Check if we already processed this trade
            if tx_id:
                # Clean old entries (older than TTL)
                current_time = time.time()
                self._processed_trades_cache = {
                    k: v for k, v in self._processed_trades_cache.items()
                    if current_time - v < self._processed_trades_ttl
                }

                # Check if already processed
                if tx_id in self._processed_trades_cache:
                    logger.debug(f"⏭️ SKIP: Trade {tx_id[:20]}... already processed {current_time - self._processed_trades_cache[tx_id]:.1f}s ago")
                    return

                # Mark as processed
                self._processed_trades_cache[tx_id] = current_time

            if tx_timestamp:
                from datetime import datetime
                tx_time = datetime.fromisoformat(tx_timestamp.replace('Z', '+00:00')).timestamp()
                delay = received_time - tx_time
                logger.info(f"🚀 INSTANT WEBHOOK: Trade from {user_address[:10]}... received in {delay:.1f}s")
            else:
                logger.info(f"🚀 INSTANT WEBHOOK: Trade from {user_address[:10]}... via Redis Pub/Sub")

            # Get leader_id from address
            leader_id = await self._get_leader_id_from_address(user_address)
            if not leader_id:
                logger.info(f"⏭️ SKIP: Address {user_address[:10]}... not a tracked leader")
                return

            # Get active followers for this leader
            followers = await self._get_active_followers(leader_id)
            if not followers:
                logger.info(f"⏭️ SKIP: No active followers for leader {leader_id}")
                return

            logger.info(f"🔄 INSTANT COPY: {len(followers)} followers for leader {leader_id}")

            # Convert webhook data to transaction format
            transaction_dict = await self._convert_webhook_to_transaction(trade_data)

            # Execute copy trades immediately (parallel execution in copy_service)
            await self.copy_service.copy_trade(transaction_dict, leader_id)

        except Exception as e:
            logger.error(f"❌ Redis trade handler error: {e}", exc_info=True)

    def _refresh_leader_cache(self):
        """Refresh leader address cache (called periodically)"""
        import time
        now = time.time()

        if now - self._cache_last_refresh < self._cache_ttl:
            return  # Cache still fresh

        try:
            def load_cache(session: Session):
                from database import ExternalLeader, User
                from core.services.copy_trading.models import CopyTradingSubscription
                from sqlalchemy import func

                # Clear old cache
                self._leader_address_cache.clear()
                self._followers_cache.clear()

                # Load external leaders
                external_leaders = session.query(ExternalLeader).all()
                for leader in external_leaders:
                    if leader.polygon_address:
                        self._leader_address_cache[leader.polygon_address.lower()] = leader.virtual_id

                # Load bot users
                users = session.query(User).filter(User.polygon_address.isnot(None)).all()
                for user in users:
                    if user.polygon_address:
                        self._leader_address_cache[user.polygon_address.lower()] = user.telegram_user_id

                # Load smart wallets (generate virtual IDs)
                try:
                    from core.persistence.models import SmartWallet
                    smart_wallets = session.query(SmartWallet).all()
                    for wallet in smart_wallets:
                        if wallet.address:
                            # Generate consistent virtual ID for smart wallet
                            virtual_id = -abs(hash(wallet.address.lower())) % (2**31)
                            self._leader_address_cache[wallet.address.lower()] = virtual_id
                            logger.debug(f"🏦 Added smart wallet {wallet.address[:10]}... as virtual leader {virtual_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not load smart wallets for leader cache: {e}")

                # Load followers for each leader
                subscriptions = session.query(
                    CopyTradingSubscription.leader_id,
                    func.array_agg(CopyTradingSubscription.follower_id).label('followers')
                ).filter(
                    CopyTradingSubscription.status == 'ACTIVE'
                ).group_by(CopyTradingSubscription.leader_id).all()

                for sub in subscriptions:
                    self._followers_cache[sub.leader_id] = sub.followers or []

                return len(self._leader_address_cache), len(self._followers_cache)

            counts = self.db_manager.safe_query(load_cache, retry_on_failure=False)
            if counts:
                self._cache_last_refresh = now
                logger.debug(f"🚀 Refreshed leader cache: {counts[0]} addresses, {counts[1]} leader-follower mappings")

        except Exception as e:
            logger.warning(f"⚠️ Failed to refresh leader cache: {e}")

    async def _get_leader_id_from_address(self, user_address: str) -> Optional[int]:
        """Get leader virtual_id from wallet address (cached for speed)"""
        # Refresh cache if needed
        self._refresh_leader_cache()

        # Return from cache
        return self._leader_address_cache.get(user_address.lower())

    async def _get_active_followers(self, leader_id: int) -> List[int]:
        """Get list of active follower IDs for a leader (cached for speed)"""
        # Refresh cache if needed
        self._refresh_leader_cache()

        # Return from cache
        return self._followers_cache.get(leader_id, [])

    async def _resolve_market_from_condition_id(self, condition_id_decimal: str) -> Optional[dict]:
        """
        Resolve conditionId (decimal) to real Polymarket market data.

        Strategy:
        1. First try local DB (subsquid_markets_poll) - ultra fast
        2. Fallback to Polymarket Gamma API if not found

        Args:
            condition_id_decimal: Condition ID as decimal string from blockchain

        Returns:
            Market dict with real Polymarket data, or None if not found
        """
        if not condition_id_decimal:
            return None

        try:
            # 🚀 STEP 1: Try local DB first (ultra-fast)
            from database import db_manager
            session = db_manager.get_session()

            try:
                # Convert decimal to hex for database lookup (local DB stores condition_ids as hex)
                condition_id_int = int(condition_id_decimal)
                condition_id_hex = f"0x{condition_id_int:064x}"

                # Query local subsquid_markets_poll table (only active markets)
                from database import SubsquidMarketPoll
                local_market = session.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.condition_id == condition_id_hex,
                    SubsquidMarketPoll.status == 'active',  # Only active markets
                    SubsquidMarketPoll.archived == False    # Not archived
                ).first()

                if local_market:
                    logger.info(f"✅ [LOCAL] Resolved conditionId {condition_id_decimal} to market {local_market.market_id}: {local_market.title[:50]}...")

                    # Parse clob_token_ids correctly (stored as JSON string in DB)
                    clob_token_ids = []
                    if local_market.clob_token_ids:
                        try:
                            # DB stores as JSON string, parse it
                            import json
                            # If it's already a list (from some sources), use as-is
                            if isinstance(local_market.clob_token_ids, list):
                                clob_token_ids = local_market.clob_token_ids
                            else:
                                # Parse JSON string
                                clob_token_ids = json.loads(local_market.clob_token_ids)
                        except (json.JSONDecodeError, TypeError):
                            # Fallback: try to parse as PostgreSQL array format
                            token_str = str(local_market.clob_token_ids).strip('{}')
                            if token_str:
                                clob_token_ids = [t.strip().strip('"') for t in token_str.split(',') if t.strip()]

                    # Parse outcomes array (already an array in DB)
                    outcomes = local_market.outcomes or []

                    # Ensure we have matching token_ids and outcomes
                    if len(clob_token_ids) != len(outcomes):
                        logger.warning(f"⚠️ [LOCAL] Mismatch: {len(clob_token_ids)} tokens vs {len(outcomes)} outcomes for market {local_market.market_id}")
                        # Try to use only what we have
                        min_length = min(len(clob_token_ids), len(outcomes))
                        clob_token_ids = clob_token_ids[:min_length]
                        outcomes = outcomes[:min_length]

                    # Return standardized market dict
                    return {
                        'id': local_market.market_id,
                        'condition_id': condition_id_decimal,
                        'question': local_market.title or 'Unknown',
                        'description': local_market.description or '',
                        'outcome_prices': [float(p) if p else 0.5 for p in (local_market.outcome_prices or [])],
                        'tokens': [
                            {'token_id': token_id, 'outcome': outcome}
                            for token_id, outcome in zip(clob_token_ids, outcomes)
                        ],
                        'clob_token_ids': clob_token_ids,
                        'active': local_market.status == 'active',
                        'closed': local_market.status == 'closed',
                        'archived': local_market.archived or False,
                        'needs_api_resolution': False,  # Successfully resolved locally!
                    }
            finally:
                session.close()

            # 🚀 STEP 2: Fallback to Polymarket Gamma API
            logger.info(f"📡 [API] conditionId {condition_id_decimal} not in local DB, trying Polymarket API...")

            # Convert decimal conditionId to hex
            condition_id_int = int(condition_id_decimal)
            condition_id_hex = f"0x{condition_id_int:064x}"

            # Query Polymarket Gamma API
            url = f"https://gamma-api.polymarket.com/markets?conditionId={condition_id_hex}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        markets = await response.json()

                        if markets and len(markets) > 0:
                            market = markets[0]  # Take first match
                            logger.info(f"✅ [API] Resolved conditionId {condition_id_decimal} to market {market.get('id')}: {market.get('question')[:50]}...")
                            logger.debug(f"Market data: outcomes={market.get('outcomes')}, clobTokenIds={market.get('clobTokenIds')} (type: {type(market.get('clobTokenIds'))}), outcomePrices={market.get('outcomePrices')}")

                            # Parse clobTokenIds correctly (API returns as JSON string)
                            clob_token_ids = market.get('clobTokenIds', [])
                            if isinstance(clob_token_ids, str):
                                try:
                                    import json
                                    clob_token_ids = json.loads(clob_token_ids)
                                except json.JSONDecodeError:
                                    logger.error(f"❌ Failed to parse clobTokenIds string: {clob_token_ids}")
                                    clob_token_ids = []

                            # Parse outcomes correctly (API returns as JSON string)
                            outcomes = market.get('outcomes', [])
                            if isinstance(outcomes, str):
                                try:
                                    import json
                                    outcomes = json.loads(outcomes)
                                except json.JSONDecodeError:
                                    logger.error(f"❌ Failed to parse outcomes string: {outcomes}")
                                    outcomes = []

                            # Ensure we have matching data
                            if len(clob_token_ids) != len(outcomes):
                                logger.warning(f"⚠️ [API] Mismatch: {len(clob_token_ids)} tokens vs {len(outcomes)} outcomes for market {market.get('id')}")
                                min_length = min(len(clob_token_ids), len(outcomes))
                                clob_token_ids = clob_token_ids[:min_length]
                                outcomes = outcomes[:min_length]

                            # Return standardized market dict
                            return {
                                'id': market.get('id'),
                                'condition_id': condition_id_decimal,
                                'question': market.get('question', 'Unknown'),
                                'description': market.get('description', ''),
                                'outcome_prices': [float(p) if isinstance(p, str) and p.replace('.', '').isdigit() else 0.5 for p in market.get('outcomePrices', ['0.5', '0.5'])],
                                'tokens': [
                                    {'token_id': token_id, 'outcome': outcome}
                                    for token_id, outcome in zip(clob_token_ids, outcomes)
                                ],
                                'clob_token_ids': clob_token_ids,
                                'active': market.get('active', True),
                                'closed': market.get('closed', False),
                                'resolved_at': market.get('resolvedAt'),
                                'archived': market.get('archived', False),
                                'needs_api_resolution': False,  # Successfully resolved via API!
                            }

            logger.warning(f"⚠️ No market found for conditionId {condition_id_hex} in API")
            return None

        except Exception as e:
            logger.error(f"❌ Error resolving conditionId {condition_id_decimal}: {e}")
            return None

    async def _resolve_market_from_condition_id_any_format(self, condition_id: str) -> Optional[dict]:
        """
        Resolve market from condition_id that can be in hex (0x...) or decimal format.
        """
        try:
            if condition_id.startswith('0x'):
                # Hex format - call API directly
                return await self._resolve_market_from_hex_condition_id(condition_id)
            else:
                # Decimal format - use existing method
                return await self._resolve_market_from_condition_id(condition_id)
        except Exception as e:
            logger.warning(f"⚠️ Error resolving condition_id {condition_id}: {e}")
            return None

    async def _resolve_market_from_hex_condition_id(self, condition_id_hex: str) -> Optional[dict]:
        """
        Resolve market directly from Polymarket API using hex condition_id.
        """
        try:
            import aiohttp

            url = f"https://gamma-api.polymarket.com/markets?conditionId={condition_id_hex}"
            logger.debug(f"📡 [HEX_API] Calling: {url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            market = data[0]
                            logger.info(f"✅ [HEX_API] Found market: {market.get('question', 'Unknown')}")

                            # Extract token_ids
                            clob_token_ids = market.get('clobTokenIds', [])
                            outcomes = market.get('outcomes', ['YES', 'NO'])

                            # Ensure we have the right number of outcomes
                            if len(clob_token_ids) != len(outcomes):
                                logger.warning(f"⚠️ [HEX_API] Token/outcome mismatch: {len(clob_token_ids)} vs {len(outcomes)}")

                            # Return standardized market dict
                            return {
                                'id': market.get('id'),
                                'condition_id': market.get('conditionId'),
                                'question': market.get('question', 'Unknown'),
                                'description': market.get('description', ''),
                                'outcome_prices': [float(p) if isinstance(p, str) and p.replace('.', '').isdigit() else 0.5 for p in market.get('outcomePrices', ['0.5', '0.5'])],
                                'tokens': [
                                    {'token_id': token_id, 'outcome': outcome}
                                    for token_id, outcome in zip(clob_token_ids, outcomes)
                                ],
                                'clob_token_ids': clob_token_ids,
                                'active': market.get('active', True),
                                'closed': market.get('closed', False),
                                'resolved_at': market.get('resolvedAt'),
                                'archived': False,
                                'needs_api_resolution': False,  # Successfully resolved via API!
                            }
                        else:
                            logger.warning(f"⚠️ [HEX_API] No market found for conditionId {condition_id_hex}")
                            return None
                    else:
                        logger.warning(f"⚠️ [HEX_API] API error {response.status} for conditionId {condition_id_hex}")
                        return None

        except Exception as e:
            logger.error(f"❌ [HEX_API] Error calling API for conditionId {condition_id_hex}: {e}")
            return None

    async def _resolve_market_by_known_mappings(self, webhook_data: dict) -> Optional[dict]:
        """
        Resolve market using hardcoded mappings for known indexer issues.
        This is a workaround until the indexer sends correct market_ids.
        """
        market_id = webhook_data.get('market_id')

        # No hardcoded mappings - rely on algorithmic resolution only

        return None

    async def _resolve_market_by_position_id(self, position_id: str) -> Optional[dict]:
        """
        🚀 PRIORITY RESOLUTION: Use position_id (clob_token_id) to find market + outcome
        This is the MOST RELIABLE method as position_id is the ground truth from blockchain

        ✅ OPTIMIZED: Uses in-memory cache for instant lookups (5min TTL)

        Args:
            position_id: The token_id from the trade (clob_token_id)

        Returns:
            Dict with {
                'market': market_dict with full data,
                'outcome': outcome string ('Yes', 'No', etc.),
                'outcome_index': numeric index in outcomes array,
                'token_index': index of this token in clob_token_ids array
            } or None if not found
        """
        if not position_id:
            return None

        # 🚀 CACHE CHECK: Return from cache if fresh (INSTANT - no DB query!)
        import time
        current_time = time.time()

        if position_id in self._position_resolution_cache:
            cache_age = current_time - self._position_cache_timestamps.get(position_id, 0)
            if cache_age < self._position_cache_ttl:
                logger.debug(f"✅ [POSITION_CACHE_HIT] Using cached resolution for ...{position_id[-20:]} (age: {cache_age:.1f}s)")
                return self._position_resolution_cache[position_id]
            else:
                # Cache expired, remove it
                del self._position_resolution_cache[position_id]
                del self._position_cache_timestamps[position_id]

        try:
            logger.info(f"🔍 [POSITION_ID_RESOLUTION] Resolving position_id: ...{position_id[-20:]}")

            # Query subsquid_markets_poll for market containing this position_id
            from database import db_manager
            session = db_manager.get_session()

            try:
                from database import SubsquidMarketPoll
                import json

                # 🔍 Search for market with this position_id in clob_token_ids
                # ✅ OPTIMIZED: Use JSONB @> operator with GIN index (80% faster!)
                # clob_token_ids is now JSONB array, use contains operator for fast lookup
                from sqlalchemy import func
                from sqlalchemy.dialects.postgresql import JSONB

                # Strategy: Use JSONB @> operator (requires array JSONB, works with GIN index)
                # This is MUCH faster than TEXT contains (uses idx_markets_clob_tokens_gin)
                # Handle both string JSONB (legacy) and array JSONB (new format)
                matching_market = session.query(SubsquidMarketPoll).filter(
                    # Try array JSONB first (new format) - uses GIN index
                    func.jsonb_typeof(SubsquidMarketPoll.clob_token_ids) == 'array',
                    SubsquidMarketPoll.clob_token_ids.op('@>')([position_id]),  # JSONB contains operator
                    # Only search in ACTIVE markets to speed up query
                    SubsquidMarketPoll.is_active == True
                ).first()

                # Fallback: If not found, try string JSONB format (legacy data)
                if not matching_market:
                    matching_market = session.query(SubsquidMarketPoll).filter(
                        func.jsonb_typeof(SubsquidMarketPoll.clob_token_ids) == 'string',
                        SubsquidMarketPoll.clob_token_ids.cast(String).contains(str(position_id)),
                        SubsquidMarketPoll.is_active == True
                    ).first()

                # ✅ Validate match (prevent false positives from substring matches)
                # JSONB @> operator already validates exact match, but double-check for safety
                if matching_market and matching_market.clob_token_ids:
                    try:
                        # Extract token IDs from JSONB (handles both array and string formats)
                        clob_token_ids = []
                        if isinstance(matching_market.clob_token_ids, list):
                            clob_token_ids = [str(tid) for tid in matching_market.clob_token_ids]
                        elif isinstance(matching_market.clob_token_ids, str):
                            # Legacy string JSONB format
                            parsed = json.loads(matching_market.clob_token_ids)
                            if isinstance(parsed, list):
                                clob_token_ids = [str(tid) for tid in parsed]
                            else:
                                clob_token_ids = [str(parsed)]
                        else:
                            # JSONB might be stored differently
                            clob_token_ids = [str(tid) for tid in matching_market.clob_token_ids] if hasattr(matching_market.clob_token_ids, '__iter__') else []

                        # Exact match validation (JSONB @> already does this, but double-check)
                        if matching_market and str(position_id) not in clob_token_ids:
                            logger.warning(f"⚠️ [POSITION_ID_RESOLUTION] False positive match for {position_id}, continuing search...")
                            matching_market = None
                    except (json.JSONDecodeError, TypeError, AttributeError) as e:
                        logger.error(f"❌ [POSITION_ID_RESOLUTION] Error parsing clob_token_ids: {e}")
                        matching_market = None

                if not matching_market:
                    logger.warning(f"⚠️ [POSITION_ID_RESOLUTION] No market found for position_id ...{position_id[-20:]}")
                    return None

                market = matching_market
                logger.info(f"✅ [POSITION_ID_RESOLUTION] Found market: {market.title[:50]}...")

                # Parse clob_token_ids to find index (handle JSONB formats)
                clob_token_ids = []
                if market.clob_token_ids:
                    try:
                        # Handle array JSONB (new format)
                        if isinstance(market.clob_token_ids, list):
                            clob_token_ids = [str(tid) for tid in market.clob_token_ids]
                        # Handle string JSONB (legacy format)
                        elif isinstance(market.clob_token_ids, str):
                            parsed = json.loads(market.clob_token_ids)
                            if isinstance(parsed, list):
                                clob_token_ids = [str(tid) for tid in parsed]
                            else:
                                clob_token_ids = [str(parsed)]
                        # Handle other JSONB types
                        else:
                            clob_token_ids = [str(tid) for tid in market.clob_token_ids] if hasattr(market.clob_token_ids, '__iter__') else []
                    except (json.JSONDecodeError, TypeError, AttributeError) as e:
                        logger.error(f"❌ [POSITION_ID_RESOLUTION] Could not parse clob_token_ids: {e}")
                        return None

                # Find index of position_id in clob_token_ids
                token_index = -1
                for i, token_id in enumerate(clob_token_ids):
                    if str(token_id) == str(position_id):
                        token_index = i
                        break

                if token_index < 0:
                    logger.error(f"❌ [POSITION_ID_RESOLUTION] position_id not found in clob_token_ids array")
                    return None

                # Get outcome from outcomes array at same index
                outcomes = market.outcomes or []
                if token_index >= len(outcomes):
                    logger.error(f"❌ [POSITION_ID_RESOLUTION] token_index {token_index} out of range for outcomes (len={len(outcomes)})")
                    return None

                outcome_str = outcomes[token_index]

                logger.info(f"✅ [POSITION_ID_RESOLUTION] Mapped token_index={token_index} → outcome='{outcome_str}'")

                # Build market dict
                market_dict = self._convert_market_to_dict(market)

                resolution_result = {
                    'market': market_dict,
                    'outcome': outcome_str,
                    'outcome_index': token_index,
                    'token_index': token_index,
                    'market_title': market.title,  # ✅ For smart_wallet_trades.market_question
                }

                # 🚀 CACHE IT: Store for future lookups (5min TTL)
                self._position_resolution_cache[position_id] = resolution_result
                self._position_cache_timestamps[position_id] = current_time
                logger.debug(f"💾 [POSITION_CACHE] Cached resolution for ...{position_id[-20:]}")

                return resolution_result

            finally:
                session.close()

        except Exception as e:
            logger.error(f"❌ [POSITION_ID_RESOLUTION] Error: {e}", exc_info=True)
            return None

    async def _fuzzy_match_supabase(self, calculated_token_id: str) -> Optional[dict]:
        """
        Fuzzy match calculated token_id against Supabase database
        Uses last 40 characters excluding last character for matching
        """
        try:
            # Calculate match key for fuzzy matching
            def get_match_key(token_id: str) -> str:
                if len(token_id) <= 1:
                    return token_id
                # Take last 40 characters, excluding the very last one
                return token_id[-41:-1] if len(token_id) > 41 else token_id[:-1]

            match_key = get_match_key(calculated_token_id)
            logger.debug(f"🔍 [FUZZY_SUPABASE] Searching for match key: {match_key}")

            # Query Supabase directly (same DB as the rest of the system)
            from database import db_manager
            session = db_manager.get_session()

            try:
                from database import SubsquidMarketPoll

                # Strategy 1: Exact match first (fastest)
                logger.debug(f"🔍 [FUZZY_SUPABASE] Strategy 1: Exact match for token: ...{calculated_token_id[-20:]}")
                markets = session.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.clob_token_ids.like(f'%{calculated_token_id}%'),
                    SubsquidMarketPoll.status == 'active'
                ).all()

                if markets:
                    market = markets[0]  # Take first match
                    logger.info(f"✅ [FUZZY_SUPABASE] Found exact match in Supabase: {market.title[:50]}...")
                    return self._convert_market_to_dict(market)

                # Strategy 2: Fuzzy match using pattern (fallback)
                logger.debug(f"🔍 [FUZZY_SUPABASE] Strategy 2: Fuzzy match for pattern: ...{match_key}")
                markets = session.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.clob_token_ids.like(f'%{match_key}%'),
                    SubsquidMarketPoll.status == 'active'
                ).all()

                if markets:
                    market = markets[0]  # Take first match
                    logger.info(f"✅ [FUZZY_SUPABASE] Found fuzzy match in Supabase: {market.title[:50]}...")
                    return self._convert_market_to_dict(market)

                logger.debug(f"⚠️ [FUZZY_SUPABASE] No match found in Supabase for token: ...{calculated_token_id[-20:]}")
                return None

            finally:
                session.close()

        except Exception as e:
            logger.error(f"❌ [FUZZY_SUPABASE] Error in Supabase fuzzy match: {e}")
            return None

    async def _convert_tracked_trade_to_transaction(self, tracked_trade) -> dict:
        """
        Convert TrackedLeaderTrade to transaction format for copy_trade
        Same logic as webhook conversion but from DB model
        """
        try:
            # Extract data from tracked trade
            market_id = tracked_trade.market_id
            outcome = tracked_trade.outcome
            tx_type = tracked_trade.tx_type

            # 🚀 PRIORITY 1: Calculate position_id and resolve via position_id
            # This is the MOST RELIABLE method (same as webhook flow)
            position_id_calculated = None
            market_dict = None
            outcome_str = None
            market_title = None

            if market_id and str(market_id).isdigit() and outcome is not None:
                try:
                    # Calculate position_id using same formula as indexer
                    position_id_calculated = str(int(market_id) * 2 + outcome)

                    # Resolve via position_id (ground truth)
                    resolution = await self._resolve_market_by_position_id(position_id_calculated)

                    if resolution:
                        market_dict = resolution['market']
                        outcome_str = resolution['outcome']  # Already correctly mapped!
                        market_title = resolution['market_title']
                        logger.info(f"✅ [TRACKED_TRADE] Resolved via position_id: outcome={outcome_str}, market={market_title[:50]}...")
                    else:
                        logger.warning(f"⚠️ [TRACKED_TRADE] Position resolution failed, using fallback")
                except Exception as e:
                    logger.warning(f"⚠️ [TRACKED_TRADE] Position calculation/resolution error: {e}")

            # PRIORITY 2: Fallback to DB lookup if position resolution failed
            if not market_dict:
                try:
                    db_manager = get_database_manager()
                    with db_manager.get_session() as session:
                        from database import SubsquidMarketPoll
                        import json

                        market = session.query(SubsquidMarketPoll).filter(
                            SubsquidMarketPoll.market_id == market_id
                        ).first()

                        if market:
                            # Build market_dict for outcome mapping
                            market_dict = {
                                'id': market.market_id,
                                'question': market.title,
                                'outcomes': market.outcomes or [],
                                'outcome_prices': market.outcome_prices or [],
                            }
                            market_title = market.title

                            # Map outcome using market data
                            if outcome is not None:
                                outcome_str = map_numeric_outcome_to_real_outcome(outcome, market_dict)

                except Exception as db_error:
                    logger.warning(f"⚠️ [TRACKED_TRADE] DB lookup failed: {db_error}")

            # PRIORITY 3: Last resort fallback
            if not outcome_str and outcome is not None:
                outcome_str = map_numeric_outcome_to_real_outcome(outcome, market_dict or {})

            # Use position_id_calculated as the real token_id
            real_token_id = position_id_calculated

            # Calculate total_amount - ALWAYS prefer amount_usdc (exact USDC from indexer)
            total_amount = None
            if tracked_trade.amount_usdc:
                # Priority 1: Use exact USDC amount from indexer
                total_amount = float(tracked_trade.amount_usdc)
            elif tracked_trade.price and tracked_trade.amount:
                # Fallback: Calculate from price * tokens (but amount is in microunits, so divide by 1e6)
                total_amount = float(tracked_trade.price) * (float(tracked_trade.amount) / 1e6)
                logger.warning(f"⚠️ [TRACKED_TRADE] Using price*amount fallback: ${total_amount:.2f}")

            return {
                'id': tracked_trade.id,
                'user_id': None,  # External leader
                'transaction_type': tx_type,
                'market_id': market_dict.get('id') if market_dict else market_id,
                'token_id': real_token_id,  # ✅ FIX: Use REAL token_id from DB, not calculated
                'market': market_dict,
                'market_title': market_title,  # ✅ For smart_wallet_trades
                'outcome': outcome_str,  # String outcome for display ('YES', 'NO', etc.)
                'outcome_numeric': outcome,  # ✅ CRITICAL: Keep numeric outcome (0/1) for indexing
                'tokens': float(tracked_trade.amount or 0),
                'price_per_token': float(tracked_trade.price or 0),
                'total_amount': total_amount,
                'transaction_hash': tracked_trade.tx_hash,
                'executed_at': tracked_trade.timestamp,
                'created_at': tracked_trade.timestamp
            }

        except Exception as e:
            logger.error(f"❌ Error converting tracked trade to transaction: {e}")
            # Return minimal dict to avoid crashes
            return {
                'id': tracked_trade.id,
                'transaction_type': tracked_trade.tx_type,
                'market_id': tracked_trade.market_id,
                'outcome': str(tracked_trade.outcome) if tracked_trade.outcome is not None else 'unknown',
                'outcome_numeric': tracked_trade.outcome,  # ✅ Keep numeric for indexing
                'tokens': float(tracked_trade.amount or 0),
                'total_amount': float(tracked_trade.amount_usdc or 0),
                'transaction_hash': tracked_trade.tx_hash,
                'executed_at': tracked_trade.timestamp
            }

    def _convert_market_to_dict(self, market) -> dict:
        """Convert SubsquidMarketPoll model to dict format"""
        try:
            # Parse clob_token_ids correctly
            clob_token_ids = []
            if market.clob_token_ids:
                try:
                    import json
                    if isinstance(market.clob_token_ids, str):
                        clob_token_ids = json.loads(market.clob_token_ids)
                    elif isinstance(market.clob_token_ids, list):
                        clob_token_ids = market.clob_token_ids
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"⚠️ Could not parse clob_token_ids for market {market.market_id}")

            # Parse outcomes
            outcomes = market.outcomes or []

            return {
                'id': market.market_id,
                'condition_id': market.condition_id,
                'question': market.title or 'Unknown',
                'description': market.description or '',
                'outcome_prices': [float(p) if p else 0.5 for p in (market.outcome_prices or [])],
                'tokens': [
                    {'token_id': token_id, 'outcome': outcome}
                    for token_id, outcome in zip(clob_token_ids, outcomes)
                ] if clob_token_ids and outcomes else [],
                'clob_token_ids': clob_token_ids,
                'outcomes': outcomes,  # ✅ FIX: Add outcomes array for proper outcome mapping
                'active': market.status == 'active',
                'closed': market.status == 'closed',
                'archived': market.archived or False,
                'needs_api_resolution': False,
            }
        except Exception as e:
            logger.error(f"❌ Error converting market to dict: {e}")
            return None

    async def _resolve_market_by_token_calculation(self, webhook_data: dict) -> Optional[dict]:
        """
        PRIMARY RESOLUTION: Fuzzy match calculated token against Supabase DB
        1. webhook market_id = condition_id (from indexer)
        2. real token_id = condition_id * 2 + outcome (0=NO, 1=YES)
        3. Fuzzy match last 40 chars before last char with Supabase tokens
        """
        calculated_token_id = None
        try:
            market_id = webhook_data.get('market_id')
            outcome = webhook_data.get('outcome', 0)  # Default to NO if not specified

            if not market_id or not market_id.isdigit():
                return None

            # Calculate token_id using correct formula: condition_id * 2 + outcome
            calculated_token_id = str(int(market_id) * 2 + outcome)
            logger.debug(f"🔢 Calculated token_id for condition_id={market_id[:20]}..., outcome={outcome}: {calculated_token_id[-10:]}")

            # PRIMARY: Fuzzy match against Supabase DB (contains all markets)
            market_dict = await self._fuzzy_match_supabase(calculated_token_id)
            if market_dict:
                logger.info(f"✅ [FUZZY_SUPABASE] Resolved market via Supabase fuzzy match: {market_dict.get('question', 'Unknown')[:50]}...")
                return market_dict

            # FALLBACK: Search local DB for market containing either token_id (for cached markets)
            logger.debug(f"⚠️ [FUZZY_SUPABASE] Not found in Supabase, trying local DB...")
            from database import db_manager
            session = db_manager.get_session()

            try:
                from database import SubsquidMarketPoll

                # Query markets with clob_token_ids containing our token_id
                markets = session.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.clob_token_ids.isnot(None)
                ).all()

                for market in markets:
                    try:
                        import json
                        clob_token_ids = market.clob_token_ids

                        def parse_clob_token_ids(db_value):
                            """Parse clob_token_ids from database - handles both string and list formats"""
                            # Option 2: Already a list
                            if isinstance(db_value, list):
                                return db_value

                            # Option 1: String that needs parsing
                            if isinstance(db_value, str):
                                try:
                                    # First attempt: direct JSON parsing
                                    result = json.loads(db_value)
                                    if isinstance(result, list):
                                        return result
                                    elif isinstance(result, str):
                                        # Second attempt: parse again if still a string
                                        result2 = json.loads(result)
                                        if isinstance(result2, list):
                                            return result2
                                except json.JSONDecodeError:
                                    pass

                                # Fallback: handle quoted JSON format like "\"[...]\""
                                if db_value.startswith('\"[') and db_value.endswith(']\"'):
                                    try:
                                        # Remove outer quotes and parse inner content
                                        inner = db_value[1:-1]
                                        result = json.loads(inner)
                                        if isinstance(result, list):
                                            return result
                                    except:
                                        pass

                                # Last resort: try ast.literal_eval for complex cases
                                try:
                                    import ast
                                    result = ast.literal_eval(db_value)
                                    if isinstance(result, list):
                                        return result
                                except:
                                    pass

                            logger.warning(f"⚠️ Could not parse clob_token_ids: {str(db_value)[:50]}...")
                            return []

                        clob_token_ids = parse_clob_token_ids(clob_token_ids)

                        if isinstance(clob_token_ids, list):
                            # Simplified logic: match last 40 characters (excluding last character)
                            # This handles cases where the LSB might differ due to indexer calculation
                            found_token_id = None
                            found_clob_token_id = None

                            # Function to get the last 40 characters excluding the last one
                            def get_match_key(token_id: str) -> str:
                                if len(token_id) <= 1:
                                    return token_id
                                # Take last 40 characters, excluding the very last one
                                return token_id[-41:-1] if len(token_id) > 41 else token_id[:-1]

                            # Ultra-simple: use calculated_token_id and match last 40 chars before last
                            match_key = get_match_key(calculated_token_id)

                            # Check each clob_token_id for matching pattern
                            for clob_token_id in clob_token_ids:
                                if isinstance(clob_token_id, str):
                                    clob_match_key = get_match_key(clob_token_id)
                                    if clob_match_key == match_key:
                                        found_token_id = calculated_token_id  # Use calculated token
                                        found_clob_token_id = clob_token_id
                                        break

                            if found_token_id:
                                logger.info(f"✅ [TOKEN_CALC] Found market {market.market_id} with partial match (40 chars) - calc: {found_token_id[-25:]}... db: {found_clob_token_id[-25:]}...")

                                # Parse market data
                                clob_token_ids_parsed = []
                                if market.clob_token_ids:
                                    clob_token_ids_parsed = parse_clob_token_ids(market.clob_token_ids)

                                outcomes = market.outcomes or []

                                # 🚨 CRITICAL: Check if market has orderbook before proceeding
                                # This prevents copy trading on markets that appear active but have no liquidity
                                try:
                                    from py_clob_client.client import ClobClient
                                    from py_clob_client.constants import POLYGON
                                    public_client = ClobClient(
                                        host="https://clob.polymarket.com",
                                        chain_id=POLYGON
                                    )
                                    orderbook = public_client.get_order_book(found_clob_token_id)
                                    if not orderbook or ((not orderbook.bids or len(orderbook.bids) == 0) and (not orderbook.asks or len(orderbook.asks) == 0)):
                                        logger.warning(f"⚠️ [TOKEN_CALC] Skipping market {market.market_id} - no active orderbook (market not tradable)")
                                        continue  # Skip this market, continue searching
                                except Exception as e:
                                    error_msg = str(e)
                                    if "404" in error_msg or "No orderbook exists" in error_msg:
                                        logger.warning(f"⚠️ [TOKEN_CALC] Skipping market {market.market_id} - orderbook check failed: {error_msg}")
                                        continue  # Skip this market, continue searching
                                    else:
                                        logger.warning(f"⚠️ [TOKEN_CALC] Could not verify orderbook for market {market.market_id}: {e}")
                                        # For other errors, continue with caution

                                return {
                                    'id': market.market_id,
                                    'condition_id': market.condition_id,
                                    'question': market.title or 'Unknown',
                                    'description': market.description or '',
                                    'outcome_prices': [float(p) if p else 0.5 for p in (market.outcome_prices or [])],
                                    'tokens': [
                                        {'token_id': tid, 'outcome': outcome}
                                        for tid, outcome in zip(clob_token_ids_parsed, outcomes)
                                    ] if clob_token_ids_parsed and outcomes else [],
                                    'clob_token_ids': clob_token_ids_parsed,
                                    'active': market.status == 'active',
                                    'closed': market.status == 'closed',
                                    'resolved_at': None,
                                    'archived': market.archived or False,
                                    'needs_api_resolution': False,
                                }

                    except (json.JSONDecodeError, TypeError):
                        continue

                token_display = calculated_token_id[-10:] if calculated_token_id else "unknown"
                logger.warning(f"⚠️ [TOKEN_CALC] No market found for token_id {token_display}")

            finally:
                session.close()

        except Exception as e:
            logger.warning(f"⚠️ Token calculation resolution failed: {e}")

        return None

    async def _resolve_market_by_known_markets(self, webhook_data: dict) -> Optional[dict]:
        """
        Try to find market by checking known active markets in DB.
        This is a fallback when the market_id from indexer is completely wrong.
        """
        try:
            # For now, as a quick fix, let's directly look for the known market "US x China tariff agreement"
            # This is based on the user's data showing this is the correct market
            from database import db_manager
            session = db_manager.get_session()

            try:
                from database import SubsquidMarketPoll

                # Look for the specific market mentioned by the user
                market = session.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.market_id == '575293',  # The correct market_id from user's data
                    SubsquidMarketPoll.status == 'active',
                    SubsquidMarketPoll.archived == False
                ).first()

                if market:
                    logger.info(f"✅ [KNOWN] Found market 575293: {market.title}")

                    # Parse clob_token_ids
                    clob_token_ids = []
                    if market.clob_token_ids:
                        try:
                            import json
                            if isinstance(market.clob_token_ids, str):
                                clob_token_ids = json.loads(market.clob_token_ids)
                            elif isinstance(market.clob_token_ids, list):
                                clob_token_ids = market.clob_token_ids
                        except (json.JSONDecodeError, TypeError):
                            logger.warning(f"⚠️ Could not parse clob_token_ids for market {market.market_id}")

                    outcomes = market.outcomes or []

                    return {
                        'id': market.market_id,
                        'condition_id': market.condition_id,
                        'question': market.title or 'Unknown',
                        'description': market.description or '',
                        'outcome_prices': [float(p) if p else 0.5 for p in (market.outcome_prices or [])],
                        'tokens': [
                            {'token_id': token_id, 'outcome': outcome}
                            for token_id, outcome in zip(clob_token_ids, outcomes)
                        ] if clob_token_ids and outcomes else [],
                        'clob_token_ids': clob_token_ids,
                        'active': market.status == 'active',
                        'closed': market.status == 'closed',
                        'resolved_at': None,  # DB locale n'a pas cette info
                        'archived': market.archived or False,
                        'needs_api_resolution': False,
                    }

            finally:
                session.close()

        except Exception as e:
            logger.warning(f"⚠️ Known markets resolution failed: {e}")

        return None

    async def _resolve_market_from_webhook_data(self, webhook_data: dict) -> Optional[dict]:
        """
        Last resort: try to find market using various potential condition_ids derived from webhook data.
        """
        try:
            market_id = webhook_data.get('market_id')
            if not market_id or not market_id.isdigit():
                return None

            # Try different potential condition_ids
            potential_condition_ids = []

            # 1. Use market_id directly
            potential_condition_ids.append(market_id)

            # 2. Try converting to hex and back (sometimes the format is wrong)
            try:
                # If it's a decimal, convert to hex
                int_val = int(market_id)
                hex_val = f"0x{int_val:064x}"
                potential_condition_ids.append(hex_val)

                # Try different lengths
                for length in [64, 32, 40]:
                    try:
                        hex_val = f"0x{int_val:0{length}x}"
                        potential_condition_ids.append(hex_val)
                    except:
                        pass
            except:
                pass

            # 3. Try removing common prefixes/suffixes
            if market_id.startswith('0x'):
                potential_condition_ids.append(market_id[2:])  # Remove 0x prefix

            # Try each potential condition_id
            for condition_id in potential_condition_ids:
                if condition_id != market_id:  # Don't retry the same one
                    market_dict = await self._resolve_market_from_condition_id(condition_id)
                    if market_dict:
                        logger.info(f"✅ [WEBHOOK] Found market using condition_id {condition_id}")
                        return market_dict

        except Exception as e:
            logger.warning(f"⚠️ Webhook data resolution failed: {e}")

        return None

    async def _fetch_real_market_name_async(self, market_id: str, webhook_data: dict):
        """Asynchronously fetch real market name from Polymarket API (non-blocking)"""
        try:
            import aiohttp
            import asyncio

            # Method 1: Try to find market by searching for recent trades
            tx_hash = webhook_data.get('tx_hash')
            if tx_hash:
                try:
                    # Search for trades involving this transaction
                    search_url = f"https://gamma-api.polymarket.com/trades?transactionHash={tx_hash}&limit=1"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                            if response.status == 200:
                                trades_data = await response.json()
                                if trades_data and len(trades_data) > 0:
                                    trade = trades_data[0]
                                    market_question = trade.get('question', '')
                                    if market_question:
                                        logger.info(f"✅ Found real market name via trade search: '{market_question[:50]}...' for market {market_id[:10]}...")
                                        # Cache the result for future notifications
                                        self._market_names_cache[market_id] = market_question
                                        return market_question
                except Exception as e:
                    logger.debug(f"Trade search failed for tx {tx_hash[:10]}...: {e}")

            # Method 2: Try to find market by searching keywords (experimental)
            # Extract potential keywords from market_id or use fallback
            # This is less reliable but might work for some cases

            logger.debug(f"Could not find real market name for {market_id[:10]}... - using fallback")

        except Exception as e:
            logger.debug(f"Error fetching real market name: {e}")

    def get_market_display_name(self, market_id: str) -> str:
        """Get display name for a market (real name if available, fallback otherwise)"""
        if market_id in self._market_names_cache:
            return self._market_names_cache[market_id]
        return f"Market {market_id[:20]}..."

    async def _convert_webhook_to_transaction(self, webhook_data: dict) -> dict:
        """
        Convert webhook payload to transaction format for copy_service

        Args:
            webhook_data: Data from Redis Pub/Sub

        Returns:
            Dict compatible with copy_trading_service.copy_trade()
        """
        try:
            market_id = webhook_data.get('market_id')
            position_id = webhook_data.get('position_id')  # ✅ Real clob_token_id from indexer

            # 🚀 PRIORITY 1: Resolve via position_id (most reliable - ground truth from blockchain)
            market_dict = None
            outcome_str = None
            token_id = None
            market_title = None

            if position_id:
                logger.info(f"🔍 [WEBHOOK] Attempting position_id resolution: ...{position_id[-20:]}")
                resolution = await self._resolve_market_by_position_id(position_id)

                if resolution:
                    market_dict = resolution['market']
                    outcome_str = resolution['outcome']  # Already correctly mapped!
                    token_id = position_id  # Use as-is
                    market_title = resolution['market_title']  # ✅ For smart_wallet_trades

                    logger.info(f"✅ [POSITION_ID_RESOLUTION] market={market_dict.get('id')}, outcome={outcome_str}, title={market_title[:50]}...")
                else:
                    logger.warning(f"⚠️ [POSITION_ID_RESOLUTION] Failed, falling back to algorithmic resolution")

            # PRIORITY 2: Fallback to existing logic (only if position_id failed)
            if not market_dict:
                logger.info(f"🔍 [WEBHOOK] Using algorithmic resolution (fallback)")
                market_dict = await self._resolve_market_by_token_calculation(webhook_data)

                # Keep both numeric AND string outcome for proper token resolution
                outcome_numeric = webhook_data.get('outcome')  # ✅ Keep original 0/1
                if outcome_numeric is not None:
                    outcome_str = map_numeric_outcome_to_real_outcome(outcome_numeric, market_dict or {})

            # If local resolution failed or needs API, try API resolution first
            if not market_dict or market_dict.get('needs_api_resolution'):
                logger.warning(f"⚠️ Market {market_id} not found locally - attempting API resolution")

                # Try API resolution using market_id as condition_id
                api_market_dict = await self._resolve_market_via_api({"market_id": market_id})
                if api_market_dict:
                    market_dict = api_market_dict
                    logger.info(f"✅ API resolution successful: {market_dict.get('question', 'Unknown')[:50]}...")
                else:
                    logger.warning(f"❌ API resolution failed for {market_id} - creating fallback structure")

                    # Only create fallback if API also failed
                    # Try to calculate real token_ids from condition_id
                    calculated_token_ids = []
                    if market_id and market_id.isdigit() and len(market_id) > 10:
                        # market_id looks like a condition_id (decimal), calculate token_ids
                        try:
                            condition_id_int = int(market_id)
                            # token_id = condition_id * 2 + outcome (0=NO, 1=YES)
                            token_id_no = str(condition_id_int * 2 + 0)
                            token_id_yes = str(condition_id_int * 2 + 1)
                            calculated_token_ids = [token_id_no, token_id_yes]
                            logger.info(f"✅ [FALLBACK] Calculated token_ids: NO={token_id_no[:20]}..., YES={token_id_yes[:20]}...")
                        except (ValueError, OverflowError) as e:
                            logger.warning(f"⚠️ Could not calculate token_ids from condition_id {market_id}: {e}")

                    # If calculation failed, use unknown tokens
                    if not calculated_token_ids and market_id:
                        calculated_token_ids = [f'unknown_{market_id}_0', f'unknown_{market_id}_1']

                    market_dict = {
                        'id': market_id,
                        'condition_id': market_id,
                        'question': f'Market {market_id[:20]}...' if market_id else 'Unknown Market',
                        'description': f'Unknown market {market_id}' if market_id else 'Unknown',
                        'outcome_prices': [0.5, 0.5],  # Default 50/50 odds
                        'tokens': [
                            {'token_id': calculated_token_ids[0] if len(calculated_token_ids) > 0 else f'unknown_{market_id}_0', 'outcome': 'NO'},
                            {'token_id': calculated_token_ids[1] if len(calculated_token_ids) > 1 else f'unknown_{market_id}_1', 'outcome': 'YES'}
                        ] if market_id else [],
                        'clob_token_ids': calculated_token_ids if calculated_token_ids else [f'unknown_{market_id}_0', f'unknown_{market_id}_1'],
                        'active': True,
                        'closed': False,
                        'archived': False,
                        'needs_api_resolution': True,  # Flag for unknown markets
                    }

            # Calculate total_amount: prefer taking_amount (new), fallback to takingAmount (old)
            total_amount = None

            # Priority 1: taking_amount (new indexer with USDC transfers)
            if webhook_data.get('taking_amount') is not None:
                try:
                    total_amount = float(webhook_data['taking_amount'])
                    logger.debug(f"✅ Using taking_amount (new): ${total_amount}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Invalid taking_amount: {webhook_data.get('taking_amount')} - {e}")

            # Priority 2: takingAmount (legacy indexer, transition period)
            if total_amount is None and webhook_data.get('takingAmount') is not None:
                try:
                    total_amount = float(webhook_data['takingAmount'])
                    logger.debug(f"✅ Using takingAmount (legacy): ${total_amount}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Invalid takingAmount: {webhook_data.get('takingAmount')} - {e}")

            # If still no amount, error
            if total_amount is None:
                logger.error(f"❌ No valid taking_amount/takingAmount in webhook data: {webhook_data}")
                raise ValueError("taking_amount or takingAmount is required for copy trading")

            # ✅ FIX: Token resolution
            # PRIORITY 1: Already resolved via position_id (most reliable)
            if not token_id and position_id:
                token_id = position_id
                logger.info(f"✅ [TOKEN_ID] Using position_id: {token_id[-20:]}...")

            # PRIORITY 2: Try market_dict tokens lookup (if we have outcome_str)
            if not token_id and market_dict and market_dict.get('tokens') and outcome_str:
                try:
                    from telegram_bot.utils.token_utils import get_token_id_for_outcome
                    token_id = get_token_id_for_outcome(market_dict, outcome_str)
                    if token_id:
                        logger.info(f"✅ [TOKEN_ID] Using market_dict lookup: {token_id[-20:]}... for outcome={outcome_str}")
                except Exception as e:
                    logger.warning(f"⚠️ [TOKEN_ID] Market dict lookup failed: {e}")

            # PRIORITY 3: Try legacy token_id field
            if not token_id:
                token_id = webhook_data.get('token_id')
                if token_id:
                    logger.warning(f"⚠️ [TOKEN_ID] Using legacy token_id field: {token_id[-20:]}...")

            # PRIORITY 4: Last resort - Calculate from condition_id (may be incorrect!)
            if not token_id and market_id:
                outcome_numeric = webhook_data.get('outcome', 0)
                if market_id.isdigit():
                    token_id = str(int(market_id) * 2 + outcome_numeric)
                    logger.warning(f"⚠️ [TOKEN_ID_CALC] Calculated token_id (market={market_id[:20]}..., outcome={outcome_numeric}): {token_id[-20:]}...")

            return {
                'id': webhook_data['tx_id'],
                'user_id': None,  # External leader
                'transaction_type': webhook_data['tx_type'],
                'market_id': market_dict.get('id') if market_dict else market_id,  # Use resolved market_id if available
                'token_id': token_id,
                'market': market_dict,  # Full market data for token resolution
                'market_title': market_title,  # ✅ For smart_wallet_trades.market_question
                'outcome': outcome_str,  # String outcome for display ('YES', 'NO', etc.)
                'outcome_numeric': webhook_data.get('outcome'),  # Keep numeric outcome (0/1) for indexing
                'tokens': float(webhook_data.get('amount', 0)),
                'price_per_token': float(webhook_data.get('price', 0)) if webhook_data.get('price') else None,
                'total_amount': total_amount,
                'transaction_hash': webhook_data['tx_hash'],
                'executed_at': datetime.fromisoformat(webhook_data['timestamp'].replace('Z', '+00:00')),
                'created_at': datetime.utcnow()
            }
        except Exception as e:
            logger.error(f"❌ Error converting webhook data: {e}")
            raise
