"""
Smart Wallet Repository
Handles database operations for smart_wallets table
"""

import logging
from typing import List, Dict, Optional
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from datetime import datetime

from .models import SmartWallet

logger = logging.getLogger(__name__)


class SmartWalletRepository:
    """Repository for smart wallet operations"""

    def __init__(self, db_session):
        self.session = db_session

    def get_all_wallets(self) -> List[SmartWallet]:
        """
        Get all smart wallets from database

        Returns:
            List of SmartWallet objects
        """
        try:
            wallets = self.session.query(SmartWallet).all()
            logger.debug(f"Retrieved {len(wallets)} smart wallets from database")
            return wallets
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving smart wallets: {e}")
            self.session.rollback()  # FIX: Rollback on error
            return []

    def get_wallet(self, address: str) -> Optional[SmartWallet]:
        """
        Get a specific smart wallet by address

        Args:
            address: Ethereum wallet address

        Returns:
            SmartWallet object or None if not found
        """
        try:
            wallet = self.session.query(SmartWallet).filter(
                SmartWallet.address == address
            ).first()
            return wallet
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving wallet {address}: {e}")
            self.session.rollback()  # FIX: Rollback on error
            return None

    def upsert_wallet(self, wallet_data: Dict) -> Optional[SmartWallet]:
        """
        Insert or update a smart wallet

        Args:
            wallet_data: Dictionary with wallet data

        Returns:
            SmartWallet object or None on error
        """
        try:
            # Prepare data
            address = wallet_data.get('address')
            if not address:
                logger.error("Wallet address is required")
                return None

            # Use PostgreSQL INSERT ... ON CONFLICT
            stmt = insert(SmartWallet).values(
                address=address,
                smartscore=wallet_data.get('smartscore'),
                win_rate=wallet_data.get('win_rate'),
                markets_count=wallet_data.get('markets_count'),
                realized_pnl=wallet_data.get('realized_pnl'),
                bucket_smart=wallet_data.get('bucket_smart'),
                bucket_last_date=wallet_data.get('bucket_last_date'),
                added_at=wallet_data.get('added_at', datetime.utcnow()),
                updated_at=datetime.utcnow()
            ).on_conflict_do_update(
                index_elements=['address'],
                set_={
                    'smartscore': wallet_data.get('smartscore'),
                    'win_rate': wallet_data.get('win_rate'),
                    'markets_count': wallet_data.get('markets_count'),
                    'realized_pnl': wallet_data.get('realized_pnl'),
                    'bucket_smart': wallet_data.get('bucket_smart'),
                    'bucket_last_date': wallet_data.get('bucket_last_date'),
                    'updated_at': datetime.utcnow()
                }
            )

            self.session.execute(stmt)
            self.session.commit()

            # Retrieve and return the wallet
            return self.get_wallet(address)

        except SQLAlchemyError as e:
            logger.error(f"Error upserting wallet {wallet_data.get('address')}: {e}")
            self.session.rollback()
            return None

    def bulk_upsert_wallets(self, wallets: List[Dict]) -> int:
        """
        Bulk insert or update smart wallets

        Args:
            wallets: List of wallet data dictionaries

        Returns:
            Number of wallets upserted
        """
        if not wallets:
            return 0

        try:
            # Prepare values for bulk insert
            values_list = []
            for wallet_data in wallets:
                if not wallet_data.get('address'):
                    continue

                values_list.append({
                    'address': wallet_data.get('address'),
                    'smartscore': wallet_data.get('smartscore'),
                    'win_rate': wallet_data.get('win_rate'),
                    'markets_count': wallet_data.get('markets_count'),
                    'realized_pnl': wallet_data.get('realized_pnl'),
                    'bucket_smart': wallet_data.get('bucket_smart'),
                    'bucket_last_date': wallet_data.get('bucket_last_date'),
                    'added_at': wallet_data.get('added_at', datetime.utcnow()),
                    'updated_at': datetime.utcnow()
                })

            if not values_list:
                logger.warning("No valid wallets to upsert")
                return 0

            # Use PostgreSQL INSERT ... ON CONFLICT for bulk operation
            stmt = insert(SmartWallet).values(values_list)
            stmt = stmt.on_conflict_do_update(
                index_elements=['address'],
                set_={
                    'smartscore': stmt.excluded.smartscore,
                    'win_rate': stmt.excluded.win_rate,
                    'markets_count': stmt.excluded.markets_count,
                    'realized_pnl': stmt.excluded.realized_pnl,
                    'bucket_smart': stmt.excluded.bucket_smart,
                    'bucket_last_date': stmt.excluded.bucket_last_date,
                    'updated_at': stmt.excluded.updated_at
                }
            )

            self.session.execute(stmt)
            self.session.commit()

            logger.info(f"✅ Bulk upserted {len(values_list)} smart wallets")
            return len(values_list)

        except SQLAlchemyError as e:
            logger.error(f"Error bulk upserting wallets: {e}")
            self.session.rollback()
            return 0

    def count_wallets(self) -> int:
        """
        Count total number of smart wallets

        Returns:
            Count of wallets
        """
        try:
            count = self.session.query(SmartWallet).count()
            return count
        except SQLAlchemyError as e:
            logger.error(f"Error counting wallets: {e}")
            self.session.rollback()  # FIX: Rollback on error
            return 0
