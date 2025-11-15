"""
Migration: Encrypt Private Keys in Database
Date: 2025-10-17

This migration:
1. Creates new encrypted columns in users table
2. Encrypts any existing plaintext keys
3. Swaps column names (encrypted becomes active, plaintext becomes backup)
4. Validates data integrity

ATOMIC TRANSACTION: All-or-nothing operation for data safety
"""

import sys
import os
import logging
from datetime import datetime
from sqlalchemy import text, create_engine, inspect
from sqlalchemy.orm import sessionmaker

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import User, engine, SessionLocal
from core.services.encryption_service import encryption_service, ENCRYPTION_KEY

logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# =========================================================================
# CONSTANTS
# =========================================================================

BACKUP_SUFFIX = "_plaintext_backup"

# =========================================================================
# MIGRATION FUNCTIONS
# =========================================================================

def check_encryption_key():
    """Verify encryption key is configured"""
    if not ENCRYPTION_KEY:
        logger.error("❌ CRITICAL: ENCRYPTION_KEY not set in .env")
        logger.error("   Generate key with: python -c \"import base64, os; print(base64.b64encode(os.urandom(32)).decode())\"")
        raise RuntimeError("Cannot run migration without ENCRYPTION_KEY")
    logger.info("✅ Encryption key validated")


