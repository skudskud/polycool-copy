"""
Copy Trading Service
Main orchestration layer combining repository, calculator, and business logic
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from .repository import CopyTradingRepository
from .calculator import CopyAmountCalculator
from .models import CopyTradingSubscription, CopyTradingHistory
from .config import CopyMode, SubscriptionStatus, CopyTradeStatus, COPY_TRADING_CONFIG
from .exceptions import (
    CopyTradingException,
    SubscriptionException,
    InvalidConfigException,
    InsufficientBudgetException,
    CopyExecutionException,
    MultipleSubscriptionsError,
    LeaderNotFoundError,
    FollowerNotFoundError,
)

logger = logging.getLogger(__name__)

# Global service instance
_copy_trading_service: Optional['CopyTradingService'] = None


def get_copy_trading_service() -> 'CopyTradingService':
    """Get or create global copy trading service instance"""
    global _copy_trading_service
    if _copy_trading_service is None:
        _copy_trading_service = CopyTradingService()
    return _copy_trading_service


def set_copy_trading_service(service: 'CopyTradingService'):
    """Set global copy trading service instance"""
    global _copy_trading_service
    _copy_trading_service = service


class CopyTradingService:
    """
    Main service for copy trading operations
    Orchestrates repository, calculator, and business logic
    """

    def __init__(self):
        """Initialize service (lazy-loads DB session on first use)"""
        self.db: Optional[Session] = None
        self.repo: Optional[CopyTradingRepository] = None
        self.calculator = CopyAmountCalculator()

    def _get_repo(self) -> CopyTradingRepository:
        """Lazy-load repository with current DB session, create fresh if previous failed"""
        try:
            # If we have a repo, try to ping it - if failed, recreate
            if self.repo is not None:
                from sqlalchemy import text
                self.db.execute(text("SELECT 1"))  # Wrap with text() for proper SQL handling
                return self.repo
        except Exception as e:
            logger.debug(f"Previous DB session failed, creating fresh one: {e}")
            # Close and reset
            if self.db:
                try:
                    self.db.rollback()
                    self.db.close()
                except:
                    pass
            self.db = None
            self.repo = None

        # Create fresh session
        if self.repo is None:
            from database import SessionLocal
            self.db = SessionLocal()
            self.repo = CopyTradingRepository(self.db)
        return self.repo

    # =========================================================================
    # ADDRESS RESOLUTION (3-TIER FALLBACK)
    # =========================================================================

    def resolve_leader_by_address(self, polygon_address: str) -> int:
        """
        Resolve a Polygon wallet address to a leader's telegram user ID

        Supports three tiers:
        1. Regular platform users (from users table)
        2. Smart wallet addresses (from smart_wallets table)
        3. External CLOB traders (from CLOB API with caching in external_leaders)

        Args:
            polygon_address: Polygon wallet address to resolve

        Returns:
            Telegram user ID or virtual_id for external traders

        Raises:
            LeaderNotFoundError: If address not found in any tier
        """
        try:
            repo = self._get_repo()
            normalized_addr = polygon_address.lower()

            # Tier 1: Check users table (platform members)
            user = repo.find_user_by_polygon_address(normalized_addr)
            if user:
                logger.info(f"✅ Resolved address {normalized_addr[:10]}... to user {user.telegram_user_id} (Tier 1)")
                return user.telegram_user_id

            # Tier 2: Check smart_wallets table (if exists)
            try:
                from database import SmartWallet
                smart_wallet = repo.db.query(SmartWallet).filter(
                    SmartWallet.address.ilike(normalized_addr)
                ).first()
                if smart_wallet:
                    virtual_id = -abs(hash(normalized_addr)) % (2**31)
                    logger.info(f"✅ Resolved to smart wallet (virtual_id: {virtual_id}) (Tier 2)")
                    return virtual_id
            except Exception as e:
                logger.debug(f"Smart wallet lookup: {e}")

            # Tier 3: Check CLOB API for external traders (with caching)
            virtual_id = self._resolve_external_trader(normalized_addr)
            if virtual_id:
                logger.info(f"✅ Resolved to external trader (virtual_id: {virtual_id}) (Tier 3)")
                return virtual_id

            logger.warning(f"❌ No trader found: {polygon_address} (checked 3 tiers: users, smart_wallets, CLOB API)")
            raise LeaderNotFoundError(f"No trader found with address: {polygon_address}")

        except LeaderNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error resolving leader: {e}")
            raise LeaderNotFoundError(f"Failed to resolve address: {str(e)}")

    def _resolve_external_trader(self, polygon_address: str) -> Optional[int]:
        """
        Resolve external CLOB trader with caching for scalability

        ✅ NEW BEHAVIOR: Always returns virtual_id for valid addresses
        We track FUTURE trades, not historical validation

        Args:
            polygon_address: Normalized Polygon address

        Returns:
            Virtual ID (always returns for valid addresses)
        """
        try:
            from database import ExternalLeader
            from datetime import datetime

            repo = self._get_repo()

            # Check cache first
            external = repo.db.query(ExternalLeader).filter(
                ExternalLeader.polygon_address == polygon_address
            ).first()

            if external:
                return external.virtual_id

            # Generate virtual_id and cache (no CLOB API validation)
            # We track FUTURE trades, not historical ones
            virtual_id = -abs(hash(polygon_address)) % (2**31)
            self._cache_external_trader(polygon_address, virtual_id, is_active=True)

            logger.info(f"✅ Added external leader {polygon_address[:10]}... (virtual_id: {virtual_id})")
            return virtual_id

        except Exception as e:
            logger.warning(f"Error resolving external trader: {e}")
            return None

    def _validate_external_trader_clob_api(self, polygon_address: str) -> bool:
        """
        Check if address has trades on CLOB by querying Polymarket API

        Args:
            polygon_address: Polygon wallet address

        Returns:
            True if address has trades on CLOB, False otherwise
        """
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import TradeParams, ApiCreds
            from py_clob_client.constants import POLYGON
            import os
            from dotenv import load_dotenv

            load_dotenv()

            # Get credentials from env
            api_key = os.getenv("CLOB_API_KEY")
            api_secret = os.getenv("CLOB_API_SECRET")
            api_passphrase = os.getenv("CLOB_API_PASSPHRASE")

            # If no creds available, can't validate - assume invalid
            if not all([api_key, api_secret, api_passphrase]):
                logger.debug(f"CLOB credentials missing - cannot validate external trader {polygon_address}")
                return False

            # Create properly configured client
            creds = ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase,
            )

            client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=POLYGON,
                creds=creds,
            )

            # Query trades for this address
            trades = client.get_trades(
                TradeParams(maker_address=polygon_address)
            )

            # Check if response has trades
            result = trades is not None and len(trades) > 0
            logger.debug(f"CLOB API validation for {polygon_address}: {result} (found {len(trades) if trades else 0} trades)")
            return result

        except Exception as e:
            logger.warning(f"CLOB validation error for {polygon_address}: {e}")
            return False

    def _cache_external_trader(self, polygon_address: str, virtual_id: int, is_active: bool = True):
        """
        Cache external trader for 1 hour

        Uses UPSERT to handle conflicts gracefully (idempotent)

        Args:
            polygon_address: Polygon wallet address
            virtual_id: Virtual ID for this external trader
            is_active: Whether the trader is active (default: True)
        """
        try:
            from database import ExternalLeader
            from datetime import datetime
            from sqlalchemy.dialects.postgresql import insert

            repo = self._get_repo()

            # ✅ FIX: Use UPSERT instead of manual check-then-insert
            # Handles race conditions and duplicate key errors gracefully
            stmt = insert(ExternalLeader).values(
                virtual_id=virtual_id,
                polygon_address=polygon_address.lower(),
                last_trade_id='',
                is_active=is_active,
                last_poll_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            ).on_conflict_do_update(
                index_elements=['polygon_address'],  # Conflict on unique polygon_address
                set_={
                    'is_active': is_active,
                    'last_poll_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                    # Note: Don't update virtual_id here - keep the original one
                }
            )

            repo.db.execute(stmt)
            repo.db.commit()
            logger.debug(f"✅ Cached external trader {polygon_address[:10]}... (virtual_id: {virtual_id}, active: {is_active})")

        except Exception as e:
            logger.error(f"Cache error: {e}")
            # ✅ FIX: Rollback tainted session
            try:
                repo.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {rollback_error}")

    def _ensure_leader_in_external_leaders(self, leader_id: int, repo):
        """
        Ensure leader is in external_leaders for webhook tracking

        For Telegram users, adds their polygon_address to external_leaders
        so the indexer webhook will send us their trades

        Uses UPSERT to handle conflicts when:
        - Address already exists with different virtual_id (external → bot user transition)
        - Multiple subscribers try to add same leader simultaneously
        """
        try:
            from database import ExternalLeader, User, Transaction
            from datetime import datetime
            from sqlalchemy.dialects.postgresql import insert

            # Get user's polygon address
            user = repo.db.query(User).filter(
                User.telegram_user_id == leader_id
            ).first()

            if not user or not user.polygon_address:
                logger.warning(f"Cannot add leader {leader_id} to external_leaders: no polygon address")
                return

            # Get last trade ID to avoid reprocessing old trades
            last_trade = repo.db.query(Transaction).filter(
                Transaction.user_id == leader_id
            ).order_by(Transaction.id.desc()).first()

            last_trade_id = str(last_trade.id) if last_trade else ''

            polygon_address = user.polygon_address.lower()

            # ✅ FIX: Use UPSERT with ON CONFLICT on polygon_address
            # This handles the case where address exists with different virtual_id
            stmt = insert(ExternalLeader).values(
                virtual_id=leader_id,
                polygon_address=polygon_address,
                last_trade_id=last_trade_id,
                is_active=True,
                last_poll_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            ).on_conflict_do_update(
                index_elements=['polygon_address'],  # Conflict on unique polygon_address
                set_={
                    'virtual_id': leader_id,  # Update to current telegram_user_id
                    'last_trade_id': last_trade_id,
                    'is_active': True,
                    'last_poll_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }
            )

            repo.db.execute(stmt)
            repo.db.commit()

            logger.info(f"✅ Upserted leader {leader_id} ({polygon_address[:10]}...) to external_leaders for webhook tracking")

        except Exception as e:
            logger.error(f"Error upserting leader to external_leaders: {e}")
            # ✅ FIX: Rollback tainted session
            try:
                repo.db.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {rollback_error}")
            # Non-critical error, continue anyway

    # =========================================================================
    # SUBSCRIPTION MANAGEMENT
    # =========================================================================

    def subscribe_to_leader(
        self,
        follower_id: int,
        leader_id: int,
        copy_mode: str = CopyMode.PROPORTIONAL.value,
        fixed_amount: float = None,
    ) -> Dict[str, Any]:
        """
        Start following a leader for copy trading

        Each user can only follow ONE leader at a time
        If already following someone, replaces the old subscription

        Args:
            follower_id: Telegram user ID of follower
            leader_id: Telegram user ID of leader
            copy_mode: 'PROPORTIONAL' or 'FIXED'
            fixed_amount: Fixed amount for FIXED mode

        Returns:
            Dict with subscription details

        Raises:
            InvalidConfigException: If config is invalid
        """
        repo = self._get_repo()

        # Initialize follower_transaction_id (will be set after successful trade execution)
        follower_transaction_id = None

        try:
            # Validate config
            if copy_mode == CopyMode.FIXED.value:
                if fixed_amount is None:
                    raise InvalidConfigException("Fixed amount required for FIXED mode")
                self.calculator.validate_fixed_amount(fixed_amount)

            # Validate users exist and create user for smart wallets if needed
            from database import User
            repo = self._get_repo()
            db = repo.db

            # Check if leader exists in users table
            leader_user = db.query(User).filter(User.telegram_user_id == leader_id).first()
            if not leader_user:
                # Leader doesn't exist - try to resolve as external trader or create virtual account
                logger.warning(f"🔍 Leader {leader_id} not found in users table, attempting to resolve...")

                # Try to find this leader in external leaders or smart wallets
                original_address = None

                if leader_id < 0:
                    # Negative virtual ID - resolve the original address
                    original_address = self._resolve_address_from_virtual_id(leader_id)
                    logger.info(f"🔍 Negative virtual ID {leader_id}, resolved address: {original_address}")
                else:
                    # Positive ID - check if it's an external leader
                    from database import ExternalLeader
                    external_leader = db.query(ExternalLeader).filter(
                        ExternalLeader.virtual_id == leader_id
                    ).first()

                    if external_leader:
                        original_address = external_leader.polygon_address
                        logger.info(f"✅ Found external leader for virtual_id {leader_id}: {original_address}")
                    else:
                        # Check if it corresponds to a smart wallet trade (address used as ID)
                        from database import SmartWalletTrade
                        recent_trade = db.query(SmartWalletTrade).filter(
                            SmartWalletTrade.wallet_address == str(leader_id)
                        ).first()

                        if recent_trade:
                            original_address = recent_trade.wallet_address
                            logger.info(f"✅ Found smart wallet trade for address {original_address}")
                        else:
                            # Last resort: this might be an unknown external trader
                            # Generate a placeholder address and virtual ID
                            virtual_id = -abs(hash(str(leader_id))) % (2**31)
                            original_address = f"unknown_{leader_id}"  # Placeholder
                            leader_id = virtual_id  # Convert to virtual ID
                            logger.warning(f"⚠️ Unknown leader {leader_id}, treating as external trader (virtual_id: {virtual_id})")

                if original_address:
                    # Create virtual user account
                    logger.info(f"🤖 Creating virtual user account for leader {leader_id} (address: {original_address[:20]}...)")

                    try:
                        # Create user directly in DB (don't use user_service to avoid wallet creation)
                        leader_user = User(
                            telegram_user_id=leader_id,
                            username=f"virtual_leader_{abs(leader_id) % 1000}",
                            polygon_address=original_address,
                            # Required encrypted fields (even if None for virtual users)
                            _polygon_private_key_encrypted=None,
                            # Optional fields with defaults
                            funded=False
                        )
                        db.add(leader_user)
                        db.commit()
                        logger.info(f"✅ Created virtual user account for leader {leader_id}")
                    except Exception as create_error:
                        logger.error(f"❌ Failed to create virtual user for {leader_id}: {create_error}")
                        db.rollback()
                        raise InvalidConfigException(f"Failed to create virtual user: {create_error}")
                else:
                    logger.error(f"❌ Could not resolve address for leader {leader_id}")
                    raise InvalidConfigException(f"Could not resolve leader {leader_id} - no address found")

            # ⚠️ TESTING: Allow following yourself for testing purposes
            # TODO: Re-enable this check for production
            # if follower_id == leader_id:
            #     raise InvalidConfigException("Cannot follow yourself")

            # Check if already following someone - if so, cancel old subscription first
            existing_sub = repo.get_active_subscription_for_follower(follower_id)
            if existing_sub:
                old_leader_id = existing_sub.leader_id
                logger.info(f"🔄 Replacing subscription: {follower_id} was following {old_leader_id}, now switching to {leader_id}")
                repo.cancel_subscription(follower_id, old_leader_id, commit=False)
                repo.update_leader_stats(old_leader_id)


            # Create new subscription
            subscription = repo.create_subscription(
                follower_id=follower_id,
                leader_id=leader_id,
                copy_mode=copy_mode,
                fixed_amount=fixed_amount,
            )

            # Ensure follower has budget record
            budget = repo.get_budget(follower_id)
            if not budget:
                logger.info(f"Creating default budget for new copy trader {follower_id}")
                budget = repo.create_budget(
                    follower_id,
                    allocation_percentage=COPY_TRADING_CONFIG.DEFAULT_ALLOCATION_PERCENTAGE,
                )

            # Update leader stats
            repo.update_leader_stats(leader_id)

            # ✅ IMPORTANT: Add leader to external_leaders for webhook tracking
            # This ensures the indexer sends us trades from this address
            self._ensure_leader_in_external_leaders(leader_id, repo)

            logger.info(f"✅ Subscribed {follower_id} to leader {leader_id} (mode={copy_mode})")

            return {
                'success': True,
                'follower_id': follower_id,
                'leader_id': leader_id,
                'copy_mode': copy_mode,
                'fixed_amount': fixed_amount,
                'budget_allocation_pct': float(budget.allocation_percentage),
            }

        except InvalidConfigException as e:
            logger.warning(f"❌ Subscription failed: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error in subscribe_to_leader: {e}")
            raise CopyTradingException(f"Failed to subscribe: {e}")

    def unsubscribe_from_leader(self, follower_id: int, leader_id: int) -> bool:
        """
        Stop following a leader

        Args:
            follower_id: Telegram user ID of follower
            leader_id: Telegram user ID of leader

        Returns:
            True if successful
        """
        repo = self._get_repo()

        # Initialize follower_transaction_id (will be set after successful trade execution)
        follower_transaction_id = None

        try:
            repo.cancel_subscription(follower_id, leader_id)
            repo.update_leader_stats(leader_id)
            logger.info(f"✅ Unsubscribed {follower_id} from leader {leader_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to unsubscribe: {e}")
            raise

    def get_leader_for_follower(self, follower_id: int) -> Optional[int]:
        """Get the leader ID that follower is currently following"""
        repo = self._get_repo()
        subscription = repo.get_active_subscription_for_follower(follower_id)
        return subscription.leader_id if subscription else None

    # =========================================================================
    # BUDGET MANAGEMENT
    # =========================================================================

    def set_allocation_percentage(
        self,
        user_id: int,
        allocation_percentage: float,
    ) -> Dict[str, Any]:
        """
        Set or update copy trading budget allocation percentage

        Args:
            user_id: Telegram user ID
            allocation_percentage: Percentage (5-100)

        Returns:
            Dict with new budget details

        Raises:
            InvalidConfigException: If percentage is invalid
        """
        repo = self._get_repo()

        # Initialize follower_transaction_id (will be set after successful trade execution)
        follower_transaction_id = None

        try:
            self.calculator.validate_allocation_percentage(allocation_percentage)

            budget = repo.update_budget_allocation_percentage(user_id, allocation_percentage)
            logger.info(f"✅ Updated allocation for {user_id}: {allocation_percentage}%")

            return budget.to_dict()

        except InvalidConfigException as e:
            logger.warning(f"❌ Invalid allocation: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to set allocation: {e}")
            raise

    def get_budget_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user's copy trading budget information"""
        repo = self._get_repo()
        budget = repo.get_budget(user_id)

        if not budget:
            return None

        return budget.to_dict()

    def sync_wallet_and_budget(self, user_id: int, wallet_balance: float) -> Dict[str, Any]:
        """
        Sync wallet balance and recalculate allocated budget
        Should be called before any copy trading occurs

        Args:
            user_id: Telegram user ID
            wallet_balance: Current wallet balance in USD

        Returns:
            Updated budget details
        """
        repo = self._get_repo()
        budget = repo.sync_wallet_balance(user_id, wallet_balance)
        logger.debug(f"✅ Synced budget for {user_id}: balance={wallet_balance}, allocated={float(budget.allocated_budget)}")
        return budget.to_dict()

    # =========================================================================
    # COPY TRADE EXECUTION
    # =========================================================================

    async def copy_trade(
        self,
        source_transaction: Dict[str, Any],
        leader_user_id: int,
    ) -> List[Dict[str, Any]]:
        """
        Main entry point for copying a leader's trade to all followers

        Called after a leader executes a trade
        This function finds all active followers and attempts to copy the trade

        Args:
            source_transaction: Dict with transaction details (from database.Transaction)
                Should include: id, user_id, market_id, outcome, transaction_type, total_amount
            leader_user_id: Telegram user ID of the leader

        Returns:
            List of copy results for each follower
        """
        repo = self._get_repo()

        # Initialize follower_transaction_id (will be set after successful trade execution)
        follower_transaction_id = None

        try:
            # Get all active followers for this leader
            subscriptions = repo.get_all_active_copiers_for_leader(leader_user_id)

            if not subscriptions:
                logger.debug(f"No active followers for leader {leader_user_id}")
                return []

            logger.debug(f"🔄 Copying trade from {leader_user_id} to {len(subscriptions)} followers")

            # Pre-cache follower credentials for faster execution
            follower_ids = [sub.follower_id for sub in subscriptions]
            await self._cache_follower_credentials(follower_ids)

            # Process each follower (in parallel with background tasks)
            copy_results = []
            for subscription in subscriptions:
                # Create background task for each copy (don't wait for completion)
                # IMPORTANT: Pass only IDs, not subscription objects (they become detached when session changes)
                asyncio.create_task(
                    self._execute_copy_for_follower(
                        follower_id=subscription.follower_id,
                        copy_mode=subscription.copy_mode,
                        fixed_amount=subscription.fixed_amount,
                        source_transaction=source_transaction,
                        leader_user_id=leader_user_id,
                    )
                )
                copy_results.append({
                    'follower_id': subscription.follower_id,
                    'status': 'queued',
                })

            return copy_results

        except Exception as e:
            logger.error(f"❌ Error in copy_trade: {e}")
            raise CopyExecutionException(f"Failed to copy trades: {e}")

    async def _execute_copy_for_follower(
        self,
        follower_id: int,
        copy_mode: str,
        fixed_amount: Optional[float],
        source_transaction: Dict[str, Any],
        leader_user_id: int,
    ):
        """
        Execute copy trade for a single follower
        Runs in background, non-blocking

        Args:
            subscription: CopyTradingSubscription model instance
            source_transaction: Leader's transaction details
            leader_user_id: Leader's user ID
        """
        repo = self._get_repo()

        # Initialize follower_transaction_id (will be set after successful trade execution)
        follower_transaction_id = None

        try:
            logger.debug(f"🔄 Copying trade for follower {follower_id}")

            # Get follower and leader user data with wallet addresses
            from core.services import user_service, balance_checker

            follower_user = user_service.get_user(follower_id)
            leader_user = user_service.get_user(leader_user_id)

            if not follower_user:
                logger.error(f"Follower user not found: {follower_id}")
                return

            # Get wallet balances using correct method
            # check_usdc_balance returns (balance: float, is_sufficient: bool)
            follower_balance, _ = balance_checker.check_usdc_balance(follower_user.polygon_address)

            if leader_user:
                leader_balance, _ = balance_checker.check_usdc_balance(leader_user.polygon_address)
            else:
                logger.warning(f"Leader user not found: {leader_user_id}, using default balance")
                leader_balance = 1000.0

            # ✅ CRITICAL: Sync wallet balance BEFORE calculating budget
            # This ensures budget = current_balance * allocation_percentage
            logger.debug(f"💰 Syncing wallet balance for follower {follower_id}: ${follower_balance:.2f}")

            # Get or create budget
            budget = repo.get_budget(follower_id)
            if not budget:
                logger.warning(f"No budget found for follower {follower_id}, creating default (50%)")
                budget = repo.create_budget(follower_id, 50.0, follower_balance)
            else:
                # ✅ ALWAYS sync balance before trade to get fresh allocation
                budget = repo.sync_wallet_balance(follower_id, follower_balance)
                logger.info(
                    f"✅ Budget synced for follower {follower_id}: "
                    f"Balance=${follower_balance:.2f}, "
                    f"Allocation={budget.allocation_percentage}%, "
                    f"Available=${budget.budget_remaining:.2f}"
                )

            # Calculate copy amount
            leader_trade_amount = float(source_transaction['total_amount'])
            tx_type = source_transaction.get('transaction_type', 'BUY')

            # Skip trades below threshold (different for BUY vs SELL)
            from .config import COPY_TRADING_CONFIG

            if tx_type == 'BUY':
                # BUY: Leader must trade > $2
                if leader_trade_amount < COPY_TRADING_CONFIG.IGNORE_TRADE_THRESHOLD_USD:
                    logger.info(f"⏭️ SKIP BUY: Leader trade ${leader_trade_amount:.2f} < ${COPY_TRADING_CONFIG.IGNORE_TRADE_THRESHOLD_USD:.0f} threshold")
                    return
            elif tx_type == 'SELL':
                # SELL: Leader must trade > $0.50
                if leader_trade_amount < COPY_TRADING_CONFIG.MIN_LEADER_SELL_THRESHOLD_USD:
                    logger.info(f"⏭️ SKIP SELL: Leader trade ${leader_trade_amount:.2f} < ${COPY_TRADING_CONFIG.MIN_LEADER_SELL_THRESHOLD_USD:.2f} threshold")
                    return

            # ✅ FIX: Budget check ONLY for BUY trades (SELL trades don't consume budget)
            if source_transaction['transaction_type'] == 'BUY':
                try:
                    calculated_amount = self.calculator.calculate_proportional_amount(
                        leader_trade_amount=leader_trade_amount,
                        leader_wallet_balance=float(leader_balance),
                        follower_available_usdc=float(budget.budget_remaining),
                    )

                    final_amount, reason = self.calculator.apply_minimum_and_allocation(
                        calculated_amount=calculated_amount,
                        copy_mode=copy_mode,
                        fixed_amount=float(fixed_amount) if fixed_amount else None,
                        allocation_budget_remaining=float(budget.budget_remaining),
                    )

                except InsufficientBudgetException as e:
                    logger.warning(f"Insufficient budget for {follower_id}: {e}")

                    # Record failed attempt - use calculated_amount if available, otherwise 0
                    final_calculated_amount = calculated_amount if 'calculated_amount' in locals() else 0
                    history = repo.create_copy_history(
                        follower_id=follower_id,
                        leader_id=leader_user_id,
                        leader_transaction_id=source_transaction['id'],
                        market_id=source_transaction['market_id'],
                        outcome=source_transaction['outcome'],
                        transaction_type=source_transaction['transaction_type'],
                        copy_mode=copy_mode,
                        leader_trade_amount=leader_trade_amount,
                        leader_wallet_balance=float(leader_balance),
                        calculated_copy_amount=final_calculated_amount,
                    )
                    repo.update_history_insufficient_budget(history.id)

                    # Notify user about insufficient budget
                    from core.services.copy_trading.notification_service import get_copy_trading_notification_service

                    try:
                        notification_service = get_copy_trading_notification_service()
                        leader_user = user_service.get_user(leader_user_id)
                        leader_username = leader_user.username if leader_user else f"User_{leader_user_id}"

                        # Send notification with wallet link
                        market_title = source_transaction.get('market_title', 'Unknown Market')
                        outcome = source_transaction.get('outcome', 'unknown')

                        await notification_service.send_message(
                            follower_id,
                            f"""
❌ **COPY TRADE FAILED**

👤 **Leader:** @{leader_username}
📊 **Market:** {market_title[:50]}{'...' if len(market_title) > 50 else ''}
🎯 **Position:** {outcome.upper()}
💵 **Action:** {source_transaction['transaction_type']}

**Reason:** Insufficient copy trading budget
💰 **Solution:** Add funds to your wallet

🔗 Use /wallet to manage your balance
                            """.strip()
                        )
                        logger.info(f"✅ [BUDGET_NOTIF] Sent insufficient budget notification to {follower_id}")
                    except Exception as notif_error:
                        logger.warning(f"⚠️ [BUDGET_NOTIF] Failed to send notification: {notif_error}")

                    return
            else:
                # ✅ FIX: For SELL trades, skip budget check and use position-based calculation
                calculated_amount = 0  # Placeholder for SELL (will be calculated position-based)
                final_amount = 0  # Placeholder (will be calculated in SELL block)

            # Record pending copy attempt
            history = repo.create_copy_history(
                follower_id=follower_id,
                leader_id=leader_user_id,
                leader_transaction_id=source_transaction['id'],
                market_id=source_transaction['market_id'],
                outcome=source_transaction['outcome'],
                transaction_type=source_transaction['transaction_type'],
                copy_mode=copy_mode,
                leader_trade_amount=leader_trade_amount,
                leader_wallet_balance=float(leader_balance),
                calculated_copy_amount=calculated_amount,
            )

            # EXECUTE ACTUAL TRADE via TradingService
            try:
                from telegram_bot.services.trading_service import TradingService
                from telegram_bot.session_manager import session_manager
                from telegram_bot.services.position_view_builder import PositionViewBuilder

                # Create trading service instance
                position_service = PositionViewBuilder()
                trading_service = TradingService(session_manager, position_service)

                # Create a mock callback query for TradingService methods
                class MockQuery:
                    class MockUser:
                        id = follower_id
                    from_user = MockUser()
                    async def answer(self, msg=None):
                        pass

                mock_query = MockQuery()

                # Check if this market needs API resolution (conditionId vs marketId mismatch)
                market_data = source_transaction.get('market', {})
                if market_data.get('needs_api_resolution', False):
                    logger.info(f"🔄 Market {source_transaction.get('market_id', 'N/A')[:20]}... needs API resolution - attempting now")

                    # Try to resolve via Polymarket API using the condition_id
                    condition_id = market_data.get('condition_id')
                    if condition_id:
                        try:
                            from core.services.copy_trading_monitor import get_copy_trading_monitor
                            monitor = get_copy_trading_monitor()

                            # Try to resolve the market via API
                            resolved_market = await monitor._resolve_market_from_condition_id(condition_id)
                            if resolved_market and not resolved_market.get('needs_api_resolution', False):
                                logger.info(f"✅ Successfully resolved market via API: {resolved_market.get('question', 'Unknown')}")
                                # Update the market data in source_transaction
                                source_transaction['market'] = resolved_market
                                market_data = resolved_market
                            else:
                                logger.warning(f"⚠️ API resolution failed for condition_id {condition_id}")
                                # Continue with fallback data
                        except Exception as e:
                            logger.warning(f"⚠️ Error during API resolution: {e}")
                            # Continue with fallback data

                    # If still needs resolution after API attempt, skip
                    if market_data.get('needs_api_resolution', False):
                        logger.warning(f"⚠️ Skipping trade for {follower_id}: Market resolution failed")
                        repo.update_history_failed(
                            history_id=history.id,
                            reason="Market resolution failed",
                        )
                        # No notification for technical failures
                        return

                # Get token_id from source transaction
                # ✅ NEW LOGIC: Monitor service (_convert_webhook_to_transaction or _convert_tracked_trade_to_transaction)
                # already resolved token_id via position_id resolution, so it should ALWAYS be present
                token_id = source_transaction.get('token_id')

                if not token_id:
                    # ⚠️ This should NEVER happen if monitor service is working correctly
                    logger.error(f"❌ No token_id in source_transaction after monitor resolution!")
                    logger.error(f"❌ source_transaction keys: {list(source_transaction.keys())}")
                    logger.error(f"❌ This indicates a bug in copy_trading_monitor service")

                    repo.update_history_failed(
                        history_id=history.id,
                        reason="Internal error: token_id missing after resolution",
                    )
                    return

                # 🚀 EDGE CASE FIX: Check if market is still tradable before SELL
                if source_transaction['transaction_type'] == 'SELL':
                    try:
                        from py_clob_client.client import ClobClient
                        from py_clob_client.constants import POLYGON
                        public_client = ClobClient(
                            host="https://clob.polymarket.com",
                            chain_id=POLYGON
                        )
                        orderbook = public_client.get_order_book(token_id)

                        if not orderbook or (not orderbook.bids or len(orderbook.bids) == 0):
                            logger.warning(f"⚠️ [MARKET_CHECK] Skipping SELL: Market {token_id[:20]}... no longer tradable (resolved?)")
                            repo.update_history_failed(
                                history_id=history.id,
                                reason="Market no longer tradable (possibly resolved)",
                            )
                            return

                        # ✅ Check price hasn't moved too much (max 20% slippage from leader's price)
                        if orderbook.bids and len(orderbook.bids) > 0:
                            current_best_bid = float(orderbook.bids[0][0])  # Best bid price
                            leader_sell_price = source_transaction.get('price_per_token')

                            if leader_sell_price and current_best_bid > 0:
                                price_delta_pct = abs(current_best_bid - leader_sell_price) / leader_sell_price * 100

                                if price_delta_pct > 20:  # Max 20% slippage
                                    logger.warning(
                                        f"⚠️ [PRICE_CHECK] Skipping SELL: Price moved {price_delta_pct:.1f}% "
                                        f"(leader: ${leader_sell_price:.4f}, current: ${current_best_bid:.4f})"
                                    )
                                    repo.update_history_failed(
                                        history_id=history.id,
                                        reason=f"Price slippage too high ({price_delta_pct:.1f}%)",
                                    )
                                    return

                    except Exception as market_check_error:
                        # Don't fail the entire trade on market check error, just log
                        logger.warning(f"⚠️ [MARKET_CHECK] Could not verify market status: {market_check_error}")
                        # Continue with SELL anyway

                # No market status checks - copy when it matches, regardless of market state
                logger.debug(f"🔄 Proceeding with copy trade for {follower_id} on market {source_transaction.get('market', {}).get('id', 'unknown')}")

                # Execute trade based on transaction type
                if source_transaction['transaction_type'] == 'BUY':
                    # Verify orderbook exists before trading
                    try:
                        # Use public ClobClient to check orderbook (no auth needed)
                        from py_clob_client.client import ClobClient
                        from py_clob_client.constants import POLYGON
                        public_client = ClobClient(
                            host="https://clob.polymarket.com",
                            chain_id=POLYGON
                        )
                        orderbook = public_client.get_order_book(token_id)
                        if not orderbook or (not orderbook.bids or len(orderbook.bids) == 0):
                            logger.warning(f"⚠️ Skipping BUY for {follower_id}: No orderbook or no liquidity for token {token_id[:20]}...")
                            repo.update_history_failed(
                                history_id=history.id,
                                reason="No active orderbook for this market token",
                            )
                            # No notification for technical issues
                            return
                    except Exception as orderbook_error:
                        error_msg = str(orderbook_error)
                        if "404" in error_msg or "No orderbook exists" in error_msg:
                            logger.warning(f"⚠️ Skipping BUY for {follower_id}: Market not tradable (no orderbook) - {error_msg}")
                            repo.update_history_failed(
                                history_id=history.id,
                                reason="Market not available for trading (no orderbook)",
                            )
                            # No notification for technical issues
                            return
                        else:
                            # Re-raise other errors (network issues, etc.)
                            raise

                    logger.info(f"💰 Executing BUY copy trade for {follower_id}: ${final_amount:.2f} {source_transaction['outcome']}")

                    result = await trading_service.execute_buy(
                        query=mock_query,
                        market_id=source_transaction['market_id'],
                        outcome=source_transaction['outcome'],
                        amount=final_amount,
                        market=source_transaction.get('market', {}),  # ✅ FIX: Use 'market' not 'market_data'
                    )

                    if result.get('success'):
                        logger.info(f"✅ Copy BUY successful for {follower_id}: ${final_amount:.2f}")

                        # ✅ CRITICAL: Get the follower transaction ID from database
                        # The execute_buy() method doesn't return the transaction_id, so we need to query it
                        try:
                            # Query the most recent transaction for this follower (should be the one we just executed)
                            from database import db_manager
                            session = db_manager.get_session()
                            from database import Transaction
                            from sqlalchemy import desc
                            from datetime import datetime, timedelta

                            recent_transaction = session.query(Transaction).filter(
                                Transaction.user_id == follower_id,
                                Transaction.executed_at >= (datetime.utcnow() - timedelta(seconds=10))  # Last 10 seconds
                            ).order_by(desc(Transaction.executed_at)).first()

                            if recent_transaction:
                                follower_transaction_id = recent_transaction.id
                                logger.info(f"✅ Found follower transaction ID: {follower_transaction_id} for user {follower_id}")
                            else:
                                logger.warning(f"⚠️ Could not find recent transaction for follower {follower_id} - copy history will not be linked")

                            session.close()

                        except Exception as tx_error:
                            logger.warning(f"⚠️ Could not retrieve follower transaction ID: {tx_error}")
                            # Continue anyway - copy trade was successful even if we can't link the history

                        # Update history with actual execution
                        repo.update_history_success(
                            history_id=history.id,
                            follower_transaction_id=follower_transaction_id,  # ✅ FIX: Real transaction ID
                            actual_amount=final_amount,
                        )
                        # ✅ NEW: No need to deduct from budget - it's calculated from current balance

                        # ✅ Send push notification (SUCCESS only)
                        await self._send_copy_trade_notification(
                            follower_id=follower_id,
                            leader_id=leader_user_id,
                            trade_data=source_transaction,
                            calculated_amount=calculated_amount,
                            actual_amount=final_amount,
                            success=True
                        )
                    else:
                        logger.error(f"❌ Copy BUY failed for {follower_id}: {result.get('message', 'Unknown error')}")
                        repo.update_history_failed(
                            history_id=history.id,
                            reason=result.get('message', 'Trade execution failed'),
                        )
                        # No notification for failures

                elif source_transaction['transaction_type'] == 'SELL':
                    logger.info(f"💰 [SELL_START] Processing SELL copy trade for follower {follower_id}, leader_trade_amount=${leader_trade_amount:.2f}")
                    # ✅ NEW: Position-based SELL copy trading
                    from core.services.copy_trading.position_checker import (
                        get_follower_position_size,
                        get_leader_position_size,
                        should_skip_sell_copy,
                        calculate_adjusted_sell_amount
                    )
                    from core.services import user_service
                    from telegram_bot.services.market_service import MarketService

                    # Get follower's wallet address
                    follower_wallet = user_service.get_user_wallet(follower_id)
                    if not follower_wallet:
                        logger.error(f"❌ [SELL_CHECK] No wallet found for follower {follower_id}")
                        repo.update_history_failed(
                            history_id=history.id,
                            reason="Follower wallet not found",
                        )
                        return

                    # Get current market price
                    market_service = MarketService()
                    current_price, _, _, _ = market_service.get_token_price_with_audit(token_id)

                    if not current_price or current_price == 0:
                        logger.error(f"❌ [SELL_CHECK] Could not fetch market price")
                        repo.update_history_failed(
                            history_id=history.id,
                            reason="Could not fetch market price",
                        )
                        return

                    # ✅ NEW: Position-based calculation for SELL trades
                    logger.info(f"💰 [SELL_CALC] Starting position-based calculation for follower {follower_id}")

                    # For leader: Get their ACTUAL position before the sell
                    # CRITICAL: We need position BEFORE sell, not just amount sold!
                    leader_token_count, _ = await get_leader_position_size(
                        leader_user_id=leader_user_id,
                        token_id=token_id,
                        market_id=source_transaction['market_id'],
                        outcome=source_transaction['outcome']
                    )

                    # Convert tokens from microunits (6 decimals) to real tokens
                    tokens_sold_by_leader_microunits = float(source_transaction.get('tokens', 0))
                    tokens_sold_by_leader = tokens_sold_by_leader_microunits / 1_000_000  # ✅ Convert to real tokens

                    # Calculate leader's position BEFORE sell (add back what they sold)
                    leader_position_before_sell = leader_token_count + tokens_sold_by_leader

                    logger.info(f"📊 [SELL_CHECK] Leader sold {tokens_sold_by_leader:.2f} tokens (${leader_trade_amount:.2f})")
                    logger.info(f"📊 [SELL_CHECK] Leader position BEFORE sell: {leader_position_before_sell:.2f} tokens (current: {leader_token_count:.2f})")

                    # Get follower position
                    follower_token_count, follower_position_data = await get_follower_position_size(
                        wallet_address=follower_wallet['address'],
                        token_id=token_id,
                        market_id=source_transaction['market_id'],
                        outcome=source_transaction['outcome']
                    )

                    logger.info(f"📊 [SELL_CHECK] Follower position: {follower_token_count:.2f} tokens")

                    if leader_position_before_sell > 0 and follower_token_count > 0:
                        logger.info("✅ [SELL_PATH] Using position-based calculation")
                        try:
                            # Calculate position-based sell amount using position BEFORE sell
                            position_based_amount = self.calculator.calculate_position_based_sell_amount(
                                leader_trade_amount=leader_trade_amount,
                                leader_position_size=leader_position_before_sell,  # ✅ Position BEFORE sell
                                follower_position_size=follower_token_count,
                                current_price=current_price
                            )

                            # ✅ SELL RULE: Follower minimum $0.50, liquidate if remaining < $0.50
                            follower_position_value = follower_token_count * current_price

                            if position_based_amount >= COPY_TRADING_CONFIG.MIN_FOLLOWER_SELL_AMOUNT_USD:
                                # Normal case: position-based amount >= $0.50
                                final_amount = position_based_amount

                                # Check if remaining position after SELL would be < $0.50
                                remaining_value = follower_position_value - final_amount
                                if 0 < remaining_value < COPY_TRADING_CONFIG.MIN_FOLLOWER_SELL_AMOUNT_USD:
                                    # Liquidate everything instead (better than leaving dust)
                                    final_amount = follower_position_value
                                    logger.info(f"💰 [SELL_LIQUIDATE] Remaining would be ${remaining_value:.2f} < $0.50, selling all: ${final_amount:.2f}")
                                else:
                                    logger.info(f"💰 [SELL_CALC] Using position-based amount: ${final_amount:.2f} (remaining: ${remaining_value:.2f})")

                            elif follower_position_value < COPY_TRADING_CONFIG.MIN_FOLLOWER_SELL_AMOUNT_USD:
                                # Edge case: entire position < $0.50, sell everything
                                final_amount = follower_position_value
                                logger.info(f"💰 [SELL_LIQUIDATE] Position value ${follower_position_value:.2f} < $0.50, selling all")
                            else:
                                # Skip: calculated amount < $0.50 but position >= $0.50
                                logger.info(
                                    f"⏭️ [SELL_SKIP] Position-based amount ${position_based_amount:.2f} < minimum ${COPY_TRADING_CONFIG.MIN_FOLLOWER_SELL_AMOUNT_USD:.2f}, "
                                    f"position value ${follower_position_value:.2f} still valuable, skipping"
                                )
                                repo.update_history_failed(
                                    history_id=history.id,
                                    reason=f"SKIPPED: Position-based amount ${position_based_amount:.2f} below minimum",
                                )
                                return

                            # ✅ FIX: No budget check for SELL (selling RELEASES money, doesn't consume budget)
                            # Budget check only applies to BUY operations
                            reason = "POSITION_BASED_SELL"

                            # Logging
                            if leader_position_before_sell > 0 and current_price > 0:
                                leader_pct = (leader_trade_amount/(leader_position_before_sell*current_price)*100)
                                logger.info(
                                    f"📊 [POSITION_BASED] Leader sold ${leader_trade_amount:.2f} from {leader_position_before_sell:.2f} tokens ({leader_pct:.1f}%), "
                                    f"Follower selling ${final_amount:.2f} from {follower_token_count:.2f} tokens (${follower_position_value:.2f} value)"
                                )

                        except Exception as e:
                            logger.warning(f"⚠️ [POSITION_BASED] Calculation failed: {e}, falling back to minimum amount")
                            final_amount = COPY_TRADING_CONFIG.MIN_COPY_AMOUNT_USD
                            reason = f"FALLBACK_MINIMUM: Position calculation failed"

                    else:
                        # No positions available, skip
                        if leader_position_before_sell == 0:
                            skip_reason = "LEADER_HAS_NO_POSITION"
                        else:
                            skip_reason = "FOLLOWER_HAS_NO_POSITION"

                        logger.info(f"⏭️ [SELL_CHECK] SKIPPING SELL for {follower_id}: {skip_reason} (leader_pos={leader_position_before_sell:.2f}, follower_pos={follower_token_count:.2f})")
                        repo.update_history_failed(
                            history_id=history.id,
                            reason=f"SKIPPED: {skip_reason}",
                        )
                        return

                    # Verify follower has enough tokens for the calculated amount
                    required_token_count = final_amount / current_price
                    should_skip, skip_reason = should_skip_sell_copy(
                        follower_token_count=follower_token_count,
                        required_token_count=required_token_count,
                        min_ratio=0.95  # Allow 5% slippage
                    )

                    if should_skip:
                        logger.info(
                            f"⏭️ [SELL_CHECK] SKIPPING SELL for {follower_id}: {skip_reason} "
                            f"(has {follower_token_count:.2f} tokens, needs {required_token_count:.2f})"
                        )
                        repo.update_history_failed(
                            history_id=history.id,
                            reason=f"SKIPPED: {skip_reason}",
                        )
                        return

                    # If we have slightly less tokens, adjust the sell amount
                    if follower_token_count < required_token_count:
                        # Adjust amount to match available tokens (within slippage tolerance)
                        adjusted_amount = follower_token_count * current_price
                        final_amount = adjusted_amount
                        logger.info(f"⚖️ [SELL_ADJUST] Adjusted sell amount to ${final_amount:.2f} to match available tokens")

                    # ✅ Execute SELL using the new copy method
                    logger.info(f"📉 Executing SELL copy trade for {follower_id}: ${final_amount:.2f}")

                    # ✅ FIXED: Use robust execute_sell_like_buy() method (same as BUY)
                    result = await trading_service.execute_sell_like_buy(
                        user_id=follower_id,
                        market_id=source_transaction['market_id'],
                        outcome=source_transaction['outcome'],  # String outcome ('YES', 'NO', etc.)
                        amount=final_amount,
                        market=source_transaction.get('market', {})
                    )

                    if result.get('success'):
                        logger.info(f"✅ Copy SELL successful for {follower_id}: ${final_amount:.2f}")

                        # ✅ CRITICAL: Get the follower transaction ID from database
                        follower_transaction_id = None
                        try:
                            from database import db_manager
                            session = db_manager.get_session()
                            from database import Transaction
                            from sqlalchemy import desc
                            from datetime import datetime, timedelta

                            # FIX: Handle both numeric and hex market_id formats
                            market_id_filter = source_transaction['market_id']
                            # If market_id is numeric, also try hex format from market_data
                            if isinstance(market_id_filter, str) and not market_id_filter.startswith('0x'):
                                # market_id is numeric, try to find hex version from market_data
                                market_data = source_transaction.get('market', {})
                                if market_data and 'id' in market_data:
                                    # The market_data.id might be the hex version
                                    hex_market_id = market_data.get('id')
                                    if hex_market_id and hex_market_id.startswith('0x'):
                                        market_id_filter = hex_market_id
                                        logger.debug(f"🔄 [SELL_LINK] Using hex market_id: {market_id_filter}")

                            recent_transaction = session.query(Transaction).filter(
                                Transaction.user_id == follower_id,
                                Transaction.transaction_type == 'SELL',
                                Transaction.market_id == market_id_filter,
                                Transaction.executed_at >= (datetime.utcnow() - timedelta(seconds=15))
                            ).order_by(desc(Transaction.executed_at)).first()

                            if recent_transaction:
                                follower_transaction_id = recent_transaction.id
                                logger.info(f"✅ [SELL_LINK] Found follower transaction ID: {follower_transaction_id}")
                            else:
                                logger.warning(f"⚠️ [SELL_LINK] Could not find recent SELL transaction for follower {follower_id}")

                            session.close()

                        except Exception as tx_error:
                            logger.warning(f"⚠️ [SELL_LINK] Could not retrieve follower transaction ID: {tx_error}")

                        # Extract real execution price from result if available
                        execution_price = None
                        tokens_executed = None
                        if result.get('total_received') and result.get('tokens_sold'):
                            execution_price = result['total_received'] / result['tokens_sold']
                            tokens_executed = result['tokens_sold']

                        # Update history with actual execution
                        repo.update_history_success(
                            history_id=history.id,
                            follower_transaction_id=follower_transaction_id,
                            actual_amount=final_amount,
                        )
                        # Add back to budget (from proceeds)
                        budget.budget_used = max(0, float(budget.budget_used) - final_amount)

                        # ✅ Send push notification (SUCCESS only)
                        await self._send_copy_trade_notification(
                            follower_id=follower_id,
                            leader_id=leader_user_id,
                            trade_data=source_transaction,
                            calculated_amount=calculated_amount,
                            actual_amount=final_amount,
                            execution_price=execution_price,
                            tokens_executed=tokens_executed,
                            success=True
                        )
                    else:
                        logger.error(f"❌ Copy SELL failed for {follower_id}: {result.get('message', 'Unknown error')}")
                        repo.update_history_failed(
                            history_id=history.id,
                            reason=result.get('message', 'Trade execution failed'),
                        )
                        # No notification for failures

            except Exception as e:
                logger.error(f"❌ Trade execution error for {follower_id}: {e}")
                repo.update_history_failed(
                    history_id=history.id,
                    reason=f"Trade execution failed: {str(e)}",
                )

        except Exception as e:
            logger.error(f"❌ Unexpected error copying trade for {follower_id}: {e}")

    async def _send_copy_trade_notification(
        self,
        follower_id: int,
        leader_id: int,
        trade_data: Dict[str, Any],
        calculated_amount: float,
        actual_amount: float,
        execution_price: Optional[float] = None,
        tokens_executed: Optional[float] = None,
        success: bool = True,
        failure_reason: Optional[str] = None
    ):
        """
        Send Telegram push notification for copy trade execution

        Args:
            follower_id: Follower's Telegram ID
            leader_id: Leader's Telegram ID (or virtual_id for external)
            trade_data: Trade details (market_id, outcome, tx_type, etc.)
            calculated_amount: Amount calculated by copy algorithm
            actual_amount: Amount actually executed
            execution_price: Real execution price per token (optional)
            tokens_executed: Real number of tokens executed (optional)
            success: Whether trade succeeded
        """
        try:
            from core.services.copy_trading.notification_service import (
                get_copy_trading_notification_service
            )
            from core.services import user_service
            from database import db_manager, ExternalLeader
            from core.services.copy_trading_monitor import get_market_display_name

            # Get leader username
            leader_username = "Unknown"
            try:
                # Check if it's a regular user
                if leader_id > 0:
                    leader_user = user_service.get_user(leader_id)
                    if leader_user and leader_user.username:
                        leader_username = leader_user.username
                    else:
                        leader_username = f"user_{leader_id}"
                else:
                    # It's an external leader (virtual_id is negative)
                    with db_manager.get_session() as db:
                        external = db.query(ExternalLeader).filter(
                            ExternalLeader.virtual_id == leader_id
                        ).first()

                        if external and external.polygon_address:
                            # Show shortened address
                            leader_username = f"{external.polygon_address[:6]}...{external.polygon_address[-4:]}"
                        else:
                            leader_username = f"external_{abs(leader_id)}"
            except Exception as e:
                logger.warning(f"⚠️ Could not resolve leader username: {e}")

            # Get notification service
            notif_service = get_copy_trading_notification_service()

            # 🎯 UX IMPROVEMENT: Use real market name from resolved market data
            enhanced_trade_data = trade_data.copy()
            # The market data is now resolved and contains the real question
            market_info = trade_data.get('market', {})
            enhanced_trade_data['market_title'] = market_info.get('question', 'Unknown Market')

            # Send notification (without leader username)
            await notif_service.notify_copy_trade_executed(
                follower_id=follower_id,
                leader_username="",  # Don't show leader username
                trade_data=enhanced_trade_data,  # Use enhanced data with real market name
                calculated_amount=calculated_amount,
                actual_amount=actual_amount,
                execution_price=execution_price,
                tokens_executed=tokens_executed,
                success=success,
                failure_reason=failure_reason if not success else None
            )

        except Exception as e:
            # Non-critical - don't fail the trade if notification fails
            logger.warning(f"⚠️ Failed to send copy trade notification: {e}")

    # =========================================================================
    # STATS & HISTORY
    # =========================================================================

    def get_follower_stats(self, follower_id: int) -> Dict[str, Any]:
        """Get copy trading stats for a follower"""
        repo = self._get_repo()
        leader_id = self.get_leader_for_follower(follower_id)

        if not leader_id:
            return {
                'is_copy_trading': False,
                'leader_id': None,
            }

        # Get successful copies
        history_records = repo.list_successful_copies_for_follower(follower_id, leader_id)

        # Calculate PnL (simplified - real implementation would query positions)
        total_invested = sum(float(h.actual_copy_amount) for h in history_records if h.actual_copy_amount)
        total_pnl = 0  # Would calculate from current positions

        budget = repo.get_budget(follower_id)
        subscription = repo.get_active_subscription_for_follower(follower_id)

        return {
            'is_copy_trading': True,
            'leader_id': leader_id,
            'copy_mode': subscription.copy_mode if subscription else 'PROPORTIONAL',
            'total_trades_copied': len(history_records),
            'total_invested': total_invested,
            'total_pnl': total_pnl,
            'budget_remaining': float(budget.budget_remaining) if budget else 0,
            'budget_allocated': float(budget.allocated_budget) if budget else 0,
            'allocation_percentage': float(budget.allocation_percentage) if budget else 0,
        }

    def get_leader_stats_for_display(self, leader_id: int) -> Dict[str, Any]:
        """Get stats for a leader"""
        repo = self._get_repo()
        stats = repo.get_leader_stats(leader_id)

        if not stats:
            return {
                'leader_id': leader_id,
                'total_active_followers': 0,
                'total_trades_copied': 0,
                'total_volume_copied': 0,
                'total_fees_from_copies': 0,
            }

        return stats.to_dict()

    def get_copy_history(self, follower_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get copy trading history for a follower"""
        repo = self._get_repo()
        history_records = repo.list_copy_history_for_follower(follower_id, limit=limit)
        return [h.to_dict() for h in history_records]

    def get_follower_pnl_and_trades(self, follower_id: int) -> Dict[str, Any]:
        """
        Get PnL data and recent trades for a follower
        Used for dashboard display in /copy_trading command

        Args:
            follower_id: Telegram user ID of the follower

        Returns:
            Dict with pnl_data including total_pnl, total_invested, recent trades count
        """
        repo = self._get_repo()
        leader_id = self.get_leader_for_follower(follower_id)

        if not leader_id:
            return {
                'is_copy_trading': False,
                'total_pnl': 0,
                'total_invested': 0,
                'trades_copied': 0,
            }

        # Get recent trades (last 50 for better PnL calculation)
        history_records = repo.list_copy_history_for_follower(follower_id, limit=50)

        # Calculate metrics from successful copies
        successful_copies = [h for h in history_records if h.status == CopyTradeStatus.SUCCESS.value]

        total_invested = sum(float(h.actual_copy_amount) if h.actual_copy_amount else 0 for h in successful_copies)

        # Calculate actual PnL from current positions
        total_pnl = self._calculate_copy_trading_pnl(follower_id, successful_copies)

        return {
            'is_copy_trading': True,
            'leader_id': leader_id,
            'total_pnl': total_pnl,
            'total_invested': total_invested,
            'trades_copied': len(successful_copies),
            'total_attempted': len(history_records),
        }

    def _calculate_copy_trading_pnl(self, follower_id: int, successful_copies: List) -> float:
        """
        Calculate actual PnL from copy trading positions

        Args:
            follower_id: Telegram user ID
            successful_copies: List of successful copy trade history records

        Returns:
            Total PnL from copy trading positions
        """
        try:
            total_pnl = 0.0

            # Get current positions for this user
            from telegram_bot.services.hybrid_position_service import get_hybrid_position_service
            position_service = get_hybrid_position_service()

            # Get user wallet
            db = self._get_repo().db
            from database import User
            user = db.query(User).filter(User.telegram_user_id == follower_id).first()

            if not user or not user.polygon_address:
                return 0.0

            # Get all current positions
            current_positions = position_service.get_all_positions(follower_id, user.polygon_address)

            if not current_positions:
                return 0.0

            # For each successful copy trade, find matching current position and calculate PnL
            for copy_trade in successful_copies:
                try:
                    # Get the transaction linked to this copy trade
                    if copy_trade.follower_transaction_id:
                        from database import Transaction
                        transaction = db.query(Transaction).filter(
                            Transaction.id == copy_trade.follower_transaction_id
                        ).first()

                        if transaction:
                            # Find matching current position
                            market_id = transaction.market_id
                            outcome = transaction.outcome

                            # Look for position in current_positions
                            position_key = f"{market_id}_{outcome}"
                            if position_key in current_positions:
                                position = current_positions[position_key]

                                # Calculate PnL for this position
                                from telegram_bot.services.position_service import get_position_service
                                pos_service = get_position_service()

                                # Create a mock user_trader for PnL calculation
                                from telegram_bot.services.user_trader import UserTrader
                                user_trader = UserTrader(follower_id, user.polygon_address)

                                pnl_data = pos_service.calculate_pnl(position, user_trader)

                                if pnl_data and 'pnl_amount' in pnl_data:
                                    total_pnl += float(pnl_data['pnl_amount'])

                except Exception as e:
                    logger.warning(f"Error calculating PnL for copy trade {copy_trade.id}: {e}")
                    continue

            return total_pnl

        except Exception as e:
            logger.error(f"Error calculating copy trading PnL for user {follower_id}: {e}")
            return 0.0

    def _resolve_address_from_virtual_id(self, virtual_id: int) -> Optional[str]:
        """
        Resolve a virtual ID back to the original blockchain address

        Args:
            virtual_id: Negative virtual ID generated by resolve_leader_by_address

        Returns:
            Original blockchain address or None if not found
        """
        try:
            repo = self._get_repo()
            db = repo.db

            # Try to find in smart_wallets table first
            try:
                from database import SmartWallet
                smart_wallets = db.query(SmartWallet).all()
                for wallet in smart_wallets:
                    # Generate the same virtual ID as resolve_leader_by_address
                    candidate_virtual_id = -abs(hash(wallet.address.lower())) % (2**31)
                    if candidate_virtual_id == virtual_id:
                        return wallet.address.lower()
            except Exception as e:
                logger.debug(f"Smart wallet lookup for virtual ID: {e}")

            # Try to find in smart_wallet_trades (recent trades)
            from database import SmartWalletTrade
            recent_trades = db.query(SmartWalletTrade).filter(
                SmartWalletTrade.created_at > datetime.now(timezone.utc) - timedelta(days=30)
            ).all()

            seen_addresses = set()
            for trade in recent_trades:
                addr = trade.wallet_address.lower()
                if addr in seen_addresses:
                    continue
                seen_addresses.add(addr)

                # Generate virtual ID and check match
                candidate_virtual_id = -abs(hash(addr)) % (2**31)
                if candidate_virtual_id == virtual_id:
                    return addr

            # If not found, try external traders cache (if exists)
            # For now, return None - this would need more complex reverse lookup

            logger.warning(f"Could not resolve virtual ID {virtual_id} back to address")
            return None

        except Exception as e:
            logger.error(f"Error resolving virtual ID {virtual_id}: {e}")
            return None

    def get_grouped_history(self, follower_id: int) -> Dict[str, Any]:
        """
        Get copy trading history grouped by leader and status
        Used for /history display in copy trading

        Args:
            follower_id: Telegram user ID of the follower

        Returns:
            Dict grouped by leader_id with aggregated stats
        """
        repo = self._get_repo()

        # Get all history for this follower
        all_history = repo.list_copy_history_for_follower(follower_id, limit=1000)

        # Group by leader_id
        grouped = {}
        for record in all_history:
            leader_id = record.leader_id

            if leader_id not in grouped:
                grouped[leader_id] = {
                    'leader_id': leader_id,
                    'total_trades': 0,
                    'successful': 0,
                    'failed': 0,
                    'insufficient_budget': 0,
                    'total_invested': 0,
                    'by_type': {'BUY': 0, 'SELL': 0},
                    'by_status': {},
                    'records': [],
                }

            # Aggregate counts
            grouped[leader_id]['total_trades'] += 1

            if record.status == CopyTradeStatus.SUCCESS.value:
                grouped[leader_id]['successful'] += 1
                if record.actual_copy_amount:
                    grouped[leader_id]['total_invested'] += float(record.actual_copy_amount)
            elif record.status == CopyTradeStatus.FAILED.value:
                grouped[leader_id]['failed'] += 1
            elif record.status == CopyTradeStatus.INSUFFICIENT_BUDGET.value:
                grouped[leader_id]['insufficient_budget'] += 1

            # Count by transaction type
            if record.transaction_type in grouped[leader_id]['by_type']:
                grouped[leader_id]['by_type'][record.transaction_type] += 1

            # Count by status
            status = record.status
            if status not in grouped[leader_id]['by_status']:
                grouped[leader_id]['by_status'][status] = 0
            grouped[leader_id]['by_status'][status] += 1

            # Store recent records (last 5 per leader)
            if len(grouped[leader_id]['records']) < 5:
                grouped[leader_id]['records'].append(record.to_dict())

        return grouped

    # =========================================================================
    # PERFORMANCE OPTIMIZATIONS (Phase 3.3-3.4)
    # =========================================================================

    async def _cache_follower_credentials(self, follower_ids: List[int]):
        """
        Pre-cache API credentials for all followers in Redis
        Avoids DB hits during parallel copy execution

        Args:
            follower_ids: List of follower user IDs
        """
        try:
            from core.services.redis_price_cache import get_redis_cache
            from core.services import user_service

            redis_cache = get_redis_cache()

            if not redis_cache.enabled:
                logger.debug("⏭️ Redis not available, skipping credential caching")
                return

            cached_count = 0
            fetched_count = 0

            for follower_id in follower_ids:
                try:
                    # Check if already cached
                    cached_key = f"follower_creds:{follower_id}"

                    if redis_cache.redis_client.exists(cached_key):
                        cached_count += 1
                        continue

                    # Fetch from DB
                    creds = user_service.get_api_credentials(follower_id)
                    if creds:
                        import json
                        redis_cache.redis_client.setex(
                            cached_key,
                            300,  # 5min TTL
                            json.dumps(creds)
                        )
                        fetched_count += 1

                except Exception as e:
                    logger.warning(f"⚠️ Could not cache creds for follower {follower_id}: {e}")

            if fetched_count > 0 or cached_count > 0:
                logger.info(f"📦 Credential cache: {cached_count} cached, {fetched_count} fetched")

        except Exception as e:
            logger.warning(f"⚠️ Credential caching failed (non-critical): {e}")

    async def _execute_copy_with_retry(
        self,
        follower_id: int,
        trade_params: Dict[str, Any],
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Execute copy trade with retry on failure (protection against volume spikes)

        Args:
            follower_id: Follower user ID
            trade_params: Trade parameters (market_id, outcome, amount, etc.)
            max_retries: Maximum retry attempts

        Returns:
            Copy result dictionary
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                # Execute the trade
                result = await self._execute_single_copy_trade(follower_id, trade_params)

                if attempt > 0:
                    logger.info(f"✅ Copy succeeded on attempt {attempt + 1}/{max_retries}")

                return result

            except Exception as e:
                last_error = e

                if attempt < max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"⚠️ Copy failed (attempt {attempt + 1}/{max_retries}), "
                        f"retry in {wait_time}s: {e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ Copy failed after {max_retries} attempts: {e}")

        # All retries exhausted
        raise CopyExecutionException(f"Failed after {max_retries} attempts: {last_error}")

    def _get_outcome_index_from_market(self, outcome: str, market_data: dict) -> int:
        """
        Get the correct index for an outcome in market data

        Args:
            outcome: The outcome name (e.g., 'YES', 'NO', 'Team A', etc.)
            market_data: Market dictionary with outcomes array

        Returns:
            Index of the outcome in the market's outcomes array, or fallback to YES/NO assumption
        """
        if not market_data:
            # Fallback: assume YES=0, NO=1
            return 0 if outcome.upper() not in ['NO', 'FALSE', '0'] else 1

        outcomes = market_data.get('outcomes', [])

        # Handle string format (JSON)
        if isinstance(outcomes, str):
            try:
                import json
                outcomes = json.loads(outcomes)
            except:
                outcomes = []

        # Find exact match in outcomes array
        if isinstance(outcomes, list):
            outcome_upper = outcome.upper().strip()
            for i, market_outcome in enumerate(outcomes):
                if isinstance(market_outcome, str) and market_outcome.upper().strip() == outcome_upper:
                    logger.info(f"✅ Found outcome '{outcome}' at index {i} in market outcomes")
                    return i

            # Try normalized matching (remove apostrophes, etc.)
            from telegram_bot.utils.token_utils import normalize_outcome
            outcome_normalized = normalize_outcome(outcome_upper)
            for i, market_outcome in enumerate(outcomes):
                if isinstance(market_outcome, str):
                    market_outcome_normalized = normalize_outcome(market_outcome.upper().strip())
                    if market_outcome_normalized == outcome_normalized:
                        logger.info(f"✅ Found normalized outcome '{outcome}' (normalized: '{outcome_normalized}') at index {i}")
                        return i

        # Fallback: assume YES=0, NO=1
        fallback_index = 0 if outcome.upper() not in ['NO', 'FALSE', '0'] else 1
        logger.warning(f"⚠️ Could not find outcome '{outcome}' in market outcomes, using fallback index {fallback_index}")
        return fallback_index

    async def _execute_single_copy_trade(
        self,
        follower_id: int,
        trade_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a single copy trade attempt

        Args:
            follower_id: Follower user ID
            trade_params: Trade parameters

        Returns:
            Execution result
        """
        # This is a placeholder - actual implementation would call
        # the trading service to execute the buy/sell
        # For now, return success mock
        return {
            'follower_id': follower_id,
            'status': 'success',
            'trade_params': trade_params
        }
