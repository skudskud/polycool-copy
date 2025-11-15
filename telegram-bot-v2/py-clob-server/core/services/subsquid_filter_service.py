"""
Subsquid Filter Service
Syncs trades from subsquid_user_transactions to tracked_leader_trades
Runs every 60s, filters by watched addresses (smart_wallets + external_leaders)

Architecture:
    subsquid_user_transactions (171k+, 2 day retention)
        ↓ [Filter job every 60s]
    tracked_leader_trades (watched addresses only, full history)
        ↓
    Copy Trading Monitor + Smart Trading
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import (
    db_manager,
    SubsquidUserTransaction,
    TrackedLeaderTrade,
    ExternalLeader
)
from core.persistence.models import SmartWallet

logger = logging.getLogger(__name__)

MAX_VALID_YEAR = 2100


class SubsquidFilterService:
    """Filters subsquid_user_transactions for watched addresses"""

    def __init__(self):
        self.last_sync_timestamp: Optional[datetime] = None
        self.watched_addresses_cache: Dict = {}
        self.cache_update_time: Optional[datetime] = None

    async def run_filter_cycle(self):
        """Main filter cycle - runs every 60s"""
        try:
            logger.info("🔄 [FILTER] Starting subsquid filter cycle...")

            with db_manager.get_session() as db:
                # Refresh watched addresses cache every 5 minutes
                now = datetime.now(timezone.utc)
                if (self.cache_update_time is None or
                    (now - self.cache_update_time).total_seconds() > 300):
                    self.watched_addresses_cache = self._get_watched_addresses(db)
                    self.cache_update_time = now
                    logger.info(f"🔄 [FILTER] Updated watched addresses cache: {len(self.watched_addresses_cache)} addresses")

                if not self.watched_addresses_cache:
                    logger.debug("[FILTER] No watched addresses")
                    return

                # Get last sync timestamp
                if self.last_sync_timestamp is None:
                    self.last_sync_timestamp = self._get_last_tracked_timestamp(db)
                    logger.info(f"🔄 [FILTER] Initialized last_sync_timestamp: {self.last_sync_timestamp}")

                # Query new trades from subsquid_user_transactions
                new_trades = self._fetch_new_trades(db)

                if not new_trades:
                    logger.debug("[FILTER] No new trades to process")
                    return

                logger.info(f"📥 [FILTER] Processing {len(new_trades)} new trades")

                # Upsert into tracked_leader_trades
                processed = self._upsert_tracked_trades(db, new_trades)

                logger.info(f"✅ [FILTER] Cycle complete: {processed} trades processed")

                # Update last sync timestamp
                self.last_sync_timestamp = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"❌ [FILTER] Filter cycle error: {e}", exc_info=True)

    def _get_watched_addresses(self, db: Session) -> dict:
        """Get all watched addresses (smart wallets + external leaders)"""
        try:
            smart_addresses = {}
            for sw in db.query(SmartWallet.address).all():
                if sw.address:
                    smart_addresses[sw.address] = {'type': 'smart_wallet'}

            external_addresses = {}
            for el in db.query(ExternalLeader).filter(ExternalLeader.is_active == True).all():
                if el.polygon_address:
                    external_addresses[el.polygon_address] = {
                        'type': 'external_leader',
                        'virtual_id': el.virtual_id
                    }

            result = {**smart_addresses, **external_addresses}
            logger.debug(f"[FILTER] Watched addresses: {len(smart_addresses)} smart wallets, {len(external_addresses)} external leaders")
            return result
        except Exception as e:
            logger.error(f"❌ [FILTER] Error getting watched addresses: {e}")
            return {}

    def _get_last_tracked_timestamp(self, db: Session) -> datetime:
        """Get timestamp of last tracked trade"""
        try:
            last = db.query(func.max(TrackedLeaderTrade.timestamp)).scalar()
            if last:
                if last.year > MAX_VALID_YEAR:
                    logger.warning(f"[FILTER] Ignoring invalid last tracked timestamp ({last})")
                    return datetime.now(timezone.utc) - timedelta(hours=1)
                logger.info(f"[FILTER] Last tracked trade: {last}")
                return last
            else:
                # Default to 1 hour ago if no trades yet
                default = datetime.now(timezone.utc) - timedelta(hours=1)
                logger.info(f"[FILTER] No previous tracks, starting from: {default}")
                return default
        except Exception as e:
            logger.error(f"❌ [FILTER] Error getting last tracked timestamp: {e}")
            return datetime.now(timezone.utc) - timedelta(hours=1)

    def _fetch_new_trades(self, db: Session) -> List[SubsquidUserTransaction]:
        """Fetch new trades from subsquid_user_transactions"""
        try:
            if not self.watched_addresses_cache or self.last_sync_timestamp is None:
                return []

            if self.last_sync_timestamp.year > MAX_VALID_YEAR:
                logger.warning(f"[FILTER] Resetting invalid sync timestamp ({self.last_sync_timestamp})")
                self.last_sync_timestamp = datetime.now(timezone.utc) - timedelta(hours=1)

            addresses = list(self.watched_addresses_cache.keys())

            trades = db.query(SubsquidUserTransaction).filter(
                SubsquidUserTransaction.user_address.in_(addresses),
                SubsquidUserTransaction.timestamp > self.last_sync_timestamp,
                func.extract('year', SubsquidUserTransaction.timestamp) <= MAX_VALID_YEAR
            ).order_by(SubsquidUserTransaction.timestamp.asc()).all()

            logger.debug(f"[FILTER] Fetched {len(trades)} new trades from subsquid_user_transactions")
            return trades

        except Exception as e:
            logger.error(f"❌ [FILTER] Error fetching new trades: {e}")
            return []

    def _upsert_tracked_trades(
        self,
        db: Session,
        trades: List[SubsquidUserTransaction]
    ) -> int:
        """Upsert trades into tracked_leader_trades"""
        try:
            count = 0

            for trade in trades:
                if trade.timestamp and trade.timestamp.year > MAX_VALID_YEAR:
                    logger.warning(f"[FILTER] Skipping trade {trade.id} with invalid timestamp {trade.timestamp}")
                    continue
                address_info = self.watched_addresses_cache.get(trade.user_address, {})

                tracked = TrackedLeaderTrade(
                    id=trade.id,
                    tx_id=trade.tx_id,
                    user_address=trade.user_address,
                    market_id=trade.market_id,
                    outcome=trade.outcome,
                    tx_type=trade.tx_type,
                    amount=trade.amount,
                    price=trade.price,
                    tx_hash=trade.tx_hash,
                    timestamp=trade.timestamp,
                    is_smart_wallet=(address_info.get('type') == 'smart_wallet'),
                    is_external_leader=(address_info.get('type') == 'external_leader')
                )

                db.merge(tracked)
                count += 1

            if count > 0:
                db.commit()
                logger.info(f"📝 [FILTER] Upserted {count} trades into tracked_leader_trades")

            return count

        except Exception as e:
            logger.error(f"❌ [FILTER] Error upserting tracked trades: {e}")
            db.rollback()
            return 0


# Singleton
_filter_service: Optional[SubsquidFilterService] = None


def get_subsquid_filter_service() -> SubsquidFilterService:
    """Get or create singleton instance"""
    global _filter_service
    if _filter_service is None:
        _filter_service = SubsquidFilterService()
    return _filter_service
