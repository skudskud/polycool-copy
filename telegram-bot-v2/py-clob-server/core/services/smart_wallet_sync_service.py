"""
Smart Wallet Sync Service
Syncs tracked_leader_trades (smart wallet trades) → smart_wallet_trades for UI
Runs every 60s to keep UI table optimized and fresh

Architecture:
    subsquid_user_transactions (on-chain fills)
        ↓ [Filter job - 60s]
    tracked_leader_trades (where is_smart_wallet=true)
        ↓ [Sync job - 60s]
    smart_wallet_trades (UI display, optimized)
        ↓
    /smart_trading command display
"""

import logging
import json
import asyncio
from typing import Tuple, List, Dict, Optional
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from database import db_manager, TrackedLeaderTrade
from core.persistence.models import SmartWalletTrade
from core.services.market_data_layer import MarketDataLayer

logger = logging.getLogger(__name__)


class SmartWalletSyncService:
    """Syncs smart wallet trades to dedicated UI table"""

    def __init__(self):
        self.last_sync_timestamp = None
        self.invalid_trade_count = 0
        self.total_trade_count = 0
        # Initialize market data layer for title lookups
        import os
        use_subsquid = os.getenv('USE_SUBSQUID_MARKETS', 'false').lower() == 'true'
        self.market_data_layer = MarketDataLayer(use_subsquid=use_subsquid)

        # Track active notification tasks to prevent memory leaks
        self._active_notification_tasks = set()

    def _token_id_to_condition_id(self, token_id_str: str) -> Optional[str]:
        """
        Convert token ID (decimal) to condition ID (0x format)

        Token ID is the decimal representation of condition ID.
        Example: "13270961618826476..." → "0x1d57191c9ef1e72a..."

        Args:
            token_id_str: Token ID as decimal string

        Returns:
            Condition ID in 0x format, or None if conversion fails
        """
        try:
            if not token_id_str:
                return None

            # Convert decimal string to integer
            token_id_int = int(token_id_str)

            # Convert to hex and pad to 64 chars (32 bytes)
            hex_str = hex(token_id_int)[2:]  # Remove '0x' prefix
            condition_id = "0x" + hex_str.zfill(64)

            return condition_id
        except (ValueError, TypeError) as e:
            logger.error(f"[SMART_SYNC] Error converting token_id to condition_id: {e}")
            return None

    def _get_market_title(self, position_id: str) -> Optional[str]:
        """
        Get market title using DUAL lookup strategy for maximum coverage

        Strategy 1: Search clob_token_ids JSONB array (finds markets by token_id)
        Strategy 2: Convert to condition_id and lookup (faster for markets with condition_id indexed)

        Args:
            position_id: Token ID (decimal string from subsquid)

        Returns:
            Market title or None
        """
        try:
            with db_manager.get_session() as db:
                from sqlalchemy import text
                from database import SubsquidMarketPoll

                # STRATEGY 1: Search clob_token_ids JSONB array
                # This finds markets where position_id is in the clob_token_ids array
                # Works for ALL markets, including ones not indexed by condition_id
                try:
                    query = text("""
                        SELECT title
                        FROM subsquid_markets_poll
                        WHERE clob_token_ids::jsonb ? :token_id
                        LIMIT 1
                    """)

                    result = db.execute(query, {'token_id': position_id})
                    row = result.fetchone()

                    if row and row[0]:
                        logger.debug(f"[SMART_SYNC] Found market title via clob_token_ids: {row[0][:50]}...")
                        return row[0]
                except Exception as e:
                    logger.debug(f"[SMART_SYNC] clob_token_ids search failed: {e}")

                # STRATEGY 2: Fallback to condition_id lookup
                condition_id = self._token_id_to_condition_id(position_id)
                if condition_id:
                    market = db.query(SubsquidMarketPoll).filter(
                        SubsquidMarketPoll.condition_id == condition_id
                    ).first()

                    if market and market.title:
                        logger.debug(f"[SMART_SYNC] Found market title via condition_id: {market.title[:50]}...")
                        return market.title

            logger.debug(f"[SMART_SYNC] No market found for position_id {position_id[:20]}...")
            return None

        except Exception as e:
            logger.warning(f"❌ [SMART_SYNC] Failed to get market title for position_id {position_id[:20]}...: {e}")
            return None

    async def sync_single_trade_instant(self, trade_id: str) -> bool:
        """
        Sync a single trade immediately (webhook-triggered)
        
        This method is called by the webhook receiver for instant synchronization
        instead of waiting for the next polling cycle.
        
        Args:
            trade_id: Transaction ID from tracked_leader_trades
            
        Returns:
            True if successfully synced, False otherwise
        """
        try:
            logger.info(f"⚡ [SMART_SYNC_INSTANT] Syncing trade {trade_id[:16]}... instantly")
            
            with db_manager.get_session() as db:
                # Query the specific trade from tracked_leader_trades
                trade = db.query(TrackedLeaderTrade).filter(
                    TrackedLeaderTrade.tx_id == trade_id,
                    TrackedLeaderTrade.is_smart_wallet == True
                ).first()
                
                if not trade:
                    logger.warning(f"[SMART_SYNC_INSTANT] Trade {trade_id[:16]}... not found or not a smart wallet trade")
                    return False
                
                # Check if already synced
                existing = db.query(SmartWalletTrade).filter(
                    SmartWalletTrade.id == trade.tx_id
                ).first()
                
                if existing:
                    logger.debug(f"[SMART_SYNC_INSTANT] Trade {trade_id[:16]}... already synced, skipping")
                    return True
                
                # Validate trade
                is_valid, reason = await self._validate_trade_data(trade)
                
                if not is_valid:
                    logger.warning(f"⚠️ [SMART_SYNC_INSTANT] Trade {trade_id[:16]}... is invalid: {reason}")
                    # Log to invalid trades table
                    self._log_invalid_trades(db, [(trade, reason)])
                    return False
                
                # Upsert to smart_wallet_trades
                count = await self._upsert_smart_wallet_trades(db, [trade])
                
                if count > 0:
                    logger.info(f"✅ [SMART_SYNC_INSTANT] Trade {trade_id[:16]}... synced successfully")
                    
                    # Trigger unified notifications (non-blocking)
                    try:
                        from core.services.unified_smart_trade_notifier import get_unified_notifier
                        notifier = get_unified_notifier()
                        
                        # Query for trade - try BOTH with and without suffix for best quality data
                        # Webhook creates: 0xabc...123_456 (WITH suffix, instant)
                        # Polling creates: 0xabc...123 (NO suffix, 3min later, better data)
                        base_tx_id = trade.tx_id.split('_')[0] if '_' in trade.tx_id else trade.tx_id

                        # Strategy: Prefer entry with is_first_time=TRUE (better quality)
                        synced_trade = db.query(SmartWalletTrade).filter(
                            SmartWalletTrade.id.in_([trade.tx_id, base_tx_id])
                        ).filter(
                            SmartWalletTrade.is_first_time == True  # Prefer first-time entries
                        ).order_by(
                            SmartWalletTrade.created_at.desc()  # Prefer newer if multiple
                        ).first()

                        # Fallback: Get any matching entry (with or without suffix)
                        if not synced_trade:
                            synced_trade = db.query(SmartWalletTrade).filter(
                                SmartWalletTrade.id.in_([trade.tx_id, base_tx_id])
                            ).order_by(
                                SmartWalletTrade.created_at.desc()
                        ).first()
                        
                        if synced_trade:
                            logger.debug(
                                f"🔔 [SMART_SYNC_INSTANT] Found trade for webhook: "
                                f"id={synced_trade.id[:16]}..., is_first_time={synced_trade.is_first_time}, "
                                f"has_market={bool(synced_trade.market_question)}"
                            )
                            
                            # UNIFIED: Webhook notifications now handled by UnifiedPushNotificationProcessor
                            # which reads from smart_wallet_trades_to_share table every 30 seconds
                            # No need for instant webhook-based notifications here
                            logger.debug(f"✅ [SMART_SYNC_INSTANT] Trade synced, will be processed by unified notification system")
                        else:
                            logger.warning(f"⚠️ [SMART_SYNC_INSTANT] No matching trade found for webhook {trade_id[:16]}...")

                    except Exception as notif_error:
                        logger.error(f"❌ [SMART_SYNC_INSTANT] Sync error: {notif_error}")
                        import traceback
                        logger.error(traceback.format_exc())
                    
                    return True
                else:
                    logger.error(f"❌ [SMART_SYNC_INSTANT] Failed to sync trade {trade_id[:16]}...")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ [SMART_SYNC_INSTANT] Error syncing trade {trade_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def run_sync_cycle(self):
        """Sync tracked_leader_trades (smart wallets) → smart_wallet_trades (POLLING BACKUP)"""
        sync_start_time = datetime.now(timezone.utc)

        try:
            logger.info("🔄 [SMART_SYNC] Starting smart wallet sync cycle (polling backup)...")

            with db_manager.get_session() as db:
                # Get last synced timestamp
                last_sync = db.query(func.max(SmartWalletTrade.timestamp)).scalar()
                last_sync = last_sync or datetime(2020, 1, 1, tzinfo=timezone.utc)

                # Query new smart wallet trades from tracked_leader_trades
                new_trades = db.query(TrackedLeaderTrade).filter(
                    TrackedLeaderTrade.is_smart_wallet == True,
                    TrackedLeaderTrade.timestamp > last_sync
                ).order_by(TrackedLeaderTrade.timestamp.asc()).all()

                if not new_trades:
                    logger.debug("[SMART_SYNC] No new smart wallet trades to sync")
                    return

                logger.info(f"📥 [SMART_SYNC] Processing {len(new_trades)} new smart wallet trades")

                # Validate and separate valid from invalid trades
                valid_trades, invalid_trades = await self._validate_and_separate_trades(new_trades)

                # Log invalid trades for monitoring
                if invalid_trades:
                    invalid_rate = len(invalid_trades) / len(new_trades) * 100
                    logger.warning(
                        f"⚠️ [SMART_SYNC] {len(invalid_trades)}/{len(new_trades)} trades have invalid data ({invalid_rate:.1f}%)"
                    )

                    # Alert if >10% invalid
                    if invalid_rate > 10:
                        logger.critical(
                            f"🚨 [SMART_SYNC] HIGH INVALID RATE: {invalid_rate:.1f}% - Check Subsquid data quality!"
                        )

                    # Log invalid trades to dead letter queue
                    self._log_invalid_trades(db, invalid_trades)

                # Upsert valid trades only (don't let bad data block good data)
                synced = 0
                if valid_trades:
                    synced = self._upsert_smart_wallet_trades(db, valid_trades)
                    logger.info(f"✅ [SMART_SYNC] Sync complete: {synced}/{len(valid_trades)} valid trades synced")

                # Log sync metrics
                sync_duration_ms = int((datetime.now(timezone.utc) - sync_start_time).total_seconds() * 1000)
                self._log_sync_metrics(
                    db,
                    sync_timestamp=sync_start_time,
                    trades_received=len(new_trades),
                    trades_valid=len(valid_trades),
                    trades_invalid=len(invalid_trades),
                    invalid_reasons=[reason for _, reason in invalid_trades],
                    sync_duration_ms=sync_duration_ms
                )

                if invalid_trades and not valid_trades:
                    logger.error(f"❌ [SMART_SYNC] All {len(invalid_trades)} trades were invalid - NO DATA SYNCED")

        except Exception as e:
            logger.error(f"❌ [SMART_SYNC] Smart wallet sync error: {e}", exc_info=True)

            # Log error to metrics
            with db_manager.get_session() as db:
                sync_duration_ms = int((datetime.now(timezone.utc) - sync_start_time).total_seconds() * 1000)
                self._log_sync_metrics(
                    db,
                    sync_timestamp=sync_start_time,
                    trades_received=0,
                    trades_valid=0,
                    trades_invalid=0,
                    invalid_reasons=[],
                    sync_duration_ms=sync_duration_ms,
                    error_message=str(e)
                )

    async def _validate_trade_data(self, trade: TrackedLeaderTrade) -> Tuple[bool, str]:
        """
        Validate that a trade has all required fields with valid data

        Args:
            trade: TrackedLeaderTrade object from database

        Returns:
            Tuple of (is_valid, error_reason)
        """
        # Check required fields for NULL
        if trade.tx_id is None or trade.tx_id == '':
            return False, "Missing or empty tx_id"

        if trade.user_address is None or trade.user_address == '':
            return False, "Missing or empty user_address"

        if trade.market_id is None or trade.market_id == '':
            return False, "Missing or empty market_id"

        if trade.tx_type is None or trade.tx_type == '':
            return False, "Missing or empty tx_type (side)"

        # Check price - try to fetch real price for smart wallets
        if trade.price is None:
            # Try to get real price from Polymarket API
            real_price = await self._fetch_real_price_for_trade(trade)
            if real_price is not None:
                trade.price = real_price
                logger.info(f"✅ [SMART_SYNC] Fetched real price ${real_price} for trade {trade.tx_id[:16]}")
            else:
                # Fallback to default price
                logger.warning(f"⚠️ [SMART_SYNC] Could not fetch real price for trade {trade.tx_id[:16]} - using default")
                trade.price = Decimal('0.50')  # Default 50¢ for smart wallets without price data
                trade._price_is_default = True  # Mark for special handling
        else:
            # Check price is valid number
            try:
                price_val = float(trade.price)
                if price_val < 0:
                    return False, "Negative price"
                if price_val == 0:
                    return False, "Zero price"
            except (TypeError, ValueError):
                return False, "Invalid price format"

        # Check amount (size)
        if trade.amount is None:
            return False, "NULL amount"

        try:
            amount_val = float(trade.amount)
            if amount_val <= 0:
                return False, "Invalid amount (<=0)"
        except (TypeError, ValueError):
            return False, "Invalid amount format"

        # Check timestamp
        if trade.timestamp is None:
            return False, "NULL timestamp"

        return True, "OK"

    async def _validate_and_separate_trades(
        self,
        trades: List[TrackedLeaderTrade]
    ) -> Tuple[List[TrackedLeaderTrade], List[Tuple[TrackedLeaderTrade, str]]]:
        """
        Validate trades and separate valid from invalid

        Args:
            trades: List of TrackedLeaderTrade objects

        Returns:
            Tuple of (valid_trades, invalid_trades_with_reasons)
        """
        valid_trades = []
        invalid_trades = []

        for trade in trades:
            is_valid, reason = await self._validate_trade_data(trade)

            if is_valid:
                valid_trades.append(trade)
            else:
                invalid_trades.append((trade, reason))
                trade_id_short = trade.tx_id[:16] if trade.tx_id else 'UNKNOWN'
                logger.warning(f"⚠️ [SMART_SYNC] Invalid trade {trade_id_short}: {reason}")

        return valid_trades, invalid_trades

    def _log_invalid_trades(self, db: Session, invalid_trades: List[Tuple[TrackedLeaderTrade, str]]):
        """
        Log invalid trades to dead letter queue for investigation

        Args:
            db: Database session
            invalid_trades: List of (trade, error_reason) tuples
        """
        try:
            for trade, reason in invalid_trades:
                # Convert trade to dict for JSONB storage
                trade_data = {
                    'tx_id': trade.tx_id,
                    'user_address': trade.user_address,
                    'market_id': trade.market_id,
                    'tx_type': trade.tx_type,
                    'outcome': trade.outcome,
                    'price': str(trade.price) if trade.price is not None else None,
                    'amount': str(trade.amount) if trade.amount is not None else None,
                    'timestamp': trade.timestamp.isoformat() if trade.timestamp else None,
                    'is_smart_wallet': trade.is_smart_wallet
                }

                # Insert into invalid trades table
                db.execute(
                    text("""
                        INSERT INTO smart_wallet_trades_invalid
                        (trade_data, error_reason, received_at)
                        VALUES (:trade_data, :error_reason, :received_at)
                    """),
                    {
                        'trade_data': json.dumps(trade_data),
                        'error_reason': reason,
                        'received_at': datetime.now(timezone.utc)
                    }
                )

            db.commit()
            logger.info(f"📝 [SMART_SYNC] Logged {len(invalid_trades)} invalid trades to dead letter queue")

        except Exception as e:
            logger.error(f"❌ [SMART_SYNC] Error logging invalid trades: {e}")
            db.rollback()

    def _log_sync_metrics(
        self,
        db: Session,
        sync_timestamp: datetime,
        trades_received: int,
        trades_valid: int,
        trades_invalid: int,
        invalid_reasons: List[str],
        sync_duration_ms: int,
        error_message: str = None
    ):
        """
        Log sync metrics for monitoring and analysis

        Args:
            db: Database session
            sync_timestamp: When sync started
            trades_received: Total trades received
            trades_valid: Number of valid trades
            trades_invalid: Number of invalid trades
            invalid_reasons: List of validation error reasons
            sync_duration_ms: Sync duration in milliseconds
            error_message: Optional error message if sync failed
        """
        try:
            # Count invalid reasons by type
            reason_counts = {}
            for reason in invalid_reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            db.execute(
                text("""
                    INSERT INTO smart_wallet_sync_metrics
                    (sync_timestamp, trades_received, trades_valid, trades_invalid,
                     invalid_reasons, sync_duration_ms, error_message)
                    VALUES (:sync_timestamp, :trades_received, :trades_valid, :trades_invalid,
                            :invalid_reasons, :sync_duration_ms, :error_message)
                """),
                {
                    'sync_timestamp': sync_timestamp,
                    'trades_received': trades_received,
                    'trades_valid': trades_valid,
                    'trades_invalid': trades_invalid,
                    'invalid_reasons': json.dumps(reason_counts),
                    'sync_duration_ms': sync_duration_ms,
                    'error_message': error_message
                }
            )

            db.commit()

        except Exception as e:
            logger.error(f"❌ [SMART_SYNC] Error logging sync metrics: {e}")
            db.rollback()

    def _calculate_is_first_time(self, db: Session, tracked: 'TrackedLeaderTrade') -> bool:
        """
        Calculate if this is wallet's first time trading this market

        Checks for any previous trades by this wallet in this market (by condition_id)

        Args:
            db: Database session
            tracked: Trade to check

        Returns:
            True if first-time entry into this market, False if repeat trade
        """
        try:
            # Convert to condition_id for accurate market matching
            condition_id = self._token_id_to_condition_id(tracked.market_id)
            if not condition_id:
                # Can't determine, default to True (safer for notifications)
                logger.debug(f"[SMART_SYNC] No condition_id for {tracked.tx_id[:16]}, defaulting is_first_time=True")
                return True

            # Check for previous trades in this market by this wallet
            previous_count = db.query(SmartWalletTrade).filter(
                SmartWalletTrade.wallet_address == tracked.user_address.lower(),
                SmartWalletTrade.condition_id == condition_id,
                SmartWalletTrade.timestamp < tracked.timestamp
            ).count()

            is_first = (previous_count == 0)

            logger.debug(
                f"[SMART_SYNC] Trade {tracked.tx_id[:16]}... is_first_time={is_first} "
                f"(found {previous_count} previous trades in market {condition_id[:10]}...)"
            )

            return is_first

        except Exception as e:
            logger.error(f"[SMART_SYNC] Error calculating is_first_time: {e}")
            return True  # Default to first-time on error (safer for notifications)

    async def _upsert_smart_wallet_trades(
        self,
        db: Session,
        tracked_trades: list
    ) -> int:
        """
        Upsert tracked trades into smart_wallet_trades

        DEDUPLICATION: If webhook entry exists (WITH _XXX suffix), UPDATE it instead of creating duplicate
        This prevents duplicate entries and ensures polling validates/enriches webhook data
        """
        try:
            count = 0

            for tracked in tracked_trades:
                # Calculate value - use amount_usdc (exact USD amount) if available, fallback to calculation
                if tracked.amount_usdc is not None and tracked.amount_usdc > 0:
                    # Use exact USDC amount from Subsquid (preferred)
                    calculated_value = tracked.amount_usdc
                    logger.debug(f"💰 [SMART_SYNC] Using amount_usdc ${calculated_value} for trade {tracked.tx_id[:16]}")
                else:
                    # Fallback to calculation for old data without amount_usdc
                    price_is_default = getattr(tracked, '_price_is_default', False)
                    if price_is_default or tracked.price == Decimal('0.50'):
                        # For default prices, use amount as approximate value
                        calculated_value = tracked.amount if tracked.amount else Decimal('0')
                        logger.debug(f"📊 [SMART_SYNC] Using amount as value for default price trade {tracked.tx_id[:16]}")
                    else:
                        calculated_value = tracked.amount * tracked.price if (tracked.amount and tracked.price) else None
                        logger.debug(f"🧮 [SMART_SYNC] Calculated value ${calculated_value} for trade {tracked.tx_id[:16]}")

                # Calculate is_first_time (check if wallet has traded this market before)
                is_first_time = self._calculate_is_first_time(db, tracked)

                # Get market title for display
                market_title = self._get_market_title(tracked.market_id)

                # Calculate condition_id
                condition_id = self._token_id_to_condition_id(tracked.market_id)

                # 🆕 DEDUPLICATION: Check if webhook entry exists (to avoid duplicates)
                # Webhook creates: 0xabc...123_456 (WITH suffix)
                # Polling should UPDATE it, not create duplicate WITHOUT suffix
                # FIX: Use FULL tx_id (don't strip suffix) to match exact entry
                full_tx_id = tracked.tx_id  # Keep the full ID with suffix intact

                existing_entry = db.query(SmartWalletTrade).filter(
                    SmartWalletTrade.id == full_tx_id  # Exact match
                ).first()

                if existing_entry:
                    # UPDATE existing webhook entry with validated/enriched data from polling
                    logger.debug(f"[SMART_SYNC] Updating existing entry {existing_entry.id[:16]}... with polling data")

                    # 🚀 NEW: Resolve position_id and outcome using copy_trading_monitor logic
                    position_id_resolved = None
                    outcome_resolved = None
                    market_title_resolved = None

                    # Calculate position_id from market_id (condition_id) and outcome
                    if tracked.market_id and str(tracked.market_id).isdigit():
                        try:
                            # Use same formula as indexer: token_id = condition_id * 2 + outcome
                            position_id_resolved = str(int(tracked.market_id) * 2 + tracked.outcome)

                            # Use monitor service to resolve outcome correctly
                            from core.services.copy_trading_monitor import get_copy_trading_monitor
                            monitor = get_copy_trading_monitor()
                            resolution = await monitor._resolve_market_by_position_id(position_id_resolved)

                            if resolution:
                                outcome_resolved = resolution['outcome']  # Real outcome from market data
                                market_title_resolved = resolution['market_title']
                                logger.debug(f"✅ [SMART_SYNC] Resolved outcome via position_id: {outcome_resolved}")
                            else:
                                # Fallback to old logic if resolution fails
                                outcome_resolved = 'YES' if tracked.outcome == 1 else 'NO' if tracked.outcome == 0 else None
                                logger.warning(f"⚠️ [SMART_SYNC] Could not resolve position_id, using fallback outcome: {outcome_resolved}")
                        except Exception as e:
                            logger.warning(f"⚠️ [SMART_SYNC] Position resolution failed: {e}")
                            outcome_resolved = 'YES' if tracked.outcome == 1 else 'NO' if tracked.outcome == 0 else None
                    else:
                        # Fallback for non-numeric market_id
                        outcome_resolved = 'YES' if tracked.outcome == 1 else 'NO' if tracked.outcome == 0 else None

                    # Update with calculated/enriched values (polling has better data)
                    existing_entry.position_id = position_id_resolved  # ✅ Store real token_id
                    existing_entry.outcome = outcome_resolved  # ✅ Correct outcome from resolution
                    existing_entry.is_first_time = is_first_time  # ✅ Correct value from calculation
                    existing_entry.market_question = market_title_resolved or market_title or existing_entry.market_question  # ✅ Enrich if available
                    # Keep webhook's condition_id (it's correct), but add if missing
                    if not existing_entry.condition_id:
                        existing_entry.condition_id = condition_id

                    db.add(existing_entry)
                    count += 1
                else:
                    # CREATE new entry (no webhook entry exists, backward compatibility)
                    logger.debug(f"[SMART_SYNC] Creating new entry for {tracked.tx_id[:16]}...")

                    # 🚀 NEW: Resolve position_id and outcome using copy_trading_monitor logic
                    position_id_resolved = None
                    outcome_resolved = None
                    market_title_resolved = None

                    # Calculate position_id from market_id (condition_id) and outcome
                    if tracked.market_id and str(tracked.market_id).isdigit():
                        try:
                            # Use same formula as indexer: token_id = condition_id * 2 + outcome
                            position_id_resolved = str(int(tracked.market_id) * 2 + tracked.outcome)

                            # Use monitor service to resolve outcome correctly
                            from core.services.copy_trading_monitor import get_copy_trading_monitor
                            monitor = get_copy_trading_monitor()
                            resolution = await monitor._resolve_market_by_position_id(position_id_resolved)

                            if resolution:
                                outcome_resolved = resolution['outcome']  # Real outcome from market data
                                market_title_resolved = resolution['market_title']
                                logger.debug(f"✅ [SMART_SYNC] Resolved outcome via position_id: {outcome_resolved}")
                            else:
                                # Fallback to old logic if resolution fails
                                outcome_resolved = 'YES' if tracked.outcome == 1 else 'NO' if tracked.outcome == 0 else None
                                logger.warning(f"⚠️ [SMART_SYNC] Could not resolve position_id, using fallback outcome: {outcome_resolved}")
                        except Exception as e:
                            logger.warning(f"⚠️ [SMART_SYNC] Position resolution failed: {e}")
                            outcome_resolved = 'YES' if tracked.outcome == 1 else 'NO' if tracked.outcome == 0 else None
                    else:
                        # Fallback for non-numeric market_id
                        outcome_resolved = 'YES' if tracked.outcome == 1 else 'NO' if tracked.outcome == 0 else None

                smart_trade = SmartWalletTrade(
                    id=tracked.tx_id,  # Use tx_id as unique identifier
                    wallet_address=tracked.user_address,
                        market_id=tracked.market_id,  # token_id (numeric string from subsquid)
                        condition_id=condition_id,  # ✅ Convert to 0x format
                        position_id=position_id_resolved,  # ✅ Real clob_token_id
                    side=tracked.tx_type,  # 'BUY' or 'SELL'
                        outcome=outcome_resolved,  # ✅ Real outcome from resolution
                    price=tracked.price,
                    size=tracked.amount,
                    value=calculated_value,
                    timestamp=tracked.timestamp,
                        is_first_time=is_first_time,  # ✅ Calculated based on previous trades
                        market_question=market_title_resolved or market_title,  # ✅ Enriched market title
                    tweeted_at=None,
                    created_at=datetime.now(timezone.utc)
                )

                # Merge (INSERT or UPDATE)
                db.merge(smart_trade)
                count += 1

            if count > 0:
                db.commit()
                logger.info(f"📝 [SMART_SYNC] Upserted {count} trades into smart_wallet_trades")
                
                # REMOVED: Old notification system that was causing spam
                # Notifications now ONLY sent via unified notifier in sync_single_trade_instant()

            return count

        except Exception as e:
            logger.error(f"❌ [SMART_SYNC] Error upserting smart wallet trades: {e}")
    
    async def cleanup_notification_tasks(self):
        """
        Clean up any active notification tasks on shutdown
        Call this method when shutting down the service to prevent resource leaks
        """
        if hasattr(self, '_active_notification_tasks') and self._active_notification_tasks:
            logger.info(f"🧹 [SMART_SYNC] Cleaning up {len(self._active_notification_tasks)} active notification tasks...")

            # Cancel all active tasks
            for task in self._active_notification_tasks:
                if not task.done():
                    task.cancel()

            # Wait for all tasks to complete/cancel
            if self._active_notification_tasks:
                try:
                    await asyncio.gather(*self._active_notification_tasks, return_exceptions=True)
                except Exception as e:
                    logger.warning(f"⚠️ [SMART_SYNC] Error during task cleanup: {e}")

            self._active_notification_tasks.clear()
            logger.info("✅ [SMART_SYNC] Notification tasks cleanup completed")

    async def _fetch_real_price_for_trade(self, trade) -> Optional[Decimal]:
        """
        Try to fetch the real execution price for a trade from local DB (poller data)
        Falls back to Polymarket API if not found locally
        """
        try:
            # First try to get price from local poller data (no latency!)
            from database import db_manager, SubsquidMarketPoll
            repo = db_manager.get_repo()
            db = repo.db

            market_id = trade.market_id
            if market_id:
                # Try exact condition_id match first
                market_data = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.condition_id == market_id
                ).first()

                if market_data and market_data.outcome_prices:
                    # Use poller data - no API call needed!
                    outcome_prices = market_data.outcome_prices
                    if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                        outcome = getattr(trade, 'outcome', None)
                        if outcome == 0:  # NO outcome
                            price = float(outcome_prices[1]) if len(outcome_prices) > 1 else None
                        elif outcome == 1:  # YES outcome
                            price = float(outcome_prices[0]) if len(outcome_prices) > 0 else None
                        else:
                            # Unknown outcome, use mid price
                            valid_prices = [float(p) for p in outcome_prices if p is not None]
                            price = sum(valid_prices) / len(valid_prices) if valid_prices else None

                        if price is not None:
                            logger.debug(f"✅ [PRICE] Got price ${price} from local poller data for {market_id[:16]}")
                            return Decimal(str(price))

            # Fallback to API call (only if local data unavailable)
            import httpx
            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            async with httpx.AsyncClient(timeout=3.0) as client:  # Shorter timeout
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    outcome_prices = data.get('outcomePrices', [])

                    if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                        outcome = getattr(trade, 'outcome', None)
                        if outcome == 0:  # NO outcome
                            price = float(outcome_prices[1]) if len(outcome_prices) > 1 else None
                        elif outcome == 1:  # YES outcome
                            price = float(outcome_prices[0]) if len(outcome_prices) > 0 else None
                        else:
                            valid_prices = [float(p) for p in outcome_prices if p is not None]
                            price = sum(valid_prices) / len(valid_prices) if valid_prices else None

                        if price is not None:
                            logger.debug(f"✅ [PRICE] Got price ${price} from API for {market_id[:16]}")
                            return Decimal(str(price))

            return None

        except Exception as e:
            logger.debug(f"Could not fetch real price for trade {getattr(trade, 'tx_id', 'unknown')[:16]}: {e}")
            return None


# Singleton
_smart_sync_service = None


def get_smart_wallet_sync_service():
    """Get or create singleton instance"""
    global _smart_sync_service
    if _smart_sync_service is None:
        _smart_sync_service = SmartWalletSyncService()
    return _smart_sync_service
