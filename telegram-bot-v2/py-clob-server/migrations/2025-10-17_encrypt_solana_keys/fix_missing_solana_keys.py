"""
Fix Missing Private Keys (Polygon + Solana)
Date: 2025-10-17

This migration:
1. Finds all users with Polygon address but EMPTY private_key
2. Finds all users with Solana address but EMPTY private_key
3. Generates NEW keypairs for missing keys
4. Encrypts all keys with AES-256-GCM

REASON: Some users have addresses but no private keys in DB (migration not run earlier)
"""

import sys
import os
import logging
from datetime import datetime
from typing import Tuple
from solders.keypair import Keypair
from eth_account import Account
import base58

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import User, SessionLocal, engine
from core.services.encryption_service import encryption_service, ENCRYPTION_KEY

logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# =========================================================================
# CONSTANTS
# =========================================================================

MISSING_KEY_PLACEHOLDER = "GENERATED_NEW_KEYPAIR"

# =========================================================================
# MIGRATION FUNCTIONS
# =========================================================================

def check_encryption_key():
    """Verify encryption key is configured"""
    if not ENCRYPTION_KEY:
        logger.error("❌ CRITICAL: ENCRYPTION_KEY not set in .env")
        raise RuntimeError("Cannot run migration without ENCRYPTION_KEY")
    logger.info("✅ Encryption key validated")


def generate_polygon_keypair() -> Tuple[str, str]:
    """
    Generate a new Polygon (Ethereum) keypair
    Returns: (address, private_key_hex)
    """
    account = Account.create()
    return account.address, '0x' + account.key.hex()


def generate_solana_keypair() -> Tuple[str, str]:
    """
    Generate a new Solana keypair
    Returns: (address, private_key_base58)
    """
    keypair = Keypair()
    address = str(keypair.pubkey())
    private_key = base58.b58encode(bytes(keypair)).decode('ascii')
    return address, private_key


def find_users_with_missing_keys() -> dict:
    """Find users with missing Polygon and/or Solana keys"""
    session = SessionLocal()
    try:
        missing_polygon = session.query(User).filter(
            User.polygon_address.isnot(None),
            (User._polygon_private_key_encrypted == None) | (User._polygon_private_key_encrypted == '')
        ).all()

        missing_solana = session.query(User).filter(
            User.solana_address.isnot(None),
            (User._solana_private_key_encrypted == None) | (User._solana_private_key_encrypted == '')
        ).all()

        logger.info(f"🔍 Found {len(missing_polygon)} users with missing Polygon key")
        logger.info(f"🔍 Found {len(missing_solana)} users with missing Solana key")

        return {
            'polygon': missing_polygon,
            'solana': missing_solana
        }
    finally:
        session.close()


def fix_missing_polygon_keys():
    """Generate and encrypt Polygon keys for users missing them"""
    session = SessionLocal()

    try:
        users_missing_poly = session.query(User).filter(
            User.polygon_address.isnot(None),
            (User._polygon_private_key_encrypted == None) | (User._polygon_private_key_encrypted == '')
        ).all()

        if not users_missing_poly:
            logger.info("✅ All users have Polygon private keys - nothing to fix!")
            return 0

        logger.info(f"📝 Generating and encrypting {len(users_missing_poly)} missing Polygon private keys...")

        fixed_count = 0
        for user in users_missing_poly:
            try:
                # Generate new Polygon keypair
                address, private_key = generate_polygon_keypair()

                # Encrypt it
                encrypted_key = encryption_service.encrypt(private_key, context="migration_polygon_key_generation")

                # Update user's encrypted key directly in DB
                from sqlalchemy import update
                stmt = (
                    update(User)
                    .where(User.telegram_user_id == user.telegram_user_id)
                    .values(_polygon_private_key_encrypted=encrypted_key)
                )
                session.execute(stmt)
                session.commit()

                fixed_count += 1
                logger.info(f"  ✓ Generated new Polygon key for user {user.telegram_user_id} (address: {address[:10]}...)")

            except Exception as e:
                logger.error(f"  ❌ Failed for user {user.telegram_user_id}: {e}")
                session.rollback()
                raise

        logger.info(f"✅ Successfully generated Polygon keys for {fixed_count} users")
        return fixed_count

    finally:
        session.close()


