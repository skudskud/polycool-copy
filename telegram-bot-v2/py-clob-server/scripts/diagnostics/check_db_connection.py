#!/usr/bin/env python3
"""
Database Connection Diagnostic Script
Vérifie la connexion à Supabase et affiche les dernières transactions
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from database import SessionLocal, Transaction, engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_database_connection():
    """Check if we can connect to the database"""
    try:
        # Test basic connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")

            # Get database URL (masked)
            db_url = str(engine.url)
            masked_url = db_url.split('@')[1] if '@' in db_url else 'unknown'
            logger.info(f"📍 Connected to: {masked_url}")

        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False


def check_last_transactions():
    """Get the last 5 transactions from database"""
    try:
        with SessionLocal() as session:
            transactions = session.query(Transaction).order_by(Transaction.id.desc()).limit(5).all()

            if not transactions:
                logger.warning("⚠️ No transactions found in database")
                return

            logger.info(f"\n📊 Last {len(transactions)} transactions:")
            logger.info("-" * 80)

            for tx in transactions:
                logger.info(
                    f"ID: {tx.id} | User: {tx.user_id} | Type: {tx.transaction_type} | "
                    f"Amount: ${tx.total_amount:.2f} | Time: {tx.executed_at}"
                )

            # Get max ID
            max_id = session.query(Transaction.id).order_by(Transaction.id.desc()).first()
            if max_id:
                logger.info(f"\n🔢 Max transaction ID in database: {max_id[0]}")

    except Exception as e:
        logger.error(f"❌ Error fetching transactions: {e}")


def test_write_transaction():
    """Test if we can write to the database"""
    try:
        from datetime import datetime

        with SessionLocal() as session:
            # Create a test transaction
            test_tx = Transaction(
                user_id=0,  # Test user
                transaction_type='BUY',
                market_id='TEST_DIAGNOSTIC',
                outcome='test',
                tokens=1.0,
                price_per_token=1.0,
                total_amount=1.0,
                token_id='TEST_TOKEN_ID',
                order_id='TEST_ORDER_ID',
                executed_at=datetime.utcnow()
            )

            session.add(test_tx)
            session.commit()

            test_id = test_tx.id
            logger.info(f"✅ Test transaction written successfully (ID: {test_id})")

            # Delete test transaction
            session.delete(test_tx)
            session.commit()
            logger.info("✅ Test transaction deleted")

            return True

    except Exception as e:
        logger.error(f"❌ Error writing test transaction: {e}")
        return False


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("DATABASE CONNECTION DIAGNOSTIC")
    logger.info("=" * 80)

    # Check connection
    if not check_database_connection():
        sys.exit(1)

    # Check last transactions
    check_last_transactions()

    # Test write capability
    logger.info("\n" + "=" * 80)
    logger.info("TESTING WRITE CAPABILITY")
    logger.info("=" * 80)

    if test_write_transaction():
        logger.info("\n✅ ALL CHECKS PASSED - Database connection is healthy")
    else:
        logger.error("\n❌ WRITE TEST FAILED - Database connection may be read-only or broken")
        sys.exit(1)
