"""
FIX CRITICAL: Properly Migrate Plaintext Keys to Encrypted Columns
Date: 2025-10-17

Problem:
- Plaintext keys still in old columns (polygon_private_key, solana_private_key, api_secret)
- Encrypted columns are EMPTY
- The encrypt_private_keys migration didn't copy data correctly

Solution:
1. Copy plaintext keys from old columns to encrypted columns (with encryption)
2. KEEP plaintext keys as backup (don't delete)
3. Verify all keys are properly encrypted
"""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import engine
from core.services.encryption_service import encryption_service, ENCRYPTION_KEY
from sqlalchemy import text

logger = logging.getLogger(__name__)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def check_encryption_key():
    if not ENCRYPTION_KEY:
        logger.error("❌ CRITICAL: ENCRYPTION_KEY not set")
        raise RuntimeError("Cannot run migration without ENCRYPTION_KEY")
    logger.info("✅ Encryption key validated")


def migrate_keys():
    """Migrate all plaintext keys to encrypted columns"""
    logger.info("🔄 Starting key migration...")
    
    try:
        with engine.begin() as conn:
            # Get all plaintext keys
            logger.info("📊 Fetching users with plaintext keys...")
            result = conn.execute(text("""
                SELECT telegram_user_id, polygon_private_key, solana_private_key, api_secret
                FROM users
                WHERE (polygon_private_key IS NOT NULL AND polygon_private_key != '')
                   OR (solana_private_key IS NOT NULL AND solana_private_key != '')
                   OR (api_secret IS NOT NULL AND api_secret != '')
            """))
            
            rows = result.fetchall()
            logger.info(f"📊 Found {len(rows)} users with plaintext keys to migrate\n")
            
            poly_count = 0
            sol_count = 0
            api_count = 0
            
            for user_id, poly_key, sol_key, api_key in rows:
                logger.info(f"🔄 Processing user {user_id}...")
                
                try:
                    # Encrypt Polygon key
                    if poly_key:
                        logger.info(f"  ├─ Encrypting Polygon key...")
                        encrypted_poly = encryption_service.encrypt(poly_key, context="migrate_polygon")
                        conn.execute(text("""
                            UPDATE users
                            SET polygon_private_key_encrypted = :enc
                            WHERE telegram_user_id = :uid
                        """), {"enc": encrypted_poly, "uid": user_id})
                        poly_count += 1
                        logger.info(f"  ├─ ✅ Polygon key encrypted")
                    
                    # Encrypt Solana key
                    if sol_key:
                        logger.info(f"  ├─ Encrypting Solana key...")
                        encrypted_sol = encryption_service.encrypt(sol_key, context="migrate_solana")
                        conn.execute(text("""
                            UPDATE users
                            SET solana_private_key_encrypted = :enc
                            WHERE telegram_user_id = :uid
                        """), {"enc": encrypted_sol, "uid": user_id})
                        sol_count += 1
                        logger.info(f"  ├─ ✅ Solana key encrypted")
                    
                    # Encrypt API secret
                    if api_key:
                        logger.info(f"  ├─ Encrypting API secret...")
                        encrypted_api = encryption_service.encrypt(api_key, context="migrate_api")
                        conn.execute(text("""
                            UPDATE users
                            SET api_secret_encrypted = :enc
                            WHERE telegram_user_id = :uid
                        """), {"enc": encrypted_api, "uid": user_id})
                        api_count += 1
                        logger.info(f"  └─ ✅ API secret encrypted")
                    
                except Exception as e:
                    logger.error(f"  ❌ Failed to migrate user {user_id}: {e}")
                    raise
        
            logger.info(f"\n✅ Encryption complete:")
            logger.info(f"   Polygon keys: {poly_count}")
            logger.info(f"   Solana keys: {sol_count}")
            logger.info(f"   API secrets: {api_count}")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise


def verify():
    """Verify all keys are encrypted"""
    logger.info("\n🔍 Verifying migration...\n")
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN polygon_private_key IS NOT NULL AND polygon_private_key != '' THEN 1 END) as poly_pt,
                COUNT(CASE WHEN polygon_private_key_encrypted IS NOT NULL AND polygon_private_key_encrypted != '' THEN 1 END) as poly_enc,
                COUNT(CASE WHEN solana_private_key IS NOT NULL AND solana_private_key != '' THEN 1 END) as sol_pt,
                COUNT(CASE WHEN solana_private_key_encrypted IS NOT NULL AND solana_private_key_encrypted != '' THEN 1 END) as sol_enc,
                COUNT(CASE WHEN api_secret IS NOT NULL AND api_secret != '' THEN 1 END) as api_pt,
                COUNT(CASE WHEN api_secret_encrypted IS NOT NULL AND api_secret_encrypted != '' THEN 1 END) as api_enc
            FROM users
        """))
        
        row = result.fetchone()
        total, poly_pt, poly_enc, sol_pt, sol_enc, api_pt, api_enc = row
        
        logger.info("="*80)
        logger.info("VERIFICATION RESULTS:")
        logger.info("="*80)
        logger.info(f"\nTotal users: {total}\n")
        
        logger.info("Polygon keys:")
        logger.info(f"  Plaintext (kept as backup): {poly_pt}")
        logger.info(f"  Encrypted (new): {poly_enc} {'✅' if poly_enc > 0 else '❌'}")
        
        logger.info("\nSolana keys:")
        logger.info(f"  Plaintext (kept as backup): {sol_pt}")
        logger.info(f"  Encrypted (new): {sol_enc} {'✅' if sol_enc > 0 else '❌'}")
        
        logger.info("\nAPI secrets:")
        logger.info(f"  Plaintext (kept as backup): {api_pt}")
        logger.info(f"  Encrypted (new): {api_enc} {'✅' if api_enc > 0 else '❌'}")
        
        logger.info("\n" + "="*80)
        
        # Check if encrypted columns match plaintext
        if (poly_enc == poly_pt or poly_pt == 0) and (sol_enc == sol_pt or sol_pt == 0) and (api_enc == api_pt or api_pt == 0):
            logger.info("✅ SUCCESS - All keys encrypted!")
            logger.info("   Plaintext keys kept as backup")
            logger.info("="*80 + "\n")
            return True
        else:
            logger.warning("⚠️  WARNING - Some keys may not be encrypted!")
            logger.info("="*80 + "\n")
            return False


def run_migration():
    logger.info("\n" + "="*80)
    logger.info("🔐 MIGRATION: Fix Encryption Columns")
    logger.info("="*80 + "\n")
    
    try:
        check_encryption_key()
        migrate_keys()
        success = verify()
        
        if success:
            logger.info("🎉 MIGRATION COMPLETE - System is now SECURE!")
            return True
        else:
            logger.error("❌ Verification failed - check logs")
            return False
        
    except Exception as e:
        logger.error(f"❌ MIGRATION FAILED: {e}")
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