def fix_missing_solana_keys():
    """Generate and encrypt Solana keys for users missing them"""
    session = SessionLocal()

    try:
        users_missing_sol = session.query(User).filter(
            User.solana_address.isnot(None),
            (User._solana_private_key_encrypted == None) | (User._solana_private_key_encrypted == '')
        ).all()

        if not users_missing_sol:
            logger.info("✅ All users have Solana private keys - nothing to fix!")
            return 0

        logger.info(f"📝 Generating and encrypting {len(users_missing_sol)} missing Solana private keys...")

        fixed_count = 0
        for user in users_missing_sol:
            try:
                # Generate new Solana keypair
                address, private_key = generate_solana_keypair()

                # Encrypt it
                encrypted_key = encryption_service.encrypt(private_key, context="migration_solana_key_generation")

                # Update user's encrypted key directly in DB
                from sqlalchemy import update
                stmt = (
                    update(User)
                    .where(User.telegram_user_id == user.telegram_user_id)
                    .values(_solana_private_key_encrypted=encrypted_key)
                )
                session.execute(stmt)
                session.commit()

                fixed_count += 1
                logger.info(f"  ✓ Generated new Solana key for user {user.telegram_user_id} (address: {address[:8]}...)")

            except Exception as e:
                logger.error(f"  ❌ Failed for user {user.telegram_user_id}: {e}")
                session.rollback()
                raise

        logger.info(f"✅ Successfully generated Solana keys for {fixed_count} users")
        return fixed_count

    finally:
        session.close()


def verify_all_keys_encrypted():
    """Verify all keys are properly encrypted"""
    session = SessionLocal()

    try:
        logger.info("🔍 Verifying all keys are encrypted...")

        # Check Polygon keys
        users_poly = session.query(User).filter(
            User.polygon_address.isnot(None)
        ).all()

        # Check Solana keys
        users_sol = session.query(User).filter(
            User.solana_address.isnot(None)
        ).all()

        issues = []

        # Verify Polygon keys
        for user in users_poly:
            if not user._polygon_private_key_encrypted:
                issues.append(f"User {user.telegram_user_id}: Polygon key is EMPTY")
            elif not encryption_service.is_encrypted(user._polygon_private_key_encrypted):
                issues.append(f"User {user.telegram_user_id}: Polygon key is PLAINTEXT")

        # Verify Solana keys
        for user in users_sol:
            if not user._solana_private_key_encrypted:
                issues.append(f"User {user.telegram_user_id}: Solana key is EMPTY")
            elif not encryption_service.is_encrypted(user._solana_private_key_encrypted):
                issues.append(f"User {user.telegram_user_id}: Solana key is PLAINTEXT")

        if issues:
            logger.error(f"❌ Found {len(issues)} issues:")
            for issue in issues:
                logger.error(f"   - {issue}")
            return False

        logger.info(f"✅ All {len(users_poly)} Polygon + {len(users_sol)} Solana keys properly encrypted!")
        return True

    finally:
        session.close()


def run_migration():
    """Execute the complete migration"""
    logger.info("=" * 80)
    logger.info("🔐 MIGRATION: Fix Missing Polygon & Solana Private Keys")
    logger.info("=" * 80)

    try:
        # Step 1: Validate encryption key
        logger.info("\n[Step 1/5] Validating encryption key...")
        check_encryption_key()

        # Step 2: Fix missing Polygon keys
        logger.info("\n[Step 2/5] Generating missing Polygon private keys...")
        fix_missing_polygon_keys()

        # Step 3: Fix missing Solana keys
        logger.info("\n[Step 3/5] Generating missing Solana private keys...")
        fix_missing_solana_keys()

        # Step 4: Verify
        logger.info("\n[Step 4/5] Verifying all keys are encrypted...")
        if not verify_all_keys_encrypted():
            raise RuntimeError("Verification failed - some keys are not encrypted")

        logger.info("\n" + "=" * 80)
        logger.info("✅ MIGRATION COMPLETE: All private keys are now encrypted!")
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