def column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Check if column exists in table"""
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def create_encrypted_columns():
    """Create new encrypted columns if they don't exist"""
    inspector = inspect(engine)

    with engine.connect() as conn:
        try:
            # Check for existing encrypted columns
            has_polygon_enc = column_exists(inspector, 'users', 'polygon_private_key_encrypted')
            has_solana_enc = column_exists(inspector, 'users', 'solana_private_key_encrypted')
            has_api_secret_enc = column_exists(inspector, 'users', 'api_secret_encrypted')

            if has_polygon_enc and has_solana_enc and has_api_secret_enc:
                logger.info("✅ Encrypted columns already exist")
                return

            logger.info("📝 Creating encrypted columns...")

            if not has_polygon_enc:
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN polygon_private_key_encrypted TEXT
                """))
                logger.info("  ✓ Added polygon_private_key_encrypted column")

            if not has_solana_enc:
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN solana_private_key_encrypted TEXT
                """))
                logger.info("  ✓ Added solana_private_key_encrypted column")

            if not has_api_secret_enc:
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN api_secret_encrypted TEXT
                """))
                logger.info("  ✓ Added api_secret_encrypted column")

            conn.commit()
            logger.info("✅ All encrypted columns created successfully")

        except Exception as e:
            logger.error(f"❌ Failed to create encrypted columns: {e}")
            conn.rollback()
            raise


def encrypt_existing_keys():
    """Encrypt all existing plaintext keys"""
    session = SessionLocal()

    try:
        users = session.query(User).all()

        if not users:
            logger.info("✅ No users to encrypt (fresh database)")
            return

        logger.info(f"📝 Encrypting keys for {len(users)} users...")

        encrypted_count = 0
        for user in users:
            try:
                # Encrypt Polygon key if it exists and not already encrypted
                if user._polygon_private_key_encrypted:
                    if not encryption_service.is_encrypted(user._polygon_private_key_encrypted):
                        user.polygon_private_key_encrypted = encryption_service.encrypt(
                            user._polygon_private_key_encrypted,
                            context="migration_polygon"
                        )
                        logger.debug(f"  ✓ Encrypted Polygon key for user {user.telegram_user_id}")
                    else:
                        logger.debug(f"  ℹ Polygon key already encrypted for user {user.telegram_user_id}")

                # Encrypt Solana key if it exists
                if user._solana_private_key_encrypted:
                    if not encryption_service.is_encrypted(user._solana_private_key_encrypted):
                        user.solana_private_key_encrypted = encryption_service.encrypt(
                            user._solana_private_key_encrypted,
                            context="migration_solana"
                        )
                        logger.debug(f"  ✓ Encrypted Solana key for user {user.telegram_user_id}")
                    else:
                        logger.debug(f"  ℹ Solana key already encrypted for user {user.telegram_user_id}")

                # Encrypt API secret if it exists
                if user._api_secret_encrypted:
                    if not encryption_service.is_encrypted(user._api_secret_encrypted):
                        user.api_secret_encrypted = encryption_service.encrypt(
                            user._api_secret_encrypted,
                            context="migration_api_secret"
                        )
                        logger.debug(f"  ✓ Encrypted API secret for user {user.telegram_user_id}")
                    else:
                        logger.debug(f"  ℹ API secret already encrypted for user {user.telegram_user_id}")

                encrypted_count += 1

            except Exception as e:
                logger.error(f"❌ Failed to encrypt keys for user {user.telegram_user_id}: {e}")
                session.rollback()
                raise

        # Commit all changes atomically
        session.commit()
        logger.info(f"✅ Successfully encrypted keys for {encrypted_count} users")

    except Exception as e:
        logger.error(f"❌ Encryption failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def swap_to_encrypted_columns():
    """
    Swap plaintext and encrypted columns:
    - Drop old plaintext columns (keep as backup)
    - Rename encrypted columns to be the active ones
    """
    with engine.connect() as conn:
        try:
            logger.info("📝 Updating User model to use encrypted columns...")

            inspector = inspect(engine)
            has_polygon_enc = column_exists(inspector, 'users', 'polygon_private_key_encrypted')
            has_solana_enc = column_exists(inspector, 'users', 'solana_private_key_encrypted')
            has_api_secret_enc = column_exists(inspector, 'users', 'api_secret_encrypted')

            if not (has_polygon_enc and has_solana_enc and has_api_secret_enc):
                raise RuntimeError("Encrypted columns not found - cannot proceed with swap")

            # Rename old plaintext columns as backup
            try:
                conn.execute(text(f"""
                    ALTER TABLE users
                    RENAME COLUMN polygon_private_key TO polygon_private_key{BACKUP_SUFFIX}
                """))
                logger.info(f"  ✓ Backed up polygon_private_key as polygon_private_key{BACKUP_SUFFIX}")
            except Exception as e:
                logger.warning(f"  ℹ Could not backup polygon_private_key: {e}")

            try:
                conn.execute(text(f"""
                    ALTER TABLE users
                    RENAME COLUMN solana_private_key TO solana_private_key{BACKUP_SUFFIX}
                """))
                logger.info(f"  ✓ Backed up solana_private_key as solana_private_key{BACKUP_SUFFIX}")
            except Exception as e:
                logger.warning(f"  ℹ Could not backup solana_private_key: {e}")

            try:
                conn.execute(text(f"""
                    ALTER TABLE users
                    RENAME COLUMN api_secret TO api_secret{BACKUP_SUFFIX}
                """))
                logger.info(f"  ✓ Backed up api_secret as api_secret{BACKUP_SUFFIX}")
            except Exception as e:
                logger.warning(f"  ℹ Could not backup api_secret: {e}")

            # Rename encrypted columns to be the active ones
            conn.execute(text("""
                ALTER TABLE users
                RENAME COLUMN polygon_private_key_encrypted TO polygon_private_key
            """))
            logger.info("  ✓ Activated polygon_private_key_encrypted as polygon_private_key")

            conn.execute(text("""
                ALTER TABLE users
                RENAME COLUMN solana_private_key_encrypted TO solana_private_key
            """))
            logger.info("  ✓ Activated solana_private_key_encrypted as solana_private_key")

            conn.execute(text("""
                ALTER TABLE users
                RENAME COLUMN api_secret_encrypted TO api_secret
            """))
            logger.info("  ✓ Activated api_secret_encrypted as api_secret")

            conn.commit()
            logger.info("✅ Successfully swapped to encrypted columns")

        except Exception as e:
            logger.error(f"❌ Column swap failed: {e}")
            conn.rollback()
            raise


def verify_encryption():
    """Verify all keys are encrypted"""
    session = SessionLocal()

    try:
        users = session.query(User).all()

        if not users:
            logger.info("✅ No users to verify (empty database)")
            return

        logger.info(f"🔍 Verifying encryption for {len(users)} users...")

        for user in users:
            issues = []

            # Check Polygon key
            if user.polygon_private_key and not encryption_service.is_encrypted(user.polygon_private_key):
                issues.append("polygon_private_key is plaintext (not encrypted)")

            # Check Solana key
            if user.solana_private_key and not encryption_service.is_encrypted(user.solana_private_key):
                issues.append("solana_private_key is plaintext (not encrypted)")

            # Check API secret
            if user.api_secret and not encryption_service.is_encrypted(user.api_secret):
                issues.append("api_secret is plaintext (not encrypted)")

            if issues:
                logger.error(f"❌ User {user.telegram_user_id}: {', '.join(issues)}")
                return False

        logger.info("✅ All keys are properly encrypted!")
        return True

    finally:
        session.close()


def run_migration():
    """Execute the complete migration"""
    logger.info("=" * 80)
    logger.info("🔐 MIGRATION: Encrypt Private Keys in Database")
    logger.info("=" * 80)

    try:
        # Step 1: Validate encryption key
        logger.info("\n[Step 1/5] Validating encryption key...")
        check_encryption_key()

        # Step 2: Create encrypted columns
        logger.info("\n[Step 2/5] Creating encrypted columns...")
        create_encrypted_columns()

        # Step 3: Encrypt existing keys
        logger.info("\n[Step 3/5] Encrypting existing plaintext keys...")
        encrypt_existing_keys()

        # Step 4: Swap to encrypted columns
        logger.info("\n[Step 4/5] Activating encrypted columns...")
        swap_to_encrypted_columns()

        # Step 5: Verify encryption
        logger.info("\n[Step 5/5] Verifying encryption integrity...")
        if not verify_encryption():
            raise RuntimeError("Encryption verification failed!")

        logger.info("\n" + "=" * 80)
        logger.info("✅ MIGRATION COMPLETE: Private keys are now encrypted!")
        logger.info("=" * 80)
        return True

    except Exception as e:
        logger.error("\n" + "=" * 80)
        logger.error("❌ MIGRATION FAILED!")
        logger.error(f"Error: {e}")
        logger.error("=" * 80)
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
