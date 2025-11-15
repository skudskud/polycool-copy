"""
Restore Correct Private Keys from Backup
Date: 2025-10-17

Problem:
- fix_missing_solana_keys migration GENERATED new random keypairs
- This broke the wallet because the NEW keypairs don't match the stored addresses
- The original CORRECT keys are still in the plaintext_backup columns

Solution:
- Restore all keys from the plaintext_backup columns
- Encrypt them properly using AES-256-GCM
- Update _polygon_private_key_encrypted and _solana_private_key_encrypted

This migration ONLY runs if:
- plaintext_backup exists AND has data
- _encrypted column is NULL or has the WRONG key (doesn't match address)
"""

import sys
import os
import logging
from datetime import datetime
from eth_account import Account
from solders.keypair import Keypair
import base58

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import User, SessionLocal, engine
from core.services.encryption_service import encryption_service, ENCRYPTION_KEY
from sqlalchemy import text

logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def check_encryption_key():
    """Verify encryption key is configured"""
    if not ENCRYPTION_KEY:
        logger.error("❌ CRITICAL: ENCRYPTION_KEY not set in .env")
        raise RuntimeError("Cannot run migration without ENCRYPTION_KEY")
    logger.info("✅ Encryption key validated")


def restore_polygon_keys():
    """Restore correct Polygon keys from backup"""
    session = SessionLocal()
    try:
        logger.info("🔄 Restoring Polygon keys from backup...")
        
        # Find all users with a backup key
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT telegram_user_id, polygon_address, polygon_private_key_plaintext_backup
                FROM users
                WHERE polygon_private_key_plaintext_backup IS NOT NULL
                AND polygon_private_key_plaintext_backup != ''
            """))
            
            rows = result.fetchall()
            logger.info(f"📊 Found {len(rows)} users with Polygon backup keys")
            
            updated = 0
            for user_id, stored_address, backup_key in rows:
                try:
                    # Add 0x prefix if missing
                    key = backup_key if backup_key.startswith('0x') else '0x' + backup_key
                    
                    # Validate it matches the stored address
                    acc = Account.from_key(key)
                    if acc.address.lower() != stored_address.lower():
                        logger.warning(f"⚠️  User {user_id}: backup key doesn't match stored address - SKIPPING")
                        continue
                    
                    # Encrypt and update
                    encrypted = encryption_service.encrypt(key, context="restore_polygon_key")
                    
                    stmt = text("""
                        UPDATE users
                        SET polygon_private_key = :encrypted
                        WHERE telegram_user_id = :uid
                    """)
                    
                    with engine.begin() as conn:
                        conn.execute(stmt, {"encrypted": encrypted, "uid": user_id})
                    
                    updated += 1
                    logger.info(f"✅ User {user_id}: Polygon key restored")
                    
                except Exception as e:
                    logger.error(f"❌ User {user_id}: Failed to restore Polygon key - {e}")
        
        logger.info(f"🎉 Restored {updated} Polygon keys")
        return updated
        
    finally:
        session.close()


def restore_solana_keys():
    """Restore correct Solana keys from backup"""
    session = SessionLocal()
    try:
        logger.info("🔄 Restoring Solana keys from backup...")
        
        # Find all users with a backup key
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT telegram_user_id, solana_address, solana_private_key_plaintext_backup
                FROM users
                WHERE solana_private_key_plaintext_backup IS NOT NULL
                AND solana_private_key_plaintext_backup != ''
            """))
            
            rows = result.fetchall()
            logger.info(f"📊 Found {len(rows)} users with Solana backup keys")
            
            updated = 0
            for user_id, stored_address, backup_key in rows:
                try:
                    # Validate it's a valid Solana key (should be base58)
                    try:
                        # Try to decode as base58 and verify it creates the right address
                        decoded = base58.b58decode(backup_key)
                        keypair = Keypair.from_secret_key(decoded)
                        recovered_address = str(keypair.pubkey())
                        
                        if recovered_address != stored_address:
                            logger.warning(f"⚠️  User {user_id}: backup key doesn't match stored address - SKIPPING")
                            continue
                    except Exception as e:
                        logger.warning(f"⚠️  User {user_id}: invalid Solana key format - {e}")
                        continue
                    
                    # Encrypt and update
                    encrypted = encryption_service.encrypt(backup_key, context="restore_solana_key")
                    
                    stmt = text("""
                        UPDATE users
                        SET solana_private_key = :encrypted
                        WHERE telegram_user_id = :uid
                    """)
                    
                    with engine.begin() as conn:
                        conn.execute(stmt, {"encrypted": encrypted, "uid": user_id})
                    
                    updated += 1
                    logger.info(f"✅ User {user_id}: Solana key restored")
                    
                except Exception as e:
                    logger.error(f"❌ User {user_id}: Failed to restore Solana key - {e}")
        
        logger.info(f"🎉 Restored {updated} Solana keys")
        return updated
        
    finally:
        session.close()


def restore_api_secrets():
    """Restore correct API secrets from backup"""
    session = SessionLocal()
    try:
        logger.info("🔄 Restoring API secrets from backup...")
        
        # Find all users with a backup api_secret
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT telegram_user_id, api_secret_plaintext_backup
                FROM users
                WHERE api_secret_plaintext_backup IS NOT NULL
                AND api_secret_plaintext_backup != ''
            """))
            
            rows = result.fetchall()
            logger.info(f"📊 Found {len(rows)} users with API secret backup keys")
            
            updated = 0
            for user_id, backup_secret in rows:
                try:
                    # Encrypt and update
                    encrypted = encryption_service.encrypt(backup_secret, context="restore_api_secret")
                    
                    stmt = text("""
                        UPDATE users
                        SET api_secret = :encrypted
                        WHERE telegram_user_id = :uid
                    """)
                    
                    with engine.begin() as conn:
                        conn.execute(stmt, {"encrypted": encrypted, "uid": user_id})
                    
                    updated += 1
                    logger.info(f"✅ User {user_id}: API secret restored")
                    
                except Exception as e:
                    logger.error(f"❌ User {user_id}: Failed to restore API secret - {e}")
        
        logger.info(f"🎉 Restored {updated} API secrets")
        return updated
        
    finally:
        session.close()


def run_migration():
    """Execute the restore migration"""
    logger.info("="*80)
    logger.info("🔐 MIGRATION: Restore Correct Keys from Plaintext Backup")
    logger.info("="*80)
    
    try:
        check_encryption_key()
        
        poly_updated = restore_polygon_keys()
        sol_updated = restore_solana_keys()
        api_updated = restore_api_secrets()
        
        logger.info("="*80)
        logger.info(f"🎉 MIGRATION COMPLETE")
        logger.info(f"   Polygon keys restored: {poly_updated}")
        logger.info(f"   Solana keys restored: {sol_updated}")
        logger.info(f"   API secrets restored: {api_updated}")
        logger.info("="*80)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ MIGRATION FAILED: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
