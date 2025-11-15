"""
Rollback Migration: Decrypt Private Keys
Date: 2025-10-17

EMERGENCY ONLY: This script reverts the encryption migration
Use only if encryption is causing issues and you need to recover plaintext keys

This script:
1. Checks for backup plaintext columns
2. Optionally decrypts encrypted keys back to plaintext
3. Restores original column names

WARNING: After rollback, keys are stored in PLAINTEXT - not recommended for production!
"""

import sys
import os
import logging
from sqlalchemy import text, inspect
from dotenv import load_dotenv

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
# ROLLBACK FUNCTIONS
# =========================================================================

def column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Check if column exists in table"""
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def restore_from_backup():
    """
    Restore plaintext backup columns if they exist

    During migration, old plaintext columns were renamed with _plaintext_backup suffix.
    If they still exist, we can restore them as the primary columns.
    """
    inspector = inspect(engine)

    with engine.connect() as conn:
        try:
            logger.info("📝 Checking for plaintext backup columns...")

            has_polygon_backup = column_exists(inspector, 'users', f'polygon_private_key{BACKUP_SUFFIX}')
            has_solana_backup = column_exists(inspector, 'users', f'solana_private_key{BACKUP_SUFFIX}')
            has_api_secret_backup = column_exists(inspector, 'users', f'api_secret{BACKUP_SUFFIX}')

            if not (has_polygon_backup or has_solana_backup or has_api_secret_backup):
                logger.warning("⚠️ No plaintext backup columns found")
                logger.info("   Proceeding with decryption of encrypted columns")
                return False

            logger.info("✅ Found plaintext backup columns")
            logger.info("📝 Restoring from backup...")

            # Drop encrypted columns
            try:
                conn.execute(text("""
                    ALTER TABLE users
                    DROP COLUMN polygon_private_key
                """))
                logger.info("  ✓ Removed encrypted polygon_private_key column")
            except Exception as e:
                logger.warning(f"  ℹ Could not drop polygon_private_key: {e}")

            try:
                conn.execute(text("""
                    ALTER TABLE users
                    DROP COLUMN solana_private_key
                """))
                logger.info("  ✓ Removed encrypted solana_private_key column")
            except Exception as e:
                logger.warning(f"  ℹ Could not drop solana_private_key: {e}")

            try:
                conn.execute(text("""
                    ALTER TABLE users
                    DROP COLUMN api_secret
                """))
                logger.info("  ✓ Removed encrypted api_secret column")
            except Exception as e:
                logger.warning(f"  ℹ Could not drop api_secret: {e}")

            # Restore backup columns
            if has_polygon_backup:
                conn.execute(text(f"""
                    ALTER TABLE users
                    RENAME COLUMN polygon_private_key{BACKUP_SUFFIX} TO polygon_private_key
                """))
                logger.info("  ✓ Restored polygon_private_key from backup")

            if has_solana_backup:
                conn.execute(text(f"""
                    ALTER TABLE users
                    RENAME COLUMN solana_private_key{BACKUP_SUFFIX} TO solana_private_key
                """))
                logger.info("  ✓ Restored solana_private_key from backup")

            if has_api_secret_backup:
                conn.execute(text(f"""
                    ALTER TABLE users
                    RENAME COLUMN api_secret{BACKUP_SUFFIX} TO api_secret
                """))
                logger.info("  ✓ Restored api_secret from backup")

            conn.commit()
            logger.info("✅ Successfully restored from backup")
            return True

        except Exception as e:
            logger.error(f"❌ Restore from backup failed: {e}")
            conn.rollback()
            raise


def decrypt_existing_keys():
    """
    Decrypt all encrypted keys back to plaintext

    WARNING: This is a LAST RESORT recovery method.
    After decryption, keys are stored in PLAINTEXT in the database!
    """
    if not ENCRYPTION_KEY:
        logger.error("❌ Cannot decrypt without ENCRYPTION_KEY")
        raise RuntimeError("ENCRYPTION_KEY not configured")

    session = SessionLocal()

    try:
        users = session.query(User).all()

        if not users:
            logger.info("✅ No users to decrypt (empty database)")
            return

        logger.info(f"⚠️  DECRYPTING {len(users)} users' keys to PLAINTEXT...")
        logger.warning("    This is NOT recommended for production!")

        # Confirm user action
        response = input("Type 'YES' to confirm decryption (cannot be undone): ").strip().upper()
        if response != "YES":
            logger.info("❌ Decryption cancelled by user")
            return

        decrypted_count = 0
        for user in users:
            try:
                # Decrypt Polygon key
                if user.polygon_private_key and encryption_service.is_encrypted(user.polygon_private_key):
                    try:
                        user.polygon_private_key = encryption_service.decrypt(
                            user.polygon_private_key,
                            context="rollback_polygon"
                        )
                        logger.debug(f"  ✓ Decrypted Polygon key for user {user.telegram_user_id}")
                    except Exception as e:
                        logger.error(f"  ❌ Failed to decrypt Polygon key for user {user.telegram_user_id}: {e}")
                        session.rollback()
                        raise

                # Decrypt Solana key
                if user.solana_private_key and encryption_service.is_encrypted(user.solana_private_key):
                    try:
                        user.solana_private_key = encryption_service.decrypt(
                            user.solana_private_key,
                            context="rollback_solana"
                        )
                        logger.debug(f"  ✓ Decrypted Solana key for user {user.telegram_user_id}")
                    except Exception as e:
                        logger.error(f"  ❌ Failed to decrypt Solana key for user {user.telegram_user_id}: {e}")
                        session.rollback()
                        raise

                # Decrypt API secret
                if user.api_secret and encryption_service.is_encrypted(user.api_secret):
                    try:
                        user.api_secret = encryption_service.decrypt(
                            user.api_secret,
                            context="rollback_api_secret"
                        )
                        logger.debug(f"  ✓ Decrypted API secret for user {user.telegram_user_id}")
                    except Exception as e:
                        logger.error(f"  ❌ Failed to decrypt API secret for user {user.telegram_user_id}: {e}")
                        session.rollback()
                        raise

                decrypted_count += 1

            except Exception as e:
                logger.error(f"❌ Failed to process user {user.telegram_user_id}: {e}")
                session.rollback()
                raise

        # Commit all changes
        session.commit()
        logger.warning(f"⚠️  DECRYPTED {decrypted_count} users' keys to PLAINTEXT")
        logger.warning("   Consider re-encrypting as soon as possible!")

    finally:
        session.close()


def run_rollback():
    """Execute the complete rollback"""
    logger.info("=" * 80)
    logger.info("⚠️  ROLLBACK MIGRATION: Decrypt Private Keys (EMERGENCY ONLY)")
    logger.info("=" * 80)

    try:
        # Step 1: Try to restore from backup first
        logger.info("\n[Step 1/2] Checking for plaintext backups...")
        restored = restore_from_backup()

        # Step 2: If no backup, decrypt encrypted columns
        if not restored:
            logger.info("\n[Step 2/2] Decrypting encrypted keys to plaintext...")
            decrypt_existing_keys()
        else:
            logger.info("\n✅ Rollback complete - using backed-up plaintext columns")

        logger.info("\n" + "=" * 80)
        logger.warning("✅ ROLLBACK COMPLETE - Keys are now in PLAINTEXT")
        logger.warning("   RE-ENCRYPT IMMEDIATELY when issues are resolved!")
        logger.info("=" * 80)
        return True

    except Exception as e:
        logger.error("\n" + "=" * 80)
        logger.error("❌ ROLLBACK FAILED!")
        logger.error(f"Error: {e}")
        logger.error("=" * 80)
        return False


if __name__ == "__main__":
    success = run_rollback()
    sys.exit(0 if success else 1)
